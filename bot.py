#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import logging
from datetime import datetime, date, time
import re

import gspread
from telegram import ReplyKeyboardMarkup, ReplyKeyboardRemove, Update
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    ConversationHandler,
    ContextTypes,
    filters
)

# ====== НАСТРОЙКИ GOOGLE SHEETS ======
gc = gspread.service_account(filename="/etc/secrets/credentials.json")
SPREADSHEET = "checkin-alt-bot"
EMP_SHEET_NAME = "Employees"
STAT_SHEET_NAME = "Status"
employees_ws = gc.open(SPREADSHEET).worksheet(EMP_SHEET_NAME)
status_ws    = gc.open(SPREADSHEET).worksheet(STAT_SHEET_NAME)

# ====== ЛОГГИРОВАНИЕ ======
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)

# ====== СТЕЙТЫ ======
CHOOSING, REMOTE_REASON, SHOOT_DETAIL, VACATION_DATES, DELAY_TIME, DELAY_REASON = range(6)

# ====== КЛАВИАТУРА ======
main_keyboard = [
    ['🏢 Уже в офисе', '🏠 Удалённо'],
    ['🎨 На съёмках',    '🌴 В отпуске'],
    ['⏰ Задерживаюсь',  'DayOff'],
    ['📋 Список сотрудников']
]
markup = ReplyKeyboardMarkup(main_keyboard, one_time_keyboard=True, resize_keyboard=True)

# ====== УТИЛИТЫ ======

def record_employee(name: str, tg_id: int):
    records = employees_ws.get_all_records()
    ids = {int(r["Telegram ID"]) for r in records}
    if tg_id not in ids:
        employees_ws.append_row([name, tg_id])


def record_status(name: str, tg_id: int, status: str, reason: str, period: str):
    today = date.today().strftime("%d.%m.%Y")
    # columns: Дата, Имя, Telegram ID, Статус, Период, Причина
    status_ws.append_row([today, name, tg_id, status, period, reason, ""])


def parse_vacation(text: str):
    parts = re.split(r"[–-]", text.strip())
    def to_date(s):
        for fmt in ("%d.%m.%Y", "%d.%m"):
            try:
                dt = datetime.strptime(s.strip(), fmt)
                if fmt == "%d.%m": dt = dt.replace(year=date.today().year)
                return dt.date()
            except ValueError:
                continue
        raise ValueError(f"не знаю формат даты {s}")
    return to_date(parts[0]), to_date(parts[1])


def is_on_vacation(tg_id: int) -> bool:
    today = date.today()
    recs = status_ws.get_all_records()
    for r in recs:
        if int(r["Telegram ID"]) != tg_id: continue
        if r["Статус"] != "🌴 В отпуске": continue
        try:
            start, end = parse_vacation(r["Период"])
        except:
            continue
        if start <= today <= end:
            return True
    return False

# ====== HANDLERS ======

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if "name" not in context.user_data:
        await update.message.reply_text(
            "Привет! Представься: укажи имя и фамилию на русском.",
            reply_markup=ReplyKeyboardRemove()
        )
        return CHOOSING
    await update.message.reply_text("Выбери статус:", reply_markup=markup)
    record_employee(context.user_data['name'], user.id)
    return CHOOSING

async def name_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    tg_id = update.effective_user.id
    context.user_data["name"] = text
    record_employee(text, tg_id)
    await update.message.reply_text(
        f"✅ Записали: {text}\nТеперь выбери статус:", reply_markup=markup
    )
    return CHOOSING

async def choose_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    name = context.user_data["name"]
    tg_id = update.effective_user.id

    if text == '🏠 Удалённо':
        await update.message.reply_text("Почему удалённо?", reply_markup=ReplyKeyboardRemove())
        return REMOTE_REASON

    if text == '🎨 На съёмках':
        await update.message.reply_text("Опиши съёмки:", reply_markup=ReplyKeyboardRemove())
        return SHOOT_DETAIL

    if text == '🌴 В отпуске':
        await update.message.reply_text("Укажи даты отпуска (например 01.07–09.07):", reply_markup=ReplyKeyboardRemove())
        return VACATION_DATES

    if text == '⏰ Задерживаюсь':
        await update.message.reply_text("Во сколько будешь на работе?", reply_markup=ReplyKeyboardRemove())
        return DELAY_TIME

    if text == 'DayOff':
        record_status(name, tg_id, "DayOff", "", "")
        await update.message.reply_text("✅ Записано: DayOff", reply_markup=markup)
        return ConversationHandler.END

    if text == '🏢 Уже в офисе':
        now = datetime.now().strftime("%H:%M")
        record_status(name, tg_id, "🏢 Уже в офисе", "", now)
        await update.message.reply_text(f"✅ Уже в офисе ({now})", reply_markup=markup)
        return ConversationHandler.END

    if text == '📋 Список сотрудников':
        today = date.today().strftime("%d.%m.%Y")
        recs = status_ws.get_all_records()
        lines = []
        for r in recs:
            if r["Дата"] != today: continue
            period = r.get("Период", "") or r.get("Время прибытия", "")
            reason = r.get("Причина", "")
            lines.append(
                f"{r['Имя']} — {r['Статус']}"
                + (f" ({period})" if period else "")
                + (f" ({reason})" if reason else "")
            )
        msg = (
            "Список сотрудников сегодня:\n" + "\n".join(f"{i+1}. {l}" for i, l in enumerate(lines))
            if lines else "На сегодня нет отметок."
        )
        await update.message.reply_text(msg, reply_markup=markup)
        return ConversationHandler.END

    await update.message.reply_text("Нажми кнопку меню.", reply_markup=markup)
    return CHOOSING

async def save_remote(update: Update, context: ContextTypes.DEFAULT_TYPE):
    reason = update.message.text.strip()
    name = context.user_data["name"]
    tg_id = update.effective_user.id
    record_status(name, tg_id, "🏠 Удалённо", reason, "")
    await update.message.reply_text("✅ Записано: удалённо", reply_markup=markup)
    return ConversationHandler.END

async def save_shoot(update: Update, context: ContextTypes.DEFAULT_TYPE):
    detail = update.message.text.strip()
    name = context.user_data["name"]
    tg_id = update.effective_user.id
    record_status(name, tg_id, "🎨 На съёмках", detail, "")
    await update.message.reply_text("✅ Записано: на съёмках", reply_markup=markup)
    return ConversationHandler.END

async def save_vacation(update: Update, context: ContextTypes.DEFAULT_TYPE):
    period = update.message.text.strip()
    name = context.user_data["name"]
    tg_id = update.effective_user.id
    record_status(name, tg_id, "🌴 В отпуске", "", period)
    await update.message.reply_text(f"✅ Записано: отпуск {period}", reply_markup=markup)
    return ConversationHandler.END

async def delay_time_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    t = update.message.text.strip()
    context.user_data['delay_time'] = t
    await update.message.reply_text("Укажи причину задержки:", reply_markup=ReplyKeyboardRemove())
    return DELAY_REASON

async def save_delay(update: Update, context: ContextTypes.DEFAULT_TYPE):
    reason = update.message.text.strip()
    period = context.user_data.get('delay_time', '')
    name = context.user_data['name']
    tg_id = update.effective_user.id
    record_status(name, tg_id, "⏰ Задерживаюсь", reason, period)
    await update.message.reply_text(f"✅ Записано: задержка {period} ({reason})", reply_markup=markup)
    return ConversationHandler.END

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Отменено.", reply_markup=markup)
    return ConversationHandler.END

async def daily_reminder(context: ContextTypes.DEFAULT_TYPE):
    today = date.today().strftime("%d.%m.%Y")
    emps = employees_ws.get_all_records()
    recs = status_ws.get_all_records()
    done = {int(r["Telegram ID"]) for r in recs if r["Дата"] == today}
    for r in emps:
        tg_id = int(r["Telegram ID"])
        if tg_id in done or is_on_vacation(tg_id): continue
        try:
            await context.bot.send_message(chat_id=tg_id,
                text="Пожалуйста, выбери статус на сегодня:",
                reply_markup=markup
            )
        except Exception as e:
            logging.error(f"Не доставить {tg_id}: {e}")


def main():
    TOKEN = "<ВАШ_ТОКЕН>"
    app = ApplicationBuilder().token(TOKEN).build()

    conv = ConversationHandler(
        entry_points=[CommandHandler("start", start)],
        states={
            CHOOSING:      [MessageHandler(filters.TEXT & ~filters.COMMAND, choose_status)],
            REMOTE_REASON: [MessageHandler(filters.TEXT & ~filters.COMMAND, save_remote)],
            SHOOT_DETAIL:  [MessageHandler(filters.TEXT & ~filters.COMMAND, save_shoot)],
            VACATION_DATES:[MessageHandler(filters.TEXT & ~filters.COMMAND, save_vacation)],
            DELAY_TIME:    [MessageHandler(filters.TEXT & ~filters.COMMAND, delay_time_handler)],
            DELAY_REASON:  [MessageHandler(filters.TEXT & ~filters.COMMAND, save_delay)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )
    app.add_handler(conv)

    remind = time(hour=9, minute=30)
    app.job_queue.run_daily(daily_reminder, remind, days=(0,1,2,3,4))

    app.run_polling()

if __name__ == "__main__":
    main()
