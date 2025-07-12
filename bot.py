# bot.py
import logging
from datetime import date, time
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from telegram import Update, ReplyKeyboardMarkup, KeyboardButton
from telegram.ext import (
    ApplicationBuilder, CommandHandler, MessageHandler,
    ContextTypes, ConversationHandler, filters
)

# Состояния
(STATE_NAME, STATE_STATUS, STATE_REMOTE_REASON, STATE_SHOOT_DETAILS, STATE_VACATION_DATES) = range(5)

# Константы
SCOPE = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
CREDS_FILE = "credentials.json"
SPREADSHEET_ID = "1sqyMu6iLnT1nxDckQO7BjjIhdVwzLsBAA_lib1eoQ_M"
EMPLOYEE_SHEET = "Employees"
STATUS_SHEET = "Status"
TOKEN = "7591731653:AAEdN2b6HiF0jAvEtEP8n5hzhSbl94cu4fg"

main_menu = ReplyKeyboardMarkup([
    [KeyboardButton("🏢 Уже в офисе"), KeyboardButton("🏠 Удалённо")],
    [KeyboardButton("🎨 На съёмках"), KeyboardButton("🌴 В отпуске")],
    [KeyboardButton("🚫 Dayoff"), KeyboardButton("📋 Список сотрудников")],
], resize_keyboard=True)

logging.basicConfig(level=logging.INFO)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    creds = ServiceAccountCredentials.from_json_keyfile_name(CREDS_FILE, SCOPE)
    client = gspread.authorize(creds)
    emp_ws = client.open_by_key(SPREADSHEET_ID).worksheet(EMPLOYEE_SHEET)
    ids = [str(r["Telegram ID"]) for r in emp_ws.get_all_records()]
    if str(update.effective_user.id) not in ids:
        await update.message.reply_text("Как вас зовут? (Фамилия Имя)")
        return STATE_NAME
    await update.message.reply_text("Выберите статус на сегодня:", reply_markup=main_menu)
    return STATE_STATUS

async def name_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    creds = ServiceAccountCredentials.from_json_keyfile_name(CREDS_FILE, SCOPE)
    client = gspread.authorize(creds)
    emp_ws = client.open_by_key(SPREADSHEET_ID).worksheet(EMPLOYEE_SHEET)
    emp_ws.append_row([update.message.text.strip(), str(update.effective_user.id)])
    await update.message.reply_text("Записал. Теперь выберите статус:", reply_markup=main_menu)
    return STATE_STATUS

async def save_status(update, status, detail_key="", detail_value=""):
    creds = ServiceAccountCredentials.from_json_keyfile_name(CREDS_FILE, SCOPE)
    client = gspread.authorize(creds)
    emp_ws = client.open_by_key(SPREADSHEET_ID).worksheet(EMPLOYEE_SHEET)
    stat_ws = client.open_by_key(SPREADSHEET_ID).worksheet(STATUS_SHEET)
    user_id = str(update.effective_user.id)
    name = next((r["Имя"] for r in emp_ws.get_all_records() if str(r["Telegram ID"]) == user_id), None)
    if name:
        today = date.today().strftime("%d.%m.%Y")
        row = [today, name, status, "", ""]
        if detail_key == "Причина":
            row[3] = detail_value
        elif detail_key == "Время":
            row[4] = detail_value
        stat_ws.append_row(row)
    await update.message.reply_text("Статус сохранён. Хорошего дня!")

async def handle_office(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await save_status(update, "Офис", "Время", "с 10:00")
    return ConversationHandler.END

async def handle_remote(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Причина удалёнки?")
    return STATE_REMOTE_REASON

async def remote_reason_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await save_status(update, "Удалённо", "Причина", update.message.text.strip())
    return ConversationHandler.END

async def handle_shoot(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Где съёмка?")
    return STATE_SHOOT_DETAILS

async def shoot_details_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await save_status(update, "Съёмка", "Причина", update.message.text.strip())
    return ConversationHandler.END

async def handle_vacation(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Сколько дней?")
    return STATE_VACATION_DATES

async def vacation_dates_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await save_status(update, "Отпуск", "Причина", update.message.text.strip())
    return ConversationHandler.END

async def handle_dayoff(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await save_status(update, "Dayoff")
    return ConversationHandler.END

async def show_list(update: Update, context: ContextTypes.DEFAULT_TYPE):
    creds = ServiceAccountCredentials.from_json_keyfile_name(CREDS_FILE, SCOPE)
    stat_ws = gspread.authorize(creds).open_by_key(SPREADSHEET_ID).worksheet(STATUS_SHEET)
    today = date.today().strftime("%d.%m.%Y")
    lines = [r for r in stat_ws.get_all_records() if r["Дата"] == today]
    text = "Список сотрудников сегодня:

" + "
".join(
        f"{i+1}. {r['Имя']} — {r['Статус']} ({r['Причина'] or r['Время']})" for i, r in enumerate(lines)
    )
    await update.message.reply_text(text or "Сегодня ещё никто не отметился.")
    return ConversationHandler.END

def main():
    app = ApplicationBuilder().token(TOKEN).build()

    conv_handler = ConversationHandler(
        entry_points=[CommandHandler("start", start)],
        states={
            STATE_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, name_handler)],
            STATE_STATUS: [
                MessageHandler(filters.Regex("^🏢 Уже в офисе$"), handle_office),
                MessageHandler(filters.Regex("^🏠 Удалённо$"), handle_remote),
                MessageHandler(filters.Regex("^🎨 На съёмках$"), handle_shoot),
                MessageHandler(filters.Regex("^🌴 В отпуске$"), handle_vacation),
                MessageHandler(filters.Regex("^🚫 Dayoff$"), handle_dayoff),
                MessageHandler(filters.Regex("^📋 Список сотрудников$"), show_list),
            ],
            STATE_REMOTE_REASON: [MessageHandler(filters.TEXT & ~filters.COMMAND, remote_reason_handler)],
            STATE_SHOOT_DETAILS: [MessageHandler(filters.TEXT & ~filters.COMMAND, shoot_details_handler)],
            STATE_VACATION_DATES: [MessageHandler(filters.TEXT & ~filters.COMMAND, vacation_dates_handler)],
        },
        fallbacks=[CommandHandler("start", start)],
    )

    app.add_handler(conv_handler)
    app.run_polling()

if __name__ == "__main__":
    main()
