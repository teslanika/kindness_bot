import telebot
from telebot import types
from telebot.storage import StateMemoryStorage
from telebot.handler_backends import State, StatesGroup
import os
import django
import logging
from flask import Flask, request, jsonify

# Настройка логгирования
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Настройка Django
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "kindness_bot.settings")
django.setup()

# Импорт моделей
from bot.models import Child, KindDeed, Reward, Parent

# Определение состояний бота
class BotStates(StatesGroup):
    IDLE = State()
    WAITING_DEED = State()
    WAITING_POINTS = State()
    PARENT_PASSWORD = State()
    PARENT_MENU = State()
    PARENT_ADD_CHILD = State()
    PARENT_ADD_DEED = State()
    PARENT_ADD_POINTS = State()

# Токен бота из вашего существующего кода
TOKEN = os.environ.get('TELEGRAM_TOKEN')
if not TOKEN:
    logger.error("Токен Telegram не найден в переменных окружения.")

# Создание бота с хранилищем состояний
bot = telebot.TeleBot(TOKEN, state_storage=StateMemoryStorage())

# Создание Flask приложения
app = Flask(__name__)

# Функции для работы с Django
def get_or_create_child(telegram_id, name):
    return Child.objects.get_or_create(
        telegram_id=telegram_id,
        defaults={"name": name}
    )

def get_child(telegram_id):
    return Child.objects.get(telegram_id=telegram_id)

def get_recent_deeds(child, limit=5):
    return list(child.deeds.order_by('-created_at')[:limit])

def get_rewards():
    return list(Reward.objects.all().order_by('points_required'))

def create_deed(child, description, points, parent=None):
    return KindDeed.objects.create(
        child=child,
        description=description,
        points=points,
        added_by=parent
    )

def update_child_points(child, points):
    child.total_points += points
    child.save()
    return child.total_points

def get_or_create_parent(telegram_id, name):
    return Parent.objects.get_or_create(
        telegram_id=telegram_id,
        defaults={"name": name}
    )

def get_parent(telegram_id):
    try:
        parent = Parent.objects.get(telegram_id=telegram_id)
        return parent, True
    except Parent.DoesNotExist:
        return None, False

def get_child_by_name(name):
    try:
        return Child.objects.get(name=name)
    except Child.DoesNotExist:
        return None
    except Child.MultipleObjectsReturned:
        return Child.objects.filter(name=name).first()

def set_parent_password(parent, password):
    import hashlib
    # Простое хеширование пароля
    hashed_password = hashlib.sha256(password.encode()).hexdigest()
    parent.password = hashed_password
    parent.save()
    return parent

def verify_parent_password(parent, password):
    import hashlib
    hashed_password = hashlib.sha256(password.encode()).hexdigest()
    return parent.password == hashed_password

def get_parent_children(parent):
    return list(parent.children.all())

def add_child_to_parent(parent, child):
    parent.children.add(child)
    return True

# Обработчики команд бота
@bot.message_handler(commands=['start'])
def start_command(message):
    user_id = message.from_user.id
    username = message.from_user.first_name
    logger.info(f"Start command from user {user_id}")
    
    try:
        # Проверяем, зарегистрирован ли пользователь как ребенок
        child, created = get_or_create_child(user_id, username)
        
        welcome_text = (
            f"Привет, {child.name}! 👋 Это бот для записи твоих добрых дел.\n\n"
            f"У тебя сейчас *{child.total_points} баллов*.\n\n"
            "Выбери действие:"
        )
        
        # Создаем клавиатуру с кнопками
        keyboard = types.InlineKeyboardMarkup()
        keyboard.add(types.InlineKeyboardButton("📝 Добавить доброе дело", callback_data="add_deed"))
        keyboard.add(types.InlineKeyboardButton("🌟 Мои баллы", callback_data="check_points"))
        keyboard.add(types.InlineKeyboardButton("🎁 Посмотреть награды", callback_data="view_rewards"))
        keyboard.add(types.InlineKeyboardButton("❓ Помощь", callback_data="help"))
        keyboard.add(types.InlineKeyboardButton("👨‍👩‍👧‍👦 Я родитель", callback_data="register_parent"))
        
        # Устанавливаем состояние IDLE
        bot.set_state(user_id, BotStates.IDLE, message.chat.id)
        
        # Отправляем сообщение с клавиатурой
        bot.send_message(
            message.chat.id, 
            welcome_text, 
            parse_mode='Markdown',
            reply_markup=keyboard
        )
    except Exception as e:
        logger.error(f"Error in start_command: {e}")
        bot.send_message(message.chat.id, "Произошла ошибка при запуске бота. Пожалуйста, попробуйте еще раз.")

@bot.message_handler(commands=['help'])
def help_command(message):
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
    
    keyboard = types.InlineKeyboardMarkup()
    keyboard.add(types.InlineKeyboardButton("◀️ Назад в меню", callback_data="back_to_menu"))
    
    bot.send_message(
        message.chat.id, 
        help_text, 
        parse_mode='Markdown',
        reply_markup=keyboard
    )

@bot.message_handler(commands=['add'])
def add_command(message):
    user_id = message.from_user.id
    
    # Устанавливаем состояние WAITING_DEED
    bot.set_state(user_id, BotStates.WAITING_DEED, message.chat.id)
    
    # Запрашиваем описание доброго дела
    bot.send_message(message.chat.id, "📝 Опиши свое доброе дело:")

@bot.message_handler(commands=['points'])
def points_command(message):
    user_id = message.from_user.id
    chat_id = message.chat.id
    
    try:
        child = get_child(user_id)
        recent_deeds = get_recent_deeds(child)
        
        text = f"🌟 У тебя сейчас *{child.total_points} баллов*! 🌟\n\n"
        if recent_deeds:
            text += "📋 *Твои последние добрые дела:*\n"
            for deed in recent_deeds:
                date_str = deed.created_at.strftime("%d.%m.%Y")
                text += f"• {deed.description}: *{deed.points} баллов* ({date_str})\n"
        
        keyboard = types.InlineKeyboardMarkup()
        keyboard.add(types.InlineKeyboardButton("◀️ Назад в меню", callback_data="back_to_menu"))
        
        bot.send_message(
            chat_id,
            text,
            parse_mode='Markdown',
            reply_markup=keyboard
        )
    except Exception as e:
        logger.error(f"Ошибка при получении баллов: {e}")
        bot.send_message(chat_id, "Произошла ошибка. Пожалуйста, начните сначала с /start")

@bot.message_handler(commands=['rewards'])
def rewards_command(message):
    chat_id = message.chat.id
    
    try:
        rewards = get_rewards()
        
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
        
        keyboard = types.InlineKeyboardMarkup()
        keyboard.add(types.InlineKeyboardButton("◀️ Назад в меню", callback_data="back_to_menu"))
        
        bot.send_message(
            chat_id,
            text,
            parse_mode='Markdown',
            reply_markup=keyboard
        )
    except Exception as e:
        logger.error(f"Ошибка при получении наград: {e}")
        bot.send_message(chat_id, "Произошла ошибка. Пожалуйста, начните сначала с /start")

@bot.message_handler(commands=['parent'])
def parent_command(message):
    user_id = message.from_user.id
    chat_id = message.chat.id
    
    try:
        # Проверяем, зарегистрирован ли пользователь как родитель
        parent_obj, is_parent = get_parent(user_id)
        
        if is_parent:
            # Родитель существует, запрашиваем пароль
            bot.send_message(chat_id, f"Здравствуйте, {parent_obj.name}! Для доступа к режиму родителя, пожалуйста, введите пароль:")
            
            # Устанавливаем состояние PARENT_PASSWORD
            bot.set_state(user_id, BotStates.PARENT_PASSWORD, chat_id)
            with bot.retrieve_data(user_id, chat_id) as data:
                data['registering_parent'] = False
        else:
            # Новый родитель, предлагаем зарегистрироваться
            bot.send_message(
                chat_id,
                "Вы еще не зарегистрированы как родитель. Хотите зарегистрироваться?\n\n"
                "Введите пароль, который будет использоваться для входа в режим родителя:"
            )
            
            # Устанавливаем состояние PARENT_PASSWORD
            bot.set_state(user_id, BotStates.PARENT_PASSWORD, chat_id)
            with bot.retrieve_data(user_id, chat_id) as data:
                data['registering_parent'] = True
    except Exception as e:
        logger.error(f"Ошибка при обработке команды parent: {e}")
        bot.send_message(chat_id, "Произошла ошибка. Пожалуйста, начните сначала с /start")

@bot.message_handler(commands=['cancel'])
def cancel_command(message):
    user_id = message.from_user.id
    chat_id = message.chat.id
    
    # Сбрасываем состояние
    bot.delete_state(user_id, chat_id)
    
    bot.send_message(
        chat_id,
        "❌ Действие отменено. Используйте /start для возврата в главное меню."
    )

@bot.message_handler(state=BotStates.WAITING_DEED)
def process_deed_description(message):
    user_id = message.from_user.id
    chat_id = message.chat.id
    
    # Сохраняем описание дела в данных состояния
    with bot.retrieve_data(user_id, chat_id) as data:
        data['deed_description'] = message.text
    
    # Переходим к запросу баллов
    bot.set_state(user_id, BotStates.WAITING_POINTS, chat_id)
    bot.send_message(chat_id, "👍 Отлично! Теперь укажи, сколько баллов ты получил за это дело:")

@bot.message_handler(state=BotStates.WAITING_POINTS)
def process_deed_points(message):
    user_id = message.from_user.id
    chat_id = message.chat.id
    
    try:
        points = int(message.text)
        if points <= 0:
            bot.send_message(chat_id, "❌ Баллы должны быть положительным числом. Попробуй еще раз:")
            return
        
        # Получаем данные пользователя
        child = get_child(user_id)
        
        # Получаем сохраненное описание дела
        with bot.retrieve_data(user_id, chat_id) as data:
            deed_description = data.get('deed_description', 'Доброе дело')
        
        # Создаем запись о добром деле
        deed = create_deed(
            child,
            deed_description,
            points
        )
        
        # Обновляем общее количество баллов
        total_points = update_child_points(child, points)
        
        # Создаем клавиатуру для следующих действий
        keyboard = types.InlineKeyboardMarkup()
        keyboard.add(types.InlineKeyboardButton("📝 Добавить еще доброе дело", callback_data="add_deed"))
        keyboard.add(types.InlineKeyboardButton("🏠 Вернуться в меню", callback_data="back_to_menu"))
        
        # Отправляем сообщение об успешном добавлении
        bot.send_message(
            chat_id,
            f"🎉 Отлично! Доброе дело '{deed_description}' добавлено.\n\n"
            f"Ты получил *{points} баллов*!\n"
            f"Всего у тебя теперь *{total_points} баллов*.",
            parse_mode='Markdown',
            reply_markup=keyboard
        )
        
        # Сбрасываем состояние
        bot.delete_state(user_id, chat_id)
        
    except ValueError:
        bot.send_message(chat_id, "❌ Пожалуйста, введи число. Попробуй еще раз:")

@bot.message_handler(state=BotStates.PARENT_PASSWORD)
def process_parent_password(message):
    user_id = message.from_user.id
    chat_id = message.chat.id
    password = message.text
    
    try:
        # Определяем, новый родитель или существующий
        with bot.retrieve_data(user_id, chat_id) as data:
            is_registering = data.get('registering_parent', False)
        
        if is_registering:
            # Регистрация нового родителя
            parent, created = get_or_create_parent(user_id, message.from_user.first_name)
            set_parent_password(parent, password)
            
            # Создаем клавиатуру для меню родителя
            keyboard = types.InlineKeyboardMarkup()
            keyboard.add(types.InlineKeyboardButton("➕ Добавить ребенка", callback_data="add_child"))
            keyboard.add(types.InlineKeyboardButton("📊 Просмотр статистики детей", callback_data="view_children"))
            keyboard.add(types.InlineKeyboardButton("🏠 В главное меню", callback_data="exit_parent_mode"))
            
            bot.send_message(
                chat_id,
                f"🎉 Поздравляем! Вы зарегистрированы как родитель.\n\n"
                "Теперь вы можете добавлять добрые дела вашим детям и следить за их прогрессом.",
                reply_markup=keyboard
            )
            
            # Устанавливаем состояние PARENT_MENU
            bot.set_state(user_id, BotStates.PARENT_MENU, chat_id)
        else:
            # Проверка пароля существующего родителя
            parent_obj, is_parent = get_parent(user_id)
            if is_parent:
                is_valid = verify_parent_password(parent_obj, password)
                
                if is_valid:
                    # Пароль верный, показываем меню родителя
                    children = get_parent_children(parent_obj)
                    
                    # Создаем клавиатуру для меню родителя
                    keyboard = types.InlineKeyboardMarkup()
                    if children:
                        keyboard.add(types.InlineKeyboardButton("➕ Добавить доброе дело ребенку", callback_data="add_deed_to_child"))
                        keyboard.add(types.InlineKeyboardButton("📊 Просмотр статистики детей", callback_data="view_children"))
                    
                    keyboard.add(types.InlineKeyboardButton("➕ Добавить ребенка", callback_data="add_child"))
                    keyboard.add(types.InlineKeyboardButton("🏠 В главное меню", callback_data="exit_parent_mode"))
                    
                    bot.send_message(
                        chat_id,
                        f"👋 Здравствуйте, {parent_obj.name}! Вы вошли в режим родителя.\n\n"
                        f"У вас {len(children)} {'детей' if len(children) != 1 else 'ребенок'} в системе.\n\n"
                        "Выберите действие:",
                        reply_markup=keyboard
                    )
                    
                    # Устанавливаем состояние PARENT_MENU
                    bot.set_state(user_id, BotStates.PARENT_MENU, chat_id)
                else:
                    # Пароль неверный
                    bot.send_message(
                        chat_id,
                        "❌ Неверный пароль. Пожалуйста, попробуйте еще раз или введите /cancel для отмены."
                    )
            else:
                # Родитель не найден, предлагаем зарегистрироваться
                bot.send_message(
                    chat_id,
                    "Произошла ошибка: родитель не найден. Пожалуйста, начните регистрацию заново с /parent"
                )
                bot.delete_state(user_id, chat_id)
    except Exception as e:
        logger.error(f"Ошибка при обработке пароля родителя: {e}")
        bot.send_message(chat_id, "Произошла ошибка. Пожалуйста, начните сначала с /start")
        bot.delete_state(user_id, chat_id)

@bot.message_handler(state=BotStates.PARENT_ADD_CHILD)
def process_add_child(message):
    user_id = message.from_user.id
    chat_id = message.chat.id
    child_name = message.text.strip()
    
    try:
        parent_obj, is_parent = get_parent(user_id)
        if is_parent:
            # Проверяем, существует ли ребенок с таким именем
            child = get_child_by_name(child_name)
            
            if child:
                # Если ребенок найден, привязываем его к родителю
                add_child_to_parent(parent_obj, child)
                
                bot.send_message(
                    chat_id,
                    f"✅ Ребенок *{child.name}* успешно добавлен!\n\n"
                    f"У него сейчас *{child.total_points} баллов*.\n\n"
                    "Используйте /parent для возврата в меню родителя.",
                    parse_mode='Markdown'
                )
            else:
                # Если ребенок не найден, предлагаем зарегистрировать его через бота
                bot.send_message(
                    chat_id,
                    f"❓ Ребенок с именем '{child_name}' не найден в системе.\n\n"
                    "Попросите ребенка зарегистрироваться в боте с помощью команды /start, "
                    "а затем добавьте его снова.\n\n"
                    "Используйте /parent для возврата в меню родителя."
                )
            
            # Сбрасываем состояние
            bot.delete_state(user_id, chat_id)
        else:
            bot.send_message(
                chat_id,
                "❌ Ошибка: родитель не найден. Пожалуйста, начните с /parent."
            )
            bot.delete_state(user_id, chat_id)
    except Exception as e:
        logger.error(f"Ошибка при добавлении ребенка: {e}")
        bot.send_message(
            chat_id,
            "❌ Произошла ошибка. Пожалуйста, попробуйте еще раз или используйте /start для начала."
        )
        bot.delete_state(user_id, chat_id)

@bot.message_handler(state=BotStates.PARENT_ADD_DEED)
def process_parent_deed_description(message):
    user_id = message.from_user.id
    chat_id = message.chat.id
    
    try:
        # Сохраняем описание дела
        with bot.retrieve_data(user_id, chat_id) as data:
            data['deed_description'] = message.text
        
        bot.send_message(
            chat_id,
            "👍 Отлично! Теперь укажите, сколько баллов получает ребенок за это дело:"
        )
        
        # Обновляем состояние
        bot.set_state(user_id, BotStates.PARENT_ADD_POINTS, chat_id)
    except Exception as e:
        logger.error(f"Ошибка при добавлении описания дела: {e}")
        bot.send_message(
            chat_id,
            "❌ Произошла ошибка. Пожалуйста, попробуйте еще раз или используйте /start для начала."
        )
        bot.delete_state(user_id, chat_id)

@bot.message_handler(state=BotStates.PARENT_ADD_POINTS)
def process_parent_deed_points(message):
    user_id = message.from_user.id
    chat_id = message.chat.id
    
    try:
        points = int(message.text)
        if points <= 0:
            bot.send_message(
                chat_id,
                "❌ Баллы должны быть положительным числом. Попробуйте еще раз:"
            )
            return
        
        # Получаем данные родителя и ребенка из сохраненного состояния
        parent_obj, is_parent = get_parent(user_id)
        with bot.retrieve_data(user_id, chat_id) as data:
            child_telegram_id = data.get('selected_child_id')
            deed_description = data.get('deed_description', 'Доброе дело')
        
        if not child_telegram_id:
            bot.send_message(
                chat_id,
                "❌ Ошибка: не выбран ребенок. Пожалуйста, начните заново с /parent."
            )
            
            # Сбрасываем состояние
            bot.delete_state(user_id, chat_id)
            return
        
        child = get_child(child_telegram_id)
        
        # Создаем запись о добром деле
        deed = create_deed(
            child,
            deed_description,
            points,
            parent_obj
        )
        
        # Обновляем общее количество баллов
        total_points = update_child_points(child, points)
        
        bot.send_message(
            chat_id,
            f"🎉 Доброе дело для {child.name} успешно добавлено!\n\n"
            f"Доброе дело: *{deed_description}*\n"
            f"Баллы: *+{points}*\n"
            f"Всего у ребенка теперь *{total_points} баллов*.\n\n"
            "Используйте /parent для возврата в меню родителя.",
            parse_mode='Markdown'
        )
        
        # Сбрасываем состояние
        bot.delete_state(user_id, chat_id)
        
    except ValueError:
        bot.send_message(
            chat_id,
            "❌ Пожалуйста, введите число. Попробуйте еще раз:"
        )
    except Exception as e:
        logger.error(f"Ошибка при добавлении баллов от родителя: {e}")
        bot.send_message(
            chat_id,
            "❌ Произошла ошибка. Пожалуйста, попробуйте еще раз или используйте /start для начала."
        )
        bot.delete_state(user_id, chat_id)

# Обработчик callback-запросов
@bot.callback_query_handler(func=lambda call: True)
def callback_handler(call):
    try:
        user_id = call.from_user.id
        chat_id = call.message.chat.id
        logger.info(f"Callback query: {call.data} from user {user_id}")
        
        # Обработка различных callback-запросов
        if call.data == "add_deed":
            # Устанавливаем состояние WAITING_DEED
            bot.set_state(user_id, BotStates.WAITING_DEED, chat_id)
            
            # Запрашиваем описание доброго дела
            bot.send_message(chat_id, "📝 Опиши свое доброе дело:")
            
            # Отвечаем на callback
            bot.answer_callback_query(call.id)
        
        elif call.data == "check_points":
            try:
                child = get_child(user_id)
                recent_deeds = get_recent_deeds(child)
                
                text = f"🌟 У тебя сейчас *{child.total_points} баллов*! 🌟\n\n"
                if recent_deeds:
                    text += "📋 *Твои последние добрые дела:*\n"
                    for deed in recent_deeds:
                        date_str = deed.created_at.strftime("%d.%m.%Y")
                        text += f"• {deed.description}: *{deed.points} баллов* ({date_str})\n"
                
                keyboard = types.InlineKeyboardMarkup()
                keyboard.add(types.InlineKeyboardButton("◀️ Назад в меню", callback_data="back_to_menu"))
                
                bot.edit_message_text(
                    text,
                    chat_id,
                    call.message.message_id,
                    parse_mode='Markdown',
                    reply_markup=keyboard
                )
            except Exception as e:
                logger.error(f"Ошибка при просмотре баллов: {e}")
                bot.send_message(chat_id, "Произошла ошибка. Пожалуйста, начните сначала с /start")
            
            bot.answer_callback_query(call.id)
        
        elif call.data == "view_rewards":
            try:
                rewards = get_rewards()
                
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
               
                keyboard = types.InlineKeyboardMarkup()
                keyboard.add(types.InlineKeyboardButton("◀️ Назад в меню", callback_data="back_to_menu"))
               
                bot.edit_message_text(
                    text,
                    chat_id,
                    call.message.message_id,
                    parse_mode='Markdown',
                    reply_markup=keyboard
                )
            except Exception as e:
                logger.error(f"Ошибка при просмотре наград: {e}")
                bot.send_message(chat_id, "Произошла ошибка. Пожалуйста, начните сначала с /start")
           
            bot.answer_callback_query(call.id)
       
        elif call.data == "help":
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
           
            keyboard = types.InlineKeyboardMarkup()
            keyboard.add(types.InlineKeyboardButton("◀️ Назад в меню", callback_data="back_to_menu"))
           
            try:
                bot.edit_message_text(
                    help_text,
                    chat_id,
                    call.message.message_id,
                    parse_mode='Markdown',
                    reply_markup=keyboard
                )
            except Exception as e:
                logger.error(f"Ошибка при редактировании сообщения: {e}")
                bot.send_message(
                    chat_id,
                    help_text,
                    parse_mode='Markdown',
                    reply_markup=keyboard
                )
           
            bot.answer_callback_query(call.id)
       
        elif call.data == "register_parent":
            # Если сообщение из группы
            if call.message.chat.type in ['group', 'supergroup']:
                bot.send_message(
                    chat_id,
                    f"@{call.from_user.username or call.from_user.first_name}, для регистрации как родитель, "
                    f"пожалуйста, напишите боту в личные сообщения."
                )
            else:
                # Проверяем, зарегистрирован ли пользователь как родитель
                parent_obj, is_parent = get_parent(user_id)
               
                if is_parent:
                    # Родитель существует, запрашиваем пароль
                    bot.send_message(chat_id, f"Здравствуйте, {parent_obj.name}! Для доступа к режиму родителя, пожалуйста, введите пароль:")
                   
                    # Устанавливаем состояние PARENT_PASSWORD
                    bot.set_state(user_id, BotStates.PARENT_PASSWORD, chat_id)
                    with bot.retrieve_data(user_id, chat_id) as data:
                        data['registering_parent'] = False
                else:
                    # Новый родитель, предлагаем зарегистрироваться
                    bot.send_message(
                        chat_id,
                        "Вы еще не зарегистрированы как родитель. Хотите зарегистрироваться?\n\n"
                        "Введите пароль, который будет использоваться для входа в режим родителя:"
                    )
                   
                    # Устанавливаем состояние PARENT_PASSWORD
                    bot.set_state(user_id, BotStates.PARENT_PASSWORD, chat_id)
                    with bot.retrieve_data(user_id, chat_id) as data:
                        data['registering_parent'] = True
           
            bot.answer_callback_query(call.id)
       
        elif call.data == "add_child":
            bot.send_message(
                chat_id,
                "👶 Введите имя ребенка, которого хотите добавить:"
            )
           
            # Устанавливаем состояние PARENT_ADD_CHILD
            bot.set_state(user_id, BotStates.PARENT_ADD_CHILD, chat_id)
           
            bot.answer_callback_query(call.id)
       
        elif call.data == "view_children":
            try:
                parent_obj, is_parent = get_parent(user_id)
                if is_parent:
                    children = get_parent_children(parent_obj)
                   
                    if not children:
                        keyboard = types.InlineKeyboardMarkup()
                        keyboard.add(types.InlineKeyboardButton("➕ Добавить ребенка", callback_data="add_child"))
                        keyboard.add(types.InlineKeyboardButton("🏠 В главное меню", callback_data="exit_parent_mode"))
                       
                        bot.send_message(
                            chat_id,
                            "У вас пока нет добавленных детей. Добавьте ребенка, чтобы видеть его статистику.",
                            reply_markup=keyboard
                        )
                    else:
                        text = "📊 *Статистика ваших детей:*\n\n"
                        for child in children:
                            recent_deeds = get_recent_deeds(child, limit=3)
                           
                            text += f"👶 *{child.name}*: {child.total_points} баллов\n"
                            if recent_deeds:
                                text += "Последние добрые дела:\n"
                                for deed in recent_deeds:
                                    date_str = deed.created_at.strftime("%d.%m.%Y")
                                    text += f"• {deed.description}: {deed.points} баллов ({date_str})\n"
                            text += "\n"
                       
                        keyboard = types.InlineKeyboardMarkup()
                        keyboard.add(types.InlineKeyboardButton("➕ Добавить доброе дело", callback_data="add_deed_to_child"))
                        keyboard.add(types.InlineKeyboardButton("◀️ Назад", callback_data="back_to_parent_menu"))
                       
                        bot.send_message(
                            chat_id,
                            text,
                            parse_mode='Markdown',
                            reply_markup=keyboard
                        )
                else:
                    bot.send_message(
                        chat_id,
                        "❌ Ошибка: родитель не найден. Пожалуйста, начните с /parent."
                    )
            except Exception as e:
                logger.error(f"Ошибка при просмотре статистики детей: {e}")
                bot.send_message(
                    chat_id,
                    "❌ Произошла ошибка. Пожалуйста, попробуйте еще раз."
                )
           
            bot.answer_callback_query(call.id)
       
        elif call.data == "add_deed_to_child":
            try:
                parent_obj, is_parent = get_parent(user_id)
                if is_parent:
                    children = get_parent_children(parent_obj)
                   
                    if not children:
                        keyboard = types.InlineKeyboardMarkup()
                        keyboard.add(types.InlineKeyboardButton("➕ Добавить ребенка", callback_data="add_child"))
                        keyboard.add(types.InlineKeyboardButton("🏠 В главное меню", callback_data="exit_parent_mode"))
                       
                        bot.send_message(
                            chat_id,
                            "У вас пока нет добавленных детей. Добавьте ребенка, чтобы добавлять ему добрые дела.",
                            reply_markup=keyboard
                        )
                    else:
                        # Создаем кнопки для выбора ребенка
                        keyboard = types.InlineKeyboardMarkup()
                        for child in children:
                            keyboard.add(types.InlineKeyboardButton(f"👶 {child.name}", callback_data=f"select_child_{child.telegram_id}"))
                       
                        keyboard.add(types.InlineKeyboardButton("◀️ Назад", callback_data="back_to_parent_menu"))
                       
                        bot.send_message(
                            chat_id,
                            "Выберите ребенка, которому хотите добавить доброе дело:",
                            reply_markup=keyboard
                        )
                else:
                    bot.send_message(
                        chat_id,
                        "❌ Ошибка: родитель не найден. Пожалуйста, начните с /parent."
                    )
            except Exception as e:
                logger.error(f"Ошибка при выборе ребенка: {e}")
                bot.send_message(
                    chat_id,
                    "❌ Произошла ошибка. Пожалуйста, попробуйте еще раз."
                )
           
            bot.answer_callback_query(call.id)
       
        elif call.data.startswith("select_child_"):
            try:
                child_telegram_id = int(call.data.split("_")[-1])
                child = get_child(child_telegram_id)
               
                # Сохраняем ID выбранного ребенка
                bot.set_state(user_id, BotStates.PARENT_ADD_DEED, chat_id)
                with bot.retrieve_data(user_id, chat_id) as data:
                    data['selected_child_id'] = child_telegram_id
               
                bot.send_message(
                    chat_id,
                    f"Вы выбрали ребенка: *{child.name}*\n\n"
                    "Опишите доброе дело, которое совершил ребенок:",
                    parse_mode='Markdown'
                )
            except Exception as e:
                logger.error(f"Ошибка при выборе ребенка: {e}")
                bot.send_message(
                    chat_id,
                    "❌ Произошла ошибка. Пожалуйста, попробуйте еще раз."
                )
           
            bot.answer_callback_query(call.id)
       
        elif call.data == "back_to_parent_menu":
            try:
                parent_obj, is_parent = get_parent(user_id)
                if is_parent:
                    children = get_parent_children(parent_obj)
                   
                    # Создаем клавиатуру для меню родителя
                    keyboard = types.InlineKeyboardMarkup()
                    if children:
                        keyboard.add(types.InlineKeyboardButton("➕ Добавить доброе дело ребенку", callback_data="add_deed_to_child"))
                        keyboard.add(types.InlineKeyboardButton("📊 Просмотр статистики детей", callback_data="view_children"))
                   
                    keyboard.add(types.InlineKeyboardButton("➕ Добавить ребенка", callback_data="add_child"))
                    keyboard.add(types.InlineKeyboardButton("🏠 В главное меню", callback_data="exit_parent_mode"))
                   
                    bot.send_message(
                        chat_id,
                        f"👋 Здравствуйте, {parent_obj.name}! Вы в режиме родителя.\n\n"
                        f"У вас {len(children)} {'детей' if len(children) != 1 else 'ребенок'} в системе.\n\n"
                        "Выберите действие:",
                        reply_markup=keyboard
                    )
                else:
                    bot.send_message(
                        chat_id,
                        "❌ Ошибка: родитель не найден. Пожалуйста, начните с /parent."
                    )
            except Exception as e:
                logger.error(f"Ошибка при возврате в меню родителя: {e}")
                bot.send_message(
                    chat_id,
                    "❌ Произошла ошибка. Пожалуйста, попробуйте еще раз."
                )
           
            bot.answer_callback_query(call.id)
       
        elif call.data == "exit_parent_mode":
            bot.send_message(
                chat_id,
                "Вы вышли из режима родителя. Используйте /start для начала работы с ботом."
            )
           
            # Сбрасываем состояние
            bot.delete_state(user_id, chat_id)
           
            bot.answer_callback_query(call.id)
       
        elif call.data == "back_to_menu":
            try:
                # Получаем данные пользователя
                child = get_child(user_id)
               
                text = (
                    f"Привет, {child.name}! 👋 Это бот для записи твоих добрых дел.\n\n"
                    f"У тебя сейчас *{child.total_points} баллов*.\n\n"
                    "Выбери действие:"
                )
               
                # Создаем клавиатуру с кнопками
                keyboard = types.InlineKeyboardMarkup()
                keyboard.add(types.InlineKeyboardButton("📝 Добавить доброе дело", callback_data="add_deed"))
                keyboard.add(types.InlineKeyboardButton("🌟 Мои баллы", callback_data="check_points"))
                keyboard.add(types.InlineKeyboardButton("🎁 Посмотреть награды", callback_data="view_rewards"))
                keyboard.add(types.InlineKeyboardButton("❓ Помощь", callback_data="help"))
                keyboard.add(types.InlineKeyboardButton("👨‍👩‍👧‍👦 Я родитель", callback_data="register_parent"))
               
                bot.edit_message_text(
                    text,
                    chat_id,
                    call.message.message_id,
                    parse_mode='Markdown',
                    reply_markup=keyboard
                )
               
                # Сбрасываем состояние
                bot.delete_state(user_id, chat_id)
            except Exception as e:
                logger.error(f"Ошибка при возврате в меню: {e}")
                bot.send_message(chat_id, "Произошла ошибка. Пожалуйста, начните сначала с /start")
           
            bot.answer_callback_query(call.id)
       
        else:
            logger.warning(f"Неизвестный callback_data: {call.data}")
            bot.answer_callback_query(call.id, "Неизвестная команда")
   
    except Exception as e:
        logger.error(f"Ошибка в callback_handler: {e}")
        bot.answer_callback_query(call.id, "Произошла ошибка")

# Глобальный обработчик для всех сообщений
@bot.message_handler(func=lambda message: True)
def handle_all_messages(message):
    # Проверяем, есть ли у пользователя активное состояние
    user_id = message.from_user.id
    chat_id = message.chat.id
    current_state = bot.get_state(user_id, chat_id)
   
    # Если нет активного состояния и сообщение не является командой, предлагаем /start
    if not current_state and not message.text.startswith('/'):
        bot.send_message(
            chat_id,
            "Чтобы начать работу с ботом, используйте команду /start."
        )

# Маршруты Flask для webhook
@app.route(f'/{TOKEN}', methods=['POST'])
def webhook():
    if request.headers.get('content-type') == 'application/json':
        update = request.get_json()
        logger.info(f"Получен update: {update}")
       
        # Обработка входящего обновления от Telegram
        bot.process_new_updates([telebot.types.Update.de_json(update)])
        return jsonify({'status': 'ok'})
    else:
        return jsonify({'status': 'error'})

@app.route('/set_webhook', methods=['GET'])
def set_webhook():
    webhook_url = f"https://{request.host}/{TOKEN}"
    bot.remove_webhook()
    bot.set_webhook(url=webhook_url)
    return jsonify({'status': 'webhook установлен', 'url': webhook_url})

@app.route('/remove_webhook', methods=['GET'])
def remove_webhook():
    bot.remove_webhook()
    return jsonify({'status': 'webhook удален'})

@app.route('/webhook_status', methods=['GET'])
def webhook_status():
    try:
        webhook_info = bot.get_webhook_info()
        return jsonify({
            'status': 'success',
            'url': webhook_info.url,
            'has_custom_certificate': webhook_info.has_custom_certificate,
            'pending_update_count': webhook_info.pending_update_count,
            'last_error_date': webhook_info.last_error_date,
            'last_error_message': webhook_info.last_error_message,
            'max_connections': webhook_info.max_connections
        })
    except Exception as e:
        logger.error(f"Ошибка при получении статуса webhook: {e}")
        return jsonify({'status': 'error', 'message': str(e)})

@app.route('/')
def home():
    return 'Бот для учета добрых дел успешно запущен!'

# Добавим отладочную информацию при запуске
logger.info(f"Бот инициализирован с токеном: {TOKEN[:5]}...")
logger.info(f"Django установлен: {django.get_version()}")

if __name__ == '__main__':
    app.run(debug=True)
  
