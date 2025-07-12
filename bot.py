#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import logging
import os
import re
from datetime import datetime, time, date

import gspread
from telegram import ReplyKeyboardMarkup, ReplyKeyboardRemove, Update
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    ConversationHandler,
    ContextTypes,
    filters,
)

# ====== КОНФИГУРАЦИЯ ======
SPREADSHEET_ID = os.getenv("SPREADSHEET_ID")    # ключ таблицы из Config Vars на Render
TOKEN          = os.getenv("TOKEN")               # токен бота из Config Vars

EMP_SHEET_NAME  = "Employees"
STAT_SHEET_NAME = "Status"

# ====== GOOGLE SHEETS ======
# Поместите JSON-ключ сервисного аккаунта по пути /etc/secrets/credentials.json
gc = gspread.service_account(filename="/etc/secrets/credentials.json")
employees_ws = gc.open_by_key(SPREADSHEET_ID).worksheet(EMP_SHEET_NAME)
status_ws    = gc.open_by_key(SPREADSHEET_ID).worksheet(STAT_SHEET_NAME)

# ====== ЛОГИ ======
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)

# ====== СТЕЙТЫ ======
CHOOSING, REMOTE_REASON, SHOOT_DETAIL, VACATION_DATES = range(4)

# ====== КЛАВИАТУРА ======
main_keyboard = [
    ['🏢 Уже в офисе', '🏠 Удалённо'],
    ['🎨 На съёмках',    '🌴 В отпуске'],
    ['📋 Список сотрудников', 'DayOff']
]
markup = ReplyKeyboardMarkup(main_keyboard, one_time_keyboard=True, resize_keyboard=True)

# ====== УТИЛИТЫ ======
def record_employee(name: str, tg_id: int):
    recs = employees_ws.get_all_records()
    ids = {int(r["Telegram ID"]) for r in recs}
    if tg_id not in ids:
        employees_ws.append_row([name, tg_id])

def record_status(name: str, tg_id: int, status: str, period: str, detail: str):
    today = date.today().strftime("%d.%m.%Y")
    # [Дата, Имя, ID, Статус, Детали, Причина]
    status_ws.append_row([today, name, tg_id, status, period, detail])

def parse_vacation(text: str):
    parts = re.split(r"[–-]", text.strip())
    def to_date(s):
        for fmt in ("%d.%m.%Y", "%d.%m"):
            try:
                dt = datetime.strptime(s.strip(), fmt)
                if fmt == "%d.%m":
                    dt = dt.replace(year=date.today().year)
                return dt.date()
            except ValueError:
                continue
        raise ValueError(f"не знаю формат даты {s}")
    return to_date(parts[0]), to_date(parts[1])

def is_on_vacation(tg_id: int):
    today = date.today()
    for r in status_ws.get_all_records():
        if int(r["Telegram ID"]) != tg_id or r["Статус"] != "🌴 В отпуске":
            continue
        try:
            start, end = parse_vacation(r["Детали"])
        except:
            continue
        if start <= today <= end:
            return True
    return False

# ====== HANDLERS ======
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if "name" not in context.user_data:
        await update.message.reply_text(
            "Привет! Представься, пожалуйста (имя и фамилия).",
            reply_markup=ReplyKeyboardRemove()
        )
        return CHOOSING
    await update.message.reply_text("Выбери статус:", reply_markup=markup)
    return CHOOSING

async def name_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    name = update.message.text.strip()
    tg_id = update.effective_user.id
    context.user_data["name"] = name
    record_employee(name, tg_id)
    await update.message.reply_text(f"✅ Записали: {name}\n\nТеперь выбери статус:", reply_markup=markup)
    return CHOOSING

async def choose_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    name  = context.user_data["name"]
    tg_id = update.effective_user.id

    if text == '🏠 Удалённо':
        await update.message.reply_text("Причина удалёнки?", reply_markup=ReplyKeyboardRemove())
        return REMOTE_REASON

    if text == '🎨 На съёмках':
        await update.message.reply_text("Где/клиент съёмок?", reply_markup=ReplyKeyboardRemove())
        return SHOOT_DETAIL

    if text == '🌴 В отпуске':
        await update.message.reply_text("Даты отпуска (01.07–05.07)?", reply_markup=ReplyKeyboardRemove())
        return VACATION_DATES

    if text == 'DayOff':
        record_status(name, tg_id, "DayOff", "", "")
        await update.message.reply_text("✅ Записано: DayOff", reply_markup=markup)
        return ConversationHandler.END

    if text == '🏢 Уже в офисе':
        now = datetime.now().strftime("%H:%M")
        record_status(name, tg_id, "🏢 Уже в офисе", now, "")
        await update.message.reply_text(f"✅ Вы в офисе с {now}", reply_markup=markup)
        return ConversationHandler.END

    if text == '📋 Список сотрудников':
        today = date.today().strftime("%d.%m.%Y")
        recs = status_ws.get_all_records()
        lines = []
        for r in recs:
            if r["Дата"] != today:
                continue
            status = r["Статус"]
            period = r["Детали"]
            detail = r["Причина"]
            parts = [status]
            if period: parts.append(period)
            if detail: parts.append(detail)
            lines.append(f"{r['Имя']} — {' | '.join(parts)}")
        msg = "Список сегодня:\n" + ("\n".join(f"{i+1}. {l}" for i,l in enumerate(lines)) if lines else "Нет записей")
        await update.message.reply_text(msg, reply_markup=markup)
        return ConversationHandler.END

    await update.message.reply_text("Нажми кнопку меню.", reply_markup=markup)
    return CHOOSING

async def save_remote(update: Update, context: ContextTypes.DEFAULT_TYPE):
    reason = update.message.text.strip()
    name  = context.user_data["name"]
    tg_id = update.effective_user.id
    record_status(name, tg_id, "🏠 Удалённо", "", reason)
    await update.message.reply_text("✅ Удалёнка записана", reply_markup=markup)
    return ConversationHandler.END

async def save_shoot(update: Update, context: ContextTypes.DEFAULT_TYPE):
    detail = update.message.text.strip()
    name   = context.user_data["name"]
    tg_id  = update.effective_user.id
    record_status(name, tg_id, "🎨 На съёмках", "", detail)
    await update.message.reply_text("✅ Съёмки записаны", reply_markup=markup)
    return ConversationHandler.END

async def save_vacation(update: Update, context: ContextTypes.DEFAULT_TYPE):
    period = update.message.text.strip()
    name   = context.user_data["name"]
    tg_id  = update.effective_user.id
    record_status(name, tg_id, "🌴 В отпуске", period, "")
    await update.message.reply_text(f"✅ Отпуск {period}", reply_markup=markup)
    return ConversationHandler.END

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Отменено.", reply_markup=markup)
    return ConversationHandler.END

# ====== ЕЖЕДНЕВНОЕ НАПОМИНАНИЕ ======
async def daily_reminder(context: ContextTypes.DEFAULT_TYPE):
    today = date.today().strftime("%d.%m.%Y")
    emps = employees_ws.get_all_records()
    recs = status_ws.get_all_records()
    done = {int(r["Telegram ID"]) for r in recs if r["Дата"] == today}
    for r in emps:
        tg_id = int(r["Telegram ID"])
        if tg_id in done or is_on_vacation(tg_id):
            continue
        try:
            await context.bot.send_message(chat_id=tg_id, text="Пож-та, выбери статус:", reply_markup=markup)
        except Exception as e:
            logging.error(f"Не отправилось {tg_id}: {e}")

# ====== MAIN ======
def main():
    if not TOKEN or not SPREADSHEET_ID:
        logging.error("Не заданы TOKEN или SPREADSHEET_ID!")
        return

    app = ApplicationBuilder().token(TOKEN).build()

    conv = ConversationHandler(
        entry_points=[CommandHandler("start", start)],
        states={
            CHOOSING:       [MessageHandler(filters.TEXT & ~filters.COMMAND, choose_status)],
            REMOTE_REASON:  [MessageHandler(filters.TEXT & ~filters.COMMAND, save_remote)],
            SHOOT_DETAIL:   [MessageHandler(filters.TEXT & ~filters.COMMAND, save_shoot)],
            VACATION_DATES: [MessageHandler(filters.TEXT & ~filters.COMMAND, save_vacation)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )
    app.add_handler(conv)

    # планируем утренний пуш
    remind_time = time(hour=9, minute=30)
    app.job_queue.run_daily(daily_reminder, remind_time, days=(0,1,2,3,4))

    app.run_polling()

if __name__ == "__main__":
    main()
