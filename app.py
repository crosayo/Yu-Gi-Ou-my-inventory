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
from pykakasi import kakasi

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'your_very_secure_default_secret_key_for_development_123!')
UPLOAD_FOLDER = 'uploads'
ALLOWED_EXTENSIONS = {'csv'}
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

if not os.path.exists(UPLOAD_FOLDER):
    os.makedirs(UPLOAD_FOLDER)

DB_URL = os.environ.get("DATABASE_URL", "postgresql://yu_gi_oh_inventory_db_user:SulMEphNxN6FviTKMTRUm569rS7KVuHG@dpg-d0dkoqidbo4c738lkh6g-a.singapore-postgres.render.com/yu_gi_oh_inventory_db")
USER_FILE = 'users.json'

kks_hira_converter = kakasi()
kks_hira_converter.setMode("J", "H")
kks_hira_converter.setMode("K", "H")
kks_hira_converter.setMode("s", False)
kks_hira_converter.setMode("C", False)

kks_kata_converter = kakasi()
kks_kata_converter.setMode("J", "K")
kks_kata_converter.setMode("H", "K")
kks_kata_converter.setMode("s", False)
kks_kata_converter.setMode("C", False)

DEFINED_RARITIES = [
    "N", "R", "SR", "UR", "SE", "PSE", "UL", "GR", "HR",
    "N-P", "SR-P", "UR-P", "SE-P", "P",
    "KC", "M", "CR", "EXSE", "20thSE", "QCSE",
    "NR", "HP",
    "GSE", "Ten Thousand Secret",
    "Ultra RED Ver.", "Ultra BLUE Ver.",
    "Secret BLUE Ver.",
    "Ultimate(Secret)",
    "Millennium-Ultra",
    "不明",
    "その他"
]

RARITY_CONVERSION_MAP = {
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
    'Parallel': 'P',
    '（「キ」＝玉偏に幾） Rare': 'R',
    'G-Secret': 'GSE',
    'Ultra-Parallel': 'UR-P',
    'UR-Parallel': 'UR-P',
    'Super-Parallel': 'SR-P',
    '（エド・フェニックス仕様）': 'その他',
    '（真帝王降臨）': 'その他',
    '（オレンジ）': 'その他',
    '（黄）': 'その他',
    '（緑）': 'その他',
    'レアリティ': '不明',
    '（「セン」＝玉偏に旋）': 'その他',
    '（「こう」＝網頭に正） Rare': 'その他'
}

@app.context_processor
def inject_now():
    return {'now': datetime.datetime.now(datetime.timezone.utc)} # DeprecationWarning 対応

def get_db_connection():
    try:
        conn = psycopg2.connect(DB_URL, cursor_factory=psycopg2.extras.DictCursor)
        return conn
    except psycopg2.Error as e:
        print(f"FATAL: Database connection failed. DB_URL might be incorrect or database not accessible. Error: {e}")
        print(f"Used DB_URL: {DB_URL[:DB_URL.find('@') if '@' in DB_URL else 20]}...")
        raise

def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not session.get('logged_in'):
            flash('このページにアクセスするにはログインが必要です。', 'warning')
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function

def check_login(username, password):
    if not os.path.exists(USER_FILE):
        print(f"ERROR: User file '{USER_FILE}' not found.")
        flash(f"エラー: ユーザーファイル ({USER_FILE}) が見つかりません。管理者に連絡してください。", "danger")
        return False
    try:
        with open(USER_FILE, 'r', encoding='utf-8') as f:
            users = json.load(f)
        return users.get(username) == password
    except Exception as e:
        print(f"ERROR: Failed to load or parse user file '{USER_FILE}': {e}")
        flash(f"エラー: ユーザーファイルの読み込みに失敗しました。管理者に連絡してください。", "danger")
        return False

def card_id_in_results(items, keyword):
    if not items or not keyword:
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
    elif keyword and not paginated_items:
        show_add_hint = True

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
    if session.get('logged_in'):
        return redirect(url_for('index'))
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        if check_login(username, password):
            session['logged_in'] = True
            session['username'] = username
            flash('ログインしました。', 'success')
            return redirect(url_for('index'))
        else:
            flash('ユーザー名またはパスワードが正しくありません。', 'danger')
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.clear()
    flash('ログアウトしました。', 'info')
    return redirect(url_for('login'))

@app.route('/edit_item/<int:item_id>', methods=['GET', 'POST'])
@login_required
def edit_item(item_id):
    conn = get_db_connection()
    cur = conn.cursor()

    if request.method == 'POST':
        name = request.form.get('name', '').strip()
        rare_select = request.form.get('rare_select')
        rare_custom = request.form.get('rare_custom', '').strip()
        rare = rare_custom if rare_select == 'その他' and rare_custom else rare_select
        stock_str = request.form.get('stock', '0').strip()
        try:
            stock = int(stock_str) if stock_str else 0
        except ValueError:
            stock = 0
            flash('在庫数には数値を入力してください。', 'warning')
        category = request.form.get('category', '').strip()

        error_occurred_edit = False
        if not name:
            flash('名前は必須です。', 'danger')
            error_occurred_edit = True
        if not rare:
            flash('レアリティを選択または入力してください。', 'danger')
            error_occurred_edit = True
        
        if not error_occurred_edit:
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
                cur.close()
                conn.close()
                return redirect(url_for('index'))
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
        
        if cur and not cur.closed: cur.close()
        if conn and not conn.closed: conn.close()
        
        conn_retry = get_db_connection()
        cur_retry = conn_retry.cursor()
        cur_retry.execute("SELECT * FROM items WHERE id = %s", (item_id,))
        item_for_render = cur_retry.fetchone()
        cur_retry.close()
        conn_retry.close()
        if not item_for_render:
            abort(404, "商品が見つかりませんでした。")
        return render_template('edit_item.html', item=item_for_render, rarities=DEFINED_RARITIES, logged_in=session.get('logged_in'))

    cur.execute("SELECT * FROM items WHERE id = %s", (item_id,))
    item = cur.fetchone()
    cur.close()
    conn.close()
    if not item:
        abort(404, "商品が見つかりませんでした。")
    return render_template('edit_item.html', item=item, rarities=DEFINED_RARITIES, logged_in=session.get('logged_in'))

@app.route('/add_item', methods=['GET', 'POST'])
@login_required
def add_item_page():
    if request.method == 'POST':
        name = request.form.get('name', '').strip()
        card_id = request.form.get('card_id', '').strip()
        rare_select = request.form.get('rare_select')
        rare_custom = request.form.get('rare_custom', '').strip()
        rare = rare_custom if rare_select == 'その他' and rare_custom else rare_select
        stock_str = request.form.get('stock', '0').strip()
        try:
            stock = int(stock_str) if stock_str else 0
        except ValueError:
            stock = 0
            flash('在庫数には数値を入力してください。', 'warning')
        category = request.form.get('category', '').strip()

        error_occurred = False
        if not name:
            flash('名前は必須です。', 'danger')
            error_occurred = True
        if not rare:
            flash('レアリティを選択または入力してください。', 'danger')
            error_occurred = True
        
        if error_occurred:
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
            final_card_id = card_id if card_id else '' 
            cur.execute("""
                INSERT INTO items (name, card_id, rare, stock, category)
                VALUES (%s, %s, %s, %s, %s)
            """, (name, final_card_id, rare, stock, category if category else 'default')) 
            conn.commit()
            flash(f'商品「{name}」が追加されました。', 'success')
            cur.close()
            conn.close()
            return redirect(url_for('index'))
        except psycopg2.IntegrityError as e:
            conn.rollback()
            error_message = f"データベース登録エラー: カードID「{final_card_id}」は既に存在する可能性があります。詳細: {e}"
            detailed_error = traceback.format_exc()
            print(f"ERROR: {error_message}\n{detailed_error}")
            flash(error_message, 'danger')
        except psycopg2.Error as e:
            conn.rollback()
            error_message = f"データベース登録エラー (カード名: {name}, カードID: {final_card_id or 'N/A'}): {e}"
            detailed_error = traceback.format_exc()
            print(f"ERROR: {error_message}\n{detailed_error}")
            flash(error_message, 'danger')
        except Exception as e:
            conn.rollback()
            error_message = f"予期せぬエラー (カード名: {name}, カードID: {final_card_id or 'N/A'}): {e}"
            detailed_error = traceback.format_exc()
            print(f"ERROR: {error_message}\n{detailed_error}")
            flash(error_message, 'danger')
        finally:
            if cur and not cur.closed: cur.close()
            if conn and not conn.closed: conn.close()
        
        return render_template('add_item.html', 
                               prefill_name=name,
                               prefill_card_id=card_id,
                               prefill_category=category,
                               prefill_stock=stock_str,
                               rarities=DEFINED_RARITIES,
                               selected_rarity=rare_select,
                               custom_rarity_value=rare_custom,
                               logged_in=session.get('logged_in'))

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
    cur.close()
    conn.close()
    if not item:
        abort(404, "商品が見つかりませんでした。")
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
        if cur and not cur.closed: cur.close()
        if conn and not conn.closed: conn.close()
    return redirect(url_for('index'))

@app.route('/update_stock/<int:item_id>', methods=['POST'])
@login_required
def update_stock(item_id):
    delta = request.form.get('delta', type=int)
    if delta is None:
        flash('不正なリクエストです。', 'danger')
        return redirect(request.referrer or url_for('index'))

    conn = get_db_connection()
    cur = conn.cursor()
    try:
        cur.execute("SELECT stock FROM items WHERE id = %s", (item_id,))
        result = cur.fetchone()
        if not result:
            flash("商品が見つかりません。", 'warning')
        else:
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
        if cur and not cur.closed: cur.close()
        if conn and not conn.closed: conn.close()
    return redirect(request.referrer or url_for('index'))

@app.route('/download_csv')
@login_required
def download_csv():
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT id, name, card_id, rare, stock, category FROM items ORDER BY id")
    items = cur.fetchall()
    cur.close()
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
    timestamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%d_%H%M%S")
    filename = f"yugioh_inventory_backup_{timestamp}.csv"
    output.headers["Content-Disposition"] = f"attachment; filename={filename}"
    output.headers["Content-type"] = "text/csv; charset=utf-8"
    return output

def get_items(show_zero=True, keyword=None, sort_by="name", sort_order="asc"):
    valid_sort_keys = ["name", "card_id", "rare", "stock", "id", "category"] 
    if sort_by not in valid_sort_keys:
        sort_by = "name"
    if sort_order.lower() not in ["asc", "desc"]:
        sort_order = "asc"

    conn = get_db_connection()
    cur = conn.cursor()
    query_base = "SELECT * FROM items"
    conditions = []
    params = []

    if not show_zero:
        conditions.append("stock > 0")
    
    if keyword:
        keyword_lower_like = f"%{keyword.lower()}%"
        
        hira_result = kks_hira_converter.convert(keyword)
        keyword_hira = "".join([item['hira'] for item in hira_result])
        keyword_hira_like = f"%{keyword_hira.lower()}%" if keyword_hira else None

        kata_result = kks_kata_converter.convert(keyword)
        keyword_kata = "".join([item['kana'] for item in kata_result])
        keyword_kata_like = f"%{keyword_kata.lower()}%" if keyword_kata else None
        
        name_conditions_list = []
        name_params_list = []
        
        name_conditions_list.append("LOWER(name) LIKE %s")
        name_params_list.append(keyword_lower_like)
        
        if keyword_hira_like and keyword_hira.lower() != keyword.lower():
            name_conditions_list.append("LOWER(name) LIKE %s") 
            name_params_list.append(keyword_hira_like)
        
        if keyword_kata_like and keyword_kata.lower() != keyword.lower() and \
           (not keyword_hira or keyword_kata.lower() != keyword_hira.lower()):
            name_conditions_list.append("LOWER(name) LIKE %s")
            name_params_list.append(keyword_kata_like)

        name_search_clause_str = "(" + " OR ".join(name_conditions_list) + ")"
        
        other_column_conditions = [
            "LOWER(card_id) LIKE %s",
            "LOWER(rare) LIKE %s",
            "LOWER(category) LIKE %s"
        ]
        other_column_params = [keyword_lower_like] * len(other_column_conditions)

        all_search_conditions = [name_search_clause_str] + other_column_conditions
        conditions.append("(" + " OR ".join(all_search_conditions) + ")")
        params.extend(name_params_list)
        params.extend(other_column_params)
    
    if conditions:
        query_base += " WHERE " + " AND ".join(conditions)
    
    query_base += f" ORDER BY {sort_by} {sort_order.upper()}"
    
    cur.execute(query_base, tuple(params))
    items_result = cur.fetchall()
    cur.close()
    conn.close()
    return items_result

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
            if conn: conn.rollback()
            error_message = f"レアリティ統一中にデータベースエラー: {e}"
            detailed_error = traceback.format_exc()
            print(f"ERROR: {error_message}\n{detailed_error}")
            flash(error_message, 'danger')
        except Exception as e:
            if conn: conn.rollback()
            error_message = f"レアリティ統一中に予期せぬエラー: {e}"
            detailed_error = traceback.format_exc()
            print(f"ERROR: {error_message}\n{detailed_error}")
            flash(error_message, 'danger')
        finally:
            if conn and not conn.closed: 
                if 'cur' in locals() and cur and not cur.closed: cur.close()
                conn.close()
        return redirect(url_for('admin_unify_rarities'))

    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT DISTINCT rare FROM items ORDER BY rare")
    current_db_rarities = [row['rare'] for row in cur.fetchall() if row['rare']]
    cur.close()
    conn.close()

    return render_template('admin_unify_rarities.html', 
                           rarity_map=RARITY_CONVERSION_MAP, 
                           defined_rarities=DEFINED_RARITIES,
                           current_db_rarities=current_db_rarities,
                           logged_in=session.get('logged_in'))

# --- 一括登録機能のルート (骨子) ---
def get_items_by_category(category_keyword=None, page=1, per_page=20, sort_by="name", sort_order="asc"):
    """指定されたカテゴリのカード情報をページネーション付きで取得します。"""
    if not category_keyword:
        return [], 0 

    conn = get_db_connection()
    cur = conn.cursor()
    
    base_query = "SELECT * FROM items WHERE LOWER(category) LIKE %s"
    count_query = "SELECT COUNT(*) FROM items WHERE LOWER(category) LIKE %s"
    
    search_term = f"%{category_keyword.lower()}%"
    
    cur.execute(count_query, (search_term,))
    total_items_result = cur.fetchone()
    total_items = total_items_result['count'] if total_items_result else 0


    valid_sort_keys_batch = ["name", "card_id", "rare", "stock", "id"] 
    if sort_by not in valid_sort_keys_batch:
        sort_by = "name"
    if sort_order.lower() not in ["asc", "desc"]:
        sort_order = "asc"

    offset = (page - 1) * per_page
    query = f"{base_query} ORDER BY {sort_by} {sort_order.upper()} LIMIT %s OFFSET %s"
    
    cur.execute(query, (search_term, per_page, offset))
    items = cur.fetchall()
    
    cur.close()
    conn.close()
    return items, total_items

@app.route('/admin/batch_register', methods=['GET', 'POST'])
@login_required
def admin_batch_register():
    if request.method == 'POST':
        conn = None
        updated_count = 0
        try:
            conn = get_db_connection()
            with conn.cursor() as cur: # トランザクション管理のため
                for key, value in request.form.items():
                    if key.startswith('stock_item_'):
                        try:
                            item_id = int(key.split('_')[-1])
                            stock_count_str = value.strip()
                            # 在庫数が空または数値でない場合は0として扱う
                            stock_count = int(stock_count_str) if stock_count_str.isdigit() else 0
                            
                            # 既存の在庫数を取得 (比較のため、または在庫0でも更新する場合)
                            cur.execute("SELECT stock FROM items WHERE id = %s", (item_id,))
                            current_item = cur.fetchone()

                            if current_item and current_item['stock'] != stock_count: # 在庫数が変更された場合のみ更新
                                cur.execute("UPDATE items SET stock = %s WHERE id = %s", (stock_count, item_id))
                                updated_count += 1
                                print(f"INFO: Batch update - Item ID {item_id} stock updated to {stock_count}")
                            elif not current_item:
                                print(f"WARNING: Batch update - Item ID {item_id} not found in database.")
                        
                        except ValueError:
                            flash(f"ID {key.split('_')[-1]} の在庫数に不正な値「{value}」が入力されました。スキップします。", "warning")
                            print(f"WARNING: Batch update - Invalid stock value '{value}' for item_id {key.split('_')[-1]}")
                        except Exception as e_inner: # 個別のアイテム更新中の予期せぬエラー
                            conn.rollback() # このアイテムの更新はロールバック (ループは継続)
                            flash(f"ID {key.split('_')[-1]} の更新中にエラー: {e_inner}", "danger")
                            print(f"ERROR: Batch update inner loop for item_id {key.split('_')[-1]}: {e_inner}\n{traceback.format_exc()}")
                
                if updated_count > 0:
                    conn.commit()
                    flash(f"{updated_count}件のカードの在庫を一括更新しました。", "success")
                else:
                    flash("在庫が変更されたカードはありませんでした。", "info")

        except psycopg2.Error as e_db:
            if conn: conn.rollback()
            error_message = f"一括在庫更新中にデータベースエラー: {e_db}"
            print(f"ERROR: {error_message}\n{traceback.format_exc()}")
            flash(error_message, 'danger')
        except Exception as e_outer:
            if conn: conn.rollback()
            error_message = f"一括在庫更新中に予期せぬエラー: {e_outer}"
            print(f"ERROR: {error_message}\n{traceback.format_exc()}")
            flash(error_message, 'danger')
        finally:
            if conn and not conn.closed:
                conn.close()

        category_keyword = request.form.get('category_keyword_hidden', '') 
        return redirect(url_for('admin_batch_register', category_keyword=category_keyword, page=request.form.get('current_page', 1)))


    category_keyword = request.args.get('category_keyword', '')
    page = request.args.get('page', 1, type=int)
    per_page = 20 
    
    items_for_batch = []
    total_items = 0
    if category_keyword:
        items_for_batch, total_items = get_items_by_category(category_keyword, page, per_page)
        if not items_for_batch and page == 1: 
            flash(f"カテゴリ「{category_keyword}」に該当するカードは見つかりませんでした。", "info")

    total_pages = (total_items + per_page - 1) // per_page if per_page > 0 else 1

    return render_template('batch_register.html',
                           items=items_for_batch,
                           category_keyword=category_keyword,
                           page=page,
                           per_page=per_page,
                           total_pages=total_pages,
                           total_items=total_items,
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

        conn_outer = None 
        try:
            conn_outer = get_db_connection()
            
            for file_index, file in enumerate(files):
                file_processed_this_run = False 
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
                        with conn_outer.cursor() as cur: 
                            stream = io.StringIO(file.stream.read().decode("utf-8-sig"), newline=None)
                            csv_reader = csv.DictReader(stream)

                            required_headers = ['name', 'rare']
                            if not csv_reader.fieldnames or not all(h in csv_reader.fieldnames for h in required_headers):
                                err_msg = f"ヘッダー不正。必須列: {', '.join(required_headers)} が存在しません。"
                                print(f"ERROR: File '{filename}': {err_msg}")
                                if filename not in error_files_details: error_files_details[filename] = []
                                error_files_details[filename].append(err_msg)
                                continue 
                            
                            for row_idx, row in enumerate(csv_reader):
                                file_processed_this_run = True 
                                current_csv_row_num = row_idx + 1 
                                total_rows_overall += 1
                                file_rows_processed +=1

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
                                
                                final_card_id = card_id_csv if card_id_csv else ''

                                existing_card = None
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
                                    print(f"INFO: File '{filename}' Row {current_csv_row_num}: Adding new card. Name: {card_name}, CardID: '{final_card_id or 'N/A (empty string)'}'")
                                    cur.execute("""
                                        INSERT INTO items (name, card_id, rare, stock, category)
                                        VALUES (%s, %s, %s, %s, %s)
                                    """, (card_name, final_card_id, converted_rarity, stock_csv, category_name))
                                    file_cards_added += 1
                            
                        if file_processed_this_run: 
                            conn_outer.commit() 
                            total_cards_added_overall += file_cards_added
                            total_cards_updated_overall += file_cards_updated
                            total_cards_skipped_overall += file_cards_skipped
                            print(f"INFO: File '{filename}' processed and committed. Added: {file_cards_added}, Updated: {file_cards_updated}, Skipped: {file_cards_skipped}. Total rows in file: {file_rows_processed}")

                    except UnicodeDecodeError as e_decode:
                        if conn_outer and not conn_outer.closed: conn_outer.rollback() 
                        err_msg = f"文字コードエラー: {e_decode}"
                        print(f"ERROR: File '{filename}': {err_msg}\n{traceback.format_exc()}")
                        if filename not in error_files_details: error_files_details[filename] = []
                        error_files_details[filename].append(err_msg)
                    except csv.Error as e_csv: 
                        if conn_outer and not conn_outer.closed: conn_outer.rollback()
                        err_msg = f"CSV解析エラー (行 {current_csv_row_num} 付近): {e_csv}"
                        print(f"ERROR: File '{filename}': {err_msg}\n{traceback.format_exc()}")
                        if filename not in error_files_details: error_files_details[filename] = []
                        error_files_details[filename].append(err_msg)
                    except psycopg2.Error as e_db:
                        if conn_outer and not conn_outer.closed: conn_outer.rollback()
                        err_msg = f"DBエラー (ファイル '{filename}' 行 {current_csv_row_num} 付近): {e_db}"
                        print(f"ERROR: {err_msg}\n{traceback.format_exc()}")
                        if filename not in error_files_details: error_files_details[filename] = []
                        error_files_details[filename].append(err_msg)
                    except Exception as e_general:
                        if conn_outer and not conn_outer.closed: conn_outer.rollback()
                        err_msg = f"予期せぬエラー (ファイル '{filename}' 行 {current_csv_row_num} 付近): {e_general}"
                        print(f"ERROR: {err_msg}\n{traceback.format_exc()}")
                        if filename not in error_files_details: error_files_details[filename] = []
                        error_files_details[filename].append(err_msg)
                
                elif file and not allowed_file(file.filename): 
                    err_msg = "拡張子不正"
                    print(f"WARNING: File '{file.filename}' skipped: {err_msg}")
                    if file.filename not in error_files_details: error_files_details[file.filename] = []
                    error_files_details[file.filename].append(err_msg)
            
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

        except psycopg2.Error as e_db_outer: 
            if conn_outer and not conn_outer.closed: conn_outer.rollback()
            error_message = f"CSVインポート処理中にデータベースエラーが発生しました: {e_db_outer}"
            print(f"ERROR: {error_message}\n{traceback.format_exc()}")
            flash(error_message, 'danger')
        except Exception as e_general_outer:
            if conn_outer and not conn_outer.closed: conn_outer.rollback()
            error_message = f"CSVインポート処理中に予期せぬエラーが発生しました: {e_general_outer}"
            print(f"ERROR: {error_message}\n{traceback.format_exc()}")
            flash(error_message, 'danger')
        finally:
            if conn_outer and not conn_outer.closed:
                conn_outer.close()
        
        return redirect(url_for('admin_import_csv'))

    return render_template('admin_import_csv.html', logged_in=session.get('logged_in'))


def seed_initial_data():
    """初期データをデータベースに登録します（開発用）。"""
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
    cur.close()
    conn.close()

if __name__ == '__main__':
    # seed_initial_data()
    port = int(os.environ.get("PORT", 5000)) 
    app.run(debug=True, host='0.0.0.0', port=port)
