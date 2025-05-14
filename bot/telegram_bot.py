import logging
import os
import django
import hashlib
from dotenv import load_dotenv
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, BotCommand
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    ConversationHandler,
    filters,
)
from asgiref.sync import sync_to_async

# Загрузка переменных окружения
load_dotenv()

# Конфигурация Django
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "kindness_bot.settings")
django.setup()

from bot.models import Child, KindDeed, Reward, Parent

# Состояния для ConversationHandler
CHOOSING_ACTION, ADDING_DEED, ADDING_POINTS = range(3)
PARENT_AUTH, PARENT_PASSWORD, PARENT_MENU, PARENT_SELECT_CHILD = range(3, 7)
PARENT_ADD_DEED, PARENT_ADD_POINTS = range(7, 9)
GROUP_ADD_DEED, GROUP_ADD_POINTS, GROUP_CONFIRM = range(9, 12)

# Настройка логгирования
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)

# Функции для работы с БД в асинхронном режиме
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
def set_parent_password(parent, password):
    # Простое хеширование пароля (в реальном проекте нужно использовать более надежные методы)
    hashed_password = hashlib.sha256(password.encode()).hexdigest()
    parent.password = hashed_password
    parent.save()
    return parent

@sync_to_async
def verify_parent_password(parent, password):
    hashed_password = hashlib.sha256(password.encode()).hexdigest()
    return parent.password == hashed_password

@sync_to_async
def get_parent_children(parent):
    return list(parent.children.all())

@sync_to_async
def add_child_to_parent(parent, child):
    parent.children.add(child)
    return True

@sync_to_async
def get_child_by_name(name):
    try:
        return Child.objects.get(name=name)
    except Child.DoesNotExist:
        return None
    except Child.MultipleObjectsReturned:
        # Если несколько детей с одинаковым именем, берём первого
        return Child.objects.filter(name=name).first()
    
@sync_to_async
def get_all_children():
    return list(Child.objects.all())

@sync_to_async
def is_parent_of_child(parent, child):
    return parent.children.filter(telegram_id=child.telegram_id).exists()

@sync_to_async
def verify_parent(telegram_id):
    try:
        return Parent.objects.get(telegram_id=telegram_id), True
    except Parent.DoesNotExist:
        return None, False

# --- Функции для работы с ботом в группе ---

async def group_message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обработчик сообщений в группе"""
    # Проверяем, что сообщение отправлено в группе
    if not update.effective_chat.type in ['group', 'supergroup']:
        return
    
    message = update.message.text
    
    # Шаблон для команды добавления доброго дела в группе
    # Формат: "Доброе дело: [имя ребенка] [описание дела] [баллы]"
    # Пример: "Доброе дело: Маша помогла с уборкой на кухне 50"
    deed_pattern = re.compile(r'доброе дело:?\s+([^\d]+)\s+(.+)\s+(\d+)$', re.IGNORECASE)
    match = deed_pattern.match(message)
    
    if match:
        child_name, deed_description, points_str = match.groups()
        child_name = child_name.strip()
        deed_description = deed_description.strip()
        
        try:
            points = int(points_str)
            if points <= 0:
                await update.message.reply_text(
                    "❌ Баллы должны быть положительным числом."
                )
                return
            
            # Проверяем, является ли отправитель родителем
            sender_id = update.effective_user.id
            parent, is_parent = await verify_parent(sender_id)
            
            if not is_parent:
                await update.message.reply_text(
                    "❌ Только зарегистрированные родители могут добавлять добрые дела в группе.\n"
                    "Используйте команду /parent в личном чате с ботом, чтобы зарегистрироваться."
                )
                return
            
            # Находим ребенка по имени
            child = await get_child_by_name(child_name)
            
            if not child:
                await update.message.reply_text(
                    f"❌ Ребенок с именем '{child_name}' не найден.\n"
                    "Ребенок должен сначала зарегистрироваться в боте с помощью команды /start в личном чате."
                )
                return
            
            # Проверяем, привязан ли ребенок к родителю
            is_child_of_parent = await is_parent_of_child(parent, child)
            
            if not is_child_of_parent:
                await update.message.reply_text(
                    f"❌ Ребенок '{child_name}' не привязан к вашему аккаунту.\n"
                    "Добавьте ребенка через команду /parent в личном чате с ботом."
                )
                return
            
            # Создаем запись о добром деле
            deed = await create_deed(
                child,
                deed_description,
                points,
                parent
            )
            
            # Обновляем общее количество баллов
            total_points = await update_child_points(child, points)
            
            await update.message.reply_text(
                f"🎉 Доброе дело для {child.name} успешно добавлено!\n\n"
                f"Доброе дело: *{deed_description}*\n"
                f"Баллы: *+{points}*\n"
                f"Всего у {child.name} теперь *{total_points} баллов*.",
                parse_mode='Markdown'
            )
            
        except ValueError:
            await update.message.reply_text(
                "❌ Ошибка в формате баллов. Баллы должны быть целым числом."
            )
        except Exception as e:
            logger.error(f"Ошибка при добавлении доброго дела в группе: {e}")
            await update.message.reply_text(
                "❌ Произошла ошибка при добавлении доброго дела."
            )
    
    # Шаблон для проверки баллов в группе
    # Формат: "Баллы [имя ребенка]"
    # Пример: "Баллы Маша"
    points_pattern = re.compile(r'баллы\s+(.+)$', re.IGNORECASE)
    match = points_pattern.match(message)
    
    if match:
        child_name = match.group(1).strip()
        
        try:
            # Находим ребенка по имени
            child = await get_child_by_name(child_name)
            
            if not child:
                await update.message.reply_text(
                    f"❌ Ребенок с именем '{child_name}' не найден."
                )
                return
            
            # Получаем последние добрые дела
            recent_deeds = await get_recent_deeds(child)
            
            text = f"🌟 У {child.name} сейчас *{child.total_points} баллов*! 🌟\n\n"
            if recent_deeds:
                text += "📋 *Последние добрые дела:*\n"
                for deed in recent_deeds:
                    date_str = deed.created_at.strftime("%d.%m.%Y")
                    text += f"• {deed.description}: *{deed.points} баллов* ({date_str})\n"
            
            await update.message.reply_text(text, parse_mode='Markdown')
            
        except Exception as e:
            logger.error(f"Ошибка при проверке баллов в группе: {e}")
            await update.message.reply_text(
                "❌ Произошла ошибка при проверке баллов."
            )
    
    # Шаблон для просмотра наград в группе
    # Формат: "Награды"
    rewards_pattern = re.compile(r'награды$', re.IGNORECASE)
    match = rewards_pattern.match(message)
    
    if match:
        try:
            rewards = await get_rewards()
            
            if not rewards:
                text = "Пока в базе нет доступных наград. Но дети могут копить на:\n\n"
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
            
            await update.message.reply_text(text, parse_mode='Markdown')
            
        except Exception as e:
            logger.error(f"Ошибка при просмотре наград в группе: {e}")
            await update.message.reply_text(
                "❌ Произошла ошибка при просмотре наград."
            )

async def group_help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Показывает справку по использованию бота в группе"""
    # Проверяем, что команда отправлена в группе
    if not update.effective_chat.type in ['group', 'supergroup']:
        return
    
    help_text = (
        "🌈 *Бот Добрых Дел в группе* 🌈\n\n"
        "Родители могут добавлять добрые дела детям прямо в этой группе!\n\n"
        "*Как использовать бота в группе:*\n\n"
        "1️⃣ *Добавление доброго дела:*\n"
        "Напишите: `Доброе дело: [имя ребенка] [описание] [баллы]`\n"
        "Пример: `Доброе дело: Маша помогла с уборкой 50`\n\n"
        "2️⃣ *Проверка баллов:*\n"
        "Напишите: `Баллы [имя ребенка]`\n"
        "Пример: `Баллы Маша`\n\n"
        "3️⃣ *Просмотр доступных наград:*\n"
        "Напишите: `Награды`\n\n"
        "*Важно:*\n"
        "• Добавлять добрые дела в группе могут только зарегистрированные родители\n"
        "• Ребенок должен быть предварительно зарегистрирован через личный чат с ботом\n"
        "• Ребенок должен быть привязан к аккаунту родителя\n\n"
        "Для регистрации и настройки используйте личный чат с ботом."
    )
    
    await update.message.reply_text(help_text, parse_mode='Markdown')

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Начальная точка взаимодействия с ботом"""
    user = update.effective_user
    telegram_id = user.id
    
    # Проверяем, зарегистрирован ли пользователь как родитель
    parent = None
    try:
        parent = await get_parent(telegram_id)
        # Если пользователь - родитель, предлагаем меню родителя
        keyboard = [
            [InlineKeyboardButton("👨‍👧‍👦 Войти как родитель", callback_data="parent_login")],
            [InlineKeyboardButton("👶 Войти как ребенок", callback_data="child_login")],
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await update.message.reply_text(
            f"Привет, {user.first_name}! Вы зарегистрированы как родитель.\n\n"
            "Выберите режим входа:",
            reply_markup=reply_markup
        )
        return PARENT_AUTH
    except Exception:
        # Если не родитель, проверяем как ребенка
        pass
    
    # Проверяем, зарегистрирован ли ребенок
    try:
        child, created = await get_or_create_child(telegram_id, user.first_name)
        
        keyboard = [
            [InlineKeyboardButton("📝 Добавить доброе дело", callback_data="add_deed")],
            [InlineKeyboardButton("🌟 Мои баллы", callback_data="check_points")],
            [InlineKeyboardButton("🎁 Посмотреть награды", callback_data="view_rewards")],
            [InlineKeyboardButton("❓ Помощь", callback_data="help")],
            [InlineKeyboardButton("👨‍👩‍👧‍👦 Я родитель", callback_data="register_parent")],
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await update.message.reply_text(
            f"Привет, {child.name}! 👋 Это бот для записи твоих добрых дел.\n\n"
            f"У тебя сейчас *{child.total_points} баллов*.\n\n"
            "Выбери действие:",
            reply_markup=reply_markup,
            parse_mode='Markdown'
        )
        
        return CHOOSING_ACTION
    except Exception as e:
        logger.error(f"Ошибка при старте: {e}")
        await update.message.reply_text("Произошла ошибка. Пожалуйста, попробуйте еще раз.")
        return ConversationHandler.END

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Показывает справку по использованию бота"""
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
    
    await update.message.reply_text(
        help_text,
        parse_mode='Markdown'
    )

# --- Функции режима ребенка ---

async def add_deed_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Команда для добавления доброго дела"""
    await update.message.reply_text("Опиши свое доброе дело:")
    return ADDING_DEED

async def check_points_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Команда для проверки баллов"""
    telegram_id = update.effective_user.id
    try:
        child = await get_child(telegram_id)
        recent_deeds = await get_recent_deeds(child)
        
        text = f"🌟 У тебя сейчас *{child.total_points} баллов*! 🌟\n\n"
        if recent_deeds:
            text += "📋 *Твои последние добрые дела:*\n"
            for deed in recent_deeds:
                date_str = deed.created_at.strftime("%d.%m.%Y")
                text += f"• {deed.description}: *{deed.points} баллов* ({date_str})\n"
        
        await update.message.reply_text(text, parse_mode='Markdown')
    except Exception as e:
        logger.error(f"Ошибка при получении баллов: {e}")
        await update.message.reply_text("Произошла ошибка. Начни заново: /start")

async def view_rewards_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Команда для просмотра наград"""
    rewards = await get_rewards()
    
    if not rewards:
        text = "Пока нет доступных наград. Попроси взрослых добавить их.\n\n"
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
    
    await update.message.reply_text(text, parse_mode='Markdown')

async def process_deed(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Обработка описания доброго дела"""
    # Сохраняем описание дела
    context.user_data["deed_description"] = update.message.text
    
    await update.message.reply_text(
        "👍 Отлично! Теперь укажи, сколько баллов ты получил за это дело:"
    )
    
    return ADDING_POINTS

async def process_points(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Обработка количества баллов"""
    try:
        points = int(update.message.text)
        if points <= 0:
            await update.message.reply_text(
                "❌ Баллы должны быть положительным числом. Попробуй еще раз:"
            )
            return ADDING_POINTS
        
        # Получаем данные пользователя
        telegram_id = update.effective_user.id
        child = await get_child(telegram_id)
        
        # Создаем запись о добром деле
        deed = await create_deed(
            child,
            context.user_data["deed_description"],
            points
        )
        
        # Обновляем общее количество баллов
        total_points = await update_child_points(child, points)
        
        # Очищаем данные
        context.user_data.clear()
        
        keyboard = [
            [InlineKeyboardButton("📝 Добавить еще доброе дело", callback_data="add_deed")],
            [InlineKeyboardButton("🏠 Вернуться в меню", callback_data="back_to_menu")],
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await update.message.reply_text(
            f"🎉 Отлично! Доброе дело '{deed.description}' добавлено.\n\n"
            f"Ты получил *{deed.points} баллов*!\n"
            f"Всего у тебя теперь *{total_points} баллов*.",
            reply_markup=reply_markup,
            parse_mode='Markdown'
        )
        
        return CHOOSING_ACTION
    
    except ValueError:
        await update.message.reply_text(
            "❌ Пожалуйста, введи число. Попробуй еще раз:"
        )
        return ADDING_POINTS
    except Exception as e:
        logger.error(f"Ошибка при добавлении баллов: {e}")
        await update.message.reply_text(
            "❌ Произошла ошибка. Начни заново: /start"
        )
        return ConversationHandler.END

# --- Функции режима родителя ---

async def parent_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Команда для входа в режим родителя"""
    user = update.effective_user
    telegram_id = user.id
    
    # Проверяем, зарегистрирован ли пользователь как родитель
    try:
        parent = await get_parent(telegram_id)
        # Запрашиваем пароль
        await update.message.reply_text(
            f"Здравствуйте, {parent.name}! Для доступа к режиму родителя, пожалуйста, введите пароль:"
        )
        return PARENT_PASSWORD
    except Exception:
        # Если не зарегистрирован как родитель, предлагаем регистрацию
        await update.message.reply_text(
            "Вы еще не зарегистрированы как родитель. Хотите зарегистрироваться?\n\n"
            "Введите пароль, который будет использоваться для входа в режим родителя:"
        )
        context.user_data["registering_parent"] = True
        return PARENT_PASSWORD

async def handle_parent_auth(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Обработка выбора режима входа"""
    query = update.callback_query
    await query.answer()
    
    if query.data == "parent_login":
        await query.edit_message_text(
            "Пожалуйста, введите пароль для входа в режим родителя:"
        )
        return PARENT_PASSWORD
    
    elif query.data == "child_login":
        # Входим как ребенок
        user = update.effective_user
        telegram_id = user.id
        
        try:
            # Проверяем, есть ли у этого телеграм ID зарегистрированный ребенок
            child = await get_child(telegram_id)
            
            keyboard = [
                [InlineKeyboardButton("📝 Добавить доброе дело", callback_data="add_deed")],
                [InlineKeyboardButton("🌟 Мои баллы", callback_data="check_points")],
                [InlineKeyboardButton("🎁 Посмотреть награды", callback_data="view_rewards")],
                [InlineKeyboardButton("❓ Помощь", callback_data="help")],
                [InlineKeyboardButton("👨‍👩‍👧‍👦 Я родитель", callback_data="register_parent")],
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await query.edit_message_text(
                f"Привет, {child.name}! 👋 Это бот для записи твоих добрых дел.\n\n"
                f"У тебя сейчас *{child.total_points} баллов*.\n\n"
                "Выбери действие:",
                reply_markup=reply_markup,
                parse_mode='Markdown'
            )
            
            return CHOOSING_ACTION
        except Exception:
            # Если ребенок не зарегистрирован, создаем его
            child, created = await get_or_create_child(telegram_id, user.first_name)
            
            keyboard = [
                [InlineKeyboardButton("📝 Добавить доброе дело", callback_data="add_deed")],
                [InlineKeyboardButton("🌟 Мои баллы", callback_data="check_points")],
                [InlineKeyboardButton("🎁 Посмотреть награды", callback_data="view_rewards")],
                [InlineKeyboardButton("❓ Помощь", callback_data="help")],
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await query.edit_message_text(
                f"Привет, {child.name}! 👋 Это бот для записи твоих добрых дел.\n\n"
                f"У тебя сейчас *{child.total_points} баллов*.\n\n"
                "Выбери действие:",
                reply_markup=reply_markup,
                parse_mode='Markdown'
            )
            
            return CHOOSING_ACTION
    
    return PARENT_AUTH

async def handle_parent_password(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Обработка ввода пароля родителя"""
    user = update.effective_user
    telegram_id = user.id
    password = update.message.text
    
    # Если это регистрация нового родителя
    if context.user_data.get("registering_parent"):
        parent, created = await get_or_create_parent(telegram_id, user.first_name)
        await set_parent_password(parent, password)
        
        # Очищаем флаг регистрации
        context.user_data.pop("registering_parent", None)
        
        keyboard = [
            [InlineKeyboardButton("➕ Добавить ребенка", callback_data="add_child")],
            [InlineKeyboardButton("📊 Просмотр статистики детей", callback_data="view_children")],
            [InlineKeyboardButton("🏠 В главное меню", callback_data="exit_parent_mode")],
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await update.message.reply_text(
            f"🎉 Поздравляем! Вы зарегистрированы как родитель.\n\n"
            "Теперь вы можете добавлять добрые дела вашим детям и следить за их прогрессом.",
            reply_markup=reply_markup
        )
        return PARENT_MENU
    
    # Если это вход существующего родителя
    try:
        parent = await get_parent(telegram_id)
        is_valid = await verify_parent_password(parent, password)
        
        if is_valid:
            # Пароль верный, показываем меню родителя
            children = await get_parent_children(parent)
            
            keyboard = []
            if children:
                keyboard.append([InlineKeyboardButton("➕ Добавить доброе дело ребенку", callback_data="add_deed_to_child")])
                keyboard.append([InlineKeyboardButton("📊 Просмотр статистики детей", callback_data="view_children")])
            
            keyboard.append([InlineKeyboardButton("➕ Добавить ребенка", callback_data="add_child")])
            keyboard.append([InlineKeyboardButton("🏠 В главное меню", callback_data="exit_parent_mode")])
            
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await update.message.reply_text(
                f"👋 Здравствуйте, {parent.name}! Вы вошли в режим родителя.\n\n"
                f"У вас {len(children)} {'детей' if len(children) != 1 else 'ребенок'} в системе.\n\n"
                "Выберите действие:",
                reply_markup=reply_markup
            )
            return PARENT_MENU
        else:
            # Пароль неверный
            await update.message.reply_text(
                "❌ Неверный пароль. Пожалуйста, попробуйте еще раз или введите /cancel для отмены."
            )
            return PARENT_PASSWORD
    
    except Exception as e:
        logger.error(f"Ошибка при проверке пароля родителя: {e}")
        await update.message.reply_text(
            "❌ Произошла ошибка. Пожалуйста, попробуйте еще раз или введите /start для начала."
        )
        return ConversationHandler.END

async def handle_parent_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Обработка меню родителя"""
    query = update.callback_query
    await query.answer()
    
    user = update.effective_user
    telegram_id = user.id
    
    if query.data == "add_child":
        # Переходим к добавлению ребенка
        await query.edit_message_text(
            "👶 Введите имя ребенка, которого хотите добавить:"
        )
        return PARENT_SELECT_CHILD
    
    elif query.data == "view_children":
        # Показываем статистику детей
        try:
            parent = await get_parent(telegram_id)
            children = await get_parent_children(parent)
            
            if not children:
                keyboard = [
                    [InlineKeyboardButton("➕ Добавить ребенка", callback_data="add_child")],
                    [InlineKeyboardButton("🏠 В главное меню", callback_data="exit_parent_mode")],
                ]
                reply_markup = InlineKeyboardMarkup(keyboard)
                
                await query.edit_message_text(
                    "У вас пока нет добавленных детей. Добавьте ребенка, чтобы видеть его статистику.",
                    reply_markup=reply_markup
                )
                return PARENT_MENU
            
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
            
            keyboard = [
                [InlineKeyboardButton("➕ Добавить доброе дело", callback_data="add_deed_to_child")],
                [InlineKeyboardButton("◀️ Назад", callback_data="back_to_parent_menu")],
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await query.edit_message_text(
                text,
                reply_markup=reply_markup,
                parse_mode='Markdown'
            )
            return PARENT_MENU
            
        except Exception as e:
            logger.error(f"Ошибка при просмотре статистики детей: {e}")
            await query.edit_message_text(
                "❌ Произошла ошибка. Пожалуйста, попробуйте еще раз."
            )
            return PARENT_MENU
    
    elif query.data == "add_deed_to_child":
        # Выбираем ребенка для добавления доброго дела
        try:
            parent = await get_parent(telegram_id)
            children = await get_parent_children(parent)
            
            if not children:
                keyboard = [
                    [InlineKeyboardButton("➕ Добавить ребенка", callback_data="add_child")],
                    [InlineKeyboardButton("🏠 В главное меню", callback_data="exit_parent_mode")],
                ]
                reply_markup = InlineKeyboardMarkup(keyboard)
                
                await query.edit_message_text(
                    "У вас пока нет добавленных детей. Добавьте ребенка, чтобы добавлять ему добрые дела.",
                    reply_markup=reply_markup
                )
                return PARENT_MENU
            
            # Создаем кнопки для выбора ребенка
            keyboard = []
            for child in children:
                keyboard.append([InlineKeyboardButton(f"👶 {child.name}", callback_data=f"select_child_{child.telegram_id}")])
            
            keyboard.append([InlineKeyboardButton("◀️ Назад", callback_data="back_to_parent_menu")])
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await query.edit_message_text(
                "Выберите ребенка, которому хотите добавить доброе дело:",
                reply_markup=reply_markup
            )
            return PARENT_SELECT_CHILD
            
        except Exception as e:
            logger.error(f"Ошибка при выборе ребенка: {e}")
            await query.edit_message_text(
                "❌ Произошла ошибка. Пожалуйста, попробуйте еще раз."
            )
            return PARENT_MENU
    
    elif query.data == "back_to_parent_menu":
        # Возвращаемся в основное меню родителя
        try:
            parent = await get_parent(telegram_id)
            children = await get_parent_children(parent)
            
            keyboard = []
            if children:
                keyboard.append([InlineKeyboardButton("➕ Добавить доброе дело ребенку", callback_data="add_deed_to_child")])
                keyboard.append([InlineKeyboardButton("📊 Просмотр статистики детей", callback_data="view_children")])
            
            keyboard.append([InlineKeyboardButton("➕ Добавить ребенка", callback_data="add_child")])
            keyboard.append([InlineKeyboardButton("🏠 В главное меню", callback_data="exit_parent_mode")])
            
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await query.edit_message_text(
                f"👋 Здравствуйте, {parent.name}! Вы в режиме родителя.\n\n"
                f"У вас {len(children)} {'детей' if len(children) != 1 else 'ребенок'} в системе.\n\n"
                "Выберите действие:",
                reply_markup=reply_markup
            )
            return PARENT_MENU
            
        except Exception as e:
            logger.error(f"Ошибка при возврате в меню родителя: {e}")
            await query.edit_message_text(
                "❌ Произошла ошибка. Пожалуйста, попробуйте еще раз."
            )
            return PARENT_MENU
    
    elif query.data == "exit_parent_mode":
        # Выходим из режима родителя в главное меню
        await query.edit_message_text(
            "Вы вышли из режима родителя. Используйте /start для начала работы с ботом."
        )
        return ConversationHandler.END
    
    # Если пришел запрос на выбор ребенка (формат: select_child_TELEGRAM_ID)
    elif query.data.startswith("select_child_"):
        try:
            child_telegram_id = int(query.data.split("_")[-1])
            child = await get_child(child_telegram_id)
            
            # Сохраняем ID выбранного ребенка в контексте
            context.user_data["selected_child_id"] = child_telegram_id
            
            await query.edit_message_text(
                f"Вы выбрали ребенка: *{child.name}*\n\n"
                "Опишите доброе дело, которое совершил ребенок:",
                parse_mode='Markdown'
            )
            return PARENT_ADD_DEED
            
        except Exception as e:
            logger.error(f"Ошибка при выборе ребенка: {e}")
            await query.edit_message_text(
                "❌ Произошла ошибка. Пожалуйста, попробуйте еще раз."
            )
            return PARENT_MENU
    
    return PARENT_MENU

async def handle_adding_child(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Обработка добавления ребенка к родителю"""
    user = update.effective_user
    telegram_id = user.id
    
    # Получаем имя ребенка из сообщения
    child_name = update.message.text.strip()
    
    try:
        parent = await get_parent(telegram_id)
        
        # Проверяем, существует ли ребенок с таким именем
        child = await get_child_by_name(child_name)
        
        if child:
            # Если ребенок найден, привязываем его к родителю
            await add_child_to_parent(parent, child)
            
            await update.message.reply_text(
                f"✅ Ребенок *{child.name}* успешно добавлен!\n\n"
                f"У него сейчас *{child.total_points} баллов*.\n\n"
                "Используйте /parent для возврата в меню родителя.",
                parse_mode='Markdown'
            )
        else:
            # Если ребенок не найден, предлагаем зарегистрировать его через бота
            await update.message.reply_text(
                f"❓ Ребенок с именем '{child_name}' не найден в системе.\n\n"
                "Попросите ребенка зарегистрироваться в боте с помощью команды /start, "
                "а затем добавьте его снова.\n\n"
                "Используйте /parent для возврата в меню родителя."
            )
        
        return ConversationHandler.END
            
    except Exception as e:
        logger.error(f"Ошибка при добавлении ребенка: {e}")
        await update.message.reply_text(
            "❌ Произошла ошибка. Пожалуйста, попробуйте еще раз или используйте /start для начала."
        )
        return ConversationHandler.END

async def handle_parent_deed_description(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Обработка описания доброго дела от родителя"""
    # Сохраняем описание дела
    context.user_data["deed_description"] = update.message.text
    
    await update.message.reply_text(
        "👍 Отлично! Теперь укажите, сколько баллов получает ребенок за это дело:"
    )
    
    return PARENT_ADD_POINTS

async def handle_parent_deed_points(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Обработка количества баллов от родителя"""
    user = update.effective_user
    telegram_id = user.id
    
    try:
        points = int(update.message.text)
        if points <= 0:
            await update.message.reply_text(
                "❌ Баллы должны быть положительным числом. Попробуйте еще раз:"
            )
            return PARENT_ADD_POINTS
        
        # Получаем данные родителя и ребенка
        parent = await get_parent(telegram_id)
        child_telegram_id = context.user_data.get("selected_child_id")
        
        if not child_telegram_id:
            await update.message.reply_text(
                "❌ Ошибка: не выбран ребенок. Пожалуйста, начните заново с /parent."
            )
            return ConversationHandler.END
        
        child = await get_child(child_telegram_id)
        
        # Создаем запись о добром деле
        deed = await create_deed(
            child,
            context.user_data["deed_description"],
            points,
            parent
        )
        
        # Обновляем общее количество баллов
        total_points = await update_child_points(child, points)
        
        # Очищаем данные
        context.user_data.clear()
        
        await update.message.reply_text(
            f"🎉 Доброе дело для {child.name} успешно добавлено!\n\n"
            f"Доброе дело: *{deed.description}*\n"
            f"Баллы: *+{deed.points}*\n"
            f"Всего у ребенка теперь *{total_points} баллов*.\n\n"
            "Используйте /parent для возврата в меню родителя.",
            parse_mode='Markdown'
        )
        
        return ConversationHandler.END
    
    except ValueError:
        await update.message.reply_text(
            "❌ Пожалуйста, введите число. Попробуйте еще раз:"
        )
        return PARENT_ADD_POINTS
    except Exception as e:
        logger.error(f"Ошибка при добавлении баллов от родителя: {e}")
        await update.message.reply_text(
            "❌ Произошла ошибка. Пожалуйста, начните заново с /parent."
        )
        return ConversationHandler.END

# --- Общие функции ---

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Обработчик нажатий на кнопки"""
    query = update.callback_query
    await query.answer()
    
    if query.data == "add_deed":
        await query.edit_message_text("📝 Опиши свое доброе дело:")
        return ADDING_DEED
    
    elif query.data == "check_points":
        telegram_id = update.effective_user.id
        try:
            child = await get_child(telegram_id)
            recent_deeds = await get_recent_deeds(child)
            
            text = f"🌟 У тебя сейчас *{child.total_points} баллов*! 🌟\n\n"
            if recent_deeds:
                text += "📋 *Твои последние добрые дела:*\n"
                for deed in recent_deeds:
                    date_str = deed.created_at.strftime("%d.%m.%Y")
                    text += f"• {deed.description}: *{deed.points} баллов* ({date_str})\n"
            
            keyboard = [[InlineKeyboardButton("◀️ Назад в меню", callback_data="back_to_menu")]]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await query.edit_message_text(text, reply_markup=reply_markup, parse_mode='Markdown')
        except Exception as e:
            logger.error(f"Ошибка при получении баллов: {e}")
            await query.edit_message_text("Произошла ошибка. Начни заново: /start")
        
        return CHOOSING_ACTION
    
    elif query.data == "view_rewards":
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
        
        keyboard = [[InlineKeyboardButton("◀️ Назад в меню", callback_data="back_to_menu")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.edit_message_text(text, reply_markup=reply_markup, parse_mode='Markdown')
        return CHOOSING_ACTION
    
    elif query.data == "help":
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
        
        keyboard = [[InlineKeyboardButton("◀️ Назад в меню", callback_data="back_to_menu")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.edit_message_text(help_text, reply_markup=reply_markup, parse_mode='Markdown')
        return CHOOSING_ACTION
    
    elif query.data == "register_parent":
        # Переходим к регистрации родителя
        await query.edit_message_text(
            "Вы хотите зарегистрироваться как родитель?\n\n"
            "Введите пароль, который будет использоваться для входа в режим родителя:"
        )
        context.user_data["registering_parent"] = True
        return PARENT_PASSWORD
    
    elif query.data == "back_to_menu":
        # Возвращаемся в главное меню через новый вызов start
        user = update.effective_user
        telegram_id = user.id
        
        try:
            child = await get_child(telegram_id)
            
            keyboard = [
                [InlineKeyboardButton("📝 Добавить доброе дело", callback_data="add_deed")],
                [InlineKeyboardButton("🌟 Мои баллы", callback_data="check_points")],
                [InlineKeyboardButton("🎁 Посмотреть награды", callback_data="view_rewards")],
                [InlineKeyboardButton("❓ Помощь", callback_data="help")],
                [InlineKeyboardButton("👨‍👩‍👧‍👦 Я родитель", callback_data="register_parent")],
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await query.edit_message_text(
                f"Привет, {child.name}! 👋 Это бот для записи твоих добрых дел.\n\n"
                f"У тебя сейчас *{child.total_points} баллов*.\n\n"
                "Выбери действие:",
                reply_markup=reply_markup,
                parse_mode='Markdown'
            )
        except Exception as e:
            logger.error(f"Ошибка при возврате в меню: {e}")
            await query.edit_message_text("Произошла ошибка. Начни заново: /start")
        
        return CHOOSING_ACTION
    
    return CHOOSING_ACTION

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Отмена текущего действия"""
    context.user_data.clear()
    await update.message.reply_text("❌ Действие отменено. Начни заново: /start")
    return ConversationHandler.END

async def setup_commands(application: Application) -> None:
    """Устанавливает команды бота в меню Telegram"""
    commands = [
        BotCommand("start", "Запустить бота и показать главное меню"),
        BotCommand("add", "Добавить новое доброе дело"),
        BotCommand("points", "Посмотреть мои баллы"),
        BotCommand("rewards", "Посмотреть список доступных наград"),
        BotCommand("parent", "Режим родителя"),
        BotCommand("help", "Показать справку по использованию бота"),
    ]
    await application.bot.set_my_commands(commands)

def main(token=None) -> None:
    """Запуск бота"""
    # Получаем токен из параметра или из переменных окружения
    if not token:
        token = os.environ.get("TELEGRAM_TOKEN")
    
    if not token:
        logger.error("Токен Telegram не найден в переменных окружения или параметрах.")
        return
    
    application = Application.builder().token(token).build()
    
    # Настройка команд в меню
    application.post_init = setup_commands
    
    # Настройка обработчика разговора
    conv_handler = ConversationHandler(
        entry_points=[
            CommandHandler("start", start),
            CommandHandler("add", add_deed_command),
            CommandHandler("parent", parent_command),
        ],
        states={
            CHOOSING_ACTION: [
                CallbackQueryHandler(button_handler),
            ],
            ADDING_DEED: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, process_deed),
            ],
            ADDING_POINTS: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, process_points),
            ],
            PARENT_AUTH: [
                CallbackQueryHandler(handle_parent_auth),
            ],
            PARENT_PASSWORD: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_parent_password),
            ],
            PARENT_MENU: [
                CallbackQueryHandler(handle_parent_menu),
            ],
            PARENT_SELECT_CHILD: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_adding_child),
                CallbackQueryHandler(handle_parent_menu),
            ],
            PARENT_ADD_DEED: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_parent_deed_description),
            ],
            PARENT_ADD_POINTS: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_parent_deed_points),
            ],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
        per_message=False
    )
    
    # Добавление обработчиков команд
    application.add_handler(conv_handler)
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("points", check_points_command))
    application.add_handler(CommandHandler("rewards", view_rewards_command))
    # Добавляем обработчики для работы в группе
    application.add_handler(CommandHandler("grouphelp", group_help_command))
    
 # Обработчик сообщений в группе - должен быть последним, чтобы не перехватывать другие команды
    application.add_handler(MessageHandler(
        filters.ChatType.GROUPS & filters.TEXT & ~filters.COMMAND,
        group_message_handler
    ))
    
    logger.info("Бот запущен!")
    
    # Запуск бота
    application.run_polling()

if __name__ == "__main__":
    main()