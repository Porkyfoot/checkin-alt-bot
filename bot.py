#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import threading
import http.server
import socketserver
import logging
from datetime import datetime, date, time
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

# ====== НАСТРОЙКИ ======
TOKEN = os.environ["TOKEN"]
SPREADSHEET_ID = os.environ["SPREADSHEET_ID"]
EMP_SHEET_NAME = "Employees"
STAT_SHEET_NAME = "Status"
CRED_PATH = "/etc/secrets/credentials.json"  # Render: загрузите сюда JSON вашего сервис-аккаунта

# ====== GSheets ======
gc = gspread.service_account(filename=CRED_PATH)
employees_ws = gc.open_by_key(SPREADSHEET_ID).worksheet(EMP_SHEET_NAME)
status_ws    = gc.open_by_key(SPREADSHEET_ID).worksheet(STAT_SHEET_NAME)

# ====== ЛОГИ ======
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)

# ====== Conversation States ======
CHOOSING, REMOTE_REASON, SHOOT_DETAIL, VACATION_DATES = range(4)

# ====== Клавиатура ======
main_keyboard = [
    ['🏢 Уже в офисе', '🏠 Удалённо'],
    ['🎨 На съёмках',    '🌴 В отпуске'],
    ['📋 Список сотрудников', 'DayOff']
]
markup = ReplyKeyboardMarkup(main_keyboard, one_time_keyboard=True, resize_keyboard=True)

# ====== Утилиты для GSheets ======
def record_employee(name: str, tg_id: int):
    recs = employees_ws.get_all_records()
    ids = {int(r["Telegram ID"]) for r in recs}
    if tg_id not in ids:
        employees_ws.append_row([name, tg_id])

def record_status(name: str, tg_id: int, status: str, period: str, reason: str):
    today = date.today().strftime("%d.%m.%Y")
    status_ws.append_row([today, name, tg_id, status, period, reason, ""])

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
            start, end = parse_vacation(r["Период"] or r["Причина"])
        except:
            continue
        if start <= today <= end:
            return True
    return False

# ====== Handlers ======
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if "name" not in context.user_data:
        await update.message.reply_text(
            "Привет! Для начала представься: укажи имя и фамилию на русском.",
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
    await update.message.reply_text(
        f"✅ Записали: {name}\nТеперь выбери статус:",
        reply_markup=markup
    )
    return CHOOSING

async def choose_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    name = context.user_data.get("name")
    tg_id = update.effective_user.id

    if not name:
        await update.message.reply_text("Нужно сперва указать имя через /start.")
        return CHOOSING

    if text == '🏠 Удалённо':
        await update.message.reply_text("По какой причине вы работаете удалённо?", reply_markup=ReplyKeyboardRemove())
        return REMOTE_REASON

    if text == '🎨 На съёмках':
        await update.message.reply_text("Опиши, что за съёмки:", reply_markup=ReplyKeyboardRemove())
        return SHOOT_DETAIL

    if text == '🌴 В отпуске':
        await update.message.reply_text("Какие даты отпуска (напр. 01.07–09.07)?", reply_markup=ReplyKeyboardRemove())
        return VACATION_DATES

    if text == 'DayOff':
        record_status(name, tg_id, "DayOff", "", "")
        await update.message.reply_text("✅ Записано: DayOff", reply_markup=markup)
        return ConversationHandler.END

    if text == '🏢 Уже в офисе':
        now = datetime.now().strftime("%H:%M")
        record_status(name, tg_id, "🏢 Уже в офисе", now, "")
        await update.message.reply_text(f"✅ Записано: уже в офисе ({now})", reply_markup=markup)
        return ConversationHandler.END

    if text == '📋 Список сотрудников':
        today = date.today().strftime("%d.%m.%Y")
        lines = []
        for r in status_ws.get_all_records():
            if r["Дата"] != today: continue
            period = r["Период"] or r["Время прибытия"] or ""
            reason = r["Причина"] or ""
            lines.append(
                f"{r['Имя']} — {r['Статус']}"
                + (f" ({period})" if period else "")
                + (f" ({reason})" if reason else "")
            )
        msg = "Список сотрудников сегодня:\n" + "\n".join(f"{i+1}. {l}" for i,l in enumerate(lines)) \
              if lines else "На сегодня нет ни одной отметки."
        await update.message.reply_text(msg, reply_markup=markup)
        return ConversationHandler.END

    await update.message.reply_text("Нажми кнопку меню.", reply_markup=markup)
    return CHOOSING

async def save_remote(update: Update, context: ContextTypes.DEFAULT_TYPE):
    reason = update.message.text.strip()
    name = context.user_data["name"]
    tg_id = update.effective_user.id
    record_status(name, tg_id, "🏠 Удалённо", "", reason)
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
    record_status(name, tg_id, "🌴 В отпуске", period, "")
    await update.message.reply_text(f"✅ Записано: отпуск {period}", reply_markup=markup)
    return ConversationHandler.END

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Отменено.", reply_markup=markup)
    return ConversationHandler.END

# ====== Ежедневный напоминатель ======
async def daily_reminder(context: ContextTypes.DEFAULT_TYPE):
    today = date.today().strftime("%d.%m.%Y")
    done = {int(r["Telegram ID"]) for r in status_ws.get_all_records() if r["Дата"] == today}
    for r in employees_ws.get_all_records():
        tg_id = int(r["Telegram ID"])
        if tg_id in done or is_on_vacation(tg_id):
            continue
        try:
            await context.bot.send_message(chat_id=tg_id, text="Пожалуйста, выбери статус на сегодня:", reply_markup=markup)
        except Exception as e:
            logging.error(f"Напоминание {tg_id} провалилось: {e}")

# ====== Вспомогательный HTTP-сервер для Render ======
def start_http_server():
    port = int(os.environ.get("PORT", 8000))
    handler = http.server.SimpleHTTPRequestHandler
    with socketserver.TCPServer(("0.0.0.0", port), handler) as httpd:
        httpd.serve_forever()

# ====== Основная точка входа ======
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

    # запускаем HTTP-сервер в фоне, чтобы Render видел открытый порт
    threading.Thread(target=start_http_server, daemon=True).start()

    # планируем ежедневный джоб (понедельник–пятница в 9:30)
    app.job_queue.run_daily(daily_reminder, time(hour=9, minute=30), days=(0,1,2,3,4))

    # запускаем polling
    app.run_polling()

if __name__ == "__main__":
    main()
