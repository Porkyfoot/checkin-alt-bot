#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import logging
import re
from datetime import datetime, date, time

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

# ==== ПЕРЕМЕННЫЕ ОКРУЖЕНИЯ ====
TOKEN = os.environ["TOKEN"]
SPREADSHEET_ID = os.environ["SPREADSHEET_ID"]
CREDS_PATH = "/etc/secrets/credentials.json"  # путь к сервисному ключу в Render

# ==== GOOGLE SHEETS ====
gc = gspread.service_account(filename=CREDS_PATH)
EMP_SHEET = "Employees"
STAT_SHEET = "Status"
employees_ws = gc.open_by_key(SPREADSHEET_ID).worksheet(EMP_SHEET)
status_ws    = gc.open_by_key(SPREADSHEET_ID).worksheet(STAT_SHEET)

# ==== ЛОГИРОВАНИЕ ====
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)

# ==== STATES ====
CHOOSING, REMOTE_REASON, SHOOT_DETAIL, VACATION_DATES = range(4)

# ==== KEYBOARD ====
main_keyboard = [
    ['🏢 Уже в офисе', '🏠 Удалённо'],
    ['🎨 На съёмках',    '🌴 В отпуске'],
    ['📋 Список сотрудников', '🛌 DayOff']
]
markup = ReplyKeyboardMarkup(main_keyboard, one_time_keyboard=True, resize_keyboard=True)

# ==== HELPERS ====

def record_employee(name: str, tg_id: int):
    recs = employees_ws.get_all_records()
    ids = {int(r["Telegram ID"]) for r in recs}
    if tg_id not in ids:
        employees_ws.append_row([name, tg_id])

def record_status(name: str, tg_id: int, status: str, detail: str, period: str):
    today = date.today().strftime("%d.%m.%Y")
    status_ws.append_row([today, name, tg_id, status, detail, period])

def parse_vacation(text: str):
    parts = re.split(r"[–-]", text.strip())
    def to_date(s):
        for fmt in ("%d.%m.%Y","%d.%m"):
            try:
                d = datetime.strptime(s.strip(), fmt)
                if fmt=="%d.%m":
                    d = d.replace(year=date.today().year)
                return d.date()
            except ValueError:
                continue
        raise ValueError(f"не знаю формат даты {s}")
    return to_date(parts[0]), to_date(parts[1])

def is_on_vacation(tg_id: int):
    today = date.today()
    recs = status_ws.get_all_records()
    for r in recs:
        if int(r["Telegram ID"])!=tg_id or r["Статус"]!="🌴 В отпуске":
            continue
        try:
            start,end = parse_vacation(r["Период"] or r["Детали"])
        except:
            continue
        if start<=today<=end:
            return True
    return False

# ==== HANDLERS ====

async def start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    # всегда предлагаем заново, если нет имени
    if "name" not in ctx.user_data:
        await update.message.reply_text(
            "Привет! Представься, пожалуйста (Имя и фамилия):",
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
    await update.message.reply_text(f"✅ Записали: {name}\nТеперь выбери статус:", reply_markup=markup)
    return CHOOSING

async def choose_status(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    user = update.effective_user
    name = ctx.user_data.get("name")
    if not name:
        # на всякий случай — если кто-то вдруг пропустил ввод имени
        return await name_handler(update, ctx)

    if text=='🏠 Удалённо':
        await update.message.reply_text("По какой причине работаем удалённо?", reply_markup=ReplyKeyboardRemove())
        return REMOTE_REASON

    if text=='🎨 На съёмках':
        await update.message.reply_text("Опиши, что за съёмки (клиент/детали):", reply_markup=ReplyKeyboardRemove())
        return SHOOT_DETAIL

    if text=='🌴 В отпуске':
        await update.message.reply_text("Укажи период отпуска (например 01.07–09.07):", reply_markup=ReplyKeyboardRemove())
        return VACATION_DATES

    if text=='🛌 DayOff':
        record_status(name, user.id, "🛌 DayOff", "", "")
        await update.message.reply_text("✅ Записано: DayOff", reply_markup=markup)
        return ConversationHandler.END

    if text=='🏢 Уже в офисе':
        now = datetime.now().strftime("%H:%M")
        record_status(name, user.id, "🏢 Уже в офисе", now, "")
        await update.message.reply_text(f"✅ Записано: уже в офисе ({now})", reply_markup=markup)
        return ConversationHandler.END

    if text=='📋 Список сотрудников':
        today = date.today().strftime("%d.%m.%Y")
        recs = status_ws.get_all_records()
        lines = []
        for r in recs:
            if r["Дата"]!=today:
                continue
            det = r["Детали"] or ""
            per = r["Период"] or ""
            lines.append(
                f"{r['Имя']} — {r['Статус']}" +
                (f" ({det})" if det else "") +
                (f" [{per}]" if per else "")
            )
        msg = "На сегодня нет отметок." if not lines else "Список сотрудников:\n" + "\n".join(f"{i+1}. {l}" for i,l in enumerate(lines))
        await update.message.reply_text(msg, reply_markup=markup)
        return ConversationHandler.END

    # если получили что-то непонятное
    await update.message.reply_text("Пожалуйста, выбери кнопку меню.", reply_markup=markup)
    return CHOOSING

async def save_remote(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    reason = update.message.text.strip()
    name = ctx.user_data["name"]
    record_status(name, update.effective_user.id, "🏠 Удалённо", reason, "")
    await update.message.reply_text("✅ Записано: удалённо", reply_markup=markup)
    return ConversationHandler.END

async def save_shoot(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    detail = update.message.text.strip()
    name = ctx.user_data["name"]
    record_status(name, update.effective_user.id, "🎨 На съёмках", detail, "")
    await update.message.reply_text("✅ Записано: на съёмках", reply_markup=markup)
    return ConversationHandler.END

async def save_vacation(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    period = update.message.text.strip()
    name = ctx.user_data["name"]
    record_status(name, update.effective_user.id, "🌴 В отпуске", "", period)
    await update.message.reply_text(f"✅ Записано: отпуск {period}", reply_markup=markup)
    return ConversationHandler.END

async def cancel(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("❌ Отменено.", reply_markup=markup)
    return ConversationHandler.END

async def daily_reminder(ctx: ContextTypes.DEFAULT_TYPE):
    today = date.today().strftime("%d.%m.%Y")
    emps = employees_ws.get_all_records()
    recs = status_ws.get_all_records()
    done = {int(r["Telegram ID"]) for r in recs if r["Дата"]==today}
    for r in emps:
        tg = int(r["Telegram ID"])
        if tg in done or is_on_vacation(tg):
            continue
        try:
            await ctx.bot.send_message(chat_id=tg, text="Пожалуйста, выбери статус на сегодня:", reply_markup=markup)
        except Exception as e:
            logging.error(f"Не могу напомнить {tg}: {e}")

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

    # ежедневный джоб в 9:30 пн–пт
    remind_time = time(hour=9, minute=30)
    app.job_queue.run_daily(daily_reminder, remind_time, days=(0,1,2,3,4))

    app.run_polling()

if __name__ == "__main__":
    main()
