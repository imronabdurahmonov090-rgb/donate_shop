import sqlite3
from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

app = FastAPI()

ADMIN_ID = 8800181441
DB_PATH = "shop.db"

def init_db():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            balance INTEGER DEFAULT 0
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS products (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            price INTEGER NOT NULL
        )
    """)
    
    # Добавляем стартовые товары, если таблица пустая
    cursor.execute("SELECT COUNT(*) FROM products")
    if cursor.fetchone()[0] == 0:
        default_products = [
            ("Telegram Stars (100 шт)", 190),
            ("Telegram Premium (1 месяц)", 350),
            ("Robux (400 Robux)", 450),
            ("Standoff 2 Gold (100 Gold)", 100)
        ]
        cursor.executemany("INSERT INTO products (title, price) VALUES (?, ?)", default_products)
        
    conn.commit()
    conn.close()

init_db()

class TopUpRequest(BaseModel):
    user_id: int
    amount: int
    card_number: str

class ProductRequest(BaseModel):
    admin_id: int
    title: str
    price: int

@app.get("/", response_class=HTMLResponse)
def serve_app():
    return f"""
    <!DOCTYPE html>
    <html lang="ru">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>DONATE SHOP</title>
        <script src="https://telegram.org/js/telegram-web-app.js"></script>
        <style>
            body {{
                background-color: #0d0d12;
                color: #ffffff;
                font-family: -apple-system, BlinkMacSystemFont, sans-serif;
                margin: 0;
                padding: 16px;
            }}
            .card {{
                background: #171722;
                border: 1px solid #2e2e42;
                border-radius: 14px;
                padding: 16px;
                margin-bottom: 14px;
            }}
            h2, h3 {{ margin-top: 0; color: #a855f7; }}
            input {{
                width: 100%;
                box-sizing: border-box;
                padding: 12px;
                margin: 6px 0 12px;
                border-radius: 10px;
                border: 1px solid #3b3b54;
                background: #0d0d12;
                color: #fff;
                font-size: 15px;
            }}
            button {{
                width: 100%;
                padding: 12px;
                border: none;
                border-radius: 10px;
                background: #7c3aed;
                color: #fff;
                font-weight: bold;
                font-size: 15px;
                cursor: pointer;
            }}
            button:active {{ opacity: 0.85; }}
            .product-item {{
                display: flex;
                justify-content: space-between;
                align-items: center;
                padding: 10px 0;
                border-bottom: 1px solid #262636;
            }}
            .product-item:last-child {{ border-bottom: none; }}
            .admin-box {{
                border: 1px solid #a855f7;
                background: #1c1329;
            }}
        </style>
    </head>
    <body>
        <div class="card">
            <h2>DONATE SHOP</h2>
            <div>Ваш баланс: <b id="balance">0</b> ₽</div>
        </div>

        <div class="card">
            <h3>Пополнить баланс картой</h3>
            <input type="text" id="card" placeholder="Номер карты">
            <input type="number" id="amount" placeholder="Сумма пополнения">
            <button onclick="topUp()">Пополнить</button>
        </div>

        <div class="card">
            <h3>Доступные товары</h3>
            <div id="products-list">Загрузка...</div>
        </div>

        <div id="admin-panel" class="card admin-box" style="display:none;">
            <h3>Админ-панель (Добавить товар)</h3>
            <input type="text" id="prod-title" placeholder="Название (например: Робуксы 800)">
            <input type="number" id="prod-price" placeholder="Цена в рублях">
            <button onclick="addProduct()">Добавить в магазин</button>
        </div>

        <script>
            const tg = window.Telegram.WebApp;
            tg.expand();
            const ADMIN_ID = {ADMIN_ID};
            const user = tg.initDataUnsafe?.user;
            const userId = user ? user.id : ADMIN_ID;

            if (userId === ADMIN_ID) {{
                document.getElementById('admin-panel').style.display = 'block';
            }}

            async function loadData() {{
                const uRes = await fetch('/api/user/' + userId);
                const uData = await uRes.json();
                document.getElementById('balance').innerText = uData.balance;

                const pRes = await fetch('/api/products');
                const pData = await pRes.json();
                const list = document.getElementById('products-list');
                if (pData.products.length === 0) {{
                    list.innerHTML = 'Товаров пока нет';
                }} else {{
                    list.innerHTML = pData.products.map(p =>
                        `<div class="product-item"><span>${{p.title}}</span><b>${{p.price}} ₽</b></div>`
                    ).join('');
                }}
            }}

            async function topUp() {{
                const card = document.getElementById('card').value;
                const amount = parseInt(document.getElementById('amount').value);
                if (!card || !amount) return alert('Заполните карту и сумму');
                await fetch('/api/balance/topup', {{
                    method: 'POST',
                    headers: {{'Content-Type': 'application/json'}},
                    body: JSON.stringify({{user_id: userId, amount: amount, card_number: card}})
                }});
                document.getElementById('card').value = '';
                document.getElementById('amount').value = '';
                loadData();
            }}

            async function addProduct() {{
                const title = document.getElementById('prod-title').value;
                const price = parseInt(document.getElementById('prod-price').value);
                if (!title || !price) return alert('Введите название и цену');
                await fetch('/api/admin/products/add', {{
                    method: 'POST',
                    headers: {{'Content-Type': 'application/json'}},
                    body: JSON.stringify({{admin_id: userId, title: title, price: price}})
                }});
                document.getElementById('prod-title').value = '';
                document.getElementById('prod-price').value = '';
                loadData();
            }}

            loadData();
        </script>
    </body>
    </html>
    """

@app.get("/api/user/{user_id}")
def get_user(user_id: int):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT balance FROM users WHERE user_id = ?", (user_id,))
    row = cursor.fetchone()
    conn.close()
    return {"balance": row[0] if row else 0}

@app.post("/api/balance/topup")
def topup_balance(data: TopUpRequest):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT balance FROM users WHERE user_id = ?", (data.user_id,))
    row = cursor.fetchone()
    if row is None:
        cursor.execute("INSERT INTO users (user_id, balance) VALUES (?, ?)", (data.user_id, data.amount))
    else:
        cursor.execute("UPDATE users SET balance = ? WHERE user_id = ?", (row[0] + data.amount, data.user_id))
    conn.commit()
    conn.close()
    return {"status": "ok"}

@app.get("/api/products")
def get_products():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT id, title, price FROM products")
    rows = cursor.fetchall()
    conn.close()
    return {"products": [{"id": r[0], "title": r[1], "price": r[2]} for r in rows]}

@app.post("/api/admin/products/add")
def add_product(data: ProductRequest):
    if data.admin_id != ADMIN_ID:
        raise HTTPException(status_code=403, detail="Access denied")
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("INSERT INTO products (title, price) VALUES (?, ?)", (data.title, data.price))
    conn.commit()
    conn.close()
    return {"status": "ok"}
