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

# Настройка логирования
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# ================== ИСПРАВЛЕННАЯ БАЗА ДАННЫХ ==================
class Database:
    def __init__(self, db_name='giveaway.db'):
        self.conn = sqlite3.connect(db_name, check_same_thread=False)
        self.cursor = self.conn.cursor()
        self.create_tables()
        logger.info("✅ Database initialized successfully")

    def create_tables(self):
        """Создание всех таблиц"""

        # Таблица пользователей с верификацией
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
                device_hash TEXT,
                last_activity TEXT,
                verification_attempts INTEGER DEFAULT 0,
                last_verification_attempt TEXT
            )
        """)

        # Таблица истории верификаций
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

        # Индекс
        self.cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_verification_user 
            ON verification_history(user_id, success)
        """)

        # Остальные таблицы
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

        self.cursor.execute("""
            CREATE TABLE IF NOT EXISTS ip_addresses (
                ip_hash TEXT PRIMARY KEY,
                user_count INTEGER DEFAULT 1,
                first_seen TEXT NOT NULL,
                last_seen TEXT NOT NULL
            )
        """)

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
        logger.info("✅ All tables created")

    def add_user(self, user_id, username, first_name, last_name=""):
        """Добавление пользователя"""
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
        """ИСПРАВЛЕННАЯ ВЕРИФИКАЦИЯ"""
        try:
            current_time = datetime.now().isoformat()

            # Обновляем статус
            self.cursor.execute("""
                UPDATE users 
                SET is_verified = 1,
                    verification_date = ?,
                    verification_method = ?,
                    verification_attempts = verification_attempts + 1,
                    last_verification_attempt = ?
                WHERE user_id = ?
            """, (current_time, method, current_time, user_id))

            # Записываем в историю
            self.cursor.execute("""
                INSERT INTO verification_history 
                (user_id, verification_type, success, attempt_date, ip_hash)
                VALUES (?, ?, 1, ?, ?)
            """, (user_id, method, current_time, ip_hash))

            # КРИТИЧЕСКИ ВАЖНО - коммитим
            self.conn.commit()

            # Проверяем сохранение
            self.cursor.execute('SELECT is_verified FROM users WHERE user_id = ?', (user_id,))
            result = self.cursor.fetchone()

            if result and result[0] == 1:
                logger.info(f"✅ User {user_id} verified successfully")
                return True
            else:
                logger.error(f"❌ Verification failed for {user_id}")
                return False

        except Exception as e:
            logger.error(f"❌ Error verifying user {user_id}: {e}")
            self.conn.rollback()
            return False

    def is_verified(self, user_id):
        """ИСПРАВЛЕННАЯ ПРОВЕРКА"""
        try:
            self.cursor.execute("""
                SELECT is_verified, verification_date 
                FROM users 
                WHERE user_id = ?
            """, (user_id,))

            result = self.cursor.fetchone()

            if result:
                is_verified = result[0]
                verification_date = result[1]

                if is_verified == 1:
                    logger.info(f"✅ User {user_id} is verified (date: {verification_date})")
                    return True
                else:
                    logger.info(f"❌ User {user_id} is NOT verified")
                    return False
            else:
                logger.warning(f"⚠️ User {user_id} not found")
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
                SET verification_attempts = verification_attempts + 1,
                    last_verification_attempt = ?
                WHERE user_id = ?
            """, (current_time, user_id))

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
        """Получить информацию о верификации"""
        try:
            self.cursor.execute("""
                SELECT is_verified, verification_date, verification_method, 
                       verification_attempts, last_verification_attempt
                FROM users 
                WHERE user_id = ?
            """, (user_id,))
            return self.cursor.fetchone()
        except:
            return None

    def get_verification_history(self, user_id, limit=10):
        """Получить историю"""
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
                WHERE user_id = ? AND giveaway_id IN (
                    SELECT id FROM giveaways WHERE is_active = 1
                )
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

            self.cursor.execute("""
                UPDATE ban_list SET unban_date = ? 
                WHERE user_id = ? AND unban_date > ?
            """, (datetime.now().isoformat(), user_id, datetime.now().isoformat()))

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

    def get_suspicious_ips(self, threshold=2):
        """Подозрительные IP"""
        try:
            self.cursor.execute("""
                SELECT ip_hash, user_count, last_seen 
                FROM ip_addresses 
                WHERE user_count >= ?
                ORDER BY user_count DESC
            """, (threshold,))
            return self.cursor.fetchall()
        except:
            return []

    def get_users_by_ip(self, ip_hash):
        """Пользователи по IP"""
        try:
            self.cursor.execute("""
                SELECT user_id, username, first_name, joined_date 
                FROM users 
                WHERE ip_hash = ? 
                ORDER BY joined_date
            """, (ip_hash,))
            return self.cursor.fetchall()
        except:
            return []

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

    def get_referrals_list(self, user_id, giveaway_id):
        """Список рефералов"""
        try:
            self.cursor.execute("""
                SELECT r.referred_id, u.username, u.first_name, r.referral_date
                FROM referrals r
                LEFT JOIN users u ON r.referred_id = u.user_id
                WHERE r.referrer_id = ? AND r.giveaway_id = ?
                ORDER BY r.referral_date DESC
            """, (user_id, giveaway_id))
            return self.cursor.fetchall()
        except:
            return []

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
        """Получить участников"""
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

    def get_participants_with_info(self, giveaway_id):
        """Участники с информацией"""
        try:
            self.cursor.execute("""
                SELECT p.user_id, u.username, u.first_name, u.is_banned, p.join_date
                FROM participants p
                LEFT JOIN users u ON p.user_id = u.user_id
                WHERE p.giveaway_id = ? AND p.is_valid = 1
                ORDER BY p.join_date
            """, (giveaway_id,))
            return self.cursor.fetchall()
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

    def get_user_participations(self, user_id):
        """Участие пользователя"""
        try:
            self.cursor.execute("""
                SELECT g.id, g.name, g.end_date, p.join_date
                FROM participants p
                JOIN giveaways g ON p.giveaway_id = g.id
                WHERE p.user_id = ? AND p.is_valid = 1 AND g.is_active = 1
                ORDER BY g.end_date
            """, (user_id,))
            return self.cursor.fetchall()
        except:
            return []

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

# ================== ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ==================
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
        ban_info = db.get_ban_info(user.id)
        if ban_info:
            reason, ban_date = ban_info
            ban_dt = datetime.fromisoformat(ban_date) if ban_date else datetime.now()
            text = (
                f"🚫 *ВЫ ЗАБАНЕНЫ!*\n\n"
                f"📅 {ban_dt.strftime('%d.%m.%Y %H:%M')}\n"
                f"📝 {reason}"
            )
        else:
            text = "🚫 Вы забанены"
        update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN)
        return

    # Реферальная ссылка
    if context.args and context.args[0].startswith('ref_'):
        try:
            parts = context.args[0].split('_')
            if len(parts) == 3:
                giveaway_id = int(parts[1])
                referrer_id = int(parts[2])
                context.user_data['referrer'] = referrer_id
                context.user_data['giveaway'] = giveaway_id
                update.message.reply_text(
                    f"👋 Привет! Сначала пройдите верификацию: /verify",
                    parse_mode=ParseMode.MARKDOWN
                )
                return
        except:
            pass

    text = (
        f"👋 Привет, {user.first_name}!\n\n"
        f"🎉 *Бот для розыгрышей*\n\n"
        f"/verify - Пройти проверку\n"
        f"/help - Помощь"
    )

    update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN)

def verify(update: Update, context: CallbackContext):
    """ИСПРАВЛЕННАЯ ВЕРИФИКАЦИЯ"""
    if update.message.chat.type != 'private':
        update.message.reply_text(
            "🔒 *Только в ЛС!*",
            parse_mode=ParseMode.MARKDOWN
        )
        return

    user_id = update.effective_user.id

    if db.is_banned(user_id):
        update.message.reply_text("🚫 Вы забанены")
        return

    # Проверка верификации
    if db.is_verified(user_id):
        verification_info = db.get_verification_info(user_id)
        if verification_info:
            is_verified, ver_date, ver_method, attempts, last_attempt = verification_info
            ver_dt = datetime.fromisoformat(ver_date) if ver_date else None

            text = (
                f"✅ *Вы уже верифицированы!*\n\n"
                f"📅 {ver_dt.strftime('%d.%m.%Y %H:%M') if ver_dt else 'неизвестно'}\n"
                f"🔐 Метод: {ver_method or 'неизвестно'}\n"
                f"🔢 Попыток: {attempts}"
            )
        else:
            text = "✅ Вы уже верифицированы!"

        update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN)
        return

    # Генерация капчи
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
        f"Отправьте ответ числом.",
        parse_mode=ParseMode.MARKDOWN
    )

    logger.info(f"Captcha for user {user_id}: {question}")

def handle_text(update: Update, context: CallbackContext):
    """ОБРАБОТЧИК ТЕКСТА"""
    if update.message.chat.type != 'private':
        return

    user_id = update.effective_user.id
    text = update.message.text.strip()

    if db.is_banned(user_id):
        return

    if user_id in captcha_storage:
        captcha = captcha_storage[user_id]

        # Таймаут
        if datetime.now() - captcha['time'] > timedelta(minutes=5):
            update.message.reply_text("⏰ Время вышло. /verify")
            db.record_verification_attempt(user_id, success=False, ip_hash=captcha.get('ip_hash'))
            del captcha_storage[user_id]
            return

        # Проверка ответа
        if text == captcha['answer']:
            ip_hash = captcha.get('ip_hash')
            success = db.verify_user(user_id, method="captcha", ip_hash=ip_hash)

            if success:
                del captcha_storage[user_id]

                multi_accounts = db.check_multiple_accounts(user_id)
                if multi_accounts:
                    update.message.reply_text(
                        "⚠️ *Внимание!* Обнаружены мультиаккаунты.",
                        parse_mode=ParseMode.MARKDOWN
                    )

                update.message.reply_text(
                    "✅ *Проверка пройдена!*\n\nТеперь можете участвовать в розыгрышах!",
                    parse_mode=ParseMode.MARKDOWN
                )

                logger.info(f"✅ User {user_id} verified")
            else:
                update.message.reply_text(
                    "❌ *Ошибка!* Попробуйте снова: /verify",
                    parse_mode=ParseMode.MARKDOWN
                )
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
    user_id = update.effective_user.id

    text = (
        "❓ *Помощь*\n\n"
        "🎁 *Как участвовать:*\n"
        "1. Напишите боту\n"
        "2. /verify - проверка\n"
        "3. Найдите розыгрыш в канале\n"
        "4. Нажмите 'Участвовать'\n\n"
        "/start - Начать\n"
        "/verify - Проверка\n"
        "/help - Помощь"
    )

    update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN)

    if is_admin(user_id):
        admin_text = (
            "🔧 *Админ-команды:*\n\n"
            "/new - Создать\n"
            "/list - Список\n"
            "/end - Завершить\n"
            "/stats - Статистика\n"
            "/ban - Забанить\n"
            "/unban - Разбанить\n"
            "/banned - Забаненные\n"
            "/check_multi - Мультиаккаунты\n"
            "/remove - Удалить участника\n"
            "/participants - Участники\n"
            "/verify_info - Инфо о верификации"
        )
        update.message.reply_text(admin_text, parse_mode=ParseMode.MARKDOWN)

def my_referrals(update: Update, context: CallbackContext):
    """Рефералы"""
    user_id = update.effective_user.id

    if db.is_banned(user_id):
        update.message.reply_text("🚫 Вы забанены")
        return

    if not db.is_verified(user_id):
        update.message.reply_text("❌ Сначала /verify")
        return

    active_giveaways = db.get_active_giveaways()

    if not active_giveaways:
        update.message.reply_text("❌ Нет розыгрышей")
        return

    text = "🎁 *Ваши реферальные ссылки:*\n\n"

    for g in active_giveaways:
        gid, name, winners, end_date = g
        referral_count = db.get_referral_count(user_id, gid)
        bonus_entries = db.get_bonus_entries(user_id, gid)

        bot_username = context.bot.get_me().username
        ref_link = f"https://t.me/{bot_username}?start=ref_{gid}_{user_id}"

        text += (
            f"🏆 *{name}*\n"
            f"🔗 `{ref_link}`\n"
            f"👥 {referral_count} | 🎟 {bonus_entries}\n"
            f"──────\n"
        )

    text += "\n💡 Отправьте ссылку друзьям!"

    update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN)

# ================== АДМИН КОМАНДЫ (продолжение в следующей части) ==================
