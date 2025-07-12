import os
import logging
from datetime import datetime, time
from typing import Dict

import gspread
from oauth2client.service_account import ServiceAccountCredentials
from telegram import (
    Update,
    ReplyKeyboardMarkup,
    KeyboardButton,
)
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    ConversationHandler,
    ContextTypes,
    filters,
)

# ——— Настройка логирования ———
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)

# ——— Константы состояний для ConversationHandler ———
ASK_NAME, CHOOSE_STATUS, ASK_DETAILS = range(3)

# ——— Клавиатура со статусами ———
KEYBOARD = [
    [KeyboardButton("Уже в офисе"), KeyboardButton("Удалённо")],
    [KeyboardButton("Задерживаюсь"), KeyboardButton("DayOff")],
    [KeyboardButton("В отпуске"), KeyboardButton("На съёмках")],
]
MARKUP = ReplyKeyboardMarkup(KEYBOARD, one_time_keyboard=True, resize_keyboard=True)

# ——— Читаем переменные окружения ———
SPREADSHEET_ID = os.environ["SPREADSHEET_ID"]
SHEET_EMPLOYEES = "Employees"
SHEET_DATA = "Лист1"

TOKEN = os.environ["TOKEN"]
CRED_PATH = os.environ["SECRET_JSON"]  # например "/etc/secrets/credentials.json"

# ——— Подключаемся к Google Sheets ———
scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
creds = ServiceAccountCredentials.from_json_keyfile_name(CRED_PATH, scope)
gc = gspread.authorize(creds)
sh = gc.open_by_key(SPREADSHEET_ID)
ws_emp = sh.worksheet(SHEET_EMPLOYEES)
ws_data = sh.worksheet(SHEET_DATA)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Первый хендлер: спрашиваем имя, если не знаем."""
    user_id = str(update.effective_user.id)
    records = ws_emp.get_all_records()
    # ищем Telegram ID в таблице
    for row in records:
        if str(row.get("Telegram ID", "")) == user_id:
            context.user_data["name"] = row["Имя"]
            await update.message.reply_text(
                f"Привет, {row['Имя']}! Выбирай статус:", reply_markup=MARKUP
            )
            return CHOOSE_STATUS

    # если не нашли — спрашиваем имя
    await update.message.reply_text("Как вас зовут? Введите имя:")
    return ASK_NAME


async def ask_status(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Сохраняем имя и переходим к выбору статуса."""
    name = update.message.text.strip()
    context.user_data["name"] = name
    # записываем в Employees
    ws_emp.append_row([name, str(update.effective_user.id)])
    await update.message.reply_text(f"Спасибо, {name}! Теперь выбери статус:", reply_markup=MARKUP)
    return CHOOSE_STATUS


async def save_status(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Сохраняем выбранный статус и, если нужно, спрашиваем детали."""
    status = update.message.text.strip()
    context.user_data["status"] = status

    # если нужно детали или причину
    if status in ("Задерживаюсь", "Удалённо", "В отпуске", "На съёмках"):
        prompt = {
            "Задерживаюсь": "Во сколько будешь в офисе и по какой причине?",
            "Удалённо": "По какой причине работаешь удалённо?",
            "В отпуске": "Введите даты отпуска в формате с DD.MM по DD.MM",
            "На съёмках": "Клиент и детали съёмок?",
        }[status]
        await update.message.reply_text(prompt)
        return ASK_DETAILS

    # если DayOff — сразу пишем
    await record_and_thanks(update, context, details="")
    return ConversationHandler.END


async def ask_details(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Сохраняем детали и финализируем запись."""
    details = update.message.text.strip()
    await record_and_thanks(update, context, details)
    return ConversationHandler.END


async def record_and_thanks(
    update: Update, context: ContextTypes.DEFAULT_TYPE, details: str
) -> None:
    """Записываем строку в Google Sheet и благодарим пользователя."""
    name = context.user_data["name"]
    status = context.user_data["status"]
    date_str = datetime.now().strftime("%d.%m.%Y")
    # в колонку Причина пишем только для удалёнки и задержки
    reason = details if status in ("Задерживаюсь", "Удалённо") else ""
    # в колонку Детали: для отпуска и съёмок — туда же
    det = details if status in ("В отпуске", "На съёмках") else details.split()[0] if status=="Задерживаюсь" else ""
    # собираем row
    row = [date_str, name, str(update.effective_user.id), status, det, reason]
    ws_data.append_row(row)
    await update.message.reply_text("Готово! Статус записан. Спасибо 🙏")


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Отмена диалога."""
    await update.message.reply_text("ОК, отмена. Начнём сначала — /start")
    return ConversationHandler.END


def main() -> None:
    app = ApplicationBuilder().token(TOKEN).build()

    conv = ConversationHandler(
        entry_points=[CommandHandler("start", start)],
        states={
            ASK_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, ask_status)],
            CHOOSE_STATUS: [MessageHandler(filters.TEXT & ~filters.COMMAND, save_status)],
            ASK_DETAILS: [MessageHandler(filters.TEXT & ~filters.COMMAND, ask_details)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )

    app.add_handler(conv)
    app.run_polling()


if __name__ == "__main__":
    main()
