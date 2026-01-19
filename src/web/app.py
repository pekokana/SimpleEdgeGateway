from fastapi import FastAPI, Request, Form
from fastapi.templating import Jinja2Templates
from fastapi.responses import RedirectResponse
from fastapi.responses import HTMLResponse
import aiosqlite
import os

app = FastAPI()
templates = Jinja2Templates(directory="src/web/templates")
DB_PATH = "data/gateway.sqlite"

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

# app.py に追加

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
async def get_dashboard_fragment(request: Request):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute("""
            SELECT items.*, hosts.display_name as host_name, hosts.status as host_status
            FROM items 
            JOIN hosts ON items.host_id = hosts.id
            ORDER BY hosts.display_name, items.tag_name
        """)
        items = await cursor.fetchall()
        
    html = """
    <table role="grid" class="compact-table">
        <thead>
            <tr>
                <th style="width: 100px;">状態</th>
                <th>ホスト名</th>
                <th>タグ名</th>
                <th style="text-align: center;">最新値</th>
                <th>アラート設定</th>
                <th>周期</th>
                <th>最終更新</th>
            </tr>
        </thead>
        <tbody>
    """
    
    for item in items:
        val = item['last_value'] if item['last_value'] is not None else "--"
        alarm_enabled = item['alarm_enabled'] == 1
        threshold = item['alarm_threshold']
        
        # アラーム判定（設定がONの時のみ判定）
        is_alarm = (alarm_enabled and 
                    item['last_value'] is not None and 
                    item['last_value'] >= threshold)
        
        host_offline = item['host_status'] == 'Offline'
        
        # 状態ラベル
        if host_offline:
            status_label = '<span class="badge" style="background-color: #757575;">通信断</span>'
        elif is_alarm:
            status_label = '<span class="badge alarm">異常</span>'
        else:
            status_label = '<span class="badge normal">正常</span>'

        # アラート設定の表示（ON/OFF）
        if alarm_enabled:
            alert_cfg_html = f'<span style="color: var(--primary); font-size: 0.8rem;">🔔 ON (>= {threshold})</span>'
            val_style = "font-size: 1.2rem; color: var(--h1-color);"
        else:
            alert_cfg_html = '<span style="color: #666; font-size: 0.8rem;">🔕 OFF</span>'
            val_style = "font-size: 1.2rem; color: #666; opacity: 0.5;" # 設定OFFなら値を薄くする

        row_class = "row-alarm" if is_alarm else ""

        html += f"""
        <tr class="{row_class}">
            <td>{status_label}</td>
            <td><strong>{item['host_name']}</strong></td>
            <td><code>{item['tag_name']}</code></td>
            <td style="font-family: monospace; font-weight: bold; text-align: center; {val_style}">
                {val}
            </td>
            <td>{alert_cfg_html}</td>
            <td><small>{item['polling_interval']}s</small></td>
            <td><small>{item['updated_at'] or '-'}</small></td>
        </tr>
        """
    
    html += "</tbody></table>"
    return HTMLResponse(content=html)

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
    # --- デバッグ用プリント ---
    print("--- DEBUG: update_item received ---")
    print(f"Item ID: {item_id}")
    print(f"Tag Name: {tag_name}")
    print(f"Address: {address}")
    print(f"Threshold: {alarm_threshold}")
    print(f"Enabled: {alarm_enabled}")
    print("-----------------------------------")
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """UPDATE items 
               SET tag_name = ?, address = ?, alarm_threshold = ?, alarm_enabled = ? 
               WHERE id = ?""",
            (tag_name, address, alarm_threshold, alarm_enabled, item_id)
        )
        await db.commit()
    return RedirectResponse(url=f"/hosts/{host_id}/items", status_code=303)

