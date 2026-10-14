import os
import json
import asyncio
from datetime import datetime, timezone, timedelta
from fastapi import FastAPI, Request
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram import ReplyKeyboardMarkup, KeyboardButton
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ContextTypes
from upstash_redis.asyncio import Redis

TOKEN = os.environ.get("BOT_TOKEN")

redis = Redis(
    url=os.environ.get("UPSTASH_REDIS_REST_URL"),
    token=os.environ.get("UPSTASH_REDIS_REST_TOKEN")
)

DATA_KEY = "bot_data"
SPONSORS_KEY = "sponsor_channels"
BLOCKED_CHANNELS_KEY = "blocked_channels"
BLOCKED_USERS_KEY = "blocked_users"

_initialized = False

# ----- تنظیمات ثابت -----
ADMIN_ID = 7724653657
ADMIN_USERNAME = "@Dorinamm"
ORDER_CHANNEL_ID = "@viewpluse"
ORDER_CHANNEL_URL = "https://t.me/viewpluse"
CHANNEL_USERNAME = "viewpluse"
DAILY_COINS_AMOUNT = 3
DAILY_COINS_COOLDOWN_HOURS = 24
DEFAULT_SPONSOR_CHANNELS = [c.strip() for c in os.environ.get("SPONSOR_CHANNELS", "@patrickeeee,@infinitiiii2,@viewpluse").split(",") if c.strip()]
REFUND_RATE = 1
# ---------------------------------------------------

# ---------- توابع کمکی ----------
def gregorian_to_jalali(gy, gm, gd):
    g_d_m = [0, 31, 59, 90, 120, 151, 181, 212, 243, 273, 304, 334]
    gy2 = gy - 1600
    gm2 = gm - 1
    gd2 = gd - 1
    g_day_no = 365 * gy2 + (gy2 + 3) // 4 - (gy2 + 99) // 100 + (gy2 + 399) // 400
    g_day_no += g_d_m[gm2] + gd2
    if gm > 2 and ((gy % 4 == 0 and gy % 100 != 0) or gy % 400 == 0):
        g_day_no += 1
    j_day_no = g_day_no - 79
    j_np = j_day_no // 12053
    j_day_no %= 12053
    jy = 979 + 33 * j_np + 4 * (j_day_no // 1461)
    j_day_no %= 1461
    if j_day_no >= 366:
        jy += (j_day_no - 1) // 365
        j_day_no = (j_day_no - 1) % 365
    j_days_in_month = [31, 31, 31, 31, 31, 31, 30, 30, 30, 30, 30, 29]
    jm = 1
    for i in range(11):
        if j_day_no < j_days_in_month[i]:
            jm = i + 1
            break
        j_day_no -= j_days_in_month[i]
    else:
        jm = 12
    jd = j_day_no + 1
    return jy, jm, jd

def format_task_message(order):
    try:
        dt = datetime.fromisoformat(order["created_at"])
        jy, jm, jd = gregorian_to_jalali(dt.year, dt.month, dt.day)
        date_str = f"{jy}/{jm:02d}/{jd:02d}"
        time_str = dt.strftime("%H:%M:%S")
    except Exception:
        date_str = "---"
        time_str = "---"
    return (
        f"❇️ شماره سفارش: {order['id']}\n"
        f"🌐 آیدی کانال : {order['target_id']}\n"
        f"📆 تاریخ درخواست: {date_str}\n"
        f"⏰ساعت درخواست: {time_str}\n"
        f"⏳ ممبر درخواستی: {order['count']}\n"
        f"👥️ ممبردریافتی: {order['claimed']}\n"
        f"💔تعداد لفت ها : {order.get('left_count', 0)}\n"
        f"‍📇مشاهده سفارش : /ord_{order['id']}\n"
        f"❌لغو سفارش : /cancel_{order['id']}\n"
        f"‼️ وضعیت سفارش: در حال اجرا ♻\n"
        f"—----------------------------"
    )

# ---------- دیتابیس ----------
async def get_sponsor_channels():
    raw = await redis.get(SPONSORS_KEY)
    if raw:
        try:
            return json.loads(raw)
        except Exception:
            return DEFAULT_SPONSOR_CHANNELS
    return DEFAULT_SPONSOR_CHANNELS

async def set_sponsor_channels(channels):
    await redis.set(SPONSORS_KEY, json.dumps(channels))

async def get_blocked_channels():
    raw = await redis.get(BLOCKED_CHANNELS_KEY)
    if raw:
        try:
            return json.loads(raw)
        except Exception:
            return []
    return []

async def set_blocked_channels(channels):
    await redis.set(BLOCKED_CHANNELS_KEY, json.dumps(channels))

async def get_blocked_users():
    raw = await redis.get(BLOCKED_USERS_KEY)
    if raw:
        try:
            return json.loads(raw)
        except Exception:
            return []
    return []

async def set_blocked_users(users):
    await redis.set(BLOCKED_USERS_KEY, json.dumps(users))

async def is_channel_blocked(channel_id):
    blocked = await get_blocked_channels()
    normalized = channel_id.lower().strip()
    for b in blocked:
        if b.lower().strip() == normalized:
            return True
    return False

async def is_user_blocked(user_id):
    blocked = await get_blocked_users()
    return str(user_id) in [str(u) for u in blocked]

async def get_data():
    raw = await redis.get(DATA_KEY)
    defaults = {
        "users": {"7724653657": 10000},
        "tasks": [],
        "completed": {},
        "next_task_id": 1,
        "states": {},
        "daily_claims": {},
        "usernames": {},
        "join_records": []
    }
    if raw:
        data = json.loads(raw)
        for key, value in defaults.items():
            if key not in data:
                data[key] = value
        return data
    else:
        return defaults

async def set_data(data):
    await redis.set(DATA_KEY, json.dumps(data))

# ---------- بررسی عضویت ----------
async def check_subscription(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    sponsors = await get_sponsor_channels()
    if not sponsors:
        return True
    user_id = update.effective_user.id
    for channel in sponsors:
        try:
            member = await context.bot.get_chat_member(chat_id=channel, user_id=user_id)
            if member.status not in ["member", "administrator", "creator"]:
                return False
        except Exception:
            return False
    return True

async def send_subscription_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    sponsors = await get_sponsor_channels()
    if not sponsors:
        return
    text = (
        "❗️لطفا برای ادامه کار با ربات و حمایت کردن از ما عضو گروه و کانال های زیر شوید👇\n\n"
        + "\n".join([f"🆔 {ch}" for ch in sponsors])
        + "\n\n💎اسپانسر ها:\n"
        + "\n".join([f"🪅{i+1} {ch}" for i, ch in enumerate(sponsors)])
        + "\n\n❗️پس از عضو شدن برای ربات دستور /start را ارسال کنید✓"
    )
    await update.message.reply_text(text)

# =====================================================
# ---------- پنل ادمین ----------
# =====================================================
async def admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type != "private":
        return
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("شما اجازه استفاده از این دستور را ندارید.")
        return

    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("🪪 تنظیم اسپانسرها", callback_data="admin_set_sponsors")],
        [InlineKeyboardButton("🚫 مسدود کردن کانال", callback_data="admin_block_channel")],
        [InlineKeyboardButton("♻️ خارج کردن کانال از بلاک", callback_data="admin_unblock_channel")],
        [InlineKeyboardButton("📋 لیست کانال‌های بلاک‌شده", callback_data="admin_blocked_list")],
        [InlineKeyboardButton("⛔ مسدود کردن کاربر", callback_data="admin_block_user")],
        [InlineKeyboardButton("✅ آزاد کردن کاربر", callback_data="admin_unblock_user")],
        [InlineKeyboardButton("🟢 تکمیل سفارش", callback_data="admin_done_task")],
        [InlineKeyboardButton("📢 پیام همگانی", callback_data="admin_broadcast")],
        [InlineKeyboardButton("💎 افزایش الماس به کاربر", callback_data="admin_give_coins")],
    ])
    await update.message.reply_text(
        "🎛 پنل مدیریت ربات\n\n"
        "لطفاً یکی از گزینه‌های زیر را انتخاب کنید:",
        reply_markup=keyboard
    )

async def admin_panel_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if query.from_user.id != ADMIN_ID:
        return

    action = query.data

    if action == "admin_set_sponsors":
        data = await get_data()
        data["states"][str(ADMIN_ID)] = {"admin_action": "set_sponsors"}
        await set_data(data)
        await query.edit_message_text(
            "🪪 لطفاً اسپانسرها را به صورت لیست جدا شده با کاما ارسال کنید.\n\n"
            "مثال:\n`@ch1,@ch2,@ch3`\n\n"
            "برای حذف همه: `clear`\n"
            "برای بازگشت به پیش‌فرض: `reset`",
            parse_mode="Markdown"
        )

    elif action == "admin_block_channel":
        data = await get_data()
        data["states"][str(ADMIN_ID)] = {"admin_action": "block_channel"}
        await set_data(data)
        await query.edit_message_text(
            "🚫 لطفاً آیدی کانال مورد نظر را برای مسدود کردن ارسال کنید.\n\n"
            "مثال: `@channel` یا `-1001234567890`",
            parse_mode="Markdown"
        )

    elif action == "admin_unblock_channel":
        data = await get_data()
        data["states"][str(ADMIN_ID)] = {"admin_action": "unblock_channel"}
        await set_data(data)
        await query.edit_message_text(
            "♻️ لطفاً آیدی کانالی که می‌خواهید از بلاک خارج شود را ارسال کنید.\n\n"
            "مثال: `@channel`",
            parse_mode="Markdown"
        )

    elif action == "admin_blocked_list":
        blocked = await get_blocked_channels()
        if not blocked:
            await query.edit_message_text("لیست کانال‌های بلاک‌شده خالی است.")
        else:
            text = "🚫 کانال‌های مسدود شده:\n\n" + "\n".join([f"🆔 {ch}" for ch in blocked])
            await query.edit_message_text(text)

    elif action == "admin_block_user":
        data = await get_data()
        data["states"][str(ADMIN_ID)] = {"admin_action": "block_user"}
        await set_data(data)
        await query.edit_message_text("⛔ لطفاً آیدی عددی کاربر مورد نظر را ارسال کنید.")

    elif action == "admin_unblock_user":
        data = await get_data()
        data["states"][str(ADMIN_ID)] = {"admin_action": "unblock_user"}
        await set_data(data)
        await query.edit_message_text("✅ لطفاً آیدی عددی کاربری که می‌خواهید آزاد شود را ارسال کنید.")

    elif action == "admin_done_task":
        data = await get_data()
        data["states"][str(ADMIN_ID)] = {"admin_action": "done_task"}
        await set_data(data)
        await query.edit_message_text("🟢 لطفاً شماره سفارش مورد نظر را ارسال کنید.")

    elif action == "admin_broadcast":
        data = await get_data()
        data["states"][str(ADMIN_ID)] = {"admin_action": "broadcast"}
        await set_data(data)
        await query.edit_message_text(
            "📢 لطفاً متن پیام همگانی را ارسال کنید.\n\n"
            "برای ارسال عکس/ویدیو/فایل، روی پیام ریپلای کنید و کلمه `broadcast` را بفرستید."
        )

    elif action == "admin_give_coins":
        data = await get_data()
        data["states"][str(ADMIN_ID)] = {"admin_action": "give_coins"}
        await set_data(data)
        await query.edit_message_text(
            "💎 لطفاً آیدی کاربر و مقدار الماس را به این صورت ارسال کنید:\n\n"
            "`user_id amount`\n\n"
            "مثال: `123456789 50`",
            parse_mode="Markdown"
        )

# ---------- پردازش ورودی‌های پنل ادمین ----------
async def process_admin_input(update: Update, context: ContextTypes.DEFAULT_TYPE, admin_action, text_input):
    if admin_action == "set_sponsors":
        arg = text_input.strip().lower()
        if arg == "clear":
            await set_sponsor_channels([])
            await update.message.reply_text("✅ همه اسپانسرها حذف شدند.")
            return True
        if arg == "reset":
            await set_sponsor_channels(DEFAULT_SPONSOR_CHANNELS)
            txt = "✅ بازگشت به پیش‌فرض:\n\n" + "\n".join([f"🆔 {ch}" for ch in DEFAULT_SPONSOR_CHANNELS])
            await update.message.reply_text(txt)
            return True
        channels = [c.strip() for c in text_input.split(",") if c.strip()]
        if not channels:
            await update.message.reply_text("❌ فرمت نامعتبر. مثال: @ch1,@ch2,@ch3")
            return True
        for ch in channels:
            if not (ch.startswith("@") or ch.startswith("-") or ch.lstrip("-").isdigit()):
                await update.message.reply_text(f"❌ آیدی «{ch}» معتبر نیست.")
                return True
        await set_sponsor_channels(channels)
        txt = "✅ اسپانسرها به‌روز شدند:\n\n" + "\n".join([f"🆔 {ch}" for ch in channels])
        await update.message.reply_text(txt)
        return True

    elif admin_action == "block_channel":
        ch = text_input.strip()
        blocked = await get_blocked_channels()
        if ch in blocked:
            await update.message.reply_text(f"⚠️ {ch} قبلاً مسدود شده.")
            return True
        blocked.append(ch)
        await set_blocked_channels(blocked)
        await update.message.reply_text(f"✅ کانال {ch} مسدود شد.")
        return True

    elif admin_action == "unblock_channel":
        ch = text_input.strip()
        blocked = await get_blocked_channels()
        new_blocked = [b for b in blocked if b.lower() != ch.lower()]
        if len(new_blocked) == len(blocked):
            await update.message.reply_text(f"⚠️ {ch} در لیست بلاک نبود.")
            return True
        await set_blocked_channels(new_blocked)
        await update.message.reply_text(f"✅ {ch} از بلاک خارج شد.")
        return True

    elif admin_action == "block_user":
        uid = text_input.strip()
        if not uid.isdigit():
            await update.message.reply_text("❌ آیدی عددی معتبر نیست.")
            return True
        users = await get_blocked_users()
        if uid in [str(u) for u in users]:
            await update.message.reply_text(f"⚠️ کاربر {uid} قبلاً مسدود شده.")
            return True
        users.append(uid)
        await set_blocked_users(users)
        await update.message.reply_text(f"✅ کاربر {uid} مسدود شد.")
        return True

    elif admin_action == "unblock_user":
        uid = text_input.strip()
        users = await get_blocked_users()
        new_users = [u for u in users if str(u) != uid]
        if len(new_users) == len(users):
            await update.message.reply_text(f"⚠️ کاربر {uid} در لیست بلاک نبود.")
            return True
        await set_blocked_users(new_users)
        await update.message.reply_text(f"✅ کاربر {uid} از بلاک خارج شد.")
        return True

    elif admin_action == "done_task":
        try:
            task_id = int(text_input.strip())
        except ValueError:
            await update.message.reply_text("❌ شماره سفارش باید عدد باشد.")
            return True
        data = await get_data()
        task = next((t for t in data["tasks"] if t["id"] == task_id), None)
        if not task:
            await update.message.reply_text("❌ سفارش یافت نشد.")
            return True
        if "message_id" in task:
            try:
                await context.bot.delete_message(chat_id=ORDER_CHANNEL_ID, message_id=task["message_id"])
            except Exception:
                pass
        data["tasks"].remove(task)
        await set_data(data)
        try:
            await context.bot.send_message(chat_id=task["owner_id"], text="سفارش شما تکمیل شد💯💯💯")
        except Exception:
            pass
        await update.message.reply_text(f"✅ سفارش #{task_id} تکمیل شد.")
        return True

    elif admin_action == "broadcast":
        await update.message.reply_text("⏳ ارسال پیام همگانی در حال انجام است...")
        asyncio.create_task(run_broadcast(
            bot=context.bot,
            admin_chat_id=update.effective_chat.id,
            broadcast_text=text_input,
            reply_message=None
        ))
        return True

    elif admin_action == "give_coins":
        parts = text_input.strip().split()
        if len(parts) != 2:
            await update.message.reply_text("❌ فرمت صحیح: `<user_id> <amount>`", parse_mode="Markdown")
            return True
        target, amount_str = parts
        try:
            amount = int(amount_str)
        except ValueError:
            await update.message.reply_text("❌ مقدار باید عدد باشد.")
            return True
        data = await get_data()
        if target.startswith("@"):
            username = target[1:].lower()
            uid = data.get("usernames", {}).get(username)
            if not uid:
                await update.message.reply_text("❌ کاربر با این یوزرنیم پیدا نشد.")
                return True
        else:
            uid = str(target)
        if uid not in data["users"]:
            data["users"][uid] = 0
        data["users"][uid] += amount
        await set_data(data)
        await update.message.reply_text(f"✅ {amount} الماس به کاربر {target} داده شد.")
        return True

    return False

# ---------- پیام همگانی ----------
async def run_broadcast(bot, admin_chat_id, broadcast_text, reply_message):
    data = await get_data()
    user_ids = list(data["users"].keys())
    success = 0
    failed = 0
    for uid in user_ids:
        try:
            target_id = int(uid)
        except ValueError:
            continue
        try:
            if reply_message:
                await bot.copy_message(
                    chat_id=target_id,
                    from_chat_id=reply_message.chat_id,
                    message_id=reply_message.message_id
                )
            else:
                await bot.send_message(chat_id=target_id, text=broadcast_text)
            success += 1
        except Exception:
            failed += 1
        await asyncio.sleep(0.05)
    try:
        await bot.send_message(
            chat_id=admin_chat_id,
            text=f"✅ ارسال پیام همگانی تمام شد.\n\n📤 موفق: {success}\n❌ ناموفق: {failed}"
        )
    except Exception:
        pass

async def broadcast_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type != "private":
        return
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("شما اجازه استفاده از این دستور را ندارید.")
        return
    broadcast_text = None
    if context.args:
        broadcast_text = " ".join(context.args)
    reply_message = update.message.reply_to_message
    if not broadcast_text and not reply_message:
        await update.message.reply_text(
            "❌ برای ارسال پیام همگانی:\n"
            "1️⃣ /broadcast متن پیام\n"
            "2️⃣ روی یک پیام ریپلای کنید و /broadcast بزنید\n\n"
            "یا از پنل ادمین /admin استفاده کنید."
        )
        return
    await update.message.reply_text("⏳ ارسال پیام همگانی در حال انجام است...")
    asyncio.create_task(run_broadcast(
        bot=context.bot,
        admin_chat_id=update.effective_chat.id,
        broadcast_text=broadcast_text,
        reply_message=reply_message
    ))

# ---------- منوی اصلی ----------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type != "private":
        return
    user_id = str(update.effective_user.id)
    if await is_user_blocked(user_id):
        await update.message.reply_text("🚫 حساب شما توسط ادمین مسدود شده است.")
        return
    data = await get_data()
    is_new = user_id not in data["users"]
    if is_new:
        data["users"][user_id] = 10
    else:
        data["users"].setdefault(user_id, 0)
    if update.effective_user.username:
        data["usernames"][update.effective_user.username.lower()] = user_id
    if context.args and len(context.args) > 0:
        arg = context.args[0]
        if arg.startswith("ref_") and is_new:
            ref = arg[4:]
            if ref.isdigit():
                referrer_id = int(ref)
                if referrer_id != int(user_id):
                    data["users"][str(referrer_id)] = data["users"].get(str(referrer_id), 0) + 15
    await set_data(data)

    keyboard = ReplyKeyboardMarkup(
        [
            [KeyboardButton("💎 دریافت الماس رایگان 💎")],
            [
                KeyboardButton("👥 سفارش ممبر"),
                KeyboardButton("🛍️ خرید الماس"),
                KeyboardButton("👤 حساب کاربری")
            ],
            [
                KeyboardButton("👥️ زیرمجموعه گیری"),
                KeyboardButton("📚 راهنما")
            ],
            [
                KeyboardButton("🔍 پیگیری سفارشات")
            ]
        ],
        resize_keyboard=True,
        one_time_keyboard=False
    )

    welcome_text = (
        "سلام🌹\n"
        "به ربات ممبرگیر رایگان ویوپلاس خوش اومدی❤️\n"
        "🤖با این ربات بدون هیچ هزینه ای ممبر بگیر\n\n"
        "⚠️•حتماً قبل از استفاده از ربات قوانین ربات رو مطالعه بفرمایید.\n\n"
        "📚•برای آشنایی با ربات و روش کار با آن دستور /Help را ارسال کنید!\n\n"
        "برای ادامه یک گزینه را انتخاب کنید!👇"
    )
    await update.message.reply_text(welcome_text, reply_markup=keyboard)

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type != "private":
        return
    if not await check_subscription(update, context):
        await send_subscription_message(update, context)
        return
    await help_from_menu(update, context)

async def shop_from_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type != "private":
        return
    if not await check_subscription(update, context):
        await send_subscription_message(update, context)
        return
    text = (
        "🛍 به فروشگاه ربات ویو پلاس خوش آمدید💎\n"
        "لطفا گزینه ی مورد نظر را جهت خرید انتخاب کنید 👇"
    )
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("الماس 💎", callback_data="shop_coins")],
        [InlineKeyboardButton("اسپانسر", callback_data="shop_sponsor")]
    ])
    await update.message.reply_text(text, reply_markup=keyboard)

async def shop_coins(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    text = (
        "خرید الماس 💎\n\n"
        "100 الماس => 15 هزار تومن\n"
        "250 الماس => 30 هزار تومن\n"
        "500 الماس => 45 هزار تومن\n"
        "1000 الماس => 65 هزار تومن\n"
        "4000 الماس => 260 هزار تومن\n\n"
        "جهت خرید الماس و کارت به کارت یا مشاوره و سوال به ایدی زیر پیام دهید\n"
        f"🆔️{ADMIN_USERNAME}"
    )
    await query.edit_message_text(text)

async def shop_sponsor(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    text = (
        "فروش جوین ربات فعال شد🎉\n\n"
        "👥️ | تعرفه جوین اجباری 💫\n\n"
        "📣 ربات ویو پلاس\n"
        "🔤:: @Seen_member_jet_bot\n\n"
        " 24 ساعت  | 79,000  تومان  💰\n"
        " 48 ساعت  | 129,000 تومان 💰\n"
        " 72 ساعت  | 179,000 تومان 💰\n\n"
        "جهت ارتباط با ما⬇️\n"
        f"🔤:: {ADMIN_USERNAME}"
    )
    await query.edit_message_text(text)

async def free_coins_from_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type != "private":
        return
    if not await check_subscription(update, context):
        await send_subscription_message(update, context)
        return
    text = (
        "به بخش دریافت الماس رایگان خوش آمدید💫\n\n"
        "📌 در این بخش می‌تونید با استفاده از یک روش زیر برای خودتون الماس 💎جمع آوری کنید سپس با الماس های جمع آوری شده برای کانال/گروه خود ممبر سفارش بدید.\n\n"
        "👈 یک روش برای جمع آوری الماس وجود دارد:\n\n"
        "1️⃣ عضویت در سفارش های موجود: \n"
        "در این روش شما می‌توانید با عضویت در سفارشات موجود و سپس زدن دکمه ی دریافت اقدام به جمع آوری الماس نمایید.\n\n"
        "‼️اگر کمتر از 4روز از کانال ها لفت بدید 3 الماس از شما کسر میشود \n\n"
        "🫂 همچنین از طریق زیر مجموعه گیری هم می‌تونید تا بی‌نهایت الماس رایگان کسب کنید."
    )
    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("📢 عضویت در کانال", url=f"https://t.me/{CHANNEL_USERNAME}"),
            InlineKeyboardButton("💎 دریافت الماس روزانه 💎", callback_data="daily_coins")
        ]
    ])
    await update.message.reply_text(text, reply_markup=keyboard)

async def daily_coins_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = str(query.from_user.id)
    data = await get_data()
    now = datetime.now(timezone.utc)
    last_claim_str = data["daily_claims"].get(user_id)
    if last_claim_str:
        try:
            last_claim = datetime.fromisoformat(last_claim_str)
            elapsed = now - last_claim
            cooldown = timedelta(hours=DAILY_COINS_COOLDOWN_HOURS)
            if elapsed < cooldown:
                remaining = cooldown - elapsed
                hours = remaining.seconds // 3600
                minutes = (remaining.seconds % 3600) // 60
                await query.answer(
                    f"⏳ شما الماس روزانه خود را دریافت کرده‌اید.\n"
                    f"زمان باقی‌مانده: {hours} ساعت و {minutes} دقیقه",
                    show_alert=True
                )
                return
        except Exception:
            pass
    data["users"][user_id] = data["users"].get(user_id, 0) + DAILY_COINS_AMOUNT
    data["daily_claims"][user_id] = now.isoformat()
    await set_data(data)
    current_balance = data["users"][user_id]
    await query.answer(
        f"💎 {DAILY_COINS_AMOUNT} الماس دریافت کردید | موجودی: {current_balance} الماس",
        show_alert=True
    )

async def help_from_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type != "private":
        return
    if not await check_subscription(update, context):
        await send_subscription_message(update, context)
        return
    help_text = (
        "«🤔راهنمای ممبرگیر | ویوپلاس»\n\n"
        "(✅لطفاً تمام متن را با دقت بخوانید✅)\n\n"
        "ممبرگیر | ویوپلاس یک ربات برای افزایش رایگان اعضای کانال و گروه شماست!\n\n"
        "⚠️ قبل از سفارش دادن ممبر در ربات باید ربات ما یعنی ممبرگیر | ویوپلاس را ادمین کانال یا گروه خود کنید. \n"
        "⚠️ بعد از ادمین کردن ربات برای سفارش دادن ممبر برای کانال و گروه خود باید در ربات الماس داشته باشید.\n"
        "💎•برای دریافت الماس در ربات چند روش وجود دارد!👇\n\n"
        "💎\\روش اول: \n"
        "عضویت در سفارشات:\n"
        "شما میتوانید با عضویت در کانال ها و گروه هایی که در کانال سفارشات ممبرگیر | ویوپلاس وجود دارد الماس دریافت کنید.\n\n"
        "👥\\روش دوم: \n"
        "زیر مجموعه گیری :\n"
        "برای این کار وارد بخش زیر مجموعه گیری میشید و لینک خود را برای دیگران میفرستید !\n\n"
        "🛍️\\روش سوم: می توانید از ما الماس خریداری کنید!\n\n\n"
        "«🔖سوال های متداول 🔖»\n\n"
        "⁉️چطوری ربات رو ادمین کنم؟\n\n"
        "⛔️|روش ادمین کردن ربات به این صورت است که وارد کانال یا گروه تون شوید و به قسمت ادمین ها بروید و اضافه کردن ادمین را انتخاب کنید سپس روی سرچ بزنید و ایدی ربات( @Seen_member_jet_bot ) را سرچ کنید و ربات مارا ادمین کنید!\n"
        "●\n"
        "⁉️ممبر هایی که از طریق ربات ممبرگیر | ویوپلاس به کانال و گروه اضافه میشن واقعی هستن؟\n\n"
        "بله.کاملا واقعی و ایرانی که به دلیل واقعی بودن بازدید هم دارن.\n\n"
        "°\n"
        "‼️توجه :\n"
        "•در صورت باز نشدن دکمه های ربات لطفاً با ارسال دستور /start ربات را استارت کنید!\n"
        "ربات ثبت سفارشات\n"
        "@Seen_member_jet_bot\n"
        "چنل سفارشات\n"
        "@viewpluse"
    )
    await update.message.reply_text(help_text)

async def track_order_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type != "private":
        return
    if not await check_subscription(update, context):
        await send_subscription_message(update, context)
        return
    user_id = str(update.effective_user.id)
    data = await get_data()
    user_tasks = [t for t in data["tasks"] if t["owner_id"] == int(user_id)]
    if not user_tasks:
        await update.message.reply_text("شما سفارش جاری ندارید.")
        return
    text = "سفارشات اخیر شما:\n\n"
    for t in user_tasks:
        text += format_task_message(t) + "\n"
    await update.message.reply_text(text)

async def ord_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type != "private":
        return
    text_cmd = update.message.text.strip()
    try:
        task_id = int(text_cmd.replace("/ord_", "").strip())
    except Exception:
        await update.message.reply_text("فرمت: /ord_<id>")
        return
    user_id = str(update.effective_user.id)
    data = await get_data()
    task = next((t for t in data["tasks"] if t["id"] == task_id), None)
    if not task:
        await update.message.reply_text("❌ این سفارش دیگر موجود نیست.")
        return
    if str(task["owner_id"]) != user_id and update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("❌ این سفارش متعلق به شما نیست.")
        return

    keyboard = None
    if "message_id" in task:
        channel_username = ORDER_CHANNEL_ID.lstrip("@")
        message_link = f"https://t.me/{channel_username}/{task['message_id']}"
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("📇 مشاهده ی سفارش در کانال", url=message_link)]
        ])

    await update.message.reply_text(
        f"📦 جزئیات سفارش #{task['id']}\n\n"
        f"🌐 کانال: {task['target_id']}\n"
        f"🔗 لینک: {task['target_link']}\n"
        f"⏳ درخواستی: {task['count']}\n"
        f"👥 دریافتی: {task['claimed']}\n"
        f"💔 لفت‌ها: {task.get('left_count', 0)}\n"
        f"💎 هزینه: {task['cost']} الماس",
        reply_markup=keyboard
    )

async def cancel_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type != "private":
        return
    text_cmd = update.message.text.strip()
    try:
        task_id = int(text_cmd.replace("/cancel_", "").strip())
    except Exception:
        await update.message.reply_text("فرمت: /cancel_<id>")
        return
    user_id = str(update.effective_user.id)
    data = await get_data()
    task = next((t for t in data["tasks"] if t["id"] == task_id), None)
    if not task:
        await update.message.reply_text("❌ این سفارش دیگر موجود نیست.")
        return
    if str(task["owner_id"]) != user_id and update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("❌ این سفارش متعلق به شما نیست.")
        return
    remaining = task["count"] - task["claimed"]
    refund = remaining * REFUND_RATE
    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("✅️ بله", callback_data=f"confirm_cancel_{task_id}"),
            InlineKeyboardButton("❌️ خیر", callback_data=f"decline_cancel_{task_id}")
        ]
    ])
    await update.message.reply_text(
        "⁉️آیا مایل به لغو این تبلیغ هستید؟\n\n"
        f"⚠️توجه داشته باشید با ضریب {REFUND_RATE} معادل ممبر های باقی مانده الماس به حساب شما بازگشت داده خواهد شد.\n"
        f"💎 مبلغ بازگشتی: {refund} الماس",
        reply_markup=keyboard
    )

async def confirm_cancel_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    task_id = int(query.data.split("_")[-1])
    user_id = str(query.from_user.id)
    data = await get_data()
    task = next((t for t in data["tasks"] if t["id"] == task_id), None)
    if not task:
        await query.edit_message_text("❌ این سفارش دیگر موجود نیست.")
        return
    if str(task["owner_id"]) != user_id and query.from_user.id != ADMIN_ID:
        await query.edit_message_text("❌ این سفارش متعلق به شما نیست.")
        return
    remaining = task["count"] - task["claimed"]
    refund = remaining * REFUND_RATE
    data["users"][str(task["owner_id"])] = data["users"].get(str(task["owner_id"]), 0) + refund
    data["tasks"].remove(task)
    await set_data(data)
    if "message_id" in task:
        try:
            await context.bot.delete_message(chat_id=ORDER_CHANNEL_ID, message_id=task["message_id"])
        except Exception:
            pass
    await query.edit_message_text(
        f"✅ سفارش #{task_id} لغو شد.\n"
        f"💎 {refund} الماس به حساب شما بازگشت داده شد."
    )

async def decline_cancel_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.edit_message_text("❌ لغو سفارش انجام نشد.")

PACKAGES = {
    "member_5": {"count": 5, "cost": 10, "reward": 2},
    "member_10": {"count": 10, "cost": 20, "reward": 2},
    "member_20": {"count": 20, "cost": 40, "reward": 2},
    "member_50": {"count": 50, "cost": 80, "reward": 2},
    "member_80": {"count": 80, "cost": 100, "reward": 2},
    "member_100": {"count": 100, "cost": 150, "reward": 2},
    "member_500": {"count": 500, "cost": 700, "reward": 2},
}

async def order_member_from_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type != "private":
        return
    if not await check_subscription(update, context):
        await send_subscription_message(update, context)
        return
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("👥️ 5 ممبر | 10 💎", callback_data="member_5")],
        [InlineKeyboardButton("👥️ 10 ممبر | 20 💎", callback_data="member_10")],
        [InlineKeyboardButton("👥️ 20 ممبر | 40 💎", callback_data="member_20")],
        [InlineKeyboardButton("👥️ 50 ممبر | 80 💎", callback_data="member_50")],
        [InlineKeyboardButton("👥️ 80 ممبر | 100 💎", callback_data="member_80")],
        [InlineKeyboardButton("👥️ 100 ممبر | 150 💎", callback_data="member_100")],
        [InlineKeyboardButton("👥️ 500 ممبر | 700 💎", callback_data="member_500")],
    ])
    await update.message.reply_text(
        "پکیج مورد نظر را انتخاب کنید:\n"
        "مطمئن شوید ربات را ادمین کانال یا گروهتون کردید ‼️",
        reply_markup=keyboard
    )

async def package_selected(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if not await check_subscription(update, context):
        await send_subscription_message(update, context)
        return
    package_key = query.data
    user_id = str(query.from_user.id)
    data = await get_data()
    cost = PACKAGES[package_key]["cost"]
    if data["users"].get(user_id, 0) < cost:
        await query.answer("💎 موجودی شما کافی نمی باشد 🚫", show_alert=False)
        return
    data["states"][user_id] = {"awaiting_order": package_key}
    await set_data(data)
    text = (
        "✅ جهت دریافت ممبر باید ابتدا ربات را ادمین کانال مورد نظر کنید سپس آیدی کانال را ارسال نمایید\n\n"
        "👈 نمونه : @viewpluse یا https://t.me/viewpluse\n"
        "⚠️ لطفاً فقط یکی از این دو فرمت را ارسال کنید.\n"
        "‼️ ربات باید تا پایان سفارش ادمین کانال شما بماند."
    )
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("انصراف", callback_data="cancel_order")]
    ])
    await query.edit_message_text(text, reply_markup=keyboard)

async def cancel_order(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = str(query.from_user.id)
    data = await get_data()
    data["states"].pop(user_id, None)
    await set_data(data)
    try:
        await query.delete_message()
    except:
        pass

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type != "private":
        return
    user_id = str(update.effective_user.id)

    if update.effective_user.id == ADMIN_ID:
        data = await get_data()
        admin_state = data["states"].get(str(ADMIN_ID), {})
        admin_action = admin_state.get("admin_action")
        if admin_action:
            handled = await process_admin_input(update, context, admin_action, update.message.text)
            if handled:
                data = await get_data()
                data["states"].pop(str(ADMIN_ID), None)
                await set_data(data)
                return

    if await is_user_blocked(user_id):
        return

    data = await get_data()
    state = data["states"].get(user_id, {})
    if "awaiting_order" in state:
        package_key = state.pop("awaiting_order")
        raw_input = update.message.text.strip()
        if raw_input.startswith("https://t.me/"):
            raw_input = raw_input.split("/")[-1]
            if raw_input.startswith("+"):
                await update.message.reply_text("❌ لینک دعوت خصوصی قابل قبول نیست.")
                return
            target = "@" + raw_input
            invite_link = f"https://t.me/{raw_input}"
        elif raw_input.startswith("@"):
            target = raw_input
            invite_link = f"https://t.me/{raw_input[1:]}"
        else:
            await update.message.reply_text("❌ فرمت آیدی کانال صحیح نیست. لطفاً به صورت @username یا https://t.me/username ارسال کنید.")
            return
        if await is_channel_blocked(target):
            await update.message.reply_text("🚫 این کانال توسط ادمین مسدود شده است و امکان ثبت سفارش برای آن وجود ندارد.")
            return
        target_channel_id = target
        cost = PACKAGES[package_key]["cost"]
        bot_id = (await context.bot.get_me()).id
        try:
            bot_member = await context.bot.get_chat_member(chat_id=target_channel_id, user_id=bot_id)
            if bot_member.status not in ["administrator", "creator"]:
                await update.message.reply_text("🚫کاربر گرامی جهت ثبت سفارش ابتدا ربات را ادمین کانال یا کروه خود کنید و دوباره سفارش خود را ثبت کنید")
                return
        except Exception:
            await update.message.reply_text("🚫جهت ثبت سفارش، ربات باید در کانال/گروه ادمین باشد.")
            return
        if data["users"].get(user_id, 0) < cost:
            await update.message.reply_text("موجودی کافی نیست.")
            return
        data["users"][user_id] -= cost
        now_iso = datetime.now(timezone.utc).isoformat()
        task = {
            "id": data["next_task_id"],
            "type": "member",
            "owner_id": int(user_id),
            "target_id": target_channel_id,
            "target_link": invite_link,
            "count": PACKAGES[package_key]["count"],
            "cost": cost,
            "reward": PACKAGES[package_key]["reward"],
            "claimed": 0,
            "left_count": 0,
            "created_at": now_iso
        }
        data["tasks"].append(task)
        data["next_task_id"] += 1
        await set_data(data)
        channel_title = target_channel_id
        channel_description = ""
        channel_id = target_channel_id
        try:
            chat_info = await context.bot.get_chat(chat_id=target_channel_id)
            channel_title = chat_info.title or chat_info.username or target_channel_id
            channel_description = getattr(chat_info, 'description', '') or ""
            channel_id = target_channel_id
        except:
            pass
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("🪩 سفارش جدید عضویت 🪩", callback_data="noop")],
            [
                InlineKeyboardButton("✅️ عضویت", url=invite_link),
                InlineKeyboardButton("💎 دریافت الماس", callback_data=f"claim_member_{task['id']}")
            ],
            [InlineKeyboardButton("♻️ ورود به ربات", url="https://t.me/Seen_member_jet_bot")],
            [InlineKeyboardButton("🚫 تخلف", callback_data=f"report_task_{task['id']}")]
        ])
        try:
            sent_message = await context.bot.send_message(
                chat_id=ORDER_CHANNEL_ID,
                text=(
                    f"‼️نام کانال : {channel_title}\n\n"
                    f"📝توضیحات کانال: {channel_description}\n\n"
                    f"🆔 {channel_id}"
                ),
                reply_markup=keyboard
            )
            task["message_id"] = sent_message.message_id
            await set_data(data)
        except Exception as e:
            await update.message.reply_text(f"خطا در ارسال سفارش به کانال: {e}")
        confirmation_keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("مشاهده ی سفارش", url=ORDER_CHANNEL_URL)]
        ])
        await update.message.reply_text(
            f"✅ سفارش شما ثبت شد.\n"
            f"تعداد: {task['count']} ممبر\n"
            f"هزینه: {cost} الماس 💎\n"
            f"پس از تکمیل اعضا، سفارش از کانال حذف خواهد شد.",
            reply_markup=confirmation_keyboard
        )
        return
    if update.message.text == "💎 دریافت الماس رایگان 💎":
        await free_coins_from_menu(update, context)
        return
    if update.message.text == "👥 سفارش ممبر":
        await order_member_from_menu(update, context)
        return
    if update.message.text == "🛍️ خرید الماس":
        await shop_from_menu(update, context)
        return
    if update.message.text == "👤 حساب کاربری":
        if not await check_subscription(update, context):
            await send_subscription_message(update, context)
            return
        bal = data["users"].get(user_id, 0)
        await update.message.reply_text(f"💎 موجودی شما: {bal} الماس")
        return
    if update.message.text == "🔍 پیگیری سفارشات":
        await track_order_menu(update, context)
        return
    if update.message.text == "👥️ زیرمجموعه گیری":
        if not await check_subscription(update, context):
            await send_subscription_message(update, context)
            return
        await referral_menu(update, context)
        return
    if update.message.text == "📚 راهنما":
        await help_from_menu(update, context)
        return

async def report_task(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    task_id = int(query.data.split("_")[-1])
    data = await get_data()
    task = next((t for t in data["tasks"] if t["id"] == task_id), None)
    if not task:
        await query.answer("سفارش یافت نشد.", show_alert=False)
        return
    report_text = (
        "🚨 گزارش تخلف سفارش\n\n"
        f"📦 کد سفارش: {task['id']}\n"
        f"👤 آیدی صاحب سفارش: `{task['owner_id']}`\n"
        f"📌 آیدی کانال: {task['target_id']}\n"
        f"🔗 لینک کانال: {task['target_link']}\n"
        f"👥 تعداد درخواستی: {task['count']}\n"
        f"✅ تعداد دریافتی: {task['claimed']}"
    )
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("🚫 مسدود کردن کاربر", callback_data=f"block_user_{task['owner_id']}")]
    ])
    try:
        await context.bot.send_message(chat_id=ADMIN_ID, text=report_text, reply_markup=keyboard, parse_mode="Markdown")
        await query.answer("گزارش تخلف شما ثبت شد.", show_alert=False)
    except Exception:
        await query.answer("خطا در ارسال گزارش به ادمین.", show_alert=False)

async def block_user_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if query.from_user.id != ADMIN_ID:
        return
    uid = query.data.split("_")[-1]
    users = await get_blocked_users()
    if uid in [str(u) for u in users]:
        await query.edit_message_text(f"⚠️ کاربر {uid} قبلاً مسدود شده بود.")
        return
    users.append(uid)
    await set_blocked_users(users)
    await query.edit_message_text(f"✅ کاربر {uid} مسدود شد.")

async def claim_member(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id
    task_id = int(query.data.split("_")[-1])
    if await is_user_blocked(user_id):
        await query.answer("حساب شما مسدود است.", show_alert=False)
        return
    data = await get_data()
    task = next((t for t in data["tasks"] if t["id"] == task_id), None)
    if not task:
        try:
            await query.message.delete()
        except:
            pass
        await query.answer("این سفارش دیگر موجود نیست.", show_alert=False)
        return
    bot_id = (await context.bot.get_me()).id
    try:
        bot_member = await context.bot.get_chat_member(chat_id=task["target_id"], user_id=bot_id)
        bot_is_admin = bot_member.status in ["administrator", "creator"]
    except Exception:
        bot_is_admin = False
    if not bot_is_admin:
        data["tasks"].remove(task)
        await set_data(data)
        if "message_id" in task:
            try:
                await context.bot.delete_message(chat_id=ORDER_CHANNEL_ID, message_id=task["message_id"])
            except:
                pass
        try:
            await context.bot.send_message(chat_id=task["owner_id"], text="سفارش شما به دلیل ادمین نبودن ربات حذف شد")
        except:
            pass
        await query.answer("ربات در کانال ادمین نیست، سفارش حذف شد.", show_alert=False)
        return
    if str(user_id) in data["completed"].get(str(task_id), {}):
        await query.answer("شما قبلاً الماس را دریافت کرده‌اید", show_alert=False)
        return
    if not await check_subscription(update, context):
        await query.answer("ابتدا در کانال‌های اسپانسر عضو شوید.", show_alert=False)
        return
    now = datetime.now(timezone.utc)
    for record in data["join_records"]:
        if record["user_id"] == str(user_id) and record["target_id"] == task["target_id"]:
            joined_at = datetime.fromisoformat(record["joined_at"])
            if (now - joined_at) < timedelta(days=4):
                await query.answer("شما قبلاً از این کانال الماس گرفته‌اید. تا ۴ روز دیگر نمی‌توانید دوباره دریافت کنید.", show_alert=False)
                return
    try:
        member = await context.bot.get_chat_member(chat_id=task["target_id"], user_id=user_id)
        if member.status not in ["member", "administrator", "creator"]:
            await query.answer("شما عضو کانال نیستید!", show_alert=False)
            return
    except Exception:
        await query.answer("خطا در بررسی عضویت.", show_alert=False)
        return
    data["users"][str(user_id)] = data["users"].get(str(user_id), 0) + task["reward"]
    data["completed"].setdefault(str(task_id), {})[str(user_id)] = now.isoformat()
    task["claimed"] += 1
    data["join_records"].append({
        "user_id": str(user_id),
        "task_id": task_id,
        "target_id": task["target_id"],
        "owner_id": task["owner_id"],
        "joined_at": now.isoformat()
    })
    if task["claimed"] >= task["count"]:
        data["tasks"].remove(task)
        await set_data(data)
        if "message_id" in task:
            try:
                await context.bot.delete_message(chat_id=ORDER_CHANNEL_ID, message_id=task["message_id"])
            except:
                pass
        try:
            await context.bot.send_message(chat_id=task["owner_id"], text="سفارش شما تکمیل شد💯💯💯")
        except:
            pass
    else:
        await set_data(data)
    current_balance = data["users"][str(user_id)]
    await query.answer(
        f"💎 {task['reward']} الماس کسب کردید | موجودی: {current_balance} الماس",
        show_alert=False
    )

async def check_early_leaves():
    data = await get_data()
    now = datetime.now(timezone.utc)
    penalized = False
    remaining_records = []
    for record in data["join_records"]:
        joined_at = datetime.fromisoformat(record["joined_at"])
        age = now - joined_at
        if age >= timedelta(days=4):
            continue
        try:
            member = await app_bot.bot.get_chat_member(chat_id=record["target_id"], user_id=int(record["user_id"]))
            if member.status not in ["member", "administrator", "creator"]:
                user_id = record["user_id"]
                owner_id = str(record["owner_id"])
                data["users"][user_id] = max(0, data["users"].get(user_id, 0) - 3)
                data["users"][owner_id] = data["users"].get(owner_id, 0) + 2
                for t in data["tasks"]:
                    if t["id"] == record["task_id"]:
                        t["left_count"] = t.get("left_count", 0) + 1
                        break
                try:
                    await app_bot.bot.send_message(chat_id=int(user_id), text="به دلیل ترک کانال کمتر از 4روز 3 الماس از شما کسر شد")
                except:
                    pass
                penalized = True
            else:
                remaining_records.append(record)
        except:
            remaining_records.append(record)
    data["join_records"] = remaining_records
    if penalized:
        await set_data(data)
    return penalized

async def referral_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type != "private":
        return
    if not await check_subscription(update, context):
        await send_subscription_message(update, context)
        return
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("دریافت بنر زیر مجموعه گیری", callback_data="referral_banner")]
    ])
    await update.message.reply_text(
        "🫂 جهت دریافت لینک زیر مجموعه گیری خود روی دکمه زیر کلیک کنید👇",
        reply_markup=keyboard
    )

async def referral_banner(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = str(query.from_user.id)
    bot_username = (await context.bot.get_me()).username
    referral_link = f"https://t.me/{bot_username}?start=ref_{user_id}"
    text = (
        "🚀 با ممبرگیر |ویوپلاس به راحتی اعضای کانال و گروه خود را بصورت (رایگان؛پولی) افزایش دهید!\n"
        "👥 افزایش اعضای کانال و گروه شما\n"
        "🇮🇷 دریافت ممبر ایرانی کاملا واقعی و فعال\n"
        "🎁 دریافت هدیه 10 الماس برای اولین ورود شما\n"
        "سریع و بدون آفلاینی\n"
        "💯اگه اعضای کانال و گروهت کمه امتحان کن👇\n"
        f"{referral_link}"
    )
    await query.edit_message_text(text)

async def account_from_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type != "private":
        return
    if not await check_subscription(update, context):
        await send_subscription_message(update, context)
        return
    user_id = str(update.effective_user.id)
    data = await get_data()
    bal = data["users"].get(user_id, 0)
    await update.message.reply_text(f"💎 موجودی شما: {bal} الماس")

async def balance(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type != "private":
        return
    if not await check_subscription(update, context):
        await send_subscription_message(update, context)
        return
    user_id = str(update.effective_user.id)
    data = await get_data()
    bal = data["users"].get(user_id, 0)
    await update.message.reply_text(f"💎 موجودی شما: {bal} الماس")

async def noop(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

# ---------- راه‌اندازی ----------
app_bot = Application.builder().token(TOKEN).build()
app_bot.add_handler(CommandHandler("start", start))
app_bot.add_handler(CommandHandler("help", help_command))
app_bot.add_handler(CommandHandler("admin", admin_panel))
app_bot.add_handler(CommandHandler("balance", balance))
app_bot.add_handler(CommandHandler("broadcast", broadcast_command))
app_bot.add_handler(MessageHandler(filters.Regex(r"^/ord_\d+$") & filters.ChatType.PRIVATE, ord_command))
app_bot.add_handler(MessageHandler(filters.Regex(r"^/cancel_\d+$") & filters.ChatType.PRIVATE, cancel_command))
app_bot.add_handler(CallbackQueryHandler(admin_panel_callback, pattern="^admin_"))
app_bot.add_handler(CallbackQueryHandler(package_selected, pattern="^member_"))
app_bot.add_handler(CallbackQueryHandler(cancel_order, pattern="^cancel_order$"))
app_bot.add_handler(CallbackQueryHandler(referral_banner, pattern="^referral_banner$"))
app_bot.add_handler(CallbackQueryHandler(claim_member, pattern="^claim_member_"))
app_bot.add_handler(CallbackQueryHandler(shop_coins, pattern="^shop_coins$"))
app_bot.add_handler(CallbackQueryHandler(shop_sponsor, pattern="^shop_sponsor$"))
app_bot.add_handler(CallbackQueryHandler(noop, pattern="^noop$"))
app_bot.add_handler(CallbackQueryHandler(report_task, pattern="^report_task_"))
app_bot.add_handler(CallbackQueryHandler(block_user_callback, pattern="^block_user_"))
app_bot.add_handler(CallbackQueryHandler(confirm_cancel_callback, pattern="^confirm_cancel_"))
app_bot.add_handler(CallbackQueryHandler(decline_cancel_callback, pattern="^decline_cancel_"))
app_bot.add_handler(CallbackQueryHandler(daily_coins_callback, pattern="^daily_coins$"))
app_bot.add_handler(MessageHandler(filters.Text(["💎 دریافت الماس رایگان 💎"]), free_coins_from_menu))
app_bot.add_handler(MessageHandler(filters.Text(["👥 سفارش ممبر"]), order_member_from_menu))
app_bot.add_handler(MessageHandler(filters.Text(["🛍️ خرید الماس"]), shop_from_menu))
app_bot.add_handler(MessageHandler(filters.Text(["👤 حساب کاربری"]), account_from_menu))
app_bot.add_handler(MessageHandler(filters.Text(["🔍 پیگیری سفارشات"]), track_order_menu))
app_bot.add_handler(MessageHandler(filters.Text(["👥️ زیرمجموعه گیری"]), referral_menu))
app_bot.add_handler(MessageHandler(filters.Text(["📚 راهنما"]), help_from_menu))
app_bot.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))

app = FastAPI()

@app.get("/")
async def home():
    return {"status": "running"}

@app.post("/")
async def webhook(request: Request):
    global _initialized
    if not _initialized:
        await app_bot.initialize()
        _initialized = True
    json_data = await request.json()
    update = Update.de_json(json_data, app_bot.bot)
    await app_bot.process_update(update)
    return {"ok": True}

@app.get("/check")
async def check_endpoint():
    global _initialized
    if not _initialized:
        await app_bot.initialize()
        _initialized = True
    penalized = await check_early_leaves()
    return {"ok": True, "penalized": penalized}
