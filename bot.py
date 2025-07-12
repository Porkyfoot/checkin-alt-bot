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
from telegram import ReplyKeyboardMarkup, ReplyKeyboardRemove, Update
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    filters,
    ConversationHandler,
    ContextTypes,
)

# ====== CONFIGURATION ======
# Telegram Bot Token and Google Spreadsheet ID from environment variables
TOKEN = os.environ["TOKEN"]
SPREADSHEET_ID = os.environ["SPREADSHEET_ID"]
# Path to service account JSON key mounted in Render secrets
CREDENTIALS_PATH = "/etc/secrets/credentials.json"

# ====== GOOGLE SHEETS SETUP ======
gc = gspread.service_account(filename=CREDENTIALS_PATH)
# Two worksheets: Employees list and daily Status log
employees_ws = gc = gc = gc = gc.open_by_key(SPREADSHEET_ID).worksheet("Employees")
status_ws    = gc.open_by_key(SPREADSHEET_ID).worksheet("Status")

# ====== LOGGING ======
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)

# ====== STATES ======
CHOOSING, REMOTE_REASON, SHOOT_DETAIL, VACATION_DATES = range(4)

# ====== REPLY KEYBOARD ======
main_keyboard = [
    ['🏢 Уже в офисе', '🏠 Удалённо'],
    ['🎨 На съёмках',    '🌴 В отпуске'],
    ['📋 Список сотрудников', '🌙 DayOff']
]
markup = ReplyKeyboardMarkup(main_keyboard, one_time_keyboard=True, resize_keyboard=True)

# ====== GOOGLE SHEETS HELPERS ======

def record_employee(name: str, tg_id: int):
    """Добавляет нового сотрудника в Employees, если его там нет."""
    records = employees_ws.get_all_records()
    ids = {int(r["Телеграм ID"]) for r in records}
    if tg_id not in ids:
        employees_ws.append_row([name, tg_id])


def record_status(name: str, tg_id: int, status: str, details: str, reason: str):
    """Логирует новую строку в Status."""
    today = date.today().strftime("%d.%m.%Y")
    status_ws.append_row([today, name, tg_id, status, details, reason])

# ====== VACATION PARSING ======

def parse_vacation(text: str):
    """Парсит строки вида "01.07-09.07" или с годом."""
    parts = re.split(r"[–-]", text.strip())
    def to_date(s: str):
        for fmt in ("%d.%m.%Y", "%d.%m"):
            try:
                dt = datetime.strptime(s.strip(), fmt)
                if fmt == "%d.%m":
                    dt = dt.replace(year=date.today().year)
                return dt.date()
            except ValueError:
                continue
        raise ValueError(f"Не могу распарсить дату: {s}")
    return to_date(parts[0]), to_date(parts[1])


def is_on_vacation(tg_id: int) -> bool:
    """Проверяет, есть ли активный отпуск для пользователя сегодня."""
    today = date.today()
    for r in status_ws.get_all_records():
        if int(r["Телеграм ID"]) != tg_id:
            continue
        if r["Статус"] != "🌴 В отпуске":
            continue
        try:
            start, end = parse_vacation(r["Причина"])
            if start <= today <= end:
                return True
        except Exception:
            pass
    return False

# ====== HANDLERS ======

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if "name" not in context.user_data:
        await update.message.reply_text(
            "Привет! Представься: имя и фамилию, пожалуйста.",
            reply_markup=ReplyKeyboardRemove()
        )
        return CHOOSING
    # уже есть имя → меню
    await update.message.reply_text("Выбери статус:", reply_markup=markup)
    return CHOOSING


async def name_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    name = update.message.text.strip()
    tg_id = update.effective_user.id
    context.user_data["name"] = name
    record_employee(name, tg_id)
    await update.message.reply_text(
        f"✅ Записали имя: {name}\nТеперь выбери статус:",
        reply_markup=markup
    )
    return CHOOSING


async def name_or_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # если нет имени — первым сообщением сохранённое
    if "name" not in context.user_data:
        return await name_handler(update, context)
    # иначе обрабатываем выбор статуса
    return await choose_status(update, context)


async def choose_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    tg_id = update.effective_user.id
    name = context.user_data["name"]

    if text == '🏠 Удалённо':
        await update.message.reply_text("По какой причине работаешь удалённо?", reply_markup=ReplyKeyboardRemove())
        return REMOTE_REASON
    if text == '🎨 На съёмках':
        await update.message.reply_text("Опиши, что за съёмки:", reply_markup=ReplyKeyboardRemove())
        return SHOOT_DETAIL
    if text == '🌴 В отпуске':
        await update.message.reply_text("Укажи даты отпуска (напр. 01.07-09.07):", reply_markup=ReplyKeyboardRemove())
        return VACATION_DATES
    if text == '🌙 DayOff':
        record_status(name, tg_id, "🌙 DayOff", "", "")
        await update.message.reply_text("✅ Записано: DayOff", reply_markup=markup)
        return ConversationHandler.END
    if text == '🏢 Уже в офисе':
        now = datetime.now().strftime("%H:%M")
        record_status(name, tg_id, "🏢 Уже в офисе", now, "")
        await update.message.reply_text(f"✅ Записано: в офисе ({now})", reply_markup=markup)
        return ConversationHandler.END
    if text == '📋 Список сотрудников':
        today = date.today().strftime("%d.%m.%Y")
        recs = status_ws.get_all_records()
        lines = []
        for r in recs:
            if r["Дата"] != today:
                continue
            det = r.get("Детали", "")
            reason = r.get("Причина", "")
            part = f"({det})" if det else ""
            part += f" ({reason})" if reason else ""
            lines.append(f"{r['Имя']} — {r['Статус']} {part}".strip())
        msg = "На сегодня нет отметок." if not lines else "Список сотрудников сегодня:\n" + "\n".join(f"{i+1}. {l}" for i,l in enumerate(lines))
        await update.message.reply_text(msg, reply_markup=markup)
        return ConversationHandler.END
    # неизвестный ввод
    await update.message.reply_text("Пожалуйста, выбери кнопку из меню.", reply_markup=markup)
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

# ====== DAILY REMINDER JOB ======

async def daily_reminder(context: ContextTypes.DEFAULT_TYPE):
    today = date.today().strftime("%d.%m.%Y")
    emps = employees_ws.get_all_records()
    recs = status_ws.get_all_records()
    done = {int(r['Телеграм ID']) for r in recs if r['Дата']==today}
    for r in emps:
        tg_id = int(r['Телеграм ID'])
        if tg_id in done or is_on_vacation(tg_id):
            continue
        try:
            await context.bot.send_message(chat_id=tg_id, text="Пожалуйста, выбери статус на сегодня:", reply_markup=markup)
        except Exception as e:
            logging.error(f"Не удалось отправить напоминание пользователю {tg_id}: {e}")

# ====== MAIN ======

def main():
    app = ApplicationBuilder().token(TOKEN).build()

    conv = ConversationHandler(
        entry_points=[CommandHandler("start", start)],
        states={
            CHOOSING:      [MessageHandler(filters.TEXT & ~filters.COMMAND, name_or_status)],
            REMOTE_REASON: [MessageHandler(filters.TEXT & ~filters.COMMAND, save_remote)],
            SHOOT_DETAIL:  [MessageHandler(filters.TEXT & ~filters.COMMAND, save_shoot)],
            VACATION_DATES:[MessageHandler(filters.TEXT & ~filters.COMMAND, save_vacation)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )
    app.add_handler(conv)

    # Schedule daily reminder Mon-Fri at 09:30
    remind_time = time(hour=9, minute=30)
    app.job_queue.run_daily(daily_reminder, remind_time, days=(0,1,2,3,4))

    app.run_polling()

# ====== HTTP SERVER FOR RENDER ======

def serve_web():
    port = int(os.environ.get("PORT", 8000))
    handler = http.server.SimpleHTTPRequestHandler
    with socketserver.TCPServer(("0.0.0.0", port), handler) as httpd:
        httpd.serve_forever()

if __name__ == "__main__":
    threading.Thread(target=serve_web, daemon=True).start()
    main()
