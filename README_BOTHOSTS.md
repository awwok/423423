# Пакет для Bothost

Эта папка уже подготовлена для загрузки в Bothost архивом или публикации в Git-репозитории.

## Что загрузить

Упакуйте **содержимое этой папки** в ZIP. В корне архива должны лежать `main.py`, `requirements.txt`, `bothost.json` и папка `app`. Не добавляйте `.venv`, `.git`, `__pycache__` и файл базы данных.

## Переменные в панели Bothost

Добавьте:

- `BOT_TOKEN` — токен Telegram от `@BotFather`.
- `DATABASE_PATH=/app/data/bot.db`.
- `DATA_DIR=/app/data`.
- `DEFAULT_TIMEZONE=Europe/Samara`.

Bothost сохраняет `/app/data` между обновлениями, поэтому SQLite-база не пропадёт при перезапуске или новой загрузке кода.

## Настройки деплоя

- Язык: Python / aiogram.
- Главный файл: `main.py`.
- Токен не хранится в архиве.

После загрузки проверьте логи: приложение должно создать таблицы в `/app/data/bot.db` и запустить polling Telegram.

## Локальная проверка пакета

```powershell
cd D:\Codex\telegram_bank_bot_bothosts_2026-10-26
python -m venv .venv
.\.venv\Scripts\pip install -r requirements.txt
$env:BOT_TOKEN="test-token"
$env:DATABASE_PATH="D:\Codex\telegram_bank_bot_bothosts_2026-10-26\data\bot.db"
python main.py
```

Для Bothost архив не должен содержать `.venv` и `data`.
