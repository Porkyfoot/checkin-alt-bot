import os
from datetime import datetime, time
from telegram import (
    __version__ as ptb_ver, ReplyKeyboardMarkup, ReplyKeyboardRemove, KeyboardButton
)
from telegram.ext import (
    ApplicationBuilder, CommandHandler, ContextTypes,
    MessageHandler, ConversationHandler, filters
)
import gspread
from oauth2client.service_account import ServiceAccountCredentials

# ------------------ КОНФИГ ------------------
SPREADSHEET_ID = os.getenv("SPREADSHEET_ID", "ваш-ID-таблицы")
TOKEN          = os.getenv("TOKEN",          "ваш-бот-токен")
SECRET_JSON    = os.getenv("SECRET_JSON",    "/etc/secrets/credentials.json")

# Названия листов
EMP_SHEET    = "Employees"
DATA_SHEET   = "Daily"   # где хранятся метки

# Константы состояний ConversationHandler
(
    REG_NAME,
    CHOOSING,
    LATE_TIME, LATE_REASON,
    VAC_DATES,
    SHOOT_DETAIL,
    REMOTE_REASON
) = range(7)

# ------------------ GOOGLE SHEETS ------------------
scope = ["https://spreadsheets.google.com/feeds",
         "https://www.googleapis.com/auth/drive"]
creds = ServiceAccountCredentials.from_json_keyfile_name(SECRET_JSON, scope)
gc    = gspread.authorize(creds)

emp_ws  = gc.open_by_key(SPREADSHEET_ID).worksheet(EMP_SHEET)
data_ws = gc.open_by_key(SPREADSHEET_ID).worksheet(DATA_SHEET)

# ------------------ КЛАВИАТУРЫ ------------------
MAIN_KEYS = [
    ["⏰ Задерживаюсь", "🛌 DayOff"],
    ["🌴 В отпуске",    "🎨 На съёмках"],
    ["💻 Удалённо"]
]
main_kb = ReplyKeyboardMarkup(MAIN_KEYS, one_time_keyboard=True, resize_keyboard=True)

# ------------------ ХЕЛПЕРЫ ------------------
def append_row(name, tid, status, details="", reason=""):
    """Записать в DATA_SHEET новую строку."""
    today = datetime.now().strftime("%d.%m.%Y")
    data_ws.append_row([today, name, str(tid), status, details, reason])

async def show_menu(update, context):
    await update.message.reply_text(
        "Выберите статус:",
        reply_markup=main_kb
    )
    return CHOOSING

# ------------------ ОБРАБОТЧИКИ ------------------
async def start(update: ContextTypes.DEFAULT_TYPE, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.message.from_user.id)
    # проверяем, есть ли уже в Employees
    records = emp_ws.get_all_records()
    for r in records:
        if str(r.get("Telegram ID")) == user_id:
            context.user_data["name"] = r["Name"]
            return await show_menu(update, context)

    # если нет — регистрируем
    await update.message.reply_text(
        "Привет! Я бот для ежедневных отметок.\n"
        "Пожалуйста, представьтесь (Имя и фамилия):",
        reply_markup=ReplyKeyboardRemove()
    )
    return REG_NAME

async def reg_name(update, context):
    name = update.message.text.strip()
    tid  = update.message.from_user.id
    # сохраняем в Employees
    emp_ws.append_row([name, str(tid)])
    context.user_data["name"] = name
    await update.message.reply_text(f"Приятно познакомиться, {name}!\n")
    return await show_menu(update, context)

# выбор статуса
async def choose(update, context):
    text   = update.message.text
    context.user_data["status"] = text

    if text == "⏰ Задерживаюсь":
        await update.message.reply_text("Во сколько будете в офисе? (например 09:30)",
                                        reply_markup=ReplyKeyboardRemove())
        return LATE_TIME

    if text == "🛌 DayOff":
        append_row(context.user_data["name"], update.message.from_user.id,
                   text)
        await update.message.reply_text("Отметка DayOff сохранена.",
                                        reply_markup=ReplyKeyboardRemove())
        return ConversationHandler.END

    if text == "🌴 В отпуске":
        await update.message.reply_text(
            "Укажите даты отпуска в формате DD.MM–DD.MM (например 07.09–12.09):",
            reply_markup=ReplyKeyboardRemove()
        )
        return VAC_DATES

    if text == "🎨 На съёмках":
        await update.message.reply_text(
            "За кого/какой проект вы на съёмках?",
            reply_markup=ReplyKeyboardRemove()
        )
        return SHOOT_DETAIL

    if text == "💻 Удалённо":
        await update.message.reply_text(
            "По какой причине работаете удалённо?",
            reply_markup=ReplyKeyboardRemove()
        )
        return REMOTE_REASON

    # на всякий случай
    return ConversationHandler.END

# ⏰ Задерживаюсь → время → причина
async def late_time(update, context):
    context.user_data["late_time"] = update.message.text.strip()
    await update.message.reply_text("Причина опоздания?")
    return LATE_REASON

async def late_reason(update, context):
    time_   = context.user_data.pop("late_time")
    reason  = update.message.text.strip()
    append_row(context.user_data["name"], update.message.from_user.id,
               "⏰ Задерживаюсь", details=time_, reason=reason)
    await update.message.reply_text("Отметка опоздания сохранена.")
    return ConversationHandler.END

# 🌴 В отпуске → даты
async def vac_dates(update, context):
    dates = update.message.text.strip()
    append_row(context.user_data["name"], update.message.from_user.id,
               "🌴 В отпуске", details=dates)
    await update.message.reply_text("Даты отпуска сохранены.")
    return ConversationHandler.END

# 🎨 На съёмках → детали
async def shoot_detail(update, context):
    detail = update.message.text.strip()
    append_row(context.user_data["name"], update.message.from_user.id,
               "🎨 На съёмках", details=detail)
    await update.message.reply_text("Детали съёмки сохранены.")
    return ConversationHandler.END

# 💻 Удалённо → причина
async def remote_reason(update, context):
    reason = update.message.text.strip()
    append_row(context.user_data["name"], update.message.from_user.id,
               "💻 Удалённо", reason=reason)
    await update.message.reply_text("Отметка удалёнки сохранена.")
    return ConversationHandler.END

async def cancel(update, context):
    await update.message.reply_text("Отменено.", reply_markup=ReplyKeyboardRemove())
    return ConversationHandler.END

# /list — вывод всех отметок за сегодня
async def list_today(update, context):
    today = datetime.now().strftime("%d.%m.%Y")
    rows  = data_ws.get_all_records()
    lines = []
    for r in rows:
        if r["Дата"] == today:
            # собираем строку: ФИО — Статус (детали, причина)
            parts = [f"{r['Имя']} — {r['Статус']}"]
            if r.get("Детали"):
                parts.append(f"({r['Детали']})")
            if r.get("Причина"):
                parts.append(f"«{r['Причина']}»")
            lines.append(" ".join(parts))
    text = "Список сотрудников сегодня:\n" + "\n".join(f"{i+1}. {l}" for i,l in enumerate(lines))
    await update.message.reply_text(text)

# ------------------ MAIN ------------------
def main():
    app = ApplicationBuilder().token(TOKEN).build()

    conv = ConversationHandler(
        entry_points=[CommandHandler("start", start)],
        states={
            REG_NAME:     [MessageHandler(filters.TEXT & ~filters.COMMAND, reg_name)],
            CHOOSING:     [MessageHandler(filters.Regex("|".join(
                                [k for row in MAIN_KEYS for k in row])), choose)],
            LATE_TIME:    [MessageHandler(filters.TEXT & ~filters.COMMAND, late_time)],
            LATE_REASON:  [MessageHandler(filters.TEXT & ~filters.COMMAND, late_reason)],
            VAC_DATES:    [MessageHandler(filters.TEXT & ~filters.COMMAND, vac_dates)],
            SHOOT_DETAIL: [MessageHandler(filters.TEXT & ~filters.COMMAND, shoot_detail)],
            REMOTE_REASON:[MessageHandler(filters.TEXT & ~filters.COMMAND, remote_reason)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
        per_user=True
    )

    app.add_handler(conv)
    app.add_handler(CommandHandler("list", list_today))

    app.run_polling()

if __name__ == "__main__":
    main()
