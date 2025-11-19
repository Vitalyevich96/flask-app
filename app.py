from flask import Flask, render_template, request, redirect, url_for, session, flash, jsonify, send_from_directory, Response, abort
import json
import os
import csv
from io import StringIO
from datetime import datetime, timedelta
from functools import wraps
import uuid
import requests
import pg8000

SERVICES = {
    'accounting': {
        'name': 'Бухгалтерское обслуживание',
        'description': 'Полное бухгалтерское сопровождение вашего бизнеса',
        'price': 'от 50 000 ₸/мес'
    },
    'tax_optimization': {
        'name': 'Налоговая оптимизация',
        'description': 'Легальное снижение налоговой нагрузки',
        'price': 'от 100 000 ₸'
    },
    'registration': {
        'name': 'Регистрация бизнеса',
        'description': 'Регистрация ИП и ТОО под ключ',
        'price': 'от 30 000 ₸'
    },
    'audit': {
        'name': 'Аудит и консалтинг',
        'description': 'Проверка финансовой отчетности и консультации',
        'price': 'от 150 000 ₸'
    },
    'payroll': {
        'name': 'Расчет заработной платы',
        'description': 'Кадровый учет и расчет зарплаты',
        'price': 'от 20 000 ₸/мес'
    },
    'reporting': {
        'name': 'Сдача отчетности',
        'description': 'Подготовка и сдача налоговой отчетности',
        'price': 'от 40 000 ₸'
    }
}


app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'your-secret-key-change-this-in-production')

DATABASE_URL = os.environ.get('POSTGRES_URL', 'postgresql://neondb_owner:npg_EDzFntuY13CI@ep-tiny-lab-agdp3p2o-pooler.c-2.eu-central-1.aws.neon.tech/neondb?sslmode=require')

ADMIN_LOGIN = 'admin'
ADMIN_PASSWORD = 'admin1802'

TELEGRAM_BOT_TOKEN = '7561142289:AAFVFusO4EQqxsz4-oDJjVHUPEfhIarlAcs'

def set_telegram_webhook():
    """Настроить webhook для Telegram бота"""
    try:
        app_url = os.environ.get('APP_URL', 'https://buhgalter-aktobe.vercel.app')
        webhook_url = f"{app_url}/telegram-webhook"
        
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/setWebhook"
        payload = {
            'url': webhook_url,
            'allowed_updates': ['message']
        }
        
        response = requests.post(url, json=payload, timeout=10)
        result = response.json()
        
        if result.get('ok'):
            print(f"✅ Telegram webhook установлен: {webhook_url}")
        else:
            print(f"❌ Ошибка установки webhook: {result}")
        
        return result
    except Exception as e:
        print(f"❌ Ошибка в set_telegram_webhook: {e}")
        return {'ok': False, 'error': str(e)}

def get_db_connection():
    """Создать соединение с Neon database используя pg8000"""
    try:
        conn = pg8000.connect(
            host=os.environ.get('PGHOST', 'ep-tiny-lab-agdp3p2o-pooler.c-2.eu-central-1.aws.neon.tech'),
            port=5432,
            user=os.environ.get('PGUSER', 'neondb_owner'),
            password=os.environ.get('PGPASSWORD', 'npg_EDzFntuY13CI'),
            database=os.environ.get('PGDATABASE', 'neondb'),
            ssl_context=True
        )
        return conn
    except Exception as e:
        print(f"❌ Ошибка подключения к базе данных: {e}")
        return None

def init_db():
    """Инициализировать таблицы в базе данных"""
    conn = get_db_connection()
    if not conn:
        print("❌ Не удалось подключиться к базе данных для инициализации")
        return
        
    try:
        cur = conn.cursor()
        
        cur.execute('''
            CREATE TABLE IF NOT EXISTS requests (
                id SERIAL PRIMARY KEY,
                client_id UUID NOT NULL,
                name VARCHAR(100) NOT NULL,
                email VARCHAR(100) NOT NULL,
                phone VARCHAR(20) NOT NULL,
                service_type VARCHAR(50) NOT NULL,
                company_type VARCHAR(50),
                message TEXT,
                urgency VARCHAR(20) DEFAULT 'standard',
                date VARCHAR(50) NOT NULL,
                status VARCHAR(20) DEFAULT 'новая',
                assigned_to VARCHAR(100) DEFAULT '',
                notes TEXT DEFAULT '',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        cur.execute('''
            CREATE TABLE IF NOT EXISTS clients (
                id UUID PRIMARY KEY,
                name VARCHAR(100) NOT NULL,
                email VARCHAR(100) NOT NULL,
                phone VARCHAR(20) NOT NULL,
                company_type VARCHAR(50),
                created_date VARCHAR(50) NOT NULL,
                requests_count INTEGER DEFAULT 1,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        cur.execute('''
            CREATE TABLE IF NOT EXISTS telegram_chats (
                id SERIAL PRIMARY KEY,
                chat_id BIGINT UNIQUE NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        conn.commit()
        cur.close()
        print("✅ База данных Neon инициализирована успешно")
    except Exception as e:
        print(f"❌ Ошибка инициализации базы данных: {e}")
    finally:
        if conn:
            conn.close()

init_db()

def load_telegram_chats():
    """Загрузить список chat_id из базы данных"""
    conn = get_db_connection()
    if not conn:
        return []
        
    try:
        cur = conn.cursor()
        cur.execute('SELECT chat_id FROM telegram_chats')
        chats = [row[0] for row in cur.fetchall()]
        return chats
    except Exception as e:
        print(f"❌ Ошибка загрузки Telegram чатов: {e}")
        return []
    finally:
        if conn:
            conn.close()

def save_telegram_chat(chat_id):
    """Сохранить новый chat_id в базу данных"""
    conn = get_db_connection()
    if not conn:
        return False
        
    try:
        cur = conn.cursor()
        cur.execute(
            'INSERT INTO telegram_chats (chat_id) VALUES (%s) ON CONFLICT (chat_id) DO NOTHING',
            (chat_id,)
        )
        conn.commit()
        print(f"✅ Новый подписчик Telegram: {chat_id}")
        return True
    except Exception as e:
        print(f"❌ Ошибка сохранения Telegram чата: {e}")
        return False
    finally:
        if conn:
            conn.close()

def send_telegram_notification(request_data):
    """Отправить уведомление в Telegram"""
    try:
        chats = load_telegram_chats()
        if not chats:
            print("ℹ️ Нет подписчиков Telegram для уведомлений")
            return
        
        service_name = SERVICES.get(request_data['service_type'], {}).get('name', request_data['service_type'])
        
        urgency_map = {
            'standard': 'Стандартная (1–2 дня)',
            'urgent': 'Срочная (в течение дня)', 
            'very_urgent': 'Очень срочная (несколько часов)'
        }
        urgency_text = urgency_map.get(request_data.get('urgency', 'standard'), 'Стандартная')
        
        message = f"""
🆕 *Новая заявка на консультацию*

*Имя:* {request_data['name']}
*Телефон:* `{request_data['phone']}`
*Email:* {request_data['email']}
*Услуга:* {service_name}
*Тип компании:* {request_data.get('company_type', 'Не указано')}
*Срочность:* {urgency_text}
*Дата:* {request_data['date']}

*Сообщение:*
{request_data.get('message', 'Не указано')}
        """.strip()
        
        successful_sends = 0
        for chat_id in chats:
            try:
                url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
                payload = {
                    'chat_id': chat_id,
                    'text': message,
                    'parse_mode': 'Markdown'
                }
                response = requests.post(url, json=payload, timeout=10)
                if response.status_code == 200:
                    successful_sends += 1
            except Exception as e:
                print(f"⚠️ Ошибка отправки в Telegram для chat_id {chat_id}: {e}")
        
        print(f"✅ Уведомления отправлены {successful_sends}/{len(chats)} подписчикам")
        
    except Exception as e:
        print(f"❌ Ошибка в send_telegram_notification: {e}")

def save_client(client_data):
    """Сохранить клиента в базу данных"""
    conn = get_db_connection()
    if not conn:
        return None
        
    try:
        cur = conn.cursor()
        
        cur.execute('SELECT id, requests_count FROM clients WHERE email = %s', (client_data['email'],))
        existing_client = cur.fetchone()
        
        if existing_client:
            cur.execute(
                'UPDATE clients SET requests_count = requests_count + 1 WHERE id = %s',
                (existing_client[0],)
            )
            client_id = existing_client[0]
        else:
            client_id = client_data['id']
            cur.execute(
                'INSERT INTO clients (id, name, email, phone, company_type, created_date, requests_count) VALUES (%s, %s, %s, %s, %s, %s, %s)',
                (client_id, client_data['name'], client_data['email'], client_data['phone'], 
                 client_data['company_type'], client_data['created_date'], client_data['requests_count'])
            )
        
        conn.commit()
        return client_id
    except Exception as e:
        print(f"❌ Ошибка сохранения клиента: {e}")
        return None
    finally:
        if conn:
            conn.close()

def save_request(request_data):
    """Сохранить заявку в базу данных"""
    conn = get_db_connection()
    if not conn:
        return None
        
    try:
        cur = conn.cursor()
        
        cur.execute('''
            INSERT INTO requests 
            (client_id, name, email, phone, service_type, company_type, message, urgency, date, status, assigned_to, notes)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING id
        ''', (
            request_data['client_id'], request_data['name'], request_data['email'], 
            request_data['phone'], request_data['service_type'], request_data['company_type'],
            request_data['message'], request_data['urgency'], request_data['date'],
            request_data['status'], request_data['assigned_to'], request_data['notes']
        ))
        
        request_id = cur.fetchone()[0]
        conn.commit()
        
        print(f"✅ Заявка сохранена: {request_data['name']} (ID: {request_id})")
        return request_id
    except Exception as e:
        print(f"❌ Ошибка сохранения заявки: {e}")
        return None
    finally:
        if conn:
            conn.close()

def load_requests():
    """Загрузить все заявки из базы данных"""
    conn = get_db_connection()
    if not conn:
        return []
        
    try:
        cur = conn.cursor()
        cur.execute('SELECT * FROM requests ORDER BY created_at DESC')
        rows = cur.fetchall()
        
        column_names = [desc[0] for desc in cur.description]
        
        requests_list = []
        for row in rows:
            request_dict = {}
            for i, column_name in enumerate(column_names):
                request_dict[column_name] = row[i]
            requests_list.append(request_dict)
        
        return requests_list
    except Exception as e:
        print(f"❌ Ошибка загрузки заявок: {e}")
        return []
    finally:
        if conn:
            conn.close()

def load_clients():
    """Загрузить всех клиентов из базы данных"""
    conn = get_db_connection()
    if not conn:
        return []
        
    try:
        cur = conn.cursor()
        cur.execute('SELECT * FROM clients ORDER BY created_at DESC')
        rows = cur.fetchall()
        
        column_names = [desc[0] for desc in cur.description]
        clients_list = []
        for row in rows:
            client_dict = {}
            for i, column_name in enumerate(column_names):
                client_dict[column_name] = row[i]
            clients_list.append(client_dict)
        
        return clients_list
    except Exception as e:
        print(f"❌ Ошибка загрузки клиентов: {e}")
        return []
    finally:
        if conn:
            conn.close()

def update_request_status(request_id, status):
    """Обновить статус заявки"""
    conn = get_db_connection()
    if not conn:
        return False
        
    try:
        cur = conn.cursor()
        cur.execute('UPDATE requests SET status = %s WHERE id = %s', (status, request_id))
        conn.commit()
        return True
    except Exception as e:
        print(f"❌ Ошибка обновления статуса заявки: {e}")
        return False
    finally:
        if conn:
            conn.close()

def delete_request_by_id(request_id):
    """Удалить заявку"""
    conn = get_db_connection()
    if not conn:
        return False
        
    try:
        cur = conn.cursor()
        cur.execute('DELETE FROM requests WHERE id = %s', (request_id,))
        conn.commit()
        return True
    except Exception as e:
        print(f"❌ Ошибка удаления заявки: {e}")
        return False
    finally:
        if conn:
            conn.close()

def login_required(f):
    """Декоратор для проверки авторизации"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user' not in session:
            flash('Пожалуйста, выполните вход', 'error')
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function

@app.route('/')
def index():
    """Главная страница"""
    return render_template('index.html', services=SERVICES)

@app.route('/services')
def services():
    """Страница с описанием услуг"""
    return render_template('services.html', 
                         services=SERVICES,
                         meta_description="Полный перечень бухгалтерских услуг: ведение учёта, налоговая отчётность, аудит, регистрация бизнеса. Профессиональные решения для вашего бизнеса.")

@app.route('/consultation', methods=['GET', 'POST'])
def consultation():
    """Страница заявки на консультацию"""
    if request.method == 'POST':
        name = request.form.get('name', '').strip()
        email = request.form.get('email', '').strip()
        phone = request.form.get('phone', '').strip()
        service_type = request.form.get('service_type', '').strip()
        company_type = request.form.get('company_type', '').strip()
        message = request.form.get('message', '').strip()
        urgency = request.form.get('urgency', 'standard')
        
        if not all([name, email, phone, service_type]):
            flash('Пожалуйста, заполните все обязательные поля', 'error')
            return redirect(url_for('consultation'))
        
        client_id = str(uuid.uuid4())
        new_client = {
            'id': client_id,
            'name': name,
            'email': email,
            'phone': phone,
            'company_type': company_type,
            'created_date': datetime.now().strftime('%d.%m.%Y %H:%M:%S'),
            'requests_count': 1
        }
        save_client(new_client)
        
        new_request = {
            'client_id': client_id,
            'name': name,
            'email': email,
            'phone': phone,
            'service_type': service_type,
            'company_type': company_type,
            'message': message,
            'urgency': urgency,
            'date': datetime.now().strftime('%d.%m.%Y %H:%M:%S'),
            'status': 'новая',
            'assigned_to': '',
            'notes': ''
        }
        request_id = save_request(new_request)
        
        if request_id:
            try:
                new_request['id'] = request_id
                send_telegram_notification(new_request)
            except Exception as e:
                print(f"❌ Ошибка отправки уведомления в Telegram: {e}")
            
            flash('Спасибо! Ваша заявка принята. Мы свяжемся с вами в ближайшее время.', 'success')
        else:
            flash('Произошла ошибка при сохранении заявки. Пожалуйста, попробуйте еще раз.', 'error')
        
        return redirect(url_for('consultation'))
    
    return render_template('consultation.html', services=SERVICES)

@app.route('/pricing')
def pricing():
    """Страница с ценами"""
    return render_template('pricing.html', 
                         services=SERVICES,
                         meta_description="Прозрачные цены на бухгалтерские услуги в Актобе. Тарифы для ИП и ТОО. Бесплатная консультация и индивидуальный расчёт.")

@app.route('/about')
def about():
    """Страница о компании"""
    return render_template('about.html',
                         meta_description="Бухгалтер Гусева Юлия - профессиональные услуги с опытом 20+ лет. Надёжное ведение бухгалтерии для бизнеса в Актобе и Казахстане.")

@app.route('/login', methods=['GET', 'POST'])
def login():
    """Вход в админ панель"""
    if request.method == 'POST':
        login_input = request.form.get('login', '').strip()
        password_input = request.form.get('password', '').strip()
        
        if login_input == ADMIN_LOGIN and password_input == ADMIN_PASSWORD:
            session['user'] = ADMIN_LOGIN
            flash('Вы успешно вошли', 'success')
            return redirect(url_for('admin_panel'))
        else:
            flash('Неверные учетные данные', 'error')
    
    return render_template('login.html')

@app.route('/admin')
@login_required
def admin_panel():
    """Админ панель с заявками"""
    status_filter = request.args.get('status', '')
    
    requests_list = load_requests()
    
    if status_filter:
        requests_list = [r for r in requests_list if r['status'] == status_filter]

    stats = {
        'total': len(requests_list),
        'new': len([r for r in requests_list if r['status'] == 'новая']),
        'completed': len([r for r in requests_list if r['status'] == 'завершена'])
    }
    
    return render_template('admin.html', 
                         requests=requests_list,
                         stats=stats,
                         status_filter=status_filter,
                         services=SERVICES)

@app.route('/admin/delete/<int:request_id>', methods=['POST'])
@login_required
def delete_request(request_id):
    """Удалить заявку"""
    if delete_request_by_id(request_id):
        flash('Заявка удалена', 'success')
    else:
        flash('Заявка не найдена', 'error')
    return redirect(url_for('admin_panel'))

@app.route('/admin/update-status/<int:request_id>/<status>', methods=['POST'])
@login_required
def update_status(request_id, status):
    """Обновить статус заявки"""
    valid_statuses = ['новая', 'завершена']
    
    if status not in valid_statuses:
        flash('Неверный статус', 'error')
        return redirect(url_for('admin_panel'))
    
    if update_request_status(request_id, status):
        flash('Статус обновлен', 'success')
    else:
        flash('Заявка не найдена', 'error')
    return redirect(url_for('admin_panel'))

@app.route('/admin/add-note/<int:request_id>', methods=['POST'])
@login_required
def add_note(request_id):
    """Добавить заметку к заявке"""
    note = request.form.get('note', '').strip()
    requests_list = load_requests()
    for req in requests_list:
        if req['id'] == request_id:
            req['notes'] = note
            flash('Заметка добавлена', 'success')
            return redirect(url_for('admin_panel'))
    
    flash('Заявка не найдена', 'error')
    return redirect(url_for('admin_panel'))

@app.route('/admin/assign-to/<int:request_id>', methods=['POST'])
@login_required
def assign_request(request_id):
    """Назначить заявку сотруднику"""
    assigned_to = request.form.get('assigned_to', '').strip()
    requests_list = load_requests()
    for req in requests_list:
        if req['id'] == request_id:
            req['assigned_to'] = assigned_to
            flash('Заявка назначена', 'success')
            return redirect(url_for('admin_panel'))
    
    flash('Заявка не найдена', 'error')
    return redirect(url_for('admin_panel'))

@app.route('/logout')
def logout():
    """Выход из админ панели"""
    session.pop('user', None)
    flash('Вы вышли из системы', 'success')
    return redirect(url_for('index'))

@app.route('/admin/export/<int:year>/<int:month>')
@login_required
def export_requests(year, month):
    """Экспорт заявок в CSV"""
    requests_list = load_requests()
    
    if not requests_list:
        flash('Нет данных для экспорта', 'error')
        return redirect(url_for('admin_panel'))
    
    output = StringIO()
    writer = csv.writer(output)
    
    writer.writerow(['ID', 'Имя', 'Email', 'Телефон', 'Услуга', 'Тип компании', 'Сообщение', 'Дата', 'Статус'])

    for req in requests_list:
        writer.writerow([
            req['id'],
            req['name'],
            req['email'],
            req['phone'],
            req.get('service_type', ''),
            req.get('company_type', ''),
            req['message'],
            req['date'],
            req['status']
        ])
    
    output.seek(0)
    
    return Response(
        output.getvalue(),
        mimetype="text/csv",
        headers={"Content-disposition": f"attachment; filename=requests_{datetime.now().strftime('%Y%m%d')}.csv"}
    )

@app.route('/api/stats')
@login_required
def api_stats():
    """API для статистики"""
    requests_list = load_requests()
    clients = load_clients()
    
    stats = {
        'requests': {
            'total': len(requests_list),
            'new': len([r for r in requests_list if r['status'] == 'новая']),
            'completed': len([r for r in requests_list if r['status'] == 'завершена'])
        },
        'clients': {
            'total': len(clients),
            'recurring': len([c for c in clients if c.get('requests_count', 0) > 1])
        },
        'telegram_subscribers': len(load_telegram_chats())
    }
    
    return jsonify(stats)

@app.route('/telegram-webhook', methods=['GET', 'POST'])
def telegram_webhook():
    """Webhook для Telegram бота"""
    if request.method == 'GET':
        return jsonify({'status': 'ok', 'message': 'Webhook is working'})
    
    try:
        data = request.get_json()
        print(f"Telegram webhook data: {data}")
        
        if 'message' in data:
            message = data['message']
            chat_id = message['chat']['id']
            text = message.get('text', '').strip().lower()
            
            if text == '/start':
                save_telegram_chat(chat_id)
                try:
                    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
                    payload = {
                        'chat_id': chat_id,
                        'text': "✅ Вы подписались на уведомления о новых заявках. Теперь вы будете получать оповещения о новых заявках с сайта.",
                        'parse_mode': 'Markdown'
                    }
                    response = requests.post(url, json=payload, timeout=10)
                    print(f"✅ Приветственное сообщение отправлено: {response.status_code}")
                except Exception as e:
                    print(f"❌ Ошибка отправки приветствия: {e}")
                    
            elif text == '/stop':
                chats = load_telegram_chats()
                if chat_id in chats:
                    conn = get_db_connection()
                    if conn:
                        cur = conn.cursor()
                        cur.execute('DELETE FROM telegram_chats WHERE chat_id = %s', (chat_id,))
                        conn.commit()
                        conn.close()
                    print(f"✅ Подписчик удален: {chat_id}")
                
                try:
                    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
                    payload = {
                        'chat_id': chat_id,
                        'text': "❌ Вы отписались от уведомлений о новых заявках.",
                        'parse_mode': 'Markdown'
                    }
                    requests.post(url, json=payload, timeout=10)
                except Exception as e:
                    print(f"❌ Ошибка отправки сообщения об отписке: {e}")
            else:
                try:
                    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
                    payload = {
                        'chat_id': chat_id,
                        'text': "🤖 Доступные команды:\n/start - подписаться на уведомления\n/stop - отписаться от уведомлений",
                        'parse_mode': 'Markdown'
                    }
                    requests.post(url, json=payload, timeout=10)
                except Exception as e:
                    print(f"❌ Ошибка отправки справки: {e}")
        
        return jsonify({'status': 'ok'})
        
    except Exception as e:
        print(f"❌ Ошибка в webhook: {e}")
        return jsonify({'status': 'error', 'message': str(e)}), 500

@app.route('/admin/telegram-setup')
@login_required
def telegram_setup_manual():
    """Ручная настройка Telegram вебхука"""
    return '''
    <html>
    <head><title>Настройка Telegram</title></head>
    <body style="font-family: Arial; padding: 20px;">
        <h1>Настройка Telegram уведомлений</h1>
        <p>Для настройки выполните следующие шаги:</p>
        <ol>
            <li>Перейдите по ссылке: 
                <a href="https://api.telegram.org/bot7561142289:AAFVFusO4EQqxsz4-oDJjVHUPEfhIarlAcs/setWebhook?url=https://buhgalter-aktobe.vercel.app/telegram-webhook" target="_blank">
                    Настроить вебхук
                </a>
            </li>
            <li>Найдите бота в Telegram и отправьте /start</li>
            <li>Проверьте статус: 
                <a href="https://api.telegram.org/bot7561142289:AAFVFusO4EQqxsz4-oDJjVHUPEfhIarlAcs/getWebhookInfo" target="_blank">
                    Проверить статус
                </a>
            </li>
        </ol>
        <p><strong>Текущие подписчики:</strong> {}</p>
        <p><strong>Текущие заявки:</strong> {}</p>
        <a href="/admin">← Назад в админку</a>
    </body>
    </html>
    '''.format(len(load_telegram_chats()), len(load_requests()))

@app.route('/admin/setup-telegram-webhook')
@login_required
def setup_telegram_webhook():
    """Настроить webhook для Telegram (ручной вызов)"""
    result = set_telegram_webhook()
    if result and result.get('ok'):
        flash('Webhook успешно настроен', 'success')
    else:
        flash('Ошибка настройки webhook', 'error')
    return redirect(url_for('admin_panel'))

@app.route('/favicon.ico')
def favicon():
    return send_from_directory(os.path.join(app.root_path, 'static'),
                             'favicon.ico', mimetype='image/vnd.microsoft.icon')


@app.route('/test/404')
def test_404():
    """Тестовая страница 404 ошибки"""
    return render_template('404.html'), 404

@app.route('/test/500')
def test_500():
    """Тестовая страница 500 ошибки"""
    return render_template('500.html'), 500

@app.route('/test/trigger-404')
def trigger_404():
    """Вызвать реальную 404 ошибку"""
    abort(404)

@app.route('/test/trigger-500')
def trigger_500():
    """Вызвать реальную 500 ошибку"""
    abort(500)

@app.errorhandler(404)
def not_found_error(error):
    return render_template('404.html'), 404

@app.errorhandler(500)
def internal_error(error):
    return render_template('500.html'), 500

@app.route('/googleddd09674c4d97235.html')
def google_verification():
    return send_from_directory('.', 'googleddd09674c4d97235.html')

@app.route('/yandex_d94254384d1d67c8.html')
def yandex_verification_d94254384d1d67c8():
    return send_from_directory('.', 'yandex_d94254384d1d67c8.html')

@app.route('/yandex_c93958d7537cbd61.html')
def yandex_verification_c93958d7537cbd61():
    return send_from_directory('.', 'yandex_c93958d7537cbd61.html')

@app.route('/sitemap.xml')
def sitemap():
    return send_from_directory('.', 'sitemap.xml')

@app.route('/robots.txt')
def robots():
    return send_from_directory('.', 'robots.txt')

if __name__ == '__main__':
    app.run(debug=True)
