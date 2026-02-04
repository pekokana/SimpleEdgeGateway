import asyncio
import aiosqlite
from src.common.config_loader import config

DB_PATH = config.db_path


OPERATORS = {
    1: lambda v, t: v > t,
    2: lambda v, t: v >= t,
    3: lambda v, t: v < t,
    4: lambda v, t: v <= t,
    5: lambda v, t: v == t,
    6: lambda v, t: v != t,
}


class TriggerWorker:

    async def fetch_triggers(self, db):
        db.row_factory = aiosqlite.Row
        cur = await db.execute("""
            SELECT t.id AS trigger_id, t.item_id
            FROM triggers t
            WHERE t.enabled = 1
        """)
        return await cur.fetchall()

    async def fetch_groups(self, db, trigger_id, recovery=False):
        table = "recovery_condition_groups" if recovery else "trigger_condition_groups"
        cur = await db.execute(f"""
            SELECT id FROM {table}
            WHERE trigger_id = ?
        """, (trigger_id,))
        return await cur.fetchall()

    async def fetch_conditions(self, db, group_id, recovery=False):
        table = "recovery_conditions" if recovery else "trigger_conditions"
        cur = await db.execute(f"""
            SELECT
                id AS condition_id,
                item_id,
                operator_id,
                threshold,
                eval_type,
                eval_value,
                eval_window,
                duration_mode,
                priority
            FROM {table}
            WHERE group_id = ?
        """, (group_id,))
        return await cur.fetchall()


    async def has_active_event(self, db, trigger_id):
        cur = await db.execute("""
            SELECT id FROM event_logs
            WHERE trigger_id = ?
              AND status = 'active'
        """, (trigger_id,))
        return await cur.fetchone()

    async def create_event(self, db, trigger_id, group_result):
        pc = group_result["primary_condition"]

        await db.execute("""
            INSERT INTO event_logs (
                trigger_id,
                condition_group_id,
                condition_id,
                item_id,
                start_time,
                status,
                eval_type,
                operator_id,
                threshold,
                eval_window,
                actual_value,
                actual_count,
                actual_duration
            ) VALUES (
                ?, ?, ?, ?, DATETIME('now','localtime'), 'active',
                ?, ?, ?, ?, ?, ?, ?
            )
        """, (
            trigger_id,
            group_result["group_id"],
            pc["condition_id"],
            pc["item_id"],
            pc["eval_type"],
            pc["operator_id"],
            pc["threshold"],
            pc["eval_window"],
            pc["actual_value"],
            pc["actual_count"],
            pc["actual_duration"],
        ))

    # priority昇順 → eval_type昇順
    def select_primary_condition(self, conditions):
        return sorted(
            conditions,
            key=lambda c: (c["priority"], c["eval_type"])
        )[0]


    async def resolve_event(self, db, trigger_id, group_result):
        await db.execute("""
            UPDATE event_logs
            SET end_time = DATETIME('now','localtime'),
                status = 'resolved'
            WHERE trigger_id = ?
              AND status = 'active'
        """, (trigger_id,))

    async def eval_condition(self, db, cond):
        op = self.op_symbol(cond["operator_id"])
        item_id = cond["item_id"]

        if cond["eval_type"] == 1:  # last
            cur = await db.execute(
                "SELECT last_value FROM items WHERE id = ?",
                (item_id,)
            )
            row = await cur.fetchone()
            if not row:
                return None

            matched = OPERATORS[cond["operator_id"]](row["last_value"], cond["threshold"])
            return {
                "matched": matched,
                "condition_id": cond["condition_id"],
                "item_id": cond["item_id"],
                "priority": cond["priority"],
                "eval_type": cond["eval_type"],
                "operator_id": cond["operator_id"],
                "threshold": cond["threshold"],
                "eval_window": cond["eval_window"],
                "actual_value": row["last_value"],
                "actual_count": None,
                "actual_duration": None,
            }


        elif cond["eval_type"] == 2:  # count
            cur = await db.execute(f"""
                SELECT COUNT(*) AS cnt
                FROM history
                WHERE item_id = ?
                AND timestamp >= DATETIME('now','localtime', '-' || ? || ' seconds')
                AND value {op} ?
            """, (item_id, cond["eval_window"], cond["threshold"]))
            row = await cur.fetchone()

            matched = row["cnt"] >= cond["eval_value"]
            return {
                "matched": matched,
                "condition_id": cond["condition_id"],
                "item_id": cond["item_id"],
                "priority": cond["priority"],
                "eval_type": cond["eval_type"],
                "operator_id": cond["operator_id"],
                "threshold": cond["threshold"],
                "eval_window": cond["eval_window"],
                "actual_value": None,
                "actual_count": row["cnt"],
                "actual_duration": None,
            }

        elif cond["eval_type"] == 3:  # duration
            if cond["duration_mode"] == 1:
                duration = await self.eval_duration_continuous(db, cond, op)
            else:
                duration = await self.eval_duration_accumulate(db, cond, op)

            matched = duration >= cond["eval_value"]
            return {
                "matched": matched,
                "condition_id": cond["condition_id"],
                "item_id": cond["item_id"],
                "priority": cond["priority"],
                "eval_type": cond["eval_type"],
                "operator_id": cond["operator_id"],
                "threshold": cond["threshold"],
                "eval_window": cond["eval_window"],
                "actual_value": None,
                "actual_count": None,
                "actual_duration": duration,
            }



    # 連続 duration
    async def eval_duration_continuous(self, db, cond, op):
        item_id = cond["item_id"]

        cur = await db.execute(f"""
            SELECT timestamp
            FROM history
            WHERE item_id = ?
            AND timestamp >= DATETIME('now','localtime', '-' || ? || ' seconds')
            AND NOT (value {op} ?)
            ORDER BY timestamp DESC
            LIMIT 1
        """, (item_id, cond["eval_window"], cond["threshold"]))
        row = await cur.fetchone()

        break_ts = row["timestamp"] if row else None

        cur = await db.execute("""
            SELECT
                strftime('%s', DATETIME('now','localtime'))
            - strftime('%s', COALESCE(?, DATETIME('now','localtime', '-' || ? || ' seconds')))
                AS duration_sec
        """, (break_ts, cond["eval_window"]))
        row = await cur.fetchone()

        return row["duration_sec"] or 0

    # 連続 duration 実装
    async def eval_duration_accumulate(self, db, cond, op):
        item_id = cond["item_id"]

        cur = await db.execute(f"""
            WITH ordered AS (
            SELECT
                timestamp,
                value,
                LEAD(timestamp) OVER (ORDER BY timestamp) AS next_ts
            FROM history
            WHERE item_id = ?
                AND timestamp >= DATETIME('now','localtime', '-' || ? || ' seconds')
            )
            SELECT
            SUM(
                CASE
                WHEN value {op} ?
                THEN strftime('%s', COALESCE(next_ts, DATETIME('now','localtime')))
                    - strftime('%s', timestamp)
                ELSE 0
                END
            ) AS duration_sec
            FROM ordered
        """, (item_id, cond["eval_window"], cond["threshold"]))
        row = await cur.fetchone()

        return row["duration_sec"] or 0

    async def eval_groups(self, db, trigger_id, recovery=False):
        groups = await self.fetch_groups(db, trigger_id, recovery)

        for g in groups:  # OR
            conditions = await self.fetch_conditions(db, g["id"], recovery)
            if not conditions:
                continue

            results = []
            all_matched = True

            for c in conditions:
                result = await self.eval_condition(db, c)
                if not result or not result["matched"]:
                    all_matched = False
                    break
                results.append(result)

            if all_matched:
                primary = self.select_primary_condition(results)
                return {
                    "group_id": g["id"],
                    "conditions": results,
                    "primary_condition": primary
                }

        return None


    def op_symbol(self, operator_id):
        return {
            1: ">",
            2: ">=",
            3: "<",
            4: "<=",
            5: "==",
            6: "!=",
        }[operator_id]

    async def run(self):
        while True:
            async with aiosqlite.connect(DB_PATH) as db:
                triggers = await self.fetch_triggers(db)

                for t in triggers:
                    trigger_id = t["trigger_id"]
                    item_id = t["item_id"]

                    cur = await db.execute("""
                        SELECT last_value FROM items WHERE id = ?
                    """, (item_id,))
                    row = await cur.fetchone()
                    if not row:
                        continue

                    active = await self.has_active_event(db, trigger_id)

                    if not active:
                        result = await self.eval_groups(db, trigger_id, recovery=False)
                        if result:
                            await self.create_event(db, trigger_id, result)

                    else:
                        recovered = await self.eval_groups(db, trigger_id, recovery=True)
                        if recovered:
                            await self.resolve_event(db, trigger_id)


                await db.commit()

            await asyncio.sleep(1)


async def main():
    worker = TriggerWorker()
    await worker.run()


if __name__ == "__main__":
    asyncio.run(main())
