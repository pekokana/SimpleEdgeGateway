import asyncio
import aiosqlite
from pymodbus.client import AsyncModbusTcpClient
from datetime import datetime
import logging

from pymodbus.logging import Log
Log.setLevel(logging.CRITICAL)

from src.common.config_loader import config

# DBパスをconfigから取得
DB_PATH = config.db_path

class ModbusPoller:
    def __init__(self):
        self.running = True

    async def update_host_status(self, host_id, status):
        """ホストのOnline/Offline状態をDBに書き込む"""
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute(
                "UPDATE hosts SET status = ?, updated_at = datetime('now', 'localtime') WHERE id = ?",
                (status, host_id)
            )
            await db.commit()

    async def fetch_hosts(self):
        async with aiosqlite.connect(DB_PATH) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute("SELECT * FROM hosts WHERE is_active = 1")
            return await cursor.fetchall()

    async def fetch_target_items(self, host_id, active_ids):
        """収集周期に達した、または現在アラート中のアイテムを取得"""
        async with aiosqlite.connect(DB_PATH) as db:
            db.row_factory = aiosqlite.Row
            # SQLのIN句用にIDリストを文字列化 (空の場合は存在しないID -1 を指定)
            ids_str = ",".join(map(str, active_ids)) if active_ids else "-1"
            
            query = f"""
                SELECT * FROM items 
                WHERE host_id = ? 
            """
            cursor = await db.execute(query, (host_id,))
            return await cursor.fetchall()

    async def read_modbus_value(self, client, address):
        try:
            response = await client.read_holding_registers(address, count=1)
            if response.isError():
                return None
            return response.registers[0]
        except Exception:
            return None

    async def poll_host(self, host_config):
        host_id = host_config['id']
        host_name = host_config['display_name']
        active_alarms = {} 
        last_host_status = None 

        client = AsyncModbusTcpClient(host_config['ip_address'], port=host_config['port'])

        while self.running:
            try:
                if not client.connected:
                    connected = await client.connect()
                else:
                    connected = True

                if not connected:
                    print(f"DEBUG: {host_name} への接続に失敗しています")
                    await asyncio.sleep(5)
                    continue
                
                # --- デバッグポイント1: アイテムが取得できているか ---
                items = await self.fetch_target_items(host_id, list(active_alarms.keys()))

                poll_results = [] # 今回の更新分を溜めるリスト

                for item in items:
                    item_id = item['id']
                    # --- デバッグポイント2: 実際に読み出しが行われているか ---
                    val = await self.read_modbus_value(client, item['address'])
                    # print(f"DEBUG: 読み出し実行 - Tag: {item['tag_name']}, Address: {item['address']}, Value: {val}")
                    
                    if val is not None:
                        # await self.update_item_value(item_id, val)
                        # 後の履歴判定のために前回値(last_value)も一緒にリストへ
                        poll_results.append((item['id'], val, item['last_value']))

                        # アラート判定
                        threshold = item['alarm_threshold']
                        enabled = item['alarm_enabled']
                        is_currently_alarm = (enabled == 1 and val >= threshold)

                        if is_currently_alarm and item_id not in active_alarms:
                            event_id = await self.create_event_log(item_id, val, threshold)
                            active_alarms[item_id] = event_id
                            print(f"⚠️ ALARM START: {item['tag_name']}")
                        elif not is_currently_alarm and item_id in active_alarms:
                            old_event_id = active_alarms.pop(item_id)
                            await self.close_event_log(old_event_id)
                            print(f"✅ ALARM RESOLVED: {item['tag_name']}")
                    else:
                        print(f"DEBUG: {item['tag_name']} の読み出しが None です")

                # 1台分のループが終わったら「一括」でDBに書き込む
                await self.update_items_bulk(poll_results)
                # print(f"DEBUG: {host_name} - {len(poll_results)}件を更新しました")                

            except Exception as e:
                print(f"SYSTEM ERROR: {e}")
                client.close()
            
            await asyncio.sleep(1)


    async def create_event_log(self, item_id, val, threshold):
        async with aiosqlite.connect(DB_PATH) as db:
            cursor = await db.execute(
                """INSERT INTO event_logs (item_id, start_time, trigger_value, threshold_value, status) 
                   VALUES (?, DATETIME('now', 'localtime'), ?, ?, 'active')""",
                (item_id, val, threshold)
            )
            event_id = cursor.lastrowid
            await db.commit()
            return event_id

    async def close_event_log(self, event_id):
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute(
                """UPDATE event_logs 
                   SET end_time = DATETIME('now', 'localtime'), status = 'resolved' 
                   WHERE id = ? AND status = 'active'""",
                (event_id,)
            )
            await db.commit()

    async def run(self):
        hosts = await self.fetch_hosts()
        if not hosts:
            print("WARNING: No active hosts found.")
            return
            
        tasks = [self.poll_host(h) for h in hosts]
        await asyncio.gather(*tasks)

    async def update_item_value(self, item_id, new_value):
        async with aiosqlite.connect(DB_PATH) as db:
            db.row_factory = aiosqlite.Row
            
            # 1. DBから現在の値(前回保存された値)を取得
            cursor = await db.execute("SELECT last_value FROM items WHERE id = ?", (item_id,))
            row = await cursor.fetchone()
            
            # 前回値と異なる場合のみ履歴(history)に保存
            if row is None or row["last_value"] != new_value:
                # 履歴テーブルへ挿入
                await db.execute(
                    "INSERT INTO history (item_id, value) VALUES (?, ?)",
                    (item_id, new_value)
                )
                # print(f"DEBUG: Value changed. History saved for Item ID {item_id}: {new_value}")

            # 最新値の更新（これは変化に関わらず、時刻を更新するために毎回行うのが一般的）
            await db.execute(
                "UPDATE items SET last_value = ?, updated_at = DATETIME('now', 'localtime') WHERE id = ?",
                (new_value, item_id)
            )
            await db.commit()

    async def update_items_bulk(self, results):
        """
        results: [(item_id, val, old_val), ...] のリスト
        """
        if not results:
            return

        async with aiosqlite.connect(DB_PATH) as db:
            # 高速化のための設定
            await db.execute("PRAGMA journal_mode=WAL") # WALモードを有効化
            await db.execute("PRAGMA synchronous=NORMAL")

            for item_id, new_value, old_value in results:
                # 値が変化した時のみ履歴へ
                if old_value != new_value:
                    await db.execute(
                        "INSERT INTO history (item_id, value) VALUES (?, ?)",
                        (item_id, new_value)
                    )
                # 最新値の更新
                await db.execute(
                    "UPDATE items SET last_value = ?, updated_at = DATETIME('now', 'localtime') WHERE id = ?",
                    (new_value, item_id)
                )
            await db.commit()

def main():
    poller = ModbusPoller()
    try:
        asyncio.run(poller.run())
    except KeyboardInterrupt:
        poller.running = False

if __name__ == "__main__":
    main()