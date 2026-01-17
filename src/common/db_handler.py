import sqlite3
import os

DB_PATH = "data/gateway.sqlite"

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
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS items (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        tag_name TEXT UNIQUE NOT NULL,
        last_value REAL,
        threshold REAL DEFAULT 0.0,
        updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
    )
    """)

    # --- 3. マイグレーション：itemsテーブルに host_id カラムを追加 ---
    # 現在のカラム一覧を取得
    cursor.execute("PRAGMA table_info(items)")
    columns = [row[1] for row in cursor.fetchall()]

    if "host_id" not in columns:
        print("Adding host_id column to items table...")
        # 既存のデータがある場合を考慮し、デフォルト値1（最初のPLC）などを指定
        cursor.execute("ALTER TABLE items ADD COLUMN host_id INTEGER DEFAULT 1")
    
    # ついでに Modbus用のアドレスカラムなども無ければ追加しておくと後が楽です
    if "address" not in columns:
        cursor.execute("ALTER TABLE items ADD COLUMN address INTEGER DEFAULT 0")

    conn.commit()
    conn.close()
    print(f"Database initialized and migrated at: {DB_PATH}")

if __name__ == "__main__":
    init_db()