## Структура проекта

```
checkin-alt-bot/
├── bot.py
├── requirements.txt
├── render.yaml
└── README.md
```

---

### requirements.txt

```text
python-telegram-bot[job-queue]>=20.3
gspread>=5.7.0
oauth2client>=4.1.3
pendulum>=2.1
```

---

### render.yaml

```yaml
services:
  - type: web
    name: checkin-alt-bot
    env: python
    region: oregon
    plan: free
    buildCommand: "pip install -r requirements.txt"
    startCommand: "python3 bot.py"
    pythonVersion: "3.13"
    secretAccess:
      - name: GOOGLE_CREDENTIALS_JSON
      - name: TELEGRAM_TOKEN
```

---

### bot.py

```python
import os
import pendulum
from telegram import ReplyKeyboardMarkup, KeyboardButton
from telegram.ext import (
    ApplicationBuilder, ContextTypes,
    ConversationHandler, MessageHandler, filters,
    CommandHandler
)
import gspread
from oauth2client.service_account import ServiceAccountCredentials

# Константы состояний
(
    STATE_NAME,
    STATE_STATUS, STATE_DETAIL
) = range(3)

# Клавиатура меню
MENU = [
    ["🏢 Уже в офисе", "🏠 Удалённо"],
    ["⏰ Задерживаюсь", "🌴 В отпуске"],
    ["🛌 DayOff", "🎨 На съёмках"],
    ["📋 Список сотрудников"]
]

def connect_sheet():
    scope = [
        'https://spreadsheets.google.com/feeds',
        'https://www.googleapis.com/auth/drive'
    ]
    creds_json = os.environ['GOOGLE_CREDENTIALS_JSON']
    creds = ServiceAccountCredentials.from_json_keyfile_dict(
        creds_json, scope)
    gc = gspread.authorize(creds)
    wb = gc.open("StatusSheet")
    return wb

async def start(update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Привет! Для начала введи своё имя и фамилию (русскими буквами)",
    )
    return STATE_NAME

async def name_handler(update, context):
    text = update.message.text.strip()
    context.user_data['name'] = text
    await update.message.reply_text(
        "Выбери статус:",
        reply_markup=ReplyKeyboardMarkup(MENU, one_time_keyboard=True)
    )
    return STATE_STATUS

async def status_handler(update, context):
    choice = update.message.text
    context.user_data['status'] = choice
    # требуем детали только для некоторых
    if choice in ["🏠 Удалённо", "⏰ Задерживаюсь", "🌴 В отпуске", "🎨 На съёмках"]:
        prompt = {
            "🏠 Удалённо": "По какой причине вы работаете удалённо?",
            "⏰ Задерживаюсь": "Когда будете на работе? (время)",
            "🌴 В отпуске": "Укажи даты отпуска (например: 01.07–09.07)",
            "🎨 На съёмках": "Что за съёмки? (клиент/детали)"
        }[choice]
        await update.message.reply_text(prompt)
        return STATE_DETAIL
    # DayOff и Список сразу обрабатываем
    await save_status(context)
    return ConversationHandler.END

async def detail_handler(update, context):
    context.user_data['detail'] = update.message.text.strip()
    await save_status(context)
    return ConversationHandler.END

async def save_status(context):
    name = context.user_data['name']
    status = context.user_data['status']
    detail = context.user_data.get('detail', '')
    ws = connect_sheet().worksheet('Status')
    today = pendulum.now().format('DD.MM.YYYY')
    row = [today, name, context._chat_id, status, detail]
    ws.append_row(row)
    # очитска userdata
    context.user_data.clear()

async def list_handler(update, context):
    ws = connect_sheet().worksheet('Status')
    records = ws.get_all_records()
    today = pendulum.now().format('DD.MM.YYYY')
    lines = []
    i = 1
    for r in records:
        if r['Дата'] == today:
            detail = r['Детали']
            lines.append(f"{i}. {r['Имя']} — {r['Статус']} ({detail})")
            i += 1
    text = "📋 Список сотрудников сегодня:\n" + "\n".join(lines)
    await update.message.reply_text(text)

async def daily_reminder(context):
    ws = connect_sheet().worksheet('Employees')
    all_users = ws.col_values(3)[1:]
    for tid in all_users:
        context.bot.send_message(
            chat_id=int(tid),
            text="Пожалуйста, укажи свой статус сегодня",
            reply_markup=ReplyKeyboardMarkup(MENU, one_time_keyboard=True)
        )

def main():
    app = ApplicationBuilder().token(os.environ['TELEGRAM_TOKEN']).build()
    conv = ConversationHandler(
        entry_points=[CommandHandler('start', start)],
        states={
            STATE_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, name_handler)],
            STATE_STATUS: [MessageHandler(filters.TEXT & ~filters.COMMAND, status_handler)],
            STATE_DETAIL: [MessageHandler(filters.TEXT & ~filters.COMMAND, detail_handler)],
        },
        fallbacks=[CommandHandler('start', start)]
    )
    app.add_handler(conv)
    app.add_handler(CommandHandler('list', list_handler))
    # ежедневный пуш в 09:30
    remind_time = pendulum.now().set(hour=9, minute=30)
    app.job_queue.run_daily(daily_reminder, time=remind_time, days=(1,2,3,4,5))
    app.run_polling()

if __name__ == '__main__':
    main()
```
