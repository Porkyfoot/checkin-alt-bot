import os
import logging
from datetime import datetime, time, timedelta
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from telegram import Update, ReplyKeyboardMarkup, ReplyKeyboardRemove
from telegram.ext import (
    ApplicationBuilder, CommandHandler, MessageHandler,
    ConversationHandler, ContextTypes, filters, CallbackContext
)

# --- CONFIG ---
TOKEN = os.environ['TOKEN']
SPREADSHEET_NAME = 'Ежедневные Отметки'
TIMEZONE_OFFSET = 5  # часовой пояс

# --- Google Sheets Setup ---
scope = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
creds = ServiceAccountCredentials.from_json_keyfile_name('/etc/secrets/credentials.json', scope)
client = gspread.authorize(creds)
sheet = client.open(SPREADSHEET_NAME).sheet1

# --- States ---
ASK_NAME, CHOOSING, DETAILS = range(3)

logging.basicConfig(level=logging.INFO)

def today_str():
    return (datetime.utcnow() + timedelta(hours=TIMEZONE_OFFSET)).strftime('%d.%m.%Y')

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    headers = sheet.row_values(1)
    if headers != ['Дата','Имя','ID','Статус','Детали']:
        sheet.clear()
        sheet.append_row(['Дата','Имя','ID','Статус','Детали'])
    await update.message.reply_text('Привет! Напиши своё ФИО на русском.')
    return ASK_NAME

async def ask_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['name'] = update.message.text.strip()
    kb = [['🏢 Уже в офисе'], ['🏠 Удалённо','🎨 На съёмках'], ['🌴 В отпуске'], ['📋 Список']]
    markup = ReplyKeyboardMarkup(kb, resize_keyboard=True)
    await update.message.reply_text('Выбери статус:', reply_markup=markup)
    return CHOOSING

async def status_chosen(update: Update, context: ContextTypes.DEFAULT_TYPE):
    status = update.message.text
    uid = update.effective_user.id
    if status == '📋 Список':
        return await show_list(update, context)
    context.user_data['status'] = status
    if status == '🏢 Уже в офисе':
        context.user_data['details'] = (datetime.utcnow() + timedelta(hours=TIMEZONE_OFFSET)).strftime('%H:%M')
        return await save(update, context)
    await update.message.reply_text('Напиши детали или "нет".', reply_markup=ReplyKeyboardRemove())
    return DETAILS

async def details(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['details'] = update.message.text.strip()
    return await save(update, context)

async def save(update: Update, context: ContextTypes.DEFAULT_TYPE):
    u = update.effective_user
    data = context.user_data
    row = [today_str(), data['name'], str(u.id), data['status'], data.get('details','')]
    sheet.append_row(row)
    await update.message.reply_text('✅ Записано!', reply_markup=ReplyKeyboardRemove())
    return ConversationHandler.END

async def show_list(update: Update, context: ContextTypes.DEFAULT_TYPE):
    recs = sheet.get_all_records()
    t = today_str()
    lines = []
    i = 1
    for r in recs:
        if r['Дата'] == t:
            lines.append(f"{i}. {r['Имя']} — {r['Статус']} ({r['Детали']})")
            i += 1
    text = 'Список сегодня:\n' + '\n'.join(lines) if lines else 'Никто не отметил.'
    await update.message.reply_text(text, reply_markup=ReplyKeyboardRemove())

def reminder(context: CallbackContext):
    recs = sheet.get_all_records()
    t = today_str()
    ids = {r['ID'] for r in recs if r['Дата']==t}
    for uid in ids:
        context.bot.send_message(chat_id=int(uid), text='Пожалуйста, отметь свой статус до 10:00. /start')

def main():
    app = ApplicationBuilder().token(TOKEN).build()
    conv = ConversationHandler(
        entry_points=[CommandHandler('start', start)],
        states={
            ASK_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, ask_status)],
            CHOOSING: [MessageHandler(filters.TEXT & ~filters.COMMAND, status_chosen)],
            DETAILS: [MessageHandler(filters.TEXT & ~filters.COMMAND, details)]
        },
        fallbacks=[CommandHandler('cancel', lambda u,c: c.bot.send_message(u.effective_chat.id,'Отменено'))]
    )
    app.add_handler(conv)
    # ежедневно в 9:30 (UTC = 9:30 - TIMEZONE_OFFSET)
    remind_time = time(hour=9-TIMEZONE_OFFSET, minute=30)
    app.job_queue.run_daily(reminder, remind_time, days=(0,1,2,3,4))
    app.run_polling()

if __name__=='__main__':
    main()
