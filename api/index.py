import os
import json
from fastapi import FastAPI, Request
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ContextTypes
from upstash_redis.asyncio import Redis

TOKEN = os.environ.get("BOT_TOKEN")

redis = Redis(
    url=os.environ.get("UPSTASH_REDIS_REST_URL"),
    token=os.environ.get("UPSTASH_REDIS_REST_TOKEN")
)

DATA_KEY = "bot_data"
_initialized = False

async def get_data():
    raw = await redis.get(DATA_KEY)
    if raw:
        return json.loads(raw)
    else:
        return {
            "users": {"7724653657": 10000},   # user_id به صورت رشته
            "tasks": [],
            "completed": {},
            "next_task_id": 1,
            "channels": {},
            "states": {}
        }

async def set_data(data):
    await redis.set(DATA_KEY, json.dumps(data))

# ---------- Handler ها ----------

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    data = await get_data()
    data["users"].setdefault(user_id, 0)
    await set_data(data)
    await update.message.reply_text(
        "سلام! به ربات تبادل سین و ممبر خوش اومدی.\n"
        "برای ثبت کانال: /register\n"
        "برای سفارش: /order\n"
        "برای مشاهده تسک‌ها: /tasks\n"
        "برای مشاهده امتیاز: /balance"
    )

async def register(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    data = await get_data()
    data["states"][user_id] = {"awaiting_reg": True}
    await set_data(data)
    await update.message.reply_text("لطفاً آیدی عددی کانال/گروه خود را بفرستید:")

async def balance(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    data = await get_data()
    bal = data["users"].get(user_id, 0)
    await update.message.reply_text(f"💰 موجودی شما: {bal} سکه")

async def order(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [InlineKeyboardButton("👁 سین (ویو)", callback_data="order_view")],
        [InlineKeyboardButton("👥 ممبر", callback_data="order_member")]
    ]
    await update.message.reply_text("چه چیزی نیاز دارید؟", reply_markup=InlineKeyboardMarkup(keyboard))

async def button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    user_id = str(query.from_user.id)
    data_db = await get_data()

    if data == "order_view":
        data_db["states"][user_id] = {"awaiting_order": "view"}
        await set_data(data_db)
        await query.edit_message_text("لینک پست کانال خود را بفرستید:")
    elif data == "order_member":
        data_db["states"][user_id] = {"awaiting_order": "member"}
        await set_data(data_db)
        await query.edit_message_text("آیدی عددی کانال/گروه خود را بفرستید (مثل -1001234567890):")
    elif data.startswith("confirm_view_"):
        task_id = int(data.split("_")[-1])
        task = next((t for t in data_db["tasks"] if t["id"] == task_id), None)
        if not task:
            await query.edit_message_text("این تسک دیگر موجود نیست.")
            return
        if query.from_user.id == task["owner_id"]:
            await query.answer("شما نمی‌توانید تسک خودتان را انجام دهید!", show_alert=True)
            return
        if str(task_id) in data_db["completed"] and user_id in data_db["completed"][str(task_id)]:
            await query.answer("شما قبلاً این تسک را انجام داده‌اید!", show_alert=True)
            return
        data_db["users"][user_id] = data_db["users"].get(user_id, 0) + task["reward"]
        data_db["completed"].setdefault(str(task_id), []).append(user_id)
        data_db["tasks"].remove(task)
        await set_data(data_db)
        await query.edit_message_text(f"✅ مشاهده تأیید شد! {task['reward']} سکه دریافت کردید.")
    elif data.startswith("check_member_"):
        task_id = int(data.split("_")[-1])
        task = next((t for t in data_db["tasks"] if t["id"] == task_id), None)
        if not task:
            await query.edit_message_text("این تسک دیگر موجود نیست.")
            return
        if query.from_user.id == task["owner_id"]:
            await query.answer("شما نمی‌توانید تسک خودتان را انجام دهید!", show_alert=True)
            return
        if str(task_id) in data_db["completed"] and user_id in data_db["completed"][str(task_id)]:
            await query.answer("شما قبلاً این تسک را انجام داده‌اید!", show_alert=True)
            return
        try:
            member = await context.bot.get_chat_member(chat_id=task["target"], user_id=query.from_user.id)
            if member.status in ["member", "administrator", "creator"]:
                data_db["users"][user_id] = data_db["users"].get(user_id, 0) + task["reward"]
                data_db["completed"].setdefault(str(task_id), []).append(user_id)
                data_db["tasks"].remove(task)
                await set_data(data_db)
                await query.edit_message_text(f"✅ عضویت تأیید شد! {task['reward']} سکه دریافت کردید.")
            else:
                await query.answer("شما عضو این کانال/گروه نیستید!", show_alert=True)
        except Exception as e:
            await query.answer("خطا در بررسی عضویت. مطمئن شوید ربات در کانال/گروه ادمین است.", show_alert=True)

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    data_db = await get_data()
    state = data_db["states"].get(user_id, {})

    if state.get("awaiting_reg"):
        data_db["channels"][user_id] = update.message.text
        state["awaiting_reg"] = False
        await set_data(data_db)
        await update.message.reply_text("✅ کانال/گروه ثبت شد.")
        return

    order_type = state.get("awaiting_order")
    if order_type == "view":
        link = update.message.text
        cost = 1   # COST_VIEW
        if data_db["users"].get(user_id, 0) < cost:
            await update.message.reply_text("❌ موجودی کافی نیست. از /balance موجودی خود را ببینید.")
            return
        data_db["users"][user_id] -= cost
        task = {
            "id": data_db["next_task_id"],
            "type": "view",
            "owner_id": int(user_id),
            "target": link,
            "cost": cost,
            "reward": 1   # REWARD_VIEW
        }
        data_db["tasks"].append(task)
        data_db["next_task_id"] += 1
        state["awaiting_order"] = None
        await set_data(data_db)
        await update.message.reply_text(f"✅ سفارش سین ثبت شد.\nهزینه: {cost} سکه\nلینک: {link}")
    elif order_type == "member":
        chat_id = update.message.text
        cost = 2   # COST_MEMBER
        if data_db["users"].get(user_id, 0) < cost:
            await update.message.reply_text("❌ موجودی کافی نیست. از /balance موجودی خود را ببینید.")
            return
        data_db["users"][user_id] -= cost
        task = {
            "id": data_db["next_task_id"],
            "type": "member",
            "owner_id": int(user_id),
            "target": chat_id,
            "cost": cost,
            "reward": 2   # REWARD_MEMBER
        }
        data_db["tasks"].append(task)
        data_db["next_task_id"] += 1
        state["awaiting_order"] = None
        await set_data(data_db)
        await update.message.reply_text(f"✅ سفارش ممبر ثبت شد.\nهزینه: {cost} سکه\nآیدی: {chat_id}")

async def tasks_list(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    data_db = await get_data()
    available = [t for t in data_db["tasks"] if t["owner_id"] != user_id]
    if not available:
        await update.message.reply_text("فعلاً تسکی برای انجام وجود ندارد.")
        return
    for task in available:
        if task["type"] == "view":
            text = f"👁 تسک سین (ویو)\nلینک: {task['target']}\nپاداش: {task['reward']} سکه"
            keyboard = InlineKeyboardMarkup([[InlineKeyboardButton(
                "تأیید مشاهده", callback_data=f"confirm_view_{task['id']}")]])
        else:
            text = f"👥 تسک ممبر\nآیدی کانال/گروه: {task['target']}\nپاداش: {task['reward']} سکه"
            keyboard = InlineKeyboardMarkup(
                [[InlineKeyboardButton("بررسی عضویت", callback_data=f"check_member_{task['id']}")]])
        await update.message.reply_text(text, reply_markup=keyboard)

# ---------- Application ----------

app_bot = Application.builder().token(TOKEN).build()
app_bot.add_handler(CommandHandler("start", start))
app_bot.add_handler(CommandHandler("register", register))
app_bot.add_handler(CommandHandler("order", order))
app_bot.add_handler(CommandHandler("tasks", tasks_list))
app_bot.add_handler(CommandHandler("balance", balance))
app_bot.add_handler(CallbackQueryHandler(button))
app_bot.add_handler(
    MessageHandler(
        filters.TEXT & ~filters.COMMAND,
        handle_text
    )
)

# ---------- FastAPI ----------

app = FastAPI()

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
