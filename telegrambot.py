from telebot.async_telebot import AsyncTeleBot
from telebot.asyncio_storage import StateMemoryStorage
from telebot.asyncio_handler_backends import State, StatesGroup
import asyncio
import logging

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

# Определение состояний бота
class BotStates(StatesGroup):
    IDLE = State()                # Ожидание команды
    WAITING_DEED = State()        # Ожидание описания доброго дела
    WAITING_POINTS = State()      # Ожидание ввода баллов
    PARENT_PASSWORD = State()     # Ожидание ввода пароля родителя
    PARENT_MENU = State()         # Меню родителя
    PARENT_ADD_CHILD = State()    # Добавление ребенка
    PARENT_ADD_DEED = State()     # Добавление дела ребенку (ожидание описания)
    PARENT_ADD_POINTS = State()   # Добавление дела ребенку (ожидание баллов)

# Создаем экземпляр бота
TOKEN = '7369216646:AAGa1YcPHSTWiG6J1CHHRjJ_1OGlmp4Crh8'  # Замените на ваш токен
bot = AsyncTeleBot(TOKEN, state_storage=StateMemoryStorage())

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

# Определение состояний бота
class BotStates(StatesGroup):
    IDLE = State()                # Ожидание команды
    WAITING_DEED = State()        # Ожидание описания доброго дела
    WAITING_POINTS = State()      # Ожидание ввода баллов
    PARENT_PASSWORD = State()     # Ожидание ввода пароля родителя
    PARENT_MENU = State()         # Меню родителя
    PARENT_ADD_CHILD = State()    # Добавление ребенка
    PARENT_ADD_DEED = State()     # Добавление дела ребенку (ожидание описания)
    PARENT_ADD_POINTS = State()   # Добавление дела ребенку (ожидание баллов)

# Создаем экземпляр бота с использованием хранилища состояний
TOKEN = os.environ.get('TELEGRAM_TOKEN')
bot = AsyncTeleBot(TOKEN, state_storage=StateMemoryStorage())

# Функции для работы с Django в асинхронном режиме
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
    try:
        return Parent.objects.get(telegram_id=telegram_id)
    except Parent.DoesNotExist:
        return None

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
    # Простое хеширование пароля
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

# Функция для создания клавиатуры главного меню
def get_main_menu_keyboard():
    keyboard = types.InlineKeyboardMarkup()
    keyboard.add(types.InlineKeyboardButton("📝 Добавить доброе дело", callback_data="add_deed"))
    keyboard.add(types.InlineKeyboardButton("🌟 Мои баллы", callback_data="check_points"))
    keyboard.add(types.InlineKeyboardButton("🎁 Посмотреть награды", callback_data="view_rewards"))
    keyboard.add(types.InlineKeyboardButton("❓ Помощь", callback_data="help"))
    keyboard.add(types.InlineKeyboardButton("👨‍👩‍👧‍👦 Я родитель", callback_data="register_parent"))
    return keyboard

# Обработчик команды /start
@bot.message_handler(commands=['start'])
async def start_command(message):
    user_id = message.from_user.id
    username = message.from_user.first_name
    
    # Проверяем, зарегистрирован ли пользователь как ребенок
    child, created = await get_or_create_child(user_id, username)
    
    welcome_text = (
        f"Привет, {child.name}! 👋 Это бот для записи твоих добрых дел.\n\n"
        f"У тебя сейчас *{child.total_points} баллов*.\n\n"
        "Выбери действие:"
    )
    
    # Устанавливаем состояние IDLE
    await bot.set_state(user_id, BotStates.IDLE, message.chat.id)
    
    # Отправляем сообщение с клавиатурой
    await bot.send_message(
        message.chat.id, 
        welcome_text, 
        parse_mode='Markdown',
        reply_markup=get_main_menu_keyboard()
    )

# Обработчик команды /help
@bot.message_handler(commands=['help'])
async def help_command(message):
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
    
    await bot.send_message(
        message.chat.id, 
        help_text, 
        parse_mode='Markdown',
        reply_markup=keyboard
    )

# Обработчик команды /add
@bot.message_handler(commands=['add'])
async def add_command(message):
    user_id = message.from_user.id
    
    # Устанавливаем состояние WAITING_DEED
    await bot.set_state(user_id, BotStates.WAITING_DEED, message.chat.id)
    
    # Запрашиваем описание доброго дела
    await bot.send_message(message.chat.id, "📝 Опиши свое доброе дело:")

# Обработчик для получения описания доброго дела
@bot.message_handler(state=BotStates.WAITING_DEED)
async def process_deed_description(message):
    user_id = message.from_user.id
    chat_id = message.chat.id
    
    # Сохраняем описание дела в данных состояния
    async with bot.retrieve_data(user_id, chat_id) as data:
        data['deed_description'] = message.text
    
    # Переходим к запросу баллов
    await bot.set_state(user_id, BotStates.WAITING_POINTS, chat_id)
    await bot.send_message(chat_id, "👍 Отлично! Теперь укажи, сколько баллов ты получил за это дело:")

# Обработчик для получения количества баллов
@bot.message_handler(state=BotStates.WAITING_POINTS)
async def process_deed_points(message):
    user_id = message.from_user.id
    chat_id = message.chat.id
    
    try:
        points = int(message.text)
        if points <= 0:
            await bot.send_message(chat_id, "❌ Баллы должны быть положительным числом. Попробуй еще раз:")
            return
        
        # Получаем данные пользователя
        child = await get_child(user_id)
        
        # Получаем сохраненное описание дела
        async with bot.retrieve_data(user_id, chat_id) as data:
            deed_description = data.get('deed_description', 'Доброе дело')
        
        # Создаем запись о добром деле
        deed = await create_deed(
            child,
            deed_description,
            points
        )
        
        # Обновляем общее количество баллов
        total_points = await update_child_points(child, points)
        
        # Создаем клавиатуру для следующих действий
        keyboard = types.InlineKeyboardMarkup()
        keyboard.add(types.InlineKeyboardButton("📝 Добавить еще доброе дело", callback_data="add_deed"))
        keyboard.add(types.InlineKeyboardButton("🏠 Вернуться в меню", callback_data="back_to_menu"))
        
        # Отправляем сообщение об успешном добавлении
        await bot.send_message(
            chat_id,
            f"🎉 Отлично! Доброе дело '{deed_description}' добавлено.\n\n"
            f"Ты получил *{points} баллов*!\n"
            f"Всего у тебя теперь *{total_points} баллов*.",
            parse_mode='Markdown',
            reply_markup=keyboard
        )
        
        # Сбрасываем состояние
        await bot.delete_state(user_id, chat_id)
        
    except ValueError:
        await bot.send_message(chat_id, "❌ Пожалуйста, введи число. Попробуй еще раз:")

# Обработчик команды /points
@bot.message_handler(commands=['points'])
async def points_command(message):
    user_id = message.from_user.id
    chat_id = message.chat.id
    
    try:
        child = await get_child(user_id)
        recent_deeds = await get_recent_deeds(child)
        
        text = f"🌟 У тебя сейчас *{child.total_points} баллов*! 🌟\n\n"
        if recent_deeds:
            text += "📋 *Твои последние добрые дела:*\n"
            for deed in recent_deeds:
                date_str = deed.created_at.strftime("%d.%m.%Y")
                text += f"• {deed.description}: *{deed.points} баллов* ({date_str})\n"
        
        keyboard = types.InlineKeyboardMarkup()
        keyboard.add(types.InlineKeyboardButton("◀️ Назад в меню", callback_data="back_to_menu"))
        
        await bot.send_message(
            chat_id,
            text,
            parse_mode='Markdown',
            reply_markup=keyboard
        )
    except Exception as e:
        logger.error(f"Ошибка при получении баллов: {e}")
        await bot.send_message(chat_id, "Произошла ошибка. Пожалуйста, начните сначала с /start")

# Обработчик команды /rewards
@bot.message_handler(commands=['rewards'])
async def rewards_command(message):
    chat_id = message.chat.id
    
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
        
        keyboard = types.InlineKeyboardMarkup()
        keyboard.add(types.InlineKeyboardButton("◀️ Назад в меню", callback_data="back_to_menu"))
        
        await bot.send_message(
            chat_id,
            text,
            parse_mode='Markdown',
            reply_markup=keyboard
        )
    except Exception as e:
        logger.error(f"Ошибка при получении наград: {e}")
        await bot.send_message(chat_id, "Произошла ошибка. Пожалуйста, начните сначала с /start")

# Обработчик команды /parent
@bot.message_handler(commands=['parent'])
async def parent_command(message):
    user_id = message.from_user.id
    chat_id = message.chat.id
    
    try:
        # Проверяем, зарегистрирован ли пользователь как родитель
        parent, is_parent = await verify_parent(user_id)
        
        if is_parent:
            # Родитель существует, запрашиваем пароль
            await bot.send_message(chat_id, f"Здравствуйте, {parent.name}! Для доступа к режиму родителя, пожалуйста, введите пароль:")
            
            # Устанавливаем состояние PARENT_PASSWORD и сохраняем флаг, что это существующий родитель
            await bot.set_state(user_id, BotStates.PARENT_PASSWORD, chat_id)
            async with bot.retrieve_data(user_id, chat_id) as data:
                data['registering_parent'] = False
        else:
            # Новый родитель, предлагаем зарегистрироваться
            await bot.send_message(
                chat_id,
                "Вы еще не зарегистрированы как родитель. Хотите зарегистрироваться?\n\n"
                "Введите пароль, который будет использоваться для входа в режим родителя:"
            )
            
            # Устанавливаем состояние PARENT_PASSWORD и сохраняем флаг, что это новый родитель
            await bot.set_state(user_id, BotStates.PARENT_PASSWORD, chat_id)
            async with bot.retrieve_data(user_id, chat_id) as data:
                data['registering_parent'] = True
    except Exception as e:
        logger.error(f"Ошибка при обработке команды parent: {e}")
        await bot.send_message(chat_id, "Произошла ошибка. Пожалуйста, начните сначала с /start")

# Обработчик ввода пароля родителя
@bot.message_handler(state=BotStates.PARENT_PASSWORD)
async def process_parent_password(message):
    user_id = message.from_user.id
    chat_id = message.chat.id
    password = message.text
    
    try:
        # Определяем, новый родитель или существующий
        async with bot.retrieve_data(user_id, chat_id) as data:
            is_registering = data.get('registering_parent', False)
        
        if is_registering:
            # Регистрация нового родителя
            parent, created = await get_or_create_parent(user_id, message.from_user.first_name)
            await set_parent_password(parent, password)
            
            # Создаем клавиатуру для меню родителя
            keyboard = types.InlineKeyboardMarkup()
            keyboard.add(types.InlineKeyboardButton("➕ Добавить ребенка", callback_data="add_child"))
            keyboard.add(types.InlineKeyboardButton("📊 Просмотр статистики детей", callback_data="view_children"))
            keyboard.add(types.InlineKeyboardButton("🏠 В главное меню", callback_data="exit_parent_mode"))
            
            await bot.send_message(
                chat_id,
                f"🎉 Поздравляем! Вы зарегистрированы как родитель.\n\n"
                "Теперь вы можете добавлять добрые дела вашим детям и следить за их прогрессом.",
                reply_markup=keyboard
            )
            
            # Устанавливаем состояние PARENT_MENU
            await bot.set_state(user_id, BotStates.PARENT_MENU, chat_id)
        else:
            # Проверка пароля существующего родителя
            parent = await get_parent(user_id)
            if parent:
                is_valid = await verify_parent_password(parent, password)
                
                if is_valid:
                    # Пароль верный, показываем меню родителя
                    children = await get_parent_children(parent)
                    
                    # Создаем клавиатуру для меню родителя
                    keyboard = types.InlineKeyboardMarkup()
                    if children:
                        keyboard.add(types.InlineKeyboardButton("➕ Добавить доброе дело ребенку", callback_data="add_deed_to_child"))
                        keyboard.add(types.InlineKeyboardButton("📊 Просмотр статистики детей", callback_data="view_children"))
                    
                    keyboard.add(types.InlineKeyboardButton("➕ Добавить ребенка", callback_data="add_child"))
                    keyboard.add(types.InlineKeyboardButton("🏠 В главное меню", callback_data="exit_parent_mode"))
                    
                    await bot.send_message(
                        chat_id,
                        f"👋 Здравствуйте, {parent.name}! Вы вошли в режим родителя.\n\n"
                        f"У вас {len(children)} {'детей' if len(children) != 1 else 'ребенок'} в системе.\n\n"
                        "Выберите действие:",
                        reply_markup=keyboard
                    )
                    
                    # Устанавливаем состояние PARENT_MENU
                    await bot.set_state(user_id, BotStates.PARENT_MENU, chat_id)
                else:
                    # Пароль неверный
                    await bot.send_message(
                        chat_id,
                        "❌ Неверный пароль. Пожалуйста, попробуйте еще раз или введите /cancel для отмены."
                    )
            else:
                # Родитель не найден, предлагаем зарегистрироваться
                await bot.send_message(
                    chat_id,
                    "Произошла ошибка: родитель не найден. Пожалуйста, начните регистрацию заново с /parent"
                )
                await bot.delete_state(user_id, chat_id)
    except Exception as e:
        logger.error(f"Ошибка при обработке пароля родителя: {e}")
        await bot.send_message(chat_id, "Произошла ошибка. Пожалуйста, начните сначала с /start")
        await bot.delete_state(user_id, chat_id)

# Обработчик callback-запросов (нажатий на кнопки)
@bot.callback_query_handler(func=lambda call: True)
async def process_callback(call):
    user_id = call.from_user.id
    chat_id = call.message.chat.id
    
    try:
        # Обработка кнопки "Добавить доброе дело"
        if call.data == "add_deed":
            # Устанавливаем состояние WAITING_DEED
            await bot.set_state(user_id, BotStates.WAITING_DEED, chat_id)
            
            # Запрашиваем описание доброго дела
            await bot.send_message(chat_id, "📝 Опиши свое доброе дело:")
            
            # Отвечаем на callback
            await bot.answer_callback_query(call.id)
        
        # Обработка кнопки "Мои баллы"
        elif call.data == "check_points":
            try:
                child = await get_child(user_id)
                recent_deeds = await get_recent_deeds(child)
                
                text = f"🌟 У тебя сейчас *{child.total_points} баллов*! 🌟\n\n"
                if recent_deeds:
                    text += "📋 *Твои последние добрые дела:*\n"
                    for deed in recent_deeds:
                        date_str = deed.created_at.strftime("%d.%m.%Y")
                        text += f"• {deed.description}: *{deed.points} баллов* ({date_str})\n"
                
                keyboard = types.InlineKeyboardMarkup()
                keyboard.add(types.InlineKeyboardButton("◀️ Назад в меню", callback_data="back_to_menu"))
                
                await bot.edit_message_text(
                    text,
                    chat_id,
                    call.message.message_id,
                    parse_mode='Markdown',
                    reply_markup=keyboard
                )
            except Exception as e:
                logger.error(f"Ошибка при просмотре баллов: {e}")
                await bot.send_message(chat_id, "Произошла ошибка. Пожалуйста, начните сначала с /start")
            
            await bot.answer_callback_query(call.id)
        
        # Обработка кнопки "Посмотреть награды"
        elif call.data == "view_rewards":
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
                
                keyboard = types.InlineKeyboardMarkup()
                keyboard.add(types.InlineKeyboardButton("◀️ Назад в меню", callback_data="back_to_menu"))
                
                await bot.edit_message_text(
                    text,
                    chat_id,
                    call.message.message_id,
                    parse_mode='Markdown',
                    reply_markup=keyboard
                )
            except Exception as e:
                logger.error(f"Ошибка при просмотре наград: {e}")
                await bot.send_message(chat_id, "Произошла ошибка. Пожалуйста, начните сначала с /start")
            
            await bot.answer_callback_query(call.id)
        
        # ... добавьте остальные обработчики callback-ов ...
        
        # Обработка кнопки "Назад в меню"
        elif call.data == "back_to_menu":
            # Получаем данные пользователя
            child = await get_child(user_id)
            
            text = (
                f"Привет, {child.name}! 👋 Это бот для записи твоих добрых дел.\n\n"
                f"У тебя сейчас *{child.total_points} баллов*.\n\n"
                "Выбери действие:"
            )
            
            # Редактируем сообщение с главным меню
            await bot.edit_message_text(
                text,
                chat_id,
                call.message.message_id,
                parse_mode='Markdown',
                reply_markup=get_main_menu_keyboard()
            )
            
            # Сбрасываем состояние
            await bot.delete_state(user_id, chat_id)
            
            await bot.answer_callback_query(call.id)
        
        # Обработка кнопки "Я родитель"
        elif call.data == "register_parent":
            # Если сообщение из группы
            if call.message.chat.type in ['group', 'supergroup']:
                await bot.send_message(
                    chat_id,
                    f"@{call.from_user.username}, для регистрации как родитель, пожалуйста, напишите боту в личные сообщения."
                )
            else:
                # Проверяем, зарегистрирован ли пользователь как родитель
                parent, is_parent = await verify_parent(user_id)
                
                if is_parent:
                    # Родитель существует, запрашиваем пароль
                    await bot.send_message(chat_id, f"Здравствуйте, {parent.name}! Для доступа к режиму родителя, пожалуйста, введите пароль:")
                    
                    # Устанавливаем состояние PARENT_PASSWORD
                    await bot.set_state(user_id, BotStates.PARENT_PASSWORD, chat_id)
                    async with bot.retrieve_data(user_id, chat_id) as data:
                        data['registering_parent'] = False
                else:
                    # Новый родитель, предлагаем зарегистрироваться
                    await bot.send_message(
                        chat_id,
                        "Вы еще не зарегистрированы как родитель. Хотите зарегистрироваться?\n\n"
                        "Введите пароль, который будет использоваться для входа в режим родителя:"
                    )
                    
                    # Устанавливаем состояние PARENT_PASSWORD
                    await bot.set_state(user_id, BotStates.PARENT_PASSWORD, chat_id)
                    async with bot.retrieve_data(user_id, chat_id) as data:
                        data['registering_parent'] = True
            
            await bot.answer_callback_query(call.id)
        
        # Обработка кнопки "Добавить ребенка"
        elif call.data == "add_child":
            await bot.send_message(
                chat_id,
                "👶 Введите имя ребенка, которого хотите добавить:"
            )
            
            # Устанавливаем состояние PARENT_ADD_CHILD
            await bot.set_state(user_id, BotStates.PARENT_ADD_CHILD, chat_id)
            
            await bot.answer_callback_query(call.id)
        
        # Обработка кнопки "Просмотр статистики детей"
        elif call.data == "view_children":
            try:
                parent = await get_parent(user_id)
                if parent:
                    children = await get_parent_children(parent)
                    
                    if not children:
                        keyboard = types.InlineKeyboardMarkup()
                        keyboard.add(types.InlineKeyboardButton("➕ Добавить ребенка", callback_data="add_child"))
                        keyboard.add(types.InlineKeyboardButton("🏠 В главное меню", callback_data="exit_parent_mode"))
                        
                        await bot.send_message(
                            chat_id,
                            "У вас пока нет добавленных детей. Добавьте ребенка, чтобы видеть его статистику.",
                            reply_markup=keyboard
                        )
                    else:
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
                        
                        keyboard = types.InlineKeyboardMarkup()
                        keyboard.add(types.InlineKeyboardButton("➕ Добавить доброе дело", callback_data="add_deed_to_child"))
                        keyboard.add(types.InlineKeyboardButton("◀️ Назад", callback_data="back_to_parent_menu"))
                        
                        await bot.send_message(
                            chat_id,
                            text,
                            parse_mode='Markdown',
                            reply_markup=keyboard
                        )
                else:
                    await bot.send_message(
                        chat_id,
                        "❌ Ошибка: родитель не найден. Пожалуйста, начните с /parent."
                    )
            except Exception as e:
                logger.error(f"Ошибка при просмотре статистики детей: {e}")
                await bot.send_message(
                    chat_id,
                    "❌ Произошла ошибка. Пожалуйста, попробуйте еще раз."
                )
            
            await bot.answer_callback_query(call.id)
        
        # Обработка кнопки "Добавить доброе дело ребенку"
        elif call.data == "add_deed_to_child":
            try:
                parent = await get_parent(user_id)
                if parent:
                    children = await get_parent_children(parent)
                    
                    if not children:
                        keyboard = types.InlineKeyboardMarkup()
                        keyboard.add(types.InlineKeyboardButton("➕ Добавить ребенка", callback_data="add_child"))
                        keyboard.add(types.InlineKeyboardButton("🏠 В главное меню", callback_data="exit_parent_mode"))
                        
                        await bot.send_message(
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
                        
                        await bot.send_message(
                            chat_id,
                            "Выберите ребенка, которому хотите добавить доброе дело:",
                            reply_markup=keyboard
                        )
                else:
                    await bot.send_message(
                        chat_id,
                        "❌ Ошибка: родитель не найден. Пожалуйста, начните с /parent."
                    )
            except Exception as e:
                logger.error(f"Ошибка при выборе ребенка: {e}")
                await bot.send_message(
                    chat_id,
                    "❌ Произошла ошибка. Пожалуйста, попробуйте еще раз."
                )
            
            await bot.answer_callback_query(call.id)
        
        # Обработка выбора ребенка (формат: select_child_TELEGRAM_ID)
        elif call.data.startswith("select_child_"):
            try:
                child_telegram_id = int(call.data.split("_")[-1])
                child = await get_child(child_telegram_id)
                
                # Сохраняем ID выбранного ребенка
                await bot.set_state(user_id, BotStates.PARENT_ADD_DEED, chat_id)
                async with bot.retrieve_data(user_id, chat_id) as data:
                    data['selected_child_id'] = child_telegram_id
                
                await bot.send_message(
                    chat_id,
                    f"Вы выбрали ребенка: *{child.name}*\n\n"
                    "Опишите доброе дело, которое совершил ребенок:",
                    parse_mode='Markdown'
                )
            except Exception as e:
                logger.error(f"Ошибка при выборе ребенка: {e}")
                await bot.send_message(
                    chat_id,
                    "❌ Произошла ошибка. Пожалуйста, попробуйте еще раз."
                )
            
            await bot.answer_callback_query(call.id)
        
        # Обработка кнопки "Назад" в меню родителя
        elif call.data == "back_to_parent_menu":
            try:
                parent = await get_parent(user_id)
                if parent:
                    children = await get_parent_children(parent)
                    
                    # Создаем клавиатуру для меню родителя
                    keyboard = types.InlineKeyboardMarkup()
                    if children:
                        keyboard.add(types.InlineKeyboardButton("➕ Добавить доброе дело ребенку", callback_data="add_deed_to_child"))
                        keyboard.add(types.InlineKeyboardButton("📊 Просмотр статистики детей", callback_data="view_children"))
                    
                    keyboard.add(types.InlineKeyboardButton("➕ Добавить ребенка", callback_data="add_child"))
                    keyboard.add(types.InlineKeyboardButton("🏠 В главное меню", callback_data="exit_parent_mode"))
                    
                    await bot.send_message(
                        chat_id,
                        f"👋 Здравствуйте, {parent.name}! Вы в режиме родителя.\n\n"
                        f"У вас {len(children)} {'детей' if len(children) != 1 else 'ребенок'} в системе.\n\n"
                        "Выберите действие:",
                        reply_markup=keyboard
                    )
                else:
                    await bot.send_message(
                        chat_id,
                        "❌ Ошибка: родитель не найден. Пожалуйста, начните с /parent."
                    )
            except Exception as e:
                logger.error(f"Ошибка при возврате в меню родителя: {e}")
                await bot.send_message(
                    chat_id,
                    "❌ Произошла ошибка. Пожалуйста, попробуйте еще раз."
                )
            
            await bot.answer_callback_query(call.id)
        
        # Обработка кнопки "В главное меню" из режима родителя
        elif call.data == "exit_parent_mode":
            await bot.send_message(
                chat_id,
                "Вы вышли из режима родителя. Используйте /start для начала работы с ботом."
            )
            
            # Сбрасываем состояние
            await bot.delete_state(user_id, chat_id)
            
            await bot.answer_callback_query(call.id)
        
        # Обработка кнопки "Помощь"
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
            
            await bot.edit_message_text(
                help_text,
                chat_id,
                call.message.message_id,
                parse_mode='Markdown',
                reply_markup=keyboard
            )
            
            await bot.answer_callback_query(call.id)
        
        # Если не распознали callback_data
        else:
            logger.warning(f"Неизвестный callback_data: {call.data}")
            await bot.answer_callback_query(call.id, "Неизвестная команда")
    
    except Exception as e:
        logger.error(f"Ошибка при обработке callback_query: {e}")
        await bot.answer_callback_query(call.id, "Произошла ошибка")

# Обработчик добавления ребенка родителем
@bot.message_handler(state=BotStates.PARENT_ADD_CHILD)
async def process_add_child(message):
    user_id = message.from_user.id
    chat_id = message.chat.id
    child_name = message.text.strip()
    
    try:
        parent = await get_parent(user_id)
        if parent:
            # Проверяем, существует ли ребенок с таким именем
            child = await get_child_by_name(child_name)
            
            if child:
                # Если ребенок найден, привязываем его к родителю
                await add_child_to_parent(parent, child)
                
                await bot.send_message(
                    chat_id,
                    f"✅ Ребенок *{child.name}* успешно добавлен!\n\n"
                    f"У него сейчас *{child.total_points} баллов*.\n\n"
                    "Используйте /parent для возврата в меню родителя.",
                    parse_mode='Markdown'
                )
            else:
                # Если ребенок не найден, предлагаем зарегистрировать его через бота
                await bot.send_message(
                    chat_id,
                    f"❓ Ребенок с именем '{child_name}' не найден в системе.\n\n"
                    "Попросите ребенка зарегистрироваться в боте с помощью команды /start, "
                    "а затем добавьте его снова.\n\n"
                    "Используйте /parent для возврата в меню родителя."
                )
            
            # Сбрасываем состояние
            await bot.delete_state(user_id, chat_id)
        else:
            await bot.send_message(
                chat_id,
                "❌ Ошибка: родитель не найден. Пожалуйста, начните с /parent."
            )
            await bot.delete_state(user_id, chat_id)
    except Exception as e:
        logger.error(f"Ошибка при добавлении ребенка: {e}")
        await bot.send_message(
            chat_id,
            "❌ Произошла ошибка. Пожалуйста, попробуйте еще раз или используйте /start для начала."
        )
        await bot.delete_state(user_id, chat_id)

# Обработчик добавления описания доброго дела от родителя
@bot.message_handler(state=BotStates.PARENT_ADD_DEED)
async def process_parent_deed_description(message):
    user_id = message.from_user.id
    chat_id = message.chat.id
    
    try:
        # Сохраняем описание дела
        async with bot.retrieve_data(user_id, chat_id) as data:
            data['deed_description'] = message.text
        
        await bot.send_message(
            chat_id,
            "👍 Отлично! Теперь укажите, сколько баллов получает ребенок за это дело:"
        )
        
        # Обновляем состояние
        await bot.set_state(user_id, BotStates.PARENT_ADD_POINTS, chat_id)
    except Exception as e:
        logger.error(f"Ошибка при добавлении описания дела: {e}")
        await bot.send_message(
            chat_id,
            "❌ Произошла ошибка. Пожалуйста, попробуйте еще раз или используйте /start для начала."
        )
        await bot.delete_state(user_id, chat_id)

# Обработчик добавления баллов от родителя
@bot.message_handler(state=BotStates.PARENT_ADD_POINTS)
async def process_parent_deed_points(message):
    user_id = message.from_user.id
    chat_id = message.chat.id
    
    try:
        points = int(message.text)
        if points <= 0:
            await bot.send_message(
                chat_id,
                "❌ Баллы должны быть положительным числом. Попробуйте еще раз:"
            )
            return
        
        # Получаем данные родителя и ребенка из сохраненного состояния
        parent = await get_parent(user_id)
        async with bot.retrieve_data(user_id, chat_id) as data:
            child_telegram_id = data.get('selected_child_id')
            deed_description = data.get('deed_description', 'Доброе дело')
        
        if not child_telegram_id:
            await bot.send_message(
                chat_id,
                "❌ Ошибка: не выбран ребенок. Пожалуйста, начните заново с /parent."
            )
            
            # Сбрасываем состояние
            await bot.delete_state(user_id, chat_id)
            return
        
        child = await get_child(child_telegram_id)
        
        # Создаем запись о добром деле
        deed = await create_deed(
            child,
            deed_description,
            points,
            parent
        )
        
        # Обновляем общее количество баллов
        total_points = await update_child_points(child, points)
        
        await bot.send_message(
            chat_id,
            f"🎉 Доброе дело для {child.name} успешно добавлено!\n\n"
            f"Доброе дело: *{deed_description}*\n"
            f"Баллы: *+{points}*\n"
            f"Всего у ребенка теперь *{total_points} баллов*.\n\n"
            "Используйте /parent для возврата в меню родителя.",
            parse_mode='Markdown'
        )
        
        # Сбрасываем состояние
        await bot.delete_state(user_id, chat_id)
        
    except ValueError:
        await bot.send_message(
            chat_id,
            "❌ Пожалуйста, введите число. Попробуйте еще раз:"
        )
    except Exception as e:
        logger.error(f"Ошибка при добавлении баллов от родителя: {e}")
        await bot.send_message(
            chat_id,
            "❌ Произошла ошибка. Пожалуйста, попробуйте еще раз или используйте /start для начала."
        )
        await bot.delete_state(user_id, chat_id)

# Обработчик команды /cancel
@bot.message_handler(commands=['cancel'])
async def cancel_command(message):
    user_id = message.from_user.id
    chat_id = message.chat.id
    
    # Сбрасываем состояние
    await bot.delete_state(user_id, chat_id)
    
    await bot.send_message(
        chat_id,
        "❌ Действие отменено. Используйте /start для возврата в главное меню."
    )

# Функция для обработки вебхука
async def process_telegram_update(json_data):
    """Обрабатывает JSON-данные от Telegram webhook"""
    from telebot.types import Update
    update = Update.de_json(json_data)
    await bot.process_new_updates([update])