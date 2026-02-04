import asyncio
import aiosqlite
from src.common.config_loader import config

DB_PATH = config.db_path


class PreprocessingWorker:

    FETCH_LIMIT = 100

    async def fetch_raw(self):
        """
        未処理の raw_values を items と JOIN して取得
        """
        async with aiosqlite.connect(DB_PATH) as db:
            db.row_factory = aiosqlite.Row
            cur = await db.execute("""
                SELECT
                    rv.id            AS raw_id,
                    rv.item_id,
                    rv.value,
                    rv.collected_at,
                    i.alarm_enabled,
                    i.alarm_threshold
                FROM raw_values rv
                JOIN items i ON rv.item_id = i.id
                WHERE rv.processed_preprocess = 0
                ORDER BY rv.collected_at
                LIMIT ?
            """, (self.FETCH_LIMIT,))
            return await cur.fetchall()

    async def has_active_event(self, db, item_id):
        """
        対象 item に active なイベントが存在するか
        """
        cur = await db.execute("""
            SELECT id FROM event_logs
            WHERE item_id = ?
              AND status = 'active'
            LIMIT 1
        """, (item_id,))
        return await cur.fetchone()

    async def close_active_event(self, db, item_id):
        """
        active なイベントを resolved にする
        """
        await db.execute("""
            UPDATE event_logs
            SET
                end_time = DATETIME('now', 'localtime'),
                status   = 'resolved'
            WHERE item_id = ?
              AND status = 'active'
        """, (item_id,))

    async def create_event(self, db, item_id, value, threshold):
        """
        新規アラームイベント作成
        """
        await db.execute("""
            INSERT INTO event_logs
            (item_id, start_time, trigger_value, threshold_value, status)
            VALUES (?, DATETIME('now','localtime'), ?, ?, 'active')
        """, (item_id, value, threshold))

    async def process(self):
        """
        メインループ
        """
        while True:
            raws = await self.fetch_raw()

            if not raws:
                await asyncio.sleep(1)
                continue

            async with aiosqlite.connect(DB_PATH) as db:
                for r in raws:
                    item_id = r["item_id"]
                    value = r["value"]
                    enabled = r["alarm_enabled"]
                    threshold = r["alarm_threshold"]

                    # ---- トリガ判定 ----
                    is_alarm = enabled == 1 and value >= threshold

                    active_event = await self.has_active_event(db, item_id)

                    # アラーム開始
                    if is_alarm and not active_event:
                        await self.create_event(db, item_id, value, threshold)

                    # アラーム復旧
                    elif not is_alarm and active_event:
                        await self.close_active_event(db, item_id)

                    # ---- raw_values を preprocessing 済みに ----
                    await db.execute("""
                        UPDATE raw_values
                        SET processed_preprocess = 1
                        WHERE id = ?
                    """, (r["raw_id"],))

                await db.commit()


async def main():
    worker = PreprocessingWorker()
    await worker.process()


if __name__ == "__main__":
    asyncio.run(main())
