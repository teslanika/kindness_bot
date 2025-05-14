from flask import Flask, request, jsonify
import os
import django
import logging
import json
from dotenv import load_dotenv
from asgiref.sync import sync_to_async
import requests

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

# Импорт необходимых модулей из вашего проекта
from bot.models import Child, KindDeed, Reward, Parent

# Создаем Flask-приложение
app = Flask(__name__)

# Телеграм токен из переменных окружения
TOKEN = os.environ.get('TELEGRAM_TOKEN')
if not TOKEN:
    logger.error("Токен Telegram не найден в переменных окружения.")

# Хранилище состояний пользователей (в реальном проекте лучше использовать базу данных или Redis)
user_states = {}
user_contexts = {}
group_states = {}
group_contexts = {}

# Состояния диалога
class States:
    IDLE = 0              # Ожидание команды
    WAITING_DEED = 1      # Ожидание описания доброго дела
    WAITING_POINTS = 2    # Ожидание ввода баллов
    PARENT_PASSWORD = 3   # Ожидание ввода пароля родителя
    PARENT_MENU = 4           # Меню родителя
    PARENT_ADD_CHILD = 5      # Добавление ребенка
    PARENT_ADD_DEED = 6       # Добавление дела ребенку (ожидание описания)
    PARENT_ADD_POINTS = 7     # Добавление дела ребенку (ожидание баллов)
# Вспомогательные функции для работы с Django в асинхронном режиме
@sync_to_async
def get_or_create_child(telegram_id, name):
    return Child.objects.get_or_create(
        telegram_id=telegram_id,
        defaults={"name": name}
    )

@sync_to_async
def get_child(telegram_id):
    return Child.objects.get(telegram_id=telegram_id)

@sync_to_async
def get_recent_deeds(child, limit=5):
    return list(child.deeds.order_by('-created_at')[:limit])

@sync_to_async
def get_rewards():
    return list(Reward.objects.all().order_by('points_required'))

@sync_to_async
def create_deed(child, description, points, parent=None):
    return KindDeed.objects.create(
        child=child,
        description=description,
        points=points,
        added_by=parent
    )

@sync_to_async
def update_child_points(child, points):
    child.total_points += points
    child.save()
    return child.total_points

@sync_to_async
def get_or_create_parent(telegram_id, name):
    return Parent.objects.get_or_create(
        telegram_id=telegram_id,
        defaults={"name": name}
    )

@sync_to_async
def get_parent(telegram_id):
    return Parent.objects.get(telegram_id=telegram_id)

@sync_to_async
def verify_parent(telegram_id):
    try:
        return Parent.objects.get(telegram_id=telegram_id), True
    except Parent.DoesNotExist:
        return None, False

@sync_to_async
def get_child_by_name(name):
    try:
        return Child.objects.get(name=name)
    except Child.DoesNotExist:
        return None
    except Child.MultipleObjectsReturned:
        return Child.objects.filter(name=name).first()

@sync_to_async
def is_parent_of_child(parent, child):
    return parent.children.filter(telegram_id=child.telegram_id).exists()

@sync_to_async
def set_parent_password(parent, password):
    """Установка пароля родителя"""
    import hashlib
    # Простое хеширование пароля (в реальном проекте используйте более надежные методы)
    hashed_password = hashlib.sha256(password.encode()).hexdigest()
    parent.password = hashed_password
    parent.save()
    return parent

@sync_to_async
def verify_parent_password(parent, password):
    """Проверка пароля родителя"""
    import hashlib
    hashed_password = hashlib.sha256(password.encode()).hexdigest()
    return parent.password == hashed_password

@sync_to_async
def get_parent_children(parent):
    """Получение списка детей родителя"""
    return list(parent.children.all())

@sync_to_async
def add_child_to_parent(parent, child):
    """Привязка ребенка к родителю"""
    parent.children.add(child)
    return True

# Обработка webhook-запросов от Telegram
@app.route(f'/{TOKEN}', methods=['POST'])
async def webhook():
    try:
        update = request.get_json()
        logger.info(f"Получен update: {json.dumps(update, indent=2)}")

        # Обработка сообщений
        if 'message' in update:
            await process_message(update['message'])

        # Обработка callback-запросов (нажатия на кнопки)
        if 'callback_query' in update:
            await process_callback_query(update['callback_query'])

        return jsonify({'status': 'ok'})
    except Exception as e:
        logger.error(f"Ошибка при обработке webhook: {e}")
        return jsonify({'status': 'error', 'message': str(e)})

# Функция обработки сообщений

# Функция обработки сообщений
async def process_message(message):
    try:
        chat_id = message['chat']['id']
        user_id = message['from']['id']
        is_group = message['chat']['type'] in ['group', 'supergroup']
        
        # Проверяем, есть ли текст в сообщении
        if 'text' not in message:
            return
        
        text = message['text']
        
        # Получаем текущее состояние пользователя
        if is_group:
            if chat_id not in group_states:
                group_states[chat_id] = {}
            if user_id not in group_states[chat_id]:
                group_states[chat_id][user_id] = States.IDLE
            if chat_id not in group_contexts:
                group_contexts[chat_id] = {}
            if user_id not in group_contexts[chat_id]:
                group_contexts[chat_id][user_id] = {}
            current_state = group_states[chat_id][user_id]
        else:
            current_state = user_states.get(user_id, States.IDLE)

        logger.info(f"Текущее состояние пользователя {user_id} в чате {chat_id}: {current_state}, тип чата: {'группа' if is_group else 'личный'}")
        
        # Обработка в зависимости от состояния
        if current_state == States.WAITING_DEED:
            # Пользователь отправил описание доброго дела
            logger.info(f"Получено описание дела от пользователя {user_id} в чате {chat_id}: {text}")
            
            # Сохраняем описание в контекст с учетом типа чата
            if is_group:
                if chat_id not in group_contexts:
                    group_contexts[chat_id] = {}
                if user_id not in group_contexts[chat_id]:
                    group_contexts[chat_id][user_id] = {}
                group_contexts[chat_id][user_id]['deed_description'] = text
            # Просим ввести количество баллов
                await send_message(
                    chat_id,
                    f"👍 @{message['from']['username'] if 'username' in message['from'] else 'пользователь'}, опиши, сколько баллов ты получил за это дело:"
                )
                # Обновляем состояние пользователя
                user_states[user_id] = States.WAITING_POINTS
                logger.info(f"Состояние пользователя {user_id} обновлено на {States.WAITING_POINTS} в чате {chat_id}")
            else:
                # Личный чат: сохраняем описание и переходим к запросу баллов
                user_contexts[user_id]['deed_description'] = text
                await send_message(
                    chat_id,
                    f"👍 Отлично, @{message['from']['username'] if 'username' in message['from'] else ''}! Теперь укажи, сколько баллов ты получил за это дело:"
                )
                # Обновляем состояние пользователя
                user_states[user_id] = States.WAITING_POINTS
                logger.info(f"Состояние пользователя {user_id} обновлено на {States.WAITING_POINTS} в личном чате {chat_id}")
            # Обновляем состояние
            if is_group:
                group_states[chat_id][user_id] = States.WAITING_POINTS
            else:
                user_states[user_id] = States.WAITING_POINTS
            return
            
        elif current_state == States.WAITING_POINTS:
            # Пользователь отправил количество баллов
            logger.info(f"Получено количество баллов от пользователя {user_id} в чате {chat_id}: {text}")
            
            try:
                points = int(text)
                if points <= 0:
                    await send_message(
                        chat_id,
                        "❌ Баллы должны быть положительным числом. Попробуй еще раз:"
                    )
                    return
                
                # Получаем данные пользователя
                child = await get_child(user_id)
                
                # Получаем сохраненное описание дела с учетом типа чата
                if is_group:
                    deed_description = group_contexts[chat_id].get(user_id, {}).get('deed_description', 'Доброе дело')
                else:
                    deed_description = user_contexts.get(user_id, {}).get('deed_description', 'Доброе дело')
                
                # Создаем запись о добром деле
                deed = await create_deed(
                    child,
                    deed_description,
                    points
                )
                
                # Обновляем общее количество баллов
                total_points = await update_child_points(child, points)
                
                # Отправляем сообщение об успешном добавлении
                keyboard = {
                    "inline_keyboard": [
                        [{"text": "📝 Добавить еще доброе дело", "callback_data": "add_deed"}],
                        [{"text": "🏠 Вернуться в меню", "callback_data": "back_to_menu"}]
                    ]
                }
                
                username = message['from']['username'] if 'username' in message['from'] else message['from']['first_name']
                await send_message(
                    chat_id,
                    f"🎉 Отлично, @{username}! Доброе дело '{deed_description}' добавлено.\n\n"
                    f"Ты получил *{points} баллов*!\n"
                    f"Всего у тебя теперь *{total_points} баллов*.",
                    parse_mode='Markdown',
                    reply_markup=keyboard
                )
                
                # Сбрасываем состояние и контекст с учетом типа чата
                if is_group:
                    group_states[chat_id][user_id] = States.IDLE
                    if user_id in group_contexts[chat_id]:
                        del group_contexts[chat_id][user_id]
                else:
                    user_states[user_id] = States.IDLE
                    if user_id in user_contexts:
                        del user_contexts[user_id]
                
            except ValueError:
                await send_message(
                    chat_id,
                    "❌ Пожалуйста, введи число. Попробуй еще раз:"
                )
                
            return
        
        # Обработка ввода пароля родителя
        elif current_state == States.PARENT_PASSWORD:
            password = text
            is_registering = user_contexts.get(user_id, {}).get('registering_parent', False)
            
            if is_registering:
                # Регистрация нового родителя
                parent, created = await get_or_create_parent(user_id, message['from']['first_name'])
                await set_parent_password(parent, password)
                
                # Очищаем флаг регистрации из контекста
                if user_id in user_contexts and 'registering_parent' in user_contexts[user_id]:
                    del user_contexts[user_id]['registering_parent']
                
                keyboard = {
                    "inline_keyboard": [
                        [{"text": "➕ Добавить ребенка", "callback_data": "add_child"}],
                        [{"text": "📊 Просмотр статистики детей", "callback_data": "view_children"}],
                        [{"text": "🏠 В главное меню", "callback_data": "exit_parent_mode"}]
                    ]
                }
                
                await send_message(
                    chat_id,
                    f"🎉 Поздравляем! Вы зарегистрированы как родитель.\n\n"
                    "Теперь вы можете добавлять добрые дела вашим детям и следить за их прогрессом.",
                    reply_markup=keyboard
                )
                
                # Устанавливаем состояние родительского меню
                user_states[user_id] = States.PARENT_MENU
            else:
                # Проверка пароля существующего родителя
                parent = await get_parent(user_id)
                is_valid = await verify_parent_password(parent, password)
                
                if is_valid:
                    # Пароль верный, показываем меню родителя
                    children = await get_parent_children(parent)
                    
                    keyboard = []
                    if children:
                        keyboard.append([{"text": "➕ Добавить доброе дело ребенку", "callback_data": "add_deed_to_child"}])
                        keyboard.append([{"text": "📊 Просмотр статистики детей", "callback_data": "view_children"}])
                    
                    keyboard.append([{"text": "➕ Добавить ребенка", "callback_data": "add_child"}])
                    keyboard.append([{"text": "🏠 В главное меню", "callback_data": "exit_parent_mode"}])
                    
                    await send_message(
                        chat_id,
                        f"👋 Здравствуйте, {parent.name}! Вы вошли в режим родителя.\n\n"
                        f"У вас {len(children)} {'детей' if len(children) != 1 else 'ребенок'} в системе.\n\n"
                        "Выберите действие:",
                        reply_markup={"inline_keyboard": keyboard}
                    )
                    
                    # Устанавливаем состояние родительского меню
                    user_states[user_id] = States.PARENT_MENU
                else:
                    # Пароль неверный
                    await send_message(
                        chat_id,
                        "❌ Неверный пароль. Пожалуйста, попробуйте еще раз или введите /cancel для отмены."
                    )
            
            return
        
        # Обработка добавления ребенка родителем
        elif current_state == States.PARENT_ADD_CHILD:
            child_name = text.strip()
            
            try:
                parent = await get_parent(user_id)
                
                # Проверяем, существует ли ребенок с таким именем
                child = await get_child_by_name(child_name)
                
                if child:
                    # Если ребенок найден, привязываем его к родителю
                    await add_child_to_parent(parent, child)
                    
                    await send_message(
                        chat_id,
                        f"✅ Ребенок *{child.name}* успешно добавлен!\n\n"
                        f"У него сейчас *{child.total_points} баллов*.\n\n"
                        "Используйте /parent для возврата в меню родителя.",
                        parse_mode='Markdown'
                    )
                else:
                    # Если ребенок не найден, предлагаем зарегистрировать его через бота
                    await send_message(
                        chat_id,
                        f"❓ Ребенок с именем '{child_name}' не найден в системе.\n\n"
                        "Попросите ребенка зарегистрироваться в боте с помощью команды /start, "
                        "а затем добавьте его снова.\n\n"
                        "Используйте /parent для возврата в меню родителя."
                    )
                
                # Сбрасываем состояние
                user_states[user_id] = States.IDLE
                
                return
                    
            except Exception as e:
                logger.error(f"Ошибка при добавлении ребенка: {e}")
                await send_message(
                    chat_id,
                    "❌ Произошла ошибка. Пожалуйста, попробуйте еще раз или используйте /start для начала."
                )
                
                # Сбрасываем состояние
                user_states[user_id] = States.IDLE
                
                return
        
        # Обработка ввода описания доброго дела от родителя
        elif current_state == States.PARENT_ADD_DEED:
            # Сохраняем описание дела
            if user_id not in user_contexts:
                user_contexts[user_id] = {}
            user_contexts[user_id]['deed_description'] = text
            
            await send_message(
                chat_id,
                "👍 Отлично! Теперь укажите, сколько баллов получает ребенок за это дело:"
            )
            
            # Обновляем состояние
            user_states[user_id] = States.PARENT_ADD_POINTS
            return
        
        # Обработка ввода баллов от родителя
        elif current_state == States.PARENT_ADD_POINTS:
            try:
                points = int(text)
                if points <= 0:
                    await send_message(
                        chat_id,
                        "❌ Баллы должны быть положительным числом. Попробуйте еще раз:"
                    )
                    return
                
                # Получаем данные родителя и ребенка
                parent = await get_parent(user_id)
                child_telegram_id = user_contexts.get(user_id, {}).get('selected_child_id')
                
                if not child_telegram_id:
                    await send_message(
                        chat_id,
                        "❌ Ошибка: не выбран ребенок. Пожалуйста, начните заново с /parent."
                    )
                    
                    # Сбрасываем состояние
                    user_states[user_id] = States.IDLE
                    if user_id in user_contexts:
                        del user_contexts[user_id]
                        
                    return
                
                child = await get_child(child_telegram_id)
                
                # Получаем сохраненное описание дела
                deed_description = user_contexts.get(user_id, {}).get('deed_description', 'Доброе дело')
                
                # Создаем запись о добром деле
                deed = await create_deed(
                    child,
                    deed_description,
                    points,
                    parent
                )
                
                # Обновляем общее количество баллов
                total_points = await update_child_points(child, points)
                
                await send_message(
                    chat_id,
                    f"🎉 Доброе дело для {child.name} успешно добавлено!\n\n"
                    f"Доброе дело: *{deed_description}*\n"
                    f"Баллы: *+{points}*\n"
                    f"Всего у ребенка теперь *{total_points} баллов*.\n\n"
                    "Используйте /parent для возврата в меню родителя.",
                    parse_mode='Markdown'
                )
                
                # Сбрасываем состояние и контекст
                user_states[user_id] = States.IDLE
                if user_id in user_contexts:
                    del user_contexts[user_id]
                
            except ValueError:
                await send_message(
                    chat_id,
                    "❌ Пожалуйста, введите число. Попробуйте еще раз:"
                )
                
            return
        
        # Обработка команды /start
        if text in ['/start', '/start@kindness_bot', '/start@KindDiaryBot']:
            # Проверяем, зарегистрирован ли пользователь как ребенок
            child, created = await get_or_create_child(user_id, message['from']['first_name'])
            
            welcome_text = (
                f"Привет, {child.name}! 👋 Это бот для записи твоих добрых дел.\n\n"
                f"У тебя сейчас *{child.total_points} баллов*.\n\n"
                "Выбери действие:"
            )
            
            # Создаем клавиатуру с кнопками и эмодзи
            keyboard = {
                "inline_keyboard": [
                    [{"text": "📝 Добавить доброе дело", "callback_data": "add_deed"}],
                    [{"text": "🌟 Мои баллы", "callback_data": "check_points"}],
                    [{"text": "🎁 Посмотреть награды", "callback_data": "view_rewards"}],
                    [{"text": "❓ Помощь", "callback_data": "help"}],
                    [{"text": "👨‍👩‍👧‍👦 Я родитель", "callback_data": "register_parent"}]
                ]
            }
            
            await send_message(chat_id, welcome_text, parse_mode='Markdown', reply_markup=keyboard)
            
            # Устанавливаем состояние
            user_states[user_id] = States.IDLE
            
        # Обработка команды /help
        elif text == '/help':
            help_text = (
                "🌈 *Бот Добрых Дел* 🌈\n\n"
                "Здесь ты можешь записывать свои добрые дела и получать за них баллы!\n\n"
                "*Доступные команды:*\n\n"
                "/start - Запустить бота и показать главное меню\n"
                "/add - Добавить новое доброе дело\n"
                "/points - Посмотреть мои баллы\n"
                "/rewards - Посмотреть список доступных наград\n"
                "/parent - Режим родителя\n"
                "/help - Показать эту справку\n\n"
                "*Как это работает:*\n"
                "1. Ты делаешь доброе дело\n"
                "2. Записываешь его в этот бот или родитель добавляет его\n"
                "3. Накапливаешь баллы\n"
                "4. Получаешь классные награды!\n\n"
                "*Возможные награды:*\n"
                "• 1000 баллов - Обычная игрушка\n"
                "• 3000 баллов - Взять приставку на выходные\n"
                "• 5000 баллов - Крутая игрушка\n"
                "• 35000 баллов - Nintendo Switch\n\n"
                "Делай больше добрых дел и получай награды! 🎉"
            )
            
            keyboard = {
                "inline_keyboard": [
                    [{"text": "◀️ Назад в меню", "callback_data": "back_to_menu"}]
                ]
            }
           
            await send_message(chat_id, help_text, parse_mode='Markdown', reply_markup=keyboard)
        elif text == '/grouphelp':
            help_text = (
                "🌈 *Бот Добрых Дел в групповом чате* 🌈\n\n"
                "В групповом чате вы можете:\n"
                "• Использовать команду /start для начала работы\n"
                "• Добавлять добрые дела через меню или команду /add\n"
                "• Проверять баллы командой /points\n"
                "• Смотреть доступные награды командой /rewards\n\n"
                "Для более удобного взаимодействия рекомендуется использовать бота в личных сообщениях."
            )
    
            await send_message(chat_id, help_text, parse_mode='Markdown')    
        
        # Обработка команды /add
        elif text == '/add':
            await send_message(chat_id, "📝 Опиши свое доброе дело:")
            user_states[user_id] = States.WAITING_DEED
        
        # Обработка команды /points
        elif text == '/points':
            await process_points_command(chat_id, user_id)
        
        # Обработка команды /rewards
        elif text == '/rewards':
            await process_rewards_command(chat_id, user_id)
        
        # Обработка команды /parent
        elif text == '/parent':
            await process_parent_command(chat_id, user_id)
        
        # Обработка команды /cancel
        elif text == '/cancel':
            # Сбрасываем состояние пользователя
            user_states[user_id] = States.IDLE
            if user_id in user_contexts:
                del user_contexts[user_id]
            
            await send_message(
                chat_id,
                "❌ Действие отменено. Используйте /start для возврата в главное меню."
            )
        
        # Обработка неизвестных команд и сообщений
        elif text.startswith('/'):
            # Неизвестная команда
            await send_message(
                chat_id,
                "❓ Извините, я не знаю такой команды. Используйте /help для просмотра доступных команд."
            )
        
    except Exception as e:
        logger.error(f"Ошибка при обработке сообщения: {e}")
        await send_message(
            chat_id,
            "❌ Произошла ошибка при обработке вашего запроса. Пожалуйста, попробуйте еще раз или используйте /start для начала."
        )

# Функция обработки callback-запросов (нажатий на кнопки)
async def process_callback_query(callback_query):
    try:
        data = callback_query['data']
        chat_id = callback_query['message']['chat']['id']
        user_id = callback_query['from']['id']
        message_id = callback_query['message']['message_id']
        is_group = callback_query['message']['chat']['type'] in ['group', 'supergroup']
        
        
        logger.info(f"Получен callback_query: {data} от пользователя {user_id} в чате {chat_id}")
        
        # Обработка кнопки "Добавить доброе дело"
        if data == 'add_deed':
            # Отправляем сообщение с запросом описания дела
            username = callback_query['from']['username'] if 'username' in callback_query['from'] else ''
            if is_group and username:
                await send_message(chat_id, f"@{username}, 📝 опиши свое доброе дело:")
            else:
                await send_message(chat_id, "📝 Опиши свое доброе дело:")
            
            # Обновляем состояние пользователя с учетом типа чата
            if is_group:
                if chat_id not in group_states:
                    group_states[chat_id] = {}
                group_states[chat_id][user_id] = States.WAITING_DEED
            else:
                user_states[user_id] = States.WAITING_DEED
            
            # Отвечаем на callback_query
            await answer_callback_query(callback_query['id'])
        
        # Обработка кнопки "Мои баллы"
        elif data == 'check_points':
            child = await get_child(user_id)
            recent_deeds = await get_recent_deeds(child)
            
            text = f"🌟 У тебя сейчас *{child.total_points} баллов*! 🌟\n\n"
            if recent_deeds:
                text += "📋 *Твои последние добрые дела:*\n"
                for deed in recent_deeds:
                    date_str = deed.created_at.strftime("%d.%m.%Y")
                    text += f"• {deed.description}: *{deed.points} баллов* ({date_str})\n"
            
            keyboard = {
                "inline_keyboard": [
                    [{"text": "◀️ Назад в меню", "callback_data": "back_to_menu"}]
                ]
            }
            
            await send_message(chat_id, text, parse_mode='Markdown', reply_markup=keyboard)
            
            # Отвечаем на callback_query
            await answer_callback_query(callback_query['id'])
        
        # Обработка кнопки "Посмотреть награды"
        elif data == 'view_rewards':
            rewards = await get_rewards()
            
            if not rewards:
                text = "Пока в базе нет доступных наград. Но ты можешь копить на:\n\n"
                text += f"• *Обычная игрушка*: 1000 баллов\n"
                text += f"• *Приставка на выходные*: 3000 баллов\n"
                text += f"• *Крутая игрушка*: 5000 баллов\n"
                text += f"• *Nintendo Switch*: 35000 баллов\n"
            else:
                text = "🎁 *Доступные награды:*\n\n"
                for reward in rewards:
                    text += f"• *{reward.name}*: {reward.points_required} баллов"
                    if reward.description:
                        text += f" - {reward.description}"
                    text += "\n"
            
            keyboard = {
                "inline_keyboard": [
                    [{"text": "◀️ Назад в меню", "callback_data": "back_to_menu"}]
                ]
            }
            
            await send_message(chat_id, text, parse_mode='Markdown', reply_markup=keyboard)
            
            # Отвечаем на callback_query
            await answer_callback_query(callback_query['id'])
        
        # Обработка кнопки "Помощь"
        elif data == 'help':
            help_text = (
                "🌈 *Бот Добрых Дел* 🌈\n\n"
                "Здесь ты можешь записывать свои добрые дела и получать за них баллы!\n\n"
                "*Как это работает:*\n"
                "1. Ты делаешь доброе дело\n"
                "2. Записываешь его в этот бот\n"
                "3. Накапливаешь баллы\n"
                "4. Получаешь классные награды!\n\n"
                "*Доступные команды:*\n"
                "/start - Запустить бота и показать главное меню\n"
                "/add - Добавить новое доброе дело\n"
                "/points - Посмотреть мои баллы\n"
                "/rewards - Посмотреть список доступных наград\n"
                "/parent - Режим родителя\n"
                "/help - Показать эту справку\n"
            )
            
            keyboard = {
                "inline_keyboard": [
                    [{"text": "◀️ Назад в меню", "callback_data": "back_to_menu"}]
                ]
            }
            
            await send_message(chat_id, help_text, parse_mode='Markdown', reply_markup=keyboard)
            
            # Отвечаем на callback_query
            await answer_callback_query(callback_query['id'])
        
        # Обработка кнопки "Я родитель"
        elif data == 'register_parent':
            # Переходим к регистрации родителя
            await send_message(
                chat_id,
                "Вы хотите зарегистрироваться как родитель?\n\n"
                "Введите пароль, который будет использоваться для входа в режим родителя:"
            )
            
            # Сохраняем состояние для ожидания создания пароля
            user_states[user_id] = States.PARENT_PASSWORD
            if user_id not in user_contexts:
                user_contexts[user_id] = {}
            user_contexts[user_id]['registering_parent'] = True
            
            # Отвечаем на callback_query
            await answer_callback_query(callback_query['id'])
        
        # Обработка кнопки "Назад в меню"
        elif data == 'back_to_menu':
            await process_back_to_menu(chat_id, user_id)
            
            # Отвечаем на callback_query
            await answer_callback_query(callback_query['id'])
        
        # Обработка кнопки "Добавить ребенка"
        elif data == 'add_child':
            await send_message(
                chat_id,
                "👶 Введите имя ребенка, которого хотите добавить:"
            )
            user_states[user_id] = States.PARENT_ADD_CHILD
            
            await answer_callback_query(callback_query['id'])
        
        # Обработка кнопки "Просмотр статистики детей"
        elif data == 'view_children':
            try:
                parent = await get_parent(user_id)
                children = await get_parent_children(parent)
                
                if not children:
                    keyboard = {
                        "inline_keyboard": [
                            [{"text": "➕ Добавить ребенка", "callback_data": "add_child"}],
                            [{"text": "🏠 В главное меню", "callback_data": "exit_parent_mode"}]
                        ]
                    }
                    
                    await send_message(
                        chat_id,
                        "У вас пока нет добавленных детей. Добавьте ребенка, чтобы видеть его статистику.",
                        reply_markup=keyboard
                    )
                    return
                
                text = "📊 *Статистика ваших детей:*\n\n"
                for child in children:
                    recent_deeds = await get_recent_deeds(child, limit=3)
                    
                    text += f"👶 *{child.name}*: {child.total_points} баллов\n"
                    if recent_deeds:
                        text += "Последние добрые дела:\n"
                        for deed in recent_deeds:
                            date_str = deed.created_at.strftime("%d.%m.%Y")
                            text += f"• {deed.description}: {deed.points} баллов ({date_str})\n"
                    text += "\n"
                
                keyboard = {
                    "inline_keyboard": [
                        [{"text": "➕ Добавить доброе дело", "callback_data": "add_deed_to_child"}],
                        [{"text": "◀️ Назад", "callback_data": "back_to_parent_menu"}]
                    ]
                }
                
                await send_message(
                    chat_id,
                    text,
                    parse_mode='Markdown',
                    reply_markup=keyboard
                )
                
            except Exception as e:
                logger.error(f"Ошибка при просмотре статистики детей: {e}")
                await send_message(
                    chat_id,
                    "❌ Произошла ошибка. Пожалуйста, попробуйте еще раз."
                )
                
            await answer_callback_query(callback_query['id'])
        
        # Обработка кнопки "Добавить доброе дело ребенку"
        elif data == 'add_deed_to_child':
            try:
                parent = await get_parent(user_id)
                children = await get_parent_children(parent)
                
                if not children:
                    keyboard = {
                        "inline_keyboard": [
                            [{"text": "➕ Добавить ребенка", "callback_data": "add_child"}],
                            [{"text": "🏠 В главное меню", "callback_data": "exit_parent_mode"}]
                        ]
                    }
                    
                    await send_message(
                        chat_id,
                        "У вас пока нет добавленных детей. Добавьте ребенка, чтобы добавлять ему добрые дела.",
                        reply_markup=keyboard
                    )
                    return
                
                # Создаем кнопки для выбора ребенка
                keyboard = []
                for child in children:
                    keyboard.append([{"text": f"👶 {child.name}", "callback_data": f"select_child_{child.telegram_id}"}])
                
                keyboard.append([{"text": "◀️ Назад", "callback_data": "back_to_parent_menu"}])
                
                await send_message(
                    chat_id,
                    "Выберите ребенка, которому хотите добавить доброе дело:",
                    reply_markup={"inline_keyboard": keyboard}
                )
                
            except Exception as e:
                logger.error(f"Ошибка при выборе ребенка: {e}")
                await send_message(
                    chat_id,
                    "❌ Произошла ошибка. Пожалуйста, попробуйте еще раз."
                )
                
            await answer_callback_query(callback_query['id'])
        
        # Обработка кнопки "В главное меню" из режима родителя
        elif data == 'exit_parent_mode':
            await send_message(
                chat_id,
                "Вы вышли из режима родителя. Используйте /start для начала работы с ботом."
            )
            user_states[user_id] = States.IDLE
            await answer_callback_query(callback_query['id'])
        
        # Обработка кнопки "Назад" в меню родителя
        elif data == 'back_to_parent_menu':
            try:
                parent = await get_parent(user_id)
                children = await get_parent_children(parent)
                
                keyboard = []
                if children:
                    keyboard.append([{"text": "➕ Добавить доброе дело ребенку", "callback_data": "add_deed_to_child"}])
                    keyboard.append([{"text": "📊 Просмотр статистики детей", "callback_data": "view_children"}])
                
                keyboard.append([{"text": "➕ Добавить ребенка", "callback_data": "add_child"}])
                keyboard.append([{"text": "🏠 В главное меню", "callback_data": "exit_parent_mode"}])
                
                await send_message(
                    chat_id,
                    f"👋 Здравствуйте, {parent.name}! Вы в режиме родителя.\n\n"
                    f"У вас {len(children)} {'детей' if len(children) != 1 else 'ребенок'} в системе.\n\n"
                    "Выберите действие:",
                    reply_markup={"inline_keyboard": keyboard}
                )
                
            except Exception as e:
                logger.error(f"Ошибка при возврате в меню родителя: {e}")
                await send_message(
                    chat_id,
                    "❌ Произошла ошибка. Пожалуйста, попробуйте еще раз."
                )
                
            await answer_callback_query(callback_query['id'])
        
        # Обработка выбора ребенка (формат: select_child_TELEGRAM_ID)
        elif data.startswith("select_child_"):
            try:
                child_telegram_id = int(data.split("_")[-1])
                child = await get_child(child_telegram_id)
                
                # Сохраняем ID выбранного ребенка в контексте
                if user_id not in user_contexts:
                    user_contexts[user_id] = {}
                user_contexts[user_id]["selected_child_id"] = child_telegram_id
                
                await send_message(
                    chat_id,
                    f"Вы выбрали ребенка: *{child.name}*\n\n"
                    "Опишите доброе дело, которое совершил ребенок:",
                    parse_mode='Markdown'
                )
                
                # Устанавливаем состояние
                user_states[user_id] = States.PARENT_ADD_DEED
                
            except Exception as e:
                logger.error(f"Ошибка при выборе ребенка: {e}")
                await send_message(
                    chat_id,
                    "❌ Произошла ошибка. Пожалуйста, попробуйте еще раз."
                )
                
            await answer_callback_query(callback_query['id'])
        
        # Если не распознали callback_data
        else:
            logger.warning(f"Неизвестный callback_data: {data}")
            await answer_callback_query(callback_query['id'], "Неизвестная команда")
        
    except Exception as e:
        logger.error(f"Ошибка при обработке callback_query: {e}")

# Дополнительные функции обработки команд
async def process_points_command(chat_id, user_id):
    """Обработка команды проверки баллов"""
    try:
        child = await get_child(user_id)
        recent_deeds = await get_recent_deeds(child)

        text = f"🌟 У тебя сейчас *{child.total_points} баллов*! 🌟\n\n"
        if recent_deeds:
            text += "📋 *Твои последние добрые дела:*\n"
            for deed in recent_deeds:
                date_str = deed.created_at.strftime("%d.%m.%Y")
                text += f"• {deed.description}: *{deed.points} баллов* ({date_str})\n"

        keyboard = {
            "inline_keyboard": [
                [{"text": "◀️ Назад в меню", "callback_data": "back_to_menu"}]
            ]
        }

        await send_message(chat_id, text, parse_mode='Markdown', reply_markup=keyboard)
    except Exception as e:
        logger.error(f"Ошибка при обработке команды points: {e}")
        await send_message(chat_id, "Произошла ошибка. Пожалуйста, начните сначала с /start")

async def process_rewards_command(chat_id, user_id):
    """Обработка команды просмотра наград"""
    try:
        rewards = await get_rewards()

        if not rewards:
            text = "Пока в базе нет доступных наград. Но ты можешь копить на:\n\n"
            text += f"• *Обычная игрушка*: 1000 баллов\n"
            text += f"• *Приставка на выходные*: 3000 баллов\n"
            text += f"• *Крутая игрушка*: 5000 баллов\n"
            text += f"• *Nintendo Switch*: 35000 баллов\n"
        else:
            text = "🎁 *Доступные награды:*\n\n"
            for reward in rewards:
                text += f"• *{reward.name}*: {reward.points_required} баллов"
                if reward.description:
                    text += f" - {reward.description}"
                text += "\n"

        keyboard = {
            "inline_keyboard": [
                [{"text": "◀️ Назад в меню", "callback_data": "back_to_menu"}]
            ]
        }

        await send_message(chat_id, text, parse_mode='Markdown', reply_markup=keyboard)
    except Exception as e:
        logger.error(f"Ошибка при обработке команды rewards: {e}")
        await send_message(chat_id, "Произошла ошибка. Пожалуйста, начните сначала с /start")

async def process_parent_command(chat_id, user_id):
   """Обработка команды режима родителя"""
   try:
       # Проверяем, зарегистрирован ли пользователь как родитель
       parent, is_parent = await verify_parent(user_id)

       if is_parent:
           await send_message(
               chat_id,
               f"Здравствуйте, {parent.name}! Для доступа к режиму родителя, пожалуйста, введите пароль:"
           )
           # Сохраняем состояние для ожидания ввода пароля
           user_states[user_id] = States.PARENT_PASSWORD
       else:
           await send_message(
               chat_id,
               "Вы еще не зарегистрированы как родитель. Хотите зарегистрироваться?\n\n"
               "Введите пароль, который будет использоваться для входа в режим родителя:"
           )
           # Сохраняем состояние для ожидания создания пароля
           user_states[user_id] = States.PARENT_PASSWORD
           if user_id not in user_contexts:
               user_contexts[user_id] = {}
           user_contexts[user_id]['registering_parent'] = True
   except Exception as e:
       logger.error(f"Ошибка при обработке команды parent: {e}")
       await send_message(chat_id, "Произошла ошибка. Пожалуйста, начните сначала с /start")

async def process_back_to_menu(chat_id, user_id):
   """Возврат в главное меню"""
   try:
       child = await get_child(user_id)

       text = (
           f"Привет, {child.name}! 👋 Это бот для записи твоих добрых дел.\n\n"
           f"У тебя сейчас *{child.total_points} баллов*.\n\n"
           "Выбери действие:"
       )

       keyboard = {
           "inline_keyboard": [
               [{"text": "📝 Добавить доброе дело", "callback_data": "add_deed"}],
               [{"text": "🌟 Мои баллы", "callback_data": "check_points"}],
               [{"text": "🎁 Посмотреть награды", "callback_data": "view_rewards"}],
               [{"text": "❓ Помощь", "callback_data": "help"}],
               [{"text": "👨‍👩‍👧‍👦 Я родитель", "callback_data": "register_parent"}]
           ]
       }

       await send_message(chat_id, text, parse_mode='Markdown', reply_markup=keyboard)

       # Сбрасываем состояние
       user_states[user_id] = States.IDLE
   except Exception as e:
       logger.error(f"Ошибка при возврате в меню: {e}")

# Функции для работы с Telegram API
async def send_message(chat_id, text, parse_mode=None, reply_markup=None):
   """Функция для отправки сообщений"""
   url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"

   payload = {
       'chat_id': chat_id,
       'text': text
   }

   if parse_mode:
       payload['parse_mode'] = parse_mode

   if reply_markup:
       payload['reply_markup'] = reply_markup

   try:
       # Используем sync_to_async для выполнения синхронного запроса в асинхронной функции
       @sync_to_async
       def do_request():
           return requests.post(url, json=payload)

       response = await do_request()
       response_json = response.json()

       if not response_json.get('ok'):
           logger.error(f"Ошибка при отправке сообщения: {response_json}")

       return response_json
   except Exception as e:
       logger.error(f"Исключение при отправке сообщения: {e}")
       return None

async def edit_message(chat_id, message_id, text, parse_mode=None, reply_markup=None):
   """Функция для редактирования сообщений"""
   url = f"https://api.telegram.org/bot{TOKEN}/editMessageText"

   payload = {
       'chat_id': chat_id,
       'message_id': message_id,
       'text': text
   }

   if parse_mode:
       payload['parse_mode'] = parse_mode

   if reply_markup:
       payload['reply_markup'] = reply_markup

   try:
       @sync_to_async
       def do_request():
           return requests.post(url, json=payload)

       response = await do_request()
       return response.json()
   except Exception as e:
       logger.error(f"Ошибка при редактировании сообщения: {e}")
       return None

async def answer_callback_query(callback_query_id, text=None):
   """Функция для ответа на callback_query"""
   url = f"https://api.telegram.org/bot{TOKEN}/answerCallbackQuery"

   payload = {
       'callback_query_id': callback_query_id
   }

   if text:
       payload['text'] = text

   try:
       @sync_to_async
       def do_request():
           return requests.post(url, json=payload)

       response = await do_request()
       return response.json()
   except Exception as e:
       logger.error(f"Ошибка при ответе на callback_query: {e}")
       return None

# Маршрут для установки webhook
@app.route('/set_webhook', methods=['GET'])
def set_webhook():
   webhook_url = f"https://{request.host}/{TOKEN}"
   url = f"https://api.telegram.org/bot{TOKEN}/setWebhook?url={webhook_url}"

   response = requests.get(url)
   data = response.json()

   if data.get('ok'):
       return jsonify({
           'status': 'success',
           'message': f'Webhook установлен на {webhook_url}',
           'result': data
       })
   else:
       return jsonify({
           'status': 'error',
           'message': 'Не удалось установить webhook',
           'result': data
       })

# Маршрут для удаления webhook
@app.route('/remove_webhook', methods=['GET'])
def remove_webhook():
   url = f"https://api.telegram.org/bot{TOKEN}/deleteWebhook"
   response = requests.get(url)
   data = response.json()

   return jsonify({
       'status': 'success' if data.get('ok') else 'error',
       'message': 'Webhook удален' if data.get('ok') else 'Не удалось удалить webhook',
       'result': data
   })

# Маршрут для проверки статуса webhook
@app.route('/webhook_status', methods=['GET'])
def webhook_status():
   url = f"https://api.telegram.org/bot{TOKEN}/getWebhookInfo"
   response = requests.get(url)
   data = response.json()

   return jsonify({
       'status': 'success',
       'webhook_info': data
   })

# Дополнительный маршрут /web-hook
@app.route('/web-hook', methods=['GET'])
def web_hook():
   return "Для настройки webhook используйте путь /set_webhook"

# Главная страница
@app.route('/')
def home():
   return 'Бот для учета добрых дел успешно запущен!'

# Запуск приложения (в режиме разработки)
if __name__ == '__main__':
   app.run(debug=True)