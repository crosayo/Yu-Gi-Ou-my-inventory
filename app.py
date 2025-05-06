from flask import Flask, render_template, request, redirect, url_for, session, abort
import csv
import os
import json
from functools import wraps

app = Flask(__name__)
app.secret_key = 'your_secret_key_here'

CSV_FOLDER = 'csv_data'
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

# 複数CSV読み込み
def load_all_items():
    items = []
    for filename in os.listdir(CSV_FOLDER):
        if filename.endswith('.csv'):
            path = os.path.join(CSV_FOLDER, filename)
            with open(path, newline='', encoding='utf-8-sig') as csvfile:
                reader = csv.DictReader(csvfile)
                for row in reader:
                    row['name'] = row.get('name', '').lstrip('\ufeff').strip()
                    row['filename'] = filename
                    row['card_id'] = row.get('card_id', '').strip()
                    row['rare'] = row.get('rare', '').strip()
                    try:
                        row['stock'] = int(row.get('stock', 0))
                    except ValueError:
                        row['stock'] = 0
                    items.append(row)
    return items

# 書き込み
def save_items_to_file(filename, items):
    path = os.path.join(CSV_FOLDER, filename)
    with open(path, 'w', newline='', encoding='utf-8') as csvfile:
        fieldnames = ['name', 'card_id', 'rare', 'stock']
        writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
        writer.writeheader()
        for item in items:
            writer.writerow({k: item.get(k, '') for k in fieldnames})

# トップページ
@app.route('/')
def index():
    all_items = load_all_items()

    # クエリ取得
    per_page = int(request.args.get('per_page', 10))
    page = int(request.args.get('page', 1))
    show_zero = request.args.get('show_zero') == 'on'
    search = request.args.get('keyword', '').lower()
    sort_by = request.args.get('sort_by', 'name')
    sort_order = request.args.get('sort_order', 'asc')

    # フィルタ処理
    if not show_zero:
        all_items = [item for item in all_items if item['stock'] > 0]
    if search:
        all_items = [item for item in all_items if search in item['name'].lower()]

    # ソート
    reverse = (sort_order == 'desc')
    all_items.sort(key=lambda x: x.get(sort_by, ''), reverse=reverse)

    # ページング
    total = len(all_items)
    start = (page - 1) * per_page
    end = start + per_page
    items = all_items[start:end]

    page_range_start = max(1, page - 2)
    page_range_end = min(page + 3, (total + per_page - 1) // per_page + 1)

    return render_template(
        'index.html',
        items=items,
        logged_in=session.get('logged_in'),
        per_page=per_page,
        page=page,
        total_pages=(total + per_page - 1) // per_page,
        show_zero=show_zero,
        keyword=search,
        sort_by=sort_by,
        sort_order=sort_order,
        page_range_start=page_range_start,
        page_range_end=page_range_end
    )

# ログイン
@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        if check_login(username, password):
            session['logged_in'] = True
            return redirect(url_for('index'))
        else:
            return render_template('login.html', error='ログイン失敗')
    return render_template('login.html')

# ログアウト
@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('index'))

# 編集画面
@app.route('/edit/<filename>', methods=['GET', 'POST'])
@login_required
def edit(filename):
    path = os.path.join(CSV_FOLDER, filename)
    if not os.path.exists(path):
        abort(404)

    if request.method == 'POST':
        items = []
        total = int(request.form.get('total_rows', 0))
        for i in range(total):
            if request.form.get(f'delete_{i}'):
                continue

            name = request.form.get(f'name_{i}', '').strip()
            card_id = request.form.get(f'card_id_{i}', '').strip()
            rare = request.form.get(f'rare_{i}', '').strip()
            stock_raw = request.form.get(f'stock_{i}', '0').strip()

            if name and card_id:
                try:
                    stock = int(stock_raw)
                    if stock < 0:
                        stock = 0
                except ValueError:
                    stock = 0

                items.append({
                    'name': name,
                    'card_id': card_id,
                    'rare': rare,
                    'stock': stock
                })

        # 新規商品追加
        add_name = request.form.get('add_name', '').strip()
        add_card_id = request.form.get('add_card_id', '').strip()
        add_rare = request.form.get('add_rare', '').strip()
        add_stock = request.form.get('add_stock', '0').strip()

        if add_name and add_card_id:
            try:
                stock = int(add_stock)
                if stock < 0:
                    stock = 0
            except ValueError:
                stock = 0
            items.append({
                'name': add_name,
                'card_id': add_card_id,
                'rare': add_rare,
                'stock': stock
            })

        save_items_to_file(filename, items)
        return redirect(url_for('index'))

    # GET: 編集対象読み込み
    items = []
    with open(path, newline='', encoding='utf-8-sig') as csvfile:  # ✅ 修正箇所
        reader = csv.DictReader(csvfile)
        for row in reader:
            # BOM対策
            row['name'] = row.get('name') or row.get('\ufeffname', '')
            row['card_id'] = row.get('card_id', '')
            row['rare'] = row.get('rare', '')
            try:
                row['stock'] = int(row.get('stock', 0))
            except ValueError:
                row['stock'] = 0
            items.append(row)

    return render_template('edit.html', items=items, filename=filename)

if __name__ == '__main__':
    app.run(debug=True)
