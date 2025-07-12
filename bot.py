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
TOKEN = "ваш-токен"

# Keyboard
main_menu = ReplyKeyboardMarkup(
    [
        [KeyboardButton("🏢 Уже в офисе"), KeyboardButton("🏠 Удалённо")],
        [KeyboardButton("🎨 На съёмках"),    KeyboardButton("🌴 В отпуске")],
        [KeyboardButton("📋 Список сотрудников")],
    ],
    resize_keyboard=True,
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Привязка к Google
    creds = ServiceAccountCredentials.from_json_keyfile_name(CREDS_FILE, SCOPE)
    client = gspread.authorize(creds)
    emp_ws = client.open_by_key(SPREADSHEET_ID).worksheet(EMPLOYEE_SHEET)
    # если юзер новый — спросим имя
    rows = emp_ws.get_all_records()
    ids = [str(r["Telegram ID"]) for r in rows]
    if str(update.effective_user.id) not in ids:
        await update.message.reply_text("Пожалуйста, представьтесь: Фамилия Имя (русскими буквами).")
        return STATE_NAME

    await update.message.reply_text(
        "Выбери статус на сегодня:", 
        reply_markup=main_menu
    )
    return STATE_STATUS


async def name_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    creds = ServiceAccountCredentials.from_json_keyfile_name(CREDS_FILE, SCOPE)
    client = gspread.authorize(creds)
    emp_ws = client.open_by_key(SPREADSHEET_ID).worksheet(EMPLOYEE_SHEET)

    fullname = update.message.text.strip()
    emp_ws.append_row([fullname, str(update.effective_user.id)])
    await update.message.reply_text("Записал. Теперь выбери статус:", reply_markup=main_menu)
    return STATE_STATUS


# ——— Тут ваши хендлеры на каждый статус (удалёнка, съёмки, отпуск) ———
# каждый хендлер в конце делает STATE = ConversationHandler.END


async def show_list(update: Update, context: ContextTypes.DEFAULT_TYPE):
    creds = ServiceAccountCredentials.from_json_keyfile_name(CREDS_FILE, SCOPE)
    client = gspread.authorize(creds)
    status_ws = client.open_by_key(SPREADSHEET_ID).worksheet(STATUS_SHEET)

    today = date.today().strftime("%d.%m.%Y")
    records = status_ws.get_all_records()
    lines = [r for r in records if r["Дата"] == today]
    text = "Список сотрудников сегодня:\n\n"
    for i, r in enumerate(lines, 1):
        text += (
            f"{i}. {r['Имя']} — {r['Статус']} "
            f"({r['Причина'] or r['Время']})\n"
        )
    await update.message.reply_text(text)
    return ConversationHandler.END


def build_application():
    return (
        ApplicationBuilder()
        .token(TOKEN)
        .build()
    )


def main():
    app = build_application()

    # ConversationHandler
    conv = ConversationHandler(
        entry_points=[CommandHandler("start", start)],
        states={
            STATE_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, name_handler)],
            STATE_STATUS: [
                MessageHandler(filters.Regex("^🏢 Уже в офисе$"),      handle_office),
                MessageHandler(filters.Regex("^🏠 Удалённо$"),        handle_remote),
                MessageHandler(filters.Regex("^🎨 На съёмках$"),      handle_shoot),
                MessageHandler(filters.Regex("^🌴 В отпуске$"),       handle_vacation),
                MessageHandler(filters.Regex("^📋 Список сотрудников$"), show_list),
            ],
            # и далее переходы для других состояний...
        },
        fallbacks=[CommandHandler("start", start)],
    )
    app.add_handler(conv)

    # Ежедневное напоминание
    remind_time = time(hour=9, minute=30)
    app.job_queue.run_daily(send_reminder, remind_time, days=(0,1,2,3,4))

    app.run_polling()


if __name__ == "__main__":
    main()
