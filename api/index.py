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

# ----- تنظیمات ثابت -----
ADMIN_ID = 7724653657
ADMIN_USERNAME = "@Dorinamm"  # تغییر یافت
ORDER_CHANNEL_ID = "@viewpluse"
ORDER_CHANNEL_URL = "https://t.me/viewpluse"
CHANNEL_USERNAME = "viewpluse"
SPONSOR_CHANNELS = [c.strip() for c in os.environ.get("SPONSOR_CHANNELS", "@patrickeeee,@infinitiiii2,@viewpluse").split(",") if c.strip()]
# ---------------------------------------------------

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

# ---------- بررسی عضویت در کانال‌های اسپانسر ----------

async def check_subscription(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    user_id = update.effective_user.id
    for channel in SPONSOR_CHANNELS:
        try:
            member = await context.bot.get_chat_member(chat_id=channel, user_id=user_id)
            if member.status not in ["member", "administrator", "creator"]:
                return False
        except Exception:
            return False
    return True

async def send_subscription_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (
        "❗️لطفا برای ادامه کار با ربات و حمایت کردن از ما عضو گروه و کانال های زیر شوید👇\n\n"
        + "\n".join([f"🆔 {ch}" for ch in SPONSOR_CHANNELS])
        + "\n\n💎اسپانسر ها:\n"
        + "\n".join([f"🪅{i+1} {ch}" for i, ch in enumerate(SPONSOR_CHANNELS)])
        + "\n\n❗️پس از عضو شدن برای ربات دستور /start را ارسال کنید✓"
    )
    await update.message.reply_text(text)

# ---------- منوی اصلی ----------

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    data = await get_data()

    is_new = user_id not in data["users"]
    if is_new:
        data["users"][user_id] = 10   # هدیه ۱۰ سکه برای کاربر جدید
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
            [KeyboardButton("💰 دریافت سکه رایگان")],
            [KeyboardButton("👥 سفارش ممبر")],
            [KeyboardButton("🛍️ فروشگاه")],
            [KeyboardButton("👤 حساب کاربری")],
            [KeyboardButton("📦 پیگیری سفارش")],
            [KeyboardButton("👥️ جذب زیر مجموعه")],
            [KeyboardButton("📚 راهنما")]
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

# ---------- دستور /help ----------
async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_subscription(update, context):
        await send_subscription_message(update, context)
        return
    await help_from_menu(update, context)

# ---------- دستور ادمین برای افزایش سکه ----------
async def give_coins(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("شما اجازه استفاده از این دستور را ندارید.")
        return

    try:
        parts = update.message.text.split()
        if len(parts) != 3:
            await update.message.reply_text("فرمت صحیح: /give <یوزرنیم یا آیدی عددی> <مقدار>")
            return

        target = parts[1]
        amount = int(parts[2])

        data = await get_data()

        if target.startswith("@"):
            username = target[1:].lower()
            user_id = data.get("usernames", {}).get(username)
            if not user_id:
                await update.message.reply_text("❌ کاربر با این یوزرنیم پیدا نشد. مطمئن شوید کاربر ربات را استارت کرده باشد.")
                return
        else:
            user_id = str(target)

        if user_id not in data["users"]:
            data["users"][user_id] = 0

        data["users"][user_id] += amount
        await set_data(data)
        await update.message.reply_text(f"✅ {amount} سکه به کاربر {target} داده شد.")
    except ValueError:
        await update.message.reply_text("لطفاً مقدار سکه را به صورت عدد صحیح وارد کنید.")
    except Exception as e:
        await update.message.reply_text(f"خطا: {e}")

# ---------- فروشگاه ----------
async def shop_from_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_subscription(update, context):
        await send_subscription_message(update, context)
        return

    text = (
        "🛍 به فروشگاه ربات ویو پلاس خوش آمدید💰\n"
        "لطفا گزینه ی مورد نظر را جهت خرید انتخاب کنید 👇"
    )
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("سکه 🪙", callback_data="shop_coins")],
        [InlineKeyboardButton("اسپانسر", callback_data="shop_sponsor")]
    ])
    await update.message.reply_text(text, reply_markup=keyboard)

async def shop_coins(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    text = (
        "خرید سکه 💰\n\n"
        "100 سکه => 15 هزار تومن\n"
        "250 سکه => 30 هزار تومن\n"
        "500 سکه => 45 هزار تومن\n"
        "1000 سکه => 65 هزار تومن\n"
        "4000 سکه => 260 هزار تومن\n\n"
        "جهت خرید سکه و کارت به کارت یا مشاوره و سوال به ایدی زیر پیام دهید\n"
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

# ---------- دریافت سکه رایگان ----------
async def free_coins_from_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_subscription(update, context):
        await send_subscription_message(update, context)
        return

    text = (
        "به بخش دریافت سکه رایگان خوش آمدید💫\n\n"
        "📌 در این بخش می‌تونید با استفاده از یک روش زیر برای خودتون سکه جمع آوری کنید سپس با سکه های جمع آوری شده برای کانال/گروه خود ممبر سفارش بدید.\n\n"
        "👈 یک روش برای جمع آوری سکه وجود دارد:\n\n"
        "1️⃣ عضویت در سفارش های موجود: در این روش شما می‌توانید با عضویت در سفارشات موجود و سپس زدن دکمه ی دریافت اقدام به جمع آوری سکه نمایید.\n\n"
        "‼️اگر کمتر از 4روز از کانال ها لفت بدید 3 سکه از شما کسر میشود \n\n"
        "🫂 همچنین از طریق زیر مجموعه گیری هم می‌تونید تا بی‌نهایت سکه رایگان کسب کنید."
    )
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("📢 عضویت در کانال", url=f"https://t.me/{CHANNEL_USERNAME}")]
    ])
    await update.message.reply_text(text, reply_markup=keyboard)

# ---------- راهنما ----------
async def help_from_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_subscription(update, context):
        await send_subscription_message(update, context)
        return

    help_text = (
        "«🤔راهنمای ممبرگیر | ویوپلاس»\n\n"
        "(✅لطفاً تمام متن را با دقت بخوانید✅)\n\n"
        "ممبرگیر | ویوپلاس یک ربات برای افزایش رایگان اعضای کانال و گروه شماست!\n\n"
        "⚠️ قبل از سفارش دادن ممبر در ربات باید ربات ما یعنی ممبرگیر | ویوپلاس را ادمین کانال یا گروه خود کنید. \n"
        "⚠️ بعد از ادمین کردن ربات برای سفارش دادن ممبر برای کانال و گروه خود باید در ربات  سکه داشته باشید.\n"
        "💰•برای دریافت سکه در ربات چند روش وجود دارد!👇\n\n"
        "💰\\روش اول: \n"
        "عضویت در سفارشات:\n"
        "شما میتوانید با عضویت در کانال ها و گروه هایی که در کانال سفارشات ممبرگیر | ویوپلاس وجود دارد سکه دریافت کنید. برای این کار اول باید عضو کانال ها و گروه ها شوید بعد به کانال سفارشات برگردید سپس روی دریافت سکه کلیک کنید.\n\n"
        "👥\\روش دوم: \n"
        "زیر مجموعه گیری :\n"
        "برای این کار وارد بخش زیر مجموعه گیری میشید و لینک خود را برای دیگران میفرستید !\n\n"
        "🛍️\\روش سوم: می توانید از ما سکه خریداری کنید!\n\n\n"
        "«🔖سوال های متداول 🔖»\n\n"
        "⁉️چطوری ربات رو ادمین کنم؟\n\n"
        "⛔️|روش ادمین کردن ربات به این صورت است که وارد کانال یا گروه تون شوید و به قسمت ادمین ها بروید و اضافه کردن ادمین را انتخاب کنید سپس روی سرچ بزنید و ایدی ربات( @Seen_member_jet_bot ) را سرچ کنید و ربات مارا ادمین کنید!\n"
        "●\n"
        "⁉️ممبر هایی که از طریق ربات ممبرگیر | ویوپلاس به کانال و گروه اضافه میشن واقعی هستن؟\n\n"
        "بله.کاملا واقعی و ایرانی که به دلیل واقعی بودن بازدید هم دارن و اگر از کانال و گروهتون خوششون بیاد ممکنه تا همیشه بمونن و لفت ندن😊\n\n"
        "●\n"
        "⁉️چرا سفارشم تکمیل شده ولی تعداد ممبر دریافتیم کمتر از سفارشم هست؟!\n"
        "(مثلا 10 ممبر سفارش دادم ولی 7 تا اومده )\n"
        "⚠️دو دلیل داره:\n"
        "1⃣یا اون تعداد از قبل عضو کانال یا گروه شما شده بودن اما از سفارشتون سکه گرفتن.\n"
        "2⃣یا ربات رو ادمین گروه تون نکردید و سفارش دادید.وقتی این کارو کنید ربات  حتی اگر دیگران عضو گروه شما نشن  و روی دکمه دریافت سکه بزنن هم بهشون سکه میده ؛ چون ادمین گروهتون نیست!\n"
        "°\n"
        "‼️توجه :\n"
        "•در صورت باز نشدن دکمه های ربات لطفاً با ارسال دستور /start ربات را استارت کنید تا ربات آپدیت بشه و دوباره دکمه های ربات برای شما باز بشه!\n"
        "ربات ثبت سفارشات\n"
        "@Seen_member_jet_bot\n"
        "چنل سفارشات\n"
        "@viewpluse"
    )
    await update.message.reply_text(help_text)

# ---------- پیگیری سفارش (منوی جدید) ----------
async def track_order_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_subscription(update, context):
        await send_subscription_message(update, context)
        return

    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🔍 پیگیری سفارشات 🔍", callback_data="track_orders"),
            InlineKeyboardButton("‼️ قوانین ‼️", callback_data="show_rules")
        ]
    ])
    await update.message.reply_text("👈 گزینه ی مورد نظر را انتخاب کنید", reply_markup=keyboard)

async def track_orders_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if not await check_subscription(update, context):
        await send_subscription_message(update, context)
        return

    user_id = str(query.from_user.id)
    data = await get_data()
    user_orders = [t for t in data["tasks"] if t["owner_id"] == int(user_id)]
    if not user_orders:
        await query.edit_message_text("شما سفارش فعالی ندارید.")
        return

    text = "📋 لیست سفارش‌های شما:\n\n"
    for order in user_orders:
        text += (
            f"📦 سفارش #{order['id']}\n"
            f"👥 تعداد کاربر درخواستی: {order['count']}\n"
            f"✅ تعداد ممبر دریافتی: {order['claimed']}\n"
            f"📌 آیدی کانال: {order['target_id']}\n\n"
        )
    await query.edit_message_text(text)

async def rules_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    rules_text = (
        "⛔️ کانال شما نباید شامل موارد زیر باشد:\n"
        "1️⃣ - خلاف قوانین جمهوری اسلامی ایران\n"
        "2️⃣ - فحاشی و توهین\n"
        "3️⃣ - محتوای جنسی و بزرگسالان\n"
        "4️⃣ - مزاحمت و پخش اطلاعات افراد\n"
        "5️⃣ - کلاهبرداری و پخش موارد جعلی\n"
        "6️⃣ - سایتها و رباتها و کانالهای شرط بندی\n"
        "7️⃣ - تبلیغ ربات های مشابه، ربات های غیرواقعی\n"
        "8️⃣ - فریب افراد و کاربران\n"
        "9️⃣ - هک و نفوذ، پخش برنامه های پولی و موارد علیه کپی رایت\n"
        "🔟 - و ... (موارد غیرمجاز)\n\n"
        "⚠️ توجه داشته باشید در صورتی که کانال شما شامل موارد بالا بود سفارش آن لغو و حساب فرد خاطی مسدود میگردد‼️\n\n"
        "⚠️ قوانین و مقررات دائما در حال به روز شدن می باشند و کلیه کاربران موظف به مطالعه این صفحه به صورت مکرر می باشند."
    )
    await query.edit_message_text(rules_text)

# ---------- سفارش ممبر ----------
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
    if not await check_subscription(update, context):
        await send_subscription_message(update, context)
        return

    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("👥️ 5 ممبر | 10 🪙", callback_data="member_5")],
        [InlineKeyboardButton("👥️ 10 ممبر | 20 🪙", callback_data="member_10")],
        [InlineKeyboardButton("👥️ 20 ممبر | 40 🪙", callback_data="member_20")],
        [InlineKeyboardButton("👥️ 50 ممبر | 80 🪙", callback_data="member_50")],
        [InlineKeyboardButton("👥️ 80 ممبر | 100 🪙", callback_data="member_80")],
        [InlineKeyboardButton("👥️ 100 ممبر | 150 🪙", callback_data="member_100")],
        [InlineKeyboardButton("👥️ 500 ممبر | 700 🪙", callback_data="member_500")],
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
        await query.answer("💰موجودی شما کافی نمی باشد 🚫", show_alert=False)
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
    user_id = str(update.effective_user.id)
    data = await get_data()
    state = data["states"].get(user_id, {})

    if "awaiting_order" in state:
        package_key = state.pop("awaiting_order")
        raw_input = update.message.text.strip()

        if raw_input.startswith("https://t.me/"):
            raw_input = raw_input.split("/")[-1]
            if raw_input.startswith("+"):
                await update.message.reply_text("❌ لینک دعوت خصوصی قابل قبول نیست. لطفاً آیدی عمومی کانال یا گروه را به صورت @username یا https://t.me/username ارسال کنید.")
                return
            target = "@" + raw_input
            invite_link = f"https://t.me/{raw_input}"
        elif raw_input.startswith("@"):
            target = raw_input
            invite_link = f"https://t.me/{raw_input[1:]}"
        else:
            await update.message.reply_text("❌ فرمت آیدی کانال صحیح نیست. لطفاً به صورت @username یا https://t.me/username ارسال کنید.")
            return

        target_channel_id = target
        cost = PACKAGES[package_key]["cost"]

        # بررسی ادمین بودن ربات
        bot_id = (await context.bot.get_me()).id
        try:
            bot_member = await context.bot.get_chat_member(chat_id=target_channel_id, user_id=bot_id)
            if bot_member.status not in ["administrator", "creator"]:
                await update.message.reply_text("🚫کاربر گرامی جهت ثبت سفارش ابتدا ربات را ادمین کانال یا کروه خود کنید و دوباره سفارش خود را ثبت کنید")
                return
        except Exception:
            await update.message.reply_text("🚫جهت ثبت سفارش، ربات باید در کانال/گروه ادمین باشد. لطفاً ادمین بودن ربات را بررسی کنید و دوباره تلاش کنید.")
            return

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
                InlineKeyboardButton("💰 دریافت سکه", callback_data=f"claim_member_{task['id']}")
            ],
            [InlineKeyboardButton("♻️ ورود به ربات", url="https://t.me/Seen_member_jet_bot")],
            [InlineKeyboardButton("🚫 تخلف", callback_data=f"report_task_{task['id']}")]  # دکمه جدید
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
            f"هزینه: {cost} سکه\n"
            f"پس از تکمیل اعضا، سفارش از کانال حذف خواهد شد.",
            reply_markup=confirmation_keyboard
        )
        return

    # دکمه‌های منوی پایین
    if update.message.text == "💰 دریافت سکه رایگان":
        await free_coins_from_menu(update, context)
        return
    if update.message.text == "👥 سفارش ممبر":
        await order_member_from_menu(update, context)
        return
    if update.message.text == "🛍️ فروشگاه":
        await shop_from_menu(update, context)
        return
    if update.message.text == "👤 حساب کاربری":
        if not await check_subscription(update, context):
            await send_subscription_message(update, context)
            return
        bal = data["users"].get(user_id, 0)
        await update.message.reply_text(f"💰 موجودی شما: {bal} سکه")
        return
    if update.message.text == "📦 پیگیری سفارش":
        await track_order_menu(update, context)
        return
    if update.message.text == "👥️ جذب زیر مجموعه":
        if not await check_subscription(update, context):
            await send_subscription_message(update, context)
            return
        await referral_menu(update, context)
        return
    if update.message.text == "📚 راهنما":
        await help_from_menu(update, context)
        return

# ---------- گزارش تخلف ----------
async def report_task(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    task_id = int(query.data.split("_")[-1])
    data = await get_data()
    task = next((t for t in data["tasks"] if t["id"] == task_id), None)
    if not task:
        await query.answer("سفارش یافت نشد.", show_alert=False)
        return

    # ارسال گزارش به ادمین
    report_text = (
        "🚨 گزارش تخلف سفارش\n\n"
        f"📦 کد سفارش: {task['id']}\n"
        f"👤 صاحب سفارش: {task['owner_id']}\n"
        f"📌 آیدی کانال: {task['target_id']}\n"
        f"🔗 لینک کانال: {task['target_link']}\n"
        f"👥 تعداد درخواستی: {task['count']}\n"
        f"✅ تعداد دریافتی: {task['claimed']}"
    )

    try:
        await context.bot.send_message(chat_id=ADMIN_ID, text=report_text)
        await query.answer("گزارش تخلف شما ثبت شد.", show_alert=False)
    except Exception as e:
        await query.answer("خطا در ارسال گزارش به ادمین.", show_alert=False)

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

    # بررسی ادمین بودن ربات در کانال هدف
    bot_id = (await context.bot.get_me()).id
    try:
        bot_member = await context.bot.get_chat_member(chat_id=task["target_id"], user_id=bot_id)
        bot_is_admin = bot_member.status in ["administrator", "creator"]
    except Exception:
        bot_is_admin = False

    if not bot_is_admin:
        # حذف سفارش
        data["tasks"].remove(task)
        await set_data(data)

        # حذف پیام از کانال سفارش‌ها
        if "message_id" in task:
            try:
                await context.bot.delete_message(
                    chat_id=ORDER_CHANNEL_ID,
                    message_id=task["message_id"]
                )
            except:
                pass

        # اطلاع به صاحب سفارش
        try:
            await context.bot.send_message(
                chat_id=task["owner_id"],
                text="سفارش شما به دلیل ادمین نبودن ربات حذف شد"
            )
        except:
            pass

        await query.answer("ربات در کانال ادمین نیست، سفارش حذف شد.", show_alert=False)
        return

    if str(user_id) in data["completed"].get(str(task_id), {}):
        await query.answer("شما قبلاً سکه را دریافت کرده‌اید", show_alert=False)
        return

    if not await check_subscription(update, context):
        await query.answer("ابتدا در کانال‌های اسپانسر عضو شوید.", show_alert=False)
        return

    # بررسی محدودیت ۴ روزه برای همان کانال
    now = datetime.now(timezone.utc)
    for record in data["join_records"]:
        if record["user_id"] == str(user_id) and record["target_id"] == task["target_id"]:
            joined_at = datetime.fromisoformat(record["joined_at"])
            if (now - joined_at) < timedelta(days=4):
                await query.answer("شما قبلاً از این کانال سکه گرفته‌اید. تا ۴ روز دیگر نمی‌توانید دوباره دریافت کنید.", show_alert=False)
                return

    try:
        member = await context.bot.get_chat_member(chat_id=task["target_id"], user_id=user_id)
        if member.status not in ["member", "administrator", "creator"]:
            await query.answer("شما عضو کانال نیستید!", show_alert=False)
            return
    except Exception:
        await query.answer("خطا در بررسی عضویت. مطمئن شوید ربات در کانال ادمین است.", show_alert=False)
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

        # حذف پیام سفارش از کانال
        if "message_id" in task:
            try:
                await context.bot.delete_message(
                    chat_id=ORDER_CHANNEL_ID,
                    message_id=task["message_id"]
                )
            except:
                pass

        # ارسال پیام خصوصی به صاحب سفارش
        try:
            await context.bot.send_message(
                chat_id=task["owner_id"],
                text=f"سفارش شما برای {task['target_id']} با کد {task['id']} به پایان رسیده"
            )
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

    remaining_records = []
    for record in data["join_records"]:
        joined_at = datetime.fromisoformat(record["joined_at"])
        age = now - joined_at

        if age >= timedelta(days=4):
            continue

        try:
            member = await app_bot.bot.get_chat_member(
                chat_id=record["target_id"],
                user_id=int(record["user_id"])
            )
            if member.status not in ["member", "administrator", "creator"]:
                user_id = record["user_id"]
                owner_id = str(record["owner_id"])

                data["users"][user_id] = max(0, data["users"].get(user_id, 0) - 3)
                data["users"][owner_id] = data["users"].get(owner_id, 0) + 2

                try:
                    await app_bot.bot.send_message(
                        chat_id=int(user_id),
                        text="به دلیل ترک کانال کمتر از 4روز 3سکه از شما کسر شد"
                    )
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

# ---------- جذب زیر مجموعه ----------
async def referral_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
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

# ---------- حساب کاربری و پیگیری سفارش ----------
async def account_from_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_subscription(update, context):
        await send_subscription_message(update, context)
        return
    user_id = str(update.effective_user.id)
    data = await get_data()
    bal = data["users"].get(user_id, 0)
    await update.message.reply_text(f"💰 موجودی شما: {bal} سکه")

# ---------- سایر دستورات ----------
async def balance(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_subscription(update, context):
        await send_subscription_message(update, context)
        return
    user_id = str(update.effective_user.id)
    data = await get_data()
    bal = data["users"].get(user_id, 0)
    await update.message.reply_text(f"💰 موجودی شما: {bal} سکه")

# ---------- هندلر دکمه noop ----------
async def noop(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

# ---------- راه‌اندازی اپلیکیشن ----------
app_bot = Application.builder().token(TOKEN).build()
app_bot.add_handler(CommandHandler("start", start))
app_bot.add_handler(CommandHandler("help", help_command))
app_bot.add_handler(CommandHandler("give", give_coins))
app_bot.add_handler(CommandHandler("balance", balance))
app_bot.add_handler(CallbackQueryHandler(package_selected, pattern="^member_"))
app_bot.add_handler(CallbackQueryHandler(cancel_order, pattern="^cancel_order$"))
app_bot.add_handler(CallbackQueryHandler(referral_banner, pattern="^referral_banner$"))
app_bot.add_handler(CallbackQueryHandler(claim_member, pattern="^claim_member_"))
app_bot.add_handler(CallbackQueryHandler(shop_coins, pattern="^shop_coins$"))
app_bot.add_handler(CallbackQueryHandler(shop_sponsor, pattern="^shop_sponsor$"))
app_bot.add_handler(CallbackQueryHandler(noop, pattern="^noop$"))
app_bot.add_handler(CallbackQueryHandler(track_orders_callback, pattern="^track_orders$"))
app_bot.add_handler(CallbackQueryHandler(rules_callback, pattern="^show_rules$"))
app_bot.add_handler(CallbackQueryHandler(report_task, pattern="^report_task_"))
app_bot.add_handler(MessageHandler(filters.Text(["💰 دریافت سکه رایگان"]), free_coins_from_menu))
app_bot.add_handler(MessageHandler(filters.Text(["👥 سفارش ممبر"]), order_member_from_menu))
app_bot.add_handler(MessageHandler(filters.Text(["🛍️ فروشگاه"]), shop_from_menu))
app_bot.add_handler(MessageHandler(filters.Text(["👤 حساب کاربری"]), account_from_menu))
app_bot.add_handler(MessageHandler(filters.Text(["📦 پیگیری سفارش"]), track_order_menu))
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
