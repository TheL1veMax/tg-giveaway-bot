#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import logging
import random
import sqlite3
from datetime import datetime, timedelta
import os
import hashlib

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Updater,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    CallbackContext,
    Filters
)
from telegram.parsemode import ParseMode

# ================== НАСТРОЙКИ ==================
BOT_TOKEN = os.getenv('BOT_TOKEN', '8458068573:AAHaKHcWQZOOmTu-z2wu-7kbX8MdhonkS_M')
ADMIN_IDS = [5207853162, 5406117718]
CHANNEL_ID = "@sportgagarinmolodezh"

# Логирование
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# ================== БАЗА ДАННЫХ ==================
class Database:
    def __init__(self, db_name='giveaway.db'):
        self.conn = sqlite3.connect(db_name, check_same_thread=False)
        self.cursor = self.conn.cursor()
        self.create_tables()
        logger.info("Database initialized")

    def create_tables(self):
        """Создание таблиц"""

        # Пользователи
        self.cursor.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                username TEXT,
                first_name TEXT,
                last_name TEXT,
                joined_date TEXT NOT NULL,
                is_verified INTEGER DEFAULT 0 NOT NULL,
                verification_date TEXT,
                verification_method TEXT,
                is_banned INTEGER DEFAULT 0 NOT NULL,
                ban_reason TEXT,
                banned_date TEXT,
                ip_hash TEXT,
                last_activity TEXT,
                verification_attempts INTEGER DEFAULT 0
            )
        """)

        # История верификаций
        self.cursor.execute("""
            CREATE TABLE IF NOT EXISTS verification_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                verification_type TEXT NOT NULL,
                success INTEGER NOT NULL,
                attempt_date TEXT NOT NULL,
                ip_hash TEXT
            )
        """)

        # Баны
        self.cursor.execute("""
            CREATE TABLE IF NOT EXISTS ban_list (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                admin_id INTEGER,
                reason TEXT,
                ban_date TEXT NOT NULL,
                unban_date TEXT
            )
        """)

        # IP адреса
        self.cursor.execute("""
            CREATE TABLE IF NOT EXISTS ip_addresses (
                ip_hash TEXT PRIMARY KEY,
                user_count INTEGER DEFAULT 1,
                first_seen TEXT NOT NULL,
                last_seen TEXT NOT NULL
            )
        """)

        # Розыгрыши
        self.cursor.execute("""
            CREATE TABLE IF NOT EXISTS giveaways (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                description TEXT,
                winner_count INTEGER DEFAULT 1,
                start_date TEXT NOT NULL,
                end_date TEXT NOT NULL,
                is_active INTEGER DEFAULT 1,
                message_id INTEGER,
                channel_id TEXT
            )
        """)

        # Участники
        self.cursor.execute("""
            CREATE TABLE IF NOT EXISTS participants (
                giveaway_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                join_date TEXT NOT NULL,
                is_valid INTEGER DEFAULT 1,
                referred_by INTEGER,
                bonus_entries INTEGER DEFAULT 0,
                PRIMARY KEY (giveaway_id, user_id)
            )
        """)

        # Рефералы
        self.cursor.execute("""
            CREATE TABLE IF NOT EXISTS referrals (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                referrer_id INTEGER NOT NULL,
                referred_id INTEGER NOT NULL,
                giveaway_id INTEGER NOT NULL,
                referral_date TEXT NOT NULL,
                UNIQUE(referrer_id, referred_id, giveaway_id)
            )
        """)

        self.conn.commit()
        logger.info("Tables created")

    def add_user(self, user_id, username, first_name, last_name=""):
        """Добавить пользователя"""
        try:
            self.cursor.execute('SELECT user_id FROM users WHERE user_id = ?', (user_id,))
            exists = self.cursor.fetchone()

            current_time = datetime.now().isoformat()

            if exists:
                self.cursor.execute("""
                    UPDATE users 
                    SET username = ?, first_name = ?, last_name = ?, last_activity = ?
                    WHERE user_id = ?
                """, (username, first_name, last_name, current_time, user_id))
            else:
                self.cursor.execute("""
                    INSERT INTO users 
                    (user_id, username, first_name, last_name, joined_date, last_activity, is_verified)
                    VALUES (?, ?, ?, ?, ?, ?, 0)
                """, (user_id, username, first_name, last_name, current_time, current_time))

            self.conn.commit()
            return True
        except Exception as e:
            logger.error(f"Error adding user: {e}")
            return False

    def verify_user(self, user_id, method="captcha", ip_hash=None):
        """Верифицировать пользователя"""
        try:
            current_time = datetime.now().isoformat()

            self.cursor.execute("""
                UPDATE users 
                SET is_verified = 1,
                    verification_date = ?,
                    verification_method = ?,
                    verification_attempts = verification_attempts + 1
                WHERE user_id = ?
            """, (current_time, method, user_id))

            self.cursor.execute("""
                INSERT INTO verification_history 
                (user_id, verification_type, success, attempt_date, ip_hash)
                VALUES (?, ?, 1, ?, ?)
            """, (user_id, method, current_time, ip_hash))

            self.conn.commit()

            # Проверка
            self.cursor.execute('SELECT is_verified FROM users WHERE user_id = ?', (user_id,))
            result = self.cursor.fetchone()

            if result and result[0] == 1:
                logger.info(f"User {user_id} verified successfully")
                return True
            else:
                logger.error(f"Verification failed for {user_id}")
                return False

        except Exception as e:
            logger.error(f"Error verifying user {user_id}: {e}")
            self.conn.rollback()
            return False

    def is_verified(self, user_id):
        """Проверить верификацию"""
        try:
            self.cursor.execute("""
                SELECT is_verified, verification_date 
                FROM users 
                WHERE user_id = ?
            """, (user_id,))

            result = self.cursor.fetchone()

            if result:
                is_verified = result[0]
                if is_verified == 1:
                    logger.info(f"User {user_id} is verified")
                    return True
                else:
                    logger.info(f"User {user_id} is NOT verified")
                    return False
            else:
                logger.warning(f"User {user_id} not found")
                return False

        except Exception as e:
            logger.error(f"Error checking verification: {e}")
            return False

    def record_verification_attempt(self, user_id, success=False, method="captcha", ip_hash=None):
        """Записать попытку"""
        try:
            current_time = datetime.now().isoformat()

            self.cursor.execute("""
                UPDATE users 
                SET verification_attempts = verification_attempts + 1
                WHERE user_id = ?
            """, (user_id,))

            self.cursor.execute("""
                INSERT INTO verification_history 
                (user_id, verification_type, success, attempt_date, ip_hash)
                VALUES (?, ?, ?, ?, ?)
            """, (user_id, method, 1 if success else 0, current_time, ip_hash))

            self.conn.commit()
            return True
        except Exception as e:
            logger.error(f"Error recording attempt: {e}")
            return False

    def get_verification_info(self, user_id):
        """Информация о верификации"""
        try:
            self.cursor.execute("""
                SELECT is_verified, verification_date, verification_method, verification_attempts
                FROM users 
                WHERE user_id = ?
            """, (user_id,))
            return self.cursor.fetchone()
        except:
            return None

    def get_verification_history(self, user_id, limit=10):
        """История верификаций"""
        try:
            self.cursor.execute("""
                SELECT verification_type, success, attempt_date, ip_hash
                FROM verification_history
                WHERE user_id = ?
                ORDER BY attempt_date DESC
                LIMIT ?
            """, (user_id, limit))
            return self.cursor.fetchall()
        except:
            return []

    def update_user_activity(self, user_id):
        """Обновить активность"""
        try:
            self.cursor.execute("""
                UPDATE users SET last_activity = ? WHERE user_id = ?
            """, (datetime.now().isoformat(), user_id))
            self.conn.commit()
        except:
            pass

    def ban_user(self, user_id, admin_id, reason="Нарушение правил", days=30):
        """Забанить"""
        try:
            current_time = datetime.now()
            unban_date = current_time + timedelta(days=days)

            self.cursor.execute("""
                INSERT INTO ban_list (user_id, admin_id, reason, ban_date, unban_date)
                VALUES (?, ?, ?, ?, ?)
            """, (user_id, admin_id, reason, current_time.isoformat(), unban_date.isoformat()))

            self.cursor.execute("""
                UPDATE users 
                SET is_banned = 1, ban_reason = ?, banned_date = ?
                WHERE user_id = ?
            """, (reason, current_time.isoformat(), user_id))

            self.cursor.execute("""
                UPDATE participants SET is_valid = 0 
                WHERE user_id = ?
            """, (user_id,))

            self.conn.commit()
            return True
        except:
            return False

    def unban_user(self, user_id):
        """Разбанить"""
        try:
            self.cursor.execute("""
                UPDATE users 
                SET is_banned = 0, ban_reason = NULL, banned_date = NULL
                WHERE user_id = ?
            """, (user_id,))

            self.conn.commit()
            return True
        except:
            return False

    def is_banned(self, user_id):
        """Проверить бан"""
        try:
            self.cursor.execute('SELECT is_banned FROM users WHERE user_id = ?', (user_id,))
            result = self.cursor.fetchone()
            return result and result[0] == 1
        except:
            return False

    def get_ban_info(self, user_id):
        """Информация о бане"""
        try:
            self.cursor.execute("""
                SELECT ban_reason, banned_date 
                FROM users 
                WHERE user_id = ? AND is_banned = 1
            """, (user_id,))
            return self.cursor.fetchone()
        except:
            return None

    def get_banned_users(self):
        """Список забаненных"""
        try:
            self.cursor.execute("""
                SELECT user_id, username, first_name, ban_reason, banned_date 
                FROM users 
                WHERE is_banned = 1
                ORDER BY banned_date DESC
            """)
            return self.cursor.fetchall()
        except:
            return []

    def add_ip_address(self, user_id, ip_address):
        """Добавить IP"""
        try:
            ip_hash = hashlib.sha256(ip_address.encode()).hexdigest()[:32]
            current_time = datetime.now().isoformat()

            self.cursor.execute('UPDATE users SET ip_hash = ? WHERE user_id = ?', (ip_hash, user_id))

            self.cursor.execute('SELECT user_count FROM ip_addresses WHERE ip_hash = ?', (ip_hash,))
            exists = self.cursor.fetchone()

            if exists:
                self.cursor.execute("""
                    UPDATE ip_addresses 
                    SET user_count = user_count + 1, last_seen = ?
                    WHERE ip_hash = ?
                """, (current_time, ip_hash))
            else:
                self.cursor.execute("""
                    INSERT INTO ip_addresses (ip_hash, user_count, first_seen, last_seen)
                    VALUES (?, 1, ?, ?)
                """, (ip_hash, current_time, current_time))

            self.conn.commit()
            return ip_hash
        except:
            return None

    def check_multiple_accounts(self, user_id):
        """Проверить мультиаккаунты"""
        try:
            self.cursor.execute("""
                SELECT user_id FROM users 
                WHERE ip_hash = (SELECT ip_hash FROM users WHERE user_id = ?)
                AND user_id != ?
            """, (user_id, user_id))
            return [row[0] for row in self.cursor.fetchall()]
        except:
            return []

    def create_giveaway(self, name, description, winners, hours, channel_id):
        """Создать розыгрыш"""
        try:
            start_date = datetime.now()
            end_date = start_date + timedelta(hours=hours)

            self.cursor.execute("""
                INSERT INTO giveaways 
                (name, description, winner_count, start_date, end_date, is_active, channel_id) 
                VALUES (?, ?, ?, ?, ?, 1, ?)
            """, (name, description, winners, start_date.isoformat(), end_date.isoformat(), channel_id))

            self.conn.commit()
            return self.cursor.lastrowid
        except:
            return None

    def update_message_id(self, giveaway_id, message_id):
        """Обновить ID сообщения"""
        try:
            self.cursor.execute('UPDATE giveaways SET message_id = ? WHERE id = ?', 
                              (message_id, giveaway_id))
            self.conn.commit()
        except:
            pass

    def add_participant(self, giveaway_id, user_id, referred_by=None):
        """Добавить участника"""
        try:
            current_time = datetime.now().isoformat()

            self.cursor.execute("""
                INSERT INTO participants (giveaway_id, user_id, join_date, referred_by) 
                VALUES (?, ?, ?, ?)
            """, (giveaway_id, user_id, current_time, referred_by))

            if referred_by:
                try:
                    self.cursor.execute("""
                        INSERT INTO referrals (referrer_id, referred_id, giveaway_id, referral_date)
                        VALUES (?, ?, ?, ?)
                    """, (referred_by, user_id, giveaway_id, current_time))

                    self.cursor.execute("""
                        UPDATE participants 
                        SET bonus_entries = bonus_entries + 1
                        WHERE giveaway_id = ? AND user_id = ?
                    """, (giveaway_id, referred_by))
                except:
                    pass

            self.conn.commit()
            return True

        except:
            return False

    def get_referral_count(self, user_id, giveaway_id):
        """Количество рефералов"""
        try:
            self.cursor.execute("""
                SELECT COUNT(*) FROM referrals 
                WHERE referrer_id = ? AND giveaway_id = ?
            """, (user_id, giveaway_id))
            return self.cursor.fetchone()[0]
        except:
            return 0

    def get_bonus_entries(self, user_id, giveaway_id):
        """Бонусные заявки"""
        try:
            self.cursor.execute("""
                SELECT bonus_entries FROM participants 
                WHERE giveaway_id = ? AND user_id = ?
            """, (giveaway_id, user_id))
            result = self.cursor.fetchone()
            return result[0] if result else 0
        except:
            return 0

    def remove_participant(self, giveaway_id, user_id):
        """Удалить участника"""
        try:
            self.cursor.execute("""
                UPDATE participants SET is_valid = 0 
                WHERE giveaway_id = ? AND user_id = ?
            """, (giveaway_id, user_id))
            self.conn.commit()
            return self.cursor.rowcount > 0
        except:
            return False

    def get_active_giveaways(self):
        """Активные розыгрыши"""
        try:
            self.cursor.execute("""
                SELECT id, name, winner_count, end_date 
                FROM giveaways 
                WHERE is_active = 1 
                ORDER BY end_date
            """)
            return self.cursor.fetchall()
        except:
            return []

    def get_giveaway_info(self, giveaway_id):
        """Информация о розыгрыше"""
        try:
            self.cursor.execute('SELECT * FROM giveaways WHERE id = ?', (giveaway_id,))
            return self.cursor.fetchone()
        except:
            return None

    def get_participants(self, giveaway_id, valid_only=True):
        """Участники"""
        try:
            if valid_only:
                self.cursor.execute("""
                    SELECT user_id FROM participants 
                    WHERE giveaway_id = ? AND is_valid = 1
                """, (giveaway_id,))
            else:
                self.cursor.execute("""
                    SELECT user_id FROM participants WHERE giveaway_id = ?
                """, (giveaway_id,))
            return [row[0] for row in self.cursor.fetchall()]
        except:
            return []

    def get_participants_count(self, giveaway_id):
        """Количество участников"""
        try:
            self.cursor.execute("""
                SELECT COUNT(*) FROM participants 
                WHERE giveaway_id = ? AND is_valid = 1
            """, (giveaway_id,))
            return self.cursor.fetchone()[0]
        except:
            return 0

    def end_giveaway(self, giveaway_id):
        """Завершить розыгрыш"""
        try:
            self.cursor.execute('UPDATE giveaways SET is_active = 0 WHERE id = ?', (giveaway_id,))
            self.conn.commit()
            return True
        except:
            return False

# Инициализация БД
db = Database()

# ================== КАПЧА ==================
captcha_storage = {}

def generate_captcha():
    """Генерация капчи"""
    a = random.randint(1, 10)
    b = random.randint(1, 10)
    operations = ['+', '-', '*']
    operation = random.choice(operations)

    if operation == '+':
        answer = a + b
        question = f"{a} + {b}"
    elif operation == '-':
        answer = a - b
        question = f"{a} - {b}"
    else:
        answer = a * b
        question = f"{a} × {b}"

    return question, str(answer)

def extract_ip_from_request(update):
    """Извлечение IP"""
    user = update.effective_user
    return f"{user.id}.{hash(str(user.id)) % 255}.{hash(user.username or '') % 255}"

def is_admin(user_id):
    """Проверка админа"""
    return user_id in ADMIN_IDS

# ================== КОМАНДЫ ==================
def start(update: Update, context: CallbackContext):
    """Команда /start"""
    user = update.effective_user
    db.add_user(user.id, user.username or "", user.first_name, user.last_name or "")
    db.update_user_activity(user.id)

    try:
        ip = extract_ip_from_request(update)
        db.add_ip_address(user.id, ip)
    except:
        pass

    if db.is_banned(user.id):
        update.message.reply_text("🚫 Вы забанены")
        return

    if context.args and context.args[0].startswith('ref_'):
        try:
            parts = context.args[0].split('_')
            if len(parts) == 3:
                giveaway_id = int(parts[1])
                referrer_id = int(parts[2])
                context.user_data['referrer'] = referrer_id
                context.user_data['giveaway'] = giveaway_id
                update.message.reply_text(
                    "👋 Привет! Сначала пройдите верификацию: /verify"
                )
                return
        except:
            pass

    text = (
        f"👋 Привет, {user.first_name}!\n\n"
        "🎉 *Бот для розыгрышей*\n\n"
        "/verify - Пройти проверку\n"
        "/help - Помощь"
    )

    update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN)

def verify(update: Update, context: CallbackContext):
    """Верификация"""
    if update.message.chat.type != 'private':
        update.message.reply_text("🔒 Только в личных сообщениях!")
        return

    user_id = update.effective_user.id

    if db.is_banned(user_id):
        update.message.reply_text("🚫 Вы забанены")
        return

    if db.is_verified(user_id):
        update.message.reply_text("✅ Вы уже верифицированы!")
        return

    question, answer = generate_captcha()
    ip = extract_ip_from_request(update)
    ip_hash = hashlib.sha256(ip.encode()).hexdigest()[:32]

    captcha_storage[user_id] = {
        'answer': answer,
        'attempts': 0,
        'time': datetime.now(),
        'ip_hash': ip_hash
    }

    update.message.reply_text(
        f"🔐 *Пройдите проверку*\n\n"
        f"Решите: `{question} = ?`\n\n"
        "Отправьте ответ числом.",
        parse_mode=ParseMode.MARKDOWN
    )

def handle_text(update: Update, context: CallbackContext):
    """Обработчик текста"""
    if update.message.chat.type != 'private':
        return

    user_id = update.effective_user.id
    text = update.message.text.strip()

    if db.is_banned(user_id):
        return

    if user_id in captcha_storage:
        captcha = captcha_storage[user_id]

        if datetime.now() - captcha['time'] > timedelta(minutes=5):
            update.message.reply_text("⏰ Время вышло. /verify")
            db.record_verification_attempt(user_id, success=False, ip_hash=captcha.get('ip_hash'))
            del captcha_storage[user_id]
            return

        if text == captcha['answer']:
            ip_hash = captcha.get('ip_hash')
            success = db.verify_user(user_id, method="captcha", ip_hash=ip_hash)

            if success:
                del captcha_storage[user_id]

                multi_accounts = db.check_multiple_accounts(user_id)
                if multi_accounts:
                    update.message.reply_text("⚠️ Обнаружены мультиаккаунты.")

                update.message.reply_text("✅ *Проверка пройдена!*\n\nТеперь можете участвовать!", parse_mode=ParseMode.MARKDOWN)
            else:
                update.message.reply_text("❌ Ошибка! Попробуйте /verify")
        else:
            captcha['attempts'] += 1
            db.record_verification_attempt(user_id, success=False, ip_hash=captcha.get('ip_hash'))

            if captcha['attempts'] >= 3:
                update.message.reply_text("❌ Попытки закончились. /verify")
                del captcha_storage[user_id]
            else:
                left = 3 - captcha['attempts']
                update.message.reply_text(f"❌ Неверно. Осталось: {left}")

def help_cmd(update: Update, context: CallbackContext):
    """Помощь"""
    text = (
        "❓ *Помощь*\n\n"
        "1. /start - Начать\n"
        "2. /verify - Пройти проверку\n"
        "3. Участвуйте в розыгрышах\n\n"
        "/help - Эта справка"
    )
    update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN)

def new_giveaway(update: Update, context: CallbackContext):
    """Создать розыгрыш"""
    if not is_admin(update.effective_user.id):
        update.message.reply_text("❌ Нет прав")
        return

    if len(context.args) < 2:
        update.message.reply_text("Использование: /new <название> <победителей> [часы] [описание]")
        return

    name = context.args[0]
    winners = int(context.args[1])
    hours = int(context.args[2]) if len(context.args) > 2 and context.args[2].isdigit() else 24
    description = ' '.join(context.args[3:]) if len(context.args) > 3 else "Розыгрыш"

    giveaway_id = db.create_giveaway(name, description, winners, hours, CHANNEL_ID)

    if not giveaway_id:
        update.message.reply_text("❌ Ошибка")
        return

    end_time = datetime.now() + timedelta(hours=hours)

    keyboard = [[InlineKeyboardButton("🎟 Участвовать", callback_data=f"join_{giveaway_id}")]]
    markup = InlineKeyboardMarkup(keyboard)

    try:
        message = context.bot.send_message(
            chat_id=CHANNEL_ID,
            text=(
                f"🎉 *НОВЫЙ РОЗЫГРЫШ!*\n\n"
                f"🏆 *{name}*\n"
                f"📝 {description}\n\n"
                f"👑 Победителей: {winners}\n"
                f"⏰ Завершится: {end_time.strftime('%d.%m.%Y в %H:%M')}"
            ),
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=markup
        )

        db.update_message_id(giveaway_id, message.message_id)
        update.message.reply_text(f"✅ Создан! ID: {giveaway_id}")
    except Exception as e:
        update.message.reply_text(f"❌ Ошибка: {str(e)}")

def list_giveaways(update: Update, context: CallbackContext):
    """Список розыгрышей"""
    if not is_admin(update.effective_user.id):
        update.message.reply_text("❌ Нет прав")
        return

    giveaways = db.get_active_giveaways()

    if not giveaways:
        update.message.reply_text("📭 Нет розыгрышей")
        return

    text = "📋 *Активные:*\n\n"
    for g in giveaways:
        gid, name, winners, end_date = g
        participants = db.get_participants_count(gid)
        text += f"🎯 ID: {gid}\n🎁 {name}\n👥 {participants}\n──────\n"

    update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN)

def end_giveaway(update: Update, context: CallbackContext):
    """Завершить розыгрыш"""
    if not is_admin(update.effective_user.id):
        update.message.reply_text("❌ Нет прав")
        return

    if not context.args:
        update.message.reply_text("Использование: /end <id>")
        return

    try:
        giveaway_id = int(context.args[0])
        participants = db.get_participants(giveaway_id)

        if not participants:
            update.message.reply_text("❌ Нет участников")
            return

        giveaway_info = db.get_giveaway_info(giveaway_id)
        if not giveaway_info:
            update.message.reply_text("❌ Не найден")
            return

        winner_count = min(giveaway_info[3], len(participants))
        winners = random.sample(participants, winner_count)

        winners_text = "🏆 *ПОБЕДИТЕЛИ:*\n\n"
        for i, winner_id in enumerate(winners, 1):
            try:
                user = context.bot.get_chat(winner_id)
                username = f"@{user.username}" if user.username else user.first_name
                winners_text += f"{i}. {username}\n"
            except:
                winners_text += f"{i}. ID: {winner_id}\n"

        db.end_giveaway(giveaway_id)

        try:
            context.bot.send_message(chat_id=CHANNEL_ID, text=winners_text, parse_mode=ParseMode.MARKDOWN)
        except:
            pass

        update.message.reply_text(f"✅ Завершен!\n\n{winners_text}", parse_mode=ParseMode.MARKDOWN)
    except Exception as e:
        update.message.reply_text(f"❌ Ошибка: {str(e)}")

def ban_user(update: Update, context: CallbackContext):
    """Забанить"""
    if not is_admin(update.effective_user.id):
        update.message.reply_text("❌ Нет прав")
        return

    if len(context.args) < 2:
        update.message.reply_text("Использование: /ban <user_id> <причина>")
        return

    try:
        user_id = int(context.args[0])
        reason = ' '.join(context.args[1:])

        admin_id = update.effective_user.id
        if db.ban_user(user_id, admin_id, reason):
            update.message.reply_text(f"✅ Забанен: {user_id}")
        else:
            update.message.reply_text("❌ Ошибка")
    except:
        update.message.reply_text("❌ Неверный формат")

def unban_user(update: Update, context: CallbackContext):
    """Разбанить"""
    if not is_admin(update.effective_user.id):
        update.message.reply_text("❌ Нет прав")
        return

    if not context.args:
        update.message.reply_text("Использование: /unban <user_id>")
        return

    try:
        user_id = int(context.args[0])
        if db.unban_user(user_id):
            update.message.reply_text(f"✅ Разбанен: {user_id}")
        else:
            update.message.reply_text("❌ Ошибка")
    except:
        update.message.reply_text("❌ Неверный ID")

def verify_info(update: Update, context: CallbackContext):
    """Информация о верификации"""
    if not is_admin(update.effective_user.id):
        update.message.reply_text("❌ Нет прав")
        return

    if not context.args:
        update.message.reply_text("Использование: /verify_info <user_id>")
        return

    try:
        user_id = int(context.args[0])
        info = db.get_verification_info(user_id)

        if not info:
            update.message.reply_text(f"❌ Пользователь {user_id} не найден")
            return

        is_verified, ver_date, ver_method, attempts = info

        text = f"📋 *Верификация {user_id}*\n\n"
        text += f"Статус: {'✅ Верифицирован' if is_verified == 1 else '❌ НЕ верифицирован'}\n"

        if ver_date:
            ver_dt = datetime.fromisoformat(ver_date)
            text += f"Дата: {ver_dt.strftime('%d.%m.%Y %H:%M')}\n"

        if ver_method:
            text += f"Метод: {ver_method}\n"

        text += f"Попыток: {attempts}"

        update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN)
    except:
        update.message.reply_text("❌ Неверный ID")

def button_handler(update: Update, context: CallbackContext):
    """Обработчик кнопок"""
    query = update.callback_query
    user_id = query.from_user.id

    try:
        query.answer()
    except:
        pass

    if query.data.startswith('join_'):
        giveaway_id = int(query.data.split('_')[1])

        if db.is_banned(user_id):
            query.answer("🚫 Вы забанены", show_alert=True)
            return

        if not db.is_verified(user_id):
            try:
                context.bot.send_message(
                    chat_id=user_id,
                    text="❌ *Нужна проверка!*\n\nНапишите /verify",
                    parse_mode=ParseMode.MARKDOWN
                )
                query.answer("❌ Пройдите проверку!", show_alert=True)
            except:
                query.answer("❌ Пройдите проверку: /verify", show_alert=True)
            return

        giveaway_info = db.get_giveaway_info(giveaway_id)
        if not giveaway_info or giveaway_info[6] == 0:
            query.answer("❌ Розыгрыш завершен", show_alert=True)
            return

        referrer_id = context.user_data.get('referrer') if context.user_data.get('giveaway') == giveaway_id else None

        if db.add_participant(giveaway_id, user_id, referred_by=referrer_id):
            participants_count = db.get_participants_count(giveaway_id)

            if 'referrer' in context.user_data:
                del context.user_data['referrer']
            if 'giveaway' in context.user_data:
                del context.user_data['giveaway']

            try:
                context.bot.send_message(
                    chat_id=user_id,
                    text=f"✅ Вы участвуете!\n\nУчастников: {participants_count}"
                )
            except:
                pass

            query.answer(f"✅ Участвуете! Всего: {participants_count}", show_alert=True)
        else:
            query.answer("⚠️ Вы уже участвуете", show_alert=True)

# ================== ЗАПУСК ==================
def main():
    """Главная функция"""
    print("=" * 70)
    print("🤖 БОТ ДЛЯ РОЗЫГРЫШЕЙ")
    print("=" * 70)
    print(f"✅ Токен: {BOT_TOKEN[:10]}...")
    print(f"👑 Админы: {ADMIN_IDS}")
    print(f"📢 Канал: {CHANNEL_ID}")
    print("=" * 70)

    try:
        updater = Updater(BOT_TOKEN, use_context=True)
        dp = updater.dispatcher

        # Команды
        dp.add_handler(CommandHandler("start", start))
        dp.add_handler(CommandHandler("verify", verify))
        dp.add_handler(CommandHandler("help", help_cmd))
        dp.add_handler(CommandHandler("new", new_giveaway))
        dp.add_handler(CommandHandler("list", list_giveaways))
        dp.add_handler(CommandHandler("end", end_giveaway))
        dp.add_handler(CommandHandler("ban", ban_user))
        dp.add_handler(CommandHandler("unban", unban_user))
        dp.add_handler(CommandHandler("verify_info", verify_info))

        # Обработчики
        dp.add_handler(CallbackQueryHandler(button_handler))
        dp.add_handler(MessageHandler(Filters.text & ~Filters.command, handle_text))

        updater.start_polling()
        print("✅ БОТ ЗАПУЩЕН!")
        print("✋ Ctrl+C для остановки")
        print("=" * 70)

        updater.idle()

    except Exception as e:
        logger.error(f"❌ Ошибка: {e}")
        print(f"❌ Ошибка: {e}")

if __name__ == '__main__':
    main()
