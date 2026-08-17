import os
import json
from datetime import datetime, timezone
from fastapi import FastAPI, Request
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ContextTypes
from upstash_redis.asyncio import Redis
from telegram import ReplyKeyboardMarkup, KeyboardButton

TOKEN = os.environ.get("BOT_TOKEN")

redis = Redis(
    url=os.environ.get("UPSTASH_REDIS_REST_URL"),
    token=os.environ.get("UPSTASH_REDIS_REST_TOKEN")
)

DATA_KEY = "bot_data"

_initialized = False

# ----- تنظیمات ثابت (در صورت نیاز تغییر بده) -----
ORDER_CHANNEL_ID = "@viewpluse"        # آیدی عددی یا نام کاربری کانال سفارش‌ها
CHANNEL_USERNAME = "viewpluse"        # نام کاربری کانال برای ساخت لینک دعوت (بدون @)
# اگر کانال خصوصی است، به جای لینک از متد export_chat_invite_link استفاده می‌شود.
# ---------------------------------------------------

async def get_data():
    raw = await redis.get(DATA_KEY)
    if raw:
        return json.loads(raw)
    else:
        return {
            "users": {"7724653657": 10000},   # موجودی اولیه
            "tasks": [],                      # سفارش‌های فعال
            "completed": {},                  # کاربرانی که سفارش را انجام داده‌اند
            "next_task_id": 1,
            "states": {},                     # حالت‌های کاربر (مثلاً در انتظار ارسال آیدی)
            "daily_claims": {}                # زمان آخرین دریافت سکه روزانه
        }

async def set_data(data):
    await redis.set(DATA_KEY, json.dumps(data))

# ---------- منوی اصلی ----------

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    data = await get_data()
    data["users"].setdefault(user_id, 0)
    await set_data(data)

    # ساخت کیبورد پایین
    keyboard = ReplyKeyboardMarkup(
        [
            [KeyboardButton("💰 دریافت سکه رایگان")],
            [KeyboardButton("👥 سفارش ممبر")]
        ],
        resize_keyboard=True,
        one_time_keyboard=False
    )

    await update.message.reply_text(
        "به ربات خوش آمدید! یکی از گزینه‌ها را انتخاب کنید:",
        reply_markup=keyboard
    )
# ---------- دریافت سکه رایگان ----------

async def free_coins_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("🎁 دریافت سکه روزانه", callback_data="daily_coins")],
        [InlineKeyboardButton("📢 عضویت در کانال", url=f"https://t.me/{CHANNEL_USERNAME}")]
    ])
    await query.edit_message_text("یکی را انتخاب کن:", reply_markup=keyboard)

async def daily_coins(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = str(query.from_user.id)
    data = await get_data()

    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    last_claim = data["daily_claims"].get(user_id)

    if last_claim == today:
        await query.answer("شما امروز سکه روزانه را دریافت کرده‌اید!", show_alert=True)
        return

    # اعطای ۷ سکه
    data["users"][user_id] = data["users"].get(user_id, 0) + 7
    data["daily_claims"][user_id] = today
    await set_data(data)

    await query.edit_message_text("✅ ۷ سکه به موجودی شما اضافه شد!\nموجودی فعلی: " + str(data["users"][user_id]))

# ---------- سفارش ممبر ----------

PACKAGES = {
    "member_10": {"count": 10, "cost": 20, "reward": 2},
    "member_20": {"count": 20, "cost": 40, "reward": 2},
    "member_50": {"count": 50, "cost": 80, "reward": 2},
    "member_80": {"count": 80, "cost": 100, "reward": 2},
    "member_100": {"count": 100, "cost": 150, "reward": 2},
    "member_500": {"count": 500, "cost": 700, "reward": 2},
}

async def order_member_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("👥️ 10 ممبر | 20 🪙", callback_data="member_10")],
        [InlineKeyboardButton("👥️ 20 ممبر | 40 🪙", callback_data="member_20")],
        [InlineKeyboardButton("👥️ 50 ممبر | 80 🪙", callback_data="member_50")],
        [InlineKeyboardButton("👥️ 80 ممبر | 100 🪙", callback_data="member_80")],
        [InlineKeyboardButton("👥️ 100 ممبر | 150 🪙", callback_data="member_100")],
        [InlineKeyboardButton("👥️ 500 ممبر | 700 🪙", callback_data="member_500")],
    ])
    await query.edit_message_text("پکیج مورد نظر را انتخاب کنید:", reply_markup=keyboard)

async def package_selected(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    package_key = query.data  # مثلاً member_10
    user_id = str(query.from_user.id)

    data = await get_data()
    cost = PACKAGES[package_key]["cost"]
    if data["users"].get(user_id, 0) < cost:
        await query.answer("موجودی شما کافی نیست!", show_alert=True)
        return

    # ذخیره حالت: در انتظار دریافت آیدی کانال
    data["states"][user_id] = {"awaiting_order": package_key}
    await set_data(data)

    await query.edit_message_text(
        f"شما پکیج {PACKAGES[package_key]['count']} ممبر را انتخاب کردید.\n"
        f"هزینه: {cost} سکه\n"
        "لطفاً آیدی عددی کانال/گروه خود را ارسال کنید:"
    )

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    data = await get_data()
    state = data["states"].get(user_id, {})

    if "awaiting_order" in state:
        package_key = state.pop("awaiting_order")
        target_channel_id = update.message.text.strip()

        # بررسی هزینه و کسر سکه
        cost = PACKAGES[package_key]["cost"]
        if data["users"].get(user_id, 0) < cost:
            await update.message.reply_text("موجودی کافی نیست.")
            return

        data["users"][user_id] -= cost

        # دریافت لینک دعوت کانال (اگر ربات ادمین باشد)
        try:
            invite_link = await context.bot.export_chat_invite_link(chat_id=target_channel_id)
        except Exception as e:
            # اگر نتوانست لینک دعوت بگیرد، از لینک عمومی استفاده می‌کنیم
            invite_link = f"https://t.me/{CHANNEL_USERNAME}"
            await update.message.reply_text("⚠️ نتوانستم لینک دعوت کانال را دریافت کنم، از لینک عمومی استفاده می‌کنم.")

        # ساخت سفارش
        task = {
            "id": data["next_task_id"],
            "type": "member",
            "owner_id": int(user_id),
            "target_id": target_channel_id,
            "target_link": invite_link,
            "count": PACKAGES[package_key]["count"],
            "cost": cost,
            "reward": PACKAGES[package_key]["reward"],
            "claimed": 0
        }
        data["tasks"].append(task)
        data["next_task_id"] += 1
        await set_data(data)

        # ارسال سفارش به کانال
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("عضویت", url=invite_link)],
            [InlineKeyboardButton("دریافت سکه", callback_data=f"claim_member_{task['id']}")]
        ])
        try:
            await context.bot.send_message(
                chat_id=ORDER_CHANNEL_ID,
                text=(
                    f"📢 سفارش ممبر جدید!\n"
                    f"👥 تعداد: {task['count']} ممبر\n"
                    f"💰 پاداش هر عضو: {task['reward']} سکه\n"
                    f"➡️ برای دریافت سکه، ابتدا عضو کانال شوید و سپس دکمه «دریافت سکه» را بزنید."
                ),
                reply_markup=keyboard
            )
        except Exception as e:
            await update.message.reply_text(f"خطا در ارسال سفارش به کانال: {e}")

        await update.message.reply_text(
            f"✅ سفارش شما ثبت شد.\n"
            f"تعداد: {task['count']} ممبر\n"
            f"هزینه: {cost} سکه\n"
            f"پس از تکمیل اعضا، سفارش از کانال حذف خواهد شد."
        )

    else:
    # منوی پایین
    if update.message.text == "💰 دریافت سکه رایگان":
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("🎁 دریافت سکه روزانه", callback_data="daily_coins")],
            [InlineKeyboardButton("📢 عضویت در کانال", url=f"https://t.me/{CHANNEL_USERNAME}")]
        ])
        await update.message.reply_text("یکی را انتخاب کن:", reply_markup=keyboard)
        return

    if update.message.text == "👥 سفارش ممبر":
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("👥️ 10 ممبر | 20 🪙", callback_data="member_10")],
            [InlineKeyboardButton("👥️ 20 ممبر | 40 🪙", callback_data="member_20")],
            [InlineKeyboardButton("👥️ 50 ممبر | 80 🪙", callback_data="member_50")],
            [InlineKeyboardButton("👥️ 80 ممبر | 100 🪙", callback_data="member_80")],
            [InlineKeyboardButton("👥️ 100 ممبر | 150 🪙", callback_data="member_100")],
            [InlineKeyboardButton("👥️ 500 ممبر | 700 🪙", callback_data="member_500")],
        ])
        await update.message.reply_text("پکیج مورد نظر را انتخاب کنید:", reply_markup=keyboard)
        return

# ---------- دریافت سکه بعد از عضویت ----------

async def claim_member(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    task_id = int(query.data.split("_")[-1])

    data = await get_data()
    task = next((t for t in data["tasks"] if t["id"] == task_id), None)
    if not task:
        await query.answer("این سفارش دیگر موجود نیست.", show_alert=True)
        return

    if str(user_id) in data.get("completed", {}).get(str(task_id), []):
        await query.answer("شما قبلاً از این سفارش سکه گرفته‌اید!", show_alert=True)
        return

    # بررسی عضویت در کانال هدف
    try:
        member = await context.bot.get_chat_member(chat_id=task["target_id"], user_id=user_id)
        if member.status not in ["member", "administrator", "creator"]:
            await query.answer("شما عضو کانال نیستید!", show_alert=True)
            return
    except Exception as e:
        await query.answer("خطا در بررسی عضویت. مطمئن شوید ربات در کانال ادمین است.", show_alert=True)
        return

    # اعطای پاداش
    data["users"][str(user_id)] = data["users"].get(str(user_id), 0) + task["reward"]
    data["completed"].setdefault(str(task_id), []).append(str(user_id))
    task["claimed"] += 1

    # اگر تعداد تکمیل شده به حد نصاب رسید، سفارش را حذف کن
    if task["claimed"] >= task["count"]:
        data["tasks"].remove(task)
        await set_data(data)
        # ویرایش پیام کانال به تکمیل شده
        try:
            await query.edit_message_text("✅ سفارش تکمیل شد و حذف گردید.")
        except:
            pass
    else:
        await set_data(data)

    await query.answer(f"✅ {task['reward']} سکه دریافت کردید!", show_alert=True)

# ---------- سایر دستورات ----------

async def balance(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    data = await get_data()
    bal = data["users"].get(user_id, 0)
    await update.message.reply_text(f"💰 موجودی شما: {bal} سکه")

# ---------- راه‌اندازی اپلیکیشن ----------

app_bot = Application.builder().token(TOKEN).build()
app_bot.add_handler(CommandHandler("start", start))
app_bot.add_handler(CommandHandler("balance", balance))
app_bot.add_handler(CallbackQueryHandler(free_coins_menu, pattern="^free_coins$"))
app_bot.add_handler(CallbackQueryHandler(daily_coins, pattern="^daily_coins$"))
app_bot.add_handler(CallbackQueryHandler(order_member_menu, pattern="^order_member_menu$"))
app_bot.add_handler(CallbackQueryHandler(package_selected, pattern="^member_"))
app_bot.add_handler(CallbackQueryHandler(claim_member, pattern="^claim_member_"))
app_bot.add_handler(
    MessageHandler(
        filters.TEXT & ~filters.COMMAND,
        handle_text
    )
)

# ---------- FastAPI ----------

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
