import asyncio
import os
import sqlite3
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import parse_qsl
import hashlib
import hmac
import json
import time

from aiogram import Bot, Dispatcher, F
from aiogram.filters import CommandStart
from aiogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, WebAppInfo, LabeledPrice, PreCheckoutQuery, ReplyKeyboardMarkup, KeyboardButton, BotCommand, MenuButtonWebApp
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Header
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel

load_dotenv()
TOKEN = os.getenv('BOT_TOKEN', '')
WEBAPP_URL = os.getenv('WEBAPP_URL', '')
DB = os.getenv('DATABASE_PATH', 'levelup.sqlite3')
BASE = Path(__file__).resolve().parent.parent
bot = Bot(TOKEN) if TOKEN and TOKEN != 'PUT_NEW_TOKEN_HERE' else None
dp = Dispatcher()


def conn():
    c = sqlite3.connect(DB)
    c.row_factory = sqlite3.Row
    return c


def init_db():
    with conn() as c:
        c.executescript('''
        CREATE TABLE IF NOT EXISTS users(id INTEGER PRIMARY KEY, first_name TEXT, xp INTEGER DEFAULT 0, created_at INTEGER);
        CREATE TABLE IF NOT EXISTS goals(id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, title TEXT, done INTEGER DEFAULT 0);
        CREATE TABLE IF NOT EXISTS orders(id TEXT PRIMARY KEY, user_id INTEGER, product TEXT, stars INTEGER, created_at INTEGER);
        CREATE TABLE IF NOT EXISTS events(id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, kind TEXT, created_at INTEGER);
        CREATE TABLE IF NOT EXISTS mission_progress(user_id INTEGER, mission_id INTEGER, answer TEXT, completed_at INTEGER, PRIMARY KEY(user_id,mission_id));
        CREATE TABLE IF NOT EXISTS contacts(user_id INTEGER PRIMARY KEY, phone TEXT, consent_at INTEGER);
        ''')


def verify_init_data(data: str):
    if not bot or not data:
        raise HTTPException(401, 'Telegram authentication required')
    parsed = dict(parse_qsl(data, keep_blank_values=True))
    provided_hash = parsed.pop('hash', '')
    check = '\n'.join(f'{k}={v}' for k, v in sorted(parsed.items()))
    secret = hmac.new(b'WebAppData', TOKEN.encode(), hashlib.sha256).digest()
    expected = hmac.new(secret, check.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, provided_hash):
        raise HTTPException(401, 'Invalid Telegram signature')
    if abs(time.time() - int(parsed.get('auth_date', 0))) > 86400:
        raise HTTPException(401, 'Telegram login expired')
    user = json.loads(parsed.get('user', '{}'))
    if not user.get('id'):
        raise HTTPException(401, 'User missing')
    with conn() as c:
        c.execute('INSERT OR IGNORE INTO users(id,first_name,xp,created_at) VALUES(?,?,0,?)', (user['id'], user.get('first_name','Друг'), int(time.time())))
    return user


class GoalIn(BaseModel):
    title: str

class CheckoutIn(BaseModel):
    product: str = 'creator_start'

PRODUCTS = {'creator_start': {'title': 'LEVEL UP — Creator Start', 'description': 'Семь практических миссий по созданию цифрового проекта', 'stars': 150}}
SALES_ENABLED = os.getenv('ENABLE_SALES', 'false').lower() == 'true'
MISSIONS = [
 {'title':'Выбери свой проект','prompt':'Какой цифровой проект ты хочешь создать и для кого?','tip':'Выбери один понятный результат: канал, портфолио или мини-бренд.'},
 {'title':'Придумай название','prompt':'Запиши название проекта и одно предложение о его пользе.','tip':'Короткое название легче запомнить. Проверь его уникальность.'},
 {'title':'Определи визуальный стиль','prompt':'Опиши 2 основных цвета и настроение проекта.','tip':'Используй контрастные цвета и единый стиль.'},
 {'title':'Собери первые материалы','prompt':'Перечисли три визуальных материала, которые подготовишь.','tip':'Начни с аватара, обложки и шаблона публикации.'},
 {'title':'Создай контент-план','prompt':'Запиши идеи трёх полезных публикаций.','tip':'Каждая публикация должна отвечать на конкретный вопрос аудитории.'},
 {'title':'Проверь качество','prompt':'Перечисли три вещи, которые ты проверил перед запуском.','tip':'Читаемость, ссылки, ошибки и отображение на телефоне.'},
 {'title':'Подготовь проект к запуску','prompt':'Запиши три действия для публикации проекта.','tip':'Проверь материалы, настрой описание и покажи проект первому пользователю.'}
]

@dp.message(CommandStart())
async def start(message: Message):
    if not WEBAPP_URL.startswith('https://'):
        await message.answer('🟢 LEVEL UP готовится к запуску. Администратору необходимо указать WEBAPP_URL в .env.')
        return
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text='🚀 Открыть LEVEL UP', web_app=WebAppInfo(url=WEBAPP_URL))]])
    await message.answer('🟢 <b>LEVEL UP</b> — твой цифровой мир!\n\n⚡ Создавай проекты, прокачивай навыки, ставь цели и отслеживай прогресс.\n\n🔐 Вход через Telegram. Номер телефона не требуется.\n\nНажми ниже, чтобы начать.', reply_markup=kb, parse_mode='HTML')

@dp.message(F.text == '/help')
async def help_command(message: Message):
    await message.answer('🟢 LEVEL UP\n/start — открыть приложение\n/help — помощь\n/privacy — данные и конфиденциальность\n/phone — добровольно поделиться номером\n/support — поддержка')

@dp.message(F.text == '/privacy')
async def privacy_command(message: Message):
    await message.answer('Для входа используется Telegram ID и имя. Цели, прогресс и покупки хранятся для работы сервиса. Номер телефона не требуется и запрашивается только по желанию. По вопросам удаления данных напиши /support.')

@dp.message(F.text == '/support')
async def support_command(message: Message):
    await message.answer('Поддержка LEVEL UP: напиши владельцу бота. Контакт поддержки появится здесь после настройки SUPPORT_URL.')

@dp.message(F.text == '/phone')
async def phone_command(message: Message):
    kb = ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text='📱 Поделиться номером (необязательно)', request_contact=True)], [KeyboardButton(text='Пропустить')]], resize_keyboard=True, one_time_keyboard=True)
    await message.answer('Номер телефона необязателен для использования LEVEL UP. Если хочешь поделиться им, нажми кнопку ниже. Не отправляй чужой номер.', reply_markup=kb)

@dp.message(F.contact)
async def contact_command(message: Message):
    if not message.from_user or message.contact.user_id != message.from_user.id:
        await message.answer('Можно передать только свой контакт.'); return
    with conn() as c:
        c.execute('INSERT OR REPLACE INTO contacts(user_id,phone,consent_at) VALUES(?,?,?)', (message.from_user.id,message.contact.phone_number,int(time.time())))
    await message.answer('Готово. Номер сохранён по твоему согласию. Для входа он не нужен.', reply_markup=__import__('aiogram').types.ReplyKeyboardRemove())

@dp.message(F.text == 'Пропустить')
async def skip_contact(message: Message):
    await message.answer('Хорошо, продолжай без номера.', reply_markup=__import__('aiogram').types.ReplyKeyboardRemove())

@dp.pre_checkout_query()
async def checkout(query: PreCheckoutQuery):
    await query.answer(ok=SALES_ENABLED and query.currency == 'XTR' and query.invoice_payload in PRODUCTS)

@dp.message(F.successful_payment)
async def paid(message: Message):
    p = message.successful_payment
    if p.currency != 'XTR' or p.invoice_payload not in PRODUCTS:
        return
    with conn() as c:
        c.execute('INSERT OR IGNORE INTO orders(id,user_id,product,stars,created_at) VALUES(?,?,?,?,?)', (p.telegram_payment_charge_id, message.from_user.id, p.invoice_payload, p.total_amount, int(time.time())))
    await message.answer('✅ Оплата подтверждена! Комплект Creator Start открыт в приложении.')

@asynccontextmanager
async def lifespan(app):
    init_db()
    if bot:
        try:
            await bot.set_my_name(name='🟢 LEVEL UP')
            await bot.set_my_description(description='Твой цифровой мир: полезные миссии, проекты, цели и навыки. Развивайся каждый день!')
            await bot.set_my_short_description(short_description='Создавай. Учись. Прокачивайся. ⚡')
            await bot.set_my_commands([BotCommand(command='start',description='Открыть LEVEL UP'),BotCommand(command='help',description='Помощь'),BotCommand(command='privacy',description='Конфиденциальность'),BotCommand(command='phone',description='Номер по желанию'),BotCommand(command='support',description='Поддержка')])
            if WEBAPP_URL.startswith('https://'):
                await bot.set_chat_menu_button(menu_button=MenuButtonWebApp(text='Открыть LEVEL UP', web_app=WebAppInfo(url=WEBAPP_URL)))
        except Exception as exc:
            print('Bot profile setup skipped:', type(exc).__name__)
    task = asyncio.create_task(dp.start_polling(bot)) if bot else None
    yield
    if task:
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
    if bot:
        await bot.session.close()

app = FastAPI(title='LEVEL UP API', lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=[], allow_methods=['GET','POST'], allow_headers=['*'])

@app.get('/')
async def home():
    return FileResponse(BASE / 'frontend' / 'index.html')

@app.get('/health')
async def health():
    return {'status':'ok', 'bot_configured': bool(bot)}

@app.get('/api/me')
async def me(x_telegram_init_data: str = Header(default='')):
    user = verify_init_data(x_telegram_init_data)
    with conn() as c:
        u = c.execute('SELECT xp FROM users WHERE id=?', (user['id'],)).fetchone()
        goals = [dict(r) for r in c.execute('SELECT id,title,done FROM goals WHERE user_id=? ORDER BY id DESC', (user['id'],))]
        owned = [r['product'] for r in c.execute('SELECT DISTINCT product FROM orders WHERE user_id=?', (user['id'],))]
        completed = [r['mission_id'] for r in c.execute('SELECT mission_id FROM mission_progress WHERE user_id=?', (user['id'],))]
    return {'name':user.get('first_name','Друг'),'xp':u['xp'],'goals':goals,'owned':owned,'completed':completed,'sales_enabled':SALES_ENABLED}

@app.post('/api/goals')
async def add_goal(payload: GoalIn, x_telegram_init_data: str = Header(default='')):
    user = verify_init_data(x_telegram_init_data)
    title = payload.title.strip()
    if not 2 <= len(title) <= 100:
        raise HTTPException(400, 'Длина цели: 2–100 символов')
    with conn() as c:
        c.execute('INSERT INTO goals(user_id,title) VALUES(?,?)', (user['id'], title))
    return {'ok': True}

@app.post('/api/goals/{goal_id}/complete')
async def complete_goal(goal_id: int, x_telegram_init_data: str = Header(default='')):
    user = verify_init_data(x_telegram_init_data)
    with conn() as c:
        r = c.execute('UPDATE goals SET done=1 WHERE id=? AND user_id=? AND done=0', (goal_id,user['id']))
        if r.rowcount:
            c.execute('UPDATE users SET xp=xp+25 WHERE id=?', (user['id'],))
    return {'ok': True}

@app.post('/api/checkout')
async def checkout_link(payload: CheckoutIn, x_telegram_init_data: str = Header(default='')):
    verify_init_data(x_telegram_init_data)
    if not SALES_ENABLED:
        raise HTTPException(403, 'Продажи пока отключены до готовности материалов')
    if payload.product not in PRODUCTS or not bot:
        raise HTTPException(400, 'Product or bot unavailable')
    p = PRODUCTS[payload.product]
    url = await bot.create_invoice_link(title=p['title'], description=p['description'], payload=payload.product, currency='XTR', prices=[LabeledPrice(label=p['title'], amount=p['stars'])])
    return {'url':url}


class MissionAnswer(BaseModel):
    answer: str

@app.get('/api/missions')
async def missions(x_telegram_init_data: str = Header(default='')):
    verify_init_data(x_telegram_init_data)
    return {'missions': MISSIONS}

@app.post('/api/missions/{mission_id}/complete')
async def complete_mission(mission_id: int, payload: MissionAnswer, x_telegram_init_data: str = Header(default='')):
    user = verify_init_data(x_telegram_init_data)
    if mission_id < 0 or mission_id >= len(MISSIONS):
        raise HTTPException(404, 'Миссия не найдена')
    answer = payload.answer.strip()
    if len(answer) < 10 or len(answer) > 2000:
        raise HTTPException(400, 'Ответ должен содержать от 10 до 2000 символов')
    with conn() as c:
        if mission_id >= 2 and not c.execute('SELECT 1 FROM orders WHERE user_id=? AND product=?', (user['id'],'creator_start')).fetchone():
            raise HTTPException(403, 'Миссия доступна после покупки комплекта')
        r = c.execute('INSERT OR IGNORE INTO mission_progress(user_id,mission_id,answer,completed_at) VALUES(?,?,?,?)',(user['id'],mission_id,answer,int(time.time())))
        if r.rowcount:
            c.execute('UPDATE users SET xp=xp+40 WHERE id=?',(user['id'],))
    return {'ok':True,'xp_awarded':40 if r.rowcount else 0}
