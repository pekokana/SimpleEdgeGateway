from fastapi import APIRouter, HTTPException
import aiosqlite
from datetime import datetime
import time

from src.common.config_loader import config

# DBパスをconfigから取得
DB_PATH = config.db_path

# Routerの作成 (URLの接頭辞を /api/v1 に固定)
router = APIRouter(prefix="/api/v1", tags=["External API"])

@router.get("/latest")
async def api_latest():
    """SCADA向け：最新値一括取得"""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute("""
            SELECT i.tag_name, i.last_value, i.updated_at, h.display_name as host_name
            FROM items i
            JOIN hosts h ON i.host_id = h.id
        """)
        rows = await cursor.fetchall()
        
        data = [
            {
                "tag": r["tag_name"], 
                "value": r["last_value"], 
                "host": r["host_name"],
                "updated_at": r["updated_at"]
            } for r in rows
        ]
        return {
            "timestamp": datetime.now().isoformat(),
            "data": data
        }

@router.get("/alerts/active")
async def api_active_alerts():
    """SCADA向け：現在発生中のアラームのみ取得"""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute("""
            SELECT e.*, i.tag_name 
            FROM event_logs e
            JOIN items i ON e.item_id = i.id
            WHERE e.status = 'active'
        """)
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]

@router.get("/history/{tag_name}")
async def api_tag_history(tag_name: str, hours: int = 24):
    """外部解析向け：特定タグの過去履歴を取得"""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        
        # まずはタグが存在するかチェック
        cursor = await db.execute("SELECT id FROM items WHERE tag_name = ?", (tag_name,))
        item = await cursor.fetchone()
        if not item:
            raise HTTPException(status_code=404, detail="Tag not found")
            
        item_id = item["id"]
        
        # 履歴データを取得（DATETIME関数で時間を遡る）
        cursor = await db.execute("""
            SELECT timestamp, value 
            FROM history 
            WHERE item_id = ? 
              AND timestamp >= DATETIME('now', 'localtime', ?)
            ORDER BY timestamp ASC
        """, (item_id, f"-{hours} hours"))
        
        rows = await cursor.fetchall()
        
        return {
            "tag": tag_name,
            "period_hours": hours,
            "count": len(rows),
            "values": [[r["timestamp"], r["value"]] for r in rows]
        }

# --- A. ヘルスチェック ---
@router.get("/health")
async def api_health():
    """SCADA向け：システム健全性チェック"""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        # 最新のデータ更新時刻を取得
        cursor = await db.execute("SELECT MAX(updated_at) as last_update FROM items")
        row = await cursor.fetchone()
        
        last_update = row["last_update"]
        is_poller_alive = False
        
        if last_update:
            # 最終更新が10秒以内ならPoller生存とみなす
            last_ts = datetime.strptime(last_update, "%Y-%m-%d %H:%M:%S").timestamp()
            if time.time() - last_ts < 10:
                is_poller_alive = True
        
        return {
            "status": "ok" if is_poller_alive else "degraded",
            "poller_active": is_poller_alive,
            "database": "connected",
            "last_sync": last_update,
            "server_time": datetime.now().isoformat()
        }

# --- B. アラーム確認 (ACK) ---
@router.post("/alerts/{alert_id}/ack")
async def api_ack_alert(alert_id: int, user: str = "operator"):
    """SCADA向け：アラームを確認済みにする"""
    async with aiosqlite.connect(DB_PATH) as db:
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        cursor = await db.execute("""
            UPDATE event_logs 
            SET acked_at = ?, acked_by = ? 
            WHERE id = ? AND acked_at IS NULL
        """, (now, user, alert_id))
        
        await db.commit()
        
        if cursor.rowcount == 0:
            return {"status": "ignored", "message": "Already acked or ID not found"}
            
        return {"status": "success", "id": alert_id, "acked_at": now}