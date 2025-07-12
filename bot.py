#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
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
    filters,
)

# ====== НАСТРОЙКИ ======
TOKEN          = os.environ["TOKEN"]
SPREADSHEET_ID = os.environ["SPREADSHEET_ID"]

gc = gspread.service_account(filename="/etc/secrets/credentials.json")
sh = gc.open_by_key(SPREADSHEET_ID)
employees_ws = sh.worksheet("Employees")
status_ws    = sh.worksheet("Status")

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)

# состояния
CHOOSING, REMOTE_REASON, SHOOT_DETAIL, VACATION_DATES = range(4)

# клавиатура
main_keyboard = [
    ['🏢 Уже в офисе', '🏠 Удалённо'],
    ['🎨 На съёмках',    '🌴 В отпуске'],
    ['📋 Список сотрудников', 'DayOff']
]
markup = ReplyKeyboardMarkup(main_keyboard, one_time_keyboard=True, resize_keyboard=True)

def record_employee(name: str, tg_id: int):
    recs = employees_ws.get_all_records()
    ids = {int(r["Telegram ID"]) for r in recs}
    if tg_id not in ids:
        employees_ws.append_row([name, tg_id])

def record_status(name: str, tg_id: int, status: str, period: str, reason: str):
    today = date.today().strftime("%d.%m.%Y")
    status_ws.append_row([today, name, tg_id, status, period, reason])

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
        raise ValueError
    return to_date(parts[0]), to_date(parts[1])

def is_on_vacation(tg_id: int):
    today = date.today()
    for r in status_ws.get_all_records():
        if int(r["Telegram ID"])!=tg_id or r["Статус"]!="🌴 В отпуске":
            continue
        try:
            start, end = parse_vacation(r["Период"])
            if start<=today<=end:
                return True
        except:
            pass
    return False

# ===== HANDLERS =====

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if "name" not in context.user_data:
        await update.message.reply_text(
            "Привет! Представься: имя и фамилию.",
            reply_markup=ReplyKeyboardRemove()
        )
        return CHOOSING
    await update.message.reply_text("Выбери статус:", reply_markup=markup)
    return CHOOSING

async def name_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    tg_id = update.effective_user.id
    context.user_data["name"] = text
    record_employee(text, tg_id)
    await update.message.reply_text(
        f"✅ Записали: {text}\n\nТеперь выбери статус:",
        reply_markup=markup
    )
    return CHOOSING

async def choose_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # <<< ПАТЧ: если имя ещё не задано, пусть это сообщение станет именем
    if "name" not in context.user_data:
        return await name_handler(update, context)
    # <<< конец патча

    text = update.message.text
    tg_id = update.effective_user.id
    name = context.user_data["name"]

    if text=='🏠 Удалённо':
        await update.message.reply_text("По какой причине удалённо?", reply_markup=ReplyKeyboardRemove())
        return REMOTE_REASON

    if text=='🎨 На съёмках':
        await update.message.reply_text("Что за съёмки?", reply_markup=ReplyKeyboardRemove())
        return SHOOT_DETAIL

    if text=='🌴 В отпуске':
        await update.message.reply_text("Укажи даты (01.07–09.07):", reply_markup=ReplyKeyboardRemove())
        return VACATION_DATES

    if text=='DayOff':
        record_status(name, tg_id, "DayOff", "", "")
        await update.message.reply_text("✅ DayOff", reply_markup=markup)
        return ConversationHandler.END

    if text=='🏢 Уже в офисе':
        now = datetime.now().strftime("%H:%M")
        record_status(name, tg_id, "🏢 Уже в офисе", now, "")
        await update.message.reply_text(f"✅ Уже в офисе ({now})", reply_markup=markup)
        return ConversationHandler.END

    if text=='📋 Список сотрудников':
        today = date.today().strftime("%d.%m.%Y")
        recs = status_ws.get_all_records()
        lines=[]
        for r in recs:
            if r["Дата"]!=today: continue
            p = r["Период"] or ""
            q = r["Причина"] or ""
            lines.append(f"{r['Имя']} — {r['Статус']}"
                         f"{f' ({p})' if p else ''}"
                         f"{f' ({q})' if q else ''}")
        msg = "Сотрудники:\n"+"\n".join(f"{i+1}. {l}" for i,l in enumerate(lines)) if lines else "Нет отметок"
        await update.message.reply_text(msg, reply_markup=markup)
        return ConversationHandler.END

    await update.message.reply_text("Нажми кнопку меню.", reply_markup=markup)
    return CHOOSING

async def save_remote(update: Update, context: ContextTypes.DEFAULT_TYPE):
    r = update.message.text.strip()
    n = context.user_data["name"]
    i = update.effective_user.id
    record_status(n,i,"🏠 Удалённо","",r)
    await update.message.reply_text("✅ Удалённо", reply_markup=markup)
    return ConversationHandler.END

async def save_shoot(update: Update, context: ContextTypes.DEFAULT_TYPE):
    d = update.message.text.strip()
    n = context.user_data["name"]
    i = update.effective_user.id
    record_status(n,i,"🎨 На съёмках",d,"")
    await update.message.reply_text("✅ Съёмки", reply_markup=markup)
    return ConversationHandler.END

async def save_vacation(update: Update, context: ContextTypes.DEFAULT_TYPE):
    p = update.message.text.strip()
    n = context.user_data["name"]
    i = update.effective_user.id
    record_status(n,i,"🌴 В отпуске",p,"")
    await update.message.reply_text(f"✅ Отпуск {p}", reply_markup=markup)
    return ConversationHandler.END

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Отменено", reply_markup=markup)
    return ConversationHandler.END

async def daily_reminder(context: ContextTypes.DEFAULT_TYPE):
    today = date.today().strftime("%d.%m.%Y")
    emps = employees_ws.get_all_records()
    recs = status_ws.get_all_records()
    done = {int(r["Telegram ID"]) for r in recs if r["Дата"]==today}
    for r in emps:
        tid = int(r["Telegram ID"])
        if tid in done or is_on_vacation(tid): continue
        try:
            await context.bot.send_message(tid, "Выбери статус:", reply_markup=markup)
        except:
            pass

def main():
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
        allow_reentry=True,
    )
    app.add_handler(conv)

    app.job_queue.run_daily(daily_reminder, time(hour=9,minute=30), days=(0,1,2,3,4))

    app.run_polling()

if __name__=="__main__":
    main()
