import asyncio
import aiosqlite
import uuid
from pymodbus.client import AsyncModbusTcpClient
import logging

from pymodbus.logging import Log
Log.setLevel(logging.CRITICAL)

from src.common.config_loader import config

DB_PATH = config.db_path
POLL_LOCK_TIMEOUT_SEC = 10


class ModbusPoller:
    def __init__(self):
        self.running = True
        self.poller_id = str(uuid.uuid4())

    # -------------------------
    # DB Access
    # -------------------------

    async def fetch_hosts(self):
        async with aiosqlite.connect(DB_PATH) as db:
            db.row_factory = aiosqlite.Row
            cur = await db.execute(
                "SELECT * FROM hosts WHERE is_active = 1"
            )
            return await cur.fetchall()

    async def fetch_due_items(self, host_id):
        async with aiosqlite.connect(DB_PATH) as db:
            db.row_factory = aiosqlite.Row
            cur = await db.execute("""
                SELECT *
                FROM items
                WHERE host_id = ?
                  AND (next_poll_at IS NULL
                       OR next_poll_at <= DATETIME('now', 'localtime'))
            """, (host_id,))
            return await cur.fetchall()

    async def acquire_poll_lock(self, item_id):
        async with aiosqlite.connect(DB_PATH) as db:
            cur = await db.execute("""
                UPDATE items
                SET polling_lock = ?,
                    polling_lock_at = DATETIME('now', 'localtime')
                WHERE id = ?
                  AND (
                        polling_lock IS NULL
                        OR polling_lock_at < DATETIME('now', ?)
                  )
            """, (
                self.poller_id,
                item_id,
                f'-{POLL_LOCK_TIMEOUT_SEC} seconds'
            ))
            await db.commit()
            return cur.rowcount == 1

    async def release_poll_lock(self, item_id, interval_sec):
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute("""
                UPDATE items
                SET polling_lock = NULL,
                    polling_lock_at = NULL,
                    next_poll_at = DATETIME(
                        'now', '+' || ? || ' seconds'
                    )
                WHERE id = ?
                  AND polling_lock = ?
            """, (interval_sec, item_id, self.poller_id))
            await db.commit()

    async def insert_raw_value(self, item_id, value):
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute("""
                INSERT INTO raw_values (item_id, value)
                VALUES (?, ?)
            """, (item_id, value))
            await db.commit()

    # -------------------------
    # Modbus
    # -------------------------

    async def read_modbus_value(self, client, item):
        try:
            if item["io_type"] == "coil":
                res = await client.read_coils(item["address"], count=1)
                return res.bits[0] if not res.isError() else None
            else:
                res = await client.read_holding_registers(item["address"], count=1)
                return res.registers[0] if not res.isError() else None
        except Exception:
            return None

    # -------------------------
    # Main Loop
    # -------------------------

    async def poll_host(self, host):
        client = AsyncModbusTcpClient(
            host["ip_address"],
            port=host["port"]
        )

        while self.running:
            try:
                if not client.connected:
                    if not await client.connect():
                        await asyncio.sleep(3)
                        continue

                items = await self.fetch_due_items(host["id"])

                for item in items:
                    locked = await self.acquire_poll_lock(item["id"])
                    if not locked:
                        continue

                    try:
                        val = await self.read_modbus_value(client, item)
                        if val is not None:
                            await self.insert_raw_value(item["id"], val)
                    finally:
                        await self.release_poll_lock(
                            item["id"],
                            item["polling_interval"]
                        )

            except Exception as e:
                print(f"[PollerError] {e}")
                client.close()

            await asyncio.sleep(0.1)

    async def run(self):
        hosts = await self.fetch_hosts()
        if not hosts:
            print("WARNING: No active hosts.")
            return

        tasks = [self.poll_host(h) for h in hosts]
        await asyncio.gather(*tasks)


def main():
    poller = ModbusPoller()
    try:
        asyncio.run(poller.run())
    except KeyboardInterrupt:
        poller.running = False


if __name__ == "__main__":
    main()
