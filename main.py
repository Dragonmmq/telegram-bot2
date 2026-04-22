import asyncio
import os
import time
import sqlite3
import logging
import html as html_lib
from aiohttp import web
from aiogram import Bot, Dispatcher, F, types
from aiogram.filters import CommandStart, Command
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.context import FSMContext

# ================= ENV SYSTEM =================

def get_env(name: str, required=True, default=None):
    value = os.getenv(name, default)
    if required and (value is None or value.strip() == ""):
        raise ValueError(f"❌ ENV переменная '{name}' не найдена")
    return value.strip() if isinstance(value, str) else value

TOKEN = get_env("TELEGRAM_BOT_TOKEN") or get_env("BOT_TOKEN", required=False)

if not TOKEN:
    raise ValueError("❌ Не найден ни TELEGRAM_BOT_TOKEN ни BOT_TOKEN")

PORT = int(os.getenv("PORT", 10000))

ADMINS = [1206582825]
CHANNEL_ID = -1002168740058

# лог
logging.basicConfig(level=logging.INFO)
logging.info(f"✅ TOKEN загружен: {TOKEN[:10]}...")

# ================= BOT =================

bot = Bot(token=TOKEN, parse_mode="HTML")
dp = Dispatcher()

# ================= DATABASE =================

conn = sqlite3.connect("bot.db", check_same_thread=False)
cursor = conn.cursor()

cursor.execute("""
CREATE TABLE IF NOT EXISTS messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER,
    text TEXT,
    media_type TEXT,
    file_id TEXT,
    date TIMESTAMP DEFAULT CURRENT_TIMESTAMP
)
""")

cursor.execute("""
CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT
)
""")

cursor.execute("INSERT OR IGNORE INTO settings VALUES ('forwarding','1')")
conn.commit()

def get_forwarding():
    cursor.execute("SELECT value FROM settings WHERE key='forwarding'")
    r = cursor.fetchone()
    return r[0] == "1" if r else True

def set_forwarding(v):
    cursor.execute("UPDATE settings SET value=? WHERE key='forwarding'", (v,))
    conn.commit()

# ================= FSM =================

class ReplyState(StatesGroup):
    waiting = State()

last_msg = {}
SPAM_DELAY = 5

# ================= UI =================

def forward_kb():
    status = get_forwarding()
    text = "🟢 Выключить" if status else "🔴 Включить"
    return InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text=text, callback_data="toggle")]]
    )

# ================= COMMANDS =================

@dp.message(CommandStart())
async def start(msg: types.Message):
    me = await bot.get_me()
    await msg.answer(
        f"👋 Напиши сюда — сообщение придёт анонимно\n\n🔗 https://t.me/{me.username}"
    )

@dp.message(Command("forward"))
async def forward_cmd(msg: types.Message):
    if msg.from_user.id not in ADMINS:
        return
    await msg.answer("⚙️ Настройки", reply_markup=forward_kb())

@dp.callback_query(F.data == "toggle")
async def toggle(cb: types.CallbackQuery):
    if cb.from_user.id not in ADMINS:
        return await cb.answer("Нет доступа", show_alert=True)

    new = not get_forwarding()
    set_forwarding("1" if new else "0")

    await cb.message.edit_text("⚙️ Обновлено", reply_markup=forward_kb())
    await cb.answer()

# ================= REPLY =================

@dp.callback_query(F.data.startswith("reply_"))
async def reply_handler(cb: types.CallbackQuery, state: FSMContext):
    uid = int(cb.data.split("_")[1])
    await state.update_data(uid=uid)
    await state.set_state(ReplyState.waiting)
    await cb.message.answer("✍️ Ответ:")
    await cb.answer()

@dp.message(ReplyState.waiting)
async def send_reply(msg: types.Message, state: FSMContext):
    data = await state.get_data()
    try:
        await bot.send_message(data["uid"], f"📬 Ответ:\n\n{msg.text}")
        await msg.answer("✅ Отправлено")
    except:
        await msg.answer("❌ Ошибка")
    await state.clear()

# ================= MAIN HANDLER =================

@dp.message()
async def handle(msg: types.Message):
    if msg.text and msg.text.startswith("/"):
        return

    user = msg.from_user
    now = time.time()

    if user.id in last_msg and now - last_msg[user.id] < SPAM_DELAY:
        return await msg.answer("⏳ Подожди")

    last_msg[user.id] = now

    text = msg.text or ""

    # ===== В КАНАЛ =====
    if get_forwarding():
        try:
            await bot.send_message(
                CHANNEL_ID,
                f"<blockquote>💬 {html_lib.escape(text)}</blockquote>"
            )
        except Exception as e:
            logging.error(f"Ошибка канала: {e}")

    # ===== АДМИНУ =====
    username = f"@{user.username}" if user.username else "нет"
    admin_text = (
        f"📩 <b>Аноним</b>\n\n"
        f"👤 {user.full_name}\n"
        f"🔗 {username}\n"
        f"🆔 <code>{user.id}</code>\n\n"
        f"{html_lib.escape(text)}"
    )

    kb = InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="↩️ Ответить", callback_data=f"reply_{user.id}")]]
    )

    for admin in ADMINS:
        try:
            await bot.send_message(admin, admin_text, reply_markup=kb)
        except Exception as e:
            logging.error(f"Ошибка админа: {e}")

    cursor.execute(
        "INSERT INTO messages (user_id, text) VALUES (?, ?)",
        (user.id, text)
    )
    conn.commit()

    await msg.answer("✅ Отправлено")

# ================= WEB =================

async def web_handler(request):
    return web.Response(text="OK")

async def start_web():
    app = web.Application()
    app.router.add_get("/", web_handler)

    runner = web.AppRunner(app)
    await runner.setup()

    site = web.TCPSite(runner, "0.0.0.0", PORT)
    await site.start()

# ================= RUN =================

async def main():
    logging.info("🚀 Бот запускается...")
    await start_web()
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
