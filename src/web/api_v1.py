from fastapi import APIRouter, HTTPException
import aiosqlite
from datetime import datetime
import time
from pymodbus.client import AsyncModbusTcpClient

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

# ==================================================
# 書き込み系API
# ==================================================
@router.post("/plc/write/register")
async def api_write_plc_register(tag_name: str, value: int):
    """SCADA向け：PLCのレジスター値を書き込む

    Args:
        tag_name (str): 書き込み対象のタグ名
        value (int): 書き込みする値
    """

    if value < 0 or value > 65535:
        raise HTTPException(400, "Value out of range")

    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row

        # 1. タグからPLC情報を取得
        cursor = await db.execute("""
            SELECT i.address, h.ip_address, h.port, h.unit_id
            FROM items i
            JOIN hosts h ON i.host_id = h.id
            WHERE i.tag_name = ?
        """, (tag_name,))

        row = await cursor.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Tag not found")

    address = row["address"]
    ip = row["ip_address"]
    port = row["port"]
    unit_id = row["unit_id"]

    # 2. PLCへ書き込み
    client = AsyncModbusTcpClient(ip, port=port)
    try:
        connected = await client.connect()
        if not connected:
            raise HTTPException(status_code=500, detail="PLC connection failed")

        result = await client.write_register(address, value)
        print(f"WRITE PLC: {ip}:{port} unit={unit_id} address={address} value={value}")

        if result.isError():
            raise HTTPException(status_code=500, detail="Modbus write error")

    finally:
        client.close()

    # 3. DBへ反映（※ 別コネクション）
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE items SET last_value=?, updated_at=datetime('now','localtime') WHERE tag_name=?",
            (value, tag_name)
        )
        await db.commit()

    # 4. 書き込みログへの出力
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """
            INSERT INTO plc_write_log(tag_name, value, created_at)
            VALUES (?, ?, datetime('now','localtime'))
            """,
            (tag_name, value)
        )
        await db.execute(
            "UPDATE items SET last_value=?, updated_at=datetime('now','localtime') WHERE tag_name=?",
            (value, tag_name)
        )
        await db.commit()

    return {
        "status": "success",
        "tag": tag_name,
        "address": address,
        "value": value
    }

@router.post("/plc/write/coil")
async def api_write_plc_coil(tag_name: str, value: bool):
    """SCADA向け：PLCのコイル（ON/OFF）を書き込む"""

    # 1. タグからPLC情報を取得
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row

        cursor = await db.execute("""
            SELECT i.address, h.ip_address, h.port, h.unit_id
            FROM items i
            JOIN hosts h ON i.host_id = h.id
            WHERE i.tag_name = ?
        """, (tag_name,))

        row = await cursor.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Tag not found")

    address = row["address"]
    ip = row["ip_address"]
    port = row["port"]
    unit_id = row["unit_id"]

    # 2. PLCへコイル書き込み
    client = AsyncModbusTcpClient(ip, port=port)
    try:
        connected = await client.connect()
        if not connected:
            raise HTTPException(status_code=500, detail="PLC connection failed")

        result = await client.write_coil(address, value)
        print(f"WRITE PLC COIL: {ip}:{port} unit={unit_id} address={address} value={value}")

        if result.isError():
            raise HTTPException(status_code=500, detail="Modbus write error")

    finally:
        client.close()

    # 3. DB反映
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE items SET last_value=?, updated_at=datetime('now','localtime') WHERE tag_name=?",
            (1 if value else 0, tag_name)
        )
        await db.commit()

    # 4. 書き込みログへの出力
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """
            INSERT INTO plc_write_log(tag_name, value, created_at)
            VALUES (?, ?, datetime('now','localtime'))
            """,
            (tag_name, value)
        )
        await db.execute(
            "UPDATE items SET last_value=?, updated_at=datetime('now','localtime') WHERE tag_name=?",
            (value, tag_name)
        )
        await db.commit()

    return {
        "status": "success",
        "tag": tag_name,
        "address": address,
        "value": value
    }

@router.get("/plc/write_history")
async def api_plc_write_history(tag_name: str):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute("""
            SELECT value, created_at
            FROM plc_write_log
            WHERE tag_name = ?
            ORDER BY created_at DESC
            LIMIT 20
        """, (tag_name,))
        rows = await cursor.fetchall()

    return rows