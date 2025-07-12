#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import logging
from datetime import datetime, time, date
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

# ====== НАСТРОЙКИ GOOGLE SHEETS ======
# Поместите JSON-ключ сервисного аккаунта по пути /etc/secrets/credentials.json
gc = gspread.service_account(filename="/etc/secrets/credentials.json")
SPREADSHEET = "checkin-alt-bot"  # имя вашей таблицы
EMP_SHEET_NAME = "Employees"
STAT_SHEET_NAME = "Status"

# открываем два листа: список сотрудников и лог статусов
employees_ws = gc.open(SPREADSHEET).worksheet(EMP_SHEET_NAME)
status_ws    = gc.open(SPREADSHEET).worksheet(STAT_SHEET_NAME)

# ====== ЛОГГИРОВАНИЕ ======
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)

# ====== СТЕЙТЫ ДЛЯ ConversationHandler ======
CHOOSING, REMOTE_REASON, SHOOT_DETAIL, VACATION_DATES = range(4)

# ====== КЛАВИАТУРА МЕНЮ ======
main_keyboard = [
    ['🏢 Уже в офисе', '🏠 Удалённо'],
    ['🎨 На съёмках',    '🌴 В отпуске'],
    ['📋 Список сотрудников', 'DayOff']
]
markup = ReplyKeyboardMarkup(main_keyboard, one_time_keyboard=True, resize_keyboard=True)


# ====== УТИЛИТЫ ДЛЯ GOOGLE SHEETS ======

def record_employee(name: str, tg_id: int):
    """Добавить нового сотрудника в Employees, если его там нет."""
    records = employees_ws.get_all_records()
    ids = {int(r["Telegram ID"]) for r in records}
    if tg_id not in ids:
        employees_ws.append_row([name, tg_id])

def record_status(name: str, tg_id: int, status: str, reason: str, period: str):
    """Добавить строку в Status."""
    today = date.today().strftime("%d.%m.%Y")
    status_ws.append_row([today, name, tg_id, status, period, reason, ""])


# ====== HELPERS ======

def parse_vacation(text: str):
    """Парсит «01.07–09.07» или «01.07.2025–09.07.2025» → два date."""
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
    start, end = to_date(parts[0]), to_date(parts[1])
    return start, end

def is_on_vacation(tg_id: int):
    """Проверяет по Status, есть ли активный отпуск на сегодня."""
    today = date.today()
    recs = status_ws.get_all_records()
    for r in recs:
        if int(r["Telegram ID"]) != tg_id:
            continue
        if r["Статус"] != "🌴 В отпуске":
            continue
        # парсим период из колонки «Причина» или «Период»
        try:
            start, end = parse_vacation(r["Причина"])
        except:
            continue
        if start <= today <= end:
            return True
    return False

# ====== HANDLERS ======

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    # если имя ещё не сохранили — спрашиваем
    if "name" not in context.user_data:
        await update.message.reply_text(
            "Привет! Для начала представься: укажи имя и фамилию на русском.",
            reply_markup=ReplyKeyboardRemove()
        )
        return CHOOSING
    # иначе сразу в меню
    await update.message.reply_text("Выбери статус:", reply_markup=markup)
    return CHOOSING

async def name_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # получаем имя и сохраняем
    text = update.message.text.strip()
    tg_id = update.effective_user.id
    context.user_data["name"] = text
    record_employee(text, tg_id)
    await update.message.reply_text(
        f"✅ Записали: {text}\n\nТеперь выбери свой статус:",
        reply_markup=markup
    )
    return CHOOSING

async def choose_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    user_id = update.effective_user.id
    name = context.user_data["name"]
    
    if text == '🏠 Удалённо':
        await update.message.reply_text("По какой причине вы работаете удалённо?", reply_markup=ReplyKeyboardRemove())
        return REMOTE_REASON

    if text == '🎨 На съёмках':
        await update.message.reply_text("Опиши, что за съёмки:", reply_markup=ReplyKeyboardRemove())
        return SHOOT_DETAIL

    if text == '🌴 В отпуске':
        await update.message.reply_text("Укажи даты отпуска (например 01.07–09.07):", reply_markup=ReplyKeyboardRemove())
        return VACATION_DATES

    if text == 'DayOff':
        record_status(name, user_id, "DayOff", "", "")
        await update.message.reply_text("✅ Записано: DayOff", reply_markup=markup)
        return ConversationHandler.END

    if text == '🏢 Уже в офисе':
        now = datetime.now().strftime("%H:%M")
        record_status(name, user_id, "🏢 Уже в офисе", "", now)
        await update.message.reply_text(f"✅ Записано: уже в офисе ({now})", reply_markup=markup)
        return ConversationHandler.END

    if text == '📋 Список сотрудников':
        # собираем все записи за сегодня из Status
        today = date.today().strftime("%d.%m.%Y")
        recs = status_ws.get_all_records()
        lines = []
        for r in recs:
            if r["Дата"] != today:
                continue
            period = r["Время прибытия"] or r["Период"] or ""
            reason = r["Причина"] or ""
            lines.append(f"{r['Имя']} — {r['Статус']} {f'({period})' if period else ''} {f'({reason})' if reason else ''}".strip())
        if not lines:
            msg = "На сегодня нет ни одной отметки."
        else:
            msg = "Список сотрудников сегодня:\n" + "\n".join(f"{i+1}. {line}" for i, line in enumerate(lines))
        await update.message.reply_text(msg, reply_markup=markup)
        return ConversationHandler.END

    # на всякий случай
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
    record_status(name, tg_id, "🌴 В отпуске", period, "")
    await update.message.reply_text(f"✅ Записано: отпуск {period}", reply_markup=markup)
    return ConversationHandler.END

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Отменено.", reply_markup=markup)
    return ConversationHandler.END


# ====== ЕЖЕДНЕВНОЕ НАПОМИНАНИЕ ======

async def daily_reminder(context: ContextTypes.DEFAULT_TYPE):
    """В 9:30 по будням пушим всем, кто ещё не отчитался и не в отпуске."""
    today = date.today().strftime("%d.%m.%Y")
    # 1) получаем список всех сотрудников
    emps = employees_ws.get_all_records()
    # 2) получаем статусы за сегодня
    recs = status_ws.get_all_records()
    done_ids = {int(r["Telegram ID"]) for r in recs if r["Дата"] == today}
    for r in emps:
        tg_id = int(r["Telegram ID"])
        if tg_id in done_ids:
            continue
        if is_on_vacation(tg_id):
            continue
        try:
            await context.bot.send_message(
                chat_id=tg_id,
                text="Пожалуйста, выбери статус на сегодня:",
                reply_markup=markup
            )
        except Exception as e:
            logging.error(f"Не удалось отправить напоминание {tg_id}: {e}")


# ====== MAIN ======

def main():
    TOKEN = "<ВАШ_ТОКЕН>"
    app = ApplicationBuilder().token(TOKEN).build()

    # ConversationHandler для всего процесса
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

    # После старта приложения планируем ежедневный джоб
    remind_time = time(hour=9, minute=30)
    app.job_queue.run_daily(daily_reminder, remind_time, days=(0,1,2,3,4))

    app.run_polling()

if __name__ == "__main__":
    main()
