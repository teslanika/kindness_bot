from bot.models import Child, KindDeed, Reward, Parent
from flask import Flask, request, jsonify
import os
import django
import logging
import json
import re
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

# Импорт необходимых модулей из проекта

# Создаем Flask-приложение
app = Flask(__name__)

# Телеграм токен из переменных окружения
TOKEN = os.environ.get('TELEGRAM_TOKEN')
if not TOKEN:
    logger.error("Токен Telegram не найден в переменных окружения.")

# Хранилище состояний пользователей
user_states = {}
user_contexts = {}
group_states = {}
group_contexts = {}

# Состояния диалога


class States:
    IDLE = 0
    WAITING_DEED = 1
    WAITING_POINTS = 2
    PARENT_PASSWORD = 3
    PARENT_MENU = 4
    PARENT_ADD_CHILD = 5
    PARENT_ADD_DEED = 6
    PARENT_ADD_POINTS = 7

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
    import hashlib
    hashed_password = hashlib.sha256(password.encode()).hexdigest()
    parent.password = hashed_password
    parent.save()
    return parent


@sync_to_async
def verify_parent_password(parent, password):
    import hashlib
    hashed_password = hashlib.sha256(password.encode()).hexdigest()
    return parent.password == hashed_password


@sync_to_async
def get_parent_children(parent):
    return list(parent.children.all())


@sync_to_async
def add_child_to_parent(parent, child):
    parent.children.add(child)
    return True


def is_command(text, command_name):
    """Проверяет, является ли текст командой, возможно с @имя_бота."""
    if not text:
        return False
    # Удаляем возможное имя бота из команды
    # /command@botname -> /command
    # /command -> /command
    command_part = text.split('@')[0]
    return command_part == command_name


# Обработка webhook-запросов от Telegram
@app.route(f'/{TOKEN}', methods=['POST'])
async def webhook():
    try:
        update = request.get_json()
        logger.info(f"Получен update: {json.dumps(update, indent=2)}")

        if 'message' in update:
            await process_message(update['message'])
        elif 'callback_query' in update:
            await process_callback_query(update['callback_query'])

        return jsonify({'status': 'ok'})
    except Exception as e:
        logger.error(f"Ошибка при обработке webhook: {e}")
        return jsonify({'status': 'error', 'message': str(e)})

# Функция обработки сообщений


async def process_message(message):
    try:
        chat_id = message['chat']['id']
        user_id = message['from']['id']
        is_group = message['chat']['type'] in ['group', 'supergroup']

        if 'text' not in message:
            logger.info(f"Сообщение без текста от {user_id} в чате {chat_id}")
            return

        text = message['text']
        first_name = message['from'].get('first_name', 'Пользователь')
        # Используем first_name если нет username
        username = message['from'].get('username', first_name)

        current_state = States.IDLE
        if is_group:
            group_states.setdefault(chat_id, {})
            group_contexts.setdefault(chat_id, {})
            group_states[chat_id].setdefault(user_id, States.IDLE)
            group_contexts[chat_id].setdefault(user_id, {})
            current_state = group_states[chat_id][user_id]
        else:
            user_states.setdefault(user_id, States.IDLE)
            user_contexts.setdefault(user_id, {})
            current_state = user_states[user_id]

        logger.info(
            f"Сообщение от {username}({user_id}) в чате {chat_id} ({'группа' if is_group else 'личный'}): '{text}'. Состояние: {current_state}")

        # Обработка состояний
        if current_state == States.WAITING_DEED:
            logger.info(
                f"Получено описание дела: '{text}' от {username}({user_id}) в состоянии WAITING_DEED")
            if is_group:
                group_contexts[chat_id][user_id]['deed_description'] = text
                group_states[chat_id][user_id] = States.WAITING_POINTS
            else:
                user_contexts[user_id]['deed_description'] = text
                user_states[user_id] = States.WAITING_POINTS
            await send_message(chat_id, f"👍 @{username}, сколько баллов за это дело?")
            logger.info(
                f"Состояние для {username}({user_id}) изменено на WAITING_POINTS")
            return

        elif current_state == States.WAITING_POINTS:
            logger.info(
                f"Получены баллы: '{text}' от {username}({user_id}) в состоянии WAITING_POINTS")
            try:
                points = int(text)
                if points <= 0:
                    await send_message(chat_id, "❌ Баллы должны быть положительным числом. Попробуй еще раз:")
                    return

                child = await get_child(user_id)
                deed_description = ""
                if is_group:
                    deed_description = group_contexts[chat_id][user_id].get(
                        'deed_description', 'Доброе дело')
                else:
                    deed_description = user_contexts[user_id].get(
                        'deed_description', 'Доброе дело')

                await create_deed(child, deed_description, points)
                total_points = await update_child_points(child, points)

                response_text = (
                    f"🎉 Отлично, @{username}! Доброе дело '{deed_description}' добавлено.\n"
                    f"Ты получил *{points}* баллов!\n"
                    f"Всего у тебя теперь *{total_points}* баллов."
                )
                keyboard = {"inline_keyboard": [
                    [{"text": "📝 Добавить еще", "callback_data": "add_deed"}],
                    [{"text": "🏠 В меню", "callback_data": "back_to_menu"}]
                ]}
                await send_message(chat_id, response_text, parse_mode='Markdown', reply_markup=keyboard)

                if is_group:
                    group_states[chat_id][user_id] = States.IDLE
                    if user_id in group_contexts[chat_id]:
                        del group_contexts[chat_id][user_id]
                else:
                    user_states[user_id] = States.IDLE
                    if user_id in user_contexts:
                        del user_contexts[user_id]
                logger.info(
                    f"Дело '{deed_description}' ({points} баллов) добавлено для {username}({user_id}). Состояние сброшено.")

            except ValueError:
                await send_message(chat_id, "❌ Пожалуйста, введи число. Попробуй еще раз:")
            except Child.DoesNotExist:
                await send_message(chat_id, "Сначала зарегистрируйся с помощью /start")
            return

        elif current_state == States.PARENT_PASSWORD:
            password_input = text
            is_registering = user_contexts[user_id].get(
                'registering_parent', False)

            if is_registering:
                parent, _ = await get_or_create_parent(user_id, first_name)
                await set_parent_password(parent, password_input)
                del user_contexts[user_id]['registering_parent']
                user_states[user_id] = States.PARENT_MENU
                keyboard = {"inline_keyboard": [
                    [{"text": "➕ Добавить ребенка", "callback_data": "add_child"}],
                    [{"text": "📊 Статистика детей", "callback_data": "view_children"}],
                    [{"text": "🏠 В главное меню", "callback_data": "exit_parent_mode"}]
                ]}
                await send_message(chat_id, "🎉 Поздравляем! Вы зарегистрированы как родитель.", reply_markup=keyboard)
            else:
                try:
                    parent = await get_parent(user_id)
                    if await verify_parent_password(parent, password_input):
                        user_states[user_id] = States.PARENT_MENU
                        # Передаем объект родителя
                        await process_parent_command(chat_id, user_id, parent_obj=parent)
                    else:
                        await send_message(chat_id, "❌ Неверный пароль. Попробуйте еще раз или /cancel.")
                except Parent.DoesNotExist:
                    await send_message(chat_id, "❌ Вы не зарегистрированы как родитель. Используйте /parent для регистрации.")
            return

        elif current_state == States.PARENT_ADD_CHILD:
            child_name_input = text.strip()
            # Родитель должен быть уже аутентифицирован
            parent = await get_parent(user_id)

            # Пытаемся найти ребенка по имени. Если не найден, не создаем автоматом.
            # Ребенок должен сначала сам зарегистрироваться в боте через
            # /start.
            child_to_add = await get_child_by_name(child_name_input)

            if child_to_add:
                await add_child_to_parent(parent, child_to_add)
                await send_message(chat_id, f"✅ Ребенок *{child_to_add.name}* успешно добавлен!", parse_mode='Markdown')
            else:
                await send_message(chat_id, f"❓ Ребенок с именем '{child_name_input}' не найден. Попросите его сначала написать /start боту.")
            # Возврат в меню родителя
            user_states[user_id] = States.PARENT_MENU
            # Показать меню родителя
            await process_parent_command(chat_id, user_id, parent_obj=parent)
            return

        elif current_state == States.PARENT_ADD_DEED:
            user_contexts[user_id]['deed_description_parent'] = text
            user_states[user_id] = States.PARENT_ADD_POINTS
            await send_message(chat_id, "👍 Отлично! Теперь укажите, сколько баллов получает ребенок за это дело:")
            return

        elif current_state == States.PARENT_ADD_POINTS:
            try:
                points_input = int(text)
                if points_input <= 0:
                    await send_message(chat_id, "❌ Баллы должны быть положительным числом.")
                    return

                parent = await get_parent(user_id)
                selected_child_id = user_contexts[user_id].get(
                    'selected_child_id_parent')
                deed_description_parent = user_contexts[user_id].get(
                    'deed_description_parent', 'Доброе дело от родителя')

                if not selected_child_id:
                    await send_message(chat_id, "❌ Ошибка: не выбран ребенок. Начните заново с /parent.")
                    user_states[user_id] = States.PARENT_MENU
                    if 'selected_child_id_parent' in user_contexts[user_id]:
                        del user_contexts[user_id]['selected_child_id_parent']
                    if 'deed_description_parent' in user_contexts[user_id]:
                        del user_contexts[user_id]['deed_description_parent']
                    return

                child_obj = await get_child(selected_child_id)
                await create_deed(child_obj, deed_description_parent, points_input, parent)
                total_child_points = await update_child_points(child_obj, points_input)

                await send_message(chat_id,
                                   f"🎉 Доброе дело для *{child_obj.name}* добавлено!\n"
                                   f"Дело: *{deed_description_parent}*, Баллы: *+{points_input}*\n"
                                   f"Всего у ребенка: *{total_child_points}* баллов.",
                                   parse_mode='Markdown')
                user_states[user_id] = States.PARENT_MENU
                if 'selected_child_id_parent' in user_contexts[user_id]:
                    del user_contexts[user_id]['selected_child_id_parent']
                if 'deed_description_parent' in user_contexts[user_id]:
                    del user_contexts[user_id]['deed_description_parent']
                # Показать меню родителя
                await process_parent_command(chat_id, user_id, parent_obj=parent)

            except ValueError:
                await send_message(chat_id, "❌ Пожалуйста, введите число для баллов.")
            except Child.DoesNotExist:
                await send_message(chat_id, "❌ Ошибка: ребенок не найден.")
            return

        # Обработка команд
        if is_command(text, '/start'):
            child, created = await get_or_create_child(user_id, first_name)
            welcome_msg = (
                f"Привет, {child.name}! 👋 Это бот для записи твоих добрых дел.\n"
                f"У тебя сейчас *{child.total_points}* баллов.\nВыбери действие:"
            )
            keyboard_main_menu = [
                [{"text": "📝 Добавить дело", "callback_data": "add_deed"}],
                [{"text": "🌟 Мои баллы", "callback_data": "check_points"}],
                [{"text": "🎁 Награды", "callback_data": "view_rewards"}],
                [{"text": "❓ Помощь", "callback_data": "help"}]
            ]
            if not is_group:  # Кнопка родителя только в личных чатах
                keyboard_main_menu.append(
                    [{"text": "👨‍👩‍👧‍👦 Я родитель", "callback_data": "parent_mode"}])

            await send_message(chat_id, welcome_msg, parse_mode='Markdown', reply_markup={"inline_keyboard": keyboard_main_menu})
            if is_group:
                group_states[chat_id][user_id] = States.IDLE
            else:
                user_states[user_id] = States.IDLE

        elif is_command(text, '/help'):
            help_text_md = (
                "🌈 *Бот Добрых Дел* 🌈\n\n"
                "Записывай добрые дела и получай баллы!\n\n"
                "*Команды:*\n"
                "/start - Главное меню\n"
                "/add - Добавить дело\n"
                "/points - Мои баллы\n"
                "/rewards - Награды\n"
                "/parent - Режим родителя (в ЛС)\n"
                "/help - Эта справка\n\n"
                "*Как работает:*\n"
                "1. Делаешь доброе дело\n"
                "2. Записываешь в бот (сам или родитель)\n"
                "3. Копишь баллы\n"
                "4. Получаешь награды!\n\n"
                "*Примеры наград:*\n"
                "• 1000 - Обычная игрушка\n"
                "• 5000 - Крутая игрушка\n"
                "• 35000 - Nintendo Switch"
            )
            keyboard = {"inline_keyboard": [
                [{"text": "🏠 В меню", "callback_data": "back_to_menu"}]]}
            await send_message(chat_id, help_text_md, parse_mode='Markdown', reply_markup=keyboard)

        elif is_command(text, '/add'):
            if is_group:
                group_states[chat_id][user_id] = States.WAITING_DEED
            else:
                user_states[user_id] = States.WAITING_DEED
            await send_message(chat_id, f"📝 @{username}, опиши свое доброе дело:")

        elif is_command(text, '/points'):
            await process_points_command(chat_id, user_id, username)

        elif is_command(text, '/rewards'):
            await process_rewards_command(chat_id, user_id)

        elif is_command(text, '/parent'):
            if is_group:
                await send_message(chat_id, "Команда /parent доступна только в личных сообщениях с ботом.")
            else:
                await process_parent_command(chat_id, user_id)

        elif is_command(text, '/cancel'):
            state_to_set = States.IDLE
            context_to_clear = None
            if is_group:
                group_states[chat_id][user_id] = state_to_set
                context_to_clear = group_contexts[chat_id].get(user_id)
            else:
                user_states[user_id] = state_to_set
                context_to_clear = user_contexts.get(user_id)

            if context_to_clear:
                context_to_clear.clear()  # Очищаем контекст

            await send_message(chat_id, "❌ Действие отменено. Возврат в главное меню.")
            # Показываем главное меню
            await process_back_to_menu(chat_id, user_id, is_group, first_name)

        # Неизвестная команда, если не обработано выше и состояние IDLE
        elif text.startswith('/'):
            current_actual_state = group_states[chat_id][user_id] if is_group else user_states[user_id]
            if current_actual_state == States.IDLE:
                await send_message(chat_id, "❓ Неизвестная команда. Используйте /help для списка команд.")

        # Обработка "быстрого добавления" дела в группе, если состояние IDLE
        elif is_group and current_state == States.IDLE and re.match(r'(.+)\s(\d+)$', text, re.IGNORECASE):
            match = re.match(r'(.+)\s(\d+)$', text, re.IGNORECASE)
            if match:
                deed_description_quick, points_str_quick = match.groups()
                deed_description_quick = deed_description_quick.strip()
                try:
                    points_quick = int(points_str_quick)
                    if points_quick <= 0:
                        # Можно не отправлять сообщение, если это частая
                        # ошибка, чтобы не спамить
                        logger.info(
                            f"Быстрое добавление: неверные баллы от {username} ({points_str_quick})")
                        return

                    child_quick = await get_child(user_id)
                    await create_deed(child_quick, deed_description_quick, points_quick)
                    total_points_quick = await update_child_points(child_quick, points_quick)

                    await send_message(
                        chat_id,
                        f"⚡️ @{username} быстро добавил дело: '{deed_description_quick}' (+{points_quick} баллов). Теперь у него *{total_points_quick}*.",
                        parse_mode='Markdown'
                    )
                except ValueError:
                    logger.info(
                        f"Быстрое добавление: не удалось распознать баллы '{points_str_quick}' от {username}")
                except Child.DoesNotExist:
                    await send_message(chat_id, f"@{username}, сначала зарегистрируйся с помощью /start, чтобы добавлять дела.")
                except Exception as e_quick:
                    logger.error(
                        f"Ошибка при быстром добавлении дела для {username}: {e_quick}")

    except Exception as e:
        logger.error(
            f"Критическая ошибка в process_message от {user_id} в {chat_id}: {e}",
            exc_info=True)
        try:
            await send_message(chat_id, "❌ Произошла серьезная ошибка. Попробуйте позже или свяжитесь с администратором.")
        except Exception as e_send:
            logger.error(
                f"Не удалось отправить сообщение об ошибке в process_message: {e_send}")


async def process_callback_query(callback_query):
    try:
        data = callback_query['data']
        chat_id = callback_query['message']['chat']['id']
        user_id = callback_query['from']['id']
        first_name = callback_query['from'].get('first_name', 'Пользователь')
        username = callback_query['from'].get('username', first_name)
        is_group = callback_query['message']['chat']['type'] in [
            'group', 'supergroup']
        message_id = callback_query['message']['message_id']

        logger.info(
            f"Callback от {username}({user_id}): {data} в чате {chat_id}")
        # Отвечаем сразу, чтобы кнопка не "зависала"
        await answer_callback_query(callback_query['id'])

        if data == 'add_deed':
            if is_group:
                group_states.setdefault(
                    chat_id, {}).setdefault(
                    user_id, States.IDLE)  # Гарантируем инициализацию
                group_states[chat_id][user_id] = States.WAITING_DEED
            else:
                user_states.setdefault(
                    user_id, States.IDLE)  # Гарантируем инициализацию
                user_states[user_id] = States.WAITING_DEED
            await send_message(chat_id, f"📝 @{username}, опиши свое доброе дело:")

        elif data == 'check_points':
            await process_points_command(chat_id, user_id, username)

        elif data == 'view_rewards':
            await process_rewards_command(chat_id, user_id)

        elif data == 'help':
            help_text_md = (
                "🌈 *Бот Добрых Дел* 🌈\n\n"
                # ... (текст справки как в process_message)
                "/start - Главное меню\n"
                "/add - Добавить дело\n"
                "/points - Мои баллы\n"
                "/rewards - Награды\n"
                "/parent - Режим родителя (в ЛС)\n"
                "/help - Эта справка"
            )
            keyboard = {"inline_keyboard": [
                [{"text": "🏠 В меню", "callback_data": "back_to_menu"}]]}
            # Редактируем сообщение, если это возможно, или отправляем новое
            try:
                await edit_message(chat_id, message_id, help_text_md, parse_mode='Markdown', reply_markup=keyboard)
            # Если редактирование не удалось (например, сообщение слишком
            # старое)
            except BaseException:
                await send_message(chat_id, help_text_md, parse_mode='Markdown', reply_markup=keyboard)

        elif data == 'back_to_menu':
            await process_back_to_menu(chat_id, user_id, is_group, first_name, message_id_to_edit=message_id)

        elif data == 'parent_mode':
            if is_group:
                await send_message(chat_id, "Режим родителя доступен только в личных сообщениях.")
                return
            await process_parent_command(chat_id, user_id)
            # Удаляем предыдущее меню, если это callback от него
            try:
                await edit_message(chat_id, message_id, "Переход в режим родителя...")
            except BaseException:
                pass

        elif data == 'add_child':  # Только для родителя в ЛС
            if is_group:
                return
            user_states[user_id] = States.PARENT_ADD_CHILD
            await edit_message(chat_id, message_id, "👶 Введите имя ребенка, которого хотите добавить:", reply_markup=None)

        elif data == 'view_children':  # Только для родителя в ЛС
            if is_group:
                return
            parent = await get_parent(user_id)
            children = await get_parent_children(parent)
            if not children:
                text_to_send = "У вас пока нет добавленных детей."
                kb = {"inline_keyboard": [[{"text": "➕ Добавить ребенка", "callback_data": "add_child"}], [
                    {"text": "◀️ Назад в меню родителя", "callback_data": "back_to_parent_menu"}]]}
            else:
                text_to_send = "📊 *Статистика ваших детей:*\n\n"
                for ch_obj in children:
                    deeds = await get_recent_deeds(ch_obj, limit=3)
                    text_to_send += f"👶 *{ch_obj.name}*: {ch_obj.total_points} баллов\n"
                    if deeds:
                        text_to_send += "Последние дела:\n" + \
                            "\n".join([f"• {d.description}: {d.points} ({d.created_at.strftime('%d.%m')})" for d in deeds]) + "\n"
                    text_to_send += "\n"
                kb = {"inline_keyboard": [
                    [{"text": "➕ Доб. дело ребенку", "callback_data": "add_deed_to_child_select"}],
                    [{"text": "◀️ Назад в меню родителя", "callback_data": "back_to_parent_menu"}]
                ]}
            await edit_message(chat_id, message_id, text_to_send, parse_mode='Markdown', reply_markup=kb)

        elif data == 'add_deed_to_child_select':  # Только для родителя в ЛС
            if is_group:
                return
            parent = await get_parent(user_id)
            children = await get_parent_children(parent)
            if not children:
                await edit_message(chat_id, message_id, "Сначала добавьте ребенка.", reply_markup={"inline_keyboard": [[{"text": "➕ Добавить ребенка", "callback_data": "add_child"}], [{"text": "◀️ Назад", "callback_data": "back_to_parent_menu"}]]})
                return

            children_buttons = [
                [{"text": f"👶 {ch.name}", "callback_data": f"select_child_for_deed_{ch.telegram_id}"}] for ch in children]
            children_buttons.append(
                [{"text": "◀️ Назад", "callback_data": "back_to_parent_menu"}])
            await edit_message(chat_id, message_id, "Выберите ребенка для добавления дела:", reply_markup={"inline_keyboard": children_buttons})

        elif data.startswith("select_child_for_deed_"):  # Только для родителя в ЛС
            if is_group:
                return
            child_tg_id = int(data.split("_")[-1])
            user_contexts.setdefault(
                user_id, {})['selected_child_id_parent'] = child_tg_id
            child_obj = await get_child(child_tg_id)
            user_states[user_id] = States.PARENT_ADD_DEED
            await edit_message(chat_id, message_id, f"Опишите доброе дело для *{child_obj.name}*:", parse_mode='Markdown', reply_markup=None)

        elif data == 'exit_parent_mode':  # Только для родителя в ЛС
            if is_group:
                return
            user_states[user_id] = States.IDLE
            await edit_message(chat_id, message_id, "Вы вышли из режима родителя.")
            # Показать главное меню пользователя
            await process_back_to_menu(chat_id, user_id, is_group, first_name)

        elif data == 'back_to_parent_menu':  # Только для родителя в ЛС
            if is_group:
                return
            parent = await get_parent(user_id)  # Убедиться, что это родитель
            await process_parent_command(chat_id, user_id, parent_obj=parent, message_id_to_edit=message_id)

        else:
            logger.warning(
                f"Неизвестный callback_data: {data} от {username}({user_id})")
            # Можно отправить пользователю сообщение, что команда не
            # распознана, если это необходимо

    except Exception as e:
        logger.error(
            f"Ошибка в process_callback_query от {user_id} для data='{data}': {e}",
            exc_info=True)


async def process_points_command(chat_id, user_id, username_display):
    try:
        child = await get_child(user_id)
        recent_deeds = await get_recent_deeds(child, limit=5)
        text = f"🌟 @{username_display}, у тебя сейчас *{child.total_points}* баллов! 🌟\n\n"
        if recent_deeds:
            text += "📋 *Последние добрые дела:*\n"
            for deed in recent_deeds:
                text += f"• {
                    deed.description}: *{
                    deed.points}* ({
                    deed.created_at.strftime('%d.%m.%Y')})\n"
        else:
            text += "Пока нет записанных добрых дел."

        keyboard = {"inline_keyboard": [
            [{"text": "🏠 В меню", "callback_data": "back_to_menu"}]]}
        await send_message(chat_id, text, parse_mode='Markdown', reply_markup=keyboard)
    except Child.DoesNotExist:
        await send_message(chat_id, f"@{username_display}, сначала зарегистрируйся с помощью /start")
    except Exception as e:
        logger.error(f"Ошибка в process_points_command для {user_id}: {e}")
        await send_message(chat_id, "Произошла ошибка при показе баллов.")


async def process_rewards_command(chat_id, user_id):
    try:
        # Убедимся, что пользователь зарегистрирован как ребенок
        await get_child(user_id)
        # [{name: str, points_required: int, description: str}, ...]
        rewards = await get_rewards()

        text = "🎁 *Доступные награды:*\n\n"
        # Стандартные награды, если из БД ничего не пришло или они там не
        # заданы
        default_rewards_text = (
            "• Обычная игрушка: 1000 баллов\n"
            "• Взять приставку на выходные: 3000 баллов\n"
            "• Крутая игрушка: 5000 баллов\n"
            "• Nintendo Switch: 35000 баллов\n"
        )
        if not rewards:
            text += "Пока в базе нет специальных наград. Вот стандартный список:\n" + \
                default_rewards_text
        else:
            for reward in rewards:
                text += f"• *{reward.name}*: {reward.points_required} баллов"
                if reward.description:
                    text += f" ({reward.description})"
                text += "\n"
            text += "\nТакже всегда доступны стандартные награды:\n" + default_rewards_text

        keyboard = {"inline_keyboard": [
            [{"text": "🏠 В меню", "callback_data": "back_to_menu"}]]}
        await send_message(chat_id, text, parse_mode='Markdown', reply_markup=keyboard)
    except Child.DoesNotExist:
        # username можно получить из callback_query или message, но здесь его нет напрямую
        # Можно передавать или делать еще один запрос к TG API, если это
        # критично
        await send_message(chat_id, "Сначала зарегистрируйся с помощью /start, чтобы смотреть награды.")
    except Exception as e:
        logger.error(f"Ошибка в process_rewards_command для {user_id}: {e}")
        await send_message(chat_id, "Произошла ошибка при показе наград.")


async def process_parent_command(
        chat_id,
        user_id,
        parent_obj=None,
        message_id_to_edit=None):
    """Обработка команды /parent и отображение меню родителя."""
    try:
        if not parent_obj:  # Если объект родителя не передан, пытаемся его получить или проверить регистрацию
            parent_check, is_registered_parent = await verify_parent(user_id)
            if is_registered_parent:
                parent_obj = parent_check
            else:
                user_states[user_id] = States.PARENT_PASSWORD
                user_contexts.setdefault(
                    user_id, {})['registering_parent'] = True
                text_to_send = (
                    "Вы еще не зарегистрированы как родитель. "
                    "Введите пароль для регистрации и входа в режим родителя:")
                if message_id_to_edit:
                    await edit_message(chat_id, message_id_to_edit, text_to_send, reply_markup=None)
                else:
                    await send_message(chat_id, text_to_send)
                return

        # Если parent_obj есть (прошел проверку или был передан), показываем
        # меню родителя
        first_name = parent_obj.name  # Используем имя из БД

        children = await get_parent_children(parent_obj)
        parent_menu_text = f"👋 Здравствуйте, {first_name}! Режим родителя.\n"
        parent_menu_text += f"У вас {
            len(children)} {
            'детей' if len(children) != 1 else 'ребенок'}."

        keyboard_parent = [
            [{"text": "➕ Добавить ребенка", "callback_data": "add_child"}],
            [{"text": "📊 Статистика детей", "callback_data": "view_children"}],
            [{"text": "💸 Добавить дело ребенку", "callback_data": "add_deed_to_child_select"}],
            [{"text": "🏠 Выйти из режима", "callback_data": "exit_parent_mode"}]
        ]
        if message_id_to_edit:
            await edit_message(chat_id, message_id_to_edit, parent_menu_text, reply_markup={"inline_keyboard": keyboard_parent})
        else:
            await send_message(chat_id, parent_menu_text, reply_markup={"inline_keyboard": keyboard_parent})
        user_states[user_id] = States.PARENT_MENU

    except Exception as e:
        logger.error(
            f"Ошибка в process_parent_command для {user_id}: {e}",
            exc_info=True)
        text_error = "Произошла ошибка в режиме родителя."
        if message_id_to_edit:
            try:
                await edit_message(chat_id, message_id_to_edit, text_error)
            except BaseException:
                await send_message(chat_id, text_error)
        else:
            await send_message(chat_id, text_error)


async def process_back_to_menu(
        chat_id,
        user_id,
        is_group,
        user_first_name,
        message_id_to_edit=None):
    try:
        child = await get_child(user_id)  # Убеждаемся, что ребенок существует
        text = (
            f"Привет, {user_first_name}! 👋\n"
            f"У тебя *{child.total_points}* баллов.\nВыбери действие:"
        )
        keyboard_main_menu = [
            [{"text": "📝 Добавить дело", "callback_data": "add_deed"}],
            [{"text": "🌟 Мои баллы", "callback_data": "check_points"}],
            [{"text": "🎁 Награды", "callback_data": "view_rewards"}],
            [{"text": "❓ Помощь", "callback_data": "help"}]
        ]
        if not is_group:
            keyboard_main_menu.append(
                [{"text": "👨‍👩‍👧‍👦 Я родитель", "callback_data": "parent_mode"}])

        reply_markup = {"inline_keyboard": keyboard_main_menu}

        if message_id_to_edit:
            try:
                await edit_message(chat_id, message_id_to_edit, text, parse_mode='Markdown', reply_markup=reply_markup)
            except Exception as e_edit:  # Если редактирование не удалось
                logger.warning(
                    f"Не удалось отредактировать сообщение для back_to_menu: {e_edit}, отправляю новое.")
                await send_message(chat_id, text, parse_mode='Markdown', reply_markup=reply_markup)
        else:
            await send_message(chat_id, text, parse_mode='Markdown', reply_markup=reply_markup)

        if is_group:
            group_states[chat_id][user_id] = States.IDLE
        else:
            user_states[user_id] = States.IDLE
    except Child.DoesNotExist:
        await send_message(chat_id, f"{user_first_name}, сначала зарегистрируйся с помощью /start")
    except Exception as e:
        logger.error(
            f"Ошибка в process_back_to_menu для {user_id}: {e}",
            exc_info=True)
        await send_message(chat_id, "Ошибка при возврате в меню.")


# Функции для работы с Telegram API
async def send_message(chat_id, text, parse_mode=None, reply_markup=None):
    url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    payload = {'chat_id': chat_id, 'text': text}
    if parse_mode:
        payload['parse_mode'] = parse_mode
    if reply_markup:
        payload['reply_markup'] = reply_markup

    try:
        # @sync_to_async # sync_to_async не нужен для requests если он не в Django view напрямую
        # response = requests.post(url, json=payload) # Это блокирующий вызов

        # Для асинхронности с requests нужен httpx или aiohttp, либо запускать requests в executor
        # Пока оставим синхронный вариант для простоты, т.к. основная логика бота асинхронна через asgiref для Django
        # В реальном Flask async view лучше использовать async http client
        # Но т.к. это Flask под ASGI (вероятно, через Daphne/Uvicorn, т.к. есть
        # django.setup()), requests.post должен быть обернут
        @sync_to_async
        def do_post_request():
            return requests.post(url, json=payload)
        response = await do_post_request()

        response_json = response.json()
        if not response_json.get('ok'):
            logger.error(
                f"Ошибка при отправке сообщения: {response_json} | Payload: {payload}")
        return response_json
    except Exception as e:
        logger.error(
            f"Исключение при отправке сообщения: {e} | Payload: {payload}",
            exc_info=True)
        return None


async def edit_message(
        chat_id,
        message_id,
        text,
        parse_mode=None,
        reply_markup=None):
    url = f"https://api.telegram.org/bot{TOKEN}/editMessageText"
    payload = {'chat_id': chat_id, 'message_id': message_id, 'text': text}
    if parse_mode:
        payload['parse_mode'] = parse_mode
    if reply_markup:
        payload['reply_markup'] = reply_markup

    try:
        @sync_to_async
        def do_post_request():
            return requests.post(url, json=payload)
        response = await do_post_request()

        response_json = response.json()
        if not response_json.get('ok'):
            logger.error(
                f"Ошибка при редактировании сообщения: {response_json} | Payload: {payload}")
        return response_json
    except Exception as e:
        logger.error(
            f"Исключение при редактировании сообщения: {e} | Payload: {payload}",
            exc_info=True)
        return None


async def answer_callback_query(
        callback_query_id,
        text=None,
        show_alert=False):
    url = f"https://api.telegram.org/bot{TOKEN}/answerCallbackQuery"
    payload = {
        'callback_query_id': callback_query_id,
        'show_alert': show_alert}
    if text:
        payload['text'] = text

    try:
        @sync_to_async
        def do_post_request():
            return requests.post(url, json=payload)
        response = await do_post_request()

        response_json = response.json()
        if not response_json.get('ok'):
            logger.error(
                f"Ошибка при ответе на callback_query: {response_json} | Payload: {payload}")
        return response_json
    except Exception as e:
        logger.error(
            f"Исключение при ответе на callback_query: {e} | Payload: {payload}",
            exc_info=True)
        return None

# Маршруты Flask для установки/удаления webhook (обычно не нужны при
# деплое на PaaS)


@app.route('/set_webhook', methods=['GET'])
def set_webhook_route():  # Переименовал, чтобы не конфликтовать с функцией set_webhook
    host = request.host_url  # Получаем базовый URL хоста, например "https://example.com/"
    webhook_url_path = f"{TOKEN}"  # Путь к вебхуку
    full_webhook_url = f"{host.rstrip('/')}/{webhook_url_path.lstrip('/')}"

    # Для API Telegram нужен URL вебхука без query параметров в самом URL setWebhook
    # Параметр allowed_updates можно передать в JSON payload запроса setWebhook

    api_url = f"https://api.telegram.org/bot{TOKEN}/setWebhook"
    # allowed_updates можно добавить сюда ['message', 'callback_query']
    payload = {'url': full_webhook_url}

    try:
        response = requests.post(api_url, json=payload)
        data = response.json()
        if data.get('ok'):
            return jsonify({'status': 'success',
                            'message': f'Webhook установлен на {full_webhook_url}',
                            'result': data})
        else:
            logger.error(f"Не удалось установить webhook: {data}")
            return jsonify(
                {'status': 'error', 'message': 'Не удалось установить webhook', 'result': data}), 400
    except Exception as e:
        logger.error(f"Исключение при установке webhook: {e}")
        return jsonify(
            {'status': 'error', 'message': f'Исключение: {str(e)}'}), 500


@app.route('/remove_webhook', methods=['GET'])
def remove_webhook_route():  # Переименовал
    url = f"https://api.telegram.org/bot{TOKEN}/deleteWebhook"
    try:
        response = requests.get(url)
        data = response.json()
        return jsonify({'status': 'success' if data.get('ok') else 'error', 'message': data.get(
            'description', 'Webhook удален/не удален'), 'result': data})
    except Exception as e:
        logger.error(f"Исключение при удалении webhook: {e}")
        return jsonify(
            {'status': 'error', 'message': f'Исключение: {str(e)}'}), 500


@app.route('/webhook_status', methods=['GET'])
def webhook_status_route():  # Переименовал
    url = f"https://api.telegram.org/bot{TOKEN}/getWebhookInfo"
    try:
        response = requests.get(url)
        data = response.json()
        return jsonify({'status': 'success', 'webhook_info': data})
    except Exception as e:
        logger.error(f"Исключение при получении статуса webhook: {e}")
        return jsonify(
            {'status': 'error', 'message': f'Исключение: {str(e)}'}), 500


# Обычно не используется, если основной вебхук на /<TOKEN>
@app.route('/web-hook')
def web_hook_info_page():
    return "Это информационная страница. Вебхук настроен на другой URL."


@app.route('/')
def home():
    return 'Бот для учета добрых дел успешно запущен и готов к работе!'


if __name__ == '__main__':
    # При локальном запуске Flask dev server не очень хорошо работает с async/await без дополнительных настроек
    # Для полноценной асинхронной работы лучше использовать ASGI сервер, например, Uvicorn:
    # uvicorn your_script_name:app --reload
    # Однако, django.setup() и sync_to_async предполагают, что это может быть запущено в контексте ASGI.
    # Для простоты локального тестирования можно оставить app.run(), но
    # @sync_to_async вызовы будут работать синхронно.

    # Если вы используете Flask >= 2.0, он имеет встроенную поддержку async views.
    # Убедитесь, что ваша версия Flask это поддерживает.
    logger.info("Запуск Flask development server...")
    app.run(debug=True, host='0.0.0.0', port=int(os.environ.get('PORT', 8080)))
