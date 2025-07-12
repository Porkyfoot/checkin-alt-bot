import os
import logging
from datetime import datetime, timedelta

import gspread
from oauth2client.service_account import ServiceAccountCredentials
from telegram import Update, ReplyKeyboardMarkup, ReplyKeyboardRemove
from telegram.ext import (
    ApplicationBuilder, CommandHandler, MessageHandler,
    ConversationHandler, ContextTypes, filters
)

# --- CONFIG ---
TOKEN = os.environ['TOKEN']
SPREADSHEET_NAME = 'Ежедневные Отметки'
TIMEZONE_OFFSET = 5  # for Almaty

# --- Google Sheets Setup ---
scope = [
    "https://spreadsheets.google.com/feeds",
    "https://www.googleapis.com/auth/drive"
]
creds = ServiceAccountCredentials.from_json_keyfile_name(
    "/etc/secrets/credentials.json", scope
)
client = gspread.authorize(creds)
sheet = client.open(SPREADSHEET_NAME).sheet1

# --- States ---
CHOOSING_STATUS, TYPING_TIME, TYPING_REASON = range(3)
user_data_temp = {}

# --- Logging ---
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)


def get_today_date():
    return (datetime.utcnow() + timedelta(hours=TIMEZONE_OFFSET)).strftime('%d.%m.%Y')


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # главное меню статусов
    keyboard = [
        ['🏢 Уже в офисе', '⏰ Задерживаюсь'],
        ['🏠 Удалённо', '🎨 На съёмках'],
        ['🌴 В отпуске', '🛌 DayOff'],
        ['📋 Список сотрудников']
    ]
    markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
    await update.message.reply_text(
        "Привет! Где ты сегодня работаешь?", reply_markup=markup
    )
    return CHOOSING_STATUS


async def status_chosen(update: Update, context: ContextTypes.DEFAULT_TYPE):
    status = update.message.text
    user_id = update.message.from_user.id
    name = update.message.from_user.full_name

    if status == '📋 Список сотрудников':
        await send_sheet_data(update)
        return ConversationHandler.END

    # сохраняем базовые данные
    user_data_temp[user_id] = {'name': name, 'status': status, 'telegram_id': user_id}

    # обработка каждого статуса
    if status == '🌴 В отпуске':
        await update.message.reply_text(
            "Укажи даты отпуска (например: 11.07–20.07)"
        )
        return TYPING_REASON
    elif status == '🛌 DayOff':
        # сразу сохраняем DayOff без вопросов
        return await save_and_thank(update, user_id, "")
    elif status == '🏢 Уже в офисе':
        # фиксируем текущее время как время прихода
        user_data_temp[user_id]['time'] = (
            datetime.utcnow() + timedelta(hours=TIMEZONE_OFFSET)
        ).strftime('%H:%M')
        return await save_and_thank(update, user_id, "")
    elif status == '⏰ Задерживаюсь':
        await update.message.reply_text(
            "Когда ты будешь на работе? (например: 10:30)"
        )
        return TYPING_TIME
    elif status == '🏠 Удалённо':
        await update.message.reply_text(
            "По какой причине ты работаешь удалённо?"
        )
        return TYPING_REASON
    else:
        # съемки
        await update.message.reply_text(
            "Опиши, пожалуйста, что за съемки и время начала"
        )
        return TYPING_REASON


async def received_time(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    user_data_temp[user_id]['time'] = update.message.text
    # после времени просим причину, если статус не задерживаюсь
    await update.message.reply_text(
        "Если нужно добавить детали — напиши. Иначе напиши 'нет'"
    )
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
        data['name'],
        str(data['telegram_id']),
        data['status'],
        data.get('time', ''),
        reason,
        ''
    ]
    sheet.append_row(row)
    await update.message.reply_text(
        "✅ Записано. Спасибо!", reply_markup=ReplyKeyboardRemove()
    )
    return ConversationHandler.END


async def send_sheet_data(update: Update):
    try:
        records = sheet.get_all_records()
        if not records:
            await update.message.reply_text("Таблица пока пуста.")
            return

        today = get_today_date()
        text = "🗂 Список сотрудников сегодня:\n"
        for idx, row in enumerate(records, 1):
            if row.get('Дата') == today:
                name = row.get('Имя', '—')
                status = row.get('Статус', '')
                time = row.get('Время', '')
                extra = f" ({time})" if time else ''
                text += f"{idx}. {name} — {status}{extra}\n"

        await update.message.reply_text(text or "Сегодня ещё никто не отметился.")
    except Exception as e:
        await update.message.reply_text(f"Ошибка чтения таблицы: {e}")


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Окей, отменено.", reply_markup=ReplyKeyboardRemove()
    )
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


if __name__ == '__main__':
    main()
