#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import logging
import re
from datetime import datetime, date, time as dtime

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

# ====== НАСТРОЙКИ GOOGLE SHEETS ======
gc = gspread.service_account(filename="/etc/secrets/credentials.json")
SPREADSHEET_ID = os.environ["SPREADSHEET_ID"]
EMP_SHEET_NAME  = "Employees"
STAT_SHEET_NAME = "Status"

emp_ws   = gc.open_by_key(SPREADSHEET_ID).worksheet(EMP_SHEET_NAME)
stat_ws  = gc.open_by_key(SPREADSHEET_ID).worksheet(STAT_SHEET_NAME)

# ====== ЛОГГИРОВАНИЕ ======
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)

# ====== СТЕЙТЫ ======
CHOOSING, REMOTE, SHOOT, VAC = range(4)

# ====== КЛАВИАТУРА ======
kb = [
    ['🏢 Уже в офисе', '🏠 Удалённо'],
    ['🎨 На съёмках',    '🌴 В отпуске'],
    ['📋 Список сотрудников', 'DayOff'],
]
markup = ReplyKeyboardMarkup(kb, resize_keyboard=True, one_time_keyboard=True)

# ====== УТИЛИТЫ ======
def record_employee(name: str, tg_id: int):
    recs = emp_ws.get_all_records()
    ids  = {int(r["Telegram ID"]) for r in recs}
    if tg_id not in ids:
        emp_ws.append_row([name, tg_id])

def record_status(name, tg_id, status, detail, reason):
    today = date.today().strftime("%d.%m.%Y")
    stat_ws.append_row([today, name, tg_id, status, detail, reason])

def parse_vac(text: str):
    parts = re.split(r"[–-]", text.strip())
    def to_dt(s):
        for fmt in ("%d.%m.%Y","%d.%m"):
            try:
                dt = datetime.strptime(s.strip(),fmt).date()
                if fmt=="%d.%m":
                    dt = dt.replace(year=date.today().year)
                return dt
            except:
                pass
        raise ValueError
    return to_dt(parts[0]), to_dt(parts[1])

def is_on_vac(tg_id:int):
    today = date.today()
    for r in stat_ws.get_all_records():
        if int(r["Telegram ID"])!=tg_id: continue
        if r["Статус"]!="🌴 В отпуске": continue
        try:
            start,end = parse_vac(r["Причина"])
        except: continue
        if start<=today<=end: return True
    return False

# ====== HANDLERS ======
async def start(update:Update, ctx:ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if "name" not in ctx.user_data:
        await update.message.reply_text(
            "Привет! Представься: имя и фамилию на русском.",
            reply_markup=ReplyKeyboardRemove()
        )
        return CHOOSING
    await update.message.reply_text("Выбери статус:", reply_markup=markup)
    return CHOOSING

async def name_h(update:Update, ctx:ContextTypes.DEFAULT_TYPE):
    name  = update.message.text.strip()
    tg_id = update.effective_user.id
    ctx.user_data["name"] = name
    record_employee(name, tg_id)
    await update.message.reply_text(
        f"✅ Записали: {name}\nТеперь выбери статус:", reply_markup=markup
    )
    return CHOOSING

async def choose(update:Update, ctx:ContextTypes.DEFAULT_TYPE):
    txt   = update.message.text
    tg_id = update.effective_user.id
    name  = ctx.user_data.get("name","?")
    if txt=="🏠 Удалённо":
        await update.message.reply_text("Причина удалёнки?", reply_markup=ReplyKeyboardRemove())
        return REMOTE
    if txt=="🎨 На съёмках":
        await update.message.reply_text("Что за съёмки?", reply_markup=ReplyKeyboardRemove())
        return SHOOT
    if txt=="🌴 В отпуске":
        await update.message.reply_text("Даты отпускa (01.07–09.07):", reply_markup=ReplyKeyboardRemove())
        return VAC
    if txt=="🏢 Уже в офисе":
        now = datetime.now().strftime("%H:%M")
        record_status(name, tg_id, "🏢 В офисе", now, "")
        await update.message.reply_text(f"✅ Офис: {now}", reply_markup=markup)
        return ConversationHandler.END
    if txt=="DayOff":
        record_status(name, tg_id, "DayOff", "", "")
        await update.message.reply_text("✅ DayOff", reply_markup=markup)
        return ConversationHandler.END
    if txt=="📋 Список сотрудников":
        today = date.today().strftime("%d.%m.%Y")
        lines = []
        for r in stat_ws.get_all_records():
            if r["Дата"]!=today: continue
            det = r["Детали"] or ""
            rea = r["Причина"] or ""
            lines.append(
              f"{r['Имя']} — {r['Статус']}"+(
              f" ({det})" if det else "")+(
              f" ({rea})" if rea else "")
            )
        msg = "Нет записей." if not lines else "Сотрудники:\n" + "\n".join(lines)
        await update.message.reply_text(msg, reply_markup=markup)
        return ConversationHandler.END
    # иначе
    await update.message.reply_text("Нажми на кнопку меню.", reply_markup=markup)
    return CHOOSING

async def save_remote(update:Update, ctx:ContextTypes.DEFAULT_TYPE):
    rea = update.message.text.strip()
    name,tg = ctx.user_data["name"], update.effective_user.id
    record_status(name,tg,"🏠 Удалённо","",rea)
    await update.message.reply_text("✅ Удалёнка",reply_markup=markup)
    return ConversationHandler.END

async def save_shoot(update:Update, ctx:ContextTypes.DEFAULT_TYPE):
    det = update.message.text.strip()
    name,tg = ctx.user_data["name"], update.effective_user.id
    record_status(name,tg,"🎨 На съёмках",det,"")
    await update.message.reply_text("✅ Съёмки",reply_markup=markup)
    return ConversationHandler.END

async def save_vac(update:Update, ctx:ContextTypes.DEFAULT_TYPE):
    period = update.message.text.strip()
    name,tg = ctx.user_data["name"], update.effective_user.id
    record_status(name,tg,"🌴 В отпуске",period,"")
    await update.message.reply_text(f"✅ Отпуск: {period}",reply_markup=markup)
    return ConversationHandler.END

async def cancel(update:Update, ctx:ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Отменено.",reply_markup=markup)
    return ConversationHandler.END

# ====== MAIN ======

def main():
    TOKEN = os.environ["TOKEN"]
    APP_URL = os.environ["APP_URL"]  # например: https://your-app.onrender.com

    app = ApplicationBuilder()\
        .token(TOKEN)\
        .build()

    conv = ConversationHandler(
        entry_points=[CommandHandler("start", start)],
        states={
            CHOOSING: [MessageHandler(filters.TEXT & ~filters.COMMAND, choose)],
            REMOTE:   [MessageHandler(filters.TEXT & ~filters.COMMAND, save_remote)],
            SHOOT:    [MessageHandler(filters.TEXT & ~filters.COMMAND, save_shoot)],
            VAC:      [MessageHandler(filters.TEXT & ~filters.COMMAND, save_vac)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
        per_user=True,
    )
    app.add_handler(conv)

    # устанавливаем вебхук
    webhook_path = TOKEN.split(":")[0]  # какой-нибудь уникальный путь
    final_url   = f"{APP_URL}/{webhook_path}"
    app.bot.set_webhook(final_url)

    # запускаем HTTP-сервер, который будет принимать POST /<webhook_path>
    app.run_webhook(
        listen="0.0.0.0",
        port=int(os.environ.get("PORT", 80)),
        webhook_path=f"/{webhook_path}"
    )

if __name__ == "__main__":
    main()
