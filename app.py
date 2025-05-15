from flask import Flask, render_template, request, redirect, url_for, session, abort, make_response, flash
import psycopg2
import psycopg2.extras
import os
import json
from functools import wraps
import io
import csv
import datetime
import traceback
from werkzeug.utils import secure_filename

app = Flask(__name__)
app.secret_key = 'your_secret_key_here'
UPLOAD_FOLDER = 'uploads'
ALLOWED_EXTENSIONS = {'csv'}
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

if not os.path.exists(UPLOAD_FOLDER):
    os.makedirs(UPLOAD_FOLDER)

DB_URL = os.getenv("DATABASE_URL", "postgresql://yu_gi_oh_inventory_db_user:SulMEphNxN6FviTKMTRUm569rS7KVuHG@dpg-d0dkoqidbo4c738lkh6g-a.singapore-postgres.render.com/yu_gi_oh_inventory_db")
USER_FILE = 'users.json'

# --- レアリティ定義 (ユーザー指示反映版) ---
DEFINED_RARITIES = [
    "N", "R", "SR", "UR", "SE", "PSE", "UL", "GR", "HR",
    "N-P", "SR-P", "UR-P", "SE-P", "P", # Parallel を P に統合
    "KC", "M", "CR", "EXSE", "20thSE", "QCSE",
    "NR", "HP",
    "GSE", # G-Secret
    "Ten Thousand Secret",
    "Ultra RED Ver.", "Ultra BLUE Ver.",
    "Secret BLUE Ver.",
    "Ultimate(Secret)",
    "Millennium-Ultra",
    "不明", # 「レアリティ」という文字列だった場合など
    "その他"
]

RARITY_CONVERSION_MAP = {
    # 基本的な表記揺れ
    'nomal': 'N', 'Nomal': 'N', 'Normal': 'N', 'ノーマル': 'N',
    'Rare': 'R', 'レア': 'R',
    'Super': 'SR', 'スーパー': 'SR', 'SR(スーパー)': 'SR', 'スーパーレア': 'SR',
    'Ultra': 'UR', 'ウルトラ': 'UR', 'UR(ウルトラ)': 'UR', 'ウルトラレア': 'UR',
    'Secret': 'SE', 'シークレット': 'SE', 'SE(シークレット)': 'SE', 'シークレットレア': 'SE',
    'Prismatic Secret': 'PSE', 'プリズマティックシークレット': 'PSE', 'PSE(プリズマティックシークレット)': 'PSE', 'プリズマティックシークレットレア': 'PSE',
    'Ultimate': 'UL', 'アルティメット': 'UL', 'UL(アルティメット)': 'UL', 'Relief': 'UL', 'レリーフ': 'UL', 'アルティメットレア': 'UL',
    'Gold': 'GR', 'ゴールド': 'GR', 'ゴールドレア': 'GR',
    'Holographic': 'HR', 'ホログラフィック': 'HR', 'ホログラフィックレア': 'HR',
    'Normal Parallel': 'N-P', 'ノーマルパラレル': 'N-P', 'N-Parallel': 'N-P', 'Nパラ': 'N-P',
    'KC Rare': 'KC', 'KCレア': 'KC', 'KCR': 'KC',
    'Millennium': 'M', 'ミレニアム': 'M', 'ミレニアムレア': 'M',
    'Collectors': 'CR', 'コレクターズ': 'CR', 'コレクターズレア': 'CR',
    'Extra Secret': 'EXSE', 'エクストラシークレット': 'EXSE', 'Ex-Secret': 'EXSE', 'エクストラシークレットレア': 'EXSE',
    '20th Secret': '20thSE', '20thシークレット': '20thSE', '20thSE(20thシークレット)': '20thSE', '20thシークレットレア': '20thSE',
    'Quarter Century Secret': 'QCSE', 'クォーターセンチュリーシークレット': 'QCSE', 'クォーターセンチュリーシークレットレア': 'QCSE',
    'N-Rare': 'NR',
    'Holographic-Parallel': 'HP',
    # ユーザー指示による新規追加・統合
    'Parallel': 'P',
    '（「キ」＝玉偏に幾） Rare': 'R', # Rに統合
    'G-Secret': 'GSE',
    'Ultra-Parallel': 'UR-P', 
    'UR-Parallel': 'UR-P',    
    'Super-Parallel': 'SR-P', 
    # 特殊ケース・その他へ
    '（エド・フェニックス仕様）': 'その他',
    '（真帝王降臨）': 'その他',
    '（オレンジ）': 'その他',
    '（黄）': 'その他',
    '（緑）': 'その他',
    'レアリティ': '不明', 
}

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
    if not items: 
        return False
    for item in items:
        if item and 'card_id' in item and isinstance(item['card_id'], str):
            if keyword.lower() in item['card_id'].lower():
                return True
    return False

def allowed_file(filename):
    return '.' in filename and \
           filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

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
    paginated_items = items[(page - 1) * per_page : page * per_page] if per_page > 0 else items

    show_add_hint = False
    if keyword and paginated_items:
        has_exact_card_id = card_id_in_results(paginated_items, keyword)
        show_add_hint = not has_exact_card_id

    return render_template('index.html',
                           items=paginated_items,
                           per_page=per_page,
                           page=page,
                           total_pages=(total + per_page - 1) // per_page if per_page > 0 else 1,
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
        return render_template('login.html', error='ユーザー名またはパスワードが正しくありません。')
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
        rare_select = request.form.get('rare_select')
        rare_custom = request.form.get('rare_custom', '').strip()
        rare = rare_custom if rare_select == 'その他' and rare_custom else rare_select
        stock_str = request.form['stock'].strip()
        stock = int(stock_str) if stock_str.isdigit() else 0
        category = request.form.get('category', '').strip()

        if not name or not rare: 
            flash('名前とレアリティは必須です。', 'danger')
            cur.execute("SELECT * FROM items WHERE id = %s", (item_id,))
            item = cur.fetchone()
            conn.close()
            if not item:
                abort(404, "商品が見つかりませんでした。")
            return render_template('edit_item.html', item=item, rarities=DEFINED_RARITIES, logged_in=session.get('logged_in'))
        
        try:
            cur.execute("""
                UPDATE items
                   SET name = %s,
                       rare = %s,
                       stock = %s,
                       category = %s
                 WHERE id = %s
            """, (name, rare, stock, category, item_id))
            conn.commit()
            flash('商品情報が更新されました。', 'success')
        except psycopg2.Error as e:
            conn.rollback()
            error_message = f"データベース更新エラー (商品ID: {item_id}): {e}"
            detailed_error = traceback.format_exc()
            print(f"ERROR: {error_message}\n{detailed_error}")
            flash(error_message, 'danger')
        except Exception as e:
            conn.rollback()
            error_message = f"予期せぬエラー (商品ID: {item_id}): {e}"
            detailed_error = traceback.format_exc()
            print(f"ERROR: {error_message}\n{detailed_error}")
            flash(error_message, 'danger')
        finally:
            conn.close()
        return redirect(url_for('index'))

    cur.execute("SELECT * FROM items WHERE id = %s", (item_id,))
    item = cur.fetchone()
    conn.close()
    if not item:
        abort(404, "商品が見つかりませんでした。")
    return render_template('edit_item.html', item=item, rarities=DEFINED_RARITIES, logged_in=session.get('logged_in'))

@app.route('/add_item', methods=['GET', 'POST'])
@login_required
def add_item_page():
    if request.method == 'POST':
        name = request.form['name'].strip()
        card_id = request.form.get('card_id', '').strip() 
        rare_select = request.form.get('rare_select')
        rare_custom = request.form.get('rare_custom', '').strip()
        rare = rare_custom if rare_select == 'その他' and rare_custom else rare_select
        stock_str = request.form['stock'].strip()
        stock = int(stock_str) if stock_str.isdigit() else 0
        category = request.form.get('category', '').strip()

        if not name or not rare: 
            flash('名前とレアリティは必須です。カードIDは任意です。', 'danger')
            return render_template('add_item.html', 
                                   prefill_name=name,
                                   prefill_card_id=card_id,
                                   prefill_category=category,
                                   prefill_stock=stock_str,
                                   rarities=DEFINED_RARITIES,
                                   selected_rarity=rare_select,
                                   custom_rarity_value=rare_custom,
                                   logged_in=session.get('logged_in'))

        conn = get_db_connection()
        cur = conn.cursor()
        try:
            # card_idが空の場合、空文字列 '' をDBへ
            cur.execute("""
                INSERT INTO items (name, card_id, rare, stock, category)
                VALUES (%s, %s, %s, %s, %s)
            """, (name, card_id if card_id else '', rare, stock, category if category else 'default')) 
            conn.commit()
            flash('商品が追加されました。', 'success')
        except psycopg2.Error as e:
            conn.rollback()
            error_message = f"データベース登録エラー (カード名: {name}, カードID: {card_id or 'N/A'}): {e}"
            detailed_error = traceback.format_exc()
            print(f"ERROR: {error_message}\n{detailed_error}")
            flash(error_message, 'danger')
        except Exception as e:
            conn.rollback()
            error_message = f"予期せぬエラー (カード名: {name}, カードID: {card_id or 'N/A'}): {e}"
            detailed_error = traceback.format_exc()
            print(f"ERROR: {error_message}\n{detailed_error}")
            flash(error_message, 'danger')
        finally:
            conn.close()
        return redirect(url_for('index'))

    name_prefill = request.args.get('name', '')
    return render_template('add_item.html', 
                           prefill_name=name_prefill, 
                           rarities=DEFINED_RARITIES, 
                           logged_in=session.get('logged_in'))

@app.route('/confirm_delete/<int:item_id>')
@login_required
def confirm_delete(item_id):
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT * FROM items WHERE id = %s", (item_id,))
    item = cur.fetchone()
    conn.close()
    if not item:
        abort(404, "商品が見つかりません。")
    return render_template('confirm_delete.html', item=item, logged_in=session.get('logged_in'))

@app.route('/delete/<int:item_id>', methods=['POST'])
@login_required
def delete(item_id):
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        cur.execute("DELETE FROM items WHERE id = %s", (item_id,))
        conn.commit()
        flash('商品が削除されました。', 'info')
    except psycopg2.Error as e:
        conn.rollback()
        error_message = f"データベース削除エラー (商品ID: {item_id}): {e}"
        detailed_error = traceback.format_exc()
        print(f"ERROR: {error_message}\n{detailed_error}")
        flash(error_message, 'danger')
    except Exception as e:
        conn.rollback()
        error_message = f"予期せぬ削除エラー (商品ID: {item_id}): {e}"
        detailed_error = traceback.format_exc()
        print(f"ERROR: {error_message}\n{detailed_error}")
        flash(error_message, 'danger')
    finally:
        conn.close()
    return redirect(url_for('index'))

@app.route('/update_stock/<int:item_id>', methods=['POST'])
@login_required
def update_stock(item_id):
    delta = request.form.get('delta', type=int)
    if delta is None:
        abort(400, "不正なリクエストです。")

    conn = get_db_connection()
    cur = conn.cursor()
    try:
        cur.execute("SELECT stock FROM items WHERE id = %s", (item_id,))
        result = cur.fetchone()
        if not result:
            conn.close()
            abort(404, "商品が見つかりません。")
        
        new_stock = max(0, result['stock'] + delta)
        cur.execute("UPDATE items SET stock = %s WHERE id = %s", (new_stock, item_id))
        conn.commit()
    except psycopg2.Error as e:
        conn.rollback()
        error_message = f"在庫更新エラー (商品ID: {item_id}): {e}"
        detailed_error = traceback.format_exc()
        print(f"ERROR: {error_message}\n{detailed_error}")
        flash(error_message, 'danger')
    except Exception as e:
        conn.rollback()
        error_message = f"予期せぬ在庫更新エラー (商品ID: {item_id}): {e}"
        detailed_error = traceback.format_exc()
        print(f"ERROR: {error_message}\n{detailed_error}")
        flash(error_message, 'danger')
    finally:
        conn.close()
    return redirect(request.referrer or url_for('index'))

@app.route('/download_csv')
@login_required
def download_csv():
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT id, name, card_id, rare, stock, category FROM items ORDER BY id")
    items = cur.fetchall()
    conn.close()

    si = io.StringIO()
    si.write('\ufeff') 
    cw = csv.writer(si)
    
    headers = ['ID', '名前', 'カードID', 'レアリティ', '在庫数', 'カテゴリ']
    column_keys = ['id', 'name', 'card_id', 'rare', 'stock', 'category']
    cw.writerow(headers)

    for item in items:
        row_data = [item[key] if key != 'card_id' or item[key] is not None else '' for key in column_keys]
        cw.writerow(row_data)

    output = make_response(si.getvalue())
    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"yugioh_inventory_backup_{timestamp}.csv"
    output.headers["Content-Disposition"] = f"attachment; filename={filename}"
    output.headers["Content-type"] = "text/csv; charset=utf-8"
    return output

def get_items(show_zero=True, keyword=None, sort_by="name", sort_order="asc"):
    valid_sort_keys = ["name", "card_id", "rare", "stock", "id", "category"] 
    if sort_by not in valid_sort_keys:
        sort_by = "name"
    if sort_order not in ["asc", "desc"]:
        sort_order = "asc"

    conn = get_db_connection()
    cur = conn.cursor()
    query_parts = ["SELECT * FROM items"] 
    params = []
    conditions = []

    if not show_zero:
        conditions.append("stock > 0")
    if keyword:
        # card_id が空文字列 '' の場合も検索できるように調整
        # (LOWER(card_id) LIKE %s OR card_id = '') のようにするか、
        # キーワードが空の場合に card_id = '' も検索対象とするかなど検討が必要。
        # ここでは、ひとまず card_id IS NOT NULL の条件を維持しつつ、空文字列も検索できるようにする。
        conditions.append("(LOWER(name) LIKE %s OR LOWER(card_id) LIKE %s OR LOWER(rare) LIKE %s OR LOWER(category) LIKE %s)")
        k = f"%{keyword.lower()}%"
        params.extend([k, k, k, k])
    
    if conditions:
        query_parts.append("WHERE " + " AND ".join(conditions))
    
    query = " ".join(query_parts)
    query += f" ORDER BY {sort_by} {sort_order.upper()}"
    
    cur.execute(query, params)
    items = cur.fetchall()
    conn.close()
    return items

@app.route('/admin/unify_rarities', methods=['GET', 'POST'])
@login_required
def admin_unify_rarities():
    if request.method == 'POST':
        conn = None
        updated_count_total = 0
        try:
            conn = get_db_connection()
            cur = conn.cursor()
            
            for old_rare, new_rare in RARITY_CONVERSION_MAP.items():
                cur.execute("UPDATE items SET rare = %s WHERE LOWER(rare) = LOWER(%s) AND rare != %s", (new_rare, old_rare, new_rare))
                updated_count_total += cur.rowcount
            
            conn.commit()
            if updated_count_total > 0:
                flash(f'{updated_count_total}件のレアリティ表記をデータベース内で更新/確認しました。', 'success')
            else:
                flash('レアリティ表記の更新対象はありませんでした。または、既に統一済みか、変換ルールに該当しませんでした。', 'info')
        except psycopg2.Error as e:
            if conn:
                conn.rollback()
            error_message = f"レアリティ統一中にデータベースエラー: {e}"
            detailed_error = traceback.format_exc()
            print(f"ERROR: {error_message}\n{detailed_error}")
            flash(error_message, 'danger')
        except Exception as e:
            if conn:
                conn.rollback()
            error_message = f"レアリティ統一中に予期せぬエラー: {e}"
            detailed_error = traceback.format_exc()
            print(f"ERROR: {error_message}\n{detailed_error}")
            flash(error_message, 'danger')
        finally:
            if conn:
                conn.close()
        return redirect(url_for('admin_unify_rarities'))

    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT DISTINCT rare FROM items ORDER BY rare")
    current_db_rarities = [row['rare'] for row in cur.fetchall() if row['rare']]
    conn.close()

    return render_template('admin_unify_rarities.html', 
                           rarity_map=RARITY_CONVERSION_MAP, 
                           defined_rarities=DEFINED_RARITIES,
                           current_db_rarities=current_db_rarities,
                           logged_in=session.get('logged_in'))

@app.route('/admin/import_csv', methods=['GET', 'POST'])
@login_required
def admin_import_csv():
    if request.method == 'POST':
        if 'csv_files' not in request.files:
            flash('ファイルが選択されていません。', 'warning')
            return redirect(request.url)
        
        files = request.files.getlist('csv_files')
        
        if not files or all(f.filename == '' for f in files):
            flash('ファイルが選択されていません。', 'warning')
            return redirect(request.url)

        total_files_processed = 0
        total_rows_overall = 0
        total_cards_added_overall = 0
        total_cards_updated_overall = 0
        total_cards_skipped_overall = 0
        error_files_details = {} 

        conn = get_db_connection()
        cur = conn.cursor()

        try:
            for file_index, file in enumerate(files):
                if file and allowed_file(file.filename):
                    filename = secure_filename(file.filename)
                    category_name = os.path.splitext(filename)[0]
                    total_files_processed += 1
                    
                    file_rows_processed = 0
                    file_cards_added = 0
                    file_cards_updated = 0
                    file_cards_skipped = 0
                    current_csv_row_num = 0 

                    print(f"INFO: Processing file: {filename}")

                    try:
                        stream = io.StringIO(file.stream.read().decode("utf-8-sig"), newline=None)
                        csv_reader = csv.DictReader(stream)

                        if not csv_reader.fieldnames or not ('name' in csv_reader.fieldnames and 'rare' in csv_reader.fieldnames):
                            err_msg = f"ヘッダー不正 ('name', 'rare' 列が必要)。"
                            print(f"ERROR: File '{filename}': {err_msg}")
                            if filename not in error_files_details: error_files_details[filename] = []
                            error_files_details[filename].append(err_msg)
                            continue
                        
                        for row_idx, row in enumerate(csv_reader):
                            current_csv_row_num = row_idx + 1
                            total_rows_overall += 1
                            file_rows_processed += 1

                            card_name = row.get('name', '').strip()
                            card_id_csv = row.get('card_id', '').strip() 
                            raw_rarity = row.get('rare', '').strip()
                            stock_csv_str = row.get('stock', '0').strip()
                            
                            try:
                                stock_csv = int(stock_csv_str) if stock_csv_str else 0
                            except ValueError:
                                stock_csv = 0
                                print(f"WARNING: File '{filename}' Row {current_csv_row_num}: Invalid stock value '{stock_csv_str}', using 0.")

                            if not card_name or not raw_rarity: 
                                print(f"SKIPPING: File '{filename}' Row {current_csv_row_num}: Missing required data (name or rarity). Row: {row}")
                                continue

                            converted_rarity = raw_rarity 
                            raw_rarity_lower = raw_rarity.lower()
                            for map_key, map_value in RARITY_CONVERSION_MAP.items():
                                if map_key.lower() == raw_rarity_lower:
                                    converted_rarity = map_value
                                    break
                            
                            if converted_rarity not in DEFINED_RARITIES:
                                if converted_rarity: 
                                    print(f"INFO: File '{filename}' Row {current_csv_row_num}: Rarity '{raw_rarity}' (becomes '{converted_rarity}') not in defined list, using 'その他'.")
                                    converted_rarity = 'その他'
                                else: 
                                    print(f"WARNING: File '{filename}' Row {current_csv_row_num}: Rarity is empty, using 'その他'.")
                                    converted_rarity = 'その他'
                            
                            # card_idが空の場合は空文字列 '' として扱う
                            final_card_id = card_id_csv if card_id_csv else ''

                            existing_card = None
                            # card_idが空文字列でない場合のみ、DBで既存カードを検索
                            if final_card_id: 
                                cur.execute("SELECT id, name, rare, stock, category FROM items WHERE card_id = %s", (final_card_id,))
                                existing_card = cur.fetchone()
                            
                            if existing_card:
                                if (existing_card['name'] != card_name or
                                    existing_card['rare'] != converted_rarity or
                                    existing_card['category'] != category_name):
                                    cur.execute("""
                                        UPDATE items SET name = %s, rare = %s, category = %s 
                                        WHERE id = %s
                                    """, (card_name, converted_rarity, category_name, existing_card['id']))
                                    file_cards_updated += 1
                                else:
                                    file_cards_skipped +=1
                            else:
                                # 新規登録時、card_idは final_card_id (空文字列の可能性あり) を使用
                                print(f"INFO: File '{filename}' Row {current_csv_row_num}: Adding new card. Name: {card_name}, CardID: '{final_card_id or 'N/A (empty string)'}'")
                                cur.execute("""
                                    INSERT INTO items (name, card_id, rare, stock, category)
                                    VALUES (%s, %s, %s, %s, %s)
                                """, (card_name, final_card_id, converted_rarity, stock_csv, category_name))
                                file_cards_added += 1
                        
                        total_cards_added_overall += file_cards_added
                        total_cards_updated_overall += file_cards_updated
                        total_cards_skipped_overall += file_cards_skipped
                        print(f"INFO: File '{filename}' processed. Added: {file_cards_added}, Updated: {file_cards_updated}, Skipped: {file_cards_skipped}. Total rows in file: {file_rows_processed}")

                    except UnicodeDecodeError as e_decode:
                        err_msg = f"文字コードエラー: {e_decode}"
                        print(f"ERROR: File '{filename}': {err_msg}\n{traceback.format_exc()}")
                        if filename not in error_files_details: error_files_details[filename] = []
                        error_files_details[filename].append(err_msg)
                    except csv.Error as e_csv:
                        err_msg = f"CSV解析エラー (行 {current_csv_row_num} 付近): {e_csv}"
                        print(f"ERROR: File '{filename}': {err_msg}\n{traceback.format_exc()}")
                        if filename not in error_files_details: error_files_details[filename] = []
                        error_files_details[filename].append(err_msg)
                    except psycopg2.Error as e_db:
                        conn.rollback() # このファイルのここまでのDB操作をロールバック
                        err_msg = f"DBエラー (ファイル '{filename}' 行 {current_csv_row_num} 付近): {e_db}"
                        print(f"ERROR: {err_msg}\n{traceback.format_exc()}")
                        if filename not in error_files_details: error_files_details[filename] = []
                        error_files_details[filename].append(err_msg)
                        # このファイルの処理を中断し、次のファイルの処理に移る
                        # ロールバックしたので、次のファイルのために再度接続やカーソルが必要な場合があるが、
                        # psycopg2 の接続オブジェクトは通常、ロールバック後も再利用可能
                        # ただし、エラーによっては接続自体が不安定になる可能性もゼロではない
                        # より堅牢にするなら、ファイルごとに接続を確立し直すことも検討できるが、パフォーマンスに影響
                        continue 
                    except Exception as e_general:
                        err_msg = f"予期せぬエラー (ファイル '{filename}' 行 {current_csv_row_num} 付近): {e_general}"
                        print(f"ERROR: {err_msg}\n{traceback.format_exc()}")
                        if filename not in error_files_details: error_files_details[filename] = []
                        error_files_details[filename].append(err_msg)
                        continue

                elif file and not allowed_file(file.filename):
                    err_msg = "拡張子不正"
                    print(f"WARNING: File '{file.filename}' skipped: {err_msg}")
                    if file.filename not in error_files_details: error_files_details[file.filename] = []
                    error_files_details[file.filename].append(err_msg)
            
            conn.commit() 
            
            summary_message = f"CSVインポート処理完了。処理ファイル数: {total_files_processed}。"
            summary_message += f" 総行数: {total_rows_overall}。"
            summary_message += f" 追加: {total_cards_added_overall}件。"
            summary_message += f" 更新: {total_cards_updated_overall}件。"
            summary_message += f" スキップ: {total_cards_skipped_overall}件。"

            if error_files_details:
                summary_message += " エラー発生ファイル: "
                error_file_names = []
                for fname, reasons in error_files_details.items():
                    reason_summary = reasons[0] if reasons else "不明なエラー"
                    error_file_names.append(f"{fname} ({reason_summary})")
                summary_message += ", ".join(error_file_names)
                summary_message += "。詳細はサーバーログを確認してください。"
                flash(summary_message, 'warning')
            else:
                flash(summary_message, 'success')

        except psycopg2.Error as e_final_db:
            if conn:
                conn.rollback()
            error_message = f"CSVインポート最終処理中にデータベースエラー: {e_final_db}"
            print(f"ERROR: {error_message}\n{traceback.format_exc()}")
            flash(error_message, 'danger')
        except Exception as e_final_general:
            if conn:
                conn.rollback()
            error_message = f"CSVインポート最終処理中に予期せぬエラー: {e_final_general}"
            print(f"ERROR: {error_message}\n{traceback.format_exc()}")
            flash(error_message, 'danger')
        finally:
            if conn:
                conn.close()
        
        return redirect(url_for('admin_import_csv'))

    return render_template('admin_import_csv.html', logged_in=session.get('logged_in'))

def seed_initial_data():
    sample_items = [
        {"name": "青眼の白龍", "card_id": "AC01-JP000", "rare": "UR", "stock": 3, "category": "ヒストリーアーカイブコレクション"},
        {"name": "ブラック・マジシャン", "card_id": "DP16-JP001", "rare": "SR", "stock": 2, "category": "デュエリストパック－王の記憶編－"},
        {"name": "サイバー・ドラゴン", "card_id": "SD38-JP001", "rare": "N", "stock": 1, "category": "ストラクチャーデッキ－サイバー流の後継者－"},
    ]
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM items") 
    if cur.fetchone()[0] == 0:
        for item in sample_items:
            cur.execute("""
                INSERT INTO items (name, card_id, rare, stock, category)
                VALUES (%s, %s, %s, %s, %s)
            """, (item['name'], item['card_id'], item['rare'], item['stock'], item['category']))
        conn.commit()
        print("✅ 初期データの登録が完了しました。")
    conn.close()

if __name__ == '__main__':
    # seed_initial_data()
    app.run(debug=True)
