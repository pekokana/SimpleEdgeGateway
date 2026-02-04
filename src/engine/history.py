import asyncio
import aiosqlite
from src.common.config_loader import config

DB_PATH = config.db_path


class HistoryWorker:

    FETCH_LIMIT = 100

    async def run(self):
        while True:
            async with aiosqlite.connect(DB_PATH) as db:
                db.row_factory = aiosqlite.Row
                cur = await db.execute("""
                    SELECT *
                    FROM raw_values
                    WHERE processed_history = 0
                    ORDER BY collected_at
                    LIMIT ?
                """, (self.FETCH_LIMIT,))
                rows = await cur.fetchall()

                if not rows:
                    await asyncio.sleep(1)
                    continue

                for r in rows:
                    await db.execute("""
                        INSERT INTO history (item_id, value)
                        VALUES (?, ?)
                    """, (r["item_id"], r["value"]))

                    await db.execute("""
                        UPDATE items
                        SET last_value = ?, updated_at = DATETIME('now','localtime')
                        WHERE id = ?
                    """, (r["value"], r["item_id"]))

                    await db.execute("""
                        UPDATE raw_values
                        SET processed_history = 1
                        WHERE id = ?
                    """, (r["id"],))

                await db.commit()
