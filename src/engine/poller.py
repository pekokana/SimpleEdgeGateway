import asyncio
import aiosqlite
from pymodbus.client import AsyncModbusTcpClient
from datetime import datetime

# 1. DB名をこれまでの設定と合わせる (.db か .sqlite か確認してください)
DB_PATH = "data/gateway.sqlite"

class ModbusPoller:
    def __init__(self):
        self.running = True

    async def fetch_hosts(self):
        async with aiosqlite.connect(DB_PATH) as db:
            db.row_factory = aiosqlite.Row
            # 念のためデータがあるか確認
            cursor = await db.execute("SELECT * FROM hosts WHERE is_active = 1")
            rows = await cursor.fetchall()
            print(f"DEBUG: Found {len(rows)} active hosts in DB.")
            return rows

    async def fetch_items_for_host(self, host_id):
        async with aiosqlite.connect(DB_PATH) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute("SELECT * FROM items WHERE host_id = ?", (host_id,))
            return await cursor.fetchall()

    async def poll_host(self, host_config):
        host_name = host_config['display_name']
        ip = host_config['ip_address']
        port = host_config['port']
        unit_id = host_config['unit_id']

        print(f"[*] Starting poller for {host_name} ({ip}:{port})")
        
        # clientをループの外で作る（接続を維持するため）
        client = AsyncModbusTcpClient(ip, port=port)

        while self.running:
            try:
                # 2. 非同期接続は await が必要
                if not client.connected:
                    connected = await client.connect()
                    if not connected:
                        print(f"[!] Connection failed to {host_name} ({ip}:{port})")
                        await asyncio.sleep(5)
                        continue
                
                print(f"DEBUG: Connected to {host_name}, fetching items...")
                items = await self.fetch_items_for_host(host_config['id'])
                
                if not items:
                    print(f"DEBUG: No items found for {host_name} in DB.")

                for item in items:
                    # 3. 読み取りも await が必須
                    res = await client.read_holding_registers(
                        item['address'], 1
                    )
                    
                    if not res.isError():
                        val = res.registers[0]
                        now = datetime.now().strftime("%H:%M:%S")
                        print(f"[{now}] {host_name} | {item['tag_name']}: {val}")
                        # TODO: ここでDBに last_value を書き戻す
                    else:
                        print(f"[!] Error reading {item['tag_name']} from {host_name}")
                
            except Exception as e:
                print(f"[!!] Poller Error ({host_name}): {e}")
            
            await asyncio.sleep(5) # 5秒間隔

    async def run(self):
        hosts = await self.fetch_hosts()
        if not hosts:
            print("WARNING: No active hosts found in Database. Please add a host via Web UI.")
            return
            
        tasks = [self.poll_host(h) for h in hosts]
        await asyncio.gather(*tasks)

if __name__ == "__main__":
    poller = ModbusPoller()
    try:
        asyncio.run(poller.run())
    except KeyboardInterrupt:
        print("\nStopping Poller...")
        poller.running = False