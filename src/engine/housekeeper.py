import asyncio
import aiosqlite
from src.common.config_loader import config

DB_PATH = config.db_path


class Housekeeper:

    FETCH_LIMIT = 1000
    RETENTION_DAYS = 7   # 保持期間（必要に応じて変更）

    async def cleanup_raw_values(self):
        async with aiosqlite.connect(DB_PATH) as db:
            cur = await db.execute(f"""
                DELETE FROM raw_values
                WHERE processed_preprocess = 1
                  AND processed_history = 1
                  AND collected_at < DATETIME('now', '-{self.RETENTION_DAYS} days')
                LIMIT ?
            """, (self.FETCH_LIMIT,))

            deleted = cur.rowcount
            await db.commit()
            return deleted

    async def run(self):
        while True:
            deleted = await self.cleanup_raw_values()

            if deleted == 0:
                # 削除対象がなければ少し休む
                await asyncio.sleep(60)
            else:
                print(f"[housekeeper] deleted raw_values: {deleted}")


async def main():
    hk = Housekeeper()
    await hk.run()


if __name__ == "__main__":
    asyncio.run(main())
