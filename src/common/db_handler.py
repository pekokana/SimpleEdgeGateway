import sqlite3
import os

from src.common.config_loader import config

# DBパスをconfigから取得
DB_PATH = config.db_path

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
        alarm_threshold REAL DEFAULT 100.0,
        alarm_enabled INTEGER DEFAULT 0,
        updated_at DATETIME,
        FOREIGN KEY(host_id) REFERENCES hosts(id)
    )
    """)

    # --- 3. event_logsテーブルの作成 ---
    cursor.execute("""
    CREATE TABLE event_logs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        item_id INTEGER,          -- どのタグか
        start_time DATETIME,      -- 発生時刻
        end_time DATETIME,        -- 復旧時刻（発生時はNULL）
        trigger_value REAL,       -- 発生時の値
        threshold_value REAL,     -- その時のしきい値
        status TEXT               -- 'active' (継続中) or 'resolved' (復旧済み)
    )
    """)

    # --- X. マイグレーション：既存テーブルへのカラム追加チェック ---
    cursor.execute("PRAGMA table_info(items)")
    columns = [row[1] for row in cursor.fetchall()]

    # 必要カラムのチェックと追加
    migrations = [
        ("host_id", "INTEGER DEFAULT 1"),
        ("address", "INTEGER DEFAULT 0"),
        ("alarm_threshold", "REAL DEFAULT 100.0"),
        ("alarm_enabled", "INTEGER DEFAULT 0"),  # 0=無効, 1=有効
        ("polling_interval", "INTEGER DEFAULT 5")
    ]

    for col_name, col_type in migrations:
        if col_name not in columns:
            print(f"Adding {col_name} column to items table...")
            cursor.execute(f"ALTER TABLE items ADD COLUMN {col_name} {col_type}")

    conn.commit()
    conn.close()
    print(f"Database initialized and migrated at: {DB_PATH}")

if __name__ == "__main__":
    init_db()