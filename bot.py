# -*- coding: utf-8 -*-
import os
import logging
from datetime import datetime, time, date, timedelta
import re
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from telegram import Update, ReplyKeyboardMarkup, ReplyKeyboardRemove
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    ConversationHandler,
    MessageHandler,
    filters,
)

# --- настройка логирования ---
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# --- константы состояний для ConversationHandler ---
CHOOSE, REMOTE_REASON, VACATION_DATES, SHOOT_DETAILS, DELAY_TIME, DELAY_REASON = range(6)

# --- клавиатура выбора статуса ---
MENU = [
    ['⏰ Задерживаюсь', '🛌 DayOff'],
    ['🌴 В отпуске', '🎨 На съёмках'],
    ['🏢 Удаленно']
]

def connect_sheet():
    scope = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
    creds_json = os.environ['GOOGLE_CREDENTIALS_JSON']
    creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_json, scope)
    client = gspread.authorize(creds)
    sh = client.open(os.environ['SPREADSHEET_NAME'])
    ws = sh.worksheet(os.environ['SHEET_NAME'])
    return ws

def record_status(ws, update: Update, status, details, reason):
    now = datetime.now().strftime('%d.%m.%Y')
    user = update.effective_user
    row = [now, user.full_name, user.id, status, details or '', reason or '']
    ws.append_row(row)

# --- начало диалога ---
def start(update: Update, context):
    update.message.reply_text(
        'Выбери статус:',
        reply_markup=ReplyKeyboardMarkup(MENU, one_time_keyboard=True, resize_keyboard=True)
    )
    return CHOOSE

# --- выбор опции ---
def choose(update: Update, context):
    text = update.message.text
    context.user_data['status'] = text
    if text == '⏰ Задерживаюсь':
        update.message.reply_text('В какое время будешь на работе? Например, 09:30', reply_markup=ReplyKeyboardRemove())
        return DELAY_TIME
    if text == '🏢 Удаленно':
        update.message.reply_text('По какой причине работаешь удаленно?', reply_markup=ReplyKeyboardRemove())
        return REMOTE_REASON
    if text == '🌴 В отпуске':
        update.message.reply_text('Укажи даты отпуска в формате DD.MM–DD.MM, например 07.09–12.09', reply_markup=ReplyKeyboardRemove())
        return VACATION_DATES
    if text == '🎨 На съёмках':
        update.message.reply_text('Что за съёмки? Укажи клиента и детали.', reply_markup=ReplyKeyboardRemove())
        return SHOOT_DETAILS
    # DayOff
    if text == '🛌 DayOff':
        ws = connect_sheet()
        record_status(ws, update, text, '', '')
        update.message.reply_text('Записал DayOff.', reply_markup=ReplyKeyboardRemove())
        return ConversationHandler.END

# --- обработка задержки: время и причина ---
def delay_time(update: Update, context):
    context.user_data['details'] = update.message.text
    update.message.reply_text('Укажи причину задержки.')
    return DELAY_REASON

def delay_reason(update: Update, context):
    reason = update.message.text
    ws = connect_sheet()
    record_status(ws, update, context.user_data['status'], context.user_data['details'], reason)
    update.message.reply_text('Записал задержку.', reply_markup=ReplyKeyboardRemove())
    return ConversationHandler.END

# --- удаленно ---
def remote_reason(update: Update, context):
    reason = update.message.text
    ws = connect_sheet()
    record_status(ws, update, context.user_data['status'], '', reason)
    update.message.reply_text('Записал работу удаленно.', reply_markup=ReplyKeyboardRemove())
    return ConversationHandler.END

# --- отпуск ---
def vacation_dates(update: Update, context):
    text = update.message.text.strip()
    if not re.match(r'\d{2}\.\d{2}–\d{2}\.\d{2}', text):
        update.message.reply_text('Неверный формат. Используй DD.MM–DD.MM')
        return VACATION_DATES
    context.user_data['details'] = text
    ws = connect_sheet()
    record_status(ws, update, context.user_data['status'], text, '')
    update.message.reply_text('Записал отпуск.', reply_markup=ReplyKeyboardRemove())
    return ConversationHandler.END

# --- съёмки ---
def shoot_details(update: Update, context):
    text = update.message.text
    ws = connect_sheet()
    record_status(ws, update, context.user_data['status'], text, '')
    update.message.reply_text('Записал съёмки.', reply_markup=ReplyKeyboardRemove())
    return ConversationHandler.END

# --- показать список за сегодня ---
def list_today(update: Update, context):
    ws = connect_sheet()
    rows = ws.get_all_records()
    today = datetime.now().strftime('%d.%m.%Y')
    lines = []
    for r in rows:
        if r['Дата'] == today:
            parts = [r['Статус']]
            det = r['Детали']
            rea = r['Причина']
            extras = []
            if det: extras.append(det)
            if rea: extras.append(rea)
            if extras:
                parts.append('(' + '; '.join(extras) + ')')
            lines.append(f"{r['Имя']} — {' '.join(parts)}")
    if not lines:
        reply = 'Сегодня ещё никто не заполнял статусы.'
    else:
        reply = 'Список сотрудников сегодня:\n' + '\n'.join(f"{i+1}. {l}" for i,l in enumerate(lines))
    update.message.reply_text(reply)

# --- main ---
def main():
    app = ApplicationBuilder().token(os.environ['TELEGRAM_TOKEN']).build()

    conv = ConversationHandler(
        entry_points=[CommandHandler('start', start)],
        states={
            CHOOSE: [MessageHandler(filters.TEXT & ~filters.COMMAND, choose)],
            DELAY_TIME: [MessageHandler(filters.TEXT & ~filters.COMMAND, delay_time)],
            DELAY_REASON: [MessageHandler(filters.TEXT & ~filters.COMMAND, delay_reason)],
            REMOTE_REASON: [MessageHandler(filters.TEXT & ~filters.COMMAND, remote_reason)],
            VACATION_DATES: [MessageHandler(filters.TEXT & ~filters.COMMAND, vacation_dates)],
            SHOOT_DETAILS: [MessageHandler(filters.TEXT & ~filters.COMMAND, shoot_details)],
        },
        fallbacks=[CommandHandler('cancel', lambda u,c: (u.message.reply_text('Отменено.', reply_markup=ReplyKeyboardRemove()), ConversationHandler.END)[1])]
    )
    app.add_handler(conv)
    app.add_handler(CommandHandler('list', list_today))
    # запуск
    app.run_polling()

if __name__ == '__main__':
    main()
