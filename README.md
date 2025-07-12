# Telegram Check-in Bot

Этот Telegram-бот предназначен для ежедневной отметки статуса сотрудников. Он сохраняет данные в Google Sheets и отправляет утренние напоминания тем, кто забыл отметиться.

## 📌 Основные функции

- Регистрация новых сотрудников по имени и Telegram ID
- Выбор текущего статуса (офис, удалёнка, съёмки, отпуск, больничный, dayoff)
- Запись информации в Google Sheets
- Автоматическое напоминание в 9:30 утра (по будням)
- Исключение из напоминания, если сотрудник:
  - уже в офисе
  - в отпуске
  - на больничном
  - в dayoff
- Поддержка диапазонов дат для отпуска и больничного — бот автоматически заполняет все даты
- Кнопка 📋 *Список сотрудников* доступна в любой момент

---

## 🛠️ Стек технологий

- Python 3.10+
- [python-telegram-bot](https://github.com/python-telegram-bot/python-telegram-bot) `v22.2`
- `gspread` + `oauth2client` — для работы с Google Sheets
- Deploy через [Render.com](https://render.com/)

---

## 📁 Структура проекта

```
📦 telegram-checkin-bot
├── bot.py                  # основной файл бота
├── requirements.txt        # зависимости
├── render.yaml             # конфигурация для Render
└── credentials.json        # ключ доступа к Google API (секретный)
```

---

## 📗 Установка и запуск локально

1. **Клонируй репозиторий**
```bash
git clone https://github.com/yourusername/telegram-checkin-bot.git
cd telegram-checkin-bot
```

2. **Создай и активируй виртуальное окружение**
```bash
python3 -m venv venv
source venv/bin/activate
```

3. **Установи зависимости**
```bash
pip install -r requirements.txt
```

4. **Создай `credentials.json`**  
Файл с Google service account ключом (с доступом к таблице). Положи его в корень проекта.

5. **Установи переменную окружения**
```bash
export TOKEN=your_telegram_bot_token
```

6. **Запусти бота**
```bash
python bot.py
```

---

## ☁️ Деплой на Render

1. Зайди в [Render.com](https://render.com/) и создай новый Web Service
2. Укажи GitHub-репозиторий
3. Используй файл `render.yaml`:

```yaml
services:
  - type: worker
    name: telegram-checkin-bot
    env: python
    buildCommand: pip3 install -r requirements.txt
    startCommand: python3 bot.py
    secretFiles:
      - name: credentials.json
        mountPath: /etc/secrets/credentials.json
    envVars:
      - key: TOKEN
        sync: false
```

4. В `Environment > Secrets` добавь переменную:
   - `TOKEN` = ваш токен Telegram-бота

5. Добавь секретный файл `credentials.json` (ключ от Google API)

---

## 🧾 Структура Google таблицы

### Таблица `checkin-alt-bot` должна содержать:

#### 📄 Лист 1 (по умолчанию):
```plaintext
Дата | Имя | Telegram ID | Статус | Время | Причина | [необязательно]
```

#### 📄 Лист `Employees`:
```plaintext
Имя | Telegram ID
```

> Убедитесь, что сервисный аккаунт имеет **доступ на редактирование** к таблице


---

## 📃 Лицензия

MIT — используй и дорабатывай свободно.
