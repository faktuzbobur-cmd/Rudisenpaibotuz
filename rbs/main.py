import asyncio
import logging
import sqlite3
from aiogram import Bot, Dispatcher, F, Router
from aiogram.filters import Command, CommandStart, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)
from aiogram.exceptions import TelegramForbiddenError, TelegramBadRequest

# ==================== SOZLAMALAR ====================
BOT_TOKEN = "8528445893:AAHkhAPGSh-7IAlZhdLYmJ3ucRXyX-YzFvM" # O'zingizning tokeningizni qo'ying
ADMIN_USERNAMES = ["Nagi_lv7", "faktuzbobur"] # Adminlarning username'lari (@ belgisiz)
DB_NAME = "bot_database.db"

# ==================== BAZA BILAN ISHLASH ====================
def init_db():
    with sqlite3.connect(DB_NAME) as conn:
        cursor = conn.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                full_name TEXT,
                username TEXT,
                is_banned INTEGER DEFAULT 0
            )
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS media (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                code INTEGER,
                title TEXT,
                file_id TEXT,
                season INTEGER DEFAULT 1,
                episode INTEGER DEFAULT 1,
                views INTEGER DEFAULT 0
            )
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS channels (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                channel_username TEXT UNIQUE
            )
        """)
        conn.commit()

def is_admin(username: str) -> bool:
    if not username: return False
    return username.lower() in [u.lower() for u in ADMIN_USERNAMES]

def get_required_channels() -> list:
    with sqlite3.connect(DB_NAME) as conn:
        return [row[0] for row in conn.execute("SELECT channel_username FROM channels").fetchall()]

async def check_all_subscriptions(user_id: int, bot: Bot) -> list:
    channels = get_required_channels()
    unsubscribed_channels = []
    for channel in channels:
        try:
            member = await bot.get_chat_member(chat_id=channel, user_id=user_id)
            if member.status not in ["creator", "administrator", "member"]:
                unsubscribed_channels.append(channel)
        except Exception:
            # Agar bot kanalga admin qilinmagan bo'lsa yoki kanal noto'g'ri bo'lsa
            unsubscribed_channels.append(channel)
    return unsubscribed_channels

# ==================== FSM STATES ====================
class AdminStates(StatesGroup):
    add_code = State()
    add_title = State()
    add_season = State()
    add_episode = State()
    add_photo = State()
    add_file = State()
    
    delete_code = State()
    
    add_channel = State()
    del_channel = State()
    
    broadcast_msg = State()
    ban_user = State()
    unban_user = State()

# ==================== KEYBOARDLAR ====================
router = Router()

def get_admin_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ Serial qo'shish", callback_data="adm_add"), 
         InlineKeyboardButton(text="🗑 Serialni o'chirish", callback_data="adm_del")],
        [InlineKeyboardButton(text="📢 Kanal qo'shish", callback_data="adm_add_ch"), 
         InlineKeyboardButton(text="➖ Kanal o'chirish", callback_data="adm_del_ch")],
        [InlineKeyboardButton(text="🔥 Top ko'rilganlar", callback_data="adm_top"), 
         InlineKeyboardButton(text="📊 Statistika", callback_data="adm_stats")],
        [InlineKeyboardButton(text="📢 Reklama yuborish", callback_data="adm_broadcast")],
        [InlineKeyboardButton(text="🚫 Ban qilish", callback_data="adm_ban"), 
         InlineKeyboardButton(text="✅ Unban", callback_data="adm_unban")]
    ])

def get_sub_keyboard(channels: list):
    buttons = []
    for ch in channels:
        clean_ch = ch.replace("@", "")
        buttons.append([InlineKeyboardButton(text=f"📢 A'zo bo'lish: {ch}", url=f"https://t.me/{clean_ch}")])
    buttons.append([InlineKeyboardButton(text="✅ Obunani tekshirish", callback_data="check_sub")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)

# ==================== ASOSIY HANDLERLAR ====================
@router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext, bot: Bot):
    await state.clear()
    user = message.from_user
    args = message.text.split()
    
    with sqlite3.connect(DB_NAME) as conn:
        res = conn.execute("SELECT is_banned FROM users WHERE user_id = ?", (user.id,)).fetchone()
        if res and res[0] == 1:
            await message.answer("❌ Siz botdan ban qilingansiz!")
            return
        
        conn.execute("""
            INSERT OR REPLACE INTO users (user_id, full_name, username, is_banned) 
            VALUES (?, ?, ?, COALESCE((SELECT is_banned FROM users WHERE user_id = ?), 0))
        """, (user.id, user.full_name, user.username, user.id))
        conn.commit()

    not_subbed = await check_all_subscriptions(user.id, bot)
    if not_subbed:
        if len(args) > 1:
            await state.update_data(deep_code=args[1])
            
        await message.answer(
            "⚠️ **RudiSenpaiBot dan to'liq foydalanish uchun quyidagi kanallarga a'zo bo'lishingiz shart:**\n\n"
            "A'zo bo'lib, pastdagi **'✅ Obunani tekshirish'** tugmasini bosing!",
            reply_markup=get_sub_keyboard(not_subbed),
            parse_mode="Markdown"
        )
        return

    if len(args) > 1 and args[1].startswith("kod_"):
        code_str = args[1].replace("kod_", "")
        if code_str.isdigit():
            await process_serial_search(message, int(code_str), bot)
            return

    msg = f"👋 Xush kelibsiz, {user.full_name}!\n\n📺 Serial yoki anime kodini yuboring:"
    kb = get_admin_keyboard() if is_admin(user.username) else None
    await message.answer(msg, reply_markup=kb)

@router.callback_query(F.data == "check_sub")
async def check_sub_callback(call: CallbackQuery, bot: Bot, state: FSMContext):
    not_subbed = await check_all_subscriptions(call.from_user.id, bot)
    if not not_subbed:
        await call.message.delete()
        
        data = await state.get_data()
        deep_code = data.get("deep_code")
        
        if deep_code and deep_code.startswith("kod_"):
            code_str = deep_code.replace("kod_", "")
            if code_str.isdigit():
                await call.message.answer("✅ Obuna tasdiqlandi!")
                call.message.text = code_str
                await search_by_code(call.message, bot)
                return

        msg = f"✅ Rahmat! Obuna tasdiqlandi.\n\n📺 Ko'rmoqchi bo'lgan serialingiz kodini yuboring:"
        kb = get_admin_keyboard() if is_admin(call.from_user.username) else None
        await call.message.answer(msg, reply_markup=kb)
    else:
        await call.answer("❌ Hali barcha kanallarga a'zo bo'lmadingiz!", show_alert=True)

# ==================== ADMIN: SERIAL QO'SHISH ====================
@router.callback_query(F.data == "adm_add")
async def adm_add_start(call: CallbackQuery, state: FSMContext):
    if not is_admin(call.from_user.username): return
    await state.set_state(AdminStates.add_code)
    await call.message.answer("1️⃣ Serial uchun **kod** kiriting (faqat raqam, masalan: 101):")
    await call.answer()

@router.message(AdminStates.add_code, F.text.isdigit())
async def adm_add_code(message: Message, state: FSMContext):
    await state.update_data(code=int(message.text))
    await state.set_state(AdminStates.add_title)
    await message.answer("2️⃣ Serial **nomini** kiriting:")

@router.message(AdminStates.add_code)
async def err_add_code(message: Message): await message.answer("❌ XATO: Faqat raqam yuboring!")

@router.message(AdminStates.add_title, F.text)
async def adm_add_title(message: Message, state: FSMContext):
    await state.update_data(title=message.text)
    await state.set_state(AdminStates.add_season)
    await message.answer("3️⃣ **Fasl raqamini** kiriting (masalan: 1):")

@router.message(AdminStates.add_title)
async def err_add_title(message: Message): await message.answer("❌ XATO: Iltimos, matn ko'rinishida nom kiriting!")

@router.message(AdminStates.add_season, F.text.isdigit())
async def adm_add_season(message: Message, state: FSMContext):
    await state.update_data(season=int(message.text))
    await state.set_state(AdminStates.add_episode)
    await message.answer("4️⃣ **Qism raqamini** kiriting (masalan: 1):")

@router.message(AdminStates.add_season)
async def err_add_season(message: Message): await message.answer("❌ XATO: Faqat raqam yuboring!")

@router.message(AdminStates.add_episode, F.text.isdigit())
async def adm_add_ep(message: Message, state: FSMContext):
    await state.update_data(episode=int(message.text))
    await state.set_state(AdminStates.add_photo)
    await message.answer("5️⃣ Kanalga tashlash uchun **anime rasmini (poster)** yuboring:")

@router.message(AdminStates.add_episode)
async def err_add_ep(message: Message): await message.answer("❌ XATO: Faqat raqam yuboring!")

@router.message(AdminStates.add_photo, F.photo)
async def adm_add_photo(message: Message, state: FSMContext):
    await state.update_data(photo_id=message.photo[-1].file_id)
    await state.set_state(AdminStates.add_file)
    await message.answer("6️⃣ Endi serial qismining **video faylini** yuboring:")

@router.message(AdminStates.add_photo)
async def err_add_photo(message: Message): await message.answer("❌ XATO: Siz rasm o'rniga boshqa narsa yubordingiz. Faqat **rasm** yuboring!")

@router.message(AdminStates.add_file, F.video)
async def adm_add_file(message: Message, state: FSMContext):
    data = await state.get_data()
    
    with sqlite3.connect(DB_NAME) as conn:
        conn.execute("""
            INSERT INTO media (code, title, season, episode, file_id)
            VALUES (?, ?, ?, ?, ?)
        """, (data['code'], data['title'], data['season'], data['episode'], message.video.file_id))
        conn.commit()
    
    bot_info = await message.bot.get_me()
    channel_btn = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔹 Tomosha qilish 🔹", url=f"https://t.me/{bot_info.username}?start=kod_{data['code']}")]
    ])
    
    caption = f"🎬 **{data['title']}**\n📌 {data['season']}-Fasl, {data['episode']}-Qism\n🔑 Kod: `{data['code']}`"
    
    await message.answer("✅ Barchasi tayyor! Kanalingizga tashlash uchun tayyor post:")
    await message.answer_photo(photo=data['photo_id'], caption=caption, reply_markup=channel_btn, parse_mode="Markdown")
    await state.clear()

@router.message(AdminStates.add_file)
async def err_add_file(message: Message): await message.answer("❌ XATO: Bu yerga faqat **video fayl** yuboring!")

# ==================== ADMIN: SERIALNI O'CHIRISH ====================
@router.callback_query(F.data == "adm_del")
async def adm_del_start(call: CallbackQuery, state: FSMContext):
    if not is_admin(call.from_user.username): return
    await state.set_state(AdminStates.delete_code)
    await call.message.answer("🗑 O'chirmoqchi bo'lgan serialning **kodini** kiriting:")
    await call.answer()

@router.message(AdminStates.delete_code, F.text.isdigit())
async def adm_del_execute(message: Message, state: FSMContext):
    code = int(message.text)
    with sqlite3.connect(DB_NAME) as conn:
        count = conn.execute("SELECT COUNT(*) FROM media WHERE code = ?", (code,)).fetchone()[0]
        if count == 0:
            await message.answer(f"❌ {code}-kodli serial topilmadi.")
        else:
            conn.execute("DELETE FROM media WHERE code = ?", (code,))
            conn.commit()
            await message.answer(f"✅ {code}-kodli serialga tegishli barcha ({count} ta) qismlar bazadan o'chirildi!")
    await state.clear()

@router.message(AdminStates.delete_code)
async def err_del_code(message: Message): await message.answer("❌ XATO: Faqat raqam yuboring!")

# ==================== ADMIN: KANAL QO'SHISH/O'CHIRISH ====================
@router.callback_query(F.data == "adm_add_ch")
async def add_ch_start(call: CallbackQuery, state: FSMContext):
    if not is_admin(call.from_user.username): return
    await state.set_state(AdminStates.add_channel)
    await call.message.answer("📢 Majburiy obuna uchun kanal username'ni kiriting (masalan: @mening_kanalim):")
    await call.answer()

@router.message(AdminStates.add_channel, F.text.startswith("@"))
async def add_ch_exec(message: Message, state: FSMContext):
    with sqlite3.connect(DB_NAME) as conn:
        try:
            conn.execute("INSERT INTO channels (channel_username) VALUES (?)", (message.text,))
            conn.commit()
            await message.answer(f"✅ {message.text} kanali majburiy obunalarga qo'shildi!\n\n⚠️ Eslatma: Bot ushbu kanalda admin bo'lishi shart!")
        except sqlite3.IntegrityError:
            await message.answer("❌ Bu kanal allaqachon qo'shilgan!")
    await state.clear()

@router.message(AdminStates.add_channel)
async def err_add_ch(message: Message): await message.answer("❌ XATO: Kanal nomi @ belgisi bilan boshlanishi kerak!")

@router.callback_query(F.data == "adm_del_ch")
async def del_ch_start(call: CallbackQuery, state: FSMContext):
    if not is_admin(call.from_user.username): return
    channels = get_required_channels()
    if not channels:
        await call.message.answer("🤷‍♂️ Hozircha hech qanday kanal qo'shilmagan.")
        return
    ch_list = "\n".join(channels)
    await state.set_state(AdminStates.del_channel)
    await call.message.answer(f"📋 Hozirgi kanallar:\n{ch_list}\n\nO'chirmoqchi bo'lgan kanalni yozing (masalan: @mening_kanalim):")
    await call.answer()

@router.message(AdminStates.del_channel, F.text.startswith("@"))
async def del_ch_exec(message: Message, state: FSMContext):
    with sqlite3.connect(DB_NAME) as conn:
        conn.execute("DELETE FROM channels WHERE channel_username = ?", (message.text,))
        conn.commit()
    await message.answer(f"✅ {message.text} ro'yxatdan o'chirildi.")
    await state.clear()

# ==================== ADMIN: STATS VA TOP ====================
@router.callback_query(F.data == "adm_stats")
async def show_stats(call: CallbackQuery):
    if not is_admin(call.from_user.username): return
    with sqlite3.connect(DB_NAME) as conn:
        users_count = conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
        media_count = conn.execute("SELECT COUNT(*) FROM media").fetchone()[0]
    await call.message.answer(f"📊 **Statistika:**\n\n👥 Jami foydalanuvchilar: {users_count} ta\n🎬 Jami yuklangan qismlar: {media_count} ta")
    await call.answer()

@router.callback_query(F.data == "adm_top")
async def show_top(call: CallbackQuery):
    if not is_admin(call.from_user.username): return
    with sqlite3.connect(DB_NAME) as conn:
        top = conn.execute("SELECT title, code, views FROM media GROUP BY code ORDER BY views DESC LIMIT 10").fetchall()
    
    if not top:
        await call.message.answer("Hali hech narsa ko'rilmadi.")
        return
        
    msg = "🔥 **Eng ko'p ko'rilgan seriallar (Top 10):**\n\n"
    for i, (title, code, views) in enumerate(top, 1):
        msg += f"{i}. **{title}** (Kod: {code}) - 👁 {views} marta\n"
        
    await call.message.answer(msg, parse_mode="Markdown")
    await call.answer()

# ==================== ADMIN: BROADCAST VA BAN ====================
@router.callback_query(F.data == "adm_broadcast")
async def broadcast_start(call: CallbackQuery, state: FSMContext):
    if not is_admin(call.from_user.username): return
    await state.set_state(AdminStates.broadcast_msg)
    await call.message.answer("📢 Barcha foydalanuvchilarga yubormoqchi bo'lgan xabaringizni yozing:")
    await call.answer()

@router.message(AdminStates.broadcast_msg)
async def broadcast_exec(message: Message, state: FSMContext):
    with sqlite3.connect(DB_NAME) as conn:
        users = conn.execute("SELECT user_id FROM users WHERE is_banned = 0").fetchall()
    
    sent = 0
    await message.answer("⏳ Tarqatish boshlandi...")
    for (uid,) in users:
        try:
            await message.copy_to(chat_id=uid)
            sent += 1
            await asyncio.sleep(0.05) # Telegram limitlariga tushmaslik uchun
        except Exception:
            pass
            
    await message.answer(f"✅ Xabar {sent} ta foydalanuvchiga muvaffaqiyatli yetkazildi.")
    await state.clear()

# ==================== QISMLARNI KETMA-KET YUBORISH ====================
async def process_serial_search(message: Message, code: int, bot: Bot):
    with sqlite3.connect(DB_NAME) as conn:
        results = conn.execute("SELECT file_id, title, season, episode FROM media WHERE code = ? ORDER BY season, episode", (code,)).fetchall()
        
        if not results:
            await message.answer("❌ Bu kod bo'yicha hech qanday serial topilmadi.")
            return

        conn.execute("UPDATE media SET views = views + 1 WHERE code = ?", (code,))
        conn.commit()
    
    await message.answer(f"🎬 Topildi! Serial qismlari ketma-ket yuborilmoqda ⬇️")
    
    for file_id, title, s, ep in results:
        cap = f"🎬 {title}\n📌 {s}-Fasl, {ep}-Qism"
        try:
            await bot.send_video(chat_id=message.chat.id, video=file_id, caption=cap)
            await asyncio.sleep(0.3) 
        except Exception as e:
            logging.error(f"Video yuborishda xato: {e}")

@router.message(StateFilter(None), F.text.isdigit())
async def search_by_code(message: Message, bot: Bot):
    not_subbed = await check_all_subscriptions(message.from_user.id, bot)
    if not_subbed:
        await message.answer("⚠️ Avval kanallarga a'zo bo'ling:", reply_markup=get_sub_keyboard(not_subbed))
        return
    await process_serial_search(message, int(message.text), bot)

# ==================== MAIN RUNNER ====================
async def main():
    logging.basicConfig(level=logging.INFO)
    init_db()
    bot = Bot(token=BOT_TOKEN)
    dp = Dispatcher(storage=MemoryStorage())
    dp.include_router(router)
    await bot.delete_webhook(drop_pending_updates=True)
    logging.info("Bot ishga tushdi...")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())