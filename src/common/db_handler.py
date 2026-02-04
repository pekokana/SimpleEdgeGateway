import sqlite3
import os

from src.common.config_loader import config

# DBパスをconfigから取得
DB_PATH = config.db_path


def migration_columns(cursor, target = None, columnlist = None):
    if target == None or columnlist == None:
        print(f"Parameter None.")
        return None
    # --- X3. マイグレーション：ホストへのカラム追加チェック ---
    cursor.execute(f"PRAGMA table_info({target})")
    columns = [row[1] for row in cursor.fetchall()]

    for col_name, col_type in columnlist:
        if col_name not in columns:
            print(f"Adding {col_name} column to {target} table...")
            cursor.execute(f"ALTER TABLE {target} ADD COLUMN {col_name} {col_type}")

def init_db():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA journal_mode=WAL;")
    cursor = conn.cursor()

    # --- 1. hostsテーブルの作成 ---
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS hosts (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        display_name TEXT NOT NULL,
        ip_address TEXT NOT NULL,
        port INTEGER DEFAULT 502,
        unit_id INTEGER DEFAULT 1,
        is_active INTEGER DEFAULT 1,
        status TEXT DEFAULT 'Unknown',
        last_seen DATETIME,
        updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
    )
    """)

    # --- 2. itemsテーブルの作成 ---
    # 初回作成時にアラート関連カラムも含めて定義
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS items (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        host_id INTEGER,
        tag_name TEXT NOT NULL,
        address INTEGER NOT NULL,
        polling_interval INTEGER DEFAULT 5, 
        last_value REAL,
        io_type TEXT DEFAULT 'register',   -- 'coil' or 'register'
        writable INTEGER DEFAULT 0,         -- 0: 読み取り専用, 1: 書き込み可
        updated_at DATETIME,
        next_poll_at DATETIME,        -- 次回収集時刻
        polling_lock TEXT,            -- poller識別子
        polling_lock_at DATETIME,     -- ロック取得時刻
        UNIQUE(host_id, tag_name),
        FOREIGN KEY(host_id) REFERENCES hosts(id)
    )
    """)

    # --- 4. historyテーブルの作成 ---
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            item_id INTEGER NOT NULL,
            value REAL,
            timestamp DATETIME DEFAULT (DATETIME('now', 'localtime')),
            FOREIGN KEY (item_id) REFERENCES items(id)
        )
    """)
    # -- 検索を速くするためのインデックス
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_history_item_id_timestamp ON history(item_id, timestamp)
    """)

    # --- 5. API経由でのPLCへの値書き込みログplc_write_logテーブルの作成 ---
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS plc_write_log (
            tag_name TEXT NOT NULL,
            value REAL,
            created_at DATETIME DEFAULT (DATETIME('now', 'localtime'))
        )
    """)

    # --- 6. Poller機能分割：MODBUSで読み込みしたデータ保持　raw_valuesテーブルの作成 ---
    cursor.execute("""
        CREATE TABLE raw_values (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            item_id INTEGER NOT NULL,
            value REAL,
            collected_at DATETIME DEFAULT (DATETIME('now', 'localtime')),
            processed_preprocess INTEGER DEFAULT 0,
            processed_history INTEGER DEFAULT 0,
            FOREIGN KEY(item_id) REFERENCES items(id)
        )
    """)
    # -- 検索を速くするためのインデックス
    cursor.execute("""
        CREATE INDEX idx_raw_unprocessed_preprocess ON raw_values(processed_preprocess, collected_at)
    """)
    cursor.execute("""
        CREATE INDEX idx_raw_unprocessed_history ON raw_values(processed_history, collected_at)
    """)

    # --- 7. triggers（発生条件）テーブル ---
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS triggers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            item_id INTEGER NOT NULL,
            name TEXT NOT NULL,
            enabled INTEGER DEFAULT 1,
            severity INTEGER DEFAULT 2, -- 将来用
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(item_id) REFERENCES items(id)
        )
    """)

    # --- 8. trigger_condition_groups（OR単位）テーブル ---
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS trigger_condition_groups (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            trigger_id INTEGER NOT NULL,
            group_type INTEGER DEFAULT 1, -- 1:AND（将来拡張用）
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(trigger_id) REFERENCES triggers(id)
        )
    """)


    # --- 9. 発生条件テーブル（trigger_conditions）テーブル ---
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS trigger_conditions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            group_id INTEGER NOT NULL,
            item_id INTEGER NOT NULL,              
            operator_id INTEGER NOT NULL,
            threshold REAL NOT NULL,
            eval_type INTEGER NOT NULL,             -- 1:last, 2:count, 3:duration
            eval_value INTEGER NOT NULL,            -- 回数 or 秒
            eval_window INTEGER NOT NULL,           -- 評価対象期間（秒）
            duration_mode INTEGER DEFAULT 1,        -- 1:continuous, 2:accumulate
            priority INTEGER DEFAULT 100,
            FOREIGN KEY(group_id) REFERENCES trigger_condition_groups(id),
            FOREIGN KEY(item_id) REFERENCES items(id),
            FOREIGN KEY(operator_id) REFERENCES operators(id)
        )
    """)


    # --- 10. 復旧条件テーブルOR単位（recovery_condition_groups） ---
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS recovery_condition_groups (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            trigger_id INTEGER NOT NULL,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(trigger_id) REFERENCES triggers(id)
        )
    """)

    # --- 11. 復旧条件テーブル（recovery_conditions）テーブル ---
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS recovery_conditions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            group_id INTEGER NOT NULL,
            item_id INTEGER NOT NULL,
            operator_id INTEGER NOT NULL,
            threshold REAL NOT NULL,
            eval_type INTEGER NOT NULL,
            eval_value INTEGER NOT NULL,
            eval_window INTEGER NOT NULL,
            duration_mode INTEGER DEFAULT 1, -- 1:continuous, 2:accumulate
            priority INTEGER DEFAULT 100,
            FOREIGN KEY(group_id) REFERENCES recovery_condition_groups(id),
            FOREIGN KEY(operator_id) REFERENCES operators(id)
        )
    """)

    # --- 3. event_logsテーブルの作成 ---
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS event_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            trigger_id INTEGER NOT NULL,
            condition_group_id INTEGER NOT NULL,
            condition_id INTEGER NOT NULL,
            item_id INTEGER NOT NULL,
            start_time DATETIME NOT NULL,
            end_time DATETIME,
            status TEXT NOT NULL,              -- 'active' / 'resolved'
            eval_type INTEGER NOT NULL,
            operator_id INTEGER NOT NULL,
            threshold REAL NOT NULL,
            eval_window INTEGER NOT NULL,
            actual_value REAL,                 -- last 用
            actual_count INTEGER,              -- count 用
            actual_duration INTEGER,           -- duration 用
            acked_at DATETIME,
            acked_by TEXT,
            FOREIGN KEY(trigger_id) REFERENCES triggers(id),
            FOREIGN KEY(condition_group_id) REFERENCES trigger_condition_groups(id),
            FOREIGN KEY(condition_id) REFERENCES trigger_conditions(id),
            FOREIGN KEY(item_id) REFERENCES items(id),
            CHECK (
                (eval_type = 1 AND actual_value IS NOT NULL AND actual_count IS NULL AND actual_duration IS NULL)
            OR (eval_type = 2 AND actual_value IS NULL AND actual_count IS NOT NULL AND actual_duration IS NULL)
            OR (eval_type = 3 AND actual_value IS NULL AND actual_count IS NULL AND actual_duration IS NOT NULL)
            )
        )
    """)

    # -- 検索を速くするためのインデックス
    cursor.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS uq_event_logs_active ON event_logs(trigger_id) WHERE status = 'active'
    """)

    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_event_logs_active ON event_logs(status, trigger_id)
    """)

    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_event_logs_start_time ON event_logs(start_time DESC)
    """)

    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_event_logs_item ON event_logs(item_id, start_time DESC)
    """)

    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_event_logs_ack ON event_logs(acked_at)
    """)

    # --- 12. operators（演算子マスタ） ---
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS operators (
            id INTEGER PRIMARY KEY,
            symbol TEXT NOT NULL,
            description TEXT
        )
    """)

    # 初期データ（INSERT OR IGNORE）
    cursor.executemany("""
        INSERT OR IGNORE INTO operators (id, symbol, description)
        VALUES (?, ?, ?)
    """, [
        (1, ">",  "greater than"),
        (2, ">=", "greater or equal"),
        (3, "<",  "less than"),
        (4, "<=", "less or equal"),
        (5, "==", "equal"),
        (6, "!=", "not equal"),
    ])


    # --- X1. マイグレーション：アイテムテーブルへのカラム追加チェック ---
    # cursor.execute("PRAGMA table_info(items)")
    # columns = [row[1] for row in cursor.fetchall()]
    # 必要カラムのチェックと追加
    migrations = [
        ("host_id", "INTEGER DEFAULT 1"),
        ("address", "INTEGER DEFAULT 0"),
        ("alarm_threshold", "REAL DEFAULT 100.0"),
        ("alarm_enabled", "INTEGER DEFAULT 0"),  # 0=無効, 1=有効
        ("polling_interval", "INTEGER DEFAULT 5"),
        ("io_type", "TEXT DEFAULT 'register'"),   # 'coil' or 'register'
        ("writable", "INTEGER DEFAULT 0"),         # 0: 監視のみ, 1: 操作可
        ("next_poll_at", "DATETIME"), # 次回収集時刻
        ("polling_lock", "TEXT"), # poller識別子
        ("polling_lock_at", "DATETIME"), # ロック取得時刻
    ]
    migration_columns(cursor=cursor, target="items", columnlist=migrations)
    # for col_name, col_type in migrations:
    #     if col_name not in columns:
    #         print(f"Adding {col_name} column to items table...")
    #         cursor.execute(f"ALTER TABLE items ADD COLUMN {col_name} {col_type}")

    # --- X2. マイグレーション：イベントログテーブルへのカラム追加チェック ---
    # cursor.execute("PRAGMA table_info(event_logs)")
    # columns = [row[1] for row in cursor.fetchall()]
    # 必要カラムのチェックと追加
    migrations = [
        ("acked_at", "TEXT"),
        ("acked_by", "TEXT")
    ]
    migration_columns(cursor=cursor, target="event_logs", columnlist=migrations)
    # for col_name, col_type in migrations:
    #     if col_name not in columns:
    #         print(f"Adding {col_name} column to event_logs table...")
    #         cursor.execute(f"ALTER TABLE event_logs ADD COLUMN {col_name} {col_type}")

    # --- X3. マイグレーション：ホストへのカラム追加チェック ---
    # 必要カラムのチェックと追加
    migrations = [
        ("last_seen", "DATETIME")
    ]
    migration_columns(cursor=cursor, target="hosts", columnlist=migrations)

    conn.commit()
    conn.close()
    print(f"Database initialized and migrated at: {DB_PATH}")

if __name__ == "__main__":
    init_db()