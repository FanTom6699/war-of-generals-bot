import asyncio
import logging
import random
import time
import datetime
import json
import sqlite3
import os
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters.command import Command
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.enums import ParseMode
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.exceptions import TelegramAPIError
from typing import Union
from aiogram.types import BotCommand
from apscheduler.schedulers.asyncio import AsyncIOScheduler

# Импортируем наш лексикон полностью
from lexicon import LEXICON_RU, LEXICON_COMMANDS_RU

# ==============================================================================
# --- НАСТРОЙКИ И КОНФИГУРАЦИЯ ---
# ==============================================================================
logging.basicConfig(level=logging.INFO)
API_TOKEN = os.environ.get('TELEGRAM_API_TOKEN')
DATABASE_NAME = '/var/data/wog_database.db'
ADMIN_IDS = [5658493362]

if not API_TOKEN:
    raise ValueError("Не найден API_TOKEN. Убедитесь, что он задан в переменных окружения.")

bot = Bot(token=API_TOKEN)
dp = Dispatcher()
scheduler = AsyncIOScheduler(timezone="Europe/Moscow")

# --- Определения Юнитов, Зданий и Времени ---
UNITS = {'soldier': {'name': 'Боец 💂', 'cost': 25, 'stats': {'hp': 15, 'attack': 3, 'cargo_capacity': 5}}}
BUILDINGS = {
    'command_center': {
        'name': 'Командный центр 🏛️',
        'description': 'Сердце вашей базы. Производит Припасы для строительства и улучшений.',
        'produces': 50
    },
    'barracks': {
        'name': 'Казармы 🛖',
        'description': 'Здесь вы тренируете своих бойцов. Улучшение этого здания сокращает время тренировки каждого солдата.'
    },
    'warehouse': {
        'name': 'Склад 📦',
        'description': 'Служит для хранения добытых ресурсов. Улучшение увеличивает вместимость и количество ресурсов, защищенных от грабежа.'
    }
}
LUCK_MODIFIER_RANGE = 0.25
ATTACK_COOLDOWN_SECONDS = 600
BONUS_COOLDOWN_SECONDS = 2 * 3600

BARRACKS_TRAINING_TIME = {1: 90, 2: 82, 3: 75, 4: 68, 5: 62, 6: 56, 7: 50, 8: 45, 9: 40, 10: 35}
WAREHOUSE_PROTECTION_PERCENT = 0.40
BUILDING_UPGRADE_TIME = {1: 300, 2: 600, 3: 1200, 4: 2700, 5: 5400, 6: 10800, 7: 21600, 8: 43200, 9: 86400, 10: 172800}
MAX_BUILDING_LEVEL = 10

BUILDING_UPGRADE_COST = {
    1: 800, 2: 1800, 3: 3500, 4: 6500, 5: 11000,
    6: 18000, 7: 28000, 8: 45000, 9: 70000, 10: 0
}
WAREHOUSE_CAPACITY = {
    1: 2000, 2: 4000, 3: 7000, 4: 12000, 5: 20000,
    6: 30000, 7: 50000, 8: 80000, 9: 120000, 10: 200000
}


# ==============================================================================
# --- УПРАВЛЕНИЕ БАЗОЙ ДАННЫХ ---
# ==============================================================================
def init_db():
    with sqlite3.connect(DATABASE_NAME) as conn:
        cursor = conn.cursor()
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS players (
                user_id INTEGER PRIMARY KEY, name TEXT NOT NULL, resources REAL NOT NULL,
                last_update INTEGER NOT NULL, army TEXT NOT NULL, buildings TEXT NOT NULL,
                attack_wins INTEGER DEFAULT 0, defense_wins INTEGER DEFAULT 0 )
        ''')
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS battle_reports (
                report_id INTEGER PRIMARY KEY AUTOINCREMENT, player_id INTEGER NOT NULL,
                report_text TEXT NOT NULL, timestamp INTEGER NOT NULL )
        ''')
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS training_queue (
                user_id INTEGER PRIMARY KEY, unit_id TEXT NOT NULL,
                quantity_remaining INTEGER NOT NULL, next_unit_finish_time INTEGER NOT NULL )
        ''')
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS construction_queue (
                queue_id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL UNIQUE,
                building_id TEXT NOT NULL, finish_time INTEGER NOT NULL )
        ''')
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS attack_cooldowns (
                user_id INTEGER PRIMARY KEY, finish_time INTEGER NOT NULL )
        ''')
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS daily_bonuses (
                user_id INTEGER PRIMARY KEY,
                last_claim_timestamp INTEGER NOT NULL,
                notification_sent INTEGER DEFAULT 0
            )
        ''')
        try:
            cursor.execute("ALTER TABLE players ADD COLUMN attack_wins INTEGER DEFAULT 0")
            cursor.execute("ALTER TABLE players ADD COLUMN defense_wins INTEGER DEFAULT 0")
        except sqlite3.OperationalError: pass
        try:
            cursor.execute("ALTER TABLE daily_bonuses ADD COLUMN notification_sent INTEGER DEFAULT 0")
        except sqlite3.OperationalError: pass
        conn.commit()


def get_bonus_cooldown(user_id: int) -> int | None:
    with sqlite3.connect(DATABASE_NAME) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT last_claim_timestamp FROM daily_bonuses WHERE user_id = ?", (user_id,))
        row = cursor.fetchone()
        if row:
            time_since_last_claim = int(time.time()) - row[0]
            if time_since_last_claim < BONUS_COOLDOWN_SECONDS:
                return BONUS_COOLDOWN_SECONDS - time_since_last_claim
        return None

def set_bonus_claimed(user_id: int):
    with sqlite3.connect(DATABASE_NAME) as conn:
        cursor = conn.cursor()
        cursor.execute("REPLACE INTO daily_bonuses (user_id, last_claim_timestamp, notification_sent) VALUES (?, ?, 0)", (user_id, int(time.time())))
        conn.commit()

def get_players_for_bonus_notification() -> list[tuple[int, int]]:
    with sqlite3.connect(DATABASE_NAME) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT user_id, last_claim_timestamp FROM daily_bonuses WHERE notification_sent = 0")
        return cursor.fetchall()

def set_bonus_notification_sent(user_id: int):
    with sqlite3.connect(DATABASE_NAME) as conn:
        cursor = conn.cursor()
        cursor.execute("UPDATE daily_bonuses SET notification_sent = 1 WHERE user_id = ?", (user_id,))
        conn.commit()

def add_player(user_id: int, name: str, army_template: dict, buildings_template: dict):
    with sqlite3.connect(DATABASE_NAME) as conn:
        cursor = conn.cursor()
        player_data = (
            user_id, name, 1000.0, int(time.time()),
            json.dumps(army_template), json.dumps(buildings_template),
            0, 0
        )
        cursor.execute('''
            INSERT INTO players (user_id, name, resources, last_update, army, buildings, attack_wins, defense_wins)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ''', player_data)
        set_bonus_claimed(user_id)
        conn.commit()


def get_player(user_id: int) -> Union[dict, None]:
    with sqlite3.connect(DATABASE_NAME) as conn:
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM players WHERE user_id = ?", (user_id,))
        row = cursor.fetchone()
        if row:
            player_dict = dict(row)
            player_dict['army'] = json.loads(player_dict['army'])
            player_dict['buildings'] = json.loads(player_dict['buildings'])
            return player_dict
        return None


def update_player_data(user_id: int, data: dict):
    with sqlite3.connect(DATABASE_NAME) as conn:
        cursor = conn.cursor()
        army_json = json.dumps(data.get('army'))
        buildings_json = json.dumps(data.get('buildings'))
        cursor.execute('''
            UPDATE players 
            SET resources = ?, last_update = ?, army = ?, buildings = ?, 
            attack_wins = ?, defense_wins = ? WHERE user_id = ?
        ''', (
            data.get('resources'), data.get('last_update'), army_json, buildings_json,
            data.get('attack_wins', 0), data.get('defense_wins', 0), user_id
        ))
        conn.commit()


def add_to_training_queue(user_id: int, unit_id: str, quantity: int, next_finish_time: int):
    with sqlite3.connect(DATABASE_NAME) as conn:
        cursor = conn.cursor()
        cursor.execute(
            "REPLACE INTO training_queue (user_id, unit_id, quantity_remaining, next_unit_finish_time) VALUES (?, ?, ?, ?)",
            (user_id, unit_id, quantity, next_finish_time))
        conn.commit()


def get_training_queue(user_id: int) -> Union[tuple, None]:
    with sqlite3.connect(DATABASE_NAME) as conn:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT user_id, unit_id, quantity_remaining, next_unit_finish_time FROM training_queue WHERE user_id = ?",
            (user_id,))
        return cursor.fetchone()


def remove_from_training_queue(user_id: int):
    with sqlite3.connect(DATABASE_NAME) as conn:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM training_queue WHERE user_id = ?", (user_id,))
        conn.commit()


def player_exists(user_id: int) -> bool:
    with sqlite3.connect(DATABASE_NAME) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT user_id FROM players WHERE user_id = ?", (user_id,))
        return cursor.fetchone() is not None


def get_all_user_ids() -> list[int]:
    with sqlite3.connect(DATABASE_NAME) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT user_id FROM players")
        return [row[0] for row in cursor.fetchall()]


def get_top_players(sort_by: str, limit: int = 3) -> list:
    with sqlite3.connect(DATABASE_NAME) as conn:
        query = f"SELECT name, {sort_by} FROM players ORDER BY {sort_by} DESC LIMIT ?"
        cursor = conn.cursor()
        cursor.execute(query, (limit,))
        return cursor.fetchall()


def get_all_players_for_power_rating() -> list:
    with sqlite3.connect(DATABASE_NAME) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT name, army FROM players")
        return cursor.fetchall()


def add_to_construction_queue(user_id: int, building_id: str, finish_time: int):
    with sqlite3.connect(DATABASE_NAME) as conn:
        cursor = conn.cursor()
        cursor.execute("INSERT INTO construction_queue (user_id, building_id, finish_time) VALUES (?, ?, ?)",
                       (user_id, building_id, finish_time))
        conn.commit()


def get_construction_queue(user_id: int) -> Union[tuple, None]:
    with sqlite3.connect(DATABASE_NAME) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM construction_queue WHERE user_id = ?", (user_id,))
        return cursor.fetchone()


def remove_from_construction_queue(queue_id: int):
    with sqlite3.connect(DATABASE_NAME) as conn:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM construction_queue WHERE queue_id = ?", (queue_id,))
        conn.commit()


def add_battle_report(player_id: int, report_text: str) -> int:
    with sqlite3.connect(DATABASE_NAME) as conn:
        cursor = conn.cursor()
        timestamp = int(time.time())
        cursor.execute("INSERT INTO battle_reports (player_id, report_text, timestamp) VALUES (?, ?, ?)",
                       (player_id, report_text, timestamp))
        conn.commit()
        return cursor.lastrowid


def get_battle_report(report_id: int) -> Union[str, None]:
    with sqlite3.connect(DATABASE_NAME) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT report_text FROM battle_reports WHERE report_id = ?", (report_id,))
        row = cursor.fetchone()
        return row[0] if row else None


def get_all_players_for_attack(user_id_to_exclude: int) -> list:
    with sqlite3.connect(DATABASE_NAME) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT user_id, name FROM players WHERE user_id != ?", (user_id_to_exclude,))
        return cursor.fetchall()


def set_attack_cooldown(user_id: int, finish_time: int):
    with sqlite3.connect(DATABASE_NAME) as conn:
        cursor = conn.cursor()
        cursor.execute("REPLACE INTO attack_cooldowns (user_id, finish_time) VALUES (?, ?)", (user_id, finish_time))
        conn.commit()


def get_attack_cooldown(user_id: int) -> Union[int, None]:
    with sqlite3.connect(DATABASE_NAME) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT finish_time FROM attack_cooldowns WHERE user_id = ?", (user_id,))
        row = cursor.fetchone()
        if row and row[0] > int(time.time()):
            return row[0]
        return None
# ==============================================================================
# --- FSM (МАШИНА СОСТОЯНИЙ) ---
# ==============================================================================

class AdminStates(StatesGroup):
    waiting_for_target_id_for_resources = State()
    waiting_for_amount = State()
    waiting_for_broadcast_message = State()
    waiting_for_player_id_for_info = State()


class TrainingState(StatesGroup):
    selecting_quantity = State()


class ArmyManagementState(StatesGroup):
    waiting_for_reserve_quantity = State()
    waiting_for_active_quantity = State()


# ==============================================================================
# --- ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ И УТИЛИТЫ ---
# ==============================================================================
def create_progress_bar(current: float, maximum: float, length: int = 10) -> str:
    if maximum == 0: return '░' * length
    percent = current / maximum
    filled_length = int(length * percent)
    bar = '█' * filled_length + '░' * (length - filled_length)
    return bar

def update_player_resources(player_data: dict):
    now = int(time.time())
    time_passed_seconds = now - player_data.get('last_update', now)
    cc_level = player_data['buildings'].get('command_center', 0)
    resources_per_hour = BUILDINGS['command_center']['produces'] * cc_level
    gained = (time_passed_seconds / 3600) * resources_per_hour
    warehouse_level = player_data['buildings'].get('warehouse', 1)
    capacity = WAREHOUSE_CAPACITY.get(warehouse_level, 0)
    current_resources = player_data.get('resources', 0)
    if current_resources < capacity:
        player_data['resources'] = min(capacity, current_resources + gained)
    player_data['last_update'] = now
    return player_data

async def check_and_complete_training(user_id: int):
    training_job = get_training_queue(user_id)
    if not training_job:
        return False
    now = int(time.time())
    _, unit_id, quantity_remaining, next_unit_finish_time = training_job
    player_data = get_player(user_id)
    if not player_data: return False
    player_data = update_player_resources(player_data)
    barracks_level = player_data['buildings'].get('barracks', 1)
    time_per_unit = BARRACKS_TRAINING_TIME.get(barracks_level, 999)
    units_completed = 0
    with sqlite3.connect(DATABASE_NAME) as conn:
        cursor = conn.cursor()
        while now >= next_unit_finish_time and quantity_remaining > 0:
            units_completed += 1
            quantity_remaining -= 1
            next_unit_finish_time += time_per_unit
        if units_completed > 0:
            player_data['army']['reserve'][unit_id] = player_data['army']['reserve'].get(unit_id, 0) + units_completed
            update_player_data(user_id, player_data)
            if quantity_remaining > 0:
                cursor.execute("UPDATE training_queue SET quantity_remaining = ?, next_unit_finish_time = ? WHERE user_id = ?",
                               (quantity_remaining, next_unit_finish_time, user_id))
            else:
                cursor.execute("DELETE FROM training_queue WHERE user_id = ?", (user_id,))
            conn.commit()
    if units_completed > 0 and quantity_remaining == 0:
        try:
            await bot.send_message(user_id, "✅ **Подготовка завершена!** Новые отряды прибыли в гарнизон.")
        except TelegramAPIError as e:
            logging.error(f"Не удалось уведомить о финальном завершении тренировки {user_id}: {e}")
    return units_completed > 0


async def check_and_complete_construction(user_id: int):
    job = get_construction_queue(user_id)
    if job and time.time() >= job[3]:
        queue_id, _, building_id, _ = job
        if building_id not in BUILDINGS:
            logging.error(f"Invalid building_id '{building_id}' for user {user_id}. Removing bad entry.")
            remove_from_construction_queue(queue_id)
            return False
        player_data = get_player(user_id)
        if player_data:
            player_data['buildings'][building_id] = player_data['buildings'].get(building_id, 0) + 1
            update_player_data(user_id, player_data)
        remove_from_construction_queue(queue_id)
        try:
            building_name = BUILDINGS[building_id]['name']
            await bot.send_message(user_id,
                                   f"✅ **Строительство завершено!**\n{building_name} улучшен до уровня {player_data['buildings'][building_id]}.")
        except TelegramAPIError as e:
            logging.error(f"Не удалось уведомить о завершении строительства {user_id}: {e}")
        return True
    return False

# Функция для настройки команд меню
async def set_main_menu(bot: Bot):
    main_menu_commands = [
        BotCommand(command=command, description=description)
        for command, description in LEXICON_COMMANDS_RU.items()
    ]
    await bot.set_my_commands(main_menu_commands)


# ==============================================================================
# --- ФОНОВЫЕ ЗАДАЧИ (SCHEDULER) ---
# ==============================================================================
async def check_bonus_notifications():
    logging.info("Scheduler job 'check_bonus_notifications' running...")
    users_to_check = get_players_for_bonus_notification()
    now = int(time.time())
    for user_id, last_claim_timestamp in users_to_check:
        if (now - last_claim_timestamp) >= BONUS_COOLDOWN_SECONDS:
            try:
                await bot.send_message(user_id, LEXICON_RU['bonus_notification'], parse_mode=ParseMode.MARKDOWN)
                set_bonus_notification_sent(user_id)
                logging.info(f"Sent bonus notification to user {user_id}")
            except TelegramAPIError as e:
                if 'bot was blocked by the user' in e.message:
                    logging.warning(f"User {user_id} has blocked the bot. Cannot send notification.")
                else:
                    logging.error(f"Failed to send bonus notification to {user_id}: {e}")
            await asyncio.sleep(0.1)

# ==============================================================================
# --- КЛАВИАТУРЫ ---
# ==============================================================================
def get_main_menu_keyboard():
    builder = InlineKeyboardBuilder()
    builder.button(text="🏕️ Оперативная сводка", callback_data="show_base")
    builder.button(text="🎯 Цели для атаки", callback_data="show_targets")
    builder.button(text="🏭 Объекты и стройка", callback_data="show_buildings")
    builder.button(text="🛖 Подготовка войск", callback_data="show_barracks_training")
    builder.button(text="🏆 Зал славы", callback_data="show_rating")
    builder.button(text="🎁 Бонусный контейнер", callback_data="show_bonus_menu")
    builder.adjust(2, 2, 2)
    return builder.as_markup()


def get_buildings_menu_keyboard(player_buildings: dict):
    builder = InlineKeyboardBuilder()
    for bld_id, bld_info in BUILDINGS.items():
        level = player_buildings.get(bld_id, 0)
        builder.button(text=f"{bld_info['name']} (Ур. {level})", callback_data=f"view_building_{bld_id}")
    builder.button(text="↩️ Назад в штаб", callback_data="main_menu")
    builder.adjust(1)
    return builder.as_markup()


def get_admin_main_keyboard():
    builder = InlineKeyboardBuilder()
    builder.button(text="💰 Управление ресурсами", callback_data="admin_resources")
    builder.button(text="👨‍💻 Управление игроками", callback_data="admin_player_management")
    builder.button(text="📢 Глобальные объявления", callback_data="admin_broadcast")
    builder.adjust(1)
    return builder.as_markup()


def get_admin_resources_keyboard():
    builder = InlineKeyboardBuilder()
    builder.button(text="💰 Припасы", callback_data="admin_give_supplies")
    builder.button(text="↩️ Назад в админ-панель", callback_data="admin_main")
    builder.adjust(1)
    return builder.as_markup()

# ==============================================================================
# --- ОБРАБОТЧИКИ КОМАНД И ОСНОВНЫЕ МЕНЮ ---
# ==============================================================================

@dp.message(Command("start"))
async def cmd_start(message: types.Message, state: FSMContext):
    await state.clear()
    user_id = message.from_user.id

    if not player_exists(user_id):
        army_template = {'active': {'soldier': 0}, 'reserve': {'soldier': 0}}
        buildings_template = {'command_center': 1, 'barracks': 1, 'warehouse': 1}
        add_player(user_id, message.from_user.full_name, army_template, buildings_template)

        await message.answer(LEXICON_RU['welcome_1'].format(name=message.from_user.full_name), parse_mode=ParseMode.MARKDOWN)
        await asyncio.sleep(3)
        await message.answer(LEXICON_RU['welcome_2'], parse_mode=ParseMode.MARKDOWN)
        await asyncio.sleep(4)
        await message.answer(LEXICON_RU['welcome_3'], parse_mode=ParseMode.MARKDOWN)
        await asyncio.sleep(4)
        await message.answer(LEXICON_RU['welcome_4'], parse_mode=ParseMode.MARKDOWN)
    
    else:
        await check_and_complete_construction(user_id)
        await check_and_complete_training(user_id)
        await message.answer(LEXICON_RU['welcome_back'].format(name=message.from_user.full_name))

    player_data = get_player(user_id)
    if not player_data:
        logging.error(f"FATAL: Could not get or create player data for user {user_id}")
        return

    player_data = update_player_resources(player_data)
    update_player_data(user_id, player_data)

    await message.answer(LEXICON_RU['main_menu_text'], reply_markup=get_main_menu_keyboard())

@dp.message(Command("help"))
async def cmd_help(message: types.Message):
    await message.answer(LEXICON_RU['help_command_text'], parse_mode=ParseMode.MARKDOWN_V2)

@dp.message(Command("id"))
async def cmd_id(message: types.Message):
    await message.reply(f"Ваш Telegram ID: `{message.from_user.id}`", parse_mode=ParseMode.MARKDOWN_V2)

# ==============================================================================
# --- ЕЖЕДНЕВНЫЙ БОНУС ---
# ==============================================================================
async def process_bonus_claim(source: Union[types.Message, types.CallbackQuery]):
    user = source.from_user
    
    if isinstance(source, types.CallbackQuery):
        await source.answer()

    cooldown_seconds = get_bonus_cooldown(user.id)
    if cooldown_seconds:
        hours, remainder = divmod(cooldown_seconds, 3600)
        minutes, _ = divmod(remainder, 60)
        time_left = f"{int(hours)} ч {int(minutes)} мин"
        
        if isinstance(source, types.Message) and source.chat.type != 'private':
            try:
                await bot.send_message(user.id, LEXICON_RU['group_bonus_cooldown_pm'].format(time_left=time_left))
            except TelegramAPIError: pass 
        else:
            await bot.send_message(user.id, LEXICON_RU['bonus_cooldown'].format(time_left=time_left))
        return

    prizes = {
        'resources_S': {'chance': 35, 'type': 'resources', 'amount': 50},
        'soldiers_S': {'chance': 25, 'type': 'soldiers', 'amount': 1},
        'resources_M': {'chance': 20, 'type': 'resources', 'amount': 200},
        'soldiers_M': {'chance': 10, 'type': 'soldiers', 'amount': 5},
        'resources_L': {'chance': 6, 'type': 'resources', 'amount': 600},
        'soldiers_L': {'chance': 2.5, 'type': 'soldiers', 'amount': 15},
        'resources_XL': {'chance': 1, 'type': 'resources', 'amount': 2000},
        'soldiers_XL': {'chance': 0.5, 'type': 'soldiers', 'amount': 40},
    }
    
    prize_list = list(prizes.keys())
    weights = [p['chance'] for p in prizes.values()]
    chosen_prize_key = random.choices(prize_list, weights=weights, k=1)[0]
    chosen_prize = prizes[chosen_prize_key]
    
    if isinstance(source, types.Message) and source.chat.type != 'private':
        await source.reply(LEXICON_RU['group_bonus_claim_reply'].format(user_mention=user.mention_html()), parse_mode=ParseMode.HTML)

    try:
        msg_for_anim = await bot.send_message(user.id, LEXICON_RU['bonus_opening'].format(spinner="⢿"))
        spinners = ["⢿", "⣻", "⣽", "⣾", "⣷", "⣯", "⣟", "⡿"]
        for i in range(1, len(spinners) * 2):
            await asyncio.sleep(0.15)
            await msg_for_anim.edit_text(LEXICON_RU['bonus_opening'].format(spinner=spinners[i % len(spinners)]))
        
        player_data = get_player(user.id)
        if not player_data:
            return
            
        prize_text = ""
        if chosen_prize['type'] == 'resources':
            player_data['resources'] += chosen_prize['amount']
            prize_text = f"**{chosen_prize['amount']}** 💰"
        elif chosen_prize['type'] == 'soldiers':
            player_data['army']['reserve']['soldier'] = player_data['army']['reserve'].get('soldier', 0) + chosen_prize['amount']
            prize_text = f"**{chosen_prize['amount']}** 💂"
        
        update_player_data(user.id, player_data)
        set_bonus_claimed(user.id)

        await msg_for_anim.edit_text(LEXICON_RU['bonus_success'].format(prize_text=prize_text), parse_mode=ParseMode.MARKDOWN)

    except TelegramAPIError as e:
        logging.warning(f"Could not send bonus result to user {user.id}, likely blocked: {e}")

@dp.message(Command("bonus"))
async def cmd_bonus(message: types.Message):
    await process_bonus_claim(message)

@dp.message(F.text.lower() == '!контейнер')
async def text_cmd_bonus(message: types.Message):
    await process_bonus_claim(message)

@dp.callback_query(F.data == "show_bonus_menu")
async def cq_show_bonus_menu(callback: types.CallbackQuery):
    await callback.message.delete()
    await process_bonus_claim(callback)


# ==============================================================================
# --- АДМИН-ПАНЕЛЬ ---
# ==============================================================================
@dp.message(Command("admin"))
async def cmd_admin(message: types.Message, state: FSMContext):
    if message.from_user.id not in ADMIN_IDS:
        return
    await state.clear()
    await message.answer(LEXICON_RU['admin_panel_title'], reply_markup=get_admin_main_keyboard())


@dp.callback_query(F.data == "admin_main")
async def cq_admin_main_menu(callback: types.CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.edit_text(LEXICON_RU['admin_panel_title'], reply_markup=get_admin_main_keyboard())
    await callback.answer()

# --- Управление ресурсами ---
@dp.callback_query(F.data == "admin_resources")
async def cq_admin_resources(callback: types.CallbackQuery):
    await callback.message.edit_text(LEXICON_RU['admin_give_resources_title'], reply_markup=get_admin_resources_keyboard())
    await callback.answer()

@dp.callback_query(F.data.startswith("admin_give_"))
async def cq_admin_select_target_for_res(callback: types.CallbackQuery, state: FSMContext):
    await state.update_data(resource_to_give=callback.data.split("_")[2])
    await callback.message.edit_text(LEXICON_RU['admin_enter_target_id_prompt'])
    await state.set_state(AdminStates.waiting_for_target_id_for_resources)
    await callback.answer()

@dp.message(AdminStates.waiting_for_target_id_for_resources)
async def process_admin_target_id_for_res(message: types.Message, state: FSMContext):
    if not message.text.isdigit():
        await message.reply(LEXICON_RU['error_positive_number_required'])
        return
    if not player_exists(int(message.text)):
        await message.reply(LEXICON_RU['admin_player_not_found'])
        await state.clear()
        return
    await state.update_data(target_id=int(message.text))
    await message.reply(LEXICON_RU['admin_enter_amount_prompt'])
    await state.set_state(AdminStates.waiting_for_amount)

@dp.message(AdminStates.waiting_for_amount)
async def process_admin_amount(message: types.Message, state: FSMContext):
    try:
        amount = int(message.text)
    except ValueError:
        await message.reply("Количество должно быть числом.")
        return
    admin_data = await state.get_data()
    target_id = admin_data.get('target_id')
    target_player_data = get_player(target_id)
    if not target_player_data:
        await message.reply(LEXICON_RU['admin_player_not_found'])
        await state.clear()
        return
    target_player_data['resources'] += amount
    update_player_data(target_id, target_player_data)
    await message.reply(LEXICON_RU['admin_give_success'].format(
        amount=amount, name=target_player_data['name'], user_id=target_id
    ), reply_markup=InlineKeyboardBuilder().button(text="↩️ В админ-панель", callback_data="admin_main").as_markup())
    await state.clear()


# --- Рассылка ---
@dp.callback_query(F.data == "admin_broadcast")
async def cq_admin_broadcast(callback: types.CallbackQuery, state: FSMContext):
    await state.set_state(AdminStates.waiting_for_broadcast_message)
    await callback.message.edit_text(LEXICON_RU['admin_broadcast_prompt'])
    await callback.answer()

@dp.message(AdminStates.waiting_for_broadcast_message)
async def process_broadcast_message(message: types.Message, state: FSMContext):
    await state.clear()
    text = message.text
    user_ids = get_all_user_ids()
    await message.answer(LEXICON_RU['admin_broadcast_started'].format(user_count=len(user_ids)))
    success_count = 0
    for user_id in user_ids:
        try:
            await bot.send_message(user_id, text)
            success_count += 1
        except TelegramAPIError:
            pass
        await asyncio.sleep(0.1)
    await message.answer(LEXICON_RU['admin_broadcast_success'].format(
        success_count=success_count, fail_count=len(user_ids) - success_count
    ), reply_markup=InlineKeyboardBuilder().button(text="↩️ В админ-панель", callback_data="admin_main").as_markup())


# --- УПРАВЛЕНИЕ ИГРОКАМИ ---
@dp.callback_query(F.data == "admin_player_management")
async def cq_admin_player_management(callback: types.CallbackQuery, state: FSMContext):
    await state.clear()
    builder = InlineKeyboardBuilder()
    builder.button(text="ℹ️ Получить досье игрока", callback_data="admin_get_player_info")
    builder.button(text="↩️ Назад в админ-панель", callback_data="admin_main")
    builder.adjust(1)
    await callback.message.edit_text(LEXICON_RU['admin_player_management_title'], reply_markup=builder.as_markup())


@dp.callback_query(F.data == "admin_get_player_info")
async def cq_admin_get_player_info(callback: types.CallbackQuery, state: FSMContext):
    await state.set_state(AdminStates.waiting_for_player_id_for_info)
    await callback.message.edit_text(LEXICON_RU['admin_enter_player_id_for_info'])
    await callback.answer()


@dp.message(AdminStates.waiting_for_player_id_for_info)
async def process_player_id_for_info(message: types.Message, state: FSMContext):
    await state.clear()
    if not message.text.isdigit():
        await message.reply(LEXICON_RU['error_positive_number_required'])
        return
    
    target_id = int(message.text)
    player_data = get_player(target_id)
    if not player_data:
        await message.reply(LEXICON_RU['admin_player_not_found'])
        return
    
    dossier_text = LEXICON_RU['admin_player_dossier_title'].format(name=player_data['name'], user_id=target_id)
    dossier_text += f"\n\n**Ресурсы:** {int(player_data['resources'])} 💰\n\n"
    dossier_text += LEXICON_RU['dossier_stats'].format(attack_wins=player_data['attack_wins'], defense_wins=player_data['defense_wins']) + '\n\n'
    
    buildings = player_data['buildings']
    dossier_text += LEXICON_RU['dossier_buildings'].format(
        cc_level=buildings.get('command_center', 0),
        barracks_level=buildings.get('barracks', 0),
        warehouse_level=buildings.get('warehouse', 0)
    ) + '\n\n'
    
    army = player_data['army']
    dossier_text += LEXICON_RU['dossier_army'].format(
        active_army=army.get('active', {}).get('soldier', 0),
        reserve_army=army.get('reserve', {}).get('soldier', 0)
    ) + '\n\n'
    
    processes_text = ""
    construction_job = get_construction_queue(target_id)
    if construction_job:
        _, _, bld_id, finish_time = construction_job
        time_left = str(datetime.timedelta(seconds=max(0, int(finish_time - time.time()))))
        processes_text += '\n' + LEXICON_RU['dossier_process_construction'].format(
            building_name=BUILDINGS[bld_id]['name'],
            level=player_data['buildings'].get(bld_id, 0) + 1,
            time_left=time_left
        )
        
    training_job = get_training_queue(target_id)
    if training_job:
        _, unit_id, quantity, next_finish_time = training_job
        time_left = str(datetime.timedelta(seconds=max(0, int(next_finish_time - time.time()))))
        processes_text += '\n' + LEXICON_RU['dossier_process_training'].format(
            unit_name=UNITS[unit_id]['name'],
            quantity=quantity,
            time_left=time_left
        )
        
    cooldown_finish_time = get_attack_cooldown(target_id)
    if cooldown_finish_time:
        time_left = str(datetime.timedelta(seconds=max(0, int(cooldown_finish_time - time.time()))))
        processes_text += '\n' + LEXICON_RU['dossier_process_attack_cooldown'].format(time_left=time_left)

    if processes_text:
        dossier_text += LEXICON_RU['dossier_processes'] + processes_text
    else:
        dossier_text += LEXICON_RU['dossier_no_processes']
        
    await message.answer(dossier_text, parse_mode=ParseMode.MARKDOWN)


# ==============================================================================
# --- ОСНОВНЫЕ ИГРОВЫЕ ОБРАБОТЧИКИ ---
# ==============================================================================
@dp.callback_query(F.data == "main_menu")
async def cq_main_menu(callback: types.CallbackQuery, state: FSMContext):
    await state.clear()
    await check_and_complete_construction(callback.from_user.id)
    await check_and_complete_training(callback.from_user.id)
    try:
        await callback.message.edit_text(LEXICON_RU['main_menu_text'], reply_markup=get_main_menu_keyboard())
    except TelegramAPIError:
        await callback.message.answer(LEXICON_RU['main_menu_text'], reply_markup=get_main_menu_keyboard())
    await callback.answer()

@dp.callback_query(F.data == "show_base")
async def cq_show_base(callback: types.CallbackQuery, state: FSMContext):
    await state.clear()
    user_id = callback.from_user.id
    await check_and_complete_construction(user_id)
    await check_and_complete_training(user_id)
    player_data = get_player(user_id)
    if not player_data:
        await callback.answer(LEXICON_RU['error_player_data_not_found'], show_alert=True)
        return
    player_data = update_player_resources(player_data)
    update_player_data(user_id, player_data)
    
    warehouse_level = player_data['buildings'].get('warehouse', 1)
    capacity = WAREHOUSE_CAPACITY.get(warehouse_level, 1)
    
    text = LEXICON_RU['base_info_title'] + '\n\n' + LEXICON_RU['base_info_text'].format(
        capacity_bar=create_progress_bar(player_data['resources'], capacity),
        percent_full=int((player_data['resources'] / capacity) * 100) if capacity > 0 else 0,
        current_res=int(player_data['resources']),
        capacity_val=capacity,
        active_army=player_data['army'].get('active', {}).get('soldier', 0),
        reserve_army=player_data['army'].get('reserve', {}).get('soldier', 0)
    )
    
    processes_text = ""
    construction_job = get_construction_queue(user_id)
    if construction_job:
        _, _, bld_id, finish_time = construction_job
        time_left = str(datetime.timedelta(seconds=max(0, int(finish_time - time.time()))))
        processes_text += '\n' + LEXICON_RU['construction_in_progress'].format(
            building_name=BUILDINGS[bld_id]['name'],
            level=player_data['buildings'].get(bld_id, 0) + 1,
            time_left=time_left
        )
        
    training_job = get_training_queue(user_id)
    if training_job:
        _, unit_id, quantity, next_finish_time = training_job
        time_left = str(datetime.timedelta(seconds=max(0, int(next_finish_time - time.time()))))
        processes_text += ('\n' if processes_text else '') + LEXICON_RU['training_in_progress'].format(
            unit_name=UNITS[unit_id]['name'],
            quantity=quantity,
            time_left=time_left
        )
    
    if processes_text:
        text += LEXICON_RU['base_processes_title'] + processes_text

    builder = InlineKeyboardBuilder()
    builder.button(text="🗂️ Распределение сил", callback_data="manage_army")
    builder.button(text="↩️ Назад в штаб", callback_data="main_menu")
    builder.adjust(1)
    await callback.message.edit_text(text, parse_mode=ParseMode.MARKDOWN, reply_markup=builder.as_markup())
    await callback.answer()

@dp.callback_query(F.data == "manage_army")
async def cq_manage_army(callback: types.CallbackQuery, state: FSMContext):
    await show_army_management_menu(callback.from_user.id, state, message_to_edit=callback.message)
    
async def show_army_management_menu(user_id: int, state: FSMContext, message_to_edit: types.Message = None, message_to_answer: types.Message = None):
    await state.clear()
    player_data = get_player(user_id)
    if not player_data: return
    
    text = LEXICON_RU['army_management_title'].format(
        active_army=player_data['army']['active'].get('soldier', 0),
        reserve_army=player_data['army']['reserve'].get('soldier', 0)
    )
    builder = InlineKeyboardBuilder()
    builder.button(text="➡️ В гарнизон", callback_data="move_to_reserve")
    builder.button(text="⬅️ В штурмовой отряд", callback_data="move_to_active")
    builder.button(text="↩️ Назад", callback_data="show_base")
    builder.adjust(2, 1)

    if message_to_edit:
        try:
            await message_to_edit.edit_text(text, parse_mode=ParseMode.MARKDOWN, reply_markup=builder.as_markup())
        except TelegramAPIError: # Если сообщение не изменилось
             if message_to_answer:
                await message_to_answer.answer(text, parse_mode=ParseMode.MARKDOWN, reply_markup=builder.as_markup())
    elif message_to_answer:
         await message_to_answer.answer(text, parse_mode=ParseMode.MARKDOWN, reply_markup=builder.as_markup())
        
@dp.callback_query(F.data == "move_to_reserve")
async def cq_move_to_reserve(callback: types.CallbackQuery, state: FSMContext):
    await callback.message.edit_text(LEXICON_RU['move_to_reserve_prompt'])
    await state.set_state(ArmyManagementState.waiting_for_reserve_quantity)
    await callback.answer()

@dp.callback_query(F.data == "move_to_active")
async def cq_move_to_active(callback: types.CallbackQuery, state: FSMContext):
    await callback.message.edit_text(LEXICON_RU['move_to_active_prompt'])
    await state.set_state(ArmyManagementState.waiting_for_active_quantity)
    await callback.answer()

@dp.message(ArmyManagementState.waiting_for_reserve_quantity)
async def process_move_to_reserve(message: types.Message, state: FSMContext):
    if not message.text.isdigit() or int(message.text) <= 0:
        await message.reply(LEXICON_RU['error_positive_number_required'])
        return
    quantity = int(message.text)
    player_data = get_player(message.from_user.id)
    if not player_data: return
    active_army = player_data['army']['active'].get('soldier', 0)
    if quantity > active_army:
        await message.reply(LEXICON_RU['error_not_enough_units_in_active'].format(active_army=active_army))
        return
    player_data['army']['active']['soldier'] -= quantity
    player_data['army']['reserve']['soldier'] += quantity
    update_player_data(message.from_user.id, player_data)
    await message.reply(LEXICON_RU['move_to_reserve_success'].format(quantity=quantity))
    await show_army_management_menu(message.from_user.id, state, message_to_answer=message)

@dp.message(ArmyManagementState.waiting_for_active_quantity)
async def process_move_to_active(message: types.Message, state: FSMContext):
    if not message.text.isdigit() or int(message.text) <= 0:
        await message.reply(LEXICON_RU['error_positive_number_required'])
        return
    quantity = int(message.text)
    player_data = get_player(message.from_user.id)
    if not player_data: return
    reserve_army = player_data['army']['reserve'].get('soldier', 0)
    if quantity > reserve_army:
        await message.reply(LEXICON_RU['error_not_enough_units_in_reserve'].format(reserve_army=reserve_army))
        return
    player_data['army']['reserve']['soldier'] -= quantity
    player_data['army']['active']['soldier'] += quantity
    update_player_data(message.from_user.id, player_data)
    await message.reply(LEXICON_RU['move_to_active_success'].format(quantity=quantity))
    await show_army_management_menu(message.from_user.id, state, message_to_answer=message)

@dp.callback_query(F.data == "show_buildings")
async def cq_show_buildings_menu(callback: types.CallbackQuery):
    await check_and_complete_construction(callback.from_user.id)
    player_data = get_player(callback.from_user.id)
    if not player_data: return
    
    await callback.message.edit_text(LEXICON_RU['buildings_menu_title'], reply_markup=get_buildings_menu_keyboard(player_data['buildings']))
    await callback.answer()

@dp.callback_query(F.data.startswith("view_building_"))
async def cq_view_specific_building(callback: types.CallbackQuery, state: FSMContext):
    await state.clear()
    user_id = callback.from_user.id
    bld_id = callback.data.replace("view_building_", "")
    await check_and_complete_construction(user_id)
    player_data = get_player(user_id)
    if not player_data:
        await callback.answer(LEXICON_RU['error_player_data_not_found'], show_alert=True)
        return
    
    level = player_data['buildings'].get(bld_id, 0)
    bld_info = BUILDINGS[bld_id]

    text = LEXICON_RU['building_info'].format(
        building_name=bld_info['name'],
        level=level,
        description=bld_info['description']
    )

    if bld_id == 'command_center':
        production = BUILDINGS['command_center']['produces'] * level
        text += LEXICON_RU['building_info_command_center'].format(production=production)
    
    elif bld_id == 'warehouse':
        capacity = WAREHOUSE_CAPACITY.get(level, 0)
        protected = int(capacity * WAREHOUSE_PROTECTION_PERCENT)
        text += LEXICON_RU['building_info_warehouse'].format(capacity=capacity, protected=protected)

    elif bld_id == 'barracks':
        training_time = BARRACKS_TRAINING_TIME.get(level, "N/A")
        text += LEXICON_RU['building_info_barracks'].format(training_time=training_time)
    
    builder = InlineKeyboardBuilder()
    construction_job = get_construction_queue(user_id)
    
    if construction_job:
        text += f"\n\n{LEXICON_RU['builder_is_busy_long']}"
    else:
        if level < MAX_BUILDING_LEVEL:
            upgrade_cost = BUILDING_UPGRADE_COST.get(level + 1)
            upgrade_time_sec = BUILDING_UPGRADE_TIME.get(level + 1, 0)
            upgrade_time_str = str(datetime.timedelta(seconds=upgrade_time_sec))
            text += LEXICON_RU['upgrade_info'].format(
                next_level=level + 1,
                cost=upgrade_cost,
                build_time=upgrade_time_str
            )
            builder.button(text="✨ Улучшить", callback_data=f"upgrade_{bld_id}")
        else:
            text += f"\n\n{LEXICON_RU['max_level_reached']}"
    
    if bld_id == 'barracks':
        builder.button(text="💪 Подготовить войска", callback_data="show_barracks_training")
    
    builder.button(text="↩️ Назад к объектам", callback_data="show_buildings")
    builder.adjust(1)
    
    await callback.message.edit_text(text, parse_mode=ParseMode.MARKDOWN, reply_markup=builder.as_markup())
    await callback.answer()


@dp.callback_query(F.data.startswith("upgrade_"))
async def cq_upgrade_building(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    bld_id = callback.data.replace("upgrade_", "")
    if get_construction_queue(user_id):
        await callback.answer(LEXICON_RU['error_builder_busy'], show_alert=True)
        return
    player_data = get_player(user_id)
    if not player_data: return
    update_player_resources(player_data)
    level = player_data['buildings'].get(bld_id, 0)
    if level >= MAX_BUILDING_LEVEL:
        await callback.answer(LEXICON_RU['error_max_level_reached_alert'], show_alert=True)
        return
    cost = BUILDING_UPGRADE_COST.get(level + 1)
    if cost and player_data['resources'] >= cost:
        player_data['resources'] -= cost
        update_player_data(user_id, player_data)
        build_time_seconds = BUILDING_UPGRADE_TIME.get(level + 1, 0)
        finish_time = int(time.time() + build_time_seconds)
        add_to_construction_queue(user_id, bld_id, finish_time)
        await callback.answer(LEXICON_RU['upgrade_started'].format(building_name=BUILDINGS[bld_id]['name']))
        await cq_show_buildings_menu(callback)
    else:
        await callback.answer(LEXICON_RU['error_not_enough_resources_alert'], show_alert=True)

async def show_interactive_training_menu(callback: types.CallbackQuery, state: FSMContext, player_data: dict):
    state_data = await state.get_data()
    quantity_to_train = state_data.get('quantity_to_train', 1)
    unit_info = UNITS['soldier']
    unit_cost = unit_info['cost']
    max_can_train = int(player_data['resources'] / unit_cost) if unit_cost > 0 else 0
    if quantity_to_train > max_can_train: quantity_to_train = max_can_train
    if quantity_to_train < 1 and max_can_train > 0: quantity_to_train = 1
    elif max_can_train == 0: quantity_to_train = 0
    
    await state.update_data(quantity_to_train=quantity_to_train)
    total_cost = unit_cost * quantity_to_train
    text = (LEXICON_RU['training_menu_title'].format(unit_name=unit_info['name']) + '\n\n' +
            LEXICON_RU['training_menu_stats'].format(hp=unit_info['stats']['hp'], attack=unit_info['stats']['attack'], cargo=unit_info['stats']['cargo_capacity']) + '\n\n' +
            LEXICON_RU['training_production_info'].format(training_time=BARRACKS_TRAINING_TIME.get(player_data['buildings'].get('barracks', 1), 999), unit_cost=unit_cost) + '\n\n' +
            LEXICON_RU['training_possibilities'].format(resources=int(player_data['resources']), quantity_to_train=quantity_to_train, max_can_train=max_can_train, total_cost=total_cost))
    builder = InlineKeyboardBuilder()
    builder.button(text="-10", callback_data="train_sub_10"); builder.button(text="-1", callback_data="train_sub_1")
    builder.button(text="+1", callback_data="train_add_1"); builder.button(text="+10", callback_data="train_add_10")
    builder.button(text="Мин.", callback_data="train_set_1"); builder.button(text="Макс.", callback_data="train_set_max")
    builder.button(text=f"✅ Подтвердить ({quantity_to_train} шт.)", callback_data="train_confirm")
    builder.button(text="❌ Отмена", callback_data="main_menu")
    builder.adjust(4, 2, 1, 1)
    try:
        await callback.message.edit_text(text, parse_mode=ParseMode.MARKDOWN, reply_markup=builder.as_markup())
    except TelegramAPIError: pass
    await callback.answer()

@dp.callback_query(F.data == "show_barracks_training")
async def cq_start_training_session(callback: types.CallbackQuery, state: FSMContext):
    user_id = callback.from_user.id
    training_job = get_training_queue(user_id)
    if training_job:
        _, unit_id, quantity, next_finish_time = training_job
        time_left = str(datetime.timedelta(seconds=max(0, int(next_finish_time - time.time()))))
        text = LEXICON_RU['barracks_busy_status'].format(
            unit_name=UNITS[unit_id]['name'],
            quantity=quantity,
            time_left=time_left
        )
        builder = InlineKeyboardBuilder()
        builder.button(text="↩️ Назад в штаб", callback_data="main_menu")
        await callback.message.edit_text(text, reply_markup=builder.as_markup())
        await callback.answer()
        return
    player_data = get_player(user_id)
    if not player_data: return
    await state.set_state(TrainingState.selecting_quantity)
    await state.update_data(quantity_to_train=1)
    await show_interactive_training_menu(callback, state, player_data)

@dp.callback_query(TrainingState.selecting_quantity, F.data.startswith("train_"))
async def cq_adjust_training_quantity(callback: types.CallbackQuery, state: FSMContext):
    action = callback.data.split("_")[1]
    player_data = get_player(callback.from_user.id)
    state_data = await state.get_data()
    quantity = state_data.get('quantity_to_train', 1)
    max_can_train = int(player_data['resources'] / UNITS['soldier']['cost']) if UNITS['soldier']['cost'] > 0 else 0
    if action == "add": quantity += int(callback.data.split("_")[2])
    elif action == "sub": quantity -= int(callback.data.split("_")[2])
    elif action == "set": quantity = max_can_train if callback.data.split("_")[2] == "max" else 1
    elif action == "confirm":
        if quantity <= 0:
            await callback.answer("Не выбрано ни одного юнита для тренировки.", show_alert=True)
            return
        total_cost = UNITS['soldier']['cost'] * quantity
        if player_data['resources'] < total_cost:
            await callback.answer(LEXICON_RU['error_not_enough_resources_alert'], show_alert=True)
            return
        player_data['resources'] -= total_cost
        update_player_data(callback.from_user.id, player_data)
        barracks_level = player_data['buildings'].get('barracks', 1)
        training_time_per_unit = BARRACKS_TRAINING_TIME.get(barracks_level, 999)
        next_finish_time = int(time.time() + training_time_per_unit)
        add_to_training_queue(callback.from_user.id, 'soldier', quantity, next_finish_time)
        await state.clear()
        await callback.message.edit_text(
            LEXICON_RU['training_started'],
            reply_markup=InlineKeyboardBuilder().button(text="🏕️ Перейти на базу", callback_data="show_base").as_markup())
        return
    await state.update_data(quantity_to_train=quantity)
    await show_interactive_training_menu(callback, state, player_data)

@dp.callback_query(F.data == "show_rating")
async def cq_show_rating(callback: types.CallbackQuery):
    builder = InlineKeyboardBuilder()
    builder.button(text="🎖️ Легендарные полководцы", callback_data="rating_power")
    builder.button(text="⚔️ Великие завоеватели", callback_data="rating_attack_wins")
    builder.button(text="🛡️ Неприступные крепости", callback_data="rating_defense_wins")
    builder.button(text="💰 Военные магнаты", callback_data="rating_resources")
    builder.button(text="↩️ Назад в штаб", callback_data="main_menu")
    builder.adjust(1)
    await callback.message.edit_text(LEXICON_RU['rating_menu_title'], parse_mode=ParseMode.MARKDOWN, reply_markup=builder.as_markup())
    await callback.answer()

@dp.callback_query(F.data.startswith("rating_"))
async def cq_show_specific_rating(callback: types.CallbackQuery):
    category = callback.data.replace("rating_", "")
    medals = ["🥇", "🥈", "🥉"]
    rating_text = ""
    titles = {"power": LEXICON_RU['rating_power_title'],"attack_wins": LEXICON_RU['rating_attack_wins_title'],"defense_wins": LEXICON_RU['rating_defense_wins_title'],"resources": LEXICON_RU['rating_resources_title']}
    rating_text += titles[category]
    if category == "power":
        power_ratings = sorted(
            [{'name': name, 'power': (json.loads(army).get('active', {}).get('soldier', 0) + json.loads(army).get('reserve', {}).get('soldier', 0)) * (UNITS['soldier']['stats']['hp'] + UNITS['soldier']['stats']['attack'])} 
             for name, army in get_all_players_for_power_rating()], 
            key=lambda x: x['power'], reverse=True)[:3]
        if not power_ratings: rating_text += LEXICON_RU['rating_no_players']
        else:
            for i, player in enumerate(power_ratings):
                rating_text += LEXICON_RU['rating_line'].format(medal=medals[i], rank=i + 1, name=player['name'], metric="Мощь", value=player['power'])
    else:
        metrics = {"attack_wins": "Побед в атаке", "defense_wins": "Побед в защите", "resources": "Припасы"}
        top_players = get_top_players(category)
        if not top_players: rating_text += LEXICON_RU['rating_no_players']
        else:
            for i, (name, value) in enumerate(top_players):
                rating_text += LEXICON_RU['rating_line'].format(medal=medals[i], rank=i + 1, name=name, metric=metrics[category], value=int(value))
    builder = InlineKeyboardBuilder().button(text="↩️ Назад к Залу славы", callback_data="show_rating")
    await callback.message.edit_text(rating_text, parse_mode=ParseMode.MARKDOWN, reply_markup=builder.as_markup())
    await callback.answer()

@dp.callback_query(F.data == "show_targets")
async def cq_show_targets(callback: types.CallbackQuery):
    cooldown_finish_time = get_attack_cooldown(callback.from_user.id)
    if cooldown_finish_time:
        remaining_seconds = max(0, int(cooldown_finish_time - time.time()))
        minutes, seconds = divmod(remaining_seconds, 60)
        await callback.answer(LEXICON_RU['attack_cooldown'].format(time_left=f"{minutes:02d}:{seconds:02d}"), show_alert=True)
        return
    targets = get_all_players_for_attack(callback.from_user.id)
    if not targets:
        await callback.message.edit_text(LEXICON_RU['no_targets_available'], reply_markup=InlineKeyboardBuilder().button(text="↩️ Назад в штаб", callback_data="main_menu").as_markup())
        return
        
    builder = InlineKeyboardBuilder()
    for t_id, name in targets:
        builder.button(text=f"🎯 {name}", callback_data=f"attack_{t_id}")
    builder.button(text="📡 Обновить данные", callback_data="show_targets")
    builder.button(text="↩️ Назад в штаб", callback_data="main_menu")
    builder.adjust(1)
    await callback.message.edit_text(LEXICON_RU['select_target'], reply_markup=builder.as_markup())

@dp.callback_query(F.data.startswith("attack_"))
async def cq_attack_player(callback: types.CallbackQuery, state: FSMContext):
    await callback.answer("Симуляция боя...")
    try:
        await state.clear()
        attacker_id, defender_id = callback.from_user.id, int(callback.data.split("_")[1])
        if get_attack_cooldown(attacker_id):
            await callback.answer(LEXICON_RU['error_attack_on_cooldown_alert'], show_alert=True)
            return
        attacker_data, defender_data = get_player(attacker_id), get_player(defender_id)
        if not attacker_data or not defender_data: return
        a_initial_army = attacker_data['army']['active'].get('soldier', 0)
        if a_initial_army == 0:
            await callback.answer(LEXICON_RU['error_no_army_to_attack_alert'], show_alert=True)
            return
        d_initial_army = defender_data['army']['active'].get('soldier', 0)
        s_stats = UNITS['soldier']['stats']
        if d_initial_army == 0:
            attacker_data['attack_wins'] += 1
            warehouse_level = defender_data['buildings'].get('warehouse', 1)
            capacity = WAREHOUSE_CAPACITY.get(warehouse_level, 0)
            protected_resources = capacity * WAREHOUSE_PROTECTION_PERCENT
            available_for_looting = max(0, defender_data['resources'] - protected_resources)
            cargo_capacity = a_initial_army * s_stats['cargo_capacity']
            looted_resources = min(available_for_looting, cargo_capacity)
            attacker_data['resources'] += looted_resources
            defender_data['resources'] -= looted_resources
            update_player_data(defender_id, defender_data)
            update_player_data(attacker_id, attacker_data)
            report_text = LEXICON_RU['defenseless_attack_report'].format(target_name=defender_data['name'], looted_resources=int(looted_resources))
            await callback.message.edit_text(report_text, parse_mode=ParseMode.MARKDOWN, reply_markup=InlineKeyboardBuilder().button(text="↩️ В штаб", callback_data="main_menu").as_markup())
            report_id = add_battle_report(defender_id, report_text)
            set_attack_cooldown(attacker_id, int(time.time() + ATTACK_COOLDOWN_SECONDS))
            try:
                await bot.send_message(defender_id, LEXICON_RU['attack_notification'], reply_markup=InlineKeyboardBuilder().button(text="👁️ Посмотреть отчет", callback_data=f"view_report_{report_id}").as_markup())
            except TelegramAPIError as e:
                logging.error(f"Не удалось отправить уведомление защитнику {defender_id}: {e}")
            return
            
        luck_modifier = random.uniform(-LUCK_MODIFIER_RANGE, LUCK_MODIFIER_RANGE)
        a_total_damage = a_initial_army * s_stats['attack'] * (1 + luck_modifier)
        defender_losses = min(d_initial_army, round(a_total_damage / s_stats['hp']))
        d_survivors = d_initial_army - defender_losses
        d_total_damage = d_survivors * s_stats['attack']
        attacker_losses = min(a_initial_army, round(d_total_damage / s_stats['hp']))
        a_survivors = a_initial_army - attacker_losses
        is_attacker_win = attacker_losses < defender_losses
        if is_attacker_win: attacker_data['attack_wins'] += 1
        else: defender_data['defense_wins'] += 1
        looted_resources = 0
        if is_attacker_win:
            warehouse_level = defender_data['buildings'].get('warehouse', 1)
            capacity = WAREHOUSE_CAPACITY.get(warehouse_level, 0)
            protected_resources = capacity * WAREHOUSE_PROTECTION_PERCENT
            available_for_looting = max(0, defender_data['resources'] - protected_resources)
            cargo_capacity = a_survivors * s_stats['cargo_capacity']
            looted_resources = min(available_for_looting, cargo_capacity)
            attacker_data['resources'] += looted_resources
            defender_data['resources'] -= looted_resources
            
        attacker_data['army']['active']['soldier'] = a_survivors
        defender_data['army']['active']['soldier'] = d_survivors
        update_player_data(attacker_id, attacker_data)
        update_player_data(defender_id, defender_data)
        
        now_str = datetime.datetime.now().strftime('%d.%m.%Y %H:%M')
        
        attacker_report = (LEXICON_RU['battle_report_title'] + '\n' + 
            LEXICON_RU['battle_report_header'].format(operation_type="Нападение", target_name=defender_data['name'], datetime=now_str, luck_modifier=luck_modifier, result="ПОБЕДА") +
            LEXICON_RU['battle_report_loot'].format(looted_resources=int(looted_resources)) +
            LEXICON_RU['battle_report_attacker_stats'].format(attacker_name=attacker_data['name'], losses=attacker_losses, initial=a_initial_army, loss_percent=round(attacker_losses / a_initial_army * 100 if a_initial_army > 0 else 0)) +
            LEXICON_RU['battle_report_defender_stats'].format(defender_name=defender_data['name'], losses=defender_losses, initial=d_initial_army, loss_percent=round(defender_losses / d_initial_army * 100 if d_initial_army > 0 else 0)))
        
        defender_report = (LEXICON_RU['battle_report_title'] + '\n' + 
            LEXICON_RU['battle_report_header'].format(operation_type="Оборона", target_name=attacker_data['name'], datetime=now_str, luck_modifier=luck_modifier, result="ПОРАЖЕНИЕ") +
            LEXICON_RU['battle_report_defender_stats'].format(defender_name=defender_data['name'], losses=defender_losses, initial=d_initial_army, loss_percent=round(defender_losses / d_initial_army * 100 if d_initial_army > 0 else 0)) +
            LEXICON_RU['battle_report_attacker_stats'].format(attacker_name=attacker_data['name'], losses=attacker_losses, initial=a_initial_army, loss_percent=round(attacker_losses / a_initial_army * 100 if a_initial_army > 0 else 0)))

        await callback.message.edit_text(attacker_report, parse_mode=ParseMode.MARKDOWN, reply_markup=InlineKeyboardBuilder().button(text="↩️ В штаб", callback_data="main_menu").as_markup())
        report_id = add_battle_report(defender_id, defender_report)
        set_attack_cooldown(attacker_id, int(time.time() + ATTACK_COOLDOWN_SECONDS))
        try:
            await bot.send_message(defender_id, LEXICON_RU['attack_notification'], reply_markup=InlineKeyboardBuilder().button(text="👁️ Посмотреть отчет", callback_data=f"view_report_{report_id}").as_markup())
        except TelegramAPIError as e:
            logging.error(f"Не удалось отправить уведомление защитнику {defender_id}: {e}")
            
    except Exception as e:
        logging.error(f"КРИТИЧЕСКАЯ ОШИБКА В БОЮ: {e}", exc_info=True)
        await callback.message.edit_text(LEXICON_RU['critical_battle_error'], reply_markup=InlineKeyboardBuilder().button(text="↩️ В штаб", callback_data="main_menu").as_markup())

@dp.callback_query(F.data.startswith("view_report_"))
async def cq_view_report(callback: types.CallbackQuery):
    report_id = int(callback.data.split("_")[2])
    report_text = get_battle_report(report_id)
    if report_text:
        await callback.message.answer(report_text, parse_mode=ParseMode.MARKDOWN)
        await callback.answer()
    else:
        await callback.answer("Отчет не найден.", show_alert=True)
# ==============================================================================
# --- ОСНОВНАЯ ФУНКЦИЯ ---
# ==============================================================================
async def main():
    init_db()
    await set_main_menu(bot)
    
    scheduler.add_job(check_bonus_notifications, 'interval', minutes=15)
    scheduler.start()

    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        scheduler.shutdown()
        logging.info("Бот и планировщик остановлены.")
