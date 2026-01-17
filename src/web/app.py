from fastapi import FastAPI, Request, Form
from fastapi.templating import Jinja2Templates
from fastapi.responses import RedirectResponse
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
async def add_item(host_id: int, tag_name: str = Form(...), address: int = Form(...)):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT INTO items (tag_name, address, host_id) VALUES (?, ?, ?)",
            (tag_name, address, host_id)
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
async def update_item(host_id: int, item_id: int, tag_name: str = Form(...), address: int = Form(...)):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE items SET tag_name = ?, address = ? WHERE id = ?",
            (tag_name, address, item_id)
        )
        await db.commit()
    return RedirectResponse(url=f"/hosts/{host_id}/items", status_code=303)