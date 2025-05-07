from flask import Flask, render_template, request, redirect, url_for, session
import psycopg2
import psycopg2.extras
import os
import json
from functools import wraps

app = Flask(__name__)
app.secret_key = 'your_secret_key_here'

# PostgreSQL 接続設定
DB_URL = os.getenv("DATABASE_URL", "postgresql://yu_gi_oh_inventory_db_user:SulMEphNxN6FviTKMTRUm569rS7KVuHG@dpg-d0dkoqidbo4c738lkh6g-a.singapore-postgres.render.com/yu_gi_oh_inventory_db")
USER_FILE = 'users.json'

# ログイン保護デコレータ
def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not session.get('logged_in'):
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function

# ユーザー認証
def check_login(username, password):
    if not os.path.exists(USER_FILE):
        return False
    with open(USER_FILE, 'r', encoding='utf-8') as f:
        users = json.load(f)
    return users.get(username) == password

# データベース接続
def get_db_connection():
    return psycopg2.connect(DB_URL, cursor_factory=psycopg2.extras.DictCursor)

# アイテム取得
def get_items(show_zero=True, keyword=None, sort_by="name", sort_order="asc"):
    valid_sort_keys = ["name", "card_id", "rare", "stock"]
    valid_sort_orders = ["asc", "desc"]

    if sort_by not in valid_sort_keys:
        sort_by = "name"
    if sort_order not in valid_sort_orders:
        sort_order = "asc"

    conn = get_db_connection()
    cur = conn.cursor()

    # ✅ ここを変更：「defaultカテゴリの商品のみ」
    query = "SELECT * FROM items WHERE category = 'default'"
    params = []

    if not show_zero:
        query += " AND stock > 0"
    if keyword:
        query += " AND (LOWER(name) LIKE %s OR LOWER(card_id) LIKE %s OR LOWER(rare) LIKE %s)"
        k = f"%{keyword.lower()}%"
        params.extend([k, k, k])

    query += f" ORDER BY {sort_by} {sort_order.upper()}"
    cur.execute(query, params)
    items = cur.fetchall()
    conn.close()
    return items


# アイテム更新
def update_items(items):
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("DELETE FROM items WHERE category='default'")
    for item in items:
        cur.execute("""
            INSERT INTO items (name, card_id, rare, stock, category)
            VALUES (%s, %s, %s, %s, 'default')
        """, (item['name'], item['card_id'], item['rare'], item['stock']))
    conn.commit()
    conn.close()

# アイテム追加
def add_item(name, card_id, rare, stock):
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO items (name, card_id, rare, stock, category)
        VALUES (%s, %s, %s, %s, 'default')
    """, (name, card_id, rare, stock))
    conn.commit()
    conn.close()

# メイン画面
@app.route('/')
def index():
    per_page = int(request.args.get('per_page', 10))
    page = int(request.args.get('page', 1))
    show_zero = request.args.get('show_zero') == 'on'
    keyword = request.args.get('keyword', '')
    sort_by = request.args.get('sort_key', 'name')
    sort_order = request.args.get('sort_order', 'asc')

    all_items = get_items(show_zero=show_zero, keyword=keyword, sort_by=sort_by, sort_order=sort_order)
    total = len(all_items)
    start = (page - 1) * per_page
    end = start + per_page
    items = all_items[start:end]

    return render_template('index.html',
                           items=items,
                           per_page=per_page,
                           page=page,
                           total_pages=(total + per_page - 1) // per_page,
                           show_zero=show_zero,
                           keyword=keyword,
                           sort_key=sort_by,
                           sort_order=sort_order,
                           logged_in=session.get('logged_in'))

# 編集画面
@app.route('/edit', methods=['GET', 'POST'])
@login_required
def edit():
    if request.method == 'POST':
        items = []
        total = int(request.form.get('total_rows', 0))
        for i in range(total):
            if request.form.get(f'delete_{i}'):
                continue
            name = request.form.get(f'name_{i}', '').strip()
            card_id = request.form.get(f'card_id_{i}', '').strip()
            rare = request.form.get(f'rare_{i}', '').strip()
            stock = request.form.get(f'stock_{i}', '0').strip()
            if name and card_id:
                items.append({
                    'name': name,
                    'card_id': card_id,
                    'rare': rare,
                    'stock': int(stock) if stock.isdigit() else 0
                })

        add_name = request.form.get('add_name', '').strip()
        add_card_id = request.form.get('add_card_id', '').strip()
        add_rare = request.form.get('add_rare', '').strip()
        add_stock = request.form.get('add_stock', '0').strip()
        if add_name and add_card_id:
            items.append({
                'name': add_name,
                'card_id': add_card_id,
                'rare': add_rare,
                'stock': int(add_stock) if add_stock.isdigit() else 0
            })

        update_items(items)
        return redirect(url_for('edit'))

    # 🔍 GET: キーワード検索を反映
    keyword = request.args.get('keyword', '')
    items = get_items(keyword=keyword)
    return render_template('edit.html', items=items, keyword=keyword, filename='DB')


# ログイン
@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        if check_login(request.form['username'], request.form['password']):
            session['logged_in'] = True
            return redirect(url_for('index'))
        return render_template('login.html', error='ログイン失敗')
    return render_template('login.html')

# ログアウト
@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('index'))
@app.route('/delete/<card_id>')
@login_required
def delete(card_id):
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("DELETE FROM items WHERE card_id = %s", (card_id,))
    conn.commit()
    conn.close()
    return redirect(url_for('index'))

# 初期データ（開発用）
def seed_initial_data():
    sample_items = [
        {"name": "青眼の白龍", "card_id": "AC01-JP000", "rare": "Ultra", "stock": 3},
        {"name": "ブラック・マジシャン", "card_id": "DP16-JP001", "rare": "Super", "stock": 2},
        {"name": "サイバー・ドラゴン", "card_id": "SD38-JP001", "rare": "Normal", "stock": 1},
    ]
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM items")
    count = cur.fetchone()[0]
    if count == 0:
        for item in sample_items:
            cur.execute("""
                INSERT INTO items (name, card_id, rare, stock, category)
                VALUES (%s, %s, %s, %s, 'default')
            """, (item["name"], item["card_id"], item["rare"], item["stock"]))
        conn.commit()
        print("✅ 初期データの登録が完了しました")
    conn.close()

seed_initial_data()

if __name__ == '__main__':
    app.run(debug=True)
