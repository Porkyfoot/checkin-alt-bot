# bot.py
import logging
from datetime import time, date
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from telegram import ReplyKeyboardMarkup, KeyboardButton, Update
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    ConversationHandler,
    ContextTypes,
    filters,
)

# --- константы состояний разговора ---
(
    STATE_NAME,
    STATE_STATUS,
    STATE_REMOTE_REASON,
    STATE_SHOOT_DETAILS,
    STATE_VACATION_DATES,
) = range(5)

# Google-сборы
SCOPE = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
CREDS_FILE = "/etc/secrets/credentials.json"
SPREADSHEET_ID = "ваш-ID-таблицы"
EMPLOYEE_SHEET = "Employees"
STATUS_SHEET = "Status"

# Telegram
TOKEN = "7591731653:AAEdN2b6HiF0jAvEtEP8n5hzhSbl94cu4fg"

# Keyboard
main_menu = ReplyKeyboardMarkup(
    [
        [KeyboardButton("🏢 Уже в офисе"), KeyboardButton("🏠 Удалённо")],
        [KeyboardButton("🎨 На съёмках"), KeyboardButton("🌴 В отпуске")],
        [KeyboardButton("📋 Список сотрудников")],
    ],
    resize_keyboard=True,
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    creds = ServiceAccountCredentials.from_json_keyfile_name(CREDS_FILE, SCOPE)
    client = gspread.authorize(creds)
    emp_ws = client.open_by_key(SPREADSHEET_ID).worksheet(EMPLOYEE_SHEET)

    rows = emp_ws.get_all_records()
    ids = [str(r.get("Telegram ID", "")).strip() for r in rows]

    current_id = str(update.effective_user.id).strip()
    logger.info(f"User ID: {current_id}, existing IDs: {ids}")

    if current_id not in ids:
        await update.message.reply_text("Пожалуйста, представьтесь: Фамилия Имя (русскими буквами).")
        return STATE_NAME

    await update.message.reply_text("Выбери статус на сегодня:", reply_markup=main_menu)
    return STATE_STATUS


async def name_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    creds = ServiceAccountCredentials.from_json_keyfile_name(CREDS_FILE, SCOPE)
    client = gspread.authorize(creds)
    emp_ws = client.open_by_key(SPREADSHEET_ID).worksheet(EMPLOYEE_SHEET)

    fullname = update.message.text.strip()
    user_id = str(update.effective_user.id).strip()

    emp_ws.append_row([fullname, user_id])
    await update.message.reply_text("Записал. Теперь выбери статус:", reply_markup=main_menu)
    return STATE_STATUS


async def handle_office(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await save_status(update, "Офис", "")
    await update.message.reply_text("Отметил — вы в офисе.")
    return ConversationHandler.END


async def handle_remote(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Напиши кратко причину удалёнки (болею, дома жду доставку и т.п.)")
    return STATE_REMOTE_REASON


async def remote_reason_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    reason = update.message.text.strip()
    await save_status(update, "Удалённо", reason)
    await update.message.reply_text("Отметил — вы на удалёнке.")
    return ConversationHandler.END


async def handle_shoot(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Напиши кратко: где и во сколько съёмка?")
    return STATE_SHOOT_DETAILS


async def shoot_details_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    details = update.message.text.strip()
    await save_status(update, "Съёмка", details)
    await update.message.reply_text("Отметил — вы на съёмке.")
    return ConversationHandler.END


async def handle_vacation(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Напиши даты отпуска (например: 15.07 — 25.07):")
    return STATE_VACATION_DATES


async def vacation_dates_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    dates = update.message.text.strip()
    await save_status(update, "Отпуск", dates)
    await update.message.reply_text("Хорошего отдыха! Отметил.")
    return ConversationHandler.END


async def save_status(update: Update, status: str, note: str):
    creds = ServiceAccountCredentials.from_json_keyfile_name(CREDS_FILE, SCOPE)
    client = gspread.authorize(creds)
    status_ws = client.open_by_key(SPREADSHEET_ID).worksheet(STATUS_SHEET)
    emp_ws = client.open_by_key(SPREADSHEET_ID).worksheet(EMPLOYEE_SHEET)

    rows = emp_ws.get_all_records()
    user_id = str(update.effective_user.id).strip()
    name = next((r["Имя"] for r in rows if str(r.get("Telegram ID", "")).strip() == user_id), "Неизвестный")

    today = date.today().strftime("%d.%m.%Y")
    status_ws.append_row([today, name, status, note])


async def show_list(update: Update, context: ContextTypes.DEFAULT_TYPE):
    creds = ServiceAccountCredentials.from_json_keyfile_name(CREDS_FILE, SCOPE)
    client = gspread.authorize(creds)
    status_ws = client.open_by_key(SPREADSHEET_ID).worksheet(STATUS_SHEET)

    today = date.today().strftime("%d.%m.%Y")
    records = status_ws.get_all_records()
    lines = [r for r in records if r["Дата"] == today]
    text = "Список сотрудников сегодня:\n\n"
    for i, r in enumerate(lines, 1):
        note = r.get("Причина", "") or r.get("Время", "") or ""
        text += f"{i}. {r['Имя']} — {r['Статус']} ({note})\n"
    await update.message.reply_text(text)
    return ConversationHandler.END


async def send_reminder(context: ContextTypes.DEFAULT_TYPE):
    creds = ServiceAccountCredentials.from_json_keyfile_name(CREDS_FILE, SCOPE)
    client = gspread.authorize(creds)
    emp_ws = client.open_by_key(SPREADSHEET_ID).worksheet(EMPLOYEE_SHEET)
    rows = emp_ws.get_all_records()

    for r in rows:
        try:
            uid = int(r["Telegram ID"])
            await context.bot.send_message(chat_id=uid, text="Доброе утро! Не забудь отметить свой статус на сегодня 😉", reply_markup=main_menu)
        except Exception as e:
            logger.error(f"Не смог отправить сообщение {r}: {e}")


def build_application():
    return ApplicationBuilder().token(TOKEN).build()


def main():
    app = build_application()

    conv = ConversationHandler(
        entry_points=[CommandHandler("start", start)],
        states={
            STATE_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, name_handler)],
            STATE_STATUS: [
                MessageHandler(filters.Regex("^🏢 Уже в офисе$"), handle_office),
                MessageHandler(filters.Regex("^🏠 Удалённо$"), handle_remote),
                MessageHandler(filters.Regex("^🎨 На съёмках$"), handle_shoot),
                MessageHandler(filters.Regex("^🌴 В отпуске$"), handle_vacation),
                MessageHandler(filters.Regex("^📋 Список сотрудников$"), show_list),
            ],
            STATE_REMOTE_REASON: [MessageHandler(filters.TEXT & ~filters.COMMAND, remote_reason_handler)],
            STATE_SHOOT_DETAILS: [MessageHandler(filters.TEXT & ~filters.COMMAND, shoot_details_handler)],
            STATE_VACATION_DATES: [MessageHandler(filters.TEXT & ~filters.COMMAND, vacation_dates_handler)],
        },
        fallbacks=[CommandHandler("start", start)],
    )
    app.add_handler(conv)

    remind_time = time(hour=9, minute=30)
    app.job_queue.run_daily(send_reminder, remind_time, days=(0, 1, 2, 3, 4))

    app.run_polling()


if __name__ == "__main__":
    main()
