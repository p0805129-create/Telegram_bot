import os
import json
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

_initialized = False

# ----- تنظیمات ثابت (حتماً این دو را تغییر بده) -----
ADMIN_ID = 7724653657                   # آیدی عددی ادمین
ORDER_CHANNEL_ID = "@viewpluse"   # آیدی یا نام کاربری کانال سفارش‌ها
CHANNEL_USERNAME = "viewpluse"    # نام کاربری کانال برای دکمه عضویت (بدون @)
# ---------------------------------------------------

async def get_data():
    raw = await redis.get(DATA_KEY)
    defaults = {
        "users": {"7724653657": 10000},   # موجودی اولیه ادمین
        "tasks": [],
        "completed": {},        # {task_id: {user_id: timestamp}}
        "next_task_id": 1,
        "states": {},
        "daily_claims": {}      # بدون استفاده، ولی برای سازگاری
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

# ---------- منوی اصلی ----------

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    data = await get_data()

    is_new = user_id not in data["users"]
    if is_new:
        data["users"][user_id] = 10   # هدیه ۱۰ سکه برای کاربر جدید
    else:
        data["users"].setdefault(user_id, 0)

    # پردازش لینک ریفرال
    if context.args and len(context.args) > 0:
        arg = context.args[0]
        if arg.startswith("ref_"):
            ref = arg[4:]
            if ref.isdigit() and is_new:
                referrer_id = int(ref)
                if referrer_id != int(user_id):
                    data["users"][str(referrer_id)] = data["users"].get(str(referrer_id), 0) + 15

    await set_data(data)

    keyboard = ReplyKeyboardMarkup(
        [
            [KeyboardButton("💰 دریافت سکه رایگان")],
            [KeyboardButton("👥 سفارش ممبر")],
            [KeyboardButton("👤 حساب کاربری")],
            [KeyboardButton("📦 پیگیری سفارش")],
            [KeyboardButton("👥️ جذب زیر مجموعه")],
            [KeyboardButton("📚 راهنما")]
        ],
        resize_keyboard=True,
        one_time_keyboard=False
    )

    await update.message.reply_text(
        "به ربات خوش آمدید! یکی از گزینه‌ها را انتخاب کنید:",
        reply_markup=keyboard
    )

# ---------- دستور ادمین برای افزایش سکه ----------

async def give_coins(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("شما اجازه استفاده از این دستور را ندارید.")
        return
    try:
        parts = update.message.text.split()
        if len(parts) != 3:
            await update.message.reply_text("فرمت صحیح: /give <user_id> <amount>")
            return
        target_id = int(parts[1])
        amount = int(parts[2])
        data = await get_data()
        data["users"][str(target_id)] = data["users"].get(str(target_id), 0) + amount
        await set_data(data)
        await update.message.reply_text(f"✅ {amount} سکه به کاربر {target_id} داده شد.")
    except ValueError:
        await update.message.reply_text("لطفاً اعداد صحیح وارد کنید.")

# ---------- دریافت سکه رایگان ----------

async def free_coins_from_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (
        "به بخش دریافت سکه رایگان خوش آمدید💫\n\n"
        "📌 در این بخش می‌تونید با استفاده از یک روش زیر برای خودتون سکه جمع آوری کنید سپس با سکه های جمع آوری شده برای کانال/گروه خود ممبر سفارش بدید.\n\n"
        "👈 یک روش برای جمع آوری الماس وجود دارد:\n\n"
        "1️⃣ عضویت در سفارش های موجود: در این روش شما می‌توانید با عضویت در سفارشات موجود و سپس زدن دکمه ی دریافت اقدام به جمع آوری الماس نمایید.\n\n"
        "🫂 همچنین از طریق زیر مجموعه گیری هم می‌تونید تا بی‌نهایت الماس رایگان کسب کنید."
    )
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("📢 عضویت در کانال", url=f"https://t.me/{CHANNEL_USERNAME}")]
    ])
    await update.message.reply_text(text, reply_markup=keyboard)

# ---------- راهنما ----------

async def help_from_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    help_text = (
        "«🤔راهنمای ممبرگیر | ویوپلاس»\n\n"
        "(✅لطفاً تمام متن را با دقت بخوانید✅)\n\n"
        "ممبرگیر | ویوپلاس یک ربات برای افزایش رایگان اعضای کانال و گروه شماست!\n\n"
        "⚠️ قبل از سفارش دادن ممبر در ربات باید ربات ما یعنی ممبرگیر | ویوپلاس را ادمین کانال یا گروه خود کنید. \n"
        "⚠️ بعد از ادمین کردن ربات برای سفارش دادن ممبر برای کانال و گروه خود باید در ربات  سکه داشته باشید.\n"
        "💰•برای دریافت سکه در ربات چند روش وجود دارد!👇\n\n"
        "💰\\روش اول: \n"
        "عضویت در سفارشات:\n"
        "شما میتوانید با عضویت در کانال ها و گروه هایی که در کانال سفارشات سرعت ممبر وجود دارد الماس دریافت کنید. برای این کار اول باید عضو کانال ها و گروه ها شوید بعد به کانال سفارشات برگردید سپس روی دریافت الماس کلیک کنید.\n\n"
        "👥\\روش دوم: \n"
        "زیر مجموعه گیری :\n"
        "برای این کار وارد بخش زیر مجموعه گیری میشید و لینک خود را برای دیگران میفرستید !\n\n"
        "🛍️\\روش سوم: می توانید از ما سکه خریداری کنید!\n\n\n"
        "«🔖سوال های متداول 🔖»\n\n"
        "⁉️چطوری ربات رو ادمین کنم؟\n\n"
        "⛔️|روش ادمین کردن ربات به این صورت است که وارد کانال یا گروه تون شوید و به قسمت ادمین ها بروید و اضافه کردن ادمین را انتخاب کنید سپس روی سرچ بزنید و ایدی ربات( @Seen_member_jet_bot ) را سرچ کنید و ربات مارا ادمین کنید!\n"
        "●\n"
        "⁉️ممبر هایی که از طریق ربات سرعت ممبر به کانال و گروه اضافه میشن واقعی هستن؟\n\n"
        "بله.کاملا واقعی و ایرانی که به دلیل واقعی بودن بازدید هم دارن و اگر از کانال و گروهتون خوششون بیاد ممکنه تا همیشه بمونن و لفت ندن😊\n\n"
        "●\n"
        "⁉️چرا سفارشم تکمیل شده ولی تعداد ممبر دریافتیم کمتر از سفارشم هست؟!\n"
        "(مثلا 10 ممبر سفارش دادم ولی 7 تا اومده )\n"
        "⚠️دو دلیل داره:\n"
        "1⃣یا اون تعداد از قبل عضو کانال یا گروه شما شده بودن اما از سفارشتون سکه گرفتن.\n"
        "2⃣یا ربات رو ادمین گروه تون نکردید و سفارش دادید.وقتی این کارو کنید ربات  حتی اگر دیگران عضو گروه شما نشن  و روی دکمه دریافت سکه بزنن هم بهشون الماس میده ؛ چون ادمین گروهتون نیست!\n"
        "°\n"
        "‼️توجه :\n"
        "•در صورت باز نشدن دکمه های ربات لطفاً با ارسال دستور /start ربات را استارت کنید تا ربات آپدیت بشه و دوباره دکمه های ربات برای شما باز بشه!\n"
        "ربات ثبت سفارشات\n"
        "@Seen_member_jet_bot\n"
        "چنل سفارشات\n"
        "@viewpluse"
    )
    await update.message.reply_text(help_text)

# ---------- سفارش ممبر ----------

PACKAGES = {
    "member_10": {"count": 10, "cost": 20, "reward": 2},
    "member_20": {"count": 20, "cost": 40, "reward": 2},
    "member_50": {"count": 50, "cost": 80, "reward": 2},
    "member_80": {"count": 80, "cost": 100, "reward": 2},
    "member_100": {"count": 100, "cost": 150, "reward": 2},
    "member_500": {"count": 500, "cost": 700, "reward": 2},
}

async def order_member_from_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("👥️ 10 ممبر | 20 🪙", callback_data="member_10")],
        [InlineKeyboardButton("👥️ 20 ممبر | 40 🪙", callback_data="member_20")],
        [InlineKeyboardButton("👥️ 50 ممبر | 80 🪙", callback_data="member_50")],
        [InlineKeyboardButton("👥️ 80 ممبر | 100 🪙", callback_data="member_80")],
        [InlineKeyboardButton("👥️ 100 ممبر | 150 🪙", callback_data="member_100")],
        [InlineKeyboardButton("👥️ 500 ممبر | 700 🪙", callback_data="member_500")],
    ])
    await update.message.reply_text("پکیج مورد نظر را انتخاب کنید:", reply_markup=keyboard)

async def package_selected(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    package_key = query.data
    user_id = str(query.from_user.id)

    data = await get_data()
    cost = PACKAGES[package_key]["cost"]
    if data["users"].get(user_id, 0) < cost:
        await query.answer("موجودی شما کافی نیست!", show_alert=False)
        return

    data["states"][user_id] = {"awaiting_order": package_key}
    await set_data(data)

    text = (
        "✅ جهت دریافت ممبر باید ابتدا ربات را ادمین کانال مورد نظر کنید سپس آیدی کانال را ارسال نمایید\n\n"
        "👈 نمونه : viewpluse@\n"
        "⚠️ لطفاً لینک یا نام کاربری کانال را ارسال کنید."
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

    keyboard = ReplyKeyboardMarkup(
        [
            [KeyboardButton("💰 دریافت سکه رایگان")],
            [KeyboardButton("👥 سفارش ممبر")],
            [KeyboardButton("👤 حساب کاربری")],
            [KeyboardButton("📦 پیگیری سفارش")],
            [KeyboardButton("👥️ جذب زیر مجموعه")],
            [KeyboardButton("📚 راهنما")]
        ],
        resize_keyboard=True,
        one_time_keyboard=False
    )
    await query.edit_message_text("سفارش لغو شد. به منوی اصلی بازگشتید:", reply_markup=keyboard)

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    data = await get_data()
    state = data["states"].get(user_id, {})

    if "awaiting_order" in state:
        package_key = state.pop("awaiting_order")
        raw_input = update.message.text.strip()

        # پردازش لینک یا نام کاربری
        if raw_input.startswith("https://t.me/"):
            raw_input = raw_input.split("/")[-1]
            if raw_input.startswith("+"):
                await update.message.reply_text(
                    "❌ برای کانال/گروه خصوصی، لطفاً آیدی عددی را ارسال کنید یا یک پیام از کانال را فوروارد کنید."
                )
                return
            target = "@" + raw_input
            invite_link = f"https://t.me/{raw_input}"
        elif raw_input.startswith("@"):
            target = raw_input
            invite_link = f"https://t.me/{raw_input[1:]}"
        else:
            # فرض می‌کنیم آیدی عددی است
            target = raw_input
            try:
                invite_link = await context.bot.export_chat_invite_link(chat_id=target)
            except Exception as e:
                await update.message.reply_text(
                    "❌ نتوانستم لینک دعوت بسازم. مطمئن شوید ربات در کانال ادمین است و آیدی صحیح است."
                )
                return

        target_channel_id = target
        cost = PACKAGES[package_key]["cost"]
        if data["users"].get(user_id, 0) < cost:
            await update.message.reply_text("موجودی کافی نیست.")
            return

        data["users"][user_id] -= cost

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

        # تلاش برای گرفتن نام کانال
        channel_display = target_channel_id
        try:
            chat_info = await context.bot.get_chat(chat_id=target_channel_id)
            channel_display = chat_info.title or chat_info.username or target_channel_id
        except:
            pass

        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("مشاهده کانال", url=invite_link)],
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
                    f"📌 کانال: {channel_display}\n"
                    f"➡️ ابتدا کانال را مشاهده کنید، سپس عضو شوید و بعد دکمه «دریافت سکه» را بزنید."
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
        return

    # دکمه‌های منوی پایین
    if update.message.text == "💰 دریافت سکه رایگان":
        await free_coins_from_menu(update, context)
        return

    if update.message.text == "👥 سفارش ممبر":
        await order_member_from_menu(update, context)
        return

    if update.message.text == "👤 حساب کاربری":
        bal = data["users"].get(user_id, 0)
        await update.message.reply_text(f"💰 موجودی شما: {bal} سکه")
        return

    if update.message.text == "📦 پیگیری سفارش":
        user_orders = [t for t in data["tasks"] if t["owner_id"] == int(user_id)]
        if not user_orders:
            await update.message.reply_text("شما سفارش فعالی ندارید.")
            return
        for order in user_orders:
            await update.message.reply_text(
                f"📦 سفارش #{order['id']}\n"
                f"👥 تعداد کاربر درخواستی: {order['count']}\n"
                f"✅ تعداد ممبر دریافتی: {order['claimed']}"
            )
        return

    if update.message.text == "👥️ جذب زیر مجموعه":
        await referral_menu(update, context)
        return

    if update.message.text == "📚 راهنما":
        await help_from_menu(update, context)
        return

# ---------- دریافت سکه بعد از عضویت ----------

async def claim_member(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id
    task_id = int(query.data.split("_")[-1])

    data = await get_data()
    task = next((t for t in data["tasks"] if t["id"] == task_id), None)
    if not task:
        await query.answer("این سفارش دیگر موجود نیست.", show_alert=False)
        return

    if str(user_id) in data["completed"].get(str(task_id), {}):
        await query.answer("شما قبلاً سکه را دریافت کرده‌اید", show_alert=False)
        return

    try:
        member = await context.bot.get_chat_member(chat_id=task["target_id"], user_id=user_id)
        if member.status not in ["member", "administrator", "creator"]:
            await query.answer("شما عضو کانال نیستید!", show_alert=False)
            return
    except Exception as e:
        await query.answer("خطا در بررسی عضویت. مطمئن شوید ربات در کانال ادمین است.", show_alert=False)
        return

    # اعطای پاداش
    data["users"][str(user_id)] = data["users"].get(str(user_id), 0) + task["reward"]
    # ثبت زمان عضویت برای بررسی ترک زودهنگام
    data["completed"].setdefault(str(task_id), {})[str(user_id)] = datetime.now(timezone.utc).isoformat()
    task["claimed"] += 1

    if task["claimed"] >= task["count"]:
        data["tasks"].remove(task)
        await set_data(data)
        try:
            await query.edit_message_text("✅ سفارش تکمیل شد و حذف گردید.")
        except:
            pass
    else:
        await set_data(data)

    current_balance = data["users"][str(user_id)]
    await query.answer(
        f"💰 {task['reward']} سکه کسب کردید | موجودی: {current_balance} سکه",
        show_alert=False
    )

# ---------- بررسی ترک زودهنگام ----------

async def check_early_leaves():
    data = await get_data()
    now = datetime.now(timezone.utc)
    penalized = False

    for task in data["tasks"]:
        task_id = str(task["id"])
        if task_id not in data["completed"]:
            continue
        completed_users = data["completed"][task_id]
        for user_id, joined_at_str in list(completed_users.items()):
            joined_at = datetime.fromisoformat(joined_at_str)
            age = now - joined_at
            if age < timedelta(days=4):
                try:
                    member = await app_bot.bot.get_chat_member(chat_id=task["target_id"], user_id=int(user_id))
                    if member.status not in ["member", "administrator", "creator"]:
                        # کاربر عضو نیست → جریمه
                        data["users"][user_id] = max(0, data["users"].get(user_id, 0) - 3)
                        owner_id = str(task["owner_id"])
                        data["users"][owner_id] = data["users"].get(owner_id, 0) + 2
                        del completed_users[user_id]
                        penalized = True
                except Exception as e:
                    pass

    if penalized:
        await set_data(data)
    return penalized

# ---------- جذب زیر مجموعه ----------

async def referral_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
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

# ---------- حساب کاربری و پیگیری سفارش ----------

async def account_from_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    data = await get_data()
    bal = data["users"].get(user_id, 0)
    await update.message.reply_text(f"💰 موجودی شما: {bal} سکه")

async def track_order_from_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    data = await get_data()
    user_orders = [t for t in data["tasks"] if t["owner_id"] == int(user_id)]
    if not user_orders:
        await update.message.reply_text("شما سفارش فعالی ندارید.")
        return
    for order in user_orders:
        await update.message.reply_text(
            f"📦 سفارش #{order['id']}\n"
            f"👥 تعداد کاربر درخواستی: {order['count']}\n"
            f"✅ تعداد ممبر دریافتی: {order['claimed']}"
        )

# ---------- سایر دستورات ----------

async def balance(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    data = await get_data()
    bal = data["users"].get(user_id, 0)
    await update.message.reply_text(f"💰 موجودی شما: {bal} سکه")

# ---------- راه‌اندازی اپلیکیشن ----------

app_bot = Application.builder().token(TOKEN).build()
app_bot.add_handler(CommandHandler("start", start))
app_bot.add_handler(CommandHandler("give", give_coins))
app_bot.add_handler(CommandHandler("balance", balance))
app_bot.add_handler(CallbackQueryHandler(package_selected, pattern="^member_"))
app_bot.add_handler(CallbackQueryHandler(cancel_order, pattern="^cancel_order$"))
app_bot.add_handler(CallbackQueryHandler(referral_banner, pattern="^referral_banner$"))
app_bot.add_handler(CallbackQueryHandler(claim_member, pattern="^claim_member_"))
app_bot.add_handler(MessageHandler(filters.Text(["💰 دریافت سکه رایگان"]), free_coins_from_menu))
app_bot.add_handler(MessageHandler(filters.Text(["👥 سفارش ممبر"]), order_member_from_menu))
app_bot.add_handler(MessageHandler(filters.Text(["👤 حساب کاربری"]), account_from_menu))
app_bot.add_handler(MessageHandler(filters.Text(["📦 پیگیری سفارش"]), track_order_from_menu))
app_bot.add_handler(MessageHandler(filters.Text(["👥️ جذب زیر مجموعه"]), referral_menu))
app_bot.add_handler(MessageHandler(filters.Text(["📚 راهنما"]), help_from_menu))
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

@app.get("/check")
async def check_endpoint():
    global _initialized
    if not _initialized:
        await app_bot.initialize()
        _initialized = True
    penalized = await check_early_leaves()
    return {"ok": True, "penalized": penalized}
