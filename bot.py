#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import logging
import re
from datetime import datetime, date, time

import gspread
from telegram import ReplyKeyboardMarkup, ReplyKeyboardRemove, Update
from telegram.ext import (
    ApplicationBuilder, CommandHandler, MessageHandler,
    ConversationHandler, ContextTypes, filters
)

# ============ ЛОГИ =============
logging.basicConfig(
    format="%(asctime)s %(levelname)s %(message)s",
    level=logging.INFO
)

# ============ КОНФИГ =============
TOKEN         = os.environ["TOKEN"]
SPREADSHEET_ID= os.environ["SPREADSHEET_ID"]
WEBHOOK_PATH  = f"/{TOKEN}"
PORT          = int(os.environ.get("PORT", 8443))
HOSTNAME      = os.environ.get("RENDER_EXTERNAL_HOSTNAME")  # Render даёт это автоматически

# ============ GOOGLE SHEETS ============
gc = gspread.service_account(filename="/etc/secrets/credentials.json")
sh = gc.open_by_key(SPREADSHEET_ID)
employees_ws = sh.worksheet("Employees")
status_ws    = sh.worksheet("Status")

# ============ STATES ============
CHOOSING, REMOTE_REASON, SHOOT_DETAIL, VACATION_DATES = range(4)

# ============ КЛАВИАТУРА ============
main_keyboard = [
    ['🏢 Уже в офисе', '🏠 Удалённо'],
    ['🎨 На съёмках',    '🌴 В отпуске'],
    ['📋 Список сотрудников', 'DayOff']
]
markup = ReplyKeyboardMarkup(main_keyboard, one_time_keyboard=True, resize_keyboard=True)

# ============ HELPERS для GS ============
def record_employee(name: str, tg_id: int):
    ids = {int(r["Telegram ID"]) for r in employees_ws.get_all_records()}
    if tg_id not in ids:
        employees_ws.append_row([name, tg_id])

def record_status(name, tg_id, status, period, reason):
    today = date.today().strftime("%d.%m.%Y")
    status_ws.append_row([today, name, tg_id, status, period, reason, ""])

def parse_vacation(text: str):
    parts = re.split(r"[–-]", text.strip())
    def to_date(s):
        for fmt in ("%d.%m.%Y", "%d.%m"):
            try:
                dt = datetime.strptime(s.strip(), fmt)
                if fmt=="%d.%m":
                    dt = dt.replace(year=date.today().year)
                return dt.date()
            except ValueError:
                continue
        raise ValueError(f"не знаю формат даты {s}")
    return to_date(parts[0]), to_date(parts[1])

def is_on_vacation(tg_id):
    today = date.today()
    for r in status_ws.get_all_records():
        if int(r["Telegram ID"])!=tg_id: continue
        if r["Статус"]!="🌴 В отпуске": continue
        try:
            start,end = parse_vacation(r["Период"])
        except:
            continue
        if start<=today<=end:
            return True
    return False

# ============ HANDLERS ============

async def start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if "name" not in ctx.user_data:
        await update.message.reply_text(
            "Привет! Представься: имя и фамилию.",
            reply_markup=ReplyKeyboardRemove()
        )
        return CHOOSING
    await update.message.reply_text("Выбери статус:", reply_markup=markup)
    return CHOOSING

async def name_handler(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    name = update.message.text.strip()
    tg_id= update.effective_user.id
    ctx.user_data["name"]=name
    record_employee(name, tg_id)
    await update.message.reply_text(f"✅ Записали: {name}", reply_markup=markup)
    return CHOOSING

async def choose_status(update, ctx):
    text = update.message.text
    data = ctx.user_data
    if "name" not in data:
        return await start(update, ctx)

    name, tg_id = data["name"], update.effective_user.id

    if text=='🏠 Удалённо':
        await update.message.reply_text("Причина удалёнки?", reply_markup=ReplyKeyboardRemove())
        return REMOTE_REASON

    if text=='🎨 На съёмках':
        await update.message.reply_text("Что за съёмки?", reply_markup=ReplyKeyboardRemove())
        return SHOOT_DETAIL

    if text=='🌴 В отпуске':
        await update.message.reply_text("Даты отпуска (01.07–09.07):", reply_markup=ReplyKeyboardRemove())
        return VACATION_DATES

    if text=='DayOff':
        record_status(name, tg_id, "DayOff", "", "")
        await update.message.reply_text("✅ DayOff", reply_markup=markup)
        return ConversationHandler.END

    if text=='🏢 Уже в офисе':
        now = datetime.now().strftime("%H:%M")
        record_status(name, tg_id, "🏢 Уже в офисе", now, "")
        await update.message.reply_text(f"✅ В офисе ({now})", reply_markup=markup)
        return ConversationHandler.END

    if text=='📋 Список сотрудников':
        today = date.today().strftime("%d.%m.%Y")
        recs  = status_ws.get_all_records()
        lines = []
        for r in recs:
            if r["Дата"]!=today: continue
            st = r["Статус"]
            per= r["Период"] or r.get("Детали","")
            rea= r["Причина"] or ""
            d1 = f"({per})" if per else ""
            d2 = f"({rea})" if rea else ""
            lines.append(f"{r['Имя']} — {st} {d1} {d2}".strip())
        msg = "Сотрудники:\n"+"\n".join(f"{i+1}. {l}" for i,l in enumerate(lines)) if lines else "Нет записей."
        await update.message.reply_text(msg, reply_markup=markup)
        return ConversationHandler.END

    await update.message.reply_text("Нажми кнопку меню.", reply_markup=markup)
    return CHOOSING

async def save_remote(update, ctx):
    reason = update.message.text.strip()
    name, tg = ctx.user_data["name"], update.effective_user.id
    record_status(name, tg, "🏠 Удалённо", "", reason)
    await update.message.reply_text("✅ Удалённо", reply_markup=markup)
    return ConversationHandler.END

async def save_shoot(update, ctx):
    det = update.message.text.strip()
    name, tg = ctx.user_data["name"], update.effective_user.id
    record_status(name, tg, "🎨 На съёмках", det, "")
    await update.message.reply_text("✅ Съёмки", reply_markup=markup)
    return ConversationHandler.END

async def save_vacation(update, ctx):
    per = update.message.text.strip()
    name, tg = ctx.user_data["name"], update.effective_user.id
    record_status(name, tg, "🌴 В отпуске", per, "")
    await update.message.reply_text(f"✅ Отпуск {per}", reply_markup=markup)
    return ConversationHandler.END

async def cancel(update, ctx):
    await update.message.reply_text("Отменено.", reply_markup=markup)
    return ConversationHandler.END

async def daily_reminder(ctx: ContextTypes.DEFAULT_TYPE):
    today = date.today().strftime("%d.%m.%Y")
    emps  = employees_ws.get_all_records()
    recs  = status_ws.get_all_records()
    done  = {int(r["Telegram ID"]) for r in recs if r["Дата"]==today}
    for r in emps:
        tg = int(r["Telegram ID"])
        if tg in done or is_on_vacation(tg): continue
        try:
            await ctx.bot.send_message(chat_id=tg, text="Пожалуйста, статус на сегодня?", reply_markup=markup)
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
    )
    app.add_handler(conv)

    app.job_queue.run_daily(daily_reminder, time(hour=9, minute=30), days=(0,1,2,3,4))

    # запускаем webhook-сервер
    app.run_webhook(
        listen="0.0.0.0",
        port=PORT,
        url_path=WEBHOOK_PATH,
        webhook_url=f"https://{HOSTNAME}{WEBHOOK_PATH}"
    )

if __name__ == "__main__":
    main()
