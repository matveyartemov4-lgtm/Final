import telebot
from telebot import types
import requests
import random
import time
import threading
import sys
import os
import signal
import logging
from logging.handlers import RotatingFileHandler
import socket
import json

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        RotatingFileHandler('bot.log', maxBytes=10485760, backupCount=5, encoding='utf-8'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# Твой токен Telegram-бота
TOKEN = '8932397702:AAGApXMJ2mmqYRD9PrC0KyUwx0JPPr5phd4'

# Проверка токена
if not TOKEN or TOKEN == 'YOUR_TOKEN_HERE':
    logger.error("Токен не настроен! Установите переменную окружения TELEGRAM_BOT_TOKEN")
    sys.exit(1)

# Создание бота с увеличенным таймаутом
bot = telebot.TeleBot(
    TOKEN,
    threaded=True,
    num_threads=4,
    skip_pending=True
)

# База данных состояний пользователей (потокобезопасная)
import threading
user_states_lock = threading.Lock()
user_states = {}

# Наборы символов для генерации
LETTERS = "abcdefghijklmnopqrstuvwxyz"
DIGITS = "0123456789"
VOWELS = "aeiouy"
CONSONANTS = "bcdfghjklmnpqrstvwxz"

# Список User-Agent для обхода блокировок
USER_AGENTS = [
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/114.0.0.0 Safari/537.36',
    'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/113.0.0.0 Safari/537.36',
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:109.0) Gecko/20100101 Firefox/113.0',
    'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/112.0.0.0 Safari/537.36',
    'Mozilla/5.0 (iPhone; CPU iPhone OS 16_5 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.5 Mobile/15E148 Safari/604.1',
    'Mozilla/5.0 (iPad; CPU OS 16_5 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.5 Mobile/15E148 Safari/604.1'
]

# Сессия requests с повторными попытками
from requests.adapters import HTTPAdapter
from requests.packages.urllib3.util.retry import Retry

def create_session():
    session = requests.Session()
    retry = Retry(
        total=3,
        backoff_factor=0.5,
        status_forcelist=[429, 500, 502, 503, 504]
    )
    adapter = HTTPAdapter(max_retries=retry, pool_connections=10, pool_maxsize=10)
    session.mount('http://', adapter)
    session.mount('https://', adapter)
    return session

session = create_session()

def check_username(username):
    """
    Проверяет доступность юзернейма с повторными попытками
    """
    if not username or len(username) < 5:
        return False
    
    for attempt in range(3):
        try:
            headers = {
                'User-Agent': random.choice(USER_AGENTS),
                'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
                'Accept-Language': 'en-US,en;q=0.5',
                'Accept-Encoding': 'gzip, deflate',
                'Connection': 'keep-alive',
                'Upgrade-Insecure-Requests': '1'
            }
            url = f"https://t.me/{username}"
            response = session.get(url, headers=headers, timeout=10)
            
            # Проверяем различные признаки недоступности
            if response.status_code == 200:
                if "tgme_page_title" not in response.text and "tgme_page" not in response.text:
                    return True
                if "If you have Telegram" in response.text:
                    return True
                    
            # Если аккаунт не существует, обычно редирект или 404
            if response.status_code == 302 or response.status_code == 404:
                return True
                
            time.sleep(0.5)  # Пауза между попытками
            
        except requests.exceptions.Timeout:
            logger.warning(f"Таймаут при проверке @{username} (попытка {attempt+1})")
            time.sleep(1)
        except requests.exceptions.RequestException as e:
            logger.warning(f"Ошибка сети при проверке @{username}: {e}")
            time.sleep(1)
        except Exception as e:
            logger.error(f"Неизвестная ошибка при проверке @{username}: {e}")
            time.sleep(1)
    
    return False

def save_found_username(username, chat_id=None):
    """
    Сохраняет найденный юзернейм в файл и логи
    """
    try:
        # Сохраняем в общий файл
        with open('found_usernames.txt', 'a', encoding='utf-8') as f:
            f.write(f"@{username}\n")
        
        # Логируем с информацией о чате
        if chat_id:
            logger.info(f"Найден свободный юзернейм: @{username} (чат: {chat_id})")
        else:
            logger.info(f"Найден свободный юзернейм: @{username}")
            
        return True
    except IOError as e:
        logger.error(f"Ошибка сохранения @{username}: {e}")
        return False
    except Exception as e:
        logger.error(f"Неизвестная ошибка сохранения: {e}")
        return False

# --- КЛАВИАТУРЫ ---

def get_main_keyboard():
    """Создает главное меню"""
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=1)
    markup.add(
        types.KeyboardButton("📖 Искать по словарю (words.txt)"),
        types.KeyboardButton("🎲 Генератор ников (5-7 символов)"),
        types.KeyboardButton("ℹ️ Статистика")
    )
    return markup

def get_length_keyboard():
    """Клавиатура выбора длины"""
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=3)
    markup.add(
        types.KeyboardButton("📏 5 символов"), 
        types.KeyboardButton("📏 6 символов"), 
        types.KeyboardButton("📏 7 символов")
    )
    markup.add(types.KeyboardButton("⬅️ Главное меню"))
    return markup

def get_type_keyboard():
    """Клавиатура выбора типа генерации"""
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    markup.add(
        types.KeyboardButton("🔤 Только буквы"), 
        types.KeyboardButton("🔢 Буквы и цифры"),
        types.KeyboardButton("🗣 Читаемые ники")
    )
    markup.add(types.KeyboardButton("⬅️ Главное меню"))
    return markup

def get_stop_keyboard():
    """Клавиатура для остановки поиска"""
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
    markup.add(types.KeyboardButton("🛑 Остановить поиск"))
    return markup

# --- ФОНОВЫЙ ПОТОК (ОБРАБАТЫВАЕТ СЛОВАРЬ И ВСЕ ВИДЫ ГЕНЕРАТОРОВ) ---

def search_worker(chat_id):
    """
    Фоновый поток для поиска юзернеймов
    """
    state = None
    with user_states_lock:
        state = user_states.get(chat_id, {}).copy()
    
    if not state:
        logger.error(f"Нет состояния для чата {chat_id}")
        return
    
    mode = state.get('mode')
    logger.info(f"Запуск поиска для чата {chat_id}, режим: {mode}")
    
    try:
        # Уведомляем о начале поиска
        bot.send_message(
            chat_id,
            "🔍 Поиск запущен! Свободные юзернеймы будут появляться здесь.\n"
            "Для остановки нажмите кнопку ниже.",
            reply_markup=get_stop_keyboard()
        )
        
        found_count = 0
        checked_count = 0
        last_update_time = time.time()
        
        # РЕЖИМ 1: ПОИСК ПО СЛОВАРЮ
        if mode == 'dictionary':
            try:
                with open('words.txt', 'r', encoding='utf-8') as f:
                    words = f.readlines()
                
                logger.info(f"Загружено {len(words)} слов из словаря")
                
                for line in words:
                    # Проверяем, не остановлен ли поиск
                    with user_states_lock:
                        if not user_states.get(chat_id, {}).get('searching', False):
                            break
                    
                    word = line.strip().lower()
                    if len(word) >= 5:
                        checked_count += 1
                        
                        # Отправляем статус каждые 30 секунд
                        if time.time() - last_update_time > 30:
                            try:
                                bot.send_message(
                                    chat_id,
                                    f"📊 Статус: проверено {checked_count}, найдено {found_count}",
                                    reply_markup=get_stop_keyboard()
                                )
                                last_update_time = time.time()
                            except:
                                pass
                        
                        if check_username(word):
                            found_count += 1
                            try:
                                bot.send_message(chat_id, f"🔥 СВОБОДЕН ИЗ СЛОВАРЯ: @{word}")
                                save_found_username(word, chat_id)
                            except Exception as e:
                                logger.error(f"Ошибка отправки сообщения: {e}")
                                break
                        
                        time.sleep(2.5)
                
                # Завершение поиска
                with user_states_lock:
                    if chat_id in user_states:
                        user_states[chat_id]['searching'] = False
                
                summary = (
                    f"🏁 Проверка словаря завершена!\n"
                    f"📊 Всего проверено: {checked_count}\n"
                    f"✅ Найдено свободных: {found_count}"
                )
                bot.send_message(chat_id, summary, reply_markup=get_main_keyboard())
                
            except FileNotFoundError:
                bot.send_message(chat_id, "❌ Файл words.txt не найден!", reply_markup=get_main_keyboard())
            except Exception as e:
                logger.error(f"Ошибка в режиме словаря: {e}")
                bot.send_message(chat_id, f"❌ Произошла ошибка: {str(e)}", reply_markup=get_main_keyboard())
        
        # РЕЖИМ 2: ГЕНЕРАТОР
        elif mode == 'generator':
            logger.info(f"Запуск генератора с параметрами: {state}")
            
            while True:
                # Проверяем, не остановлен ли поиск
                with user_states_lock:
                    if not user_states.get(chat_id, {}).get('searching', False):
                        break
                
                try:
                    length = state['length']
                    with_digits = state.get('with_digits', False)
                    is_readable = state.get('readable', False)
                    
                    # Генерация юзернейма
                    if is_readable:
                        username = generate_readable_username(length)
                    else:
                        username = generate_random_username(length, with_digits)
                    
                    checked_count += 1
                    
                    # Обновление статуса
                    if time.time() - last_update_time > 30:
                        try:
                            bot.send_message(
                                chat_id,
                                f"📊 Статус: проверено {checked_count}, найдено {found_count}",
                                reply_markup=get_stop_keyboard()
                            )
                            last_update_time = time.time()
                        except:
                            pass
                    
                    # Проверка доступности
                    if check_username(username):
                        found_count += 1
                        try:
                            bot.send_message(chat_id, f"🔥 СВОБОДЕН: @{username}")
                            save_found_username(username, chat_id)
                        except Exception as e:
                            logger.error(f"Ошибка отправки: {e}")
                            break
                    
                    time.sleep(2.5)
                    
                except Exception as e:
                    logger.error(f"Ошибка в цикле генератора: {e}")
                    time.sleep(5)
            
            # Завершение
            with user_states_lock:
                if chat_id in user_states:
                    user_states[chat_id]['searching'] = False
            
            summary = (
                f"🏁 Генерация завершена!\n"
                f"📊 Проверено комбинаций: {checked_count}\n"
                f"✅ Найдено свободных: {found_count}"
            )
            bot.send_message(chat_id, summary, reply_markup=get_main_keyboard())
    
    except Exception as e:
        logger.error(f"Критическая ошибка в search_worker: {e}")
        try:
            bot.send_message(chat_id, f"❌ Критическая ошибка: {str(e)}", reply_markup=get_main_keyboard())
        except:
            pass
        with user_states_lock:
            if chat_id in user_states:
                user_states[chat_id]['searching'] = False

def generate_readable_username(length):
    """Генерирует читаемый юзернейм с чередованием гласных/согласных"""
    username = ""
    is_vowel_next = random.choice([True, False])
    
    for _ in range(length):
        if is_vowel_next:
            username += random.choice(VOWELS)
        else:
            username += random.choice(CONSONANTS)
        is_vowel_next = not is_vowel_next
    
    return username

def generate_random_username(length, with_digits=False):
    """Генерирует случайный юзернейм"""
    first_char = random.choice(LETTERS)
    pool = LETTERS + (DIGITS if with_digits else "")
    remaining_chars = "".join(random.choice(pool) for _ in range(length - 1))
    return first_char + remaining_chars

# --- ОБРАБОТЧИКИ КОМАНД ---

@bot.message_handler(commands=['start', 'menu'])
def start_command(message):
    """Обработчик команды /start"""
    chat_id = message.chat.id
    
    with user_states_lock:
        if chat_id in user_states:
            user_states[chat_id]['searching'] = False
        user_states[chat_id] = {
            'mode': None,
            'length': 5,
            'with_digits': False,
            'readable': False,
            'searching': False
        }
    
    welcome_text = (
        "👋 Привет! Я профессиональный радар юзернеймов Telegram.\n\n"
        "🎯 Мои возможности:\n"
        "• Поиск по словарю (words.txt)\n"
        "• Генерация случайных ников\n"
        "• Генерация читаемых ников\n\n"
        "Выберите режим работы:"
    )
    
    bot.send_message(chat_id, welcome_text, reply_markup=get_main_keyboard())

@bot.message_handler(commands=['stats'])
def stats_command(message):
    """Показывает статистику"""
    chat_id = message.chat.id
    
    try:
        with open('found_usernames.txt', 'r', encoding='utf-8') as f:
            found = f.readlines()
    except FileNotFoundError:
        found = []
    
    stats_text = (
        f"📊 Статистика бота:\n"
        f"✅ Всего найдено: {len(found)} юзернеймов\n"
        f"👥 Активных пользователей: {len(user_states)}\n"
        f"💾 Файл: found_usernames.txt"
    )
    
    bot.send_message(chat_id, stats_text)

@bot.message_handler(content_types=['text'])
def handle_buttons(message):
    """Основной обработчик текстовых сообщений"""
    chat_id = message.chat.id
    text = message.text
    
    # Инициализация состояния
    with user_states_lock:
        if chat_id not in user_states:
            user_states[chat_id] = {
                'mode': None,
                'length': 5,
                'with_digits': False,
                'readable': False,
                'searching': False
            }
    
    try:
        # ГЛАВНОЕ МЕНЮ
        if text == "📖 Искать по словарю (words.txt)":
            with user_states_lock:
                if user_states[chat_id]['searching']:
                    bot.send_message(chat_id, "❌ Сначала остановите текущий поиск!")
                    return
                
                user_states[chat_id]['mode'] = 'dictionary'
                user_states[chat_id]['searching'] = True
            
            bot.send_message(
                chat_id,
                "🚀 Запускаю проверку по словарю words.txt!\n"
                "Найденные свободные ники будут появляться здесь.",
                reply_markup=get_stop_keyboard()
            )
            
            thread = threading.Thread(target=search_worker, args=(chat_id,), daemon=True)
            thread.start()
        
        elif text == "🎲 Генератор ников (5-7 символов)":
            bot.send_message(chat_id, "📏 Выберите желаемую длину юзернейма:", reply_markup=get_length_keyboard())
        
        elif text == "ℹ️ Статистика":
            stats_command(message)
        
        # ВЫБОР ДЛИНЫ
        elif text in ["📏 5 символов", "📏 6 символов", "📏 7 символов"]:
            length = int(text.split()[1])
            with user_states_lock:
                user_states[chat_id]['length'] = length
            bot.send_message(
                chat_id,
                f"Длина: {length} символов.\nТеперь выберите формат:",
                reply_markup=get_type_keyboard()
            )
        
        # ВЫБОР ТИПА ГЕНЕРАЦИИ
        elif text in ["🔤 Только буквы", "🔢 Буквы и цифры", "🗣 Читаемые ники"]:
            with user_states_lock:
                if user_states[chat_id]['searching']:
                    bot.send_message(chat_id, "❌ Поиск уже запущен!")
                    return
                
                user_states[chat_id]['mode'] = 'generator'
                user_states[chat_id]['with_digits'] = (text == "🔢 Буквы и цифры")
                user_states[chat_id]['readable'] = (text == "🗣 Читаемые ники")
                user_states[chat_id]['searching'] = True
                state = user_states[chat_id].copy()
            
            # Формируем описание режима
            if state['readable']:
                fmt_desc = "Читаемые (чередование гласных/согласных)"
            elif state['with_digits']:
                fmt_desc = "Случайные буквы + цифры"
            else:
                fmt_desc = "Только случайные буквы"
            
            bot.send_message(
                chat_id,
                f"🚀 Генератор запущен!\n"
                f"📏 Длина: {state['length']} символов\n"
                f"🔤 Формат: {fmt_desc}\n\n"
                f"Для остановки нажмите кнопку ниже 👇",
                reply_markup=get_stop_keyboard()
            )
            
            thread = threading.Thread(target=search_worker, args=(chat_id,), daemon=True)
            thread.start()
        
        # УПРАВЛЕНИЕ
        elif text == "🛑 Остановить поиск":
            with user_states_lock:
                was_searching = user_states[chat_id].get('searching', False)
                user_states[chat_id]['searching'] = False
            
            if was_searching:
                bot.send_message(chat_id, "🛑 Поиск остановлен.", reply_markup=get_main_keyboard())
            else:
                bot.send_message(chat_id, "ℹ️ Поиск не был запущен.", reply_markup=get_main_keyboard())
        
        elif text == "⬅️ Главное меню":
            with user_states_lock:
                user_states[chat_id]['searching'] = False
            bot.send_message(chat_id, "📍 Главное меню:", reply_markup=get_main_keyboard())
        
        else:
            # Неизвестная команда
            bot.send_message(
                chat_id,
                "🤔 Неизвестная команда. Используйте кнопки меню.",
                reply_markup=get_main_keyboard()
            )
    
    except Exception as e:
        logger.error(f"Ошибка в обработчике для чата {chat_id}: {e}")
        try:
            bot.send_message(chat_id, "❌ Произошла ошибка. Попробуйте снова.", reply_markup=get_main_keyboard())
        except:
            pass

# --- ОБРАБОТЧИК ОШИБОК POLLING ---

def handle_polling_error(exc):
    """Обработчик ошибок polling"""
    logger.error(f"Polling er
