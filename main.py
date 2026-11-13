import hashlib
import hmac
import json
import os
import urllib.parse
from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
import requests
import sqlite3

app = FastAPI(title="Donate Shop All-in-One")

BOT_TOKEN = os.getenv("BOT_TOKEN", "YOUR_BOT_TOKEN_HERE")
ADMIN_IDS = [int(x) for x in os.getenv("ADMIN_IDS", "123456789").split(",")]
DB_PATH = "shop.db"

# --- БАЗА ДАННЫХ ---
def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS categories (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        slug TEXT UNIQUE NOT NULL
    )""")
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS products (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        title TEXT NOT NULL,
        category_slug TEXT NOT NULL,
        price INTEGER NOT NULL,
        old_price INTEGER,
        image_url TEXT,
        description TEXT,
        is_popular INTEGER DEFAULT 0
    )""")
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS orders (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        username TEXT,
        full_name TEXT,
        items TEXT NOT NULL,
        total_price INTEGER NOT NULL,
        payment_method TEXT NOT NULL,
        status TEXT DEFAULT 'pending_payment',
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )""")
    conn.commit()
    
    cursor.execute("SELECT COUNT(*) FROM categories")
    if cursor.fetchone()[0] == 0:
        default_cats = [
            ("Telegram Stars", "stars"),
            ("Telegram Premium", "premium"),
            ("Robux", "robux"),
            ("Standoff 2 Gold", "standoff"),
            ("Подарки Telegram", "gifts"),
            ("Подписки", "subscriptions")
        ]
        cursor.executemany("INSERT INTO categories (name, slug) VALUES (?, ?)", default_cats)
        conn.commit()
    conn.close()

@app.on_event("startup")
def startup_event():
    init_db()

# --- ПРОВЕРКА TELEGRAM ---
def verify_telegram_init_data(init_data: str) -> dict:
    if not init_data:
        raise HTTPException(status_code=401, detail="No initData provided")
    try:
        parsed = urllib.parse.parse_qsl(init_data)
        data_map = dict(parsed)
        if "hash" not in data_map:
            raise HTTPException(status_code=401, detail="Invalid initData format")
        received_hash = data_map.pop("hash")
        data_list = sorted([f"{k}={v}" for k, v in data_map.items()])
        data_check_string = "\n".join(data_list)
        
        secret_key = hmac.new(b"WebAppData", BOT_TOKEN.encode(), hashlib.sha256).digest()
        calculated_hash = hmac.new(secret_key, data_check_string.encode(), hashlib.sha256).hexdigest()
        
        if calculated_hash != received_hash:
            raise HTTPException(status_code=403, detail="InitData signature mismatch")
        return json.loads(data_map.get("user", "{}"))
    except Exception as e:
        raise HTTPException(status_code=401, detail=f"Auth error: {str(e)}")

# --- API МАРШРУТЫ ---
class OrderCreate(BaseModel):
    items: list
    total_price: int
    payment_method: str
    init_data: str

class ProductUpdate(BaseModel):
    title: str
    category_slug: str
    price: int
    old_price: int | None = None
    image_url: str | None = None
    description: str | None = None
    is_popular: int = 0

@app.get("/api/catalog")
def get_catalog():
    db = get_db()
    categories = db.execute("SELECT * FROM categories").fetchall()
    products = db.execute("SELECT * FROM products").fetchall()
    db.close()
    return {
        "categories": [dict(c) for c in categories],
        "products": [dict(p) for p in products]
    }

@app.post("/api/order")
def create_order(order: OrderCreate):
    user = verify_telegram_init_data(order.init_data)
    user_id = user.get("id")
    username = user.get("username", "")
    full_name = f"{user.get('first_name', '')} {user.get('last_name', '')}".strip()
    
    db = get_db()
    cursor = db.cursor()
    cursor.execute(
        """INSERT INTO orders (user_id, username, full_name, items, total_price, payment_method, status)
           VALUES (?, ?, ?, ?, ?, ?, 'pending_payment')""",
        (user_id, username, full_name, json.dumps(order.items), order.total_price, order.payment_method)
    )
    order_id = cursor.lastrowid
    db.commit()
    db.close()
    
    # Уведомление администратору в Телеграм
    items_str = "\n".join([f"• {i['title']} x{i['quantity']} — {i['price']} сум" for i in order.items])
    text = (
        f"🛍 <b>Новый заказ #{order_id}</b>\n\n"
        f"👤 <b>Покупатель:</b> {full_name} (@{username}, ID: <code>{user_id}</code>)\n"
        f"📦 <b>Товары:</b>\n{items_str}\n\n"
        f"💰 <b>Итого:</b> {order.total_price} сум\n"
        f"💳 <b>Оплата:</b> {order.payment_method}\n"
        f"⏳ <b>Статус:</b> Ожидает оплаты"
    )
    for admin_id in ADMIN_IDS:
        try:
            requests.post(
                f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
                json={"chat_id": admin_id, "text": text, "parse_mode": "HTML"}
            )
        except Exception:
            pass
    return {"success": True, "order_id": order_id}

@app.get("/api/admin/orders")
def get_admin_orders(init_data: str):
    user = verify_telegram_init_data(init_data)
    if user.get("id") not in ADMIN_IDS:
        raise HTTPException(status_code=403, detail="Access denied")
    db = get_db()
    orders = db.execute("SELECT * FROM orders ORDER BY id DESC").fetchall()
    db.close()
    return [dict(o) for o in orders]

@app.post("/api/admin/order/{order_id}/status")
def update_order_status(order_id: int, status_data: dict, init_data: str):
    user = verify_telegram_init_data(init_data)
    if user.get("id") not in ADMIN_IDS:
        raise HTTPException(status_code=403, detail="Access denied")
    db = get_db()
    db.execute("UPDATE orders SET status = ? WHERE id = ?", (status_data.get("status"), order_id))
    db.commit()
    db.close()
    return {"success": True}

@app.post("/api/admin/products")
def save_product(product: ProductUpdate, init_data: str):
    user = verify_telegram_init_data(init_data)
    if user.get("id") not in ADMIN_IDS:
        raise HTTPException(status_code=403, detail="Access denied")
    db = get_db()
    db.execute(
        """INSERT INTO products (title, category_slug, price, old_price, image_url, description, is_popular)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (product.title, product.category_slug, product.price, product.old_price, product.image_url, product.description, product.is_popular)
    )
    db.commit()
    db.close()
    return {"success": True}

# --- ФРОНТЕНД МАГАЗИНА (ГЛАВНАЯ) ---
@app.get("/", response_class=HTMLResponse)
def serve_index():
    return """<!DOCTYPE html>
<html lang="ru">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>DONATE SHOP</title>
    <script src="https://telegram.org/js/telegram-web-app.js"></script>
    <style>
        :root { --bg: #0b0b0f; --card: #161622; --primary: #8700ff; --accent: #a855f7; --text: #fff; --muted: #9494a0; }
        body { background: var(--bg); color: var(--text); font-family: sans-serif; margin: 0; padding-bottom: 80px; }
        header { padding: 16px; text-align: center; background: linear-gradient(180deg, #1b0c3f 0%, var(--bg) 100%); border-bottom: 1px solid #222233; }
        .logo { font-size: 24px; font-weight: 900; background: linear-gradient(90deg, #fff, var(--accent)); -webkit-background-clip: text; -webkit-text-fill-color: transparent; }
        .container { padding: 16px; }
        .balance-card { background: linear-gradient(135deg, #2b0c54, #120924); border: 1px solid var(--primary); border-radius: 16px; padding: 16px; margin-bottom: 20px; display: flex; justify-content: space-between; align-items: center; }
        .categories { display: flex; gap: 8px; overflow-x: auto; padding-bottom: 8px; margin-bottom: 16px; }
        .categories::-webkit-scrollbar { display: none; }
        .cat-btn { background: var(--card); border: 1px solid #2a2a3c; color: var(--muted); padding: 8px 16px; border-radius: 20px; white-space: nowrap; cursor: pointer; }
        .cat-btn.active { background: var(--primary); color: #fff; border-color: var(--accent); }
        .grid { display: grid; grid-template-columns: repeat(2, 1fr); gap: 12px; }
        .card { background: var(--card); border: 1px solid #222236; border-radius: 14px; padding: 12px; display: flex; flex-direction: column; justify-content: space-between; }
        .card img { width: 100%; height: 110px; object-fit: cover; border-radius: 10px; background: #202030; }
        .title { font-size: 14px; font-weight: 600; margin: 8px 0 4px; }
        .price { font-size: 15px; font-weight: 700; color: var(--accent); }
        .btn { background: var(--primary); color: #fff; border: none; width: 100%; padding: 8px; border-radius: 8px; font-weight: 600; margin-top: 8px; cursor: pointer; }
        nav { position: fixed; bottom: 0; left: 0; right: 0; background: #111118; border-top: 1px solid #222233; display: flex; justify-content: space-around; padding: 12px 0; }
        .nav-item { color: var(--muted); background: none; border: none; font-size: 12px; cursor: pointer; }
        .nav-item.active { color: var(--accent); }
    </style>
</head>
<body>
    <header><div class="logo">DONATE SHOP</div></header>
    <div class="container">
        <div class="balance-card">
            <div>
                <div style="font-size: 12px; color: var(--muted);">Баланс</div>
                <div style="font-size: 20px; font-weight: bold;">0 сум</div>
            </div>
            <button class="btn" style="width: auto; padding: 8px 16px;" onclick="alert('Пополнение доступно через администратора')">Пополнить</button>
        </div>
        <div class="categories" id="cats"></div>
        <div class="grid" id="products"></div>
    </div>
    <nav>
        <button class="nav-item active">🏠 Каталог</button>
        <button class="nav-item" onclick="makeOrder()">🛒 Корзина (<span id="cart-count">0</span>)</button>
        <button class="nav-item" onclick="showProfile()">👤 Профиль</button>
    </nav>
    <script>
        const tg = window.Telegram.WebApp;
        tg.expand();
        let data = { categories: [], products: [] };
        let activeCat = 'all';
        let cart = [];

        async function load() {
            const res = await fetch('/api/catalog');
            data = await res.json();
            render();
        }

        function render() {
            document.getElementById('cats').innerHTML = `<button class="cat-btn ${activeCat==='all'?'active':''}" onclick="setCat('all')">Все</button>` +
                data.categories.map(c => `<button class="cat-btn ${activeCat===c.slug?'active':''}" onclick="setCat('${c.slug}')">${c.name}</button>`).join('');
            
            const filtered = activeCat === 'all' ? data.products : data.products.filter(p => p.category_slug === activeCat);
            document.getElementById('products').innerHTML = filtered.map(p => `
                <div class="card">
                    <div>
                        <img src="${p.image_url || 'https://via.placeholder.com/150'}" alt="">
                        <div class="title">${p.title}</div>
                    </div>
                    <div>
                        <div class="price">${p.price} сум</div>
                        <button class="btn" onclick='addCart(${JSON.stringify(p)})'>Купить</button>
                    </div>
                </div>
            `).join('');
        }

        function setCat(slug) { activeCat = slug; render(); }
        
        function addCart(p) {
            cart.push(p);
            document.getElementById('cart-count').innerText = cart.length;
            tg.HapticFeedback.notificationOccurred('success');
            tg.showAlert(`Товар "${p.title}" добавлен в корзину!`);
        }

        function showProfile() {
            const u = tg.initDataUnsafe?.user || { id: 'Demo', first_name: 'Гость' };
            alert(`Профиль:\\nИмя: ${u.first_name}\\nID: ${u.id}\\nБаланс: 0 сум`);
        }

        async function makeOrder() {
            if (cart.length === 0) { tg.showAlert('Корзина пуста'); return; }
            const method = prompt("Выберите способ оплаты:\\n1 - Uzum\\n2 - Перевод на карту\\n3 - Наличные", "Uzum");
            if (!method) return;

            const res = await fetch('/api/order', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    items: cart.map(i => ({ title: i.title, price: i.price, quantity: 1 })),
                    total_price: cart.reduce((s, i) => s + i.price, 0),
                    payment_method: method,
                    init_data: tg.initData
                })
            });
            const r = await res.json();
            if (r.success) {
                cart = [];
                document.getElementById('cart-count').innerText = 0;
                tg.showAlert(`Заказ #${r.order_id} создан! Статус: Ожидает оплаты.`);
            }
        }
        load();
    </script>
</body>
</html>"""

# --- АДМИН-ПАНЕЛЬ (/admin) ---
@app.get("/admin", response_class=HTMLResponse)
def serve_admin():
    return """<!DOCTYPE html>
<html lang="ru">
<head>
    <meta charset="UTF-8">
    <title>Админ-панель</title>
    <script src="https://telegram.org/js/telegram-web-app.js"></script>
    <style>
        body { background: #0b0b0f; color: #fff; font-family: sans-serif; padding: 16px; }
        .card { background: #161622; padding: 12px; margin-bottom: 10px; border-radius: 8px; }
        input, select { width: 100%; padding: 8px; margin: 6px 0; background: #222; border: 1px solid #444; color: #fff; border-radius: 4px; box-sizing: border-box; }
        button { background: #8700ff; color: #fff; border: none; padding: 10px; width: 100%; border-radius: 6px; cursor: pointer; font-weight: bold; }
    </style>
</head>
<body>
    <h1>Админ-панель</h1>
    <div class="card">
        <h3>Добавить товар</h3>
        <input type="text" id="title" placeholder="Название">
        <select id="cat">
            <option value="stars">Telegram Stars</option>
            <option value="premium">Telegram Premium</option>
            <option value="robux">Robux</option>
            <option value="standoff">Standoff 2 Gold</option>
            <option value="gifts">Подарки Telegram</option>
            <option value="subscriptions">Подписки</option>
        </select>
        <input type="number" id="price" placeholder="Цена в сумах">
        <input type="text" id="img" placeholder="Ссылка на картинку">
        <button onclick="add()">Добавить</button>
    </div>
    <h2>Заказы</h2>
    <div id="orders">Загрузка...</div>
    <script>
        const tg = window.Telegram.WebApp;
        async function loadOrders() {
            const res = await fetch(`/api/admin/orders?init_data=${encodeURIComponent(tg.initData)}`);
            const orders = await res.json();
            document.getElementById('orders').innerHTML = orders.map(o => `
                <div class="card">
                    <b>Заказ #${o.id}</b> | ${o.full_name} (@${o.username})<br>
                    Сумма: <b>${o.total_price} сум</b> | Оплата: ${o.payment_method}<br>
                    Статус: <b>${o.status}</b>
                    <select onchange="up(${o.id}, this.value)">
                        <option value="pending_payment" ${o.status==='pending_payment'?'selected':''}>Ожидает оплаты</option>
                        <option value="paid" ${o.status==='paid'?'selected':''}>Оплачен</option>
                        <option value="completed" ${o.status==='completed'?'selected':''}>Выполнен</option>
                        <option value="cancelled" ${o.status==='cancelled'?'selected':''}>Отменён</option>
                    </select>
                </div>
            `).join('');
        }
        async function add() {
            const res = await fetch(`/api/admin/products?init_data=${encodeURIComponent(tg.initData)}`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    title: document.getElementById('title').value,
                    category_slug: document.getElementById('cat').value,
                    price: parseInt(document.getElementById('price').value),
                    image_url: document.getElementById('img').value
                })
            });
            if((await res.json()).success) { alert('Успешно!'); location.reload(); }
        }
        async function up(id, status) {
            await fetch(`/api/admin/order/${id}/status?init_data=${encodeURIComponent(tg.initData)}`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ status })
            });
            loadOrders();
        }
        loadOrders();
    </script>
</body>
</html>"""# donate_shop
