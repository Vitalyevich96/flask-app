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
import time

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
    """Настроить webhook для Telegram бота с повторными попытками"""
    max_retries = 3
    for attempt in range(max_retries):
        try:
            app_url = os.environ.get('APP_URL', 'https://buhgalter-aktobe.vercel.app')
            webhook_url = f"{app_url}/telegram-webhook"
            
            url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/setWebhook"
            payload = {
                'url': webhook_url,
                'allowed_updates': ['message', 'callback_query'],
                'drop_pending_updates': True
            }
            
            response = requests.post(url, json=payload, timeout=10)
            result = response.json()
            
            if result.get('ok'):
                print(f"✅ Telegram webhook установлен: {webhook_url} (попытка {attempt + 1})")
                return result
            else:
                print(f"❌ Ошибка установки webhook (попытка {attempt + 1}): {result}")
                
        except Exception as e:
            print(f"❌ Ошибка в set_telegram_webhook (попытка {attempt + 1}): {e}")
        
        if attempt < max_retries - 1:
            time.sleep(2)
    
    return {'ok': False, 'error': 'Все попытки установки webhook не удались'}

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
        username VARCHAR(100),
        first_name VARCHAR(100),
        notification_enabled BOOLEAN DEFAULT TRUE,
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
    """Загрузить список chat_id с статусом 1 из базы данных"""
    conn = get_db_connection()
    if not conn:
        return []
        
    try:
        cur = conn.cursor()
        cur.execute('SELECT chat_id FROM telegram_chats WHERE notification_enabled = TRUE')
        chats = [row[0] for row in cur.fetchall()]
        print(f"📊 Загружено {len(chats)} пользователей со статусом 1")
        return chats
    except Exception as e:
        print(f"❌ Ошибка загрузки Telegram чатов: {e}")
        return []
    finally:
        if conn:
            conn.close()

def save_telegram_chat(chat_id, username=None, first_name=None):
    """Сохранить или обновить chat_id в базе данных"""
    conn = get_db_connection()
    if not conn:
        return False
        
    try:
        cur = conn.cursor()
        cur.execute('''
            INSERT INTO telegram_chats (chat_id, username, first_name, notification_enabled) 
            VALUES (%s, %s, %s, TRUE) 
            ON CONFLICT (chat_id) 
            DO UPDATE SET username = EXCLUDED.username, 
                         first_name = EXCLUDED.first_name,
                         notification_enabled = TRUE
        ''', (chat_id, username, first_name))
        conn.commit()
        print(f"✅ Пользователь добавлен/обновлен: {chat_id} (@{username}) - статус: 1")
        return True
    except Exception as e:
        print(f"❌ Ошибка сохранения Telegram чата: {e}")
        return False
    finally:
        if conn:
            conn.close()

def send_telegram_message(chat_id, message, parse_mode='Markdown', reply_markup=None, retries=3):
    """Отправить сообщение в Telegram с повторными попытками"""
    for attempt in range(retries):
        try:
            url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
            payload = {
                'chat_id': chat_id,
                'text': message,
                'parse_mode': parse_mode
            }
            if reply_markup:
                payload['reply_markup'] = reply_markup
            
            response = requests.post(url, json=payload, timeout=10)
            if response.status_code == 200:
                return True
        except Exception as e:
            if attempt == retries - 1:
                print(f"❌ Не удалось отправить после {retries} попыток в chat {chat_id}: {e}")
            time.sleep(1)
    return False

def send_telegram_notification(request_data):
    """Отправить уведомление о новой заявке в Telegram"""
    try:
        print(f"🔔 Начало отправки уведомления для заявки {request_data.get('id')}")
        
        chats = load_telegram_chats()
        print(f"📋 Найдено подписчиков: {len(chats)}")
        print(f"📋 Chat IDs: {chats}")
        
        if not chats:
            print("ℹ️ Нет подписчиков Telegram для уведомлений")
            test_chat_id = 573190621
            test_message = "🔔 Тестовое уведомление: система работает!"
            send_telegram_message(test_chat_id, test_message)
            return
        
        service_name = SERVICES.get(request_data['service_type'], {}).get('name', request_data['service_type'])
        
        urgency_map = {
            'standard': ('🟢', 'Стандартная (1–2 дня)'),
            'urgent': ('🟡', 'Срочная (в течение дня)'), 
            'very_urgent': ('🔴', 'Очень срочная (несколько часов)')
        }
        urgency_emoji, urgency_text = urgency_map.get(request_data.get('urgency', 'standard'), ('🟢', 'Стандартная'))
        
        message_text = request_data.get('message', 'Не указано')
        if len(message_text) > 200:
            message_text = message_text[:200] + '...'
        
        message = f"""
🆕 *НОВАЯ ЗАЯВКА #{request_data.get('id', 'N/A')}*

👤 *Клиент:* {request_data['name']}
📱 *Телефон:* `{request_data['phone']}`
📧 *Email:* `{request_data['email']}`

💼 *Услуга:* {service_name}
🏢 *Компания:* {request_data.get('company_type', 'Не указано')}
{urgency_emoji} *Срочность:* {urgency_text}
📅 *Дата:* {request_data['date']}

💬 *Сообщение:*
_{message_text}_
        """.strip()

        reply_markup = {
            'inline_keyboard': [
                [
                    {'text': '✅ Взять в работу', 'callback_data': f'take_{request_data.get("id")}'},
                    {'text': '📞 Связаться', 'callback_data': f'contact_{request_data.get("id")}'}
                ],
                [
                    {'text': '⚡ Отметить срочной', 'callback_data': f'urgent_{request_data.get("id")}'},
                    {'text': '✔️ Завершить', 'callback_data': f'complete_{request_data.get("id")}'}
                ]
            ]
        }
        
        successful_sends = 0
        for chat_id in chats:
            if send_telegram_message(chat_id, message, reply_markup=reply_markup):
                successful_sends += 1
        
        print(f"✅ Уведомления отправлены {successful_sends}/{len(chats)} подписчикам")
        
    except Exception as e:
        print(f"❌ Ошибка в send_telegram_notification: {e}")

def disable_telegram_notifications(chat_id):
    """Установить статус 0 для пользователя"""
    conn = get_db_connection()
    if not conn:
        return False
        
    try:
        cur = conn.cursor()
        cur.execute('UPDATE telegram_chats SET notification_enabled = FALSE WHERE chat_id = %s', (chat_id,))
        conn.commit()
        print(f"✅ Уведомления отключены для пользователя: {chat_id} (статус: 0)")
        return True
    except Exception as e:
        print(f"❌ Ошибка отключения уведомлений: {e}")
        return False
    finally:
        if conn:
            conn.close()

def get_stats_message():
    """Получить статистику для отправки в Telegram"""
    try:
        requests_list = load_requests()
        clients = load_clients()
        
        today = datetime.now().date()
        today_requests = [r for r in requests_list if datetime.strptime(r['date'], '%d.%m.%Y %H:%M:%S').date() == today]
        
        new_count = len([r for r in requests_list if r['status'] == 'новая'])
        completed_count = len([r for r in requests_list if r['status'] == 'завершена'])
        
        message = f"""
📊 *СТАТИСТИКА ЗАЯВОК*

📅 *Сегодня:* {len(today_requests)} заявок

📈 *Общая статистика:*
• Всего заявок: {len(requests_list)}
• 🆕 Новые: {new_count}
• ✅ Завершено: {completed_count}

        """.strip()
        
        return message
    except Exception as e:
        return f"❌ Ошибка получения статистики: {e}"

def get_today_requests_message():
    """Получить заявки за сегодня"""
    try:
        requests_list = load_requests()
        today = datetime.now().date()
        today_requests = [r for r in requests_list 
                         if datetime.strptime(r['date'], '%d.%m.%Y %H:%M:%S').date() == today]
        
        if not today_requests:
            return "📅 *ЗАЯВКИ ЗА СЕГОДНЯ*\n\nНет заявок за сегодня"
        
        message = f"📅 *ЗАЯВКИ ЗА СЕГОДНЯ* ({len(today_requests)})\n\n"
        
        for idx, req in enumerate(today_requests[:10], 1): 
            service_name = SERVICES.get(req['service_type'], {}).get('name', req['service_type'])
            status_emoji = {'новая': '🆕', 'в работе': '🔄', 'завершена': '✅'}.get(req['status'], '📋')
            
            message += f"""
{idx}. 👤 {req['name']} | 📱 {req['phone']}
   💼 {service_name}
   ⏰ {req['date'].split()[1]}

"""
        
        if len(today_requests) > 10:
            message += f"\n_...и еще {len(today_requests) - 10} заявок_"
        
        return message.strip()
    except Exception as e:
        return f"❌ Ошибка получения заявок: {e}"

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

def get_user_status_message(chat_id):
    """Получить текстовое сообщение о статусе пользователя"""
    conn = get_db_connection()
    if not conn:
        return "Неизвестно (ошибка базы данных)"
        
    try:
        cur = conn.cursor()
        cur.execute('SELECT notification_enabled FROM telegram_chats WHERE chat_id = %s', (chat_id,))
        result = cur.fetchone()
        
        if result:
            status = result[0]
            return "✅ Уведомления ВКЛЮЧЕНЫ (1)" if status else "❌ Уведомления ОТКЛЮЧЕНЫ (0)"
        else:
            return "❓ Не зарегистрирован (отправьте /start)"
    except Exception as e:
        print(f"❌ Ошибка получения статуса пользователя: {e}")
        return "Неизвестно (ошибка)"
    finally:
        if conn:
            conn.close()

with app.app_context():
    print("🔄 Настраиваю Telegram вебхук при запуске...")
    result = set_telegram_webhook()
    if result and result.get('ok'):
        print("✅ Вебхук успешно настроен")
    else:
        print("❌ Ошибка настройки вебхука")

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
    status_mapping = {
        'completed': 'завершена',
        'new': 'новая'
    }
    
    if status not in status_mapping:
        flash('Неверный статус', 'error')
        return redirect(url_for('admin_panel'))
    
    russian_status = status_mapping[status]
    
    if update_request_status(request_id, russian_status):
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
    """Улучшенный webhook для Telegram бота"""
    if request.method == 'GET':
        return jsonify({'status': 'ok', 'message': 'Webhook is working'})
    
    try:
        data = request.get_json()
        print(f"📥 Telegram webhook data: {json.dumps(data, ensure_ascii=False)}")
        
        if 'message' in data:
            message = data['message']
            chat_id = message['chat']['id']
            username = message['chat'].get('username')
            first_name = message['chat'].get('first_name', 'Пользователь')
            text = message.get('text', '').strip().lower()
            
            if text == '/start':
                save_telegram_chat(chat_id, username, first_name)
                welcome_message = f"""
👋 *Добро пожаловать, {first_name}!*

Вы подписались на уведомления о новых заявках с сайта бухгалтерских услуг.

📋 *Доступные команды:*
/stats - статистика заявок
/today - заявки за сегодня
/help - справка по командам
/stop - отключить уведомления

💡 *Быстрые действия:*
Когда придёт новая заявка, вы увидите кнопки для быстрой обработки прямо в сообщении!

✅ *Текущий статус:* Уведомления ВКЛЮЧЕНЫ (1)
                """.strip()
                send_telegram_message(chat_id, welcome_message)
            
            elif text == '/stop':
                if disable_telegram_notifications(chat_id):
                    goodbye_message = """
🔕 *Уведомления отключены*

Вы больше не будете получать уведомления о новых заявках.

❌ *Текущий статус:* Уведомления ОТКЛЮЧЕНЫ (0)

Чтобы снова включить уведомления, отправьте /start
                    """.strip()
                else:
                    goodbye_message = "❌ Произошла ошибка при отключении уведомлений"
                
                send_telegram_message(chat_id, goodbye_message)
            
            elif text == '/stats':
                stats_message = get_stats_message()
                send_telegram_message(chat_id, stats_message)
            
            elif text == '/today':
                today_message = get_today_requests_message()
                send_telegram_message(chat_id, today_message)
            
            elif text == '/help':
                help_message = f"""
📚 *СПРАВКА ПО КОМАНДАМ*

*Основные команды:*
/start - подписаться на уведомления (статус 1)
/stop - отключить уведомления (статус 0)
/stats - показать статистику заявок
/today - показать заявки за сегодня
/help - эта справка

*Интерактивные кнопки:*
При получении уведомления о новой заявке вы увидите кнопки для быстрых действий:

✅ *Взять в работу* - изменить статус на "в работе"
📞 *Связаться* - открыть контакты клиента
⚡ *Отметить срочной* - повысить приоритет
✔️ *Завершить* - закрыть заявку

💡 *Совет:* Используйте кнопки прямо из уведомления - это быстрее!

👤 *Ваш статус:* {get_user_status_message(chat_id)}
                """.strip()
                send_telegram_message(chat_id, help_message)
            
            else:
                unknown_message = f"""
🤔 *Неизвестная команда*

Используйте /help для списка доступных команд

*Доступно:*
/stats - статистика
/today - заявки за сегодня
/help - справка

👤 *Ваш статус:* {get_user_status_message(chat_id)}
                """.strip()
                send_telegram_message(chat_id, unknown_message)
        
        elif 'callback_query' in data:
            callback = data['callback_query']
            chat_id = callback['message']['chat']['id']
            message_id = callback['message']['message_id']
            callback_data = callback['data']
            
            action, request_id = callback_data.split('_', 1)
            request_id = int(request_id)
            
            requests_list = load_requests()
            current_request = next((r for r in requests_list if r['id'] == request_id), None)
            
            if not current_request:
                answer_text = "❌ Заявка не найдена"
            elif action == 'take':
                if update_request_status(request_id, 'в работе'):
                    answer_text = f"✅ Заявка #{request_id} взята в работу"
                else:
                    answer_text = "❌ Ошибка обновления статуса"
            
            elif action == 'contact':
                answer_text = f"📞 Контакты клиента:\n{current_request['phone']}\n{current_request['email']}"
            
            elif action == 'urgent':
                answer_text = f"⚡ Заявка #{request_id} отмечена как срочная"
            
            elif action == 'complete':
                if update_request_status(request_id, 'завершена'):
                    answer_text = f"✔️ Заявка #{request_id} завершена"
                else:
                    answer_text = "❌ Ошибка обновления статуса"
            
            else:
                answer_text = "❓ Неизвестное действие"
            
            try:
                url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/answerCallbackQuery"
                payload = {
                    'callback_query_id': callback['id'],
                    'text': answer_text,
                    'show_alert': False
                }
                requests.post(url, json=payload, timeout=10)
                
                if action == 'complete':
                    edit_url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/editMessageReplyMarkup"
                    edit_payload = {
                        'chat_id': chat_id,
                        'message_id': message_id,
                        'reply_markup': {'inline_keyboard': []}
                    }
                    requests.post(edit_url, json=edit_payload, timeout=10)
                    
            except Exception as e:
                print(f"❌ Ошибка обработки callback: {e}")
        
        return jsonify({'status': 'ok'})
        
    except Exception as e:
        print(f"❌ Ошибка в webhook: {e}")
        return jsonify({'status': 'error', 'message': str(e)}), 500

@app.route('/admin/telegram-setup')
@login_required
def telegram_setup_manual():
    """Ручная настройка Telegram вебхука"""
    chats = load_telegram_chats()
    
    conn = get_db_connection()
    chat_details = []
    if conn:
        try:
            cur = conn.cursor()
            cur.execute('SELECT chat_id, username, first_name, notification_enabled, created_at FROM telegram_chats ORDER BY created_at DESC')
            rows = cur.fetchall()
            for row in rows:
                chat_details.append({
                    'chat_id': row[0],
                    'username': row[1] or 'N/A',
                    'first_name': row[2] or 'N/A',
                    'enabled': '✅' if row[3] else '❌',
                    'created': row[4].strftime('%d.%m.%Y %H:%M') if row[4] else 'N/A'
                })
        finally:
            conn.close()
    
    chat_table = ""
    if chat_details:
        chat_table = "<table style='width:100%; border-collapse: collapse; margin-top: 20px;'>"
        chat_table += "<tr style='background: #f0f0f0;'><th style='padding:10px; border:1px solid #ddd;'>Chat ID</th><th style='padding:10px; border:1px solid #ddd;'>Username</th><th style='padding:10px; border:1px solid #ddd;'>Имя</th><th style='padding:10px; border:1px solid #ddd;'>Статус</th><th style='padding:10px; border:1px solid #ddd;'>Дата</th></tr>"
        for chat in chat_details:
            chat_table += f"<tr><td style='padding:8px; border:1px solid #ddd;'>{chat['chat_id']}</td><td style='padding:8px; border:1px solid #ddd;'>@{chat['username']}</td><td style='padding:8px; border:1px solid #ddd;'>{chat['first_name']}</td><td style='padding:8px; border:1px solid #ddd;'>{chat['enabled']}</td><td style='padding:8px; border:1px solid #ddd;'>{chat['created']}</td></tr>"
        chat_table += "</table>"
    
    return f'''
    <html>
    <head>
        <title>Настройка Telegram</title>
        <meta charset="utf-8">
        <style>
            body {{ font-family: 'Segoe UI', Arial, sans-serif; padding: 40px; background: #f5f5f5; }}
            .container {{ max-width: 900px; margin: 0 auto; background: white; padding: 30px; border-radius: 10px; box-shadow: 0 2px 10px rgba(0,0,0,0.1); }}
            h1 {{ color: #2c3e50; margin-bottom: 10px; }}
            .status {{ background: #e8f5e9; padding: 15px; border-radius: 5px; margin: 20px 0; }}
            .status-good {{ color: #2e7d32; }}
            .status-bad {{ color: #c62828; background: #ffebee; }}
            ol {{ line-height: 2; }}
            a {{ color: #1976d2; text-decoration: none; }}
            a:hover {{ text-decoration: underline; }}
            .button {{ display: inline-block; padding: 10px 20px; background: #1976d2; color: white; border-radius: 5px; margin: 10px 5px; }}
            .button:hover {{ background: #1565c0; text-decoration: none; }}
            table {{ font-size: 14px; }}
            th {{ font-weight: 600; }}
            .back-link {{ margin-top: 30px; display: inline-block; }}
        </style>
    </head>
    <body>
        <div class="container">
            <h1>🤖 Настройка Telegram уведомлений</h1>
            
            <div class="status {'status-good' if len(chats) > 0 else 'status-bad'}">
                <strong>📊 Текущий статус:</strong><br>
                ✅ Активных подписчиков: <strong>{len(chats)}</strong><br>
                📋 Всего заявок: <strong>{len(load_requests())}</strong>
            </div>
            
            <h2>📝 Инструкция по настройке:</h2>
            <ol>
                <li>
                    <strong>Установите webhook:</strong><br>
                    <a class="button" href="https://api.telegram.org/bot7561142289:AAFVFusO4EQqxsz4-oDJjVHUPEfhIarlAcs/setWebhook?url=https://buhgalter-aktobe.vercel.app/telegram-webhook" target="_blank">
                        🔗 Настроить вебхук
                    </a>
                </li>
                <li>
                    <strong>Найдите бота в Telegram:</strong> @YourBotName
                </li>
                <li>
                    <strong>Отправьте команду:</strong> /start
                </li>
                <li>
                    <strong>Проверьте статус:</strong><br>
                    <a class="button" href="https://api.telegram.org/bot7561142289:AAFVFusO4EQqxsz4-oDJjVHUPEfhIarlAcs/getWebhookInfo" target="_blank">
                        ✅ Проверить статус webhook
                    </a>
                </li>
            </ol>
            
            <h2>👥 Подписчики:</h2>
            {chat_table if chat_table else '<p style="color: #999;">Пока нет подписчиков. Отправьте /start боту в Telegram.</p>'}
            
            <h2>💡 Доступные команды бота:</h2>
            <ul style="line-height: 2;">
                <li><code>/start</code> - подписаться на уведомления</li>
                <li><code>/stop</code> - отписаться от уведомлений</li>
                <li><code>/stats</code> - показать статистику заявок</li>
                <li><code>/today</code> - показать заявки за сегодня</li>
                <li><code>/help</code> - справка по командам</li>
            </ul>
            
            <a href="/admin" class="back-link">← Назад в админку</a>
        </div>
    </body>
    </html>
    '''

@app.route('/admin/setup-telegram-webhook')
@login_required
def setup_telegram_webhook():
    """Настроить webhook для Telegram (ручной вызов)"""
    result = set_telegram_webhook()
    if result and result.get('ok'):
        flash('✅ Webhook успешно настроен', 'success')
    else:
        flash('❌ Ошибка настройки webhook', 'error')
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
