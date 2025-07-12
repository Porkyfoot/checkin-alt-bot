import os
import logging
import gspread
from datetime import datetime, timedelta
from oauth2client.service_account import ServiceAccountCredentials
from telegram import Update, ReplyKeyboardMarkup, ReplyKeyboardRemove
from telegram.ext import (
    ApplicationBuilder, CommandHandler, MessageHandler,
    ConversationHandler, ContextTypes, filters
)

# CONFIG
TOKEN = os.environ["TOKEN"]
SPREADSHEET_NAME = "Ежедневные Отметки"
TIMEZONE_OFFSET = 5

# Google Sheets
scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
creds = ServiceAccountCredentials.from_json_keyfile_name("/etc/secrets/credentials.json", scope)
client = gspread.authorize(creds)
sheet = client.open(SPREADSHEET_NAME).sheet1

# States
CHOOSING_STATUS, TYPING_TIME, TYPING_REASON = range(3)
user_data_temp = {}

# Logging
logging.basicConfig(format="%(asctime)s - %(levelname)s - %(message)s", level=logging.INFO)

def get_today_date():
    return (datetime.utcnow() + timedelta(hours=TIMEZONE_OFFSET)).strftime("%d.%m.%Y")

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Загрузка меню...", reply_markup=ReplyKeyboardRemove())

    keyboard = [
        ["🏢 Уже в офисе"],
        ["🏠 Удалённо", "🎬 На съёмках"],
        ["🌴 В отпуске"],
        ["📋 Список сотрудников"]
    ]
    markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
    await update.message.reply_text("Привет! Где ты сегодня работаешь?", reply_markup=markup)
    return CHOOSING_STATUS

async def status_chosen(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    user_id = update.message.from_user.id
    name = update.message.from_user.full_name

    if text == "📋 Список сотрудников":
        await send_sheet_data(update)
        return ConversationHandler.END

    user_data_temp[user_id] = {
        "name": name,
        "status": text,
        "telegram_id": user_id
    }

    if text == "🌴 В отпуске":
        await update.message.reply_text("Укажи даты отпуска (например: 11.07–20.07)")
        return TYPING_REASON

    elif text == "🏢 Уже в офисе":
        return await save_and_thank(update, user_id, "")

    else:
        await update.message.reply_text("Во сколько будешь на связи или в офисе?")
        return TYPING_TIME

async def received_time(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    user_data_temp[user_id]["time"] = update.message.text
    await update.message.reply_text("Если есть причина задержки — напиши. Если нет — напиши 'нет'")
    return TYPING_REASON

async def received_reason(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    reason = update.message.text
    return await save_and_thank(update, user_id, reason)

async def save_and_thank(update, user_id, reason):
    data = user_data_temp[user_id]
    today = get_today_date()
    row = [
        today,
        data["name"],
        str(data["telegram_id"]),
        data["status"],
        data.get("time", ""),
        reason,
        ""
    ]
    sheet.append_row(row)
    await update.message.reply_text("✅ Записано. Спасибо!")
    return ConversationHandler.END

async def send_sheet_data(update: Update):
    try:
        records = sheet.get_all_records()
        today = get_today_date()
        text = "📋 Сегодня отметились:\n\n"
        count = 0
        for row in records:
            if row.get("Дата") == today:
                name = row.get("Имя", "—")
                status = row.get("Статус", "")
                time = row.get("Время", "")
                text += f"• {name} — {status} ({time})\n"
                count += 1
        if count == 0:
            text = "Сегодня ещё никто не отметился."
        await update.message.reply_text(text)
    except Exception as e:
        await update.message.reply_text(f"Ошибка чтения таблицы: {e}")

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Окей, отменено.")
    return ConversationHandler.END

def main():
    app = ApplicationBuilder().token(TOKEN).build()

    conv = ConversationHandler(
        entry_points=[CommandHandler("start", start)],
        states={
            CHOOSING_STATUS: [MessageHandler(filters.TEXT & ~filters.COMMAND, status_chosen)],
            TYPING_TIME: [MessageHandler(filters.TEXT & ~filters.COMMAND, received_time)],
            TYPING_REASON: [MessageHandler(filters.TEXT & ~filters.COMMAND, received_reason)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )

    app.add_handler(conv)
    app.run_polling()

if __name__ == "__main__":
    main()
