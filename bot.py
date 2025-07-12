import logging
from datetime import datetime, time, date
import re

import gspread
from telegram import (
    ReplyKeyboardMarkup,
    ReplyKeyboardRemove,
    Update,
)
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    ConversationHandler,
    ContextTypes,
    filters,
)

# ====== НАСТРОЙКИ GOOGLE SHEETS ======
# JSON-ключ сервисного аккаунта по пути /etc/secrets/credentials.json
gc = gspread.service_account(filename="/etc/secrets/credentials.json")
SPREADSHEET = "checkin-alt-bot"  # имя таблицы
EMP_SHEET = "Employees"
STAT_SHEET = "Status"

# открываем листы
employees_ws = gc.open(SPREADSHEET).worksheet(EMP_SHEET)
status_ws    = gc.open(SPREADSHEET).worksheet(STAT_SHEET)

# ====== ЛОГГИРОВАНИЕ ======
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)

# ====== СТЕЙТЫ ======
(
    ASK_NAME,
    CHOOSING,
    REMOTE_REASON,
    SHOOT_DETAIL,
    VACATION_DATES,
    DELAY_TIME,
    DELAY_REASON
) = range(7)

# ====== КЛАВИАТУРА ======
menu = [
    ['🏢 Уже в офисе', '🏠 Удалённо'],
    ['🎨 На съёмках',    '🌴 В отпуске'],
    ['⏰ Задерживаюсь', 'DayOff'],
    ['📋 Список сотрудников']
]
markup = ReplyKeyboardMarkup(menu, one_time_keyboard=True, resize_keyboard=True)

# ====== UTILS SHEETS ======

def record_employee(name: str, tg_id: int):
    recs = employees_ws.get_all_records()
    ids = {int(r['Telegram ID']) for r in recs}
    if tg_id not in ids:
        employees_ws.append_row([name, tg_id])


def record_status(name: str, tg_id: int, status: str, period: str, reason: str):
    today = date.today().strftime('%d.%m.%Y')
    status_ws.append_row([today, name, tg_id, status, period, reason])

# ====== PARSERS ======

def parse_vacation(text: str):
    parts = re.split(r"[–-]", text.strip())
    def to_date(s):
        for fmt in ('%d.%m.%Y','%d.%m'):
            try:
                d = datetime.strptime(s.strip(), fmt)
                if fmt=='%d.%m': d = d.replace(year=date.today().year)
                return d.date()
            except: pass
        raise
    return to_date(parts[0]), to_date(parts[1])

# ====== REMINDER HELP ======

def is_on_vacation(tg_id: int):
    today = date.today()
    for r in status_ws.get_all_records():
        if int(r['Telegram ID'])!=tg_id or r['Статус']!='🌴 В отпуске': continue
        try:
            start,end = parse_vacation(r['Период'])
            if start<=today<=end: return True
        except: pass
    return False

# ====== HANDLERS ======

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if 'name' not in context.user_data:
        await update.message.reply_text(
            'Привет! Представься: укажи имя и фамилию на русском.',
            reply_markup=ReplyKeyboardRemove()
        )
        return ASK_NAME
    await update.message.reply_text('Выбери статус:', reply_markup=markup)
    return CHOOSING

async def ask_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    name = update.message.text.strip()
    tg_id = update.effective_user.id
    context.user_data['name']=name
    record_employee(name, tg_id)
    await update.message.reply_text(f'✅ Записали: {name}\nТеперь выбери статус:', reply_markup=markup)
    return CHOOSING

async def choose_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    name = context.user_data['name']
    tg_id = update.effective_user.id
    if text=='🏠 Удалённо':
        await update.message.reply_text('Причина удалёнки?', reply_markup=ReplyKeyboardRemove())
        return REMOTE_REASON
    if text=='🎨 На съёмках':
        await update.message.reply_text('Детали съёмки (клиент)?', reply_markup=ReplyKeyboardRemove())
        return SHOOT_DETAIL
    if text=='🌴 В отпуске':
        await update.message.reply_text('Даты отпуска (пример 01.07–09.07)?', reply_markup=ReplyKeyboardRemove())
        return VACATION_DATES
    if text=='⏰ Задерживаюсь':
        await update.message.reply_text('Во сколько будешь на работе?', reply_markup=ReplyKeyboardRemove())
        return DELAY_TIME
    if text=='DayOff':
        record_status(name, tg_id, 'DayOff', '', '')
        await update.message.reply_text('✅ Записано: DayOff', reply_markup=markup)
        return ConversationHandler.END
    if text=='🏢 Уже в офисе':
        now=datetime.now().strftime('%H:%M')
        record_status(name, tg_id, '🏢 Уже в офисе', now, '')
        await update.message.reply_text(f'✅ Записано: офис ({now})', reply_markup=markup)
        return ConversationHandler.END
    if text=='📋 Список сотрудников':
        today=date.today().strftime('%d.%m.%Y')
        recs=status_ws.get_all_records()
        lines=[]
        for r in recs:
            if r['Дата']!=today: continue
            period=r['Период'] or r['Время'] or ''
            reason=r['Причина'] or ''
            lines.append(f"{r['Имя']} — {r['Статус']}" +
                         (f" ({period})" if period else '') +
                         (f" ({reason})" if reason else ''))
        msg='Список сотрудников сегодня:\n'+"\n".join(f"{i+1}. {l}" for i,l in enumerate(lines)) if lines else 'Нет отметок.'
        await update.message.reply_text(msg, reply_markup=markup)
        return ConversationHandler.END
    await update.message.reply_text('Выбери с помощью кнопок.', reply_markup=markup)
    return CHOOSING

async def save_remote(update: Update, context: ContextTypes.DEFAULT_TYPE):
    reason=update.message.text.strip()
    name=context.user_data['name']; tg_id=update.effective_user.id
    record_status(name, tg_id, '🏠 Удалённо', '', reason)
    await update.message.reply_text('✅ Записано: удалённо', reply_markup=markup)
    return ConversationHandler.END

async def save_shoot(update: Update, context: ContextTypes.DEFAULT_TYPE):
    detail=update.message.text.strip()
    name=context.user_data['name']; tg_id=update.effective_user.id
    record_status(name, tg_id, '🎨 На съёмках', '', detail)
    await update.message.reply_text('✅ Записано: съёмки', reply_markup=markup)
    return ConversationHandler.END

async def save_vacation(update: Update, context: ContextTypes.DEFAULT_TYPE):
    period=update.message.text.strip()
    name=context.user_data['name']; tg_id=update.effective_user.id
    record_status(name, tg_id, '🌴 В отпуске', period, '')
    await update.message.reply_text(f'✅ Отпуск {period}', reply_markup=markup)
    return ConversationHandler.END

async def save_delay_time(update: Update, context: ContextTypes.DEFAULT_TYPE):
    t=update.message.text.strip()
    context.user_data['delay_time']=t
    await update.message.reply_text('Причина задержки?', reply_markup=ReplyKeyboardRemove())
    return DELAY_REASON

async def save_delay_reason(update: Update, context: ContextTypes.DEFAULT_TYPE):
    reason=update.message.text.strip()
    name=context.user_data['name']; tg_id=update.effective_user.id
    t=context.user_data.get('delay_time','')
    record_status(name, tg_id, '⏰ Задерживаюсь', t, reason)
    await update.message.reply_text('✅ Записано: задержка', reply_markup=markup)
    return ConversationHandler.END

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text('Отменено.', reply_markup=markup)
    return ConversationHandler.END

# ====== ЕЖЕДНЕВНЫЙ REMINDER ======
async def daily_reminder(context: ContextTypes.DEFAULT_TYPE):
    today=date.today().strftime('%d.%m.%Y')
    emps=employees_ws.get_all_records()
    recs=status_ws.get_all_records()
    done={int(r['Telegram ID']) for r in recs if r['Дата']==today}
    for r in emps:
        tg=int(r['Telegram ID'])
        if tg in done or is_on_vacation(tg): continue
        try:
            await context.bot.send_message(chat_id=tg, text='Пожалуйста, выбери статус:', reply_markup=markup)
        except Exception as e:
            logging.error(f'Напоминание не дошло {tg}: {e}')

# ====== MAIN ======

def main():
    TOKEN = '<ВАШ_ТОКЕН>'
    app = ApplicationBuilder().token(TOKEN).build()
    conv = ConversationHandler(
        entry_points=[CommandHandler('start', start)],
        states={
            ASK_NAME:       [MessageHandler(filters.TEXT & ~filters.COMMAND, ask_name)],
            CHOOSING:       [MessageHandler(filters.TEXT & ~filters.COMMAND, choose_status)],
            REMOTE_REASON:  [MessageHandler(filters.TEXT & ~filters.COMMAND, save_remote)],
            SHOOT_DETAIL:   [MessageHandler(filters.TEXT & ~filters.COMMAND, save_shoot)],
            VACATION_DATES:[MessageHandler(filters.TEXT & ~filters.COMMAND, save_vacation)],
            DELAY_TIME:     [MessageHandler(filters.TEXT & ~filters.COMMAND, save_delay_time)],
            DELAY_REASON:   [MessageHandler(filters.TEXT & ~filters.COMMAND, save_delay_reason)],
        },
        fallbacks=[CommandHandler('cancel', cancel)],
    )
    app.add_handler(conv)
    remind = time(hour=9, minute=30)
    app.job_queue.run_daily(daily_reminder, remind, days=(0,1,2,3,4))
    app.run_polling()

if __name__=='__main__': main()
