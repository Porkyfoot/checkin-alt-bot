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
att_sheet = client.open(SPREADSHEET_NAME).sheet1
emp_sheet = client.open(SPREADSHEET_NAME).worksheet('Employees')

# === Состояния ConversationHandler ===
(
    NEW_USER,
    CHOOSING_STATUS,
    TYPING_TIME,
    TYPING_REASON
) = range(4)

user_data = {}

logging.basicConfig(
    format='%(asctime)s - %(levelname)s - %(message)s', level=logging.INFO
)

def get_today_date() -> str:
    return (datetime.utcnow() + timedelta(hours=TIMEZONE_OFFSET)).strftime('%d.%m.%Y')

def is_registered(chat_id: int) -> bool:
    records = emp_sheet.get_all_records()
    return any(str(chat_id) == str(r.get('Telegram ID')) for r in records)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.message.chat_id

    if is_registered(chat_id):
        records = emp_sheet.get_all_records()
        user = next(r for r in records if str(r.get('Telegram ID')) == str(chat_id))
        user_data[chat_id] = {'name': user['Имя']}

        today = get_today_date()
        all_att = att_sheet.get_all_records()
        if any(str(chat_id) == str(r['Telegram ID']) and r['Дата'] == today for r in all_att):
            await update.message.reply_text("⚠️ Вы уже отметили статус сегодня.")
            return ConversationHandler.END

        keyboard = [
            ['🏢 Уже в офисе', '⏰ Задерживаюсь'],
            ['🏠 Удалённо', '🎨 На съёмках'],
            ['🌴 В отпуске', '🛌 Dayoff'],
            ['📋 Список сотрудников']
        ]
        await update.message.reply_text(
            f"Добро пожаловать снова, {user['Имя']}!\nВыберите статус на сегодня:",
            reply_markup=ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
        )
        return CHOOSING_STATUS

    await update.message.reply_text(
        "Добро пожаловать! Пожалуйста, представьтесь:\nВведите Фамилию и Имя (на русском):",
        reply_markup=ReplyKeyboardRemove()
    )
    return NEW_USER

async def new_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    chat_id = update.message.chat_id

    if is_registered(chat_id):
        await update.message.reply_text("⚠️ Вы уже зарегистрированы.")
        return ConversationHandler.END

    emp_sheet.append_row([text, chat_id])
    user_data[chat_id] = {'name': text}

    keyboard = [
        ['🏢 Уже в офисе', '⏰ Задерживаюсь'],
        ['🏠 Удалённо', '🎨 На съёмках'],
        ['🌴 В отпуске', '🛌 Dayoff'],
        ['📋 Список сотрудников']
    ]
    await update.message.reply_text(
        f"Спасибо, {text}! Выберите ваш статус на сегодня:",
        reply_markup=ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
    )
    return CHOOSING_STATUS

async def status_chosen(update: Update, context: ContextTypes.DEFAULT_TYPE):
    status = update.message.text
    chat_id = update.message.chat_id
    user_data[chat_id]['status'] = status

    if status == '📋 Список сотрудников':
        return await send_overview(update, context)

    if status == '🏢 Уже в офисе':
        return await save_and_finish(update, time_str=get_today_date())

    if status == '🌴 В отпуске':
        await update.message.reply_text("Укажите диапазон дат отпуска (например: 01.07–09.07):")
        return TYPING_REASON

    if status == '⏰ Задерживаюсь':
        await update.message.reply_text("Во сколько вы будете в офисе?")
        return TYPING_TIME

    prompt = "Во сколько вы на связи или в офисе?" if status in ('🎨 На съёмках', '🏠 Удалённо') else ""
    await update.message.reply_text(prompt)
    return TYPING_TIME

async def received_time(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.message.chat_id
    user_data[chat_id]['time'] = update.message.text.strip()

    if user_data[chat_id]['status'] == '⏰ Задерживаюсь':
        await update.message.reply_text("По какой причине вы задерживаетесь?")
    else:
        await update.message.reply_text("Укажите причину (или «нет»)") 
    return TYPING_REASON

async def received_reason(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.message.chat_id
    user_data[chat_id]['reason'] = update.message.text.strip()
    return await save_and_finish(update)

async def save_and_finish(update: Update, time_str: str = None) -> int:
    chat_id = update.message.chat_id
    data = user_data[chat_id]
    today = get_today_date()

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

async def send_overview(update: Update, context: ContextTypes.DEFAULT_TYPE):
    records = att_sheet.get_all_records()
    today = get_today_date()
    lines = []
    for idx, r in enumerate(records, start=1):
        if r['Дата'] == today:
            name = r['Имя']
            st = r['Статус']
            tm = r.get('Время', '')
            rsn = r.get('Причина', '')
            suffix = f"({rsn or tm})" if (rsn or tm) else ""
            lines.append(f"{idx}. {name} — {st} {suffix}")
    text = "📋 Список сотрудников сегодня:\n" + "\n".join(lines) if lines else "Сегодня ещё никто не отметил статус."
    await update.message.reply_text(text, reply_markup=ReplyKeyboardRemove())
    return ConversationHandler.END

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("❌ Отменено.", reply_markup=ReplyKeyboardRemove())
    return ConversationHandler.END

async def send_reminder(context: ContextTypes.DEFAULT_TYPE):
    today = get_today_date()
    done = {
        r['Telegram ID']
        for r in att_sheet.get_all_records()
        if r['Дата'] == today
    }
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
            NEW_USER: [MessageHandler(filters.TEXT & ~filters.COMMAND, new_user)],
            CHOOSING_STATUS: [MessageHandler(filters.TEXT & ~filters.COMMAND, status_chosen)],
            TYPING_TIME: [MessageHandler(filters.TEXT & ~filters.COMMAND, received_time)],
            TYPING_REASON: [MessageHandler(filters.TEXT & ~filters.COMMAND, received_reason)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )
    app.add_handler(conv)

    jq = app.job_queue
    jq.run_daily(send_reminder, dt_time(hour=9, minute=30), days=(0,1,2,3,4))

    app.run_polling()

if __name__ == '__main__':
    main()
