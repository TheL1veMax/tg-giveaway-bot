#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import logging
import random
import sqlite3
from datetime import datetime, timedelta
import os
import hashlib

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Updater, CommandHandler, CallbackQueryHandler, MessageHandler, CallbackContext, Filters

BOT_TOKEN = os.getenv('BOT_TOKEN', '8458068573:AAHaKHcWQZOOmTu-z2wu-7kbX8MdhonkS_M')
ADMIN_IDS = [5207853162, 5406117718]
CHANNEL_ID = "@sportgagarinmolodezh"

logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

class Database:
    def __init__(self, db_name='giveaway.db'):
        self.conn = sqlite3.connect(db_name, check_same_thread=False)
        self.cursor = self.conn.cursor()
        self.create_tables()

    def create_tables(self):
        self.cursor.execute("""CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY, username TEXT, first_name TEXT, last_name TEXT,
            joined_date TEXT NOT NULL, is_verified INTEGER DEFAULT 0, verification_date TEXT,
            verification_method TEXT, is_banned INTEGER DEFAULT 0, ban_reason TEXT,
            banned_date TEXT, ip_hash TEXT, last_activity TEXT, verification_attempts INTEGER DEFAULT 0)""")

        self.cursor.execute("""CREATE TABLE IF NOT EXISTS verification_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL,
            verification_type TEXT NOT NULL, success INTEGER NOT NULL,
            attempt_date TEXT NOT NULL, ip_hash TEXT)""")

        self.cursor.execute("""CREATE TABLE IF NOT EXISTS ban_list (
            id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL,
            admin_id INTEGER, reason TEXT, ban_date TEXT NOT NULL, unban_date TEXT)""")

        self.cursor.execute("""CREATE TABLE IF NOT EXISTS ip_addresses (
            ip_hash TEXT PRIMARY KEY, user_count INTEGER DEFAULT 1,
            first_seen TEXT NOT NULL, last_seen TEXT NOT NULL)""")

        self.cursor.execute("""CREATE TABLE IF NOT EXISTS giveaways (
            id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL, description TEXT,
            winner_count INTEGER DEFAULT 1, start_date TEXT NOT NULL, end_date TEXT NOT NULL,
            is_active INTEGER DEFAULT 1, message_id INTEGER, channel_id TEXT)""")

        self.cursor.execute("""CREATE TABLE IF NOT EXISTS participants (
            giveaway_id INTEGER NOT NULL, user_id INTEGER NOT NULL, join_date TEXT NOT NULL,
            is_valid INTEGER DEFAULT 1, referred_by INTEGER, bonus_entries INTEGER DEFAULT 0,
            PRIMARY KEY (giveaway_id, user_id))""")

        self.cursor.execute("""CREATE TABLE IF NOT EXISTS referrals (
            id INTEGER PRIMARY KEY AUTOINCREMENT, referrer_id INTEGER NOT NULL,
            referred_id INTEGER NOT NULL, giveaway_id INTEGER NOT NULL,
            referral_date TEXT NOT NULL, UNIQUE(referrer_id, referred_id, giveaway_id))""")

        self.conn.commit()

    def add_user(self, user_id, username, first_name, last_name=""):
        try:
            self.cursor.execute('SELECT user_id FROM users WHERE user_id = ?', (user_id,))
            exists = self.cursor.fetchone()
            current_time = datetime.now().isoformat()
            if exists:
                self.cursor.execute("UPDATE users SET username = ?, first_name = ?, last_name = ?, last_activity = ? WHERE user_id = ?",
                    (username, first_name, last_name, current_time, user_id))
            else:
                self.cursor.execute("INSERT INTO users (user_id, username, first_name, last_name, joined_date, last_activity, is_verified) VALUES (?, ?, ?, ?, ?, ?, 0)",
                    (user_id, username, first_name, last_name, current_time, current_time))
            self.conn.commit()
            return True
        except:
            return False

    def verify_user(self, user_id, method="captcha", ip_hash=None):
        try:
            current_time = datetime.now().isoformat()
            self.cursor.execute("UPDATE users SET is_verified = 1, verification_date = ?, verification_method = ?, verification_attempts = verification_attempts + 1 WHERE user_id = ?",
                (current_time, method, user_id))
            self.cursor.execute("INSERT INTO verification_history (user_id, verification_type, success, attempt_date, ip_hash) VALUES (?, ?, 1, ?, ?)",
                (user_id, method, current_time, ip_hash))
            self.conn.commit()
            self.cursor.execute('SELECT is_verified FROM users WHERE user_id = ?', (user_id,))
            result = self.cursor.fetchone()
            return result and result[0] == 1
        except:
            self.conn.rollback()
            return False

    def is_verified(self, user_id):
        try:
            self.cursor.execute('SELECT is_verified FROM users WHERE user_id = ?', (user_id,))
            result = self.cursor.fetchone()
            return result and result[0] == 1
        except:
            return False

    def record_verification_attempt(self, user_id, success=False, method="captcha", ip_hash=None):
        try:
            current_time = datetime.now().isoformat()
            self.cursor.execute('UPDATE users SET verification_attempts = verification_attempts + 1 WHERE user_id = ?', (user_id,))
            self.cursor.execute("INSERT INTO verification_history (user_id, verification_type, success, attempt_date, ip_hash) VALUES (?, ?, ?, ?, ?)",
                (user_id, method, 1 if success else 0, current_time, ip_hash))
            self.conn.commit()
            return True
        except:
            return False

    def get_verification_info(self, user_id):
        try:
            self.cursor.execute('SELECT is_verified, verification_date, verification_method, verification_attempts FROM users WHERE user_id = ?', (user_id,))
            return self.cursor.fetchone()
        except:
            return None

    def get_verification_history(self, user_id, limit=10):
        try:
            self.cursor.execute("SELECT verification_type, success, attempt_date, ip_hash FROM verification_history WHERE user_id = ? ORDER BY attempt_date DESC LIMIT ?",
                (user_id, limit))
            return self.cursor.fetchall()
        except:
            return []

    def update_user_activity(self, user_id):
        try:
            self.cursor.execute('UPDATE users SET last_activity = ? WHERE user_id = ?', (datetime.now().isoformat(), user_id))
            self.conn.commit()
        except:
            pass

    def ban_user(self, user_id, admin_id, reason="Нарушение", days=30):
        try:
            current_time = datetime.now()
            unban_date = current_time + timedelta(days=days)
            self.cursor.execute("INSERT INTO ban_list (user_id, admin_id, reason, ban_date, unban_date) VALUES (?, ?, ?, ?, ?)",
                (user_id, admin_id, reason, current_time.isoformat(), unban_date.isoformat()))
            self.cursor.execute('UPDATE users SET is_banned = 1, ban_reason = ?, banned_date = ? WHERE user_id = ?',
                (reason, current_time.isoformat(), user_id))
            self.cursor.execute('UPDATE participants SET is_valid = 0 WHERE user_id = ?', (user_id,))
            self.conn.commit()
            return True
        except:
            return False

    def unban_user(self, user_id):
        try:
            self.cursor.execute('UPDATE users SET is_banned = 0, ban_reason = NULL, banned_date = NULL WHERE user_id = ?', (user_id,))
            self.conn.commit()
            return True
        except:
            return False

    def is_banned(self, user_id):
        try:
            self.cursor.execute('SELECT is_banned FROM users WHERE user_id = ?', (user_id,))
            result = self.cursor.fetchone()
            return result and result[0] == 1
        except:
            return False

    def get_ban_info(self, user_id):
        try:
            self.cursor.execute('SELECT ban_reason, banned_date FROM users WHERE user_id = ? AND is_banned = 1', (user_id,))
            return self.cursor.fetchone()
        except:
            return None

    def get_banned_users(self):
        try:
            self.cursor.execute('SELECT user_id, username, first_name, ban_reason, banned_date FROM users WHERE is_banned = 1 ORDER BY banned_date DESC')
            return self.cursor.fetchall()
        except:
            return []

    def add_ip_address(self, user_id, ip_address):
        try:
            ip_hash = hashlib.sha256(ip_address.encode()).hexdigest()[:32]
            current_time = datetime.now().isoformat()
            self.cursor.execute('UPDATE users SET ip_hash = ? WHERE user_id = ?', (ip_hash, user_id))
            self.cursor.execute('SELECT user_count FROM ip_addresses WHERE ip_hash = ?', (ip_hash,))
            exists = self.cursor.fetchone()
            if exists:
                self.cursor.execute('UPDATE ip_addresses SET user_count = user_count + 1, last_seen = ? WHERE ip_hash = ?', (current_time, ip_hash))
            else:
                self.cursor.execute('INSERT INTO ip_addresses (ip_hash, user_count, first_seen, last_seen) VALUES (?, 1, ?, ?)', (ip_hash, current_time, current_time))
            self.conn.commit()
            return ip_hash
        except:
            return None

    def get_suspicious_ips(self, threshold=2):
        try:
            self.cursor.execute('SELECT ip_hash, user_count, last_seen FROM ip_addresses WHERE user_count >= ? ORDER BY user_count DESC', (threshold,))
            return self.cursor.fetchall()
        except:
            return []

    def get_users_by_ip(self, ip_hash):
        try:
            self.cursor.execute('SELECT user_id, username, first_name, joined_date FROM users WHERE ip_hash = ? ORDER BY joined_date', (ip_hash,))
            return self.cursor.fetchall()
        except:
            return []

    def check_multiple_accounts(self, user_id):
        try:
            self.cursor.execute('SELECT user_id FROM users WHERE ip_hash = (SELECT ip_hash FROM users WHERE user_id = ?) AND user_id != ?', (user_id, user_id))
            return [row[0] for row in self.cursor.fetchall()]
        except:
            return []

    def create_giveaway(self, name, description, winners, hours, channel_id):
        try:
            start_date = datetime.now()
            end_date = start_date + timedelta(hours=hours)
            self.cursor.execute("INSERT INTO giveaways (name, description, winner_count, start_date, end_date, is_active, channel_id) VALUES (?, ?, ?, ?, ?, 1, ?)",
                (name, description, winners, start_date.isoformat(), end_date.isoformat(), channel_id))
            self.conn.commit()
            return self.cursor.lastrowid
        except:
            return None

    def update_message_id(self, giveaway_id, message_id):
        try:
            self.cursor.execute('UPDATE giveaways SET message_id = ? WHERE id = ?', (message_id, giveaway_id))
            self.conn.commit()
        except:
            pass

    def add_participant(self, giveaway_id, user_id, referred_by=None):
        try:
            current_time = datetime.now().isoformat()
            self.cursor.execute('INSERT INTO participants (giveaway_id, user_id, join_date, referred_by) VALUES (?, ?, ?, ?)',
                (giveaway_id, user_id, current_time, referred_by))
            if referred_by:
                try:
                    self.cursor.execute('INSERT INTO referrals (referrer_id, referred_id, giveaway_id, referral_date) VALUES (?, ?, ?, ?)',
                        (referred_by, user_id, giveaway_id, current_time))
                    self.cursor.execute('UPDATE participants SET bonus_entries = bonus_entries + 1 WHERE giveaway_id = ? AND user_id = ?',
                        (giveaway_id, referred_by))
                except:
                    pass
            self.conn.commit()
            return True
        except:
            return False

    def get_referral_count(self, user_id, giveaway_id):
        try:
            self.cursor.execute('SELECT COUNT(*) FROM referrals WHERE referrer_id = ? AND giveaway_id = ?', (user_id, giveaway_id))
            return self.cursor.fetchone()[0]
        except:
            return 0

    def get_bonus_entries(self, user_id, giveaway_id):
        try:
            self.cursor.execute('SELECT bonus_entries FROM participants WHERE giveaway_id = ? AND user_id = ?', (giveaway_id, user_id))
            result = self.cursor.fetchone()
            return result[0] if result else 0
        except:
            return 0

    def remove_participant(self, giveaway_id, user_id):
        try:
            self.cursor.execute('UPDATE participants SET is_valid = 0 WHERE giveaway_id = ? AND user_id = ?', (giveaway_id, user_id))
            self.conn.commit()
            return self.cursor.rowcount > 0
        except:
            return False

    def get_active_giveaways(self):
        try:
            self.cursor.execute('SELECT id, name, winner_count, end_date FROM giveaways WHERE is_active = 1 ORDER BY end_date')
            return self.cursor.fetchall()
        except:
            return []

    def get_giveaway_info(self, giveaway_id):
        try:
            self.cursor.execute('SELECT * FROM giveaways WHERE id = ?', (giveaway_id,))
            return self.cursor.fetchone()
        except:
            return None

    def get_participants(self, giveaway_id, valid_only=True):
        try:
            if valid_only:
                self.cursor.execute('SELECT user_id FROM participants WHERE giveaway_id = ? AND is_valid = 1', (giveaway_id,))
            else:
                self.cursor.execute('SELECT user_id FROM participants WHERE giveaway_id = ?', (giveaway_id,))
            return [row[0] for row in self.cursor.fetchall()]
        except:
            return []

    def get_participants_with_info(self, giveaway_id):
        try:
            self.cursor.execute("SELECT p.user_id, u.username, u.first_name, u.is_banned, p.join_date FROM participants p LEFT JOIN users u ON p.user_id = u.user_id WHERE p.giveaway_id = ? AND p.is_valid = 1 ORDER BY p.join_date",
                (giveaway_id,))
            return self.cursor.fetchall()
        except:
            return []

    def get_participants_count(self, giveaway_id):
        try:
            self.cursor.execute('SELECT COUNT(*) FROM participants WHERE giveaway_id = ? AND is_valid = 1', (giveaway_id,))
            return self.cursor.fetchone()[0]
        except:
            return 0

    def end_giveaway(self, giveaway_id):
        try:
            self.cursor.execute('UPDATE giveaways SET is_active = 0 WHERE id = ?', (giveaway_id,))
            self.conn.commit()
            return True
        except:
            return False

db = Database()
captcha_storage = {}

def generate_captcha():
    a = random.randint(1, 10)
    b = random.randint(1, 10)
    operations = ['+', '-', '*']
    operation = random.choice(operations)
    if operation == '+':
        answer = a + b
        question = str(a) + " + " + str(b)
    elif operation == '-':
        answer = a - b
        question = str(a) + " - " + str(b)
    else:
        answer = a * b
        question = str(a) + " x " + str(b)
    return question, str(answer)

def extract_ip_from_request(update):
    user = update.effective_user
    return str(user.id) + "." + str(hash(str(user.id)) % 255) + "." + str(hash(user.username or '') % 255)

def is_admin(user_id):
    return user_id in ADMIN_IDS

def start(update, context):
    user = update.effective_user
    db.add_user(user.id, user.username or "", user.first_name, user.last_name or "")
    db.update_user_activity(user.id)
    try:
        ip = extract_ip_from_request(update)
        db.add_ip_address(user.id, ip)
    except:
        pass
    if db.is_banned(user.id):
        update.message.reply_text("Вы забанены")
        return
    if context.args and context.args[0].startswith('ref_'):
        try:
            parts = context.args[0].split('_')
            if len(parts) == 3:
                giveaway_id = int(parts[1])
                referrer_id = int(parts[2])
                context.user_data['referrer'] = referrer_id
                context.user_data['giveaway'] = giveaway_id
                update.message.reply_text("Привет! Сначала пройдите проверку: /verify")
                return
        except:
            pass
    text = "Привет, " + user.first_name + "!\n\nБот для розыгрышей\n\n/verify - Пройти проверку\n/my_referrals - Мои рефералы\n/help - Помощь"
    update.message.reply_text(text)

def verify(update, context):
    if update.message.chat.type != 'private':
        update.message.reply_text("Только в личных сообщениях!")
        return
    user_id = update.effective_user.id
    if db.is_banned(user_id):
        update.message.reply_text("Вы забанены")
        return
    if db.is_verified(user_id):
        update.message.reply_text("Вы уже верифицированы!")
        return
    question, answer = generate_captcha()
    ip = extract_ip_from_request(update)
    ip_hash = hashlib.sha256(ip.encode()).hexdigest()[:32]
    captcha_storage[user_id] = {'answer': answer, 'attempts': 0, 'time': datetime.now(), 'ip_hash': ip_hash}
    update.message.reply_text("Пройдите проверку\n\nРешите: " + question + " = ?\n\nОтправьте ответ числом.")

def handle_text(update, context):
    if update.message.chat.type != 'private':
        return
    user_id = update.effective_user.id
    text = update.message.text.strip()
    if db.is_banned(user_id):
        return
    if user_id in captcha_storage:
        captcha = captcha_storage[user_id]
        if datetime.now() - captcha['time'] > timedelta(minutes=5):
            update.message.reply_text("Время вышло. /verify")
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
                    update.message.reply_text("Обнаружены мультиаккаунты.")
                update.message.reply_text("Проверка пройдена!\n\nТеперь можете участвовать!")
            else:
                update.message.reply_text("Ошибка! Попробуйте /verify")
        else:
            captcha['attempts'] += 1
            db.record_verification_attempt(user_id, success=False, ip_hash=captcha.get('ip_hash'))
            if captcha['attempts'] >= 3:
                update.message.reply_text("Попытки закончились. /verify")
                del captcha_storage[user_id]
            else:
                left = 3 - captcha['attempts']
                update.message.reply_text("Неверно. Осталось: " + str(left))

def my_referrals(update, context):
    user_id = update.effective_user.id
    if db.is_banned(user_id):
        update.message.reply_text("Вы забанены")
        return
    if not db.is_verified(user_id):
        update.message.reply_text("Сначала пройдите проверку: /verify")
        return
    active_giveaways = db.get_active_giveaways()
    if not active_giveaways:
        update.message.reply_text("Нет активных розыгрышей")
        return
    text = "Ваши реферальные ссылки:\n\n"
    for g in active_giveaways:
        gid, name, winners, end_date = g
        referral_count = db.get_referral_count(user_id, gid)
        bonus_entries = db.get_bonus_entries(user_id, gid)
        bot_username = context.bot.get_me().username
        ref_link = "https://t.me/" + bot_username + "?start=ref_" + str(gid) + "_" + str(user_id)
        text += name + "\n" + ref_link + "\nПриглашено: " + str(referral_count) + "\nБонусов: " + str(bonus_entries) + "\n------\n"
    text += "\nОтправьте ссылку друзьям!"
    update.message.reply_text(text)

def help_cmd(update, context):
    user_id = update.effective_user.id
    text = "Помощь\n\nПользователь:\n/start - Начать\n/verify - Проверка\n/my_referrals - Рефералы\n/help - Помощь\n"
    if is_admin(user_id):
        text += "\nАдмин:\n/new - Создать\n/list - Список\n/end - Завершить\n/stats - Статистика\n/participants - Участники\n/remove - Удалить\n/ban - Забанить\n/unban - Разбанить\n/banned - Забаненные\n/check_multi - Мультиаккаунты\n/verify_info - Инфо\n"
    update.message.reply_text(text)

def new_giveaway(update, context):
    if not is_admin(update.effective_user.id):
        update.message.reply_text("Нет прав")
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
        update.message.reply_text("Ошибка создания")
        return
    end_time = datetime.now() + timedelta(hours=hours)
    keyboard = [[InlineKeyboardButton("Участвовать", callback_data="join_" + str(giveaway_id))]]
    markup = InlineKeyboardMarkup(keyboard)
    try:
        message = context.bot.send_message(chat_id=CHANNEL_ID, text="НОВЫЙ РОЗЫГРЫШ!\n\n" + name + "\n" + description + "\n\nПобедителей: " + str(winners) + "\nЗавершится: " + end_time.strftime('%d.%m.%Y в %H:%M') + "\n\nНажмите кнопку!", reply_markup=markup)
        db.update_message_id(giveaway_id, message.message_id)
        update.message.reply_text("Розыгрыш создан! ID: " + str(giveaway_id))
    except Exception as e:
        update.message.reply_text("Ошибка: " + str(e))

def list_giveaways(update, context):
    if not is_admin(update.effective_user.id):
        update.message.reply_text("Нет прав")
        return
    giveaways = db.get_active_giveaways()
    if not giveaways:
        update.message.reply_text("Нет розыгрышей")
        return
    text = "Активные розыгрыши:\n\n"
    for g in giveaways:
        gid, name, winners, end_date = g
        participants = db.get_participants_count(gid)
        text += "ID: " + str(gid) + "\n" + name + "\nУчастников: " + str(participants) + "\n------\n"
    update.message.reply_text(text)

def end_giveaway(update, context):
    if not is_admin(update.effective_user.id):
        update.message.reply_text("Нет прав")
        return
    if not context.args:
        update.message.reply_text("Использование: /end <id>")
        return
    try:
        giveaway_id = int(context.args[0])
        participants = db.get_participants(giveaway_id)
        if not participants:
            update.message.reply_text("Нет участников")
            return
        giveaway_info = db.get_giveaway_info(giveaway_id)
        if not giveaway_info:
            update.message.reply_text("Не найден")
            return
        winner_count = min(giveaway_info[3], len(participants))
        winners = random.sample(participants, winner_count)
        winners_text = "ПОБЕДИТЕЛИ!\n\n"
        for i, winner_id in enumerate(winners, 1):
            try:
                user = context.bot.get_chat(winner_id)
                username = "@" + user.username if user.username else user.first_name
                winners_text += str(i) + ". " + username + "\n"
            except:
                winners_text += str(i) + ". ID: " + str(winner_id) + "\n"
        db.end_giveaway(giveaway_id)
        try:
            context.bot.send_message(chat_id=CHANNEL_ID, text=winners_text)
        except:
            pass
        update.message.reply_text("Завершен!\n\n" + winners_text)
    except Exception as e:
        update.message.reply_text("Ошибка: " + str(e))

def stats(update, context):
    if not is_admin(update.effective_user.id):
        update.message.reply_text("Нет прав")
        return
    if not context.args:
        update.message.reply_text("Использование: /stats <id>")
        return
    try:
        giveaway_id = int(context.args[0])
        giveaway_info = db.get_giveaway_info(giveaway_id)
        if not giveaway_info:
            update.message.reply_text("Не найден")
            return
        participants_count = db.get_participants_count(giveaway_id)
        _, name, description, winners, start_date, end_date, is_active, _, _ = giveaway_info
        start = datetime.fromisoformat(start_date)
        end = datetime.fromisoformat(end_date)
        status = "Активен" if is_active == 1 else "Завершен"
        text = "Статистика #" + str(giveaway_id) + "\n\n" + name + "\n" + description + "\nПобедителей: " + str(winners) + "\nУчастников: " + str(participants_count) + "\nСтатус: " + status + "\n\n" + start.strftime('%d.%m %H:%M') + " - " + end.strftime('%d.%m %H:%M')
        update.message.reply_text(text)
    except Exception as e:
        update.message.reply_text("Ошибка: " + str(e))

def participants_cmd(update, context):
    if not is_admin(update.effective_user.id):
        update.message.reply_text("Нет прав")
        return
    if not context.args:
        update.message.reply_text("Использование: /participants <id>")
        return
    try:
        giveaway_id = int(context.args[0])
        participants = db.get_participants_with_info(giveaway_id)
        if not participants:
            update.message.reply_text("Нет участников")
            return
        giveaway_info = db.get_giveaway_info(giveaway_id)
        name = giveaway_info[1] if giveaway_info else "#" + str(giveaway_id)
        text = "Участники '" + name + "'\nВсего: " + str(len(participants)) + "\n\n"
        for i, (user_id, username, first_name, is_banned, join_date) in enumerate(participants[:50], 1):
            status = "BAN" if is_banned == 1 else "OK"
            username_str = "@" + username if username else "нет"
            text += str(i) + ". " + status + " " + first_name + " (" + username_str + ") - " + str(user_id) + "\n"
        if len(participants) > 50:
            text += "\n...и еще " + str(len(participants) - 50)
        update.message.reply_text(text)
    except Exception as e:
        update.message.reply_text("Ошибка: " + str(e))

def remove_participant(update, context):
    if not is_admin(update.effective_user.id):
        update.message.reply_text("Нет прав")
        return
    if len(context.args) < 2:
        update.message.reply_text("Использование: /remove <giveaway_id> <user_id>")
        return
    try:
        giveaway_id = int(context.args[0])
        user_id = int(context.args[1])
        if db.remove_participant(giveaway_id, user_id):
            update.message.reply_text("Участник " + str(user_id) + " удален из " + str(giveaway_id))
        else:
            update.message.reply_text("Не найден")
    except Exception as e:
        update.message.reply_text("Ошибка: " + str(e))

def ban_user(update, context):
    if not is_admin(update.effective_user.id):
        update.message.reply_text("Нет прав")
        return
    if len(context.args) < 2:
        update.message.reply_text("Использование: /ban <user_id> <причина> [дней]")
        return
    try:
        user_id = int(context.args[0])
        if len(context.args) > 2 and context.args[-1].isdigit():
            days = int(context.args[-1])
            reason = ' '.join(context.args[1:-1])
        else:
            days = 30
            reason = ' '.join(context.args[1:])
        admin_id = update.effective_user.id
        if db.ban_user(user_id, admin_id, reason, days):
            try:
                context.bot.send_message(chat_id=user_id, text="ВЫ ЗАБАНЕНЫ!\n\nПричина: " + reason + "\nСрок: " + str(days) + " дней")
            except:
                pass
            update.message.reply_text("Пользователь " + str(user_id) + " забанен\nПричина: " + reason + "\nСрок: " + str(days) + " дней")
        else:
            update.message.reply_text("Ошибка")
    except Exception as e:
        update.message.reply_text("Ошибка: " + str(e))

def unban_user(update, context):
    if not is_admin(update.effective_user.id):
        update.message.reply_text("Нет прав")
        return
    if not context.args:
        update.message.reply_text("Использование: /unban <user_id>")
        return
    try:
        user_id = int(context.args[0])
        if db.unban_user(user_id):
            try:
                context.bot.send_message(chat_id=user_id, text="Вы разбанены!")
            except:
                pass
            update.message.reply_text("Пользователь " + str(user_id) + " разбанен")
        else:
            update.message.reply_text("Ошибка")
    except Exception as e:
        update.message.reply_text("Ошибка: " + str(e))

def banned_list(update, context):
    if not is_admin(update.effective_user.id):
        update.message.reply_text("Нет прав")
        return
    banned_users = db.get_banned_users()
    if not banned_users:
        update.message.reply_text("Нет забаненных")
        return
    text = "Забаненные (" + str(len(banned_users)) + ")\n\n"
    for user in banned_users[:30]:
        user_id, username, first_name, reason, ban_date = user
        ban_dt = datetime.fromisoformat(ban_date) if ban_date else None
        date_str = ban_dt.strftime('%d.%m.%Y') if ban_dt else 'неизвестно'
        username_str = "@" + username if username else "нет"
        text += first_name + " (" + username_str + ") - " + str(user_id) + "\n" + reason + "\nДата: " + date_str + "\n------\n"
    if len(banned_users) > 30:
        text += "\n...и еще " + str(len(banned_users) - 30)
    update.message.reply_text(text)

def check_multi(update, context):
    if not is_admin(update.effective_user.id):
        update.message.reply_text("Нет прав")
        return
    threshold = int(context.args[0]) if context.args and context.args[0].isdigit() else 2
    suspicious_ips = db.get_suspicious_ips(threshold)
    if not suspicious_ips:
        update.message.reply_text("Не найдено IP с " + str(threshold) + "+ аккаунтами")
        return
    text = "Подозрительные IP (" + str(threshold) + "+):\n\n"
    for ip_hash, user_count, last_seen in suspicious_ips[:10]:
        users = db.get_users_by_ip(ip_hash)
        text += "IP: " + ip_hash[:16] + "...\nАккаунтов: " + str(user_count) + "\n"
        for user in users[:5]:
            user_id, username, first_name, joined_date = user
            username_str = "@" + username if username else "нет"
            text += "  " + first_name + " (" + username_str + ") - " + str(user_id) + "\n"
        if len(users) > 5:
            text += "  ...и еще " + str(len(users) - 5) + "\n"
        text += "------\n"
    if len(suspicious_ips) > 10:
        text += "\n...и еще " + str(len(suspicious_ips) - 10)
    update.message.reply_text(text)

def verify_info(update, context):
    if not is_admin(update.effective_user.id):
        update.message.reply_text("Нет прав")
        return
    if not context.args:
        update.message.reply_text("Использование: /verify_info <user_id>")
        return
    try:
        user_id = int(context.args[0])
        info = db.get_verification_info(user_id)
        if not info:
            update.message.reply_text("Пользователь " + str(user_id) + " не найден")
            return
        is_verified, ver_date, ver_method, attempts = info
        text = "Верификация " + str(user_id) + "\n\n"
        text += "Статус: " + ("Верифицирован" if is_verified == 1 else "НЕ верифицирован") + "\n"
        if ver_date:
            ver_dt = datetime.fromisoformat(ver_date)
            text += "Дата: " + ver_dt.strftime('%d.%m.%Y %H:%M') + "\n"
        if ver_method:
            text += "Метод: " + ver_method + "\n"
        text += "Попыток: " + str(attempts) + "\n"
        history = db.get_verification_history(user_id, 5)
        if history:
            text += "\nПоследние попытки:\n"
            for ver_type, success, attempt_date, ip_hash in history:
                attempt_dt = datetime.fromisoformat(attempt_date)
                status_icon = "OK" if success == 1 else "FAIL"
                text += status_icon + " " + attempt_dt.strftime('%d.%m %H:%M') + "\n"
        update.message.reply_text(text)
    except Exception as e:
        update.message.reply_text("Ошибка: " + str(e))

def button_handler(update, context):
    query = update.callback_query
    user_id = query.from_user.id
    try:
        query.answer()
    except:
        pass
    if query.data.startswith('join_'):
        giveaway_id = int(query.data.split('_')[1])
        if db.is_banned(user_id):
            query.answer("Вы забанены", show_alert=True)
            return
        if not db.is_verified(user_id):
            try:
                context.bot.send_message(chat_id=user_id, text="Необходима верификация!\n\nНапишите /verify")
                query.answer("Пройдите проверку!", show_alert=True)
            except:
                query.answer("Напишите боту /verify", show_alert=True)
            return
        giveaway_info = db.get_giveaway_info(giveaway_id)
        if not giveaway_info or giveaway_info[6] == 0:
            query.answer("Розыгрыш завершен", show_alert=True)
            return
        end_time = datetime.fromisoformat(giveaway_info[5])
        if datetime.now() > end_time:
            query.answer("Время истекло", show_alert=True)
            return
        multi_accounts = db.check_multiple_accounts(user_id)
        if multi_accounts and len(multi_accounts) >= 2:
            query.answer("Обнаружены мультиаккаунты!", show_alert=True)
        referrer_id = context.user_data.get('referrer') if context.user_data.get('giveaway') == giveaway_id else None
        if db.add_participant(giveaway_id, user_id, referred_by=referrer_id):
            participants_count = db.get_participants_count(giveaway_id)
            if 'referrer' in context.user_data:
                del context.user_data['referrer']
            if 'giveaway' in context.user_data:
                del context.user_data['giveaway']
            try:
                context.bot.send_message(chat_id=user_id, text="Вы участвуете!\n\n" + giveaway_info[1] + "\nПобедителей: " + str(giveaway_info[3]) + "\nУчастников: " + str(participants_count) + "\n\nИспользуйте /my_referrals")
            except:
                pass
            query.answer("Вы участвуете! Всего: " + str(participants_count), show_alert=True)
        else:
            query.answer("Вы уже участвуете", show_alert=True)

def main():
    print("="*70)
    print("БОТ ДЛЯ РОЗЫГРЫШЕЙ")
    print("="*70)
    print("Токен: " + BOT_TOKEN[:15] + "...")
    print("Админы: " + str(ADMIN_IDS))
    print("Канал: " + CHANNEL_ID)
    print("="*70)
    try:
        updater = Updater(BOT_TOKEN, use_context=True)
        dp = updater.dispatcher
        dp.add_handler(CommandHandler("start", start))
        dp.add_handler(CommandHandler("verify", verify))
        dp.add_handler(CommandHandler("my_referrals", my_referrals))
        dp.add_handler(CommandHandler("help", help_cmd))
        dp.add_handler(CommandHandler("new", new_giveaway))
        dp.add_handler(CommandHandler("list", list_giveaways))
        dp.add_handler(CommandHandler("end", end_giveaway))
        dp.add_handler(CommandHandler("stats", stats))
        dp.add_handler(CommandHandler("participants", participants_cmd))
        dp.add_handler(CommandHandler("remove", remove_participant))
        dp.add_handler(CommandHandler("ban", ban_user))
        dp.add_handler(CommandHandler("unban", unban_user))
        dp.add_handler(CommandHandler("banned", banned_list))
        dp.add_handler(CommandHandler("check_multi", check_multi))
        dp.add_handler(CommandHandler("verify_info", verify_info))
        dp.add_handler(CallbackQueryHandler(button_handler))
        dp.add_handler(MessageHandler(Filters.text & ~Filters.command, handle_text))
        updater.start_polling()
        print("="*70)
        print("БОТ ЗАПУЩЕН!")
        print("="*70)
        updater.idle()
    except Exception as e:
        logger.error("Ошибка: " + str(e))
        print("Ошибка: " + str(e))

if __name__ == '__main__':
    main()
