import os
import logging
from datetime import datetime, timedelta, time as dt_time

import gspread
from oauth2client.service_account import ServiceAccountCredentials

from telegram import (
    Update,
    ReplyKeyboardMarkup,
    ReplyKeyboardRemove
)
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    ConversationHandler,
    ContextTypes,
    filters,
)

# === КОНФИГ ===
TOKEN = os.environ['TOKEN']
SPREADSHEET_NAME = 'checkin-alt-bot'
TIMEZONE_OFFSET = 5  # часовой пояс

# === Google Sheets ===
scope = [
    "https://spreadsheets.google.com/feeds",
    "https://www.googleapis.com/auth/drive"
]
creds = ServiceAccountCredentials.from_json_keyfile_name(
    "/etc/secrets/credentials.json", scope
)
client = gspread.authorize(creds)
att_sheet = client.open(SPREADSHEET_NAME).worksheet('Status')
emp_sheet = client.open(SPREADSHEET_NAME).worksheet('Employees')

# === Состояния ConversationHandler ===
(
    NEW_USER,        # вводим ФИО
    CHOOSING_STATUS, # выбираем пункт меню
    TYPING_TIME,     # ввод времени
    TYPING_REASON    # ввод причины
) = range(4)

user_data = {}  # временные данные по пользователю

# === Логирование ===
logging.basicConfig(
    format='%(asctime)s - %(levelname)s - %(message)s', level=logging.INFO
)

def get_today_date() -> str:
    return (datetime.utcnow() + timedelta(hours=TIMEZONE_OFFSET)).strftime('%d.%m.%Y')

# --- Шаг 1: зарегистрировать нового пользователя ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Добро пожаловать! Пожалуйста, представьтесь:\nВведите Фамилию и Имя (на русском):",
        reply_markup=ReplyKeyboardRemove()
    )
    return NEW_USER

async def new_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    chat_id = update.message.chat_id

    # сохраняем ФИО и telegram_id
    emp_sheet.append_row([text, chat_id])
    user_data[chat_id] = {'name': text}

    # показываем главное меню
    keyboard = [
        ['🏢 Уже в офисе'],
        ['🏠 Удалённо', '🎨 На съёмках'],
        ['🌴 В отпуске'],
        ['📋 Список сотрудников']
    ]
    await update.message.reply_text(
        f"Спасибо, {text}! Выберите ваш статус на сегодня:",
        reply_markup=ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
    )
    return CHOOSING_STATUS

# --- Шаг 2: пользователь выбирает статус ---
async def status_chosen(update: Update, context: ContextTypes.DEFAULT_TYPE):
    status = update.message.text
    chat_id = update.message.chat_id
    user_data[chat_id]['status'] = status

    if status == '📋 Список сотрудников':
        return await send_overview(update, context)

    if status == '🏢 Уже в офисе':
        # сразу фиксируем время
        return await save_and_finish(update, time_str=get_today_date())

    if status == '🌴 В отпуске':
        await update.message.reply_text("Укажите диапазон дат отпуска (например: 01.07–09.07):")
        return TYPING_REASON

    # для остальных — спрашиваем время/причину
    prompt = "Во сколько вы на связи или в офисе?" if status in ('🎨 На съёмках', '🏠 Удалённо') else ""
    await update.message.reply_text(prompt)
    return TYPING_TIME

# ввод времени прибытия
async def received_time(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.message.chat_id
    user_data[chat_id]['time'] = update.message.text.strip()
    await update.message.reply_text("Укажите причину (или «нет»)") 
    return TYPING_REASON

# ввод причины или диапазона отпуска
async def received_reason(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.message.chat_id
    user_data[chat_id]['reason'] = update.message.text.strip()
    return await save_and_finish(update)

# сохраняем запись и завершаем разговор
async def save_and_finish(
    update: Update,
    time_str: str = None
) -> int:
    chat_id = update.message.chat_id
    data = user_data[chat_id]
    today = get_today_date()

    # если time_str явно не передан, берём из введённого
    t = time_str or data.get('time', '')
    reason = data.get('reason', '')

    row = [
        today,
        data['name'],
        str(chat_id),
        data['status'],
        t,
        reason,
        ''
    ]
    att_sheet.append_row(row)

    await update.message.reply_text(
        "✅ Записано. Хорошего дня!",
        reply_markup=ReplyKeyboardRemove()
    )
    return ConversationHandler.END

# общий список за сегодня
async def send_overview(update: Update, context: ContextTypes.DEFAULT_TYPE):
    records = att_sheet.get_all_records()
    today = get_today_date()
    lines = []
    for idx, r in enumerate(records, start=1):
        if r['Дата'] == today:
            name = r['Имя']
            st   = r['Статус']
            tm   = r.get('Время', '')
            rsn  = r.get('Причина', '')
            suffix = f"({rsn or tm})" if (rsn or tm) else ""
            lines.append(f"{idx}. {name} — {st} {suffix}")
    text = "📋 Список сотрудников сегодня:\n" + "\n".join(lines) if lines else "Сегодня ещё никто не отметил статус."
    await update.message.reply_text(text, reply_markup=ReplyKeyboardRemove())
    return ConversationHandler.END

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("❌ Отменено.", reply_markup=ReplyKeyboardRemove())
    return ConversationHandler.END

# --- Напоминание в 9:30 по будням ---
async def send_reminder(context: ContextTypes.DEFAULT_TYPE):
    today = get_today_date()
    # список уже отметившихся
    done = {
        r['Telegram ID']
        for r in att_sheet.get_all_records()
        if r['Дата'] == today
    }
    # все сотрудники
    emps = emp_sheet.get_all_records()
    for r in emps:
        tid = str(r['Telegram ID'])
        if tid not in done:
            await context.bot.send_message(
                chat_id=int(tid),
                text="⏰ Пожалуйста, отметьте свой статус на сегодня!"
            )

def main():
    logging.getLogger().setLevel(logging.INFO)
    app = ApplicationBuilder().token(TOKEN).build()

    conv = ConversationHandler(
        entry_points=[CommandHandler("start", start)],
        states={
            NEW_USER:        [MessageHandler(filters.TEXT & ~filters.COMMAND, new_user)],
            CHOOSING_STATUS: [MessageHandler(filters.TEXT & ~filters.COMMAND, status_chosen)],
            TYPING_TIME:     [MessageHandler(filters.TEXT & ~filters.COMMAND, received_time)],
            TYPING_REASON:   [MessageHandler(filters.TEXT & ~filters.COMMAND, received_reason)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )
    app.add_handler(conv)

    # планировщик на будни (пон-пят) в 09:30
    jq = app.job_queue
    jq.run_daily(send_reminder, dt_time(hour=9, minute=30), days=(0,1,2,3,4))

    app.run_polling()

if __name__ == '__main__':
    main()
