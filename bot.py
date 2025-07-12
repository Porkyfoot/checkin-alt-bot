#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import threading
import http.server
import socketserver
import logging
from datetime import datetime, time, date
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

# ====== ЛОГИРОВАНИЕ ======
logging.basicConfig(
    format="%(asctime)s — %(name)s — %(levelname)s — %(message)s",
    level=logging.INFO,
)

# ====== ПЕРЕМЕННЫЕ ОКРУЖЕНИЯ ======
TOKEN = os.environ["TOKEN"]
SPREADSHEET_ID = os.environ["SPREADSHEET_ID"]
EMP_SHEET_NAME = "Employees"
STAT_SHEET_NAME = "Status"

# ====== GOOGLE SHEETS ======
gc = gspread.service_account(filename="/etc/secrets/credentials.json")
employees_ws = gc.open_by_key(SPREADSHEET_ID).worksheet(EMP_SHEET_NAME)
status_ws    = gc.open_by_key(SPREADSHEET_ID).worksheet(STAT_SHEET_NAME)

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

def record_status(name: str, tg_id: int, status: str, detail: str, period: str):
    today = date.today().strftime("%d.%m.%Y")
    status_ws.append_row([today, name, tg_id, status, detail, period, ""])

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
        except:
            continue
        if start<=today<=end:
            return True
    return False

# ====== HANDLERS ======
async def start_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if "name" not in ctx.user_data:
        await update.message.reply_text(
            "Привет! Представься, пожалуйста (имя и фамилия).",
            reply_markup=ReplyKeyboardRemove()
        )
        return CHOOSING
    await update.message.reply_text("Выбери статус:", reply_markup=markup)
    return CHOOSING

async def name_handler(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    name = update.message.text.strip()
    tg_id = update.effective_user.id
    ctx.user_data["name"] = name
    record_employee(name, tg_id)
    await update.message.reply_text(f"Записал `{name}`\nТеперь выбери статус:", reply_markup=markup)
    return CHOOSING

async def choose_status(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    name = ctx.user_data.get("name")
    tg_id = update.effective_user.id

    if not name:
        # на всякий случай
        await update.message.reply_text("Сначала представься, пожалуйста.", reply_markup=ReplyKeyboardRemove())
        return CHOOSING

    if text=='🏠 Удалённо':
        await update.message.reply_text("Причина удалёнки?", reply_markup=ReplyKeyboardRemove())
        return REMOTE_REASON

    if text=='🎨 На съёмках':
        await update.message.reply_text("Опиши детали съёмок:", reply_markup=ReplyKeyboardRemove())
        return SHOOT_DETAIL

    if text=='🌴 В отпуске':
        await update.message.reply_text("Укажи даты (01.07–09.07):", reply_markup=ReplyKeyboardRemove())
        return VACATION_DATES

    if text=='DayOff':
        record_status(name, tg_id, "DayOff", "", "")
        await update.message.reply_text("✅ DayOff записан", reply_markup=markup)
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
            det = r["Детали"] or ""
            per = r["Период"] or ""
            lines.append(f"{r['Имя']} — {r['Статус']} {det or per}".strip())
        msg = "Нет записей." if not lines else "Сотрудники сегодня:\n" + "\n".join(lines)
        await update.message.reply_text(msg, reply_markup=markup)
        return ConversationHandler.END

    await update.message.reply_text("Нажми кнопку меню.", reply_markup=markup)
    return CHOOSING

async def save_remote(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    detail = update.message.text.strip()
    name = ctx.user_data["name"]; tg_id=update.effective_user.id
    record_status(name, tg_id, "🏠 Удалённо", detail, "")
    await update.message.reply_text("✅ Удалённо записано", reply_markup=markup)
    return ConversationHandler.END

async def save_shoot(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    detail = update.message.text.strip()
    name = ctx.user_data["name"]; tg_id=update.effective_user.id
    record_status(name, tg_id, "🎨 На съёмках", detail, "")
    await update.message.reply_text("✅ Съёмки записаны", reply_markup=markup)
    return ConversationHandler.END

async def save_vacation(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    period = update.message.text.strip()
    name = ctx.user_data["name"]; tg_id=update.effective_user.id
    record_status(name, tg_id, "🌴 В отпуске", "", period)
    await update.message.reply_text(f"✅ Отпуск: {period}", reply_markup=markup)
    return ConversationHandler.END

async def cancel(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Отменено.", reply_markup=markup)
    return ConversationHandler.END

# ====== DAILY REMINDER ======
async def daily_reminder(ctx: ContextTypes.DEFAULT_TYPE):
    today = date.today().strftime("%d.%m.%Y")
    emps = employees_ws.get_all_records()
    recs = status_ws.get_all_records()
    done = {int(r["Telegram ID"]) for r in recs if r["Дата"]==today}
    for r in emps:
        tg = int(r["Telegram ID"])
        if tg in done or is_on_vacation(tg): continue
        try:
            await ctx.bot.send_message(chat_id=tg, text="Пожалуйста, выбери статус:", reply_markup=markup)
        except Exception as e:
            logging.error(f"Reminder fail {tg}: {e}")

# ====== SERVE WEB FOR RENDER ======
def serve_web():
    port = int(os.environ.get("PORT", 8000))
    handler = http.server.SimpleHTTPRequestHandler
    with socketserver.TCPServer(("", port), handler) as httpd:
        httpd.serve_forever()

# ====== MAIN ======
def main():
    app = ApplicationBuilder().token(TOKEN).build()

    conv = ConversationHandler(
        entry_points=[CommandHandler("start", start_cmd)],
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

    # планируем джоб
    app.job_queue.run_daily(daily_reminder, time(hour=9, minute=30), days=(0,1,2,3,4))

    # запускаем polling (блокирующая)
    app.run_polling()

if __name__ == "__main__":
    # сначала HTTP-сервер, чтобы Render "увидел" живой порт
    threading.Thread(target=serve_web, daemon=True).start()
    # затем сам бот
    main()
