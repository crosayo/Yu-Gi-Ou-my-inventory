from flask import Flask, render_template, request, redirect, url_for, session, abort
import psycopg2
import psycopg2.extras
import os
import json
from functools import wraps

app = Flask(__name__)
app.secret_key = 'your_secret_key_here'

DB_URL = os.getenv("DATABASE_URL", "postgresql://yu_gi_oh_inventory_db_user:SulMEphNxN6FviTKMTRUm569rS7KVuHG@dpg-d0dkoqidbo4c738lkh6g-a.singapore-postgres.render.com/yu_gi_oh_inventory_db")
USER_FILE = 'users.json'

# --- Utility Functions ---
def get_db_connection():
    return psycopg2.connect(DB_URL, cursor_factory=psycopg2.extras.DictCursor)

def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not session.get('logged_in'):
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function

def check_login(username, password):
    if not os.path.exists(USER_FILE):
        return False
    with open(USER_FILE, 'r', encoding='utf-8') as f:
        users = json.load(f)
    return users.get(username) == password

def card_id_in_results(items, keyword):
    for item in items:
        if keyword.lower() in item['card_id'].lower():
            return True
    return False

# --- Routes ---
@app.route('/')
def index():
    per_page = int(request.args.get('per_page', 10))
    page = int(request.args.get('page', 1))
    show_zero = request.args.get('show_zero') == 'on'
    keyword = request.args.get('keyword', '')
    sort_by = request.args.get('sort_key', 'name')
    sort_order = request.args.get('sort_order', 'asc')

    items = get_items(show_zero, keyword, sort_by, sort_order)
    total = len(items)
    paginated = items[(page - 1) * per_page : page * per_page]

    show_add_hint = False
    if keyword and items:
        has_exact_card_id = card_id_in_results(items, keyword)
        show_add_hint = not has_exact_card_id

    return render_template('index.html',
                           items=paginated,
                           per_page=per_page,
                           page=page,
                           total_pages=(total + per_page - 1) // per_page,
                           show_zero=show_zero,
                           keyword=keyword,
                           sort_key=sort_by,
                           sort_order=sort_order,
                           show_add_hint=show_add_hint,
                           logged_in=session.get('logged_in'))

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        if check_login(request.form['username'], request.form['password']):
            session['logged_in'] = True
            return redirect(url_for('index'))
        return render_template('login.html', error='ログイン失敗')
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('index'))

@app.route('/edit_item/<int:item_id>', methods=['GET', 'POST'])
@login_required
def edit_item(item_id):
    conn = get_db_connection()
    cur = conn.cursor()

    if request.method == 'POST':
        name = request.form['name'].strip()
        rare = request.form['rare'].strip()
        stock = request.form['stock'].strip()
        stock = int(stock) if stock.isdigit() else 0

        cur.execute("""
            UPDATE items
               SET name = %s,
                   rare = %s,
                   stock = %s
             WHERE id = %s
        """, (name, rare, stock, item_id))
        conn.commit()
        conn.close()
        return redirect(url_for('index'))

    cur.execute("SELECT * FROM items WHERE id = %s", (item_id,))
    item = cur.fetchone()
    conn.close()
    if not item:
        abort(404, "商品が見つかりませんでした")
    return render_template('edit_item.html', item=item)

@app.route('/add_item', methods=['GET', 'POST'])
@login_required
def add_item_page():
    if request.method == 'POST':
        name = request.form['name'].strip()
        card_id = request.form['card_id'].strip()
        rare = request.form['rare'].strip()
        stock = request.form['stock'].strip()
        stock = int(stock) if stock.isdigit() else 0

        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO items (name, card_id, rare, stock, category)
            VALUES (%s, %s, %s, %s, 'default')
        """, (name, card_id, rare, stock))
        conn.commit()
        conn.close()
        return redirect(url_for('index'))

    name_prefill = request.args.get('name', '')
    return render_template('add_item.html', prefill_name=name_prefill)

@app.route('/confirm_delete/<int:item_id>')
@login_required
def confirm_delete(item_id):
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT * FROM items WHERE id = %s", (item_id,))
    item = cur.fetchone()
    conn.close()
    if not item:
        abort(404, "商品が見つかりません")
    return render_template('confirm_delete.html', item=item)

@app.route('/delete/<int:item_id>', methods=['POST'])
@login_required
def delete(item_id):
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("DELETE FROM items WHERE id = %s", (item_id,))
    conn.commit()
    conn.close()
    return redirect(url_for('index'))

@app.route('/update_stock/<int:item_id>', methods=['POST'])
@login_required
def update_stock(item_id):
    delta = request.form.get('delta', type=int)
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT stock FROM items WHERE id = %s", (item_id,))
    result = cur.fetchone()
    if not result:
        conn.close()
        abort(404)
    new_stock = max(0, result['stock'] + (delta or 0))
    cur.execute("UPDATE items SET stock = %s WHERE id = %s", (new_stock, item_id))
    conn.commit()
    conn.close()
    return redirect(url_for('index'))

# --- Database operations ---
def get_items(show_zero=True, keyword=None, sort_by="name", sort_order="asc"):
    valid_sort_keys = ["name", "card_id", "rare", "stock"]
    if sort_by not in valid_sort_keys:
        sort_by = "name"
    if sort_order not in ["asc", "desc"]:
        sort_order = "asc"

    conn = get_db_connection()
    cur = conn.cursor()
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

# --- Seed initial data (development only) ---
def seed_initial_data():
    sample_items = [
        {"name": "青眼の白龍", "card_id": "AC01-JP000", "rare": "Ultra", "stock": 3},
        {"name": "ブラック・マジシャン", "card_id": "DP16-JP001", "rare": "Super", "stock": 2},
        {"name": "サイバー・ドラゴン", "card_id": "SD38-JP001", "rare": "Normal", "stock": 1},
    ]
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM items")
    if cur.fetchone()[0] == 0:
        for item in sample_items:
            cur.execute("""
                INSERT INTO items (name, card_id, rare, stock, category)
                VALUES (%s, %s, %s, %s, 'default')
            """, (item['name'], item['card_id'], item['rare'], item['stock']))
        conn.commit()
        print("✅ 初期データの登録が完了しました")
    conn.close()

seed_initial_data()

if __name__ == '__main__':
    app.run(debug=True)
