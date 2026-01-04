#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import logging
import random
import string
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
    CallbackContext
)
from telegram.ext import Filters
from telegram.parsemode import ParseMode

# ================== НАСТРОЙКИ ==================
BOT_TOKEN = os.getenv('BOT_TOKEN', '8458068573:AAHaKHcWQZOOmTu-z2wu-7kbX8MdhonkS_M')
ADMIN_IDS = [5207853162, 5406117718]  # Ваш Telegram ID
CHANNEL_ID = "@sportgagarinmolodezh"  # ID вашего КАНАЛА

# Настройка логирования
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# ================== БАЗА ДАННЫХ ==================
class Database:
    def __init__(self, db_name='giveaway.db'):
        self.conn = sqlite3.connect(db_name, check_same_thread=False)
        self.create_tables()
    
    def create_tables(self):
        cursor = self.conn.cursor()
        
        # Пользователи
        cursor.execute('PRAGMA table_info(users)')
        columns = [col[1] for col in cursor.fetchall()]
        
        if not columns:
            cursor.execute('''
                CREATE TABLE users (
                    user_id INTEGER PRIMARY KEY,
                    username TEXT,
                    first_name TEXT,
                    last_name TEXT,
                    joined_date TEXT,
                    is_verified INTEGER DEFAULT 0,
                    is_banned INTEGER DEFAULT 0,
                    ban_reason TEXT,
                    banned_date TEXT,
                    ip_hash TEXT,
                    device_hash TEXT,
                    last_activity TEXT
                )
            ''')
        else:
            if 'last_name' not in columns:
                cursor.execute('ALTER TABLE users ADD COLUMN last_name TEXT')
            if 'is_banned' not in columns:
                cursor.execute('ALTER TABLE users ADD COLUMN is_banned INTEGER DEFAULT 0')
            if 'ban_reason' not in columns:
                cursor.execute('ALTER TABLE users ADD COLUMN ban_reason TEXT')
            if 'banned_date' not in columns:
                cursor.execute('ALTER TABLE users ADD COLUMN banned_date TEXT')
            if 'ip_hash' not in columns:
                cursor.execute('ALTER TABLE users ADD COLUMN ip_hash TEXT')
            if 'device_hash' not in columns:
                cursor.execute('ALTER TABLE users ADD COLUMN device_hash TEXT')
            if 'last_activity' not in columns:
                cursor.execute('ALTER TABLE users ADD COLUMN last_activity TEXT')
        
        # Бан-лист
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS ban_list (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                admin_id INTEGER,
                reason TEXT,
                ban_date TEXT,
                unban_date TEXT
            )
        ''')
        
        # IP-адреса
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS ip_addresses (
                ip_hash TEXT PRIMARY KEY,
                user_count INTEGER DEFAULT 1,
                first_seen TEXT,
                last_seen TEXT
            )
        ''')
        
        # Розыгрыши - проверяем существующие столбцы
        cursor.execute('PRAGMA table_info(giveaways)')
        giveaway_columns = [col[1] for col in cursor.fetchall()]
        
        if not giveaway_columns:
            cursor.execute('''
                CREATE TABLE giveaways (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    description TEXT,
                    winner_count INTEGER DEFAULT 1,
                    start_date TEXT,
                    end_date TEXT,
                    is_active INTEGER DEFAULT 1,
                    message_id INTEGER,
                    channel_id INTEGER
                )
            ''')
        else:
            if 'channel_id' not in giveaway_columns:
                cursor.execute('ALTER TABLE giveaways ADD COLUMN channel_id INTEGER')
            if 'message_id' not in giveaway_columns:
                cursor.execute('ALTER TABLE giveaways ADD COLUMN message_id INTEGER')
        
        # Участники
        cursor.execute('PRAGMA table_info(participants)')
        participants_columns = [col[1] for col in cursor.fetchall()]
        
        if not participants_columns:
            cursor.execute('''
                CREATE TABLE participants (
                    giveaway_id INTEGER,
                    user_id INTEGER,
                    join_date TEXT,
                    is_valid INTEGER DEFAULT 1,
                    PRIMARY KEY (giveaway_id, user_id)
                )
            ''')
        else:
            if 'is_valid' not in participants_columns:
                cursor.execute('ALTER TABLE participants ADD COLUMN is_valid INTEGER DEFAULT 1')
        
        self.conn.commit()
    
    def add_user(self, user_id, username, first_name, last_name=""):
        cursor = self.conn.cursor()
        
        cursor.execute('SELECT 1 FROM users WHERE user_id = ?', (user_id,))
        exists = cursor.fetchone()
        
        if exists:
            cursor.execute('''
                UPDATE users SET 
                username = ?, first_name = ?, last_name = ?, last_activity = ?
                WHERE user_id = ?
            ''', (username, first_name, last_name, datetime.now().isoformat(), user_id))
        else:
            cursor.execute('''
                INSERT INTO users 
                (user_id, username, first_name, last_name, joined_date, last_activity) 
                VALUES (?, ?, ?, ?, ?, ?)
            ''', (user_id, username, first_name, last_name, 
                  datetime.now().isoformat(), datetime.now().isoformat()))
        
        self.conn.commit()
    
    def update_user_activity(self, user_id):
        cursor = self.conn.cursor()
        cursor.execute('''
            UPDATE users SET last_activity = ? WHERE user_id = ?
        ''', (datetime.now().isoformat(), user_id))
        self.conn.commit()
    
    def verify_user(self, user_id):
        cursor = self.conn.cursor()
        cursor.execute('UPDATE users SET is_verified = 1 WHERE user_id = ?', (user_id,))
        self.conn.commit()
    
    def is_verified(self, user_id):
        cursor = self.conn.cursor()
        cursor.execute('SELECT is_verified FROM users WHERE user_id = ?', (user_id,))
        result = cursor.fetchone()
        return result and result[0] == 1
    
    def ban_user(self, user_id, admin_id, reason="Нарушение правил", days=30):
        cursor = self.conn.cursor()
        
        unban_date = datetime.now() + timedelta(days=days)
        cursor.execute('''
            INSERT INTO ban_list (user_id, admin_id, reason, ban_date, unban_date)
            VALUES (?, ?, ?, ?, ?)
        ''', (user_id, admin_id, reason, datetime.now().isoformat(), unban_date.isoformat()))
        
        cursor.execute('''
            UPDATE users SET is_banned = 1, ban_reason = ?, banned_date = ?
            WHERE user_id = ?
        ''', (reason, datetime.now().isoformat(), user_id))
        
        cursor.execute('''
            UPDATE participants SET is_valid = 0 
            WHERE user_id = ? AND giveaway_id IN (
                SELECT id FROM giveaways WHERE is_active = 1
            )
        ''', (user_id,))
        
        self.conn.commit()
    
    def unban_user(self, user_id):
        cursor = self.conn.cursor()
        cursor.execute('''
            UPDATE users SET is_banned = 0, ban_reason = NULL, banned_date = NULL
            WHERE user_id = ?
        ''', (user_id,))
        
        cursor.execute('''
            UPDATE ban_list SET unban_date = ? 
            WHERE user_id = ? AND unban_date > ?
        ''', (datetime.now().isoformat(), user_id, datetime.now().isoformat()))
        
        self.conn.commit()
    
    def is_banned(self, user_id):
        cursor = self.conn.cursor()
        cursor.execute('SELECT is_banned FROM users WHERE user_id = ?', (user_id,))
        result = cursor.fetchone()
        return result and result[0] == 1
    
    def get_ban_info(self, user_id):
        cursor = self.conn.cursor()
        cursor.execute('''
            SELECT reason, banned_date FROM users 
            WHERE user_id = ? AND is_banned = 1
        ''', (user_id,))
        return cursor.fetchone()
    
    def get_banned_users(self):
        cursor = self.conn.cursor()
        cursor.execute('''
            SELECT user_id, username, first_name, ban_reason, banned_date 
            FROM users WHERE is_banned = 1
            ORDER BY banned_date DESC
        ''')
        return cursor.fetchall()
    
    def add_ip_address(self, user_id, ip_address):
        cursor = self.conn.cursor()
        
        ip_hash = hashlib.sha256(ip_address.encode()).hexdigest()[:32]
        cursor.execute('UPDATE users SET ip_hash = ? WHERE user_id = ?', (ip_hash, user_id))
        
        cursor.execute('''
            INSERT INTO ip_addresses (ip_hash, first_seen, last_seen)
            VALUES (?, ?, ?)
            ON CONFLICT(ip_hash) DO UPDATE SET 
            user_count = user_count + 1,
            last_seen = ?
        ''', (ip_hash, datetime.now().isoformat(), datetime.now().isoformat(), 
              datetime.now().isoformat()))
        
        self.conn.commit()
        return ip_hash
    
    def get_suspicious_ips(self, threshold=2):
        cursor = self.conn.cursor()
        cursor.execute('''
            SELECT ip_hash, user_count, last_seen 
            FROM ip_addresses 
            WHERE user_count >= ?
            ORDER BY user_count DESC
        ''', (threshold,))
        return cursor.fetchall()
    
    def get_users_by_ip(self, ip_hash):
        cursor = self.conn.cursor()
        cursor.execute('''
            SELECT user_id, username, first_name, joined_date 
            FROM users 
            WHERE ip_hash = ? 
            ORDER BY joined_date
        ''', (ip_hash,))
        return cursor.fetchall()
    
    def check_multiple_accounts(self, user_id, ip_address=None):
        cursor = self.conn.cursor()
        
        if ip_address:
            ip_hash = hashlib.sha256(ip_address.encode()).hexdigest()[:32]
            cursor.execute('SELECT ip_hash FROM users WHERE user_id = ?', (user_id,))
            result = cursor.fetchone()
            
            if result and result[0]:
                ip_hash = result[0]
            else:
                return []
        
        cursor.execute('''
            SELECT user_id FROM users 
            WHERE ip_hash = (SELECT ip_hash FROM users WHERE user_id = ?)
            AND user_id != ?
        ''', (user_id, user_id))
        
        return [row[0] for row in cursor.fetchall()]
    
    def create_giveaway(self, name, description, winners, hours, channel_id):
        cursor = self.conn.cursor()
        start_date = datetime.now()
        end_date = start_date + timedelta(hours=hours)
        
        cursor.execute('''
            INSERT INTO giveaways 
            (name, description, winner_count, start_date, end_date, is_active, channel_id) 
            VALUES (?, ?, ?, ?, ?, ?, ?)
        ''', (name, description, winners, start_date.isoformat(), 
              end_date.isoformat(), 1, channel_id))
        
        self.conn.commit()
        return cursor.lastrowid
    
    def update_message_id(self, giveaway_id, message_id):
        cursor = self.conn.cursor()
        cursor.execute('UPDATE giveaways SET message_id = ? WHERE id = ?', 
                      (message_id, giveaway_id))
        self.conn.commit()
    
    def add_participant(self, giveaway_id, user_id, referred_by=None):
        cursor = self.conn.cursor()
        try:
            cursor.execute('''
                INSERT INTO participants (giveaway_id, user_id, join_date, referred_by) 
                VALUES (?, ?, ?, ?)
            ''', (giveaway_id, user_id, datetime.now().isoformat(), referred_by))
            self.conn.commit()

            if referred_by:
                try:
                    cursor.execute('''
                        INSERT INTO referrals (referrer_id, referred_id, giveaway_id, referral_date)
                        VALUES (?, ?, ?, ?)
                    ''', (referred_by, user_id, giveaway_id, datetime.now().isoformat()))

                    cursor.execute('''
                        UPDATE participants 
                        SET bonus_entries = bonus_entries + 1
                        WHERE giveaway_id = ? AND user_id = ?
                    ''', (giveaway_id, referred_by))

                    self.conn.commit()
                except sqlite3.IntegrityError:
                    pass

            return True
        except sqlite3.IntegrityError:
            cursor.execute('''
                UPDATE participants SET is_valid = 1, join_date = ?
                WHERE giveaway_id = ? AND user_id = ?
            ''', (datetime.now().isoformat(), giveaway_id, user_id))
            self.conn.commit()
            return True

    def get_referral_count(self, user_id, giveaway_id):
        cursor = self.conn.cursor()
        cursor.execute('''
            SELECT COUNT(*) FROM referrals 
            WHERE referrer_id = ? AND giveaway_id = ?
        ''', (user_id, giveaway_id))
        return cursor.fetchone()[0]

    def get_referrals_list(self, user_id, giveaway_id):
        cursor = self.conn.cursor()
        cursor.execute('''
            SELECT r.referred_id, u.username, u.first_name, r.referral_date
            FROM referrals r
            LEFT JOIN users u ON r.referred_id = u.user_id
            WHERE r.referrer_id = ? AND r.giveaway_id = ?
            ORDER BY r.referral_date DESC
        ''', (user_id, giveaway_id))
        return cursor.fetchall()

    def get_referrer(self, user_id, giveaway_id):
        cursor = self.conn.cursor()
        cursor.execute('''
            SELECT p.referred_by, u.username, u.first_name
            FROM participants p
            LEFT JOIN users u ON p.referred_by = u.user_id
            WHERE p.giveaway_id = ? AND p.user_id = ? AND p.referred_by IS NOT NULL
        ''', (giveaway_id, user_id))
        return cursor.fetchone()

    def get_bonus_entries(self, user_id, giveaway_id):
        cursor = self.conn.cursor()
        cursor.execute('''
            SELECT bonus_entries FROM participants 
            WHERE giveaway_id = ? AND user_id = ?
        ''', (giveaway_id, user_id))
        result = cursor.fetchone()
        return result[0] if result else 0

    def get_participants_with_bonus(self, giveaway_id):
        cursor = self.conn.cursor()
        cursor.execute('''
            SELECT user_id, (1 + bonus_entries) as total_entries
            FROM participants 
            WHERE giveaway_id = ? AND is_valid = 1
        ''', (giveaway_id,))
        return cursor.fetchall()
    
    def remove_participant(self, giveaway_id, user_id):
        cursor = self.conn.cursor()
        cursor.execute('''
            UPDATE participants SET is_valid = 0 
            WHERE giveaway_id = ? AND user_id = ?
        ''', (giveaway_id, user_id))
        
        affected = cursor.rowcount
        self.conn.commit()
        return affected > 0
    
    def get_active_giveaways(self):
        cursor = self.conn.cursor()
        cursor.execute('''
            SELECT id, name, winner_count, end_date 
            FROM giveaways 
            WHERE is_active = 1 
            ORDER BY end_date
        ''')
        return cursor.fetchall()
    
    def get_giveaway_info(self, giveaway_id):
        cursor = self.conn.cursor()
        cursor.execute('SELECT * FROM giveaways WHERE id = ?', (giveaway_id,))
        return cursor.fetchone()
    
    def get_participants(self, giveaway_id, valid_only=True):
        cursor = self.conn.cursor()
        if valid_only:
            cursor.execute('''
                SELECT user_id FROM participants 
                WHERE giveaway_id = ? AND is_valid = 1
            ''', (giveaway_id,))
        else:
            cursor.execute('SELECT user_id FROM participants WHERE giveaway_id = ?', (giveaway_id,))
        return [row[0] for row in cursor.fetchall()]
    
    def get_participants_with_info(self, giveaway_id):
        cursor = self.conn.cursor()
        cursor.execute('''
            SELECT p.user_id, u.username, u.first_name, u.is_banned, p.join_date
            FROM participants p
            LEFT JOIN users u ON p.user_id = u.user_id
            WHERE p.giveaway_id = ? AND p.is_valid = 1
            ORDER BY p.join_date
        ''', (giveaway_id,))
        return cursor.fetchall()
    
    def get_participants_count(self, giveaway_id):
        cursor = self.conn.cursor()
        cursor.execute('SELECT COUNT(*) FROM participants WHERE giveaway_id = ? AND is_valid = 1', 
                      (giveaway_id,))
        return cursor.fetchone()[0]
    
    def end_giveaway(self, giveaway_id):
        cursor = self.conn.cursor()
        cursor.execute('UPDATE giveaways SET is_active = 0 WHERE id = ?', (giveaway_id,))
        self.conn.commit()
    
    def get_user_participations(self, user_id):
        cursor = self.conn.cursor()
        cursor.execute('''
            SELECT g.id, g.name, g.end_date, p.join_date
            FROM participants p
            JOIN giveaways g ON p.giveaway_id = g.id
            WHERE p.user_id = ? AND p.is_valid = 1 AND g.is_active = 1
            ORDER BY g.end_date
        ''', (user_id,))
        return cursor.fetchall()

db = Database()

# ================== КАПЧА (математическая) ==================
captcha_storage = {}

def generate_captcha():
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
    user = update.effective_user
    return f"{user.id}.{hash(str(user.id)) % 255}.{hash(user.username or '') % 255}"

def is_admin(user_id):
    return user_id in ADMIN_IDS

# ================== КОМАНДЫ ДЛЯ ПОЛЬЗОВАТЕЛЕЙ ==================
def start(update: Update, context: CallbackContext):
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
                f"📅 Дата бана: {ban_dt.strftime('%d.%m.%Y %H:%M')}\n"
                f"📝 Причина: {reason}\n\n"
                f"❌ Вы не можете участвовать в розыгрышах."
            )
        else:
            text = "🚫 Вы забанены и не можете использовать бота."
        
        update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN)
        return
    
    text = (
        f"👋 Привет, {user.first_name}!\n\n"
        f"🎉 *Бот для розыгрышей*\n\n"
        f"📋 *Команды:*\n"
        f"/verify - Пройти проверку\n"
        f"/help - Помощь\n\n"
        f"Для участия в розыгрышах нужно пройти проверку."
    )
    
    update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN)

def verify(update: Update, context: CallbackContext):
    if update.message.chat.type != 'private':
        update.message.reply_text(
            "🔒 *Проверка доступна только в личных сообщениях!*",
            parse_mode=ParseMode.MARKDOWN
        )
        return
    
    user_id = update.effective_user.id
    
    if db.is_banned(user_id):
        update.message.reply_text("🚫 Вы забанены и не можете проходить проверку.")
        return
    
    if db.is_verified(user_id):
        update.message.reply_text("✅ Вы уже проверены!")
        return
    
    question, answer = generate_captcha()
    
    captcha_storage[user_id] = {
        'answer': answer,
        'attempts': 0,
        'time': datetime.now()
    }
    
    update.message.reply_text(
        f"🔐 *Пройдите проверку*\n\n"
        f"Решите пример:\n"
        f"`{question} = ?`\n\n"
        f"Отправьте ответ числом.",
        parse_mode=ParseMode.MARKDOWN
    )

def help_cmd(update: Update, context: CallbackContext):
    """Команда /help - упрощенная версия"""
    user_id = update.effective_user.id
    admin = is_admin(user_id)
    
    # Базовая справка для всех
    text = (
        "❓ *Помощь по боту*\n\n"
        "🎁 *Как участвовать:*\n"
        "1. Напишите боту в личные сообщения\n"
        "2. Пройдите проверку командой /verify\n"
        "3. Найдите активный розыгрыш в канале\n"
        "4. Нажмите кнопку '🎟 Участвовать'\n\n"
        "⚙️ *Основные команды:*\n"
        "/start - Начать работу\n"
        "/verify - Пройти проверку\n"
        "/help - Эта справка"
    )
    
    update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN)
    
    # Отдельное сообщение с командами админа
    if admin:
        admin_text = (
            "🔧 *Команды администратора:*\n\n"
            "*Розыгрыши:*\n"
            "/new - Создать розыгрыш\n"
            "/list - Список розыгрышей\n"
            "/end - Завершить розыгрыш\n"
            "/stats - Статистика\n\n"
            "*Модерация:*\n"
            "/ban - Забанить\n"
            "/unban - Разбанить\n"
            "/banned - Список забаненных\n"
            "/check_multi - Проверить мультиаккаунты\n"
            "/remove - Удалить участника\n"
            "/participants - Список участников"
        )
        
        update.message.reply_text(admin_text, parse_mode=ParseMode.MARKDOWN)

def handle_text(update: Update, context: CallbackContext):
    if update.message.chat.type != 'private':
        return
    
    user_id = update.effective_user.id
    text = update.message.text.strip()
    
    if db.is_banned(user_id):
        return
    
    if user_id in captcha_storage:
        captcha = captcha_storage[user_id]
        
        if datetime.now() - captcha['time'] > timedelta(minutes=5):
            update.message.reply_text("⏰ Время вышло. Используйте /verify")
            del captcha_storage[user_id]
            return
        
        if text == captcha['answer']:
            db.verify_user(user_id)
            del captcha_storage[user_id]
            
            multi_accounts = db.check_multiple_accounts(user_id)
            if multi_accounts:
                update.message.reply_text(
                    "⚠️ *Внимание! Обнаружены подозрительные активности.*\n\n"
                    "У вашего IP-адреса несколько аккаунтов.\n"
                    "Это может привести к бану.",
                    parse_mode=ParseMode.MARKDOWN
                )
            
            update.message.reply_text(
                "✅ *Проверка пройдена успешно!*\n\n"
                "Теперь вы можете участвовать в розыгрышах!",
                parse_mode=ParseMode.MARKDOWN
            )
        else:
            captcha['attempts'] += 1
            if captcha['attempts'] >= 3:
                update.message.reply_text("❌ Попытки закончились. Попробуйте позже.")
                del captcha_storage[user_id]
            else:
                left = 3 - captcha['attempts']
                update.message.reply_text(f"❌ Неверно. Осталось попыток: {left}")


def my_referrals(update: Update, context: CallbackContext):
    """Показать статистику по рефералам"""
    user_id = update.effective_user.id

    if db.is_banned(user_id):
        update.message.reply_text("🚫 Вы забанены.")
        return

    if not db.is_verified(user_id):
        update.message.reply_text("❌ Сначала пройдите проверку: /verify")
        return

    active_giveaways = db.get_active_giveaways()

    if not active_giveaways:
        update.message.reply_text("❌ Нет активных розыгрышей")
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
            f"🔗 Ваша ссылка:\n`{ref_link}`\n"
            f"👥 Приглашено: {referral_count}\n"
            f"🎟 Бонусных заявок: {bonus_entries}\n"
            f"📈 Шансов на победу: {1 + bonus_entries}x\n"
            f"──────\n"
        )

    text += (
        "\n💡 *Как это работает:*\n"
        "• Отправьте ссылку друзьям\n"
        "• За каждого друга вы получаете +1 заявку\n"
        "• Больше заявок = выше шанс победы!\n\n"
        "📊 Подробная статистика: /refstats"
    )

    update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN)

def ref_stats(update: Update, context: CallbackContext):
    """Детальная статистика по рефералам"""
    user_id = update.effective_user.id

    if not context.args:
        update.message.reply_text("Использование: /refstats <id_розыгрыша>\n\nУзнать ID: /list")
        return

    try:
        giveaway_id = int(context.args[0])
    except:
        update.message.reply_text("❌ ID должен быть числом")
        return

    referrals = db.get_referrals_list(user_id, giveaway_id)

    if not referrals:
        update.message.reply_text("У вас пока нет приглашенных пользователей в этом розыгрыше.")
        return

    giveaway_info = db.get_giveaway_info(giveaway_id)
    name = giveaway_info[1] if giveaway_info else f"#{giveaway_id}"

    text = f"📊 *Статистика приглашений*\n🏆 Розыгрыш: {name}\n\n"
    text += f"👥 *Ваши рефералы ({len(referrals)}):*\n\n"

    for i, (ref_id, username, first_name, ref_date) in enumerate(referrals, 1):
        date_str = datetime.fromisoformat(ref_date).strftime('%d.%m.%Y %H:%M') if ref_date else "неизвестно"
        user_display = f"{first_name} (@{username})" if username else first_name
        text += f"{i}. {user_display}\n   📅 {date_str}\n"

    bonus = db.get_bonus_entries(user_id, giveaway_id)
    text += f"\n🎟 *Всего бонусных заявок:* {bonus}\n"
    text += f"📈 *Ваш множитель шанса:* {1 + bonus}x"

    update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN)

# ================== КОМАНДЫ ДЛЯ АДМИНОВ ==================
def new_giveaway(update: Update, context: CallbackContext):
    if not is_admin(update.effective_user.id):
        update.message.reply_text("❌ Нет прав")
        return
    
    if len(context.args) < 2:
        update.message.reply_text(
            "Использование: /new <название> <победителей> [часы=24] [описание]\n"
            "Пример: /new iPhone 3 48 Выиграй iPhone!"
        )
        return
    
    name = context.args[0]
    winners = int(context.args[1])
    hours = int(context.args[2]) if len(context.args) > 2 else 24
    description = ' '.join(context.args[3:]) if len(context.args) > 3 else "Розыгрыш приза"
    
    giveaway_id = db.create_giveaway(name, description, winners, hours, CHANNEL_ID)
    
    end_time = datetime.now() + timedelta(hours=hours)
    
    time_left = end_time - datetime.now()
    days = time_left.days
    hours_left = time_left.seconds // 3600
    minutes_left = (time_left.seconds % 3600) // 60
    
    time_text = ""
    if days > 0:
        time_text = f"{days} дней {hours_left} часов"
    elif hours_left > 0:
        time_text = f"{hours_left} часов {minutes_left} минут"
    else:
        time_text = f"{minutes_left} минут"
    
    keyboard = [[InlineKeyboardButton("🎟 Участвовать", callback_data=f"join_{giveaway_id}")]]
    markup = InlineKeyboardMarkup(keyboard)
    
    try:
        message = context.bot.send_message(
            chat_id=CHANNEL_ID,
            text=(
                f"🎉 *НОВЫЙ РОЗЫГРЫШ!*\n\n"
                f"🏆 *{name}*\n"
                f"📝 {description}\n\n"
                f"👑 *Победителей:* {winners}\n"
                f"⏰ *Завершится через:* {time_text}\n"
                f"📅 *Дата окончания:* {end_time.strftime('%d.%m.%Y в %H:%M')}\n\n"
                f"👇 *Нажмите кнопку ниже для участия*"
            ),
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=markup
        )
        
        db.update_message_id(giveaway_id, message.message_id)
        update.message.reply_text(
            f"✅ *Розыгрыш создан в канале!*\n\n"
            f"🎯 ID розыгрыша: {giveaway_id}\n"
            f"🎁 Название: {name}\n"
            f"👑 Победителей: {winners}\n"
            f"⏰ Длительность: {hours} часов",
            parse_mode=ParseMode.MARKDOWN
        )
        
    except Exception as e:
        update.message.reply_text(f"❌ Ошибка: {str(e)}")

def list_giveaways(update: Update, context: CallbackContext):
    if not is_admin(update.effective_user.id):
        update.message.reply_text("❌ Нет прав")
        return
    
    giveaways = db.get_active_giveaways()
    
    if not giveaways:
        update.message.reply_text("📭 Нет активных розыгрышей")
        return
    
    text = "📋 *Активные розыгрыши:*\n\n"
    for g in giveaways:
        gid, name, winners, end_date = g
        end = datetime.fromisoformat(end_date)
        left = end - datetime.now()
        
        if left.total_seconds() <= 0:
            continue
        
        participants = db.get_participants_count(gid)
        hours = int(left.total_seconds() // 3600)
        minutes = int((left.total_seconds() % 3600) // 60)
        
        text += (
            f"🎯 *ID:* {gid}\n"
            f"🎁 *Название:* {name}\n"
            f"👑 *Победителей:* {winners}\n"
            f"👥 *Участников:* {participants}\n"
            f"⏳ *Осталось:* {hours}ч {minutes}м\n"
            f"──────\n"
        )
    
    update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN)

def end_giveaway(update: Update, context: CallbackContext):
    if not is_admin(update.effective_user.id):
        update.message.reply_text("❌ Нет прав")
        return
    
    if not context.args:
        update.message.reply_text("Использование: /end <id_розыгрыша>")
        return
    
    try:
        giveaway_id = int(context.args[0])
        participants = db.get_participants(giveaway_id)
        
        if not participants:
            update.message.reply_text("❌ Нет участников")
            return
        
        giveaway_info = db.get_giveaway_info(giveaway_id)
        if not giveaway_info:
            update.message.reply_text("❌ Розыгрыш не найден")
            return
        
        winner_count = giveaway_info[3]
        
        if len(participants) < winner_count:
            winner_count = len(participants)
        
        winners = random.sample(participants, winner_count)
        
        winners_text = "🏆 *ПОБЕДИТЕЛИ РОЗЫГРЫША:*\n\n"
        for i, winner_id in enumerate(winners, 1):
            try:
                user = context.bot.get_chat(winner_id)
                username = f"@{user.username}" if user.username else user.first_name
                winners_text += f"{i}. {username}\n"
            except:
                winners_text += f"{i}. ID: {winner_id}\n"
        
        db.end_giveaway(giveaway_id)
        
        try:
            context.bot.send_message(
                chat_id=CHANNEL_ID,
                text=winners_text,
                parse_mode=ParseMode.MARKDOWN
            )
        except:
            pass
        
        update.message.reply_text(
            f"✅ *Розыгрыш завершен!*\n\n"
            f"{winners_text}",
            parse_mode=ParseMode.MARKDOWN
        )
        
    except Exception as e:
        update.message.reply_text(f"❌ Ошибка: {str(e)}")

def stats(update: Update, context: CallbackContext):
    if not is_admin(update.effective_user.id):
        update.message.reply_text("❌ Нет прав")
        return
    
    if not context.args:
        update.message.reply_text("Использование: /stats <id_розыгрыша>")
        return
    
    try:
        giveaway_id = int(context.args[0])
        giveaway_info = db.get_giveaway_info(giveaway_id)
        
        if not giveaway_info:
            update.message.reply_text("❌ Розыгрыш не найден")
            return
        
        participants = db.get_participants(giveaway_id)
        participants_count = len(participants)
        
        _, name, description, winners, start_date, end_date, is_active, message_id, channel_id = giveaway_info
        
        start = datetime.fromisoformat(start_date)
        end = datetime.fromisoformat(end_date)
        left = end - datetime.now()
        
        status = "✅ Активен" if is_active == 1 else "❌ Завершен"
        
        text = (
            f"📊 *Статистика розыгрыша #{giveaway_id}*\n\n"
            f"🎁 *Название:* {name}\n"
            f"📝 *Описание:* {description}\n"
            f"👑 *Победителей:* {winners}\n"
            f"👥 *Участников:* {participants_count}\n"
            f"🔄 *Статус:* {status}\n\n"
            f"⏰ *Начало:* {start.strftime('%d.%m.%Y %H:%M')}\n"
            f"⏰ *Конец:* {end.strftime('%d.%m.%Y %H:%M')}\n"
        )
        
        if is_active == 1 and left.total_seconds() > 0:
            hours = int(left.total_seconds() // 3600)
            minutes = int((left.total_seconds() % 3600) // 60)
            text += f"⏳ *Осталось:* {hours}ч {minutes}м"
        
        update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN)
        
    except Exception as e:
        update.message.reply_text(f"❌ Ошибка: {str(e)}")

def ban_user(update: Update, context: CallbackContext):
    if not is_admin(update.effective_user.id):
        update.message.reply_text("❌ Нет прав")
        return
    
    if len(context.args) < 2:
        update.message.reply_text(
            "Использование: /ban <user_id> <причина> [дней=30]\n"
            "Пример: /ban 123456789 Нарушение правил 90"
        )
        return
    
    try:
        user_arg = context.args[0]
        user_id = int(user_arg)
        
        reason = ' '.join(context.args[1:-1]) if len(context.args) > 2 else context.args[1]
        days = int(context.args[-1]) if context.args[-1].isdigit() else 30
        
        admin_id = update.effective_user.id
        db.ban_user(user_id, admin_id, reason, days)
        
        try:
            context.bot.send_message(
                chat_id=user_id,
                text=f"🚫 *ВЫ ЗАБАНЕНЫ!*\n\nПричина: {reason}\nСрок: {days} дней",
                parse_mode=ParseMode.MARKDOWN
            )
        except:
            pass
        
        update.message.reply_text(
            f"✅ *Пользователь забанен!*\n\n"
            f"👤 ID: {user_id}\n"
            f"📝 Причина: {reason}\n"
            f"⏰ Срок: {days} дней",
            parse_mode=ParseMode.MARKDOWN
        )
        
    except ValueError:
        update.message.reply_text("❌ User ID должен быть числом")
    except Exception as e:
        update.message.reply_text(f"❌ Ошибка: {str(e)}")

def unban_user(update: Update, context: CallbackContext):
    if not is_admin(update.effective_user.id):
        update.message.reply_text("❌ Нет прав")
        return
    
    if not context.args:
        update.message.reply_text("Использование: /unban <user_id>")
        return
    
    try:
        user_id = int(context.args[0])
        db.unban_user(user_id)
        update.message.reply_text(f"✅ Пользователь {user_id} разбанен!")
        
    except ValueError:
        update.message.reply_text("❌ User ID должен быть числом")
    except Exception as e:
        update.message.reply_text(f"❌ Ошибка: {str(e)}")

def banned_list(update: Update, context: CallbackContext):
    if not is_admin(update.effective_user.id):
        update.message.reply_text("❌ Нет прав")
        return
    
    banned_users = db.get_banned_users()
    
    if not banned_users:
        update.message.reply_text("✅ Нет забаненных пользователей")
        return
    
    text = "🚫 *Забаненные пользователи:*\n\n"
    for user in banned_users:
        user_id, username, first_name, reason, ban_date = user
        ban_dt = datetime.fromisoformat(ban_date) if ban_date else datetime.now()
        
        text += (
            f"👤 *{first_name}* (@{username if username else 'нет'})\n"
            f"🆔 ID: `{user_id}`\n"
            f"📝 Причина: {reason}\n"
            f"📅 Дата: {ban_dt.strftime('%d.%m.%Y %H:%M')}\n"
            f"──────\n"
        )
    
    update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN)

def check_multi_accounts(update: Update, context: CallbackContext):
    if not is_admin(update.effective_user.id):
        update.message.reply_text("❌ Нет прав")
        return
    
    threshold = 2
    if context.args:
        try:
            threshold = int(context.args[0])
        except:
            pass
    
    suspicious_ips = db.get_suspicious_ips(threshold)
    
    if not suspicious_ips:
        update.message.reply_text(f"✅ Нет подозрительных IP (порог: {threshold}+ аккаунтов)")
        return
    
    text = f"🔍 *Подозрительные IP ({threshold}+ аккаунтов):*\n\n"
    
    for ip_hash, user_count, last_seen in suspicious_ips[:10]:
        users = db.get_users_by_ip(ip_hash)
        
        text += f"🌐 *IP (хеш):* `{ip_hash[:12]}...`\n"
        text += f"👥 Аккаунтов: {user_count}\n"
        text += f"📅 Последняя активность: {datetime.fromisoformat(last_seen).strftime('%d.%m.%Y %H:%M')}\n"
        text += f"👤 Пользователи:\n"
        
        for user in users[:5]:
            user_id, username, first_name, joined_date = user
            joined = datetime.fromisoformat(joined_date).strftime('%d.%m.%Y') if joined_date else "неизвестно"
            text += f"  • {first_name} (@{username if username else 'нет'}) ID: `{user_id}` (с {joined})\n"
        
        text += "──────\n"
    
    if len(suspicious_ips) > 10:
        text += f"\n... и еще {len(suspicious_ips) - 10} подозрительных IP"
    
    update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN)

def remove_participant(update: Update, context: CallbackContext):
    if not is_admin(update.effective_user.id):
        update.message.reply_text("❌ Нет прав")
        return
    
    if len(context.args) < 2:
        update.message.reply_text(
            "Использование: /remove <id_розыгрыша> <user_id>\n"
            "Пример: /remove 5 123456789"
        )
        return
    
    try:
        giveaway_id = int(context.args[0])
        user_id = int(context.args[1])
        
        if db.remove_participant(giveaway_id, user_id):
            update.message.reply_text(
                f"✅ *Участник удален из розыгрыша!*\n\n"
                f"🎯 Розыгрыш ID: {giveaway_id}\n"
                f"👤 Пользователь ID: {user_id}",
                parse_mode=ParseMode.MARKDOWN
            )
        else:
            update.message.reply_text("❌ Участник не найден или уже удален")
        
    except ValueError:
        update.message.reply_text("❌ ID должны быть числами")
    except Exception as e:
        update.message.reply_text(f"❌ Ошибка: {str(e)}")

def list_participants(update: Update, context: CallbackContext):
    if not is_admin(update.effective_user.id):
        update.message.reply_text("❌ Нет прав")
        return
    
    if not context.args:
        update.message.reply_text("Использование: /participants <id_розыгрыша>")
        return
    
    try:
        giveaway_id = int(context.args[0])
        participants = db.get_participants_with_info(giveaway_id)
        
        if not participants:
            update.message.reply_text("❌ Нет участников в этом розыгрыше")
            return
        
        giveaway_info = db.get_giveaway_info(giveaway_id)
        name = giveaway_info[1] if giveaway_info else f"#{giveaway_id}"
        
        text = f"👥 *Участники розыгрыша: {name}*\n\n"
        
        for i, (user_id, username, first_name, is_banned, join_date) in enumerate(participants[:50], 1):
            join_dt = datetime.fromisoformat(join_date).strftime('%d.%m.%Y %H:%M') if join_date else "неизвестно"
            status = "🚫" if is_banned == 1 else "✅"
            
            text += (
                f"{i}. {status} *{first_name}* "
                f"(@{username if username else 'нет'})\n"
                f"   🆔 ID: `{user_id}`\n"
                f"   📅 Вступил: {join_dt}\n"
            )
            
            multi_accounts = db.check_multiple_accounts(user_id)
            if multi_accounts:
                text += f"   ⚠️ *Мультиаккаунты:* {len(multi_accounts)}\n"
            
            text += "\n"
        
        if len(participants) > 50:
            text += f"\n... и еще {len(participants) - 50} участников"
        
        update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN)
        
    except ValueError:
        update.message.reply_text("❌ ID должен быть числом")
    except Exception as e:
        update.message.reply_text(f"❌ Ошибка: {str(e)}")

# ================== ОБРАБОТКА КНОПОК ==================
def button_handler(update: Update, context: CallbackContext):
    query = update.callback_query
    user_id = query.from_user.id
    
    query.answer("✅ Вы участвуете в розыгрыше!", show_alert=False)
    
    if query.data.startswith('join_'):
        giveaway_id = int(query.data.split('_')[1])
        
        if db.is_banned(user_id):
            query.answer("🚫 Вы забанены и не можете участвовать", show_alert=True)
            return
        
        if not db.is_verified(user_id):
            try:
                context.bot.send_message(
                    chat_id=user_id,
                    text="❌ *Для участия в розыгрышах необходимо пройти проверку!*\n\n"
                         "Напишите мне команду /verify",
                    parse_mode=ParseMode.MARKDOWN
                )
            except:
                query.answer(
                    "❌ Пройдите проверку! Напишите боту /verify",
                    show_alert=True
                )
            return
        
        giveaway_info = db.get_giveaway_info(giveaway_id)
        if not giveaway_info or giveaway_info[6] == 0:
            query.answer("❌ Розыгрыш уже завершен", show_alert=True)
            return
        
        end_time = datetime.fromisoformat(giveaway_info[5])
        if datetime.now() > end_time:
            query.answer("⏰ Время участия истекло", show_alert=True)
            return
        
        multi_accounts = db.check_multiple_accounts(user_id)
        if multi_accounts and len(multi_accounts) >= 2:
            query.answer(
                "⚠️ Обнаружены мультиаккаунты! Участие может быть отменено.",
                show_alert=True
            )
        
        if db.add_participant(giveaway_id, user_id):
            participants_count = db.get_participants_count(giveaway_id)
            
            try:
                context.bot.send_message(
                    chat_id=user_id,
                    text=(
                        f"✅ *Вы успешно зарегистрированы в розыгрыше!*\n\n"
                        f"🎁 *Название:* {giveaway_info[1]}\n"
                        f"👑 *Победителей:* {giveaway_info[3]}\n"
                        f"👥 *Всего участников:* {participants_count}\n"
                        f"⏰ *Завершится:* {end_time.strftime('%d.%m.%Y в %H:%M')}\n\n"
                        f"🎯 *Ваш номер в списке:* {participants_count}"
                    ),
                    parse_mode=ParseMode.MARKDOWN
                )
            except:
                query.answer(
                    f"✅ Вы участвуете! Участников: {participants_count}",
                    show_alert=True
                )
        else:
            query.answer("⚠️ Вы уже участвуете в этом розыгрыше", show_alert=True)

# ================== ЗАПУСК ==================
def main():
    if BOT_TOKEN == 'ВАШ_ТОКЕН_ЗДЕСЬ':
        print("❌ ОШИБКА: Не установлен токен бота!")
        print("1. Получите токен у @BotFather")
        print("2. Замените 'ВАШ_ТОКЕН_ЗДЕСЬ' на ваш токен")
        print("3. Запустите снова")
        return
    
    print("=" * 60)
    print("🤖 БОТ ДЛЯ РОЗЫГРЫШЕЙ С АНТИНАКРУТКОЙ")
    print("=" * 60)
    print(f"✅ Токен установлен")
    print(f"👑 Админы: {ADMIN_IDS}")
    print(f"📢 Канал: {CHANNEL_ID}")
    print("=" * 60)
    print("🔄 Обновление структуры базы данных...")
    print("✅ Все таблицы проверены и обновлены")
    print("⏳ Запуск бота...")
    
    try:
        updater = Updater(BOT_TOKEN, use_context=True)
        dp = updater.dispatcher
        
        # Команды пользователей
        dp.add_handler(CommandHandler("start", start))
        dp.add_handler(CommandHandler("verify", verify))
        dp.add_handler(CommandHandler("help", help_cmd))
        
        # Команды админов
        dp.add_handler(CommandHandler("new", new_giveaway))
        dp.add_handler(CommandHandler("list", list_giveaways))
        dp.add_handler(CommandHandler("end", end_giveaway))
        dp.add_handler(CommandHandler("stats", stats))
        dp.add_handler(CommandHandler("ban", ban_user))
        dp.add_handler(CommandHandler("unban", unban_user))
        dp.add_handler(CommandHandler("banned", banned_list))
        dp.add_handler(CommandHandler("check_multi", check_multi_accounts))
        dp.add_handler(CommandHandler("remove", remove_participant))
        dp.add_handler(CommandHandler("participants", list_participants))
        
        # Кнопки
        dp.add_handler(CallbackQueryHandler(button_handler))
        
        # Сообщения
        dp.add_handler(MessageHandler(Filters.text & ~Filters.command, handle_text))
        
        updater.start_polling()
        print("✅ Бот запущен успешно!")
        print("✋ Для остановки нажмите Ctrl+C")
        print("=" * 60)
        
        updater.idle()
        
    except Exception as e:
        print(f"❌ Ошибка запуска: {e}")

if __name__ == '__main__':
    main()