from flask import Flask, request, jsonify
import os
import django
import logging
import json
from dotenv import load_dotenv
import asyncio
from telebot.async_telebot import AsyncTeleBot
from telebot import types

# Импортируем бота из telebot_app.py
from telebot_app import bot

# Настройка логгирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('bot.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# Загрузка переменных окружения
load_dotenv()

# Настройка Django
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "kindness_bot.settings")
django.setup()

# Создаем Flask-приложение
app = Flask(__name__)

# Получаем TOKEN из telebot_app
TOKEN = bot.token

# Обработка webhook-запросов от Telegram
@app.route(f'/{TOKEN}', methods=['POST'])
async def webhook():
    try:
        if request.headers.get('content-type') == 'application/json':
            update = request.get_json()
            logger.info(f"Получен update: {json.dumps(update, indent=2)}")
            
            # Создание объекта Update
            telegram_update = types.Update.de_json(update)
            
            # Создаем задачу для асинхронной обработки
            asyncio.create_task(bot.process_new_updates([telegram_update]))
            
            return jsonify({'status': 'ok'})
        else:
            return jsonify({'status': 'error', 'message': 'Неверный формат запроса'})
    except Exception as e:
        logger.error(f"Ошибка при обработке webhook: {e}")
        return jsonify({'status': 'error', 'message': str(e)})

# Маршрут для установки webhook
@app.route('/set_webhook', methods=['GET'])
async def set_webhook():
    webhook_url = f"https://{request.host}/{TOKEN}"
    try:
        await bot.remove_webhook()
        await bot.set_webhook(url=webhook_url)
        return jsonify({
            'status': 'success',
            'message': f'Webhook установлен на {webhook_url}'
        })
    except Exception as e:
        logger.error(f"Ошибка при установке webhook: {e}")
        return jsonify({'status': 'error', 'message': str(e)})

# Маршрут для удаления webhook
@app.route('/remove_webhook', methods=['GET'])
async def remove_webhook():
    try:
        await bot.remove_webhook()
        return jsonify({
            'status': 'success',
            'message': 'Webhook удален'
        })
    except Exception as e:
        logger.error(f"Ошибка при удалении webhook: {e}")
        return jsonify({'status': 'error', 'message': str(e)})

# Маршрут для проверки статуса webhook
@app.route('/webhook_status', methods=['GET'])
async def webhook_status():
    try:
        info = await bot.get_webhook_info()
        return jsonify({
            'status': 'success',
            'webhook_info': {
                'url': info.url,
                'has_custom_certificate': info.has_custom_certificate,
                'pending_update_count': info.pending_update_count,
                'last_error_date': info.last_error_date,
                'last_error_message': info.last_error_message,
                'max_connections': info.max_connections
            }
        })
    except Exception as e:
        logger.error(f"Ошибка при получении статуса webhook: {e}")
        return jsonify({'status': 'error', 'message': str(e)})

# Главная страница
@app.route('/')
def home():
    return 'Бот для учета добрых дел успешно запущен!'

# Запуск приложения (в режиме разработки)
if __name__ == '__main__':
    app.run(debug=True)