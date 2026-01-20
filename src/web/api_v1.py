from fastapi import APIRouter
import aiosqlite
from datetime import datetime


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