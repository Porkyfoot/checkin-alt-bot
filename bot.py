#!/usr/bin/env python3
import os
import logging
from datetime import datetime
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from telegram import Update, ReplyKeyboardMarkup, ReplyKeyboardRemove
from telegram.ext import (
    ApplicationBuilder, ContextTypes,
    ConversationHandler, CommandHandler, MessageHandler, filters
)

# Логирование
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO
)
logger = logging.getLogger(__name__)

# Google Sheets авторизация
scope = [
    "https://spreadsheets.google.com/feeds",
    "https://www.googleapis.com/auth/drive",
]
creds = ServiceAccountCredentials.from_json_keyfile_name(
    '/etc/secrets/credentials.json', scope
)
gc = gspread.authorize(creds)

# Настройки таблицы
SPREADSHEET = os.getenv("SPREADSHEET_NAME", "MyStatusBot")
EMP_SHEET = os.getenv("EMP_SHEET_NAME", "Employees")
STATUS_SHEET = os.getenv("STATUS_SHEET_NAME", "Statuses")

employees_ws = gc.open(SPREADSHEET).worksheet(EMP_SHEET)
status_ws = gc.open(SPREADSHEET).worksheet(STATUS_SHEET)

# Состояния беседы
(
    ASK_NAME,
    CHOOSING,
    ASK_LATE_TIME,
    ASK_LATE_REASON,
    ASK_REMOTE_REASON,
    ASK_VACATION_DATES,
    ASK_SHOOTING_DETAILS,
) = range(7)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    uid = update.effective_user.id
    records = employees_ws.get_all_records()
    # Если нет в списке — спрашиваем имя
    if not any(str(r.get("Telegram ID")) == str(uid) for r in records):
        await update.message.reply_text(
            "Привет! Как вас зовут?",
            reply_markup=ReplyKeyboardRemove()
        )
        return ASK_NAME
    # Иначе сразу меню статусов
    return await ask_status(update, context)

async def ask_status(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    keyboard = [
        ["⏰ Задерживаюсь", "🏢 Удаленно"],
        ["🌴 В отпуске", "🎨 На съёмках", "🛌 DayOff"],
    ]
    await update.message.reply_text(
        "Выбери статус:",
        reply_markup=ReplyKeyboardMarkup(keyboard, one_time_keyboard=True)
    )
    return CHOOSING

async def save_name(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    name = update.message.text.strip()
    uid = update.effective_user.id
    date = datetime.now().strftime("%d.%m.%Y")
    # Сохраняем в Employees (Date, Name, Telegram ID)
    employees_ws.append_row([date, name, uid])
    await update.message.reply_text(f"Спасибо, {name}! Теперь выберите статус.")
    return await ask_status(update, context)

async def handle_choice(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    choice = update.message.text
    context.user_data['status'] = choice
    # Обработка каждого варианта
    if choice == "⏰ Задерживаюсь":
        await update.message.reply_text(
            "Во сколько планируешь быть в офисе?",
            reply_markup=ReplyKeyboardRemove()
        )
        return ASK_LATE_TIME
    if choice == "🏢 Удаленно":
        await update.message.reply_text(
            "По какой причине работаешь удаленно?",
            reply_markup=ReplyKeyboardRemove()
        )
        return ASK_REMOTE_REASON
    if choice == "🌴 В отпуске":
        await update.message.reply_text(
            "Укажи даты отпуска (например: с 07.09 до 12.09)",
            reply_markup=ReplyKeyboardRemove()
        )
        return ASK_VACATION_DATES
    if choice == "🎨 На съёмках":
        await update.message.reply_text(
            "Что за съёмки? (клиент/детали)",
            reply_markup=ReplyKeyboardRemove()
        )
        return ASK_SHOOTING_DETAILS
    if choice == "🛌 DayOff":
        # Сразу записываем и выходим
        await record_status(update, context, details="", reason="")
        return ConversationHandler.END
    # Если непонятно — заново
    await update.message.reply_text("Пожалуйста, выбери статус из меню.")
    return CHOOSING

async def late_time(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data['late_time'] = update.message.text.strip()
    await update.message.reply_text("Почему задерживаешься?")
    return ASK_LATE_REASON

async def late_reason(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    reason = update.message.text.strip()
    details = context.user_data.get('late_time', '')
    await record_status(update, context, details=details, reason=reason)
    return ConversationHandler.END

async def remote_reason(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    reason = update.message.text.strip()
    await record_status(update, context, details="", reason=reason)
    return ConversationHandler.END

async def vacation_dates(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    details = update.message.text.strip()
    await record_status(update, context, details=details, reason="")
    return ConversationHandler.END

async def shooting_details(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    details = update.message.text.strip()
    await record_status(update, context, details=details, reason="")
    return ConversationHandler.END

async def record_status(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    details: str,
    reason: str
) -> None:
    user = update.effective_user
    uid = user.id
    # Ищем имя в Employees
    name = None
    for r in employees_ws.get_all_records():
        if str(r.get("Telegram ID")) == str(uid):
            name = r.get("Name")
            break
    if not name:
        name = user.full_name
    status = context.user_data['status']
    date = datetime.now().strftime("%d.%m.%Y")
    # Запись в таблицу Statuses (Date, Name, Telegram ID, Status, Details, Reason)
    status_ws.append_row([date, name, uid, status, details, reason])
    await update.message.reply_text(
        "Ваш статус сохранен!",
        reply_markup=ReplyKeyboardRemove()
    )

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await update.message.reply_text(
        "Отменено.", reply_markup=ReplyKeyboardRemove()
    )
    return ConversationHandler.END

# /today — вывод статусов за сегодня
async def today(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    date = datetime.now().strftime("%d.%m.%Y")
    recs = status_ws.get_all_records()
    lines = []
    i = 1
    for r in recs:
        if r.get("Date") == date:
            name = r.get("Name")
            st = r.get("Status")
            det = r.get("Details", "")
            rea = r.get("Reason", "")
            note = ""
            if st == "⏰ Задерживаюсь":
                note = f"({det}, {rea})"
            elif st == "🏢 Удаленно":
                note = f"({rea})"
            elif st == "🌴 В отпуске":
                note = f"({det})"
            elif st == "🎨 На съёмках":
                note = f"({det})"
            lines.append(f"{i}. {name} — {st} {note}")
            i += 1
    text = ("Список сотрудников сегодня:\n" + "\n".join(lines)) if lines else "Записей на сегодня нет."
    await update.message.reply_text(text)


def main() -> None:
    token = os.getenv("BOT_TOKEN")
    app = ApplicationBuilder().token(token).build()

    conv = ConversationHandler(
        entry_points=[CommandHandler("start", start)],
        states={
            ASK_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, save_name)],
            CHOOSING: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_choice)],
            ASK_LATE_TIME: [MessageHandler(filters.TEXT & ~filters.COMMAND, late_time)],
            ASK_LATE_REASON: [MessageHandler(filters.TEXT & ~filters.COMMAND, late_reason)],
            ASK_REMOTE_REASON: [MessageHandler(filters.TEXT & ~filters.COMMAND, remote_reason)],
            ASK_VACATION_DATES: [MessageHandler(filters.TEXT & ~filters.COMMAND, vacation_dates)],
            ASK_SHOOTING_DETAILS: [MessageHandler(filters.TEXT & ~filters.COMMAND, shooting_details)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )

    app.add_handler(conv)
    app.add_handler(CommandHandler("today", today))

    app.run_polling()

if __name__ == "__main__":
    main()
