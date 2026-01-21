from fastapi import FastAPI, Request, Form, UploadFile, File
from fastapi.templating import Jinja2Templates
from fastapi.responses import RedirectResponse
from fastapi.responses import HTMLResponse
import aiosqlite
import os
import yaml
from fastapi.responses import StreamingResponse
import io
import time

# from src.web import api_v1
from src.web import api_v1

app = FastAPI()
app.include_router(api_v1.router)
templates = Jinja2Templates(directory="src/web/templates")

from src.common.config_loader import config

# DBパスをconfigから取得
DB_PATH = config.db_path

RETENTION_MINUTES = config.retention_minutes
last_cleanup_time = 0  # 前回の実行時間を保持するグローバル変数

@app.get("/")
async def index(request: Request):
    # 最新値キャッシュ(items)を取得
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute("SELECT tag_name, last_value, updated_at FROM items")
        items = await cursor.fetchall()
    
    return templates.TemplateResponse("index.html", {"request": request, "items": items})

@app.post("/update_config")
async def update_config(tag_name: str = Form(...), new_threshold: float = Form(...)):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE items SET threshold = ? WHERE tag_name = ?",
            (new_threshold, tag_name)
        )
        await db.commit()
    # ここでDBが更新されると、別プロセスのWatcherが検知する流れ
    return RedirectResponse(url="/", status_code=303)

@app.get("/hosts")
async def list_hosts(request: Request):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute("SELECT * FROM hosts")
        hosts = await cursor.fetchall()
    return templates.TemplateResponse("hosts.html", {"request": request, "hosts": hosts})

@app.post("/add_host")
async def add_host(display_name: str = Form(...), ip_address: str = Form(...), port: int = Form(502)):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT INTO hosts (display_name, ip_address, port) VALUES (?, ?, ?)",
            (display_name, ip_address, port)
        )
        await db.commit()
    return RedirectResponse(url="/hosts", status_code=303)

@app.post("/delete_host/{host_id}")
async def delete_host(host_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        # 1. 紐づく監視項目(items)を先に削除
        await db.execute("DELETE FROM items WHERE host_id = ?", (host_id,))
        # 2. PLC本体(hosts)を削除
        await db.execute("DELETE FROM hosts WHERE id = ?", (host_id,))
        await db.commit()
    
    return RedirectResponse(url="/hosts", status_code=303)

@app.get("/hosts/{host_id}/items")
async def list_host_items(request: Request, host_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        # PLC情報の取得
        cursor = await db.execute("SELECT * FROM hosts WHERE id = ?", (host_id,))
        host = await cursor.fetchone()
        # そのPLCに紐づくアイテム一覧の取得
        cursor = await db.execute("SELECT * FROM items WHERE host_id = ?", (host_id,))
        items = await cursor.fetchall()
        
    return templates.TemplateResponse("host_items.html", {
        "request": request, 
        "host": host, 
        "items": items
    })

@app.post("/hosts/{host_id}/add_item")
async def add_item(host_id: int, tag_name: str = Form(...), address: int = Form(...), alarm_threshold: float = Form(...), polling_interval: int = Form(...) ):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT INTO items (tag_name, address, host_id, alarm_threshold, alarm_enabled, polling_interval) VALUES (?, ?, ?, ?, ?, ?)",
            (tag_name, address, host_id, alarm_threshold, 1, polling_interval)
        )
        await db.commit()
    return RedirectResponse(url=f"/hosts/{host_id}/items", status_code=303)

@app.post("/hosts/{host_id}/delete_item/{item_id}")
async def delete_item(host_id: int, item_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("DELETE FROM items WHERE id = ?", (item_id,))
        await db.commit()
    return RedirectResponse(url=f"/hosts/{host_id}/items", status_code=303)

@app.post("/hosts/{host_id}/update_item/{item_id}")
async def update_item(
    host_id: int, 
    item_id: int, 
    tag_name: str = Form(...), 
    address: int = Form(...),
    alarm_threshold: float = Form(0.0),
    alarm_enabled: int = Form(0),
    polling_interval: int = Form(5) # ← 追加
):
    # --- デバッグ用プリント (intervalも追加) ---
    print("--- DEBUG: update_item received ---")
    print(f"Item ID: {item_id}, Interval: {polling_interval}")
    print("-----------------------------------")

    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """UPDATE items 
               SET tag_name = ?, address = ?, alarm_threshold = ?, alarm_enabled = ?, polling_interval = ? 
               WHERE id = ?""",
            (tag_name, address, alarm_threshold, alarm_enabled, polling_interval, item_id) # ← 引数追加
        )
        await db.commit()
    return RedirectResponse(url=f"/hosts/{host_id}/items", status_code=303)

@app.get("/api/dashboard_fragment")
async def get_dashboard_fragment(
    request: Request,
    host_filter: str = "",
    search: str = "",
    only_positive: bool = False,  # 0以上のアイテムのみ
    only_alarm: bool = False      # アラート中のみ
):
    
    # ダッシュボード更新のリクエストが来るたびにチェック（実際には1分に1回だけ動く）
    await cleanup_old_data()

    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row

        # --- 1. 統計情報の取得（前回と同じ） ---
        cursor = await db.execute("""
            SELECT 
                COUNT(*) as total,
                SUM(CASE WHEN alarm_enabled = 1 AND last_value >= alarm_threshold THEN 1 ELSE 0 END) as alarms,
                SUM(CASE WHEN last_value IS NULL THEN 1 ELSE 0 END) as no_data
            FROM items
        """)
        stats = await cursor.fetchone()

        # --- 2. メインクエリ構築 ---
        query = """
            SELECT items.*, hosts.display_name as host_name, hosts.status as host_status,
            (SELECT GROUP_CONCAT(value) FROM (
                SELECT value FROM history 
                WHERE item_id = items.id 
                ORDER BY timestamp DESC LIMIT 10
            )) as recent_values
            FROM items 
            JOIN hosts ON items.host_id = hosts.id
            WHERE 1=1
        """
        params = []

        # ホスト名での絞り込み
        if host_filter:
            query += " AND hosts.display_name = ?"
            params.append(host_filter)
        
        # キーワード検索（タグ名）
        if search:
            query += " AND items.tag_name LIKE ?"
            params.append(f"%{search}%")

        if only_positive:
            query += " AND items.last_value > 0"
        
        if only_alarm:
            # アラート有効かつ、閾値を超えているもの
            query += " AND items.alarm_enabled = 1 AND items.last_value >= items.alarm_threshold"

        query += " ORDER BY hosts.display_name, items.tag_name"
        
        cursor = await db.execute(query, params)
        items = await cursor.fetchall()

    # --- 3. サマリーHTML構築 ---
    # 統計値に基づいて色を決定
    alarm_color = "#d32f2f" if stats['alarms'] > 0 else "#888"
    alarm_bg = "rgba(211,47,47,0.1)" if stats['alarms'] > 0 else "transparent"

    summary_html = f"""
    <div style="display: flex; gap: 1.5rem; margin-bottom: 1rem; padding: 0.5rem 1rem; background: rgba(255,255,255,0.03); border-radius: 8px; align-items: center;">
        <div style="font-size: 0.85rem;">
            <span style="color: #888; margin-right: 0.5rem;">Total:</span>
            <strong style="font-size: 1.1rem;">{stats['total']}</strong>
        </div>
        <div style="font-size: 0.85rem; padding: 2px 12px; border-radius: 20px; background: {alarm_bg}; border: 1px solid {alarm_color if stats['alarms'] > 0 else '#444'};">
            <span style="color: {alarm_color}; margin-right: 0.5rem;">{'⚠️' if stats['alarms'] > 0 else '✅'} Alarms:</span>
            <strong style="font-size: 1.1rem; color: {alarm_color};">{stats['alarms']}</strong>
        </div>
        <div style="font-size: 0.85rem;">
            <span style="color: #888; margin-right: 0.5rem;">Offline/No Data:</span>
            <strong style="font-size: 1.1rem;">{stats['no_data'] or 0}</strong>
        </div>
        <div style="flex-grow: 1; text-align: right;">
            <small style="color: #555; font-size: 0.7rem;">Retention: {RETENTION_MINUTES}min</small>
        </div>
    </div>
    """

    # --- 4. メインダッシュボードHTML構築 ---
    table_html = """
    <table role="grid" class="compact-table">
        <thead>
            <tr>
                <th style="width: 80px;">状態</th>
                <th>ホスト名</th>
                <th>タグ名</th>
                <th style="text-align: center;">最新値</th>
                <th>アラート設定</th>
                <th>周期</th>
                <th style="width: 120px; text-align: center;">トレンド</th>
                <th>最終更新</th>
                <th>操作</th>
            </tr>
        </thead>
        <tbody>
    """
    
    for item in items:
        # --- 変数の定義開始 ---
        val = item['last_value'] if item['last_value'] is not None else "--"
        alarm_enabled = item['alarm_enabled'] == 1
        threshold = item['alarm_threshold']
        
        # アラーム判定
        is_alarm = (alarm_enabled and 
                    item['last_value'] is not None and 
                    item['last_value'] >= threshold)
        
        host_offline = item['host_status'] == 'Offline'
        
        # row_class の定義 (これが漏れていました)
        row_class = "row-alarm" if is_alarm else ""
        
        # 状態ラベル
        if host_offline:
            status_label = '<span class="badge" style="background-color: #757575;">通信断</span>'
        elif is_alarm:
            status_label = '<span class="badge alarm">異常</span>'
        else:
            status_label = '<span class="badge normal">正常</span>'

        # アラート設定とスタイル
        if alarm_enabled:
            alert_cfg_html = f'<span style="color: var(--primary); font-size: 0.8rem;">🔔 ON (>= {threshold})</span>'
            val_style = "font-size: 1.2rem; color: var(--h1-color);"
        else:
            alert_cfg_html = '<span style="color: #666; font-size: 0.8rem;">🔕 OFF</span>'
            val_style = "font-size: 1.2rem; color: #666; opacity: 0.5;"

        history_data = item['recent_values'] or ""
        # --- 変数の定義終了 ---

        table_html += f"""
        <tr class="{row_class}">
            <td>{status_label}</td>
            <td><strong>{item['host_name']}</strong></td>
            <td><code>{item['tag_name']}</code></td>
            <td style="font-family: monospace; font-weight: bold; text-align: center; {val_style}">
                {val}
            </td>
            <td>{alert_cfg_html}</td>
            <td><small>{item['polling_interval']}s</small></td>
            
            <td style="vertical-align: middle; text-align: center; background: rgba(255,255,255,0.05);">
                <canvas class="sparkline-canvas" 
                        data-values="{history_data}" 
                        width="100" height="25"></canvas>
            </td>

            <td><small>{item['updated_at'] or '-'}</small></td>
            <td>
                <a href="/items/{item['id']}/history" role="button" class="outline secondary" 
                   style="font-size: 0.7rem; padding: 2px 8px; margin-bottom: 0;">
                    📈 履歴
                </a>
            </td>
        </tr>
        """
    
    table_html += "</tbody></table>"
    return HTMLResponse(content=summary_html + table_html)

@app.get("/alerts")
async def list_alerts(request: Request):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        # event_logs と items, hosts を結合して、詳細な情報を取得
        cursor = await db.execute("""
            SELECT 
                e.*, 
                i.tag_name, 
                h.display_name as host_name
            FROM event_logs e
            JOIN items i ON e.item_id = i.id
            JOIN hosts h ON i.host_id = h.id
            ORDER BY e.start_time DESC
            LIMIT 50
        """)
        alerts = await cursor.fetchall()
        
    return templates.TemplateResponse("alerts.html", {
        "request": request,
        "alerts": alerts
    })

@app.post("/hosts/{host_id}/add_item")
async def add_item(
    host_id: int, 
    tag_name: str = Form(...), 
    address: int = Form(...),
    alarm_threshold: float = Form(100.0), # デフォルト値
    alarm_enabled: int = Form(0),          # デフォルトOFF
    polling_interval: int = Form(5)
):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """INSERT INTO items (tag_name, address, host_id, alarm_threshold, alarm_enabled, polling_interval) 
               VALUES (?, ?, ?, ?, ?, ?)""",
            (tag_name, address, host_id, alarm_threshold, alarm_enabled, polling_interval)
        )
        await db.commit()
    return RedirectResponse(url=f"/hosts/{host_id}/items", status_code=303)

@app.post("/hosts/{host_id}/update_item/{item_id}")
async def update_item(
    host_id: int, 
    item_id: int, 
    tag_name: str = Form(...), 
    address: int = Form(...),
    alarm_threshold: float = Form(0.0),
    alarm_enabled: int = Form(0)
):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """UPDATE items 
               SET tag_name = ?, address = ?, alarm_threshold = ?, alarm_enabled = ? 
               WHERE id = ?""",
            (tag_name, address, alarm_threshold, alarm_enabled, item_id)
        )
        await db.commit()
    return RedirectResponse(url=f"/hosts/{host_id}/items", status_code=303)

@app.get("/history/{tag_name}")
async def get_item_history(tag_name: str, hours: int = 24):
    """SCADA向け：特定タグの過去履歴を取得"""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        
        # 1. まずtag_nameからitem_idを特定
        cursor = await db.execute("SELECT id FROM items WHERE tag_name = ?", (tag_name,))
        item = await cursor.fetchone()
        if not item:
            return {"error": f"Tag '{tag_name}' not found"}, 404
            
        # 2. 指定された時間分の履歴を取得
        cursor = await db.execute("""
            SELECT timestamp, value 
            FROM history 
            WHERE item_id = ? 
              AND timestamp >= DATETIME('now', 'localtime', ?)
            ORDER BY timestamp ASC
        """, (item["id"], f"-{hours} hours"))
        
        rows = await cursor.fetchall()
        
        # SCADAのグラフライブラリ(Chart.js等)が扱いやすい形式に整形
        values = [[row["timestamp"], row["value"]] for row in rows]
        
        return {
            "tag": tag_name,
            "count": len(values),
            "values": values
        }

@app.get("/items/{item_id}/history")
async def item_history_view(request: Request, item_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        
        # 1. アイテム名とホスト名を取得（画面のタイトル用）
        cursor = await db.execute("""
            SELECT i.*, h.display_name as host_name 
            FROM items i JOIN hosts h ON i.host_id = h.id 
            WHERE i.id = ?
        """, (item_id,))
        item = await cursor.fetchone()
        
        if not item:
            return HTMLResponse(content="Item not found", status_code=404)

        # 2. 直近50件の履歴を取得
        cursor = await db.execute("""
            SELECT value, timestamp 
            FROM history 
            WHERE item_id = ? 
            ORDER BY timestamp DESC 
            LIMIT 50
        """, (item_id,))
        history = await cursor.fetchall()
        
    return templates.TemplateResponse("history_detail.html", {
        "request": request,
        "item": item,
        "history": history
    })

# --- 設定画面の表示 ---
@app.get("/settings", response_class=HTMLResponse)
async def settings_page(request: Request):
    return templates.TemplateResponse("settings.html", {"request": request})

# --- エクスポート機能 ---
@app.get("/settings/export/yaml")
async def export_yaml():
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        # 1. ホスト一覧を取得
        cursor = await db.execute("SELECT * FROM hosts")
        hosts = await cursor.fetchall()
        
        config_data = {"hosts": []}
        
        for host in hosts:
            host_dict = {
                "display_name": host["display_name"],
                "ip_address": host["ip_address"],
                "port": host["port"],
                "unit_id": host["unit_id"],
                "is_active": bool(host["is_active"]),
                "items": []
            }
            # 2. そのホストに紐づくアイテムを取得
            item_cursor = await db.execute("SELECT * FROM items WHERE host_id = ?", (host["id"],))
            items = await item_cursor.fetchall()
            for item in items:
                host_dict["items"].append({
                    "tag_name": item["tag_name"],
                    "address": item["address"],
                    "alarm_threshold": item["alarm_threshold"],
                    "alarm_enabled": bool(item["alarm_enabled"]),
                    "polling_interval": item["polling_interval"]
                })
            config_data["hosts"].append(host_dict)

    yaml_str = yaml.dump(config_data, allow_unicode=True, sort_keys=False, default_flow_style=False)
    
    return StreamingResponse(
        io.BytesIO(yaml_str.encode()),
        media_type="application/x-yaml",
        headers={"Content-Disposition": "attachment; filename=simple_edge_config.yaml"}
    )

# --- インポート機能 ---
@app.post("/settings/import/yaml")
async def import_yaml(
    file: UploadFile = File(...), 
    overwrite_all: bool = Form(False)  # ★フォームから値を受け取る
):
    # print("yaml import: start")
    content = await file.read()
    data = yaml.safe_load(content)

    # 統計用のカウント
    # print("yaml import: Cnt")

    host_count = len(data.get("hosts", []))
    item_count = sum(len(h.get("items", [])) for h in data.get("hosts", []))

    async with aiosqlite.connect(DB_PATH) as db:
        # --- ★全削除モードの処理 ---
        if overwrite_all:
            # 外部キー制約がある場合は削除順序に注意（items -> hosts）
            # print("yaml import: Delete Start")

            await db.execute("DELETE FROM items")
            await db.execute("DELETE FROM hosts")
            await db.execute("DELETE FROM event_logs")
            await db.execute("DELETE FROM history")
            # IDをリセットしたい場合は SQLiteのシーケンスもクリア
            await db.execute("DELETE FROM sqlite_sequence WHERE name IN ('items', 'hosts', 'event_logs', 'history')")
            # print("yaml import: Delete End")


        for h in data.get("hosts", []):
            # print(f"yaml import: host > {h['display_name']} Start")

            # ホストの登録 (名前で存在確認)
            cursor = await db.execute(
                "SELECT id FROM hosts WHERE display_name = ?", (h['display_name'],)
            )
            host_row = await cursor.fetchone()
            
            if host_row:
                host_id = host_row[0]
                # 既存ホストの設定を更新する場合
                await db.execute(
                    "UPDATE hosts SET ip_address=?, port=?, unit_id=?, is_active=? WHERE id=?",
                    (h['ip_address'], h['port'], h.get('unit_id', 1), 1 if h.get('is_active', True) else 0, host_id)
                )
            else:
                cursor = await db.execute(
                    "INSERT INTO hosts (display_name, ip_address, port, unit_id, is_active) VALUES (?, ?, ?, ?, ?)",
                    (h['display_name'], h['ip_address'], h['port'], h.get('unit_id', 1), 1 if h.get('is_active', True) else 0)
                )
                host_id = cursor.lastrowid
            
            # アイテムの登録
            for i in h.get("items", []):
                # print(f"yaml import: host > {h['display_name']} - Item > {i['tag_name']} Start")
                # タグ名重複時は更新(UPSERT)
                await db.execute(
                    """INSERT INTO items 
                       (tag_name, address, host_id, alarm_threshold, alarm_enabled, polling_interval) 
                       VALUES (?, ?, ?, ?, ?, ?)
                       ON CONFLICT(host_id, tag_name) DO UPDATE SET
                       address=excluded.address,
                       host_id=excluded.host_id,
                       alarm_threshold=excluded.alarm_threshold,
                       alarm_enabled=excluded.alarm_enabled,
                       polling_interval=excluded.polling_interval""",
                    (i['tag_name'], i['address'], host_id, 
                     i['alarm_threshold'], 1 if i.get('alarm_enabled', True) else 0, i['polling_interval'])
                )
                # print(f"yaml import: host > {h['display_name']} - Item > {i['tag_name']} End")

            # print(f"yaml import: host > {h} - Item End")

        await db.commit()
    
    # URLパラメータに結果を付けてリダイレクト
    return RedirectResponse(
        url=f"/settings?msg=success&h={host_count}&i={item_count}", 
        status_code=303
    )

async def cleanup_old_data():
    """設定された分数を経過したデータを削除する。1分に1回だけ実行。"""
    global last_cleanup_time
    now = time.time()
    
    # 前回の実行から60秒経過していなければ何もしない
    if now - last_cleanup_time < 60:
        return

    try:
        async with aiosqlite.connect(DB_PATH) as db:
            # 分単位で古いデータを削除
            await db.execute(
                "DELETE FROM history WHERE timestamp < DATETIME('now', 'localtime', ?)",
                (f"-{RETENTION_MINUTES} minutes",)
            )
            # アラートログも同様にクリーンアップする場合（必要に応じて）
            await db.execute(
                "DELETE FROM event_logs WHERE start_time < DATETIME('now', 'localtime', ?)",
                (f"-{RETENTION_MINUTES} minutes",)
            )
            await db.commit()
            last_cleanup_time = now
            print(f"DEBUG: Cleaned up data older than {RETENTION_MINUTES} minutes.")
    except Exception as e:
        print(f"Cleanup Error: {e}")

@app.get("/api_docs", response_class=HTMLResponse)
async def api_docs_page(request: Request):
    return templates.TemplateResponse("api_docs.html", {"request": request})

