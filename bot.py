#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os, threading, http.server, socketserver
import logging
from datetime import datetime, time, date
import re
import gspread
from telegram import ReplyKeyboardMarkup, ReplyKeyboardRemove, Update
from telegram.ext import (
    ApplicationBuilder, CommandHandler, MessageHandler,
    ConversationHandler, ContextTypes, filters
)

# logging
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)

# Google Sheets
SPREADSHEET_ID = os.environ["SPREADSHEET_ID"]
gc = gspread.service_account(filename="/etc/secrets/credentials.json")
employees_ws = gc.open_by_key(SPREADSHEET_ID).worksheet("Employees")
status_ws    = gc.open_by_key(SPREADSHEET_ID).worksheet("Status")

# states
CHOOSING, REMOTE_REASON, SHOOT_DETAIL, VACATION_DATES = range(4)

# keyboard
main_keyboard = [
    ['🏢 Уже в офисе', '🏠 Удалённо'],
    ['🎨 На съёмках',    '🌴 В отпуске'],
    ['📋 Список сотрудников', 'DayOff']
]
markup = ReplyKeyboardMarkup(main_keyboard, one_time_keyboard=True, resize_keyboard=True)

# helpers (GS)
def record_employee(name, tg_id):
    ids = {int(r["Telegram ID"]) for r in employees_ws.get_all_records()}
    if tg_id not in ids:
        employees_ws.append_row([name, tg_id])

def record_status(name, tg_id, status, period, reason):
    today = date.today().strftime("%d.%m.%Y")
    status_ws.append_row([today, name, tg_id, status, period, reason, ""])

def parse_vacation(text):
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

def is_on_vacation(tg_id):
    today = date.today()
    for r in status_ws.get_all_records():
        if int(r["Telegram ID"]) != tg_id: continue
        if r["Статус"] != "🌴 В отпуске": continue
        try:
            start, end = parse_vacation(r["Период"])
        except:
            continue
        if start <= today <= end:
            return True
    return False

# handlers
async def start(update, context):
    if "name" not in context.user_data:
        await update.message.reply_text(
            "Привет! Представься: имя и фамилию.",
            reply_markup=ReplyKeyboardRemove()
        )
        return CHOOSING
    await update.message.reply_text("Выбери статус:", reply_markup=markup)
    return CHOOSING

async def name_handler(update, context):
    name = update.message.text.strip()
    tg_id = update.effective_user.id
    context.user_data["name"] = name
    record_employee(name, tg_id)
    await update.message.reply_text(f"✅ Записали: {name}", reply_markup=markup)
    return CHOOSING

async def choose_status(update, context):
    text = update.message.text
    name = context.user_data.get("name")
    tg_id = update.effective_user.id

    if not name:
        return await start(update, context)

    if text == '🏠 Удалённо':
        await update.message.reply_text("Причина удалёнки?", reply_markup=ReplyKeyboardRemove())
        return REMOTE_REASON

    if text == '🎨 На съёмках':
        await update.message.reply_text("Что за съёмки?", reply_markup=ReplyKeyboardRemove())
        return SHOOT_DETAIL

    if text == '🌴 В отпуске':
        await update.message.reply_text("Даты отпуска (01.07–09.07):", reply_markup=ReplyKeyboardRemove())
        return VACATION_DATES

    if text == 'DayOff':
        record_status(name, tg_id, "DayOff", "", "")
        await update.message.reply_text("✅ DayOff", reply_markup=markup)
        return ConversationHandler.END

    if text == '🏢 Уже в офисе':
        now = datetime.now().strftime("%H:%M")
        record_status(name, tg_id, "🏢 Уже в офисе", now, "")
        await update.message.reply_text(f"✅ В офисе ({now})", reply_markup=markup)
        return ConversationHandler.END

    if text == '📋 Список сотрудников':
        today = date.today().strftime("%d.%m.%Y")
        recs = status_ws.get_all_records()
        lines = []
        for r in recs:
            if r["Дата"] != today: continue
            st = r["Статус"]
            per = r["Период"] or r.get("Детали","")
            rea = r["Причина"] or ""
            detail = f"({per})" if per else ""
            reas   = f"({rea})" if rea else ""
            lines.append(f"{r['Имя']} — {st} {detail} {reas}".strip())
        msg = "Сотрудники сегодня:\n" + "\n".join(f"{i+1}. {l}" for i,l in enumerate(lines)) if lines else "Нет записей."
        await update.message.reply_text(msg, reply_markup=markup)
        return ConversationHandler.END

    await update.message.reply_text("Нажми кнопку.", reply_markup=markup)
    return CHOOSING

async def save_remote(update, context):
    reason = update.message.text.strip()
    name = context.user_data["name"]
    tg_id = update.effective_user.id
    record_status(name, tg_id, "🏠 Удалённо", "", reason)
    await update.message.reply_text("✅ Удалённо", reply_markup=markup)
    return ConversationHandler.END

async def save_shoot(update, context):
    detail = update.message.text.strip()
    name = context.user_data["name"]
    tg_id = update.effective_user.id
    record_status(name, tg_id, "🎨 На съёмках", detail, "")
    await update.message.reply_text("✅ Съёмки", reply_markup=markup)
    return ConversationHandler.END

async def save_vacation(update, context):
    period = update.message.text.strip()
    name = context.user_data["name"]
    tg_id = update.effective_user.id
    record_status(name, tg_id, "🌴 В отпуске", period, "")
    await update.message.reply_text(f"✅ Отпуск {period}", reply_markup=markup)
    return ConversationHandler.END

async def cancel(update, context):
    await update.message.reply_text("Отменено.", reply_markup=markup)
    return ConversationHandler.END

# ежедневка
async def daily_reminder(context):
    today = date.today().strftime("%d.%m.%Y")
    emps = employees_ws.get_all_records()
    recs = status_ws.get_all_records()
    done = {int(r["Telegram ID"]) for r in recs if r["Дата"] == today}
    for r in emps:
        tg = int(r["Telegram ID"])
        if tg in done or is_on_vacation(tg):
            continue
        try:
            await context.bot.send_message(chat_id=tg, text="Статус на сегодня?", reply_markup=markup)
        except:
            pass

def main():
    TOKEN = os.environ["TOKEN"]
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

    app.job_queue.run_daily(daily_reminder, time(hour=9, minute=30), days=(0,1,2,3,4))
    app.run_polling()

# HTTP-сервер для Render health-checks
def _serve_web():
    port = int(os.environ.get("PORT", 8000))
    handler = http.server.SimpleHTTPRequestHandler
    with socketserver.TCPServer(("0.0.0.0", port), handler) as httpd:
        httpd.serve_forever()

if __name__ == "__main__":
    threading.Thread(target=_serve_web, daemon=True).start()
    main()
