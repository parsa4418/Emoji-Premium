# -*- coding: utf-8 -*-
"""
بات شرط‌بندی الماس با Webhook - نسخه Supabase (کامل)
اضافه شده: پنل مدیریت، سیستم تورنومنت، رفع باگ شرط
"""

import os
import random
import re
import string
import time
import threading
import itertools
import logging
import json
import html
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from flask import Flask, request
import telebot
from telebot import types
from supabase import create_client, Client
from dotenv import load_dotenv
from apscheduler.schedulers.background import BackgroundScheduler

# ================== استایل رنگی دکمه‌های تلگرام ==================
def colored_button(*args, **kwargs):
    """ساخت دکمه Inline با یکی از سه استایل رسمی Telegram: primary/success/danger.
    رنگ بر اساس متن دکمه به‌صورت خودکار انتخاب می‌شود.
    """
    if "style" in kwargs:
        return types.InlineKeyboardButton(*args, **kwargs)

    text = str(args[0] if args else kwargs.get("text", "")).lower()

    danger_words = (
        "لغو", "انصراف", "خیر", "بستن", "حذف", "پاک", "رد", "بازگشت", "مالیات",
        "cancel", "close", "delete", "no", "reject"
    )
    success_words = (
        "بله", "تأیید", "تایید", "خرید", "برداشت", "واریز", "دریافت",
        "شروع", "پیوستن", "ارتقا", "فعال", "قبول", "انجام", "ثبت",
        "جایزه", "برداشت الماس", "yes", "confirm", "buy", "start", "join",
        "upgrade", "claim"
    )

    if any(word in text for word in danger_words):
        style = "danger"
    elif any(word in text for word in success_words):
        style = "success"
    else:
        style = "primary"

    try:
        button = types.InlineKeyboardButton(*args, **kwargs)
        # در نسخه‌های جدید pyTelegramBotAPI این فیلد مستقیماً پشتیبانی می‌شود؛
        # در نسخه‌های قدیمی‌تر هم اضافه‌کردن attribute باعث می‌شود serializer آن را بفرستد.
        setattr(button, "style", style)
        return button
    except TypeError:
        # اگر نسخه قدیمی کتابخانه style را در سازنده قبول نکند، دکمه عادی ساخته می‌شود.
        # (برای فعال شدن رنگ‌ها، کتابخانه باید نسخه‌ای با پشتیبانی style داشته باشد.)
        return types.InlineKeyboardButton(*args, **kwargs)

load_dotenv()

# ================== تنظیمات ==================
BOT_TOKEN = os.environ.get("BOT_TOKEN", "توکن-خودت-رو-اینجا-بذار")
ADMIN_IDS = [8904869158, 8196150649,]  # آیدی عددی خود را اینجا قرار دهید
START_DIAMONDS = 25000
TAX_RATE = 0.10
TAX_RECEIVER_ID = ADMIN_IDS[0]
JOIN_TIMEOUT_SECONDS = 60

# ================== الماس تصادفی گروه ==================
DIAMOND_HUNT_MESSAGE_INTERVAL = 200
DIAMOND_HUNT_COSTS = [100, 200, 400]
DIAMOND_HUNT_WIN_CHANCES = [0.30, 0.50, 0.70]
DIAMOND_HUNT_REASONS = [
    "باعث شد الماس از دستش بیافته و بشکنه❌",
    "باعث شد الماس گم بشه❌",
    "باعث شد الماس از دستش لیز بخوره و بشکنه❌",
    "باعث شد الماس ناپدید بشه❌",
    "باعث شد الماس توسط یک نفر دزدیده بشه❌",
    "باعث شد الماس از بین بره❌",
]

SPIN_MIN = 100
SPIN_MAX = 500
SPIN_COOLDOWN_HOURS = 24

LOAN_MAX = 1_000
LOAN_TAX_RATE = 0.10

# ================== سیستم سطح‌بندی (Leveling) ==================
# هر آیتم: (سطح، عنوان، XP لازم برای رسیدن به این سطح، پاداش الماس هنگام رسیدن به این سطح)
LEVELS = [
    (1,  "الماس‌یاب تازه‌کار",   0,          0),
    (2,  "الماس‌یاب مبتدی",      100,        500),
    (3,  "الماس‌یاب کارآموز",    250,        650),
    (4,  "الماس‌یاب نیمه‌حرفه‌ای", 500,        900),
    (5,  "الماس‌یاب حرفه‌ای",     800,        1_200),
    (6,  "الماس‌یاب خبره",       1_200,      1_600),
    (7,  "استاد الماس‌یابی",      1_800,      2_100),
    (8,  "افسانه الماس‌یابی",     2_500,      2_800),
    (9,  "سلطان الماس",          3_500,      3_700),
    (10, "پادشاه الماس",         5_000,      5_000),
]
MAX_LEVEL = LEVELS[-1][0]

XP_PER_MESSAGE = 1
XP_PER_BET_WIN = 10
XP_PER_CASINO_WIN = 15
XP_PER_DIAMOND_HUNT_WIN = 50
XP_PER_TOURNAMENT_WIN = 100
XP_PER_DAILY_GIFT = 5
XP_BONUS_PER_CASINO_100K = 1     # هر ۱۰۰,۰۰۰ الماس برد در کازینو ۱ XP اضافه
XP_BONUS_CASINO_CAP = 50

# ================== پاداش گفتن کلمه «الماس» ==================
# با گفتن کلمه «الماس» در گروه، کاربر بر اساس سطح فعلی‌اش الماس می‌گیرد
# (و به‌جای XP هر پیام، فقط برای همین پیام‌ها XP می‌گیرد؛ نرخ XP طبق
# جام‌های msg_100 / msg_500 مثل قبل بالا می‌رود: 1 -> 2 -> 5).
WORD_DIAMOND_COOLDOWN_SECONDS = 5 * 60  # فاصله زمانی بین هر بار گرفتن الماس با گفتن کلمه
WORD_DIAMOND_REWARD_BY_LEVEL = {
    1: 100,
    2: 200,
    3: 300,
    4: 400,
    5: 500,
    6: 600,
    7: 700,
    8: 800,
    9: 900,
    10: 1000,
}

# ================== سیستم جام‌ها (Trophies) ==================
# کلید → (عنوان نمایشی، توضیح)
TROPHIES = {
    "msg_100":       ("📝 تازه‌وارد",         "اولین قدم رو برداشتی! از این به بعد به‌ازای هر پیام ۲ XP می‌گیری."),
    "msg_500":       ("🗣️ پرحرف",            "عاشق حرف زدنه! از این به بعد به‌ازای هر پیام ۵ XP می‌گیری."),
    "bet_10":        ("🎲 قمارباز",          "وارد بازی شدی!"),
    "bet_50":        ("🎲🎲 قمارباز حرفه‌ای", "🎁 از این به بعد فقط ۸٪ مالیات از شرط‌بندی معمولی می‌دی (۲٪ کمتر)."),
    "bet_100":       ("🎲🎲🎲 سلطان قمار",    "🎁 از این به بعد فقط ۵٪ مالیات از شرط‌بندی معمولی و ۸٪ مالیات وام می‌دی."),
    "casino_50":     ("🎰 حرفه‌ای در کازینو", "🎁 از این به بعد فقط ۸٪ مالیات از کازینو می‌دی (۲٪ کمتر)."),
    "casino_100":    ("🎰🎰 سلطان کازینو",   "🎁 از این به بعد فقط ۵٪ مالیات از کازینو و ۸٪ مالیات وام می‌دی."),
    "wealth_1m":     ("💰 میلیونر",          "میلیونر شدی!"),
    "wealth_10m":    ("🏦 سرمایه‌دار",       "سرمایه‌دار شدی!"),
    "wealth_1b":     ("👑 میلیاردر",         "میلیاردر شدی!"),
    "tournament_win": ("🏆 قهرمان تورنومنت", "بهترینی!"),
    # جام نادر (فقط از طریق جعبه شانس)
    "rare_diamond":  ("💎 جام الماس",        "جایزه ویژه جعبه شانس! همراهش ۱۰,۰۰۰,۰۰۰ 💎 هدیه می‌گیری."),
}
# آستانه‌های پیام / شرط / کازینو برای اعطای خودکار جام
MSG_TROPHY_THRESHOLDS = [(100, "msg_100"), (500, "msg_500")]
BET_WIN_TROPHY_THRESHOLDS = [(10, "bet_10"), (50, "bet_50"), (100, "bet_100")]
CASINO_WIN_TROPHY_THRESHOLDS = [(50, "casino_50"), (100, "casino_100")]
WEALTH_TROPHY_THRESHOLDS = [(1_000_000, "wealth_1m"), (10_000_000, "wealth_10m"), (1_000_000_000, "wealth_1b")]
RARE_TROPHY_KEYS = ["rare_diamond"]
RARE_TROPHY_DIAMOND_REWARD = 5_000

# ================== لقب‌های ویژه (جعبه شانس حذف شد؛ لقب‌ها نگه داشته شده‌اند) ==================
LOOTBOX_TAGS = ["🗣️ خوشتیپ", "🗿 کصخل", "🎲 قمارباز", "🤌 بچه مثبت", "💰 بچه پولدار", "❤️ عشق", "😍 خوشگله", "🧑‍🦯 بچه روبیکایی", "🤓 نمک"]

# ================== تنظیمات پیش‌فرض اعلان‌های گروه ==================
NOTIFY_DEFAULTS = {
    "level_up": True,
    "trophy": True,
    "new_diamond": True,
    "daily_gift": False,
    "diamond_timer": True,
    "betting": False,
    "tournament": True,
}
NOTIFY_LABELS = {
    "level_up": "🏆 ارتقا سطح",
    "trophy": "🏅 دریافت جام",
    "new_diamond": "💎 الماس جدید",
    "daily_gift": "🎁 هدیه روزانه",
    "diamond_timer": "⏰ تایمر الماس",
    "betting": "🎲 شرط‌بندی",
    "tournament": "🏆 تورنومنت",
}

# ================== تنظیمات بانک ==================
BANK_OPENING_FEE = 5_000
BANK_INTEREST_RATE = 0.03
BANK_DAILY_INTEREST_MAX = 1_000
TEHRAN_TZ = ZoneInfo("Asia/Tehran")

bot = telebot.TeleBot(BOT_TOKEN)

# ================== ریپلای خودکار روی پیام کاربر ==================
# کاربر خواسته هر وقت چیزی می‌فرسته (مثلاً «موجودی») و بات پیام جدیدی در
# جواب می‌فرسته، اون پیام به‌صورت ریپلای روی پیام خودِ کاربر باشه (نه یه
# پیام جدای معلق توی چت). به‌جای دستکاری تک‌تک صدها جای فایل که
# bot.send_message صدا می‌زنن، خودِ متد send_message رو Wrap می‌کنیم: هر
# وقت داریم داخل پردازش یک «پیام متنی از کاربر» هستیم (نه یک callback
# دکمه)، و صدازننده صریحاً reply_to_message_id نداده، خودکار reply_to همون
# پیام کاربر ست می‌شه. برای هر ترد/ریکوئست جدا نگه داشته می‌شه تا در حالت
# threaded با هم قاطی نشن.
_reply_ctx = threading.local()

# Keep the original pyTelegramBotAPI methods. All Telegram traffic that can be
# generated by this file is routed through the small gate below. The goal is
# not to drop work: requests are serialized and a Telegram 429 is respected.
_original_send_message = bot.send_message
_original_edit_message_text = bot.edit_message_text
_original_edit_message_reply_markup = bot.edit_message_reply_markup
_original_delete_message = bot.delete_message
_original_answer_callback_query = bot.answer_callback_query

# ================== Telegram API durability / rate-limit gate ==================
# قبلاً یک RLock سراسری هم دور محاسبه‌ی نوبت‌دهی و هم دور *خودِ درخواست شبکه‌ای*
# تلگرام گرفته می‌شد؛ یعنی در تمام مدتی که منتظر پاسخ تلگرام بودیم (صد میلی‌ثانیه‌ها)
# هیچ پیام دیگری از هیچ کاربر/گروه دیگری هم نمی‌توانست ارسال/ویرایش شود — کل بات
# عملاً تک‌نفره می‌شد. الان لاک فقط دور بخش حسابداریِ نوبت‌دهی (چند خط، بدون I/O)
# گرفته می‌شود؛ خودِ sleep و خودِ درخواست شبکه‌ای بیرون از لاک انجام می‌شوند، در حالی
# که فاصله‌ی زمانی تضمین‌شده بین درخواست‌ها (global و per-chat) دقیقاً همان قبلی
# می‌ماند — یعنی محافظت در برابر 429 حفظ می‌شود، فقط دیگر کل بات را سریال نمی‌کند.
_telegram_state_lock = threading.Lock()
_telegram_next_allowed_at = 0.0
_telegram_last_request_by_chat = {}
_TELEGRAM_GLOBAL_MIN_INTERVAL = 0.055
_TELEGRAM_CHAT_MIN_INTERVAL = 0.18
_TELEGRAM_429_SAFETY_MARGIN = 1.0
_TELEGRAM_MAX_429_RETRIES = 12
_TELEGRAM_STATE_MAX = 10000

# قفل جداگانه به‌ازای هر پیام (chat_id, message_id) برای ویرایش‌ها: فقط تضمین
# می‌کند دو ویرایشِ *همان پیام* همدیگر را overtake نکنند؛ ویرایش پیام‌های دیگر
# (که قبلاً به‌خاطر لاک سراسری معطل می‌ماندند) الان آزادانه و موازی پیش می‌روند.
_telegram_edit_locks_meta_lock = threading.Lock()
_telegram_edit_locks = {}


def _get_telegram_edit_lock(chat_id, message_id):
    key = (chat_id, message_id)
    with _telegram_edit_locks_meta_lock:
        lock = _telegram_edit_locks.get(key)
        if lock is None:
            lock = threading.Lock()
            _telegram_edit_locks[key] = lock
            if len(_telegram_edit_locks) > _TELEGRAM_STATE_MAX:
                for k in list(_telegram_edit_locks)[:max(1, _TELEGRAM_STATE_MAX // 10)]:
                    _telegram_edit_locks.pop(k, None)
        return lock

# Successful edit fingerprints are intentionally bounded. This is only a
# duplicate-edit guard; it never replaces an edit that has not succeeded.
_edit_success_cache = {}
_EDIT_CACHE_MAX = 5000


def _edit_fingerprint(value):
    if value is None:
        return None
    try:
        if hasattr(value, "to_dict"):
            value = value.to_dict()
        return json.dumps(value, ensure_ascii=False, sort_keys=True,
                          separators=(",", ":"), default=str)
    except Exception:
        return repr(value)


def _edit_cache_key(chat_id, message_id, kind):
    return (str(chat_id), int(message_id), kind)


def _remember_edit_success(key, fingerprint):
    _edit_success_cache[key] = fingerprint
    if len(_edit_success_cache) > _EDIT_CACHE_MAX:
        for old_key in list(_edit_success_cache.keys())[:max(1, _EDIT_CACHE_MAX // 10)]:
            _edit_success_cache.pop(old_key, None)


def _extract_retry_after(exc):
    retry_after = getattr(exc, "retry_after", None)
    if retry_after is not None:
        try:
            return max(1.0, float(retry_after))
        except (TypeError, ValueError):
            pass
    text = str(exc).lower()
    match = re.search(r"retry\s+after\s+(\d+(?:\.\d+)?)", text)
    if match:
        return max(1.0, float(match.group(1)))
    return None


def _is_rate_limit_error(exc):
    text = str(exc).lower()
    return (_extract_retry_after(exc) is not None or
            "too many requests" in text or "429" in text)


def _is_message_not_modified(exc):
    return "message is not modified" in str(exc).lower()


def _is_permanent_message_error(exc):
    text = str(exc).lower()
    return (
        "message to edit not found" in text or
        "message can't be edited" in text or
        "message to delete not found" in text or
        "message not found" in text
    )


def _chat_id_from_call(args, kwargs):
    if "chat_id" in kwargs:
        return kwargs.get("chat_id")
    if args:
        return args[0]
    return None


def _wait_for_telegram_slot(chat_id=None):
    """Global + per-chat pacing. Never marks a request as successful.

    نوبت (زمان مجاز بعدی) به‌صورت اتمی و سریع رزرو می‌شود (زیر لاک، بدون I/O)،
    اما خودِ sleep بیرون از لاک انجام می‌شود؛ بنابراین چند thread می‌توانند
    هم‌زمان منتظر نوبتِ خودشان بمانند و درخواست شبکه‌ایشان را هم‌پوشان بزنند،
    درحالی‌که فاصله‌ی حداقلیِ تضمین‌شده بین *شروعِ* درخواست‌ها (global/per-chat)
    دقیقاً مثل قبل رعایت می‌شود."""
    global _telegram_next_allowed_at
    now = time.monotonic()
    with _telegram_state_lock:
        wait_until = max(now, _telegram_next_allowed_at)
        if chat_id is not None:
            wait_until = max(wait_until,
                             _telegram_last_request_by_chat.get(str(chat_id), 0.0))
        _telegram_next_allowed_at = wait_until + _TELEGRAM_GLOBAL_MIN_INTERVAL
        if chat_id is not None:
            _telegram_last_request_by_chat[str(chat_id)] = wait_until + _TELEGRAM_CHAT_MIN_INTERVAL
            if len(_telegram_last_request_by_chat) > _TELEGRAM_STATE_MAX:
                for k in list(_telegram_last_request_by_chat)[:max(1, _TELEGRAM_STATE_MAX // 10)]:
                    _telegram_last_request_by_chat.pop(k, None)

    delay = wait_until - now
    if delay > 0:
        time.sleep(delay)


def _telegram_call_with_429_retry(func, *args, chat_id=None, max_429_retries=_TELEGRAM_MAX_429_RETRIES, **kwargs):
    """Serialize Telegram calls and honor Bot API retry_after exactly.

    We deliberately do NOT blindly retry arbitrary network errors for send_message:
    an unknown transport failure after Telegram accepted a request can otherwise
    create duplicate messages.  429 is safe to retry because Telegram explicitly
    tells us when to try again.
    """
    global _telegram_next_allowed_at
    retries_429 = 0

    while True:
        _wait_for_telegram_slot(chat_id)
        try:
            return func(*args, **kwargs)
        except Exception as exc:
            if not _is_rate_limit_error(exc):
                raise
            retries_429 += 1
            if retries_429 > max_429_retries:
                logging.error(
                    "Telegram 429 persisted after %s retries for %s: %s",
                    max_429_retries, getattr(func, "__name__", "api_call"), exc
                )
                raise
            retry_after = _extract_retry_after(exc) or 5.0
            wait_seconds = retry_after + _TELEGRAM_429_SAFETY_MARGIN
            # فقط اگر عقب‌تر از نوبت فعلی است جلو می‌بریم؛ به‌این‌ترتیب اگر چند
            # thread هم‌زمان 429 بگیرند، یکدیگر را عقب نمی‌کشند (بیشترین backoff
            # لازم اعمال می‌شود، نه هر backoff بعدی جایگزین قبلی).
            with _telegram_state_lock:
                _telegram_next_allowed_at = max(
                    _telegram_next_allowed_at, time.monotonic() + wait_seconds
                )
            logging.warning(
                "Telegram rate limit on %s; waiting %.1fs (retry %s/%s).",
                getattr(func, "__name__", "api_call"),
                wait_seconds, retries_429, max_429_retries
            )
            time.sleep(wait_seconds)
            # لاکی برای آزاد کردن نیست؛ پردازش سایر پیام‌ها همین الان هم جریان دارد.


def _start_daemon_timer(delay, callback, *args):
    timer = threading.Timer(delay, callback, args=args)
    timer.daemon = True
    timer.start()
    return timer


# ================== راست‌چین اجباری متن پیام‌ها ==================
_RLM = "\u200f"


def _force_rtl(text):
    if not text or not isinstance(text, str):
        return text
    return "\n".join(_RLM + line for line in text.split("\n"))


def _send_message_auto_reply(chat_id, text, *args, **kwargs):
    text = _force_rtl(text)
    if kwargs.get("reply_to_message_id") is None:
        ctx_chat_id = getattr(_reply_ctx, "chat_id", None)
        ctx_message_id = getattr(_reply_ctx, "message_id", None)
        if ctx_message_id and ctx_chat_id is not None and str(ctx_chat_id) == str(chat_id):
            kwargs["reply_to_message_id"] = ctx_message_id
            kwargs.setdefault("allow_sending_without_reply", True)
    return _telegram_call_with_429_retry(
        _original_send_message, chat_id, text, *args, chat_id=chat_id, **kwargs
    )


def _edit_message_text_rtl(text, *args, **kwargs):
    # safe_edit_message performs duplicate suppression and its own edit retry;
    # this wrapper is retained for direct calls elsewhere in the file.
    text = _force_rtl(text)
    chat_id = kwargs.get("chat_id")
    if chat_id is None and len(args) >= 1:
        chat_id = args[0]
    return _telegram_call_with_429_retry(
        _original_edit_message_text, text, *args, chat_id=chat_id, **kwargs
    )


def _edit_message_reply_markup_safe(*args, **kwargs):
    chat_id = kwargs.get("chat_id")
    if chat_id is None and len(args) >= 1:
        chat_id = args[0]
    return _telegram_call_with_429_retry(
        _original_edit_message_reply_markup, *args, chat_id=chat_id, **kwargs
    )


def _delete_message_safe(*args, **kwargs):
    chat_id = _chat_id_from_call(args, kwargs)
    return _telegram_call_with_429_retry(
        _original_delete_message, *args, chat_id=chat_id, **kwargs
    )


def _answer_callback_query_safe(*args, **kwargs):
    return _telegram_call_with_429_retry(
        _original_answer_callback_query, *args, chat_id=None, **kwargs
    )


bot.send_message = _send_message_auto_reply
bot.edit_message_text = _edit_message_text_rtl
bot.edit_message_reply_markup = _edit_message_reply_markup_safe
bot.delete_message = _delete_message_safe
bot.answer_callback_query = _answer_callback_query_safe

# ================== نرمال‌سازی متن دکمه‌ها/کلمات کلیدی ==================
# کیبورد فارسی/عربی گاهی هنگام تایپ یا اتوکامپلیت، کاراکترهای نامرئی مثل
# نیم‌فاصله (ZWNJ)، علائم جهت متن (RTL/LTR mark) یا فاصله‌ی اضافه اضافه
# می‌کنه. چون همه‌ی هندلرهای کلمه‌ی کلیدی (مثل "حفاری") با == دقیق مقایسه
# می‌شدن، همین یک کاراکتر نامرئی باعث می‌شد پیام اول match نشه و کاربر
# مجبور بشه دوباره (این بار بدون اون کاراکتر مخفی) بفرسته. این تابع همه‌ی
# این کاراکترهای نامرئی رو حذف و فاصله‌های تکراری رو یکی می‌کنه.
_INVISIBLE_CHARS_RE = re.compile(r"[\u200b\u200c\u200d\u200e\u200f\ufeff]")

def normalize_text(text):
    if not text:
        return ""
    cleaned = _INVISIBLE_CHARS_RE.sub("", text)
    cleaned = re.sub(r"\s+", " ", cleaned)
    # کیبوردهای عربی به‌جای «ی»/«ک» فارسی از «ي»/«ك» عربی استفاده می‌کنن
    cleaned = cleaned.replace("ي", "ی").replace("ك", "ک")
    return cleaned.strip()

def text_is(message, *options):
    if not getattr(message, "text", None):
        return False
    return normalize_text(message.text) in options

app = Flask(__name__)

# ================== جوین اجباری فقط در پیوی ==================
FORCE_JOIN_CHANNEL = "@Crypto_mohamad7"
FORCE_JOIN_CHANNEL_URL = "https://t.me/Crypto_mohamad7"


def is_force_join_exempt(user_id):
    return user_id in ADMIN_IDS


def is_user_joined_channel(user_id):
    """بررسی عضویت کاربر در کانال جوین اجباری."""
    try:
        member = bot.get_chat_member(FORCE_JOIN_CHANNEL, user_id)
        return member.status in ("creator", "administrator", "member")
    except Exception as e:
        logging.error(f"خطا در بررسی عضویت کانال برای {user_id}: {e}")
        return False


def force_join_markup():
    markup = types.InlineKeyboardMarkup()
    markup.add(colored_button("📢 عضویت در کانال", url=FORCE_JOIN_CHANNEL_URL))
    markup.add(colored_button("✅ بررسی عضویت", callback_data="forcejoin|check"))
    return markup


def force_join_message(chat_id):
    return bot.send_message(
        chat_id,
        "⛔ برای استفاده از ربات ابتدا باید عضو کانال ما شوید.\n\n"
        "بعد از عضویت روی «✅ بررسی عضویت» بزنید.",
        reply_markup=force_join_markup(),
    )


def private_force_join_required(message):
    """فقط پیوی را قفل می‌کند؛ گروه‌ها و سوپرگروه‌ها تحت تأثیر نیستند."""
    if not message or getattr(getattr(message, "chat", None), "type", None) != "private":
        return False
    user_id = getattr(getattr(message, "from_user", None), "id", None)
    if not user_id or is_force_join_exempt(user_id):
        return False
    return not is_user_joined_channel(user_id)


@bot.callback_query_handler(func=lambda call: call.data == "forcejoin|check")
def force_join_check_callback(call):
    user_id = call.from_user.id
    if is_force_join_exempt(user_id) or is_user_joined_channel(user_id):
        bot.answer_callback_query(call.id, "✅ عضویت شما تأیید شد.")
        try:
            safe_edit_message(
                "✅ عضویت شما تأیید شد.\nحالا می‌تونی از ربات استفاده کنی.",
                call.message.chat.id,
                call.message.message_id,
            )
        except Exception:
            pass
    else:
        bot.answer_callback_query(
            call.id,
            "❌ هنوز عضو کانال نشدی. ابتدا عضو شو و دوباره بررسی کن.",
            show_alert=True,
        )


@bot.message_handler(func=private_force_join_required)
def force_join_message_guard(message):
    force_join_message(message.chat.id)


@bot.callback_query_handler(func=lambda call: (
    getattr(getattr(call, "message", None), "chat", None) is not None
    and getattr(call.message.chat, "type", None) == "private"
    and not is_force_join_exempt(call.from_user.id)
    and not is_user_joined_channel(call.from_user.id)
))
def force_join_callback_guard(call):
    bot.answer_callback_query(
        call.id,
        "⛔ ابتدا باید عضو کانال شوید.",
        show_alert=True,
    )

# ================== مهلت ورود عدد/کد ==================
# این مکانیزم به‌جای تکیه بر register_next_step_handler خودِ TeleBot (که فقط
# یک "منتظرِ پیام بعدی" در هر چت پشتیبانی می‌کند و با دو کاربر هم‌زمان در یک
# گروه تداخل پیدا می‌کند)، برای هر (چت، کاربر) به‌صورت جداگانه منتظر پیام
# بعدی می‌ماند. یعنی دو نفر می‌تونن هم‌زمان توی یه گروه، هرکدوم مرحله‌ی خودشون
# رو (مثلاً وارد کردن مبلغ) جلو ببرن بدون این‌که مزاحم همدیگه بشن.
# حداکثر ۶۰ ثانیه فعال است. بعد از آن، مرحله لغو و پیام اصلی ادیت می‌شود.
NEXT_STEP_TIMEOUT = 60
_next_step_pending = {}   # key: (chat_id, user_id) -> {"callback","args","kwargs","token","prompt_message_id","timer"}
_next_step_lock = threading.Lock()

# تأیید مبلغ بانک: تا قبل از زدن «بله» هیچ تغییری در موجودی انجام نمی‌شود.
_bank_confirmations = {}   # user_id -> {"action", "amount", "chat_id", "message_id"}
_bank_confirm_lock = threading.Lock()

# تأیید انتقال الماس: تا قبل از زدن «بله» هیچ انتقالی انجام نمی‌شود.
_transfer_confirmations = {}   # user_id -> {target_id, amount, chat_id, message_id}
_transfer_confirm_lock = threading.Lock()

def _transfer_confirmation_markup(user_id):
    markup = types.InlineKeyboardMarkup()
    markup.row(
        colored_button("خیر ⊗", callback_data=f"diamondtransfer|no|{user_id}"),
        colored_button("بله ✓", callback_data=f"diamondtransfer|yes|{user_id}"),
    )
    return markup

def _store_transfer_confirmation(user_id, target_id, amount, chat_id, message_id):
    with _transfer_confirm_lock:
        _transfer_confirmations[user_id] = {
            "target_id": int(target_id),
            "amount": int(amount),
            "chat_id": chat_id,
            "message_id": message_id,
        }

def _clear_transfer_confirmation(user_id):
    with _transfer_confirm_lock:
        return _transfer_confirmations.pop(user_id, None)

def _show_transfer_confirmation(message, sender_id, target_id, amount):
    confirmation = bot.reply_to(
        message,
        f"⎌ | از انتقال الماس مطمئن هستید؟\n\n$ | مبلغ : {amount:,}",
        reply_markup=_transfer_confirmation_markup(sender_id),
    )
    _store_transfer_confirmation(
        sender_id, target_id, amount, confirmation.chat.id, confirmation.message_id
    )
    return confirmation

@bot.callback_query_handler(func=lambda call: call.data.startswith("diamondtransfer|"))
def diamond_transfer_confirmation_callback(call):
    parts = call.data.split("|")
    if len(parts) != 3:
        bot.answer_callback_query(call.id, "دکمه نامعتبر است.", show_alert=True)
        return
    try:
        user_id = int(parts[2])
    except ValueError:
        bot.answer_callback_query(call.id, "دکمه نامعتبر است.", show_alert=True)
        return
    if call.from_user.id != user_id:
        bot.answer_callback_query(call.id, "این تأیید برای شخص دیگری است.", show_alert=True)
        return

    with _transfer_confirm_lock:
        pending = _transfer_confirmations.get(user_id)
    if not pending:
        bot.answer_callback_query(call.id, "این درخواست دیگر فعال نیست.", show_alert=True)
        return

    if parts[1] == "no":
        _clear_transfer_confirmation(user_id)
        bot.answer_callback_query(call.id, "لغو شد ❌")
        safe_edit_message(
            "⊗ | انتقال الماس لغو شد.\n✓ | هیچ مبلغی از موجودی شما کم نشد.",
            call.message.chat.id, call.message.message_id, reply_markup=None
        )
        return

    if parts[1] != "yes":
        bot.answer_callback_query(call.id, "دکمه نامعتبر است.", show_alert=True)
        return

    _clear_transfer_confirmation(user_id)
    target_id = int(pending["target_id"])
    amount = int(pending["amount"])
    ok, result_msg, sender_balance, target_balance, target_name = perform_transfer(user_id, target_id, amount)
    bot.answer_callback_query(call.id, "انتقال انجام شد ✅" if ok else "انتقال انجام نشد ❌", show_alert=not ok)
    if ok:
        markup = types.InlineKeyboardMarkup()
        markup.row(colored_button(f"$ | موجودی جدید فرستنده : {sender_balance:,}", callback_data="noop", style="primary"))
        markup.row(colored_button(f"$ | موجودی جدید گیرنده : {target_balance:,}", callback_data="noop", style="primary"))
    else:
        markup = None
    safe_edit_message(
        result_msg, call.message.chat.id, call.message.message_id,
        reply_markup=markup
    )

def register_timed_next_step_handler(message, callback, *args, timeout=NEXT_STEP_TIMEOUT, expected_user_id=None, **kwargs):
    chat_id = getattr(getattr(message, "chat", None), "id", None)
    if chat_id is None:
        return

    # اگر expected_user_id صریحاً داده نشده، فقط وقتی از روی پیام حدس بزن که
    # آن پیام واقعاً از یک کاربر واقعی است (نه خودِ ربات). خیلی از فراخوانی‌ها
    # با پیامِ خودِ ربات (call.message یا خروجی bot.reply_to) صدا زده می‌شن که
    # اگر این‌جا از from_user آن استفاده می‌شد، آیدیِ ربات به‌جای کاربر واقعی
    # ذخیره می‌شد و پیام درستِ کاربر رد می‌شد (همون باگی که باعث می‌شد کاربر
    # مجبور بشه ۲-۳ بار مبلغ رو بفرسته).
    if expected_user_id is None:
        user = getattr(message, "from_user", None)
        if user is not None and not getattr(user, "is_bot", False):
            expected_user_id = getattr(user, "id", None)

    if expected_user_id is None:
        # هیچ کاربر مشخصی نداریم (مثلاً یه فلوی ادمین که «هر ادمینی» می‌تونه
        # جوابش رو بده). این حالت را دیگه از طریق این مکانیزم پشتیبانی نمی‌کنیم
        # چون بدون آیدی کاربر نمی‌شه کلید (چت، کاربر) ساخت؛ صدازننده باید
        # expected_user_id را صریح بده.
        logging.error("register_timed_next_step_handler: expected_user_id نامشخص است.")
        return

    key = (chat_id, expected_user_id)
    prompt_message_id = None
    try:
        if getattr(getattr(message, "from_user", None), "is_bot", False):
            prompt_message_id = message.message_id
    except Exception:
        pass

    def expire():
        with _next_step_lock:
            state = _next_step_pending.get(key)
            if not state or state.get("token") is not token:
                return
            _next_step_pending.pop(key, None)
        try:
            prompt_id = state.get("prompt_message_id")
            if prompt_id:
                safe_edit_message(
                    "✓ | زمان وارد کردن اطلاعات تمام شد.",
                    chat_id, prompt_id, reply_markup=None
                )
        except Exception:
            pass

    timer = threading.Timer(timeout, expire)
    timer.daemon = True

    with _next_step_lock:
        token = object()
        previous = _next_step_pending.get(key)
        if previous:
            old_timer = previous.get("timer")
            if old_timer:
                try:
                    old_timer.cancel()
                except Exception:
                    pass
        _next_step_pending[key] = {
            "callback": callback,
            "args": args,
            "kwargs": kwargs,
            "token": token,
            "prompt_message_id": prompt_message_id or (previous or {}).get("prompt_message_id"),
            "timer": timer,
        }

    timer.start()

def cancel_pending_step(chat_id, user_id):
    """مرحله‌ی متنی در انتظار کاربر را فوراً لغو می‌کند.

    مهم: bot.clear_step_handler() فقط مکانیزم داخلی TeleBot را پاک می‌کند؛
    فلوی سفارشی _next_step_pending جدا از آن است و اگر پاک نشود، پیام‌های بعدی
    کاربر دوباره به مرحله‌ی قبلی (مثلاً مبلغ برداشت) تحویل داده می‌شوند و
    به‌نظر می‌رسد بات پیام‌های عادی را نادیده می‌گیرد.
    """
    if chat_id is None or user_id is None:
        return False
    key = (chat_id, user_id)
    with _next_step_lock:
        state = _next_step_pending.pop(key, None)
    if state:
        timer = state.get("timer")
        if timer:
            try:
                timer.cancel()
            except Exception:
                pass
        return True
    return False


def _consume_pending_step(message):
    """اگه برای این (چت، کاربر) مرحله‌ای در انتظار باشه، اجراش می‌کنه.
    خروجی True یعنی مصرف شد (دیگه هندلرهای دیگه نباید روی این پیام کاری کنن)."""
    chat_id = getattr(getattr(message, "chat", None), "id", None)
    user_id = getattr(getattr(message, "from_user", None), "id", None)
    if chat_id is None or user_id is None:
        return False
    key = (chat_id, user_id)
    with _next_step_lock:
        state = _next_step_pending.get(key)
    if not state:
        return False

    # تمام ورودی‌هایی که از یک پنل ربات شروع شده‌اند فقط با Reply مستقیم
    # به همان پیام پنل معتبر هستند. این کنترل مرکزی است تا هیچ فلویی
    # با پیام عادی کاربر اشتباهاً مصرف نشود.
    prompt_id = state.get("prompt_message_id")
    if prompt_id:
        reply = getattr(message, "reply_to_message", None)
        reply_user = getattr(reply, "from_user", None) if reply else None
        if (not reply or reply.message_id != int(prompt_id) or
                not reply_user or not getattr(reply_user, "is_bot", False)):
            try:
                safe_edit_message(
                    "↩️ برای ادامه، روی همین پیام پنل ریپلای کن و مقدار را بفرست.",
                    chat_id, int(prompt_id), reply_markup=None
                )
            except Exception:
                pass
            # مرحله مصرف نشود؛ تایمر و state باقی می‌مانند (چون هنوز pop نشده).
            return True

    # از این‌جا به بعد پیام معتبره؛ فقط الان state رو مصرف (pop) می‌کنیم.
    with _next_step_lock:
        state = _next_step_pending.pop(key, None)
    if not state:
        return False

    timer = state.get("timer")
    if timer:
        try:
            timer.cancel()
        except Exception:
            pass
    state["callback"](message, *state["args"], **state["kwargs"])
    return True


# ================== اتصال به Supabase ==================
SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY")
TELEGRAM_WEBHOOK_SECRET = os.environ.get("TELEGRAM_WEBHOOK_SECRET")
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

# بعد از اجرای layer2_migration.sql این متغیر را روی on بگذارید.
# off = سازگاری با منطق قدیمی؛ on = عملیات مالی حساس از RPC اتمیک استفاده می‌کنند.
ATOMIC_DB_MODE = os.environ.get("ATOMIC_DB_MODE", "off").strip().lower() == "on"

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# ================== قفل برای کازینو ==================
casino_lock = threading.RLock()
bet_lock = threading.RLock()
spin_lock = threading.RLock()
mine_lock = threading.RLock()

# قفل‌های per-user برای جلوگیری از lost-update در حالت غیراتمیک.
# این قفل‌ها مخصوصاً برای Flask threaded=True مهم‌اند.
_user_financial_meta_lock = threading.Lock()
_user_financial_locks = {}

def _get_user_financial_lock(user_id):
    user_id = int(user_id)
    with _user_financial_meta_lock:
        lock = _user_financial_locks.get(user_id)
        if lock is None:
            lock = threading.RLock()
            _user_financial_locks[user_id] = lock
        return lock

_word_diamond_meta_lock = threading.Lock()
_word_diamond_locks = {}

def _get_word_diamond_lock(user_id):
    user_id = int(user_id)
    with _word_diamond_meta_lock:
        lock = _word_diamond_locks.get(user_id)
        if lock is None:
            lock = threading.Lock()
            _word_diamond_locks[user_id] = lock
        return lock

active_casino_games = {}
active_mine_games = {}
MINE_GRID_SIZE = 9       # 3x3
MINE_MULTIPLIER_STEP = 0.25
casino_timers = {}

def _run_db_with_retry(func, *, retries=2, delay=0.3, label="db"):
    """اجرای یک عملیات دیتابیسی با چند بار تلاش مجدد در صورت خطای موقتی شبکه/Supabase.
    بدون این، یک قطعی کوتاه شبکه دقیقاً معادل «شکست قطعی عملیات مالی» می‌شد (مثل باگ
    گزارش‌شده‌ی «مبلغ کسر نشد» در انتقال الماس)."""
    last_err = None
    for attempt in range(retries + 1):
        try:
            return func()
        except Exception as e:
            last_err = e
            if attempt < retries:
                time.sleep(delay)
                continue
    logging.error(f"خطا در {label} بعد از {retries + 1} تلاش: {last_err}")
    raise last_err

# ================== توابع دیتابیس (Supabase) ==================
def get_user(user_id):
    try:
        response = _run_db_with_retry(
            lambda: supabase.table("users").select("*").eq("user_id", user_id).execute(),
            label=f"get_user({user_id})",
        )
        return response.data[0] if response.data else None
    except Exception as e:
        logging.error(f"خطا در get_user: {e}")
        return None

def create_user(user_id, username):
    try:
        supabase.table("users").insert({
            "user_id": user_id,
            "username": username,
            "diamonds": START_DIAMONDS,
            "loan_balance": 0,
            "last_spin": 0,
            "bank_balance": 0,
            "bank_account_number": None,
            "bank_interest_date": None,
            "last_loan_date": None
        }).execute()
        return True
    except Exception as e:
        logging.error(f"خطا در create_user: {e}")
        try:
            return bool(get_user(user_id))
        except Exception:
            return False

def update_diamonds(user_id, amount):
    try:
        if ATOMIC_DB_MODE:
            response = _run_db_with_retry(
                lambda: supabase.rpc("atomic_add_diamonds", {
                    "p_user_id": int(user_id),
                    "p_delta": int(amount),
                }).execute(),
                label=f"atomic_add_diamonds({user_id})",
            )
            return response.data
        # در حالت legacy، حداقل داخل همین process عملیات read-modify-write
        # برای هر کاربر سریالی می‌شود تا lost update رخ ندهد.
        with _get_user_financial_lock(user_id):
            user = get_user(user_id)
            if user:
                new_balance = int(user.get('diamonds', 0) or 0) + int(amount)
                _run_db_with_retry(
                    lambda: supabase.table("users").update({"diamonds": new_balance}).eq("user_id", user_id).execute(),
                    label=f"update_diamonds({user_id})",
                )
                return new_balance
    except Exception as e:
        logging.error(f"خطا در update_diamonds: {e}")
        return None

# ================== سیستم الماس تصادفی گروه ==================
# قبلاً اینجا یک Lock سراسری (global) بود که یعنی پیام یک گروه، پردازش
# پیام‌های *همه‌ی گروه‌های دیگر* را هم متوقف می‌کرد. حالا هر چت قفل
# مخصوص خودش را دارد تا گروه‌ها مزاحم هم نشوند.
_diamond_hunt_meta_lock = threading.Lock()
_diamond_hunt_locks = {}
# کش حافظه‌ای وضعیت هر گروه، تا برای هر پیام معمولی گروه مجبور نباشیم
# با Supabase (که یک درخواست شبکه‌ای است) رفت‌وبرگشت بزنیم.
_diamond_hunt_cache = {}

def _get_diamond_hunt_lock(chat_id):
    with _diamond_hunt_meta_lock:
        lock = _diamond_hunt_locks.get(chat_id)
        if lock is None:
            lock = threading.Lock()
            _diamond_hunt_locks[chat_id] = lock
        return lock

def _get_diamond_hunt(chat_id):
    try:
        response = supabase.table("diamond_hunts").select("*").eq("chat_id", chat_id).execute()
        row = response.data[0] if response.data else None
        if row is not None:
            _diamond_hunt_cache[chat_id] = row
        return row
    except Exception as e:
        logging.error(f"خطا در _get_diamond_hunt: {e}")
        return None

def _ensure_diamond_hunt_row(chat_id):
    # اگر در کش داریم، همان را برگردان (بدون تماس شبکه‌ای) — این تنها
    # چیزی است که در مسیر «هر پیام گروه» صدا زده می‌شود.
    cached = _diamond_hunt_cache.get(chat_id)
    if cached is not None:
        return cached
    row = _get_diamond_hunt(chat_id)
    if row:
        return row
    try:
        response = supabase.table("diamond_hunts").insert({
            "chat_id": chat_id,
            "message_count": 0,
            "active": False,
            "hunt_message_id": None,
            "attempts": []
        }).execute()
        row = response.data[0] if response.data else None
        if row is not None:
            _diamond_hunt_cache[chat_id] = row
        return row
    except Exception as e:
        logging.error(f"خطا در ساخت وضعیت الماس گروه {chat_id}: {e}")
        return None

def _set_diamond_hunt(chat_id, **updates):
    try:
        supabase.table("diamond_hunts").update(updates).eq("chat_id", chat_id).execute()
    except Exception as e:
        logging.error(f"خطا در به‌روزرسانی وضعیت الماس گروه {chat_id}: {e}")
    # کش را هم همگام نگه می‌داریم تا خوانده‌های بعدی از کش، قدیمی نباشند.
    cached = _diamond_hunt_cache.get(chat_id)
    if cached is not None:
        cached.update(updates)

def _diamond_hunt_markup(attempt_no, message_id):
    markup = types.InlineKeyboardMarkup()
    if attempt_no <= 3:
        markup.add(colored_button(
            "💎 برداشتن الماس",
            callback_data=f"dhunt|{message_id}|{attempt_no}"
        ))
    return markup

def _expire_diamond_hunt(chat_id, message_id):
    with _get_diamond_hunt_lock(chat_id):
        row = _get_diamond_hunt(chat_id)
        if not row:
            return
        if not row.get("active"):
            return
        if int(row.get("hunt_message_id") or 0) != int(message_id):
            return

        _set_diamond_hunt(
            chat_id,
            active=False,
            hunt_message_id=None,
            attempts=[]
        )

    try:
        bot.edit_message_caption(
            chat_id=chat_id,
            message_id=message_id,
            caption="⏰ زمان برداشتن الماس به پایان رسید و الماس از دست رفت! ❌💎",
            reply_markup=None
        )
    except Exception:
        try:
            safe_edit_message(
                "⏰ زمان برداشتن الماس به پایان رسید و الماس از دست رفت! ❌💎",
                chat_id,
                message_id,
                reply_markup=None
            )
        except Exception as e:
            logging.error(f"خطا در منقضی کردن الماس گروه {chat_id}: {e}")

def _start_diamond_hunt(chat_id):
    try:
        photo_url = "https://i.ibb.co/TDMk6NZz/file-00000000aa6481f7a219e1184b4dd639.jpg"
        
        msg = bot.send_photo(
            chat_id,
            photo=photo_url,
            caption="💎 یک الماس در شهر پیدا شد!\n\n"
                    "این الماس قابل دریافت و اضافه شدن به موجودی است 💎\n\n"
                    "تا از دست نرفته تلاش خودت رو برای بدست آوردنش بکن ✅\n\n"
                    "از دکمه زیر برای برداشتن الماس استفاده کنید❗\n\n"
                    f"💰 هزینه تلاش برای برداشتن الماس: {DIAMOND_HUNT_COSTS[0]:,} الماس💎"
        )

        _set_diamond_hunt(
            chat_id,
            active=True,
            hunt_message_id=msg.message_id,
            attempts=[]
        )

        safe_edit_message_reply_markup(
            chat_id=chat_id,
            message_id=msg.message_id,
            reply_markup=_diamond_hunt_markup(1, msg.message_id)
        )

        timer = threading.Timer(120, _expire_diamond_hunt, args=(chat_id, msg.message_id))
        timer.daemon = True
        timer.start()

    except Exception as e:
        logging.error(f"خطا در ارسال الماس تصادفی گروه {chat_id}: {e}")

def process_group_message_for_diamond_hunt(message):
    if not message or message.chat.type not in ("group", "supergroup"):
        return

    if getattr(message.from_user, "is_bot", False):
        return

    text = (message.text or "").strip()
    if text == "الماس":
        try:
            if get_user(message.from_user.id):
                register_word_diamond(
                    message.from_user.id, message.chat.id, get_display_name(message.from_user), message
                )
        except Exception as e:
            logging.error(f"خطا در ثبت پاداش کلمه الماس: {e}")

    chat_id = message.chat.id
    with _get_diamond_hunt_lock(chat_id):
        row = _ensure_diamond_hunt_row(chat_id)
        if not row:
            return

        # تا وقتی یک الماس فعال است، پیام‌ها برای چرخه بعدی حساب نمی‌شوند.
        # شمارش بعد از پایان/انقضای همین الماس دوباره ادامه پیدا می‌کند.
        if row.get("active"):
            return

        count = int(row.get("message_count", 0) or 0) + 1
        row["message_count"] = count

        # شمارنده را در Supabase هم ذخیره می‌کنیم تا با ری‌استارت Render
        # از بین نرود و مقدار واقعی جدول همیشه قابل مشاهده باشد.
        if count < DIAMOND_HUNT_MESSAGE_INTERVAL:
            _set_diamond_hunt(chat_id, message_count=count)
            return

        # پیام شماره 200: شمارنده همان لحظه صفر می‌شود و الماس ارسال می‌گردد.
        _set_diamond_hunt(chat_id, message_count=0)
        _start_diamond_hunt(chat_id)

def _user_display_from_call(call):
    # فقط اسم (First Name) رو نشون بده
    return call.from_user.first_name or "کاربر"

@bot.callback_query_handler(func=lambda call: call.data.startswith("dhunt|"))
def diamond_hunt_callback(call):
    parts = call.data.split("|")
    if len(parts) != 3:
        bot.answer_callback_query(call.id, "دکمه نامعتبر است.", show_alert=True)
        return

    try:
        message_id = int(parts[1])
        attempt_no = int(parts[2])
    except ValueError:
        bot.answer_callback_query(call.id, "دکمه نامعتبر است.", show_alert=True)
        return

    chat_id = call.message.chat.id

    with _get_diamond_hunt_lock(chat_id):
        row = _get_diamond_hunt(chat_id)

        if (
            not row
            or not row.get("active")
            or int(row.get("hunt_message_id") or 0) != message_id
        ):
            bot.answer_callback_query(
                call.id,
                "این الماس دیگر قابل برداشتن نیست ❌",
                show_alert=True
            )
            return

        attempts = row.get("attempts") or []
        expected_attempt = len(attempts) + 1

        if attempt_no != expected_attempt or attempt_no > 3:
            bot.answer_callback_query(
                call.id,
                "این تلاش قبلاً انجام شده یا معتبر نیست ❌",
                show_alert=True
            )
            return

        user_id = call.from_user.id

        if not get_user(user_id):
            bot.answer_callback_query(
                call.id,
                "اول /start را در پیوی بات بزن.",
                show_alert=True
            )
            return

        cost = DIAMOND_HUNT_COSTS[attempt_no - 1]

        # قفل hunt گروه + قفل مالی کاربر:
        # کاربر نمی‌تواند هم‌زمان در دو گروه، موجودی یکسان را دوبار خرج کند.
        with _get_user_financial_lock(user_id):
            if get_balance(user_id) < cost:
                bot.answer_callback_query(
                    call.id,
                    f"برای این تلاش {cost:,} 💎 لازم داری.",
                    show_alert=True
                )
                return

            if update_diamonds(user_id, -cost) is None:
                bot.answer_callback_query(
                    call.id,
                    "❌ کسر هزینه انجام نشد؛ دوباره تلاش کن.",
                    show_alert=True
                )
                return

            name = display_name_with_tag(user_id, _user_display_from_call(call))
            won = random.random() < DIAMOND_HUNT_WIN_CHANCES[attempt_no - 1]

        if won:
            update_diamonds(user_id, 1)
            add_xp(user_id, XP_PER_DIAMOND_HUNT_WIN, chat_id=chat_id, display_name=name)
            _check_wealth_trophies(user_id, chat_id, name)
            _notify_group_if_enabled(chat_id, "new_diamond", f"💎 {name} یک الماس به‌دست آورد!")
            total_attempts = attempt_no

            _set_diamond_hunt(
                chat_id,
                active=False,
                hunt_message_id=None,
                attempts=[]
            )

            try:
                bot.answer_callback_query(
                    call.id,
                    "💍 الماس با موفقیت نجات پیدا کرد!",
                    show_alert=False
                )
                
                bot.edit_message_caption(
                    chat_id=chat_id,
                    message_id=message_id,
                    caption=f"الماس بعد از {total_attempts} تلاش با موفقیت نجات یافت و صاحب جدید پیدا کرد!💎\n\n"
                            f"{name} با موفقیت الماس رو بدست آورد.💎\n\n"
                            "🎁 پاداش ⬇️\n"
                            "‏┘─ یک الماس 💎",
                    reply_markup=None
                )
                
            except Exception as e:
                logging.error(f"خطا در نتیجه برد الماس: {e}")
                try:
                    safe_edit_message(
                        f"الماس بعد از {total_attempts} تلاش با موفقیت نجات یافت و صاحب جدید پیدا کرد!💎\n\n"
                        f"{name} با موفقیت الماس رو بدست آورد.💎\n\n"
                        "🎁 پاداش ⬇️\n"
                        "‏┘─ یک الماس 💎",
                        chat_id,
                        message_id,
                        reply_markup=None
                    )
                except Exception as e2:
                    logging.error(f"خطا در نتیجه برد الماس (روش جایگزین): {e2}")
            return

        reason = random.choice(DIAMOND_HUNT_REASONS)
        attempts.append({"name": name, "reason": reason})
        _set_diamond_hunt(chat_id, attempts=attempts)

        bot.answer_callback_query(
            call.id,
            f"تلاش {attempt_no} ناموفق بود ❌"
        )

        if attempt_no < 3:
            next_cost = DIAMOND_HUNT_COSTS[attempt_no]
            text = (
                "❗ نتونستی الماس رو بگیری علت ⬇️\n\n"
                + _format_attempt_history(attempts)
                + "\n\n"
                f"💰 هزینه تلاش بعدی: {next_cost:,} الماس💎"
            )
            
            try:
                bot.edit_message_caption(
                    chat_id=chat_id,
                    message_id=message_id,
                    caption=text,
                    reply_markup=_diamond_hunt_markup(attempt_no + 1, message_id)
                )
            except Exception:
                safe_edit_message(
                    text,
                    chat_id,
                    message_id,
                    reply_markup=_diamond_hunt_markup(attempt_no + 1, message_id)
                )
        else:
            text = (
                "❗ نتونستی الماس رو بگیری علت ⬇️\n\n"
                + _format_attempt_history(attempts)
            )
            
            try:
                bot.edit_message_caption(
                    chat_id=chat_id,
                    message_id=message_id,
                    caption=text,
                    reply_markup=None
                )
            except Exception:
                safe_edit_message(
                    text,
                    chat_id,
                    message_id,
                    reply_markup=None
                )
            
            _set_diamond_hunt(
                chat_id,
                active=False,
                hunt_message_id=None,
                attempts=[]
            )

# ================== بخش کارخونه حفاری الماس ==================
# هزینه افتتاح بخش حفاری (مثل بانک، قفل است تا زمانی که پرداخت شود)
FACTORY_OPENING_FEE = 3000

# بالانس کارخانه حفاری:
# هر سه بخش اصلی حداکثر سطح 10 دارند.
FACTORY_MAX_LEVEL = 10

# ظرفیت انبار در هر سطح (سطح ۱۰ = ۱۵,۰۰۰ الماس)
FACTORY_WAREHOUSE_CAPACITY = {
    1: 1_500,
    2: 3_000,
    3: 4_500,
    4: 6_000,
    5: 7_500,
    6: 9_000,
    7: 10_500,
    8: 12_000,
    9: 13_500,
    10: 15_000,
}

# هزینه ارتقای انبار: سطح فعلی -> سطح بعدی (اولش کم، از لول ۵ به بعد شیب تندتر تا 10,000 در آخر)
FACTORY_WAREHOUSE_UPGRADE_COSTS = {
    1: 100,
    2: 200,
    3: 400,
    4: 700,
    5: 1_200,
    6: 2_800,
    7: 5_500,
    8: 9_000,
    9: 15_000,
}

# حداکثر تعداد کارگر = سطح کارکنان (سطح 1 تا 10)
FACTORY_WORKERS_BASE_MAX = 1

# هزینه ارتقای سطح کارکنان: سطح فعلی -> سطح بعدی
FACTORY_WORKERS_UPGRADE_COSTS = {
    1: 250,
    2: 600,
    3: 1_200,
    4: 2_000,
    5: 3_000,
    6: 4_200,
    7: 5_700,
    8: 7_500,
    9: 10_000,
}

# دستمزد روزانه هر کارگر بر اساس سطح کارکنان (متناسب با اقتصاد جدید کاهش یافت)
FACTORY_WAGE_BY_LEVEL = {
    1: 10,
    2: 20,
    3: 35,
    4: 55,
    5: 80,
    6: 120,
    7: 180,
    8: 260,
    9: 380,
    10: 500,
}

# زمان لازم برای استخراج هر الماس بر اساس سطح دستگاه
FACTORY_MACHINE_DRILL_SECONDS = {
    1: 10.0,
    2: 9.0,
    3: 8.0,
    4: 7.0,
    5: 6.0,
    6: 5.0,
    7: 4.0,
    8: 3.0,
    9: 2.0,
    10: 1.0,
}

# هزینه ارتقای دستگاه: سطح فعلی -> سطح بعدی
FACTORY_MACHINE_UPGRADE_COSTS = {
    1: 500,
    2: 1_000,
    3: 2_000,
    4: 3_500,
    5: 5_500,
    6: 8_000,
    7: 12_000,
    8: 18_000,
    9: 25_000,
}

FACTORY_XP_PER_HARVEST_UNIT = 500
FACTORY_XP_NEEDED_PER_LEVEL = 500


def get_factory(user_id):
    """دریافت/ساخت وضعیت کارخانه؛ اگر رکورد وجود نداشته باشد همان لحظه ساخته می‌شود."""
    default = {
        "user_id": int(user_id),
        "factory_unlocked": False,
        "warehouse_level": 1,
        "warehouse_stored": 0,
        "workers_level": 1,
        "workers_hired": 1,
        "machine_level": 1,
        "factory_xp": 0,
        "factory_level": 1,
        "last_calc_time": int(time.time()),
        "last_wage_date": _today_tehran().isoformat(),
    }
    try:
        resp = (supabase.table("factories").select("*")
                .eq("user_id", int(user_id)).limit(1).execute())
        if resp.data:
            factory = dict(resp.data[0])
            for key, value in default.items():
                factory.setdefault(key, value)
            return factory

        inserted = (supabase.table("factories")
                    .upsert(default, on_conflict="user_id").execute())
        if inserted.data:
            factory = dict(inserted.data[0])
            for key, value in default.items():
                factory.setdefault(key, value)
            return factory

        resp = (supabase.table("factories").select("*")
                .eq("user_id", int(user_id)).limit(1).execute())
        return resp.data[0] if resp.data else default
    except Exception as e:
        logging.exception(f"خطا در get_factory برای user_id={user_id}: {e}")
        return None


def factory_warehouse_capacity(level):
    level = max(1, min(int(level), FACTORY_MAX_LEVEL))
    return FACTORY_WAREHOUSE_CAPACITY[level]


def factory_warehouse_upgrade_cost(level):
    return FACTORY_WAREHOUSE_UPGRADE_COSTS.get(int(level), 0)


def factory_workers_max(level):
    level = max(1, min(int(level), FACTORY_MAX_LEVEL))
    return FACTORY_WORKERS_BASE_MAX + (level - 1)


def factory_workers_upgrade_cost(level):
    return FACTORY_WORKERS_UPGRADE_COSTS.get(int(level), 0)


def factory_wage_per_worker(level):
    level = max(1, min(int(level), FACTORY_MAX_LEVEL))
    return FACTORY_WAGE_BY_LEVEL[level]


def factory_drill_seconds(level):
    level = max(1, min(int(level), FACTORY_MAX_LEVEL))
    return FACTORY_MACHINE_DRILL_SECONDS[level]


def factory_machine_upgrade_cost(level):
    return FACTORY_MACHINE_UPGRADE_COSTS.get(int(level), 0)


def factory_xp_needed(level):
    level = max(1, min(int(level), FACTORY_MAX_LEVEL))
    return level * FACTORY_XP_NEEDED_PER_LEVEL


def sync_factory_production(factory):
    """الماس تولیدشده از آخرین بار تا الان رو حساب می‌کنه و به انبار اضافه می‌کنه،
    و اگه روز جدید شده دستمزد روزانه کارگرها رو کسر می‌کنه."""
    if not factory:
        return factory
    now = int(time.time())
    last = factory.get("last_calc_time") or now
    elapsed = max(0, now - last)
    drill_seconds = factory_drill_seconds(factory["machine_level"])
    rate_per_sec = (factory["workers_hired"] / drill_seconds) if drill_seconds > 0 else 0
    produced = elapsed * rate_per_sec
    capacity = factory_warehouse_capacity(factory["warehouse_level"])
    new_stored = min(capacity, factory["warehouse_stored"] + produced)

    # ستون warehouse_stored توی دیتابیس bigint (عدد صحیح) هست؛ اگه عدد اعشاری
    # (مثلاً 414.0) بفرستیم، Supabase با خطای «invalid input syntax for type
    # bigint» ریجکتش می‌کنه و تولید کارخونه اصلاً ذخیره نمی‌شه. برای همین قبل
    # از ذخیره، به عدد صحیح گرد می‌کنیم.
    new_stored = int(new_stored)

    updates = {"warehouse_stored": new_stored, "last_calc_time": now}

    today = _today_tehran().isoformat()
    if factory.get("last_wage_date") != today and factory["workers_hired"] > 0:
        wage_per = factory_wage_per_worker(factory["workers_level"])
        user_id = factory["user_id"]
        balance = get_balance(user_id)
        wage_total = factory["workers_hired"] * wage_per
        if balance >= wage_total:
            update_diamonds(user_id, -wage_total)
        else:
            affordable = int(balance // wage_per) if wage_per > 0 else 0
            if affordable > 0:
                update_diamonds(user_id, -(affordable * wage_per))
            updates["workers_hired"] = affordable
        updates["last_wage_date"] = today

    try:
        supabase.table("factories").update(updates).eq("user_id", factory["user_id"]).execute()
    except Exception as e:
        logging.error(f"خطا در sync_factory_production: {e}")
    factory = dict(factory)
    factory.update(updates)
    return factory


def get_bank_balance(user_id):
    user = get_user(user_id)
    return int(user.get("bank_balance", 0) or 0) if user else 0

def get_bank_account_number(user_id):
    user = get_user(user_id)
    return user.get("bank_account_number") if user else None

def _today_tehran():
    return datetime.now(TEHRAN_TZ).date()

def generate_bank_account_number():
    while True:
        number = "6037" + "".join(str(random.randint(0, 9)) for _ in range(12))
        try:
            exists = supabase.table("users").select("user_id").eq("bank_account_number", number).execute()
            if not exists.data:
                return number
        except Exception as e:
            logging.error(f"خطا در تولید شماره حساب: {e}")
            return number

def apply_bank_interest(user_id):
    """سود روزهای گذشته را بعد از ساعت ۰۰:۰۰ محاسبه می‌کند؛ سود هر روز حداکثر ۱ میلیون است."""
    user = get_user(user_id)
    if not user or not user.get("bank_account_number"):
        return 0

    balance = int(user.get("bank_balance", 0) or 0)
    if balance <= 0:
        today = _today_tehran().isoformat()
        supabase.table("users").update({"bank_interest_date": today}).eq("user_id", user_id).execute()
        return 0

    today = _today_tehran()
    last_raw = user.get("bank_interest_date")
    if not last_raw:
        supabase.table("users").update({"bank_interest_date": today.isoformat()}).eq("user_id", user_id).execute()
        return 0

    try:
        last_date = datetime.fromisoformat(str(last_raw)[:10]).date()
    except Exception:
        last_date = today

    if last_date >= today:
        return 0

    total_interest = 0
    days = (today - last_date).days
    for _ in range(days):
        daily_interest = min(int(balance * BANK_INTEREST_RATE), BANK_DAILY_INTEREST_MAX)
        balance += daily_interest
        total_interest += daily_interest

    supabase.table("users").update({
        "bank_balance": balance,
        "bank_interest_date": today.isoformat()
    }).eq("user_id", user_id).execute()
    return total_interest

def open_bank_account(user_id):
    user = get_user(user_id)
    if not user:
        return False, "اول /start بزن."
    if user.get("bank_account_number"):
        return True, "حساب بانکی شما از قبل فعال است."
    if get_balance(user_id) < BANK_OPENING_FEE:
        return False, f"برای افتتاح حساب باید {BANK_OPENING_FEE:,} 💎 داشته باشی."

    account_number = generate_bank_account_number()
    today = _today_tehran().isoformat()
    try:
        if ATOMIC_DB_MODE:
            result = supabase.rpc("atomic_open_bank_account", {
                "p_user_id": int(user_id),
                "p_account_number": account_number,
                "p_fee": int(BANK_OPENING_FEE),
                "p_interest_date": today,
            }).execute().data
            if not result:
                return False, "افتتاح حساب انجام نشد."
            row = result[0] if isinstance(result, list) else result
            return bool(row.get("ok", True)), row.get("account_number") or account_number
        if update_diamonds(user_id, -BANK_OPENING_FEE) is None:
            return False, "موجودی کافی نیست."
        supabase.table("users").update({
            "bank_balance": 0,
            "bank_account_number": account_number,
            "bank_interest_date": today
        }).eq("user_id", user_id).execute()
        return True, account_number
    except Exception as e:
        logging.error(f"خطا در open_bank_account: {e}")
        return False, "افتتاح حساب انجام نشد."

def atomic_bank_transfer(user_id, amount, action):
    """انتقال کیف پول/بانک در یک تراکنش دیتابیسی؛ فقط در ATOMIC_DB_MODE."""
    try:
        result = supabase.rpc("atomic_bank_transfer", {
            "p_user_id": int(user_id),
            "p_amount": int(amount),
            "p_action": action,
        }).execute()
        return bool(result.data)
    except Exception as e:
        logging.error(f"خطا در atomic_bank_transfer: {e}")
        return False

def change_bank_balance(user_id, delta):
    try:
        if ATOMIC_DB_MODE:
            supabase.rpc("atomic_change_bank_balance", {
                "p_user_id": int(user_id),
                "p_delta": int(delta),
            }).execute()
            return True
        with _get_user_financial_lock(user_id):
            user = get_user(user_id)
            if not user or not user.get("bank_account_number"):
                return False
            apply_bank_interest(user_id)
            # apply_bank_interest می‌تواند user را تغییر دهد؛ دوباره بخوان.
            user = get_user(user_id)
            current = int((user or {}).get("bank_balance", 0) or 0)
            new_balance = current + int(delta)
            if new_balance < 0:
                return False
            supabase.table("users").update({"bank_balance": new_balance}).eq("user_id", user_id).execute()
            return True
    except Exception as e:
        logging.error(f"خطا در change_bank_balance: {e}")
        return False

def get_last_loan_date(user_id):
    user = get_user(user_id)
    return user.get("last_loan_date") if user else None

def set_last_loan_date(user_id, value):
    try:
        supabase.table("users").update({"last_loan_date": value}).eq("user_id", user_id).execute()
    except Exception as e:
        logging.error(f"خطا در set_last_loan_date: {e}")

def get_balance(user_id):
    user = get_user(user_id)
    return user.get('diamonds', 0) if user else 0

def get_loan_balance(user_id):
    user = get_user(user_id)
    return user.get('loan_balance', 0) if user else 0

def change_loan_balance(user_id, delta):
    try:
        if ATOMIC_DB_MODE:
            return supabase.rpc("atomic_change_loan_balance", {
                "p_user_id": int(user_id), "p_delta": int(delta)
            }).execute().data
        with _get_user_financial_lock(user_id):
            user = get_user(user_id)
            if user:
                new_balance = max(0, int(user.get('loan_balance', 0) or 0) + int(delta))
                supabase.table("users").update({"loan_balance": new_balance}).eq("user_id", user_id).execute()
                return new_balance
    except Exception as e:
        logging.error(f"خطا در change_loan_balance: {e}")
        return None

def get_last_spin(user_id):
    user = get_user(user_id)
    return user.get('last_spin', 0) if user else 0

def set_last_spin(user_id, ts):
    try:
        supabase.table("users").update({"last_spin": ts}).eq("user_id", user_id).execute()
    except Exception as e:
        logging.error(f"خطا در set_last_spin: {e}")

_bet_locks_meta_lock = threading.Lock()
_bet_locks = {}

def _get_bet_lock(bet_id):
    """قفل مخصوص هر شرط تا پیوستن/لغو/تایم‌اوت هم‌زمان روی یک شرط با هم تداخل نکنن
    (همون الگویی که برای بازی دینامیت استفاده شده)."""
    bet_id = int(bet_id)
    with _bet_locks_meta_lock:
        lock = _bet_locks.get(bet_id)
        if lock is None:
            lock = threading.RLock()
            _bet_locks[bet_id] = lock
        return lock

def create_bet(creator_id, creator_name, amount, chat_id, message_id):
    try:
        response = supabase.table("bets").insert({
            "creator_id": creator_id,
            "creator_name": creator_name,
            "amount": amount,
            "chat_id": chat_id,
            "message_id": message_id,
            "status": "pending"
        }).execute()
        return response.data[0]['bet_id'] if response.data else None
    except Exception as e:
        logging.error(f"خطا در create_bet: {e}")
        return None

def get_bet(bet_id):
    try:
        response = supabase.table("bets").select("*").eq("bet_id", bet_id).execute()
        return response.data[0] if response.data else None
    except Exception as e:
        logging.error(f"خطا در get_bet: {e}")
        return None

def set_bet_status(bet_id, status):
    try:
        supabase.table("bets").update({"status": status}).eq("bet_id", bet_id).execute()
    except Exception as e:
        logging.error(f"خطا در set_bet_status: {e}")

def get_top_users(limit=10):
    try:
        response = supabase.table("users").select("user_id, username, diamonds").order("diamonds", desc=True).limit(limit).execute()
        return [(u['user_id'], u['username'], u['diamonds']) for u in response.data] if response.data else []
    except Exception as e:
        logging.error(f"خطا در get_top_users: {e}")
        return []

def get_display_name(user):
    """نام نمایشی استاندارد ربات: فقط First Name تلگرام."""
    return (getattr(user, "first_name", None) or "کاربر").strip()

# ================== سیستم سطح‌بندی، جام‌ها، آمار و اعلان‌ها ==================
# نکته پیاده‌سازی: این بخش به جداول زیر در Supabase نیاز دارد که باید از قبل
# ساخته شده باشند (به فایل new_tables.sql مراجعه کن):
#   user_progress(user_id PK, xp int, level int, messages_count int,
#                  bets_won_count int, casino_wins_count int, cosmetics jsonb)
#   user_trophies(id PK, user_id, trophy_key, earned_at)
#   group_notify_settings(chat_id PK, level_up bool, trophy bool, new_diamond bool,
#                          daily_gift bool, diamond_timer bool, betting bool, tournament bool)

def get_progress(user_id):
    try:
        resp = supabase.table("user_progress").select("*").eq("user_id", user_id).execute()
        if resp.data:
            return resp.data[0]
        default = {
            "user_id": user_id, "xp": 0, "level": 1,
            "messages_count": 0, "bets_won_count": 0, "casino_wins_count": 0,
            "cosmetics": {}, "last_word_diamond_at": 0
        }
        supabase.table("user_progress").insert(default).execute()
        return default
    except Exception as e:
        logging.error(f"خطا در get_progress: {e}")
        try:
            resp = supabase.table("user_progress").select("*").eq("user_id", user_id).execute()
            if resp.data:
                return resp.data[0]
        except Exception as read_error:
            logging.error(f"خطا در بازخوانی get_progress: {read_error}")
        return {"user_id": user_id, "xp": 0, "level": 1, "messages_count": 0,
                "bets_won_count": 0, "casino_wins_count": 0, "cosmetics": {}}

def level_info(level):
    for lvl, title, xp_needed, reward in LEVELS:
        if lvl == level:
            return lvl, title, xp_needed, reward
    return LEVELS[0]

def xp_needed_for_next_level(level):
    if level >= MAX_LEVEL:
        return None
    for lvl, _title, xp_needed, _reward in LEVELS:
        if lvl == level + 1:
            return xp_needed
    return None

def _notify_group_if_enabled(chat_id, key, text):
    if not chat_id:
        return
    try:
        settings = get_notify_settings(chat_id)
        if settings.get(key, True):
            bot.send_message(chat_id, text)
    except Exception as e:
        logging.error(f"خطا در ارسال اعلان گروه: {e}")

def add_xp(user_id, amount, chat_id=None, display_name=None):
    """XP اضافه می‌کند، در صورت ارتقای سطح پاداش می‌دهد و اعلان می‌فرستد."""
    if amount <= 0:
        return
    try:
        progress = get_progress(user_id)
        new_xp = int(progress.get("xp", 0) or 0) + amount
        old_level = int(progress.get("level", 1) or 1)
        new_level = old_level
        while new_level < MAX_LEVEL:
            need = xp_needed_for_next_level(new_level)
            if need is not None and new_xp >= need:
                new_level += 1
            else:
                break
        supabase.table("user_progress").update(
            {"xp": new_xp, "level": new_level}
        ).eq("user_id", user_id).execute()

        if new_level > old_level:
            name = display_name or str(user_id)
            for lvl in range(old_level + 1, new_level + 1):
                _, title, _need, reward = level_info(lvl)
                if reward:
                    update_diamonds(user_id, reward)
                try:
                    bot.send_message(
                        user_id,
                        f"🏆 تبریک! به سطح {lvl} رسیدی: {title}\n💎 پاداش: {reward:,} الماس"
                    )
                except Exception:
                    pass
                _notify_group_if_enabled(
                    chat_id, "level_up",
                    f"🏆 {name} به سطح {lvl} ({title}) رسید! 🎉"
                )
    except Exception as e:
        logging.error(f"خطا در add_xp: {e}")

def get_user_trophies(user_id):
    try:
        resp = supabase.table("user_trophies").select("trophy_key").eq("user_id", user_id).execute()
        return {row["trophy_key"] for row in (resp.data or [])}
    except Exception as e:
        logging.error(f"خطا در get_user_trophies: {e}")
        return set()

def award_trophy(user_id, trophy_key, chat_id=None, display_name=None):
    if trophy_key not in TROPHIES:
        return False
    try:
        existing = get_user_trophies(user_id)
        if trophy_key in existing:
            return False
        supabase.table("user_trophies").insert({
            "user_id": user_id, "trophy_key": trophy_key
        }).execute()
        title, desc = TROPHIES[trophy_key]
        name = display_name or str(user_id)
        try:
            bot.send_message(user_id, f"🏅 جام جدید گرفتی: {title}\n{desc}")
        except Exception:
            pass
        _notify_group_if_enabled(
            chat_id, "trophy", f"🏅 {name} جام «{title}» رو گرفت! {desc}"
        )
        return True
    except Exception as e:
        logging.error(f"خطا در award_trophy: {e}")
        return False

def _check_threshold_trophies(user_id, value, thresholds, chat_id=None, display_name=None):
    for threshold, key in thresholds:
        if value >= threshold:
            award_trophy(user_id, key, chat_id=chat_id, display_name=display_name)

def get_message_xp_rate(user_id):
    """نرخ XP هر پیام بر اساس جام‌های پیام کاربر (تازه‌وارد/پرحرف)."""
    trophies = get_user_trophies(user_id)
    if "msg_500" in trophies:
        return 5
    if "msg_100" in trophies:
        return 2
    return XP_PER_MESSAGE

def get_word_diamond_reward(user_id):
    """مقدار الماس هدیه‌ی گفتن کلمه «الماس»، بر اساس سطح فعلی کاربر."""
    progress = get_progress(user_id)
    level = int(progress.get("level", 1) or 1)
    level = max(1, min(level, MAX_LEVEL))
    return WORD_DIAMOND_REWARD_BY_LEVEL.get(level, WORD_DIAMOND_REWARD_BY_LEVEL[1])

def _format_mmss(seconds):
    seconds = max(0, int(round(seconds)))
    m, s = divmod(seconds, 60)
    return f"{m:02d}:{s:02d}"

def register_word_diamond(user_id, chat_id, display_name, message=None):
    """پاداش کلمه «الماس» را با قفل per-user و بررسی اتمیک کول‌داون ثبت می‌کند."""
    try:
        # این lock جلوی دو پیام هم‌زمان در همین process را می‌گیرد.
        # برای چند worker/process، اجرای واقعی باید با DB/RPC اتمیک هم پشتیبانی شود.
        with _get_word_diamond_lock(user_id):
            progress = get_progress(user_id)
            now_ts = time.time()
            last_ts = progress.get("last_word_diamond_at") or 0
            try:
                last_ts = float(last_ts)
            except (TypeError, ValueError):
                last_ts = 0

            elapsed = now_ts - last_ts
            if elapsed < WORD_DIAMOND_COOLDOWN_SECONDS:
                remaining = WORD_DIAMOND_COOLDOWN_SECONDS - elapsed
                text = f"تازه الماس گرفتی❗\nتا الماس بعدی : {_format_mmss(remaining)}⏳"
                if message is not None:
                    bot.reply_to(message, text)
                return

            reward = get_word_diamond_reward(user_id)
            if update_diamonds(user_id, reward) is None:
                logging.error(f"پاداش کلمه الماس برای {user_id} ثبت نشد؛ موجودی تغییر نکرد.")
                return

            count = int(progress.get("messages_count", 0) or 0) + 1
            supabase.table("user_progress").update({
                "messages_count": count,
                "last_word_diamond_at": now_ts,
            }).eq("user_id", user_id).execute()
            add_xp(user_id, get_message_xp_rate(user_id), chat_id=chat_id, display_name=display_name)
            _check_threshold_trophies(user_id, count, MSG_TROPHY_THRESHOLDS, chat_id, display_name)

            text = f"{reward:,} الماس گرفتی💎\nتا گفتن الماس بعدی: {_format_mmss(WORD_DIAMOND_COOLDOWN_SECONDS)}⏳"
            if message is not None:
                bot.reply_to(message, text)

            _notify_group_if_enabled(
                chat_id, "new_diamond", f"💎 {display_name} با گفتن «الماس» {reward:,} 💎 گرفت!"
            )
    except Exception as e:
        logging.error(f"خطا در register_word_diamond: {e}")

def register_bet_win(user_id, chat_id, display_name):
    try:
        progress = get_progress(user_id)
        count = int(progress.get("bets_won_count", 0) or 0) + 1
        supabase.table("user_progress").update({"bets_won_count": count}).eq("user_id", user_id).execute()
        add_xp(user_id, XP_PER_BET_WIN, chat_id=chat_id, display_name=display_name)
        _check_threshold_trophies(user_id, count, BET_WIN_TROPHY_THRESHOLDS, chat_id, display_name)
        _check_wealth_trophies(user_id, chat_id, display_name)
    except Exception as e:
        logging.error(f"خطا در register_bet_win: {e}")

def register_casino_win(user_id, chat_id, display_name, amount_won=0):
    try:
        progress = get_progress(user_id)
        count = int(progress.get("casino_wins_count", 0) or 0) + 1
        supabase.table("user_progress").update({"casino_wins_count": count}).eq("user_id", user_id).execute()
        bonus = min(XP_BONUS_CASINO_CAP, (amount_won // 100_000) * XP_BONUS_PER_CASINO_100K)
        add_xp(user_id, XP_PER_CASINO_WIN + bonus, chat_id=chat_id, display_name=display_name)
        _check_threshold_trophies(user_id, count, CASINO_WIN_TROPHY_THRESHOLDS, chat_id, display_name)
        _check_wealth_trophies(user_id, chat_id, display_name)
    except Exception as e:
        logging.error(f"خطا در register_casino_win: {e}")

def register_tournament_win(user_id, chat_id, display_name):
    add_xp(user_id, XP_PER_TOURNAMENT_WIN, chat_id=chat_id, display_name=display_name)
    award_trophy(user_id, "tournament_win", chat_id=chat_id, display_name=display_name)

def register_daily_gift(user_id, chat_id, display_name):
    add_xp(user_id, XP_PER_DAILY_GIFT, chat_id=chat_id, display_name=display_name)
    _notify_group_if_enabled(chat_id, "daily_gift", f"🎁 {display_name} هدیه روزانه گرفت!")

def _check_wealth_trophies(user_id, chat_id, display_name):
    balance = get_balance(user_id)
    _check_threshold_trophies(user_id, balance, WEALTH_TROPHY_THRESHOLDS, chat_id, display_name)

def stats_text_for_user(user_id, display_name):
    user = get_user(user_id) or {}
    progress = get_progress(user_id)
    trophies = get_user_trophies(user_id)
    bets_won = int(progress.get("bets_won_count", 0) or 0)
    casino_wins = int(progress.get("casino_wins_count", 0) or 0)
    diamonds = user.get("diamonds", 0)
    return (
        "◈ ━━━━━ 𝗦𝘁𝗮𝘁𝗶𝘀𝘁𝗶𝗰𝘀 ━━━━━ ◈\n"
        "⏣ | آمار شما\n\n"
        f"❖ | شرط‌های برده: {bets_won:,}\n"
        f"❖ | بازی‌های کازینو برده: {casino_wins:,}\n"
        f"$ | موجودی فعلی: {diamonds:,}\n"
        f"☻ | تعداد جام‌ها: {len(trophies)}\n"
        "◈ ━━━━━ 𝗦𝘁𝗮𝘁𝗶𝘀𝘁𝗶𝗰𝘀 ━━━━━ ◈"
    )

def trophies_help_lines():
    """لیست کامل جام‌ها برای نمایش در بخش راهنما."""
    return "\n".join(f"• {title} — {desc}" for title, desc in TROPHIES.values())

def trophies_text_for_user(user_id):
    trophies = get_user_trophies(user_id)
    if not trophies:
        return "🏅 هنوز هیچ جامی نگرفتی! با فعالیت در ربات جام‌های مختلف بگیر."
    lines = ["🏅 جام‌های شما:\n"]
    for key in trophies:
        info = TROPHIES.get(key)
        if info:
            lines.append(f"• {info[0]} — {info[1]}")
    return "\n".join(lines)

# ---------- تنظیمات اعلان‌های گروه ----------
def get_notify_settings(chat_id):
    try:
        resp = supabase.table("group_notify_settings").select("*").eq("chat_id", chat_id).execute()
        if resp.data:
            row = dict(resp.data[0])
            for k, v in NOTIFY_DEFAULTS.items():
                if k not in row or row[k] is None:
                    row[k] = v
            return row
        default = {"chat_id": chat_id, **NOTIFY_DEFAULTS}
        supabase.table("group_notify_settings").insert(default).execute()
        return default
    except Exception as e:
        logging.error(f"خطا در get_notify_settings: {e}")
        return {"chat_id": chat_id, **NOTIFY_DEFAULTS}

def set_notify_setting(chat_id, key, value):
    try:
        supabase.table("group_notify_settings").update({key: value}).eq("chat_id", chat_id).execute()
    except Exception as e:
        logging.error(f"خطا در set_notify_setting: {e}")

def notify_settings_markup(chat_id):
    settings = get_notify_settings(chat_id)
    markup = types.InlineKeyboardMarkup()
    for key, label in NOTIFY_LABELS.items():
        state = "✅" if settings.get(key, True) else "❌"
        markup.add(colored_button(
            f"{state} {label}", callback_data=f"notifytoggle|{key}"
        ))
    markup.add(colored_button("🏠 بستن", callback_data="notifyclose"))
    return markup

def notify_settings_text(chat_id):
    settings = get_notify_settings(chat_id)
    lines = ["⚙️ تنظیمات اعلان‌های گروه", "─────────────────────"]
    for key, label in NOTIFY_LABELS.items():
        state = "فعال" if settings.get(key, True) else "غیرفعال"
        mark = "✅" if settings.get(key, True) else "❌"
        lines.append(f"{mark} {label}: {state}")
    return "\n".join(lines)

@bot.message_handler(commands=["notifysettings"])
@bot.message_handler(func=lambda m: text_is(m, "تنظیمات اعلان"))
def cmd_notify_settings(message):
    if message.chat.type not in ("group", "supergroup"):
        bot.reply_to(message, "این دستور فقط داخل گروه کار می‌کند.")
        return
    try:
        member = bot.get_chat_member(message.chat.id, message.from_user.id)
        is_admin = member.status in ("administrator", "creator") or message.from_user.id in ADMIN_IDS
    except Exception:
        is_admin = message.from_user.id in ADMIN_IDS
    if not is_admin:
        bot.reply_to(message, "⛔ فقط ادمین‌های گروه می‌توانند تنظیمات اعلان را تغییر دهند.")
        return
    bot.reply_to(message, notify_settings_text(message.chat.id), reply_markup=notify_settings_markup(message.chat.id))

@bot.callback_query_handler(func=lambda call: call.data.startswith("notifytoggle|"))
def notify_toggle(call):
    if call.message.chat.type not in ("group", "supergroup"):
        bot.answer_callback_query(call.id)
        return
    try:
        member = bot.get_chat_member(call.message.chat.id, call.from_user.id)
        is_admin = member.status in ("administrator", "creator") or call.from_user.id in ADMIN_IDS
    except Exception:
        is_admin = call.from_user.id in ADMIN_IDS
    if not is_admin:
        bot.answer_callback_query(call.id, "⛔ فقط ادمین‌های گروه اجازه دارند.", show_alert=True)
        return
    key = call.data.split("|", 1)[1]
    if key not in NOTIFY_DEFAULTS:
        bot.answer_callback_query(call.id, "تنظیم نامعتبر است.", show_alert=True)
        return
    settings = get_notify_settings(call.message.chat.id)
    new_value = not settings.get(key, True)
    set_notify_setting(call.message.chat.id, key, new_value)
    bot.answer_callback_query(call.id)
    safe_edit_message(
        notify_settings_text(call.message.chat.id),
        call.message.chat.id, call.message.message_id,
        reply_markup=notify_settings_markup(call.message.chat.id)
    )

@bot.callback_query_handler(func=lambda call: call.data == "notifyclose")
def notify_close(call):
    bot.answer_callback_query(call.id)
    try:
        bot.delete_message(call.message.chat.id, call.message.message_id)
    except Exception:
        pass

LAQAB_DURATION_SECONDS = 7 * 86400  # هر لقب ویژه ۱ هفته اعتبار داره

def _migrate_legacy_tags(cosmetics):
    """اگه کاربر از سیستم قدیمی (تک‌لقب) یه لقب داشته باشه، به فرمت لیست جدید تبدیلش می‌کنه."""
    if "tags" not in cosmetics and cosmetics.get("tag"):
        cosmetics["tags"] = [{"name": cosmetics["tag"], "expires": cosmetics.get("tag_expires") or 0}]
    cosmetics.setdefault("tags", [])
    return cosmetics

def _purge_expired_tags(cosmetics):
    """لقب‌های منقضی‌شده رو از لیست حذف می‌کنه؛ اگه لقب فعال هم منقضی شده بود پاکش می‌کنه."""
    now = int(time.time())
    tags = [t for t in cosmetics.get("tags", []) if int(t.get("expires") or 0) > now]
    removed = len(tags) != len(cosmetics.get("tags", []))
    cosmetics["tags"] = tags
    if cosmetics.get("active_tag") and not any(t.get("name") == cosmetics["active_tag"] for t in tags):
        cosmetics["active_tag"] = None
        removed = True
    return cosmetics, removed

def _apply_cosmetic(user_id, cosmetic_type, value):
    try:
        progress = get_progress(user_id)
        cosmetics = dict(progress.get("cosmetics") or {})
        cosmetics = _migrate_legacy_tags(cosmetics)
        cosmetics, _ = _purge_expired_tags(cosmetics)
        if cosmetic_type == "tag":
            tags = cosmetics["tags"]
            new_expires = int(time.time()) + LAQAB_DURATION_SECONDS
            existing = next((t for t in tags if t.get("name") == value), None)
            if existing:
                existing["expires"] = new_expires
            else:
                tags.append({"name": value, "expires": new_expires})
            cosmetics["tags"] = tags
            # توجه: لقب جدید خودکار فعال نمی‌شه، کاربر باید خودش از بخش لقب‌ها انتخابش کنه.
            cosmetics.pop("tag", None)
            cosmetics.pop("tag_expires", None)
        supabase.table("user_progress").update({"cosmetics": cosmetics}).eq("user_id", user_id).execute()
    except Exception as e:
        logging.error(f"خطا در _apply_cosmetic: {e}")

def get_user_tags(user_id):
    """همه‌ی لقب‌های هنوز-معتبرِ کاربر رو برمی‌گردونه (منقضی‌شده‌ها خودکار حذف می‌شن)."""
    try:
        progress = get_progress(user_id)
        cosmetics = _migrate_legacy_tags(dict(progress.get("cosmetics") or {}))
        cosmetics, changed = _purge_expired_tags(cosmetics)
        if changed:
            supabase.table("user_progress").update({"cosmetics": cosmetics}).eq("user_id", user_id).execute()
        return cosmetics.get("tags", []), cosmetics.get("active_tag")
    except Exception as e:
        logging.error(f"خطا در get_user_tags: {e}")
        return [], None

def set_active_tag(user_id, index):
    """یکی از لقب‌های معتبر کاربر رو به‌عنوان لقب نمایشی فعال انتخاب می‌کنه."""
    try:
        progress = get_progress(user_id)
        cosmetics = _migrate_legacy_tags(dict(progress.get("cosmetics") or {}))
        cosmetics, _ = _purge_expired_tags(cosmetics)
        tags = cosmetics.get("tags", [])
        if index < 0 or index >= len(tags):
            return False, "لقب پیدا نشد."
        entry = tags[index]
        cosmetics["active_tag"] = entry["name"]
        supabase.table("user_progress").update({"cosmetics": cosmetics}).eq("user_id", user_id).execute()
        return True, entry["name"]
    except Exception as e:
        logging.error(f"خطا در set_active_tag: {e}")
        return False, "خطایی پیش اومد."

def get_active_tag(user_id):
    """لقب فعال کاربر رو برمی‌گردونه، یا None اگه نداره/منقضی شده."""
    try:
        tags, active_name = get_user_tags(user_id)
        if not active_name:
            return None
        if not any(t.get("name") == active_name for t in tags):
            return None
        return active_name
    except Exception as e:
        logging.error(f"خطا در get_active_tag: {e}")
        return None

def _format_remaining(expires_ts):
    remaining = int(expires_ts) - int(time.time())
    if remaining <= 0:
        return "⌛ منقضی شده"
    days = remaining // 86400
    hours = (remaining % 86400) // 3600
    minutes = (remaining % 3600) // 60
    if days > 0:
        return f"⏳ {days} روز و {hours} ساعت"
    if hours > 0:
        return f"⏳ {hours} ساعت و {minutes} دقیقه"
    return f"⏳ {minutes} دقیقه"

def display_name_with_tag(user_id, display_name):
    """نام نمایشی عمومی؛ لقب‌های کاربر فقط داخل بخش حساب کاربری نمایش داده می‌شوند."""
    name = (display_name or "کاربر").strip()
    if "🤖" in name or name == "ربات":
        return "🤖 ربات" if "ربات" in name else name
    return name

def casino_name_with_tag(player):
    # سازگاری با کدهای قدیمی؛ عمداً هیچ لقبی اضافه نمی‌کند.
    return display_name_with_tag(player.get("id"), player.get("name"))

# ================== پارس کردن مقادیر با کا/میل ==================
PERSIAN_DIGITS = "۰۱۲۳۴۵۶۷۸۹"
def _normalize_digits(text):
    """ارقام فارسی/عربی رو به انگلیسی تبدیل می‌کنه."""
    table = str.maketrans(PERSIAN_DIGITS + "٠١٢٣٤٥٦٧٨٩", "01234567890123456789")
    return text.translate(table)

# ترتیب مهمه: عبارت‌های بلندتر (میلیون/هزار) قبل از کوتاه‌ترها (م/ک) چک بشن
_AMOUNT_RE = re.compile(
    r"^(\d+(?:\.\d+)?)\s*(میلیون|میل|million|m|هزار|کا|کی|ک|k)?$",
    re.IGNORECASE
)

# برای استفاده داخل رجکس‌های تشخیص پیام (تریگر دستورات متنی)؛ عدد + پسوند اختیاری کا/کی/میل
AMOUNT_TOKEN = r"[\d۰-۹]+(?:[.,،][\d۰-۹]+)?\s*(?:میلیون|میل|million|m|هزار|کا|کی|ک|k)?"

def parse_amount(raw_text):
    """
    ورودی مثل '120', '120k', '120 k', '120کا', '120 کا', '12میل', '12 میلیون'
    رو به عدد صحیح تبدیل می‌کنه. کا/k = ضرب در هزار، میل/میلیون/m = ضرب در میلیون.
    اگه فرمت نامعتبر بود None برمی‌گردونه.
    """
    if not raw_text:
        return None
    text = _normalize_digits(raw_text.strip().lower())
    text = text.replace("،", "").replace(",", "")  # جداکننده هزارگان رو حذف کن
    m = _AMOUNT_RE.match(text)
    if not m:
        return None
    number = float(m.group(1))
    suffix = m.group(2)
    if suffix in ("هزار", "کا", "کی", "ک", "k"):
        number *= 1_000
    elif suffix in ("میلیون", "میل", "million", "m"):
        number *= 1_000_000
    result = int(round(number))
    if result <= 0:
        return None
    return result

def extract_amount_from_text(text, pattern_before):
    """
    برای پیام‌هایی مثل 'شرط بندی 120کا' یا 'انتقال الماس 12 میل':
    pattern_before رگ‌اکسی برای قسمت قبل از عدده (مثلاً 'شرط\\s*بندی?\\s+').
    عدد+واحد بعدش رو با parse_amount می‌خونه.
    """
    unit = r"(?:میلیون|میل|هزار|کا|ک|million|k|m)"
    match = re.search(
        pattern_before + r"([۰-۹0-9,،.]+\s*" + unit + r"?)",
        text, re.IGNORECASE
    )
    if not match:
        return None
    return parse_amount(match.group(1))

def get_effective_tax_rate(user_id, context="bet"):
    """نرخ مالیات مؤثر بر اساس جام‌های شرط‌بندی یا کازینوی کاربر."""
    trophies = get_user_trophies(user_id)
    if context == "casino":
        if "casino_100" in trophies:
            return 0.05
        if "casino_50" in trophies:
            return 0.08
    else:
        if "bet_100" in trophies:
            return 0.05
        if "bet_50" in trophies:
            return 0.08
    return TAX_RATE

def get_effective_loan_tax_rate(user_id):
    """نرخ کسر وام مؤثر؛ فقط جام سلطان قمار یا سلطان کازینو اون رو کاهش می‌ده."""
    trophies = get_user_trophies(user_id)
    if "bet_100" in trophies or "casino_100" in trophies:
        return 0.08
    return LOAN_TAX_RATE

def calculate_payout(winner_id, pool, context="bet"):
    tax_rate = get_effective_tax_rate(winner_id, context)
    admin_tax = int(pool * tax_rate)
    loan_repay = 0
    loan_rate = LOAN_TAX_RATE
    loan_balance = get_loan_balance(winner_id)
    if loan_balance > 0:
        loan_rate = get_effective_loan_tax_rate(winner_id)
        loan_cut = int(pool * loan_rate)
        loan_repay = min(loan_cut, loan_balance)
        # در حالت اتمیک، کسر وام داخل settlement RPC انجام می‌شود.
        # calculate_payout فقط باید مبلغ را محاسبه کند و side-effect نداشته باشد.
        if loan_repay > 0 and not ATOMIC_DB_MODE:
            change_loan_balance(winner_id, -loan_repay)
    final_payout = pool - admin_tax - loan_repay
    if final_payout < 0:
        final_payout = 0
    return final_payout, admin_tax, loan_repay, tax_rate, loan_rate


# ================== واریز خودکار سود بانک ==================
def apply_all_bank_interest():
    """هر روز در ساعت ۰۰:۰۰ تهران سود همه حساب‌های بانکی را واریز می‌کند."""
    try:
        response = supabase.table("users").select(
            "user_id,bank_account_number,bank_balance,bank_interest_date"
        ).not_.is_("bank_account_number", "null").execute()

        for user in (response.data or []):
            user_id = user.get("user_id")
            try:
                apply_bank_interest(user_id)
            except Exception as e:
                logging.error(f"خطا در واریز سود بانک برای {user_id}: {e}")

        logging.info("سود روزانه بانک‌ها در ساعت ۰۰:۰۰ تهران بررسی و واریز شد.")
    except Exception as e:
        logging.error(f"خطا در اجرای سود خودکار بانک: {e}")


# Scheduler timezone must be Tehran so 00:00 is Iranian local midnight.
bank_scheduler = BackgroundScheduler(timezone=TEHRAN_TZ)
bank_scheduler.add_job(
    apply_all_bank_interest,
    "cron",
    hour=0,
    minute=0,
    id="daily_bank_interest",
    replace_existing=True,
    max_instances=1,
    coalesce=True,
)
bank_scheduler.start()

# ================== توابع تورنومنت ==================
def get_active_tournament():
    """بازگرداندن تورنومنت فعال (status='active') یا None"""
    try:
        response = supabase.table("tournaments").select("*").eq("status", "active").execute()
        return response.data[0] if response.data else None
    except Exception as e:
        logging.error(f"خطا در get_active_tournament: {e}")
        return None

def get_user_code(tournament_id, user_id):
    """دریافت کد کاربر برای تورنومنت مشخص، در صورت نبود، تولید و ذخیره می‌کند"""
    try:
        # اول جستجو
        resp = supabase.table("tournament_codes").select("*").eq("tournament_id", tournament_id).eq("user_id", user_id).execute()
        if resp.data:
            return resp.data[0]['code']
        # تولید کد یکتا
        import string
        import random
        while True:
            code = ''.join(random.choices(string.ascii_lowercase + string.digits, k=6))
            # بررسی یکتایی
            check = supabase.table("tournament_codes").select("*").eq("code", code).execute()
            if not check.data:
                break
        # ذخیره
        supabase.table("tournament_codes").insert({
            "tournament_id": tournament_id,
            "user_id": user_id,
            "code": code
        }).execute()
        return code
    except Exception as e:
        logging.error(f"خطا در get_user_code: {e}")
        return None

def get_gift_code(code):
    """دریافت اطلاعات یک کد هدیه بر اساس متن کد."""
    try:
        resp = supabase.table("gift_codes").select("*").eq("code", code).execute()
        return resp.data[0] if resp.data else None
    except Exception as e:
        logging.error(f"خطا در get_gift_code: {e}")
        return None

def generate_unique_gift_code():
    """تولید یک کد هدیه یکتای ۸ کاراکتری (حروف بزرگ انگلیسی + عدد)."""
    try:
        for _ in range(50):
            code = ''.join(random.choices(string.ascii_uppercase + string.digits, k=8))
            if not get_gift_code(code):
                return code
        return None
    except Exception as e:
        logging.error(f"خطا در generate_unique_gift_code: {e}")
        return None

def create_gift_code(admin_id, amount, capacity):
    """ساخت کد هدیه جدید با مقدار جایزه و ظرفیت مشخص و ذخیره‌ی آن در دیتابیس."""
    code = generate_unique_gift_code()
    if not code:
        return None
    try:
        supabase.table("gift_codes").insert({
            "code": code,
            "amount": int(amount),
            "capacity": int(capacity),
            "redeemed_count": 0,
            "created_by": admin_id,
        }).execute()
        return code
    except Exception as e:
        logging.error(f"خطا در create_gift_code: {e}")
        return None

_gift_code_lock = threading.Lock()

def redeem_gift_code(user_id, code):
    """
    تلاش برای فعال‌سازی یک کد هدیه توسط یک کاربر.
    خروجی: (success, message, amount)
    اگر کد اصلاً وجود نداشته باشد، (False, None, None) برمی‌گردد تا پیامی
    برای پیام‌های عادی گروه که تصادفاً شبیه کد هستند نمایش داده نشود.
    """
    with _gift_code_lock:
        try:
            gift = get_gift_code(code)
            if not gift:
                return False, None, None

            already = (
                supabase.table("gift_code_redemptions")
                .select("id").eq("code", code).eq("user_id", user_id).execute()
            )
            if already.data:
                return False, "⚠️ شما قبلاً این کد هدیه را فعال کرده‌اید.", None

            if int(gift.get("redeemed_count", 0) or 0) >= int(gift.get("capacity", 0) or 0):
                supabase.table("gift_codes").delete().eq("code", code).execute()
                return False, "❌ ظرفیت این کد هدیه تکمیل شده است.", None

            amount = int(gift.get("amount", 0) or 0)
            supabase.table("gift_code_redemptions").insert({
                "code": code,
                "user_id": user_id,
            }).execute()
            new_redeemed = int(gift.get("redeemed_count", 0) or 0) + 1
            supabase.table("gift_codes").update({"redeemed_count": new_redeemed}).eq("code", code).execute()
            update_diamonds(user_id, amount)

            if new_redeemed >= int(gift.get("capacity", 0) or 0):
                supabase.table("gift_codes").delete().eq("code", code).execute()

            return True, "✅", amount
        except Exception as e:
            logging.error(f"خطا در redeem_gift_code: {e}")
            return False, "❌ خطایی رخ داد.", None

def get_votes_for_tournament(tournament_id):
    """دریافت تعداد آراء برای هر کاربر در تورنومنت"""
    try:
        response = supabase.table("tournament_votes").select("target_user_id").eq("tournament_id", tournament_id).execute()
        votes = {}
        for row in response.data:
            target = row['target_user_id']
            votes[target] = votes.get(target, 0) + 1
        return votes
    except Exception as e:
        logging.error(f"خطا در get_votes_for_tournament: {e}")
        return {}

def get_tournament_ranking(tournament_id, limit=10):
    """بازگرداندن لیست (user_id, vote_count) مرتب نزولی"""
    votes = get_votes_for_tournament(tournament_id)
    sorted_users = sorted(votes.items(), key=lambda x: x[1], reverse=True)
    return sorted_users[:limit]

def add_vote(tournament_id, voter_id, code):
    """ثبت رأی: اگر کد معتبر باشد و رأی‌دهنده قبلاً رأی نداده باشد"""
    try:
        # بررسی کد
        code_resp = supabase.table("tournament_codes").select("user_id").eq("tournament_id", tournament_id).eq("code", code).execute()
        if not code_resp.data:
            return False, "کد نامعتبر است ❌"
        target_user_id = code_resp.data[0]['user_id']
        if target_user_id == voter_id:
            return False, "نمی‌توانید به خودتان رأی دهید ❌"
        # بررسی تکراری نبودن رأی
        vote_check = supabase.table("tournament_votes").select("*").eq("tournament_id", tournament_id).eq("voter_id", voter_id).execute()
        if vote_check.data:
            return False, "شما قبلاً رأی خود را ثبت کرده‌اید ❌"
        # ثبت رأی
        supabase.table("tournament_votes").insert({
            "tournament_id": tournament_id,
            "voter_id": voter_id,
            "target_user_id": target_user_id
        }).execute()
        return True, "✅ رأی شما با موفقیت ثبت شد."
    except Exception as e:
        logging.error(f"خطا در add_vote: {e}")
        return False, "خطای داخلی رخ داد."

def end_tournament(tournament_id):
    """پایان تورنومنت: محاسبه برندگان و توزیع جوایز"""
    try:
        tourn = supabase.table("tournaments").select("*").eq("tournament_id", tournament_id).execute()
        if not tourn.data:
            return False, "تورنومنت یافت نشد"
        prizes = tourn.data[0]['prizes']  # JSON مانند {"1": 1000, "2": 500, ...}
        if not prizes:
            return False, "جایزه‌ای تعریف نشده است"
        # دریافت رتبه‌بندی
        ranking = get_tournament_ranking(tournament_id, limit=10)
        # توزیع جوایز
        for idx, (user_id, votes) in enumerate(ranking, start=1):
            prize = prizes.get(str(idx), 0)
            if prize > 0:
                update_diamonds(user_id, prize)
            if idx == 1:
                try:
                    register_tournament_win(user_id, None, str(user_id))
                except Exception as e:
                    logging.error(f"خطا در ثبت XP قهرمان تورنومنت: {e}")
        # تغییر وضعیت تورنومنت
        end_time = datetime.now(TEHRAN_TZ).isoformat()
        supabase.table("tournaments").update({"status": "ended", "end_time": end_time}).eq("tournament_id", tournament_id).execute()
        return True, "تورنومنت پایان یافت و جوایز توزیع شد."
    except Exception as e:
        logging.error(f"خطا در end_tournament: {e}")
        return False, f"خطا: {e}"

# ================== دکمه‌ها و توابع کمکی ==================
def main_menu_markup(user_id=None):
    # دکمه‌های اصلی؛ پنل مدیریت فقط برای ادمین‌ها نمایش داده می‌شود.
    markup = types.InlineKeyboardMarkup()
    markup.row(colored_button("👤 حساب کاربری", callback_data=f"showaccount|{user_id}" if user_id else "showaccount"))
    markup.row(colored_button("📖 راهنما", callback_data=f"showhelp|{user_id}" if user_id else "showhelp"))
    if user_id in ADMIN_IDS:
        markup.row(colored_button("⚙️ پنل مدیریت", callback_data=f"admin_panel|{user_id}"))
    return markup


def account_menu_markup(user_id):
    markup = types.InlineKeyboardMarkup()
    markup.row(colored_button("💸 انتقال الماس", callback_data=f"acctransfer|{user_id}"))
    markup.row(
        colored_button("🏅 جام‌ها", callback_data=f"showtrophies|{user_id}"),
        colored_button("🏷 لقب‌ها", callback_data=f"showtags|{user_id}")
    )
    markup.row(colored_button("📊 آمار", callback_data=f"showstats|{user_id}"))
    markup.row(colored_button("🏠 منوی اصلی", callback_data=f"mainmenu|{user_id}"))
    return markup

def back_to_main_menu_markup(user_id=None):
    markup = types.InlineKeyboardMarkup()
    markup.add(colored_button("🏠 منوی اصلی", callback_data=f"mainmenu|{user_id}" if user_id else "mainmenu"))
    return markup

# ================== سیستم پنل‌های تک‌پیامی ==================
# هر بخش یک پیام پنل دارد و تمام تغییرات همان پیام را ویرایش می‌کنند.
# برای دوام بعد از ری‌استارت، message_id پنل در جدول bot_panels ذخیره می‌شود.
_panel_cache = {}
_panel_cache_lock = threading.Lock()


def _panel_key(chat_id, user_id, panel):
    return (int(chat_id), int(user_id), str(panel))


def get_saved_panel_message_id(chat_id, user_id, panel):
    key = _panel_key(chat_id, user_id, panel)
    with _panel_cache_lock:
        cached = _panel_cache.get(key)
    if cached:
        return cached
    try:
        res = supabase.table("bot_panels").select("message_id").eq("chat_id", chat_id).eq("user_id", user_id).eq("panel_key", panel).limit(1).execute()
        if res.data:
            mid = int(res.data[0]["message_id"])
            with _panel_cache_lock:
                _panel_cache[key] = mid
            return mid
    except Exception as e:
        logging.warning(f"bot_panels خوانده نشد (ممکنه migration هنوز اجرا نشده باشه): {e}")
    return None


def save_panel_message_id(chat_id, user_id, panel, message_id):
    key = _panel_key(chat_id, user_id, panel)
    with _panel_cache_lock:
        _panel_cache[key] = int(message_id)
    try:
        supabase.table("bot_panels").upsert({
            "chat_id": int(chat_id),
            "user_id": int(user_id),
            "panel_key": str(panel),
            "message_id": int(message_id),
        }, on_conflict="chat_id,user_id,panel_key").execute()
    except Exception as e:
        logging.warning(f"bot_panels ذخیره نشد: {e}")


def show_or_edit_panel(message, user_id, panel, text, reply_markup=None, parse_mode=None):
    """برای ورودی متنی همیشه پنل جدید بساز و همیشه روی همون پیامی که کاربر فرستاده
    ریپلای بزن. این باعث می‌شه وقتی چند نفر هم‌زمان یک دستور مشابه می‌فرستن (مثلاً
    «موجودی»)، مشخص باشه هر پاسخ برای کدوم پیام/کاربره و موجودی‌ها با هم قاطی نشه.
    پنل قبلی دست‌نخورده بماند؛ ادیت پنل فقط در callback handlerهای دکمه‌ها انجام می‌شود.
    """
    chat_id = message.chat.id
    sent = safe_send_message(
        chat_id, text, reply_markup=reply_markup, parse_mode=parse_mode,
        reply_to_message_id=message.message_id,
    )
    if sent:
        save_panel_message_id(chat_id, user_id, panel, sent.message_id)
        return sent.message_id
    return None


def get_pending_prompt_message_id(chat_id, user_id):
    with _next_step_lock:
        state = _next_step_pending.get((chat_id, user_id))
        return state.get("prompt_message_id") if state else None


def is_reply_to_panel(message, panel_message_id):
    """قبلاً ورودی مرحله‌ای فقط با ریپلای مستقیم روی پنل معتبر بود؛ همین باعث
    می‌شد کاربرهایی که فقط عدد رو تایپ می‌کردن (بدون ریپلای کردن)، پیامشون
    نادیده گرفته بشه (باگ «تو بانک واریز/برداشت/وام نمیشه»). چون هر مرحله
    الان بر اساس (چت، کاربر) جدا نگه داشته می‌شه، دیگه نیازی به ریپلای برای
    تشخیص هویت نیست؛ فقط اگر کاربر عمداً به پیام دیگه‌ای (غیر از پنل) ریپلای
    کرده باشه، اون رو نامعتبر می‌دونیم."""
    reply = getattr(message, "reply_to_message", None)
    if not reply or panel_message_id is None:
        return True
    if reply.message_id != int(panel_message_id):
        return False
    sender = getattr(reply, "from_user", None)
    return bool(sender and getattr(sender, "is_bot", False))


def require_reply_to_panel(message, panel_message_id, instruction="لطفاً روی همین پیام پنل ریپلای کن و مقدار را بفرست."):
    if is_reply_to_panel(message, panel_message_id):
        return True
    # پیام جدیدی نمی‌فرستیم؛ همان پنل را راهنمایی می‌کنیم.
    if panel_message_id:
        safe_edit_message(f"↩️ {instruction}", message.chat.id, panel_message_id, reply_markup=None)
    return False

def safe_edit_message(text, chat_id, message_id, reply_markup=None, parse_mode=None, retries=2):
    """Reliable edit: suppress only a known-successful duplicate; never drop a new edit."""
    key = _edit_cache_key(chat_id, message_id, "text")
    fingerprint = _edit_fingerprint({
        "text": _force_rtl(text),
        "reply_markup": reply_markup,
        "parse_mode": parse_mode,
    })

    with _get_telegram_edit_lock(chat_id, message_id):
        if _edit_success_cache.get(key) == fingerprint:
            return True

        network_attempts = 0
        while True:
            try:
                _wait_for_telegram_slot(chat_id)
                _original_edit_message_text(
                    _force_rtl(text),
                    chat_id=chat_id,
                    message_id=message_id,
                    reply_markup=reply_markup,
                    parse_mode=parse_mode,
                )
                _remember_edit_success(key, fingerprint)
                return True
            except Exception as exc:
                if _is_message_not_modified(exc):
                    _remember_edit_success(key, fingerprint)
                    return True
                if _is_permanent_message_error(exc):
                    logging.warning("پیام %s قابل ویرایش نیست: %s", message_id, exc)
                    return False
                if _is_rate_limit_error(exc):
                    retry_after = _extract_retry_after(exc) or 5.0
                    # This call itself owns the lock; sleeping here guarantees
                    # no other edit can overtake this edit.
                    wait_seconds = retry_after + _TELEGRAM_429_SAFETY_MARGIN
                    logging.warning(
                        "Telegram rate limit هنگام ویرایش پیام %s؛ %.1f ثانیه صبر می‌کنیم.",
                        message_id, wait_seconds
                    )
                    time.sleep(wait_seconds)
                    continue
                network_attempts += 1
                if network_attempts <= retries:
                    time.sleep(min(0.5 * network_attempts, 2.0))
                    continue
                logging.error("خطا در ویرایش پیام %s: %s", message_id, exc)
                return False


def safe_edit_message_reply_markup(chat_id, message_id, reply_markup=None, retries=2):
    key = _edit_cache_key(chat_id, message_id, "markup")
    fingerprint = _edit_fingerprint(reply_markup)
    with _get_telegram_edit_lock(chat_id, message_id):
        if _edit_success_cache.get(key) == fingerprint:
            return True
        network_attempts = 0
        while True:
            try:
                _wait_for_telegram_slot(chat_id)
                _original_edit_message_reply_markup(
                    chat_id=chat_id,
                    message_id=message_id,
                    reply_markup=reply_markup,
                )
                _remember_edit_success(key, fingerprint)
                return True
            except Exception as exc:
                if _is_message_not_modified(exc):
                    _remember_edit_success(key, fingerprint)
                    return True
                if _is_permanent_message_error(exc):
                    logging.warning("کیبورد پیام %s قابل ویرایش نیست: %s", message_id, exc)
                    return False
                if _is_rate_limit_error(exc):
                    retry_after = _extract_retry_after(exc) or 5.0
                    wait_seconds = retry_after + _TELEGRAM_429_SAFETY_MARGIN
                    logging.warning(
                        "Telegram rate limit هنگام ویرایش کیبورد پیام %s؛ %.1f ثانیه صبر می‌کنیم.",
                        message_id, wait_seconds
                    )
                    time.sleep(wait_seconds)
                    continue
                network_attempts += 1
                if network_attempts <= retries:
                    time.sleep(min(0.5 * network_attempts, 2.0))
                    continue
                logging.error("خطا در ویرایش کیبورد پیام %s: %s", message_id, exc)
                return False


def safe_send_message(chat_id, text, reply_markup=None, parse_mode=None, reply_to_message_id=None):
    """Send without unsafe duplicate fallback; 429 is retried by the API gate."""
    try:
        return bot.send_message(
            chat_id,
            text,
            reply_markup=reply_markup,
            parse_mode=parse_mode,
            reply_to_message_id=reply_to_message_id,
        )
    except Exception as exc:
        # Only remove reply_to when Telegram explicitly says the replied-to
        # message is unavailable. Never resend after an arbitrary exception.
        err = str(exc).lower()
        if reply_to_message_id is not None and (
            "reply message not found" in err or
            "message to reply not found" in err or
            "message identifier is not specified" in err
        ):
            try:
                logging.warning(
                    "ریپلای به پیام %s ممکن نبود؛ همان پیام بدون ریپلای ارسال می‌شود.",
                    reply_to_message_id,
                )
                return bot.send_message(
                    chat_id, text, reply_markup=reply_markup, parse_mode=parse_mode
                )
            except Exception as exc2:
                logging.error("خطا در ارسال پیام بدون ریپلای: %s", exc2)
                return None
        logging.error("خطا در ارسال پیام: %s", exc)
        return None

def _auto_edit_after_delay(chat_id, message_id, delay, text, reply_markup, parse_mode=None):
    """بعد از delay ثانیه، پیام نتیجه را به پنل مربوطه برمی‌گرداند."""
    def _job():
        try:
            safe_edit_message(text, chat_id, message_id, reply_markup=reply_markup, parse_mode=parse_mode)
        except Exception as e:
            logging.error(f"خطا در برگشت خودکار پنل: {e}")
    timer = threading.Timer(delay, _job)
    timer.daemon = True
    timer.start()


def auto_return_to_main(chat_id, message_id, user_id, delay=5):
    _auto_edit_after_delay(
        chat_id, message_id, delay,
        "به بات شرط‌بندی خوش اومدید🌹\nاز دکمه‌های زیر استفاده کنید:",
        main_menu_markup(user_id)
    )


def auto_return_to_bank(chat_id, message_id, user_id, delay=5):
    _auto_edit_after_delay(
        chat_id, message_id, delay,
        bank_text(user_id),
        bank_markup(user_id),
        parse_mode="HTML"
    )


def auto_return_to_factory(chat_id, message_id, user_id, delay=5):
    factory = sync_factory_production(get_factory(user_id))
    name = get_user(user_id).get("username") if get_user(user_id) else str(user_id)
    _auto_edit_after_delay(
        chat_id, message_id, delay,
        factory_panel_text(factory, name),
        factory_main_markup(user_id)
    )


def auto_return_to_casino(chat_id, message_id, user_id, delay=5):
    _auto_edit_after_delay(
        chat_id, message_id, delay,
        "◈ ━━━━━ 𝗕𝗲𝘁 ━━━━━━ ◈\n"
        "♧ | به بخش کازینو خوش اومدی!\n\n"
        "❖ | یکی از بازی‌ها رو انتخاب کن:\n"
        "◈ ━━━━━ 𝗕𝗲𝘁 ━━━━━━ ◈",
        casino_games_keyboard(user_id)
    )

def extract_owner_id(call_data):
    """از callback_data شناسه صاحب پنل را استخراج می‌کند. همیشه آخرین بخش
    جدا‌شده با '|' است (پشتیبانی از فرمت‌های چندبخشی مثل cbet|game|amount|owner)."""
    try:
        return int(call_data.split("|")[-1])
    except (IndexError, ValueError):
        return None

def check_panel_owner(call):
    """اگر کاربری غیر از صاحب پنل روی دکمه بزند، بی‌صدا کلیک را نادیده می‌گیرد
    (بدون هیچ پیام popup) و None برمی‌گرداند. این جلوی سوءاستفاده‌ای را می‌گیرد
    که کاربر دیگری در گروه بتواند پنل شخصی شخص دیگر را با کلیک، تغییر بدهد
    یا از آن استفاده کند."""
    owner_id = extract_owner_id(call.data)
    if owner_id is None or call.from_user.id != owner_id:
        bot.answer_callback_query(call.id)  # فقط ack خالی؛ هیچ اتفاقی نمی‌افتد
        return None
    return owner_id

# ================== هندلر start ==================
@bot.message_handler(commands=["start"])
def cmd_start(message):
    user_id = message.from_user.id
    username = get_display_name(message.from_user)
    is_new = not get_user(user_id)

    if is_new:
        create_user(user_id, username)

    caption = "به بات شرط‌بندی خوش اومدید🌹\nاز دکمه‌های زیر استفاده کنید:"
    # تا وقتی URL واقعی عکس تنظیم نشده، از URL نمونه استفاده نکن.
    safe_send_message(message.chat.id, caption, reply_markup=main_menu_markup(user_id), reply_to_message_id=message.message_id)

# ================== کالبک منوی اصلی ==================
@bot.callback_query_handler(func=lambda call: call.data == "mainmenu" or call.data.startswith("mainmenu|"))
def main_menu(call):
    # اگه این دکمه داخل یه پنل شخصی (مثل بانک، حساب، رفرال، گردونه، راهنما) قرار
    # داشته باشه، شناسه صاحبش رو حمل می‌کنه؛ در این حالت فقط خودش می‌تونه بزنتش
    # و کلیک بقیه بی‌صدا نادیده گرفته میشه. روی پیام‌های عمومی/گروهی (نتیجه شرط،
    # رتبه‌بندی و ...) این دکمه owner نداره و برای همه باز می‌مونه.
    if "|" in call.data:
        clicker_id = check_panel_owner(call)
        if clicker_id is None:
            return
    else:
        clicker_id = call.from_user.id
    bot.answer_callback_query(call.id)

    # فقط clear_step_handler کافی نیست؛ ما یک سیستم next-step سفارشی هم داریم.
    # اگر کاربر وسط برداشت/واریز/وام «منوی اصلی» را بزند، باید آن مرحله هم
    # همان لحظه لغو شود تا پیام بعدی او دوباره توسط مرحله‌ی قدیمی بلعیده نشود.
    cancel_pending_step(call.message.chat.id, clicker_id)
    bot.clear_step_handler(call.message)

    caption = "به بات شرط‌بندی خوش اومدید🌹\nاز دکمه‌های زیر استفاده کنید:"
    # همون پیام قبلی ویرایش میشه (نه پیام جدید). این کار امنه چون بالاتر مالکیت
    # پنل‌های شخصی چک شده؛ فقط اگه ویرایش به هر دلیلی (مثلاً پیام اصلی عکس بود)
    # شکست بخوره، به‌عنوان فالبک یه پیام تازه فرستاده میشه.
    edited = safe_edit_message(caption, call.message.chat.id, call.message.message_id, main_menu_markup(clicker_id))
    if not edited:
        safe_send_message(call.message.chat.id, caption, reply_markup=main_menu_markup(clicker_id))

# ================== دستور /account ==================
@bot.message_handler(commands=["account"])
def cmd_account(message):
    user_id = message.from_user.id
    user = get_user(user_id)
    if not user:
        bot.reply_to(message, "اول /start بزن.")
        return

    diamonds = user.get('diamonds', 0)
    loan_balance = user.get('loan_balance', 0)
    progress = get_progress(user_id)
    level = int(progress.get("level", 1) or 1)
    xp = int(progress.get("xp", 0) or 0)
    _, title, _need, _reward = level_info(level)
    next_need = xp_needed_for_next_level(level)
    xp_line = f"{xp} / {next_need}" if next_need is not None else f"{xp} (حداکثر سطح)"

    text = (
        "◈ ━━━━━━ 𝗣𝗿𝗼𝗳𝗶𝗹𝗲 ━━━━━━ ◈\n"
        "⏣ | پروفایل شما\n\n"
        f"♛ | نام: {get_display_name(message.from_user)}\n"
        f"☏ | آیدی عددی : {user_id}\n"
        f"$ | موجودی الماس : {diamonds}\n"
        f"⎙ | باقیمانده وام فعلی: {loan_balance}\n"
        f"⌬ | سطح : {level} ({title})\n"
        f"⍟ | امتیاز : {xp_line}\n"
        "◈ ━━━━━━ 𝗣𝗿𝗼𝗳𝗶𝗹𝗲 ━━━━━━ ◈"
    )
    show_or_edit_panel(message, user_id, "account", text, back_to_main_menu_markup(user_id))

# دسترسی متنی منوی اصلی
@bot.message_handler(func=lambda m: text_is(m, "حساب کاربری"))
def text_account(message):
    cmd_account(message)

@bot.message_handler(func=lambda m: text_is(m, "راهنما", "کمک"))
def text_help(message):
    text = (
    "📖 راهنمای استفاده از بات\n\n"
    "💰 موجودی:\n"
    "کلمه «موجودی» را در چت ارسال کنید.\n\n"
    "💰 موجودی دیگران:\n"
    "کلمه «موجودی» را در چت به همراه ریپلای روی پیام شخص ارسال کنید.\n\n"
    "💸 انتقال الماس:\n"
    "روی پیام شخص ریپلای کنید و بنویسید:\n"
    "انتقال الماس 100 کا یا عدد دلخواه\n"
    "(یا از دکمه «انتقال الماس» تو حساب کاربری استفاده کنید)\n\n"
    "🎲 شرطبندی:\n"
    "برای شرط بنویسید:\n"
    "شرطبندی 100 کا یا عدد دلخواه\n\n"
    "🎰 کازینو:\n"
    "کلمه «کازینو» را در چت ارسال کنید.\n\n"
    "🏦 بانک الماس:\n"
    "کلمه «بانک» را ارسال کنید.\n\n"
    "🎡 گردونه روزانه:\n"
    "کلمه «گردونه» را در چت ارسال کنید و الماس رایگان بگیرید 🎁\n\n"
    "⛏ حفاری:\n"
    "کلمه «حفاری» را ارسال کنید.\n\n"
    "💣 دینامیت:\n"
    "بنویسید: دینامیت 100 کا یا عدد دلخواه\n\n"
    "🏆 رتبه‌بندی:\n"
    "کلمه «رنک» را ارسال کنید.\n\n"
    "👥 زیرمجموعه‌گیری:\n"
    "از دکمه زیرمجموعه‌گیری استفاده کنید.\n\n"
    f"{trophies_help_lines()}\n\n"
    "🏷 لقب‌ها:\n"
    "لقب‌هایی که تا حالا بردی، تو بخش «لقب‌ها» "
    "(داخل حساب کاربری) لیست می‌شن؛ هرکدوم ۱ هفته اعتبار داره و خودت باید انتخاب کنی "
    "کدومش نمایش داده بشه. لقب منقضی‌شده خودکار از لیست پاک می‌شه."
)
    show_or_edit_panel(message, message.from_user.id, "help", text, back_to_main_menu_markup(message.from_user.id))

# ================== بخش حساب کاربری ==================
@bot.callback_query_handler(func=lambda call: call.data == "showaccount" or call.data.startswith("showaccount|"))
def handle_show_account(call):
    if "|" in call.data:
        user_id = check_panel_owner(call)
        if user_id is None:
            return
    else:
        user_id = call.from_user.id
    bot.answer_callback_query(call.id)
    user = get_user(user_id)
    if not user:
        bot.send_message(call.message.chat.id, "اول /start بزن.")
        return
    username = user.get('username')
    diamonds = user.get('diamonds', 0)
    loan_balance = user.get('loan_balance', 0)
    last_spin = user.get('last_spin', 0)
    progress = get_progress(user_id)
    level = int(progress.get("level", 1) or 1)
    xp = int(progress.get("xp", 0) or 0)
    _, title, _need, _reward = level_info(level)
    next_need = xp_needed_for_next_level(level)
    xp_line = f"{xp} / {next_need}" if next_need is not None else f"{xp} (حداکثر سطح)"

    text = (
        "◈ ━━━━━━ 𝗣𝗿𝗼𝗳𝗶𝗹𝗲 ━━━━━━ ◈\n"
        "⏣ | پروفایل شما\n\n"
        f"♛ | نام: {get_display_name(call.from_user)}\n"
        f"☏ | آیدی عددی : {user_id}\n"
        f"$ | موجودی الماس : {diamonds}\n"
        f"⎙ | باقیمانده وام فعلی: {loan_balance}\n"
        f"⌬ | سطح : {level} ({title})\n"
        f"⍟ | امتیاز : {xp_line}\n"
        "◈ ━━━━━━ 𝗣𝗿𝗼𝗳𝗶𝗹𝗲 ━━━━━━ ◈"
    )
    safe_edit_message(text, call.message.chat.id, call.message.message_id, reply_markup=account_menu_markup(user_id))

# ================== بخش جام‌های من ==================
@bot.callback_query_handler(func=lambda call: call.data == "showtrophies" or call.data.startswith("showtrophies|"))
def handle_show_trophies(call):
    if "|" in call.data:
        user_id = check_panel_owner(call)
        if user_id is None:
            return
    else:
        user_id = call.from_user.id
    bot.answer_callback_query(call.id)
    if not get_user(user_id):
        bot.send_message(call.message.chat.id, "اول /start بزن.")
        return
    safe_edit_message(trophies_text_for_user(user_id), call.message.chat.id, call.message.message_id, reply_markup=None)

# ================== بخش آمار من ==================
@bot.callback_query_handler(func=lambda call: call.data == "showstats" or call.data.startswith("showstats|"))
def handle_show_stats(call):
    if "|" in call.data:
        user_id = check_panel_owner(call)
        if user_id is None:
            return
    else:
        user_id = call.from_user.id
    bot.answer_callback_query(call.id)
    if not get_user(user_id):
        bot.send_message(call.message.chat.id, "اول /start بزن.")
        return
    markup = types.InlineKeyboardMarkup()
    markup.row(colored_button("🔙 بازگشت به حساب کاربری", callback_data=f"showaccount|{user_id}"))
    safe_edit_message(
        stats_text_for_user(user_id, get_display_name(call.from_user)),
        call.message.chat.id,
        call.message.message_id,
        reply_markup=markup
    )

# ================== بخش لقب‌های من ==================
def tags_menu_markup(user_id, tags, active_name):
    markup = types.InlineKeyboardMarkup()
    for i, entry in enumerate(tags):
        name = entry.get("name", "")
        label = f"✅ {name}" if name == active_name else name
        markup.row(
            colored_button(label, callback_data=f"selecttag|{user_id}|{i}"),
            colored_button(_format_remaining(entry.get("expires") or 0), callback_data=f"tagtime|{user_id}|{i}")
        )
    markup.row(colored_button("🔙 بازگشت به حساب کاربری", callback_data=f"showaccount|{user_id}"))
    return markup

@bot.callback_query_handler(func=lambda call: call.data == "showtags" or call.data.startswith("showtags|"))
def handle_show_tags(call):
    if "|" in call.data:
        user_id = check_panel_owner(call)
        if user_id is None:
            return
    else:
        user_id = call.from_user.id
    bot.answer_callback_query(call.id)
    if not get_user(user_id):
        bot.send_message(call.message.chat.id, "اول /start بزن.")
        return
    tags, active_name = get_user_tags(user_id)
    if not tags:
        text = "🏷 لقب‌ها\n\nهنوز هیچ لقب ویژه‌ای نگرفتی!"
        markup = types.InlineKeyboardMarkup()
        markup.row(colored_button("🔙 بازگشت به حساب کاربری", callback_data=f"showaccount|{user_id}"))
    else:
        text = "🏷 لقب‌های شما\n\nروی یه لقب بزن تا به‌عنوان لقب نمایشی فعالت انتخاب بشه:"
        markup = tags_menu_markup(user_id, tags, active_name)
    safe_edit_message(text, call.message.chat.id, call.message.message_id, reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data.startswith("selecttag|"))
def handle_select_tag(call):
    _, owner_id_str, idx_str = call.data.split("|")
    owner_id = int(owner_id_str)
    if call.from_user.id != owner_id:
        bot.answer_callback_query(call.id, "این حساب متعلق به تو نیست.", show_alert=True)
        return
    ok, result = set_active_tag(owner_id, int(idx_str))
    if not ok:
        bot.answer_callback_query(call.id, f"❌ {result}", show_alert=True)
        return
    bot.answer_callback_query(call.id, f"✅ لقب فعال شد: {result}")
    tags, active_name = get_user_tags(owner_id)
    safe_edit_message(
        "🏷 لقب‌های شما\n\nروی یه لقب بزن تا به‌عنوان لقب نمایشی فعالت انتخاب بشه:",
        call.message.chat.id, call.message.message_id,
        reply_markup=tags_menu_markup(owner_id, tags, active_name)
    )

@bot.callback_query_handler(func=lambda call: call.data.startswith("tagtime|"))
def handle_tag_time(call):
    _, owner_id_str, idx_str = call.data.split("|")
    owner_id = int(owner_id_str)
    if call.from_user.id != owner_id:
        bot.answer_callback_query(call.id, "این حساب متعلق به تو نیست.", show_alert=True)
        return
    tags, _ = get_user_tags(owner_id)
    idx = int(idx_str)
    if idx < 0 or idx >= len(tags):
        bot.answer_callback_query(call.id, "لقب پیدا نشد.", show_alert=True)
        return
    entry = tags[idx]
    bot.answer_callback_query(call.id, f"{entry.get('name')}\n{_format_remaining(entry.get('expires') or 0)}", show_alert=True)

# ================== بخش زیرمجموعه ==================
# ================== بخش بانک ==================
# نکته امنیتی: تمام دکمه‌های زیر شناسه صاحب پنل را داخل callback_data حمل می‌کنند
# (owner|user_id) تا کاربر دیگری در گروه نتواند با زدن دکمه، پنل شخص دیگر را
# به پنل خودش تغییر بدهد. هندلرهای مربوطه این شناسه را با کاربری که کلیک کرده
# مقایسه می‌کنند (به همان الگویی که در acctransfer استفاده شده).
def bank_markup(user_id):
    markup = types.InlineKeyboardMarkup()
    markup.row(colored_button("💰 وام الماس", callback_data=f"loanmenu|{user_id}"))
    markup.row(
        colored_button("📤 برداشت", callback_data=f"bankwithdraw|{user_id}"),
        colored_button("📥 واریز", callback_data=f"bankdeposit|{user_id}")
    )
    return markup


def loan_markup(user_id):
    markup = types.InlineKeyboardMarkup()
    markup.add(colored_button("💎 بانک الماس 🏦", callback_data=f"bankmenu|{user_id}"))
    return markup


def bank_back_markup(user_id):
    markup = types.InlineKeyboardMarkup()
    markup.add(colored_button("💎 بانک الماس 🏦", callback_data=f"bankmenu|{user_id}"))
    return markup

def bank_open_markup(user_id):
    markup = types.InlineKeyboardMarkup()
    markup.add(colored_button(f"🏦 افتتاح حساب - {BANK_OPENING_FEE:,} 💎", callback_data=f"bankopen|{user_id}"))
    return markup

def bank_text(user_id):
    apply_bank_interest(user_id)
    user = get_user(user_id)
    bank_balance = get_bank_balance(user_id)
    account_number = user.get("bank_account_number")
    display_name = html.escape(str(user.get('username') or user_id))
    today_interest = min(int(bank_balance * BANK_INTEREST_RATE), BANK_DAILY_INTEREST_MAX)
    return (
        "◈ ━━━━━ 𝗕𝗮𝗻𝗸 ━━━━━━ ◈\n"
        "฿ | بانک الماس\n\n"
        f"❐ | شماره حساب : <code>{account_number}</code>\n"
        f"👤 به نام : {display_name}\n\n"
        f"$ | موجودی حساب : {bank_balance:,} الماس\n\n"
        " سود بانکی\n"
        f"┘─ ⌬ | درصد سود : {int(BANK_INTEREST_RATE * 100)}%\n"
        f"┘─ ⎌ | مبلغ واریزی : {today_interest:,} الماس\n"
        "┘─ ⎙ | زمان واریز : 00:00\n\n"
        "⍖ | برای مدیریت حساب بانکی از گزینه های زیر استفاده کنید\n"
        "◈ ━━━━━ 𝗕𝗮𝗻𝗸 ━━━━━━ ◈"
    )

@bot.callback_query_handler(func=lambda call: call.data == "bankmenu" or call.data.startswith("bankmenu|"))
def bank_menu(call):
    # سازگاری با دکمه‌ای که owner ندارد (مثلاً وقتی از منوی اصلی بدون owner ساخته شده)
    if "|" in call.data:
        user_id = check_panel_owner(call)
        if user_id is None:
            return
    else:
        user_id = call.from_user.id
    bot.answer_callback_query(call.id)

    # ورود به بانک یک navigation action است؛ اگر مرحله‌ی قبلی (برداشت/واریز/وام)
    # هنوز فعال باشد، باید آن را ببندیم.
    cancel_pending_step(call.message.chat.id, user_id)
    bot.clear_step_handler(call.message)

    user = get_user(user_id)
    if not user:
        bot.send_message(call.message.chat.id, "اول /start بزن.")
        return
    if not user.get("bank_account_number"):
        safe_edit_message(
            "🏦 بانک الماس\n\n"
            f"برای اولین بار باید حساب بانکی خودت رو با پرداخت {BANK_OPENING_FEE:,} 💎 افتتاح کنی.\n\n"
            f"💎 موجودی فعلی: {get_balance(user_id):,} 💎",
            call.message.chat.id, call.message.message_id, bank_open_markup(user_id)
        )
        return
    safe_edit_message(bank_text(user_id), call.message.chat.id, call.message.message_id, bank_markup(user_id), parse_mode="HTML")

@bot.callback_query_handler(func=lambda call: call.data.startswith("bankopen|"))
def bank_open(call):
    user_id = check_panel_owner(call)
    if user_id is None:
        return
    bot.answer_callback_query(call.id)
    ok, result = open_bank_account(user_id)
    if not ok:
        safe_edit_message(f"❌ {result}", call.message.chat.id, call.message.message_id, bank_open_markup(user_id))
        return
    safe_edit_message(
        "✅ حساب بانکی با موفقیت افتتاح شد!\n\n" + bank_text(user_id),
        call.message.chat.id, call.message.message_id, bank_markup(user_id), parse_mode="HTML"
    )

@bot.callback_query_handler(func=lambda call: call.data.startswith("bankdeposit|"))
def bank_deposit_prompt(call):
    user_id = check_panel_owner(call)
    if user_id is None:
        return
    bot.answer_callback_query(call.id)
    if not get_bank_account_number(user_id):
        safe_edit_message("❌ اول حساب بانکی خودت رو افتتاح کن.", call.message.chat.id, call.message.message_id, bank_open_markup(user_id))
        return
    safe_edit_message(
        "◈ ━━━━━ 𝗕𝗮𝗻𝗸 ━━━━━━ ◈\n"
        "⎌ | واریز به بانک الماس\n\n"
        f"$ | موجودی حساب : {get_bank_balance(user_id):,}\n\n"
        "⎋ | شما درحال واریز الماس به حساب بانکی خود میباشید.\n\n"
        "⌲ | لطفا مبلغ مورد نظر جهت واریز رو در جواب همین پنل ارسال کنید.\n"
        "◈ ━━━━━ 𝗕𝗮𝗻𝗸 ━━━━━━ ◈",
        call.message.chat.id, call.message.message_id, bank_back_markup(user_id)
    )
    register_timed_next_step_handler(call.message, bank_deposit_step, user_id, call.message.message_id, expected_user_id=user_id)

def _bank_confirmation_markup(user_id):
    markup = types.InlineKeyboardMarkup()
    markup.row(
        colored_button("بله ✅", callback_data=f"bankconfirm|yes|{user_id}"),
        colored_button("خیر ❌", callback_data=f"bankconfirm|no|{user_id}"),
    )
    return markup

def _store_bank_confirmation(user_id, action, amount, chat_id, message_id):
    with _bank_confirm_lock:
        _bank_confirmations[user_id] = {"action": action, "amount": int(amount), "chat_id": chat_id, "message_id": message_id}

def _clear_bank_confirmation(user_id):
    with _bank_confirm_lock:
        return _bank_confirmations.pop(user_id, None)

@bot.callback_query_handler(func=lambda call: call.data.startswith("bankconfirm|"))
def bank_confirmation_callback(call):
    parts = call.data.split("|")
    if len(parts) != 3:
        bot.answer_callback_query(call.id, "دکمه نامعتبر است.", show_alert=True)
        return
    try:
        user_id = int(parts[2])
    except ValueError:
        bot.answer_callback_query(call.id, "دکمه نامعتبر است.", show_alert=True)
        return
    if call.from_user.id != user_id:
        bot.answer_callback_query(call.id, "این تأیید برای شخص دیگری است.", show_alert=True)
        return
    with _bank_confirm_lock:
        pending = _bank_confirmations.get(user_id)
    if not pending:
        bot.answer_callback_query(call.id, "این درخواست دیگر فعال نیست.", show_alert=True)
        return
    action, amount = pending["action"], int(pending["amount"])
    if parts[1] == "no":
        _clear_bank_confirmation(user_id)
        bot.answer_callback_query(call.id, "لغو شد ❌")
        safe_edit_message("❌ عملیات لغو شد. هیچ مبلغی از موجودی شما کم یا اضافه نشد.", call.message.chat.id, call.message.message_id, reply_markup=None)
        auto_return_to_bank(call.message.chat.id, call.message.message_id, user_id, 3)
        return
    if parts[1] != "yes":
        bot.answer_callback_query(call.id, "دکمه نامعتبر است.", show_alert=True)
        return

    if action == "deposit":
        if ATOMIC_DB_MODE:
            ok = atomic_bank_transfer(user_id, amount, "deposit")
        else:
            if get_balance(user_id) < amount:
                ok = False
            else:
                apply_bank_interest(user_id)
                ok = bool(update_diamonds(user_id, -amount) is not None and change_bank_balance(user_id, amount))
        if not ok:
            _clear_bank_confirmation(user_id)
            bot.answer_callback_query(call.id, "ثبت واریز انجام نشد ❌", show_alert=True)
            safe_edit_message("❌ ثبت واریز انجام نشد؛ موجودی شما تغییر نکرد.", call.message.chat.id, call.message.message_id, reply_markup=None)
            auto_return_to_bank(call.message.chat.id, call.message.message_id, user_id, 3)
            return
        result_text = f"✅ {amount:,} 💎 به حساب بانکی واریز شد.\n💰 موجودی بانک: {get_bank_balance(user_id):,} 💎"
    else:
        if ATOMIC_DB_MODE:
            ok = atomic_bank_transfer(user_id, amount, "withdraw")
        else:
            # هر دو leg انتقال زیر یک lock هستند. اگر leg دوم شکست بخورد،
            # leg اول با عملیات جبرانی برگردانده می‌شود.
            with _get_user_financial_lock(user_id):
                apply_bank_interest(user_id)
                if get_bank_balance(user_id) < amount:
                    ok = False
                else:
                    bank_debited = change_bank_balance(user_id, -amount)
                    wallet_credited = False
                    if bank_debited:
                        wallet_credited = update_diamonds(user_id, amount) is not None
                    if bank_debited and not wallet_credited:
                        # rollback: پول بانک را برگردان.
                        rollback_ok = change_bank_balance(user_id, amount)
                        if not rollback_ok:
                            logging.critical(
                                f"ROLLBACK FAILED: bank withdraw user={user_id} amount={amount}"
                            )
                        ok = False
                    else:
                        ok = bool(bank_debited and wallet_credited)
        if not ok:
            _clear_bank_confirmation(user_id)
            bot.answer_callback_query(call.id, "ثبت برداشت انجام نشد ❌", show_alert=True)
            safe_edit_message("❌ ثبت برداشت انجام نشد؛ اگر خطای موقت دیتابیس رخ داده باشد عملیات برگشت داده شده است.", call.message.chat.id, call.message.message_id, reply_markup=None)
            auto_return_to_bank(call.message.chat.id, call.message.message_id, user_id, 3)
            return
        result_text = (f"✅ {amount:,} 💎 از بانک برداشت شد.\n"
                       f"💰 موجودی بانک: {get_bank_balance(user_id):,} 💎\n"
                       f"💎 موجودی کیف پول: {get_balance(user_id):,} 💎")
    _clear_bank_confirmation(user_id)
    bot.answer_callback_query(call.id, "عملیات با موفقیت انجام شد ✅")
    safe_edit_message(result_text, call.message.chat.id, call.message.message_id, reply_markup=None)
    auto_return_to_bank(call.message.chat.id, call.message.message_id, user_id, 5)

def bank_deposit_step(message, expected_user_id, panel_msg_id):
    if not require_reply_to_panel(message, panel_msg_id, "برای واریز، روی همین پنل بانک ریپلای کن و مبلغ را بفرست."):
        register_timed_next_step_handler(message, bank_deposit_step, expected_user_id, panel_msg_id, expected_user_id=expected_user_id)
        return
    if message.from_user.id != expected_user_id:
        register_timed_next_step_handler(message, bank_deposit_step, expected_user_id, panel_msg_id, expected_user_id=expected_user_id)
        return
    amount = parse_amount(message.text)
    if amount is None:
        safe_edit_message("❌ فرمت درست نیست. روی همین پنل ریپلای کن. مثال: 500000 یا 500k یا 500کا یا 12.5میل", message.chat.id, panel_msg_id, reply_markup=bank_back_markup(expected_user_id))
        register_timed_next_step_handler(message, bank_deposit_step, expected_user_id, panel_msg_id, expected_user_id=expected_user_id)
        return
    if amount <= 0:
        safe_edit_message("❌ مبلغ باید بیشتر از صفر باشد. روی همین پنل ریپلای کن و دوباره بفرست.", message.chat.id, panel_msg_id, reply_markup=bank_back_markup(expected_user_id))
        register_timed_next_step_handler(message, bank_deposit_step, expected_user_id, panel_msg_id, expected_user_id=expected_user_id)
        return
    if get_balance(expected_user_id) < amount:
        safe_edit_message("❌ موجودی الماس شما کافی نیست.", message.chat.id, panel_msg_id, reply_markup=bank_markup(expected_user_id))
        return
    safe_edit_message("آیا از واریز اطمینان دارید؟\n\n" f"مبلغ درحال واریز: {amount:,} 💎", message.chat.id, panel_msg_id, reply_markup=_bank_confirmation_markup(expected_user_id))
    _store_bank_confirmation(expected_user_id, "deposit", amount, message.chat.id, panel_msg_id)

@bot.callback_query_handler(func=lambda call: call.data.startswith("bankwithdraw|"))
def bank_withdraw_prompt(call):
    user_id = check_panel_owner(call)
    if user_id is None:
        return
    bot.answer_callback_query(call.id)
    if not get_bank_account_number(user_id):
        safe_edit_message("❌ اول حساب بانکی خودت رو افتتاح کن.", call.message.chat.id, call.message.message_id, bank_open_markup(user_id))
        return
    apply_bank_interest(user_id)
    safe_edit_message(
        "◈ ━━━━━ 𝗕𝗮𝗻𝗸 ━━━━━━ ◈\n"
        "⎋ | برداشت از بانک الماس\n\n"
        f"$ | موجودی قابل برداشت : {get_bank_balance(user_id):,} الماس\n\n"
        "⎌ | شما درحال برداشت الماس از حساب بانکی خود میباشید.\n\n"
        "⌲ | لطفا مبلغ مورد نظر جهت برداشت رو در جواب همین پنل ارسال کنید.\n"
        "◈ ━━━━━ 𝗕𝗮𝗻𝗸 ━━━━━━ ◈",
        call.message.chat.id, call.message.message_id, bank_back_markup(user_id)
    )
    register_timed_next_step_handler(call.message, bank_withdraw_step, user_id, call.message.message_id, expected_user_id=user_id)

def bank_withdraw_step(message, expected_user_id, panel_msg_id):
    if not require_reply_to_panel(message, panel_msg_id, "برای برداشت، روی همین پنل بانک ریپلای کن و مبلغ را بفرست."):
        register_timed_next_step_handler(message, bank_withdraw_step, expected_user_id, panel_msg_id, expected_user_id=expected_user_id)
        return
    if message.from_user.id != expected_user_id:
        register_timed_next_step_handler(message, bank_withdraw_step, expected_user_id, panel_msg_id, expected_user_id=expected_user_id)
        return
    amount = parse_amount(message.text)
    if amount is None:
        safe_edit_message("❌ فرمت درست نیست. روی همین پنل ریپلای کن. مثال: 500000 یا 500k یا 500کا یا 12.5میل", message.chat.id, panel_msg_id, reply_markup=bank_back_markup(expected_user_id))
        register_timed_next_step_handler(message, bank_withdraw_step, expected_user_id, panel_msg_id, expected_user_id=expected_user_id)
        return
    if amount <= 0:
        safe_edit_message("❌ مبلغ باید بیشتر از صفر باشد. روی همین پنل ریپلای کن و دوباره بفرست.", message.chat.id, panel_msg_id, reply_markup=bank_back_markup(expected_user_id))
        register_timed_next_step_handler(message, bank_withdraw_step, expected_user_id, panel_msg_id, expected_user_id=expected_user_id)
        return
    apply_bank_interest(expected_user_id)
    if get_bank_balance(expected_user_id) < amount:
        safe_edit_message("❌ موجودی بانک برای این برداشت کافی نیست.", message.chat.id, panel_msg_id, reply_markup=bank_markup(expected_user_id))
        return
    safe_edit_message("آیا از برداشت اطمینان دارید؟\n\n" f"مبلغ درحال برداشت: {amount:,} 💎", message.chat.id, panel_msg_id, reply_markup=_bank_confirmation_markup(expected_user_id))
    _store_bank_confirmation(expected_user_id, "withdraw", amount, message.chat.id, panel_msg_id)

# ================== بخش وام داخل بانک ==================
@bot.callback_query_handler(func=lambda call: call.data.startswith("loanmenu|"))
def loan_menu(call):
    user_id = check_panel_owner(call)
    if user_id is None:
        return
    bot.answer_callback_query(call.id)
    if not get_user(user_id):
        bot.send_message(call.message.chat.id, "اول /start بزن.")
        return

    current = get_loan_balance(user_id)
    remaining = LOAN_MAX - current

    if current > 0:
        safe_edit_message(
            "◈ ━━━━━ 𝗕𝗮𝗻𝗸 ━━━━━━ ◈\n"
            "☻ | وام الماس\n\n"
            f"♛ | وام فعلی شما: {current:,} الماس\n\n"
            f"⎋ | سقف وام : {LOAN_MAX:,} الماس\n\n"
            "⊗ | تا وقتی وام فعلی رو کامل پس ندی، وام جدیدی به شما داده نمیشه.\n"
            "◈ ━━━━━ 𝗕𝗮𝗻𝗸 ━━━━━━ ◈",
            call.message.chat.id, call.message.message_id,
            loan_markup(user_id)
        )
        return

    safe_edit_message(
        "◈ ━━━━━ 𝗕𝗮𝗻𝗸 ━━━━━━ ◈\n"
        "☻ | وام الماس\n\n"
        f"♛ | وام فعلی شما: {current:,} الماس\n\n"
        f"⎋ | سقف وام : {LOAN_MAX:,} الماس\n\n"
        "⊗ | دقت کنید که بعد از گرفتن وام تا پس دادن کامل وام؛ وام بعدی به شما داده نمیشود.\n\n"
        "⍖ | وام کم کم از الماس هایی که در بازی ها میبرید از شما کسر میشه.\n\n"
        "⌲ | مقداری که می‌خوای وام بگیری رو بفرست:\n"
        "◈ ━━━━━ 𝗕𝗮𝗻𝗸 ━━━━━━ ◈",
        call.message.chat.id, call.message.message_id,
        loan_markup(user_id)
    )
    register_timed_next_step_handler(call.message, loan_amount_step, user_id, remaining, call.message.message_id, expected_user_id=user_id)

def loan_amount_step(message, expected_user_id, remaining, panel_msg_id):
    if not require_reply_to_panel(message, panel_msg_id, "برای دریافت وام، روی همین پنل ریپلای کن و مبلغ را بفرست."):
        register_timed_next_step_handler(message, loan_amount_step, expected_user_id, remaining, panel_msg_id, expected_user_id=expected_user_id)
        return
    if message.from_user.id != expected_user_id:
        # پیام از یه نفر دیگه بود؛ نادیده می‌گیریم ولی منتظر پیام خودِ کاربر می‌مونیم
        register_timed_next_step_handler(message, loan_amount_step, expected_user_id, remaining, panel_msg_id, expected_user_id=expected_user_id)
        return
    amount = parse_amount(message.text)
    if amount is None:
        safe_edit_message("❌ مبلغ درست نیست. روی همین پنل وام ریپلای کن؛ مثال: 100000 یا 100k یا 100کا", message.chat.id, panel_msg_id, reply_markup=loan_markup(expected_user_id))
        register_timed_next_step_handler(message, loan_amount_step, expected_user_id, remaining, panel_msg_id, expected_user_id=expected_user_id)
        return

    if get_loan_balance(expected_user_id) > 0:
        safe_edit_message("⊗ | تا وقتی وام فعلی رو کامل پس ندی، وام جدیدی به شما داده نمیشه.", message.chat.id, panel_msg_id, reply_markup=loan_markup(expected_user_id))
        return
    if amount <= 0:
        safe_edit_message("❌ مبلغ باید بزرگتر از صفر باشه. روی همین پنل وام ریپلای کن و دوباره بفرست:", message.chat.id, panel_msg_id, reply_markup=loan_markup(expected_user_id))
        register_timed_next_step_handler(message, loan_amount_step, expected_user_id, remaining, panel_msg_id, expected_user_id=expected_user_id)
        return
    if amount > remaining:
        safe_edit_message(f"❌ حداکثر می‌تونی {remaining:,} 💎 وام بگیری. روی همین پنل ریپلای کن و یه عدد کمتر یا مساوی بفرست:", message.chat.id, panel_msg_id, reply_markup=loan_markup(expected_user_id))
        register_timed_next_step_handler(message, loan_amount_step, expected_user_id, remaining, panel_msg_id, expected_user_id=expected_user_id)
        return

    update_diamonds(expected_user_id, amount)
    change_loan_balance(expected_user_id, amount)
    if panel_msg_id:
        safe_edit_message(
            f"✓ | {amount:,} الماس وام گرفتی و به موجودیت اضافه شد.\n"
            f"♛ | مجموع وام فعلی: {get_loan_balance(expected_user_id):,} الماس\n"
            f"$ | موجودی جدید: {get_balance(expected_user_id):,} الماس\n"
            "⊗ | تا پس دادن کامل وام، وام جدیدی به شما داده نمیشه.",
            message.chat.id, panel_msg_id, reply_markup=None
        )
        auto_return_to_bank(message.chat.id, panel_msg_id, expected_user_id, 5)

# ================== دستورات متنی بانک ==================
@bot.message_handler(func=lambda m: text_is(m, "بانک", "بانک الماس"))
def text_bank(message):
    user_id = message.from_user.id
    if not get_user(user_id):
        bot.reply_to(message, "اول باید یه‌بار /start بزنی (توی پیوی بات).")
        return
    user = get_user(user_id)
    if not user.get("bank_account_number"):
        show_or_edit_panel(
            message, user_id, "bank",
            "🏦 بانک الماس\n\n"
            f"برای اولین بار باید حساب بانکی خودت رو با پرداخت {BANK_OPENING_FEE:,} 💎 افتتاح کنی.\n"
            f"💎 موجودی فعلی: {get_balance(user_id):,} 💎",
            bank_open_markup(user_id)
        )
        return
    show_or_edit_panel(message, user_id, "bank", bank_text(user_id), bank_markup(user_id), parse_mode="HTML")

# ================== بخش گردونه ==================
@bot.callback_query_handler(func=lambda call: call.data == "spinwheel" or call.data.startswith("spinwheel|"))
def spin_wheel(call):
    if "|" in call.data:
        user_id = check_panel_owner(call)
        if user_id is None:
            return
    else:
        user_id = call.from_user.id
    if not get_user(user_id):
        bot.answer_callback_query(call.id, "اول /start بزن.", show_alert=True)
        return

    with spin_lock:
        now = int(time.time())
        last_spin = get_last_spin(user_id)
        cooldown = SPIN_COOLDOWN_HOURS * 3600
        elapsed = now - last_spin

        if elapsed < cooldown:
            remaining = cooldown - elapsed
            hours = remaining // 3600
            minutes = (remaining % 3600) // 60
            bot.answer_callback_query(
                call.id,
                f"⏳ گردونه هر {SPIN_COOLDOWN_HOURS} ساعت یه‌بار قابل چرخوندنه.\n"
                f"تا نوبت بعدی: {hours} ساعت و {minutes} دقیقه مونده.",
                show_alert=True
            )
            return

        won = random.randint(SPIN_MIN, SPIN_MAX)
        update_diamonds(user_id, won)
        set_last_spin(user_id, now)
    register_daily_gift(user_id, call.message.chat.id, get_display_name(call.from_user))

    bot.answer_callback_query(call.id)
    markup = None
    safe_edit_message(
        f"🎡 گردونه چرخید!\n"
        f"💎 تبریک، {won} الماس بردی!\n"
        f"💰 موجودی جدید: {get_balance(user_id)} 💎\n\n"
        f"⏱ نوبت بعدی: {SPIN_COOLDOWN_HOURS} ساعت دیگه",
        chat_id=call.message.chat.id,
        message_id=call.message.message_id,
        reply_markup=markup
    )

# ================== بخش راهنما ==================
# ================== راهنمای شیشه‌ای ==================
def help_main_markup(user_id):
    markup = types.InlineKeyboardMarkup()
    markup.row(
        colored_button("💰 موجودی", callback_data=f"help_topic|{user_id}|balance"),
        colored_button("💰 موجودی دیگران", callback_data=f"help_topic|{user_id}|other_balance")
    )
    markup.row(
        colored_button("💸 انتقال الماس", callback_data=f"help_topic|{user_id}|transfer"),
        colored_button("🏦 بانک الماس", callback_data=f"help_topic|{user_id}|bank")
    )
    markup.row(
        colored_button("🎲 شرطبندی", callback_data=f"help_topic|{user_id}|bet"),
        colored_button("🎰 کازینو", callback_data=f"help_topic|{user_id}|casino")
    )
    markup.row(
        colored_button("⛏ حفاری", callback_data=f"help_topic|{user_id}|dig"),
        colored_button("💎 معدن الماس", callback_data=f"help_topic|{user_id}|mine")
    )
    markup.row(colored_button("💣 دینامیت", callback_data=f"help_topic|{user_id}|dynamite"))
    markup.row(colored_button("🏆 رتبه بندی", callback_data=f"help_topic|{user_id}|rank"))
    markup.row(
        colored_button("🏅 جام ها", callback_data=f"help_trophies|{user_id}"),
        colored_button("🏷 لقب ها", callback_data=f"help_tags|{user_id}")
    )
    markup.row(colored_button("🏠 منوی اصلی", callback_data=f"mainmenu|{user_id}"))
    return markup

HELP_TOPIC_TEXTS = {
    "balance": "💰 موجودی:\nکلمه «موجودی» را در چت ارسال کنید.",
    "other_balance": "💰 موجودی دیگران:\nکلمه «موجودی» را در چت به همراه ریپلای روی پیام شخص ارسال کنید.",
    "transfer": "💸 انتقال الماس:\nروی پیام شخص ریپلای کنید و بنویسید:\nانتقال الماس 100 کا یا عدد دلخواه\n(یا از دکمه «انتقال الماس» تو حساب کاربری استفاده کنید)",
    "bank": "🏦 بانک الماس:\nکلمه «بانک» را ارسال کنید.",
    "bet": "🎲 شرطبندی:\nبرای شرط بنویسید:\nشرطبندی 100 کا یا عدد دلخواه",
    "casino": "🎰 کازینو:\nکلمه «کازینو» را در چت ارسال کنید.",
    "dig": "⛏ حفاری:\nکلمه «حفاری» را ارسال کنید.",
    "mine": "💎 معدن الماس:\nکلمه «معدن الماس» را ارسال کنید.\nفقط حواستون باشه بمب رو نزنید❗",
    "dynamite": "💣 دینامیت:\nبنویسید: دینامیت 100 کا یا عدد دلخواه\nیه نفر باید بپیونده و شما به‌نوبت دکمه‌ها رو باز می‌کنید؛ هرکی روی بمب بزنه می‌بازه!",
    "rank": "🏆 رتبه‌بندی:\nکلمه «رنک» را ارسال کنید.",
}

def help_topic_markup(user_id):
    markup = types.InlineKeyboardMarkup()
    markup.row(colored_button("🔙 بازگشت به راهنما", callback_data=f"showhelp|{user_id}"))
    return markup

@bot.callback_query_handler(func=lambda call: call.data == "showhelp" or call.data.startswith("showhelp|"))
def handle_show_help(call):
    owner_id = check_panel_owner(call) if "|" in call.data else call.from_user.id
    if owner_id is None:
        return
    bot.answer_callback_query(call.id)
    safe_edit_message(
        "هر بخشی که نیاز به راهنمایی دارید رو انتخاب کنید‌.🌹",
        call.message.chat.id, call.message.message_id,
        reply_markup=help_main_markup(owner_id)
    )

@bot.callback_query_handler(func=lambda call: call.data.startswith("help_topic|"))
def handle_help_topic(call):
    parts = call.data.split("|", 2)
    if len(parts) != 3:
        return
    owner_id = int(parts[1])
    if call.from_user.id != owner_id:
        bot.answer_callback_query(call.id, "این پنل برای شخص دیگری است.", show_alert=True)
        return
    topic = parts[2]
    text = HELP_TOPIC_TEXTS.get(topic, "راهنمای این بخش پیدا نشد.")
    bot.answer_callback_query(call.id)
    safe_edit_message(text, call.message.chat.id, call.message.message_id, reply_markup=help_topic_markup(owner_id))

@bot.callback_query_handler(func=lambda call: call.data.startswith("help_trophies|"))
def handle_help_trophies(call):
    owner_id = int(call.data.split("|", 1)[1])
    if call.from_user.id != owner_id:
        bot.answer_callback_query(call.id, "این پنل برای شخص دیگری است.", show_alert=True)
        return
    bot.answer_callback_query(call.id)
    markup = types.InlineKeyboardMarkup()
    items = list(TROPHIES.items())
    for i in range(0, len(items), 2):
        row = []
        for key, (title, desc) in items[i:i+2]:
            row.append(colored_button(title, callback_data=f"help_trophy|{owner_id}|{key}"))
        markup.row(*row)
    markup.row(colored_button("🔙 بازگشت به راهنما", callback_data=f"showhelp|{owner_id}"))
    safe_edit_message("برای توضیحات جام مد نظر را انتخاب کنید", call.message.chat.id, call.message.message_id, reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data.startswith("help_trophy|"))
def handle_help_trophy(call):
    parts = call.data.split("|", 2)
    if len(parts) != 3:
        return
    owner_id, key = int(parts[1]), parts[2]
    if call.from_user.id != owner_id:
        bot.answer_callback_query(call.id, "این پنل برای شخص دیگری است.", show_alert=True)
        return
    info = TROPHIES.get(key)
    if not info:
        bot.answer_callback_query(call.id, "جام پیدا نشد.", show_alert=True)
        return
    bot.answer_callback_query(call.id)
    title, desc = info
    markup = types.InlineKeyboardMarkup()
    markup.row(colored_button("🔙 بازگشت به جام ها", callback_data=f"help_trophies|{owner_id}"))
    safe_edit_message(f"🏅 {title}\n\n{desc}", call.message.chat.id, call.message.message_id, reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data.startswith("help_tags|"))
def handle_help_tags(call):
    owner_id = int(call.data.split("|", 1)[1])
    if call.from_user.id != owner_id:
        bot.answer_callback_query(call.id, "این پنل برای شخص دیگری است.", show_alert=True)
        return
    bot.answer_callback_query(call.id)
    markup = types.InlineKeyboardMarkup()
    for i in range(0, len(TAGS), 2):
        row = [colored_button(tag, callback_data=f"help_tag_noop|{owner_id}") for tag in TAGS[i:i+2]]
        markup.row(*row)
    markup.row(colored_button("🔙 بازگشت به راهنما", callback_data=f"showhelp|{owner_id}"))
    safe_edit_message("تمام لقب ها نمایشی هستند 💎", call.message.chat.id, call.message.message_id, reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data.startswith("help_tag_noop|"))
def handle_help_tag_noop(call):
    owner_id = int(call.data.split("|", 1)[1])
    if call.from_user.id != owner_id:
        bot.answer_callback_query(call.id, "این پنل برای شخص دیگری است.", show_alert=True)
        return
    bot.answer_callback_query(call.id)


# ================== بخش انتقال الماس ==================
@bot.callback_query_handler(func=lambda call: call.data.startswith("acctransfer|"))
def handle_account_transfer_button(call):
    owner_id = int(call.data.split("|")[1])
    if call.from_user.id != owner_id:
        bot.answer_callback_query(call.id, "این حساب متعلق به تو نیست.", show_alert=True)
        return
    bot.answer_callback_query(call.id)
    
    text = (
        "🔹 روش ساده‌تر (توصیه می‌شه):\n"
        "توی گروه، روی پیام کاربر مقصد ریپلای کن و بنویس:\n"
        "انتقال الماس <مقدار>\n"
        "(مثال: انتقال الماس 200)\n\n"
        "🔹 یا از همینجا:\n"
        "آیدی عددی مقصد و مقدار الماس رو اینطوری بفرست:\n"
        "<آیدی عددی> <مقدار>\n"
        "مثال: 123456789 20\n\n"
        "⚠️ نکته: کاربر مقصد باید حتماً یه‌بار خودش توی پیوی بات /start زده باشه، "
        "وگرنه بات نمی‌تونه بشناستش و همیشه خطای «استارت نزده» می‌ده."
    )
    markup = None
    safe_edit_message(
        text,
        chat_id=call.message.chat.id,
        message_id=call.message.message_id,
        reply_markup=markup
    )
    register_timed_next_step_handler(call.message, ask_transfer_target, owner_id, expected_user_id=owner_id)

def ask_transfer_target(message, owner_id):
    if message.from_user.id != owner_id:
        register_timed_next_step_handler(message, ask_transfer_target, owner_id, expected_user_id=owner_id)
        return

    parts = message.text.split()
    amount = parse_amount(parts[1]) if len(parts) == 2 and parts[0].isdigit() else None
    if len(parts) != 2 or not parts[0].isdigit() or amount is None:
        msg = bot.reply_to(message, "فرمت اشتباهه. دوباره اینطوری بفرست:\n<آیدی عددی مقصد> <مقدار>\nمثال: 123456789 20 یا 123456789 20k")
        register_timed_next_step_handler(msg, ask_transfer_target, owner_id, expected_user_id=owner_id)
        return

    target_id = int(parts[0])
    if not get_user(target_id):
        bot.reply_to(
            message,
            "❌ کاربر مقصد هنوز /start نزده.\n\n"
            "⚠️ برای اینکه بات بتونه کاربری رو بشناسه، اون شخص باید حتماً یه‌بار "
            "توی پیوی خودِ بات دستور /start رو بزنه. فقط عضو گروه بودن کافی نیست."
        )
        return
    _show_transfer_confirmation(message, owner_id, target_id, amount)

# ================== دستورات ادمین (قدیمی) ==================
@bot.message_handler(func=lambda m: m.text and re.search(r"افزودن\s*الماس\s*(" + AMOUNT_TOKEN + r")", m.text, re.IGNORECASE))
def text_add_diamonds(message):
    if message.from_user.id not in ADMIN_IDS:
        bot.reply_to(message, "⛔ فقط ادمین می‌تونه الماس اضافه کنه.")
        return
    if not message.reply_to_message:
        bot.reply_to(message, "روی پیام کاربر مقصد ریپلای کن و بنویس:\nافزودن الماس <مقدار>\nمثال: افزودن الماس 50 یا افزودن الماس 50k")
        return

    match = re.search(r"افزودن\s*الماس\s*(" + AMOUNT_TOKEN + r")", message.text, re.IGNORECASE)
    if not match:
        bot.reply_to(message, "فرمت اشتباه است.")
        return
    amount = parse_amount(match.group(1))
    if amount is None:
        bot.reply_to(message, "❌ مبلغ نامعتبره.")
        return
    if amount <= 0:
        bot.reply_to(message, "مقدار باید بزرگتر از صفر باشه.")
        return

    target_id = message.reply_to_message.from_user.id
    if not get_user(target_id):
        bot.reply_to(message, "این کاربر هنوز /start نزده.")
        return

    update_diamonds(target_id, amount)
    target_name = get_display_name(message.reply_to_message.from_user)
    new_balance = get_balance(target_id)
    markup = types.InlineKeyboardMarkup()
    markup.add(colored_button(f"$ | موجودی جدید کاربر : {new_balance} الماس", callback_data="pending", style="primary"))
    bot.reply_to(message, f"✓ | {amount} الماس به کاربر {target_name} اضافه شد.", reply_markup=markup)

@bot.message_handler(func=lambda m: m.text and re.search(r"کم\s*کردن\s*الماس\s*(" + AMOUNT_TOKEN + r")", m.text, re.IGNORECASE))
def text_remove_diamonds(message):
    if message.from_user.id not in ADMIN_IDS:
        bot.reply_to(message, "⛔ فقط ادمین می‌تونه الماس کم کنه.")
        return
    if not message.reply_to_message:
        bot.reply_to(message, "روی پیام کاربر مقصد ریپلای کن و بنویس:\nکم کردن الماس <مقدار>\nمثال: کم کردن الماس 50 یا کم کردن الماس 50k")
        return

    match = re.search(r"کم\s*کردن\s*الماس\s*(" + AMOUNT_TOKEN + r")", message.text, re.IGNORECASE)
    if not match:
        bot.reply_to(message, "فرمت اشتباه است.")
        return
    amount = parse_amount(match.group(1))
    if amount is None:
        bot.reply_to(message, "❌ مبلغ نامعتبره.")
        return
    if amount <= 0:
        bot.reply_to(message, "مقدار باید بزرگتر از صفر باشه.")
        return

    target_id = message.reply_to_message.from_user.id
    if not get_user(target_id):
        bot.reply_to(message, "این کاربر هنوز /start نزده.")
        return

    deduct = min(amount, get_balance(target_id))
    update_diamonds(target_id, -deduct)
    bot.reply_to(message, f"✅ {deduct} 💎 از کاربر {target_id} کم شد.\nموجودی فعلی: {get_balance(target_id)} 💎")

def perform_transfer(sender_id, target_id, amount):
    if amount <= 0:
        return False, "مقدار باید بزرگتر از صفر باشه.", None, None, None
    if target_id == sender_id:
        return False, "نمیشه به خودت انتقال بدی.", None, None, None
    target_user = get_user(target_id)
    if not target_user:
        return False, "کاربر مقصد هنوز /start نزده.", None, None, None
    target_name = (target_user.get("username") or f"کاربر {target_id}").strip()
    try:
        if ATOMIC_DB_MODE:
            result = _run_db_with_retry(
                lambda: supabase.rpc("atomic_transfer_diamonds", {
                    "p_sender_id": int(sender_id),
                    "p_target_id": int(target_id),
                    "p_amount": int(amount),
                }).execute(),
                label=f"atomic_transfer_diamonds({sender_id}->{target_id})",
            ).data
            if not result:
                return False, "انتقال انجام نشد.", None, None, None
            row = result[0] if isinstance(result, list) else result
            sender_balance = int(row.get('sender_balance', 0))
            target_balance = get_balance(target_id)
            return True, f"✓ | مقدار {amount} الماس به {target_name} منتقل شد.", sender_balance, target_balance, target_name
        if get_balance(sender_id) < amount:
            return False, "موجودی کافی نداری.", None, None, None
        if update_diamonds(sender_id, -amount) is None:
            return False, "کسر از موجودی انجام نشد.", None, None, None
        if update_diamonds(target_id, amount) is None:
            update_diamonds(sender_id, amount)
            return False, "انتقال کامل نشد و مبلغ برگشت داده شد.", None, None, None
        sender_balance = get_balance(sender_id)
        target_balance = get_balance(target_id)
        return True, f"✓ | مقدار {amount} الماس به {target_name} منتقل شد.", sender_balance, target_balance, target_name
    except Exception as e:
        logging.error(f"خطا در perform_transfer: {e}")
        return False, "❌ انتقال انجام نشد.", None, None, None

@bot.message_handler(commands=["transfer"])
def cmd_transfer(message):
    sender_id = message.from_user.id
    if not get_user(sender_id):
        bot.reply_to(message, "اول /start بزن.")
        return
    if not message.reply_to_message:
        bot.reply_to(message, "روی پیام مقصد ریپلای کن: /transfer <مقدار>")
        return
    parts = message.text.split()
    amount = parse_amount(parts[1]) if len(parts) >= 2 else None
    if amount is None:
        bot.reply_to(message, "مثال: /transfer 20 یا /transfer 20k")
        return
    target_id = message.reply_to_message.from_user.id
    if not get_user(target_id):
        bot.reply_to(message, "❌ کاربر مقصد هنوز /start نزده.")
        return
    _show_transfer_confirmation(message, sender_id, target_id, amount)

@bot.message_handler(func=lambda m: m.text and re.search(r"انتقال\s+الماس\s+(" + AMOUNT_TOKEN + r")", m.text, re.IGNORECASE))
def text_transfer(message):
    sender_id = message.from_user.id
    if not get_user(sender_id):
        bot.reply_to(message, "اول باید یه‌بار /start بزنی (توی پیوی بات).")
        return
    if not message.reply_to_message:
        bot.reply_to(message, "روی پیام کاربر مقصد ریپلای کن و بنویس:\nانتقال الماس <مقدار>\nمثال: انتقال الماس 200")
        return

    match = re.search(r"انتقال\s+الماس\s+(" + AMOUNT_TOKEN + r")", message.text, re.IGNORECASE)
    if not match:
        bot.reply_to(message, "فرمت اشتباه است.")
        return
    amount = parse_amount(match.group(1))
    if amount is None:
        bot.reply_to(message, "❌ مبلغ نامعتبره.")
        return
    target_id = message.reply_to_message.from_user.id
    if not get_user(target_id):
        bot.reply_to(message, "❌ کاربر مقصد هنوز /start نزده.")
        return
    _show_transfer_confirmation(message, sender_id, target_id, amount)

# ================== شرط متنی ==================
def check_bet_timeout(bet_id):
    with _get_bet_lock(bet_id):
        bet = get_bet(bet_id)
        if not bet:
            return
        creator_id = bet.get('creator_id')
        creator_name = bet.get('creator_name')
        amount = bet.get('amount')
        chat_id = bet.get('chat_id')
        message_id = bet.get('message_id')
        status = bet.get('status')
        if status != "pending":
            return

        if ATOMIC_DB_MODE:
            try:
                supabase.rpc("atomic_refund_bet", {"p_bet_id": int(bet_id), "p_status": "timeout"}).execute()
            except Exception as e:
                logging.error(f"خطا در refund اتمیک شرط {bet_id}: {e}")
                return
        else:
            update_diamonds(creator_id, amount)
            set_bet_status(bet_id, "timeout")
    safe_edit_message(
        f"⎋ | زمان تموم شد!\n"
        f"⎌ | {amount} الماس به سازنده برگردونده شد.",
        chat_id=chat_id, message_id=message_id, reply_markup=None,
    )

def start_bet_flow(message, amount):
    user_id = message.from_user.id
    if not get_user(user_id):
        bot.reply_to(message, "اول /start بزن.")
        return

    if amount <= 0:
        bot.reply_to(message, "مقدار باید بزرگتر از صفر باشه.")
        return
    if get_balance(user_id) < amount:
        bot.reply_to(message, "موجودی الماس کافی نداری.")
        return

    creator_name = get_display_name(message.from_user)
    update_diamonds(user_id, -amount)

    sent = safe_send_message(
        message.chat.id,
        f"◈ ━━━━━ 𝗕𝗲𝘁 ━━━━━━ ◈\n"
        f"☻ | بازی : شرطبندی\n\n"
        f"$ | مقدار الماس : {amount:,}\n"
        f"♛ | سازنده : {creator_name}\n"
        f"◈ ━━━━━ 𝗕𝗲𝘁 ━━━━━━ ◈",
        reply_to_message_id=message.message_id,
    )
    if not sent:
        # پیام ساخته نشد؛ مبلغ رزرو شده باید فوراً برگردد.
        update_diamonds(user_id, amount)
        bot.reply_to(message, "❌ ارسال پنل شرط انجام نشد؛ مبلغ شرط به موجودی شما برگشت داده شد.")
        return

    bet_id = create_bet(user_id, creator_name, amount, message.chat.id, sent.message_id)
    if bet_id is None:
        # رکورد شرط ساخته نشد؛ نگذاریم مبلغ کاربر گم شود.
        update_diamonds(user_id, amount)
        safe_edit_message(
            "⊗ | نمایش دکمه‌های شرط با مشکل مواجه شد.\n⎌ | مقداری که شرط بسته بودید به حساب شما برگشت.",
            chat_id=message.chat.id, message_id=sent.message_id, reply_markup=None
        )
        return

    markup = types.InlineKeyboardMarkup()
    markup.row(
        colored_button("لغو ⊗", callback_data=f"cancel|{bet_id}"),
        colored_button("پیوستن ✓", callback_data=f"join|{bet_id}"),
    )
    edited_ok = safe_edit_message(sent.text, chat_id=message.chat.id, message_id=sent.message_id, reply_markup=markup)
    if not edited_ok:
        # دکمه‌ها اضافه نشدن؛ نگذاریم شرط بدون امکان لغو/پیوستن باقی بمونه و پول بلوکه بشه.
        with _get_bet_lock(bet_id):
            fresh = get_bet(bet_id)
            if fresh and fresh.get("status") == "pending":
                update_diamonds(user_id, amount)
                set_bet_status(bet_id, "cancelled")
        safe_edit_message(
            "⊗ | نمایش دکمه‌های شرط با مشکل مواجه شد.\n⎌ | مقداری که شرط بسته بودید به حساب شما برگشت.",
            chat_id=message.chat.id, message_id=sent.message_id, reply_markup=None,
        )
        return

    _start_daemon_timer(JOIN_TIMEOUT_SECONDS, check_bet_timeout, bet_id)

@bot.message_handler(commands=["bet", "شرط"])
def cmd_bet(message):
    parts = message.text.split()
    amount = parse_amount(parts[1]) if len(parts) == 2 else None
    if amount is None:
        bot.reply_to(message, "استفاده درست: /bet <مقدار>\nمثال: /bet 20 یا /bet 20k")
        return
    start_bet_flow(message, amount)

@bot.message_handler(func=lambda m: m.text and re.search(r"(?:شرط\s*بندی?|بازی)\s+(" + AMOUNT_TOKEN + r")", m.text, re.IGNORECASE))
def text_bet(message):
    match = re.search(r"(?:شرط\s*بندی?|بازی)\s+(" + AMOUNT_TOKEN + r")", message.text, re.IGNORECASE)
    if not match:
        bot.reply_to(message, "فرمت اشتباه است. مثال: شرط بندی 20 یا شرط بندی 20k")
        return
    amount = parse_amount(match.group(1))
    if amount is None:
        bot.reply_to(message, "❌ مبلغ نامعتبره.")
        return
    start_bet_flow(message, amount)

def resolve_bet(bet_id, opponent_id, opponent_name, is_bot=False):
    bet = get_bet(bet_id)
    creator_id = bet.get('creator_id')
    creator_name = bet.get('creator_name')
    amount = bet.get('amount')
    chat_id = bet.get('chat_id')
    message_id = bet.get('message_id')
    status = bet.get('status')

    winner_is_creator = random.random() < 0.5
    pool = amount if is_bot else 2 * amount

    if winner_is_creator:
        winner_name, winner_id = creator_name, creator_id
        loser_name, loser_id = opponent_name, opponent_id
    else:
        winner_name, winner_id = opponent_name, opponent_id
        loser_name, loser_id = creator_name, creator_id

    real_winner_id = None if (winner_id is None) else winner_id
    if real_winner_id is not None:
        payout, tax, loan_repay, tax_rate_used, loan_rate_used = calculate_payout(real_winner_id, pool, context="bet")
        if ATOMIC_DB_MODE:
            try:
                result = supabase.rpc("atomic_settle_pool", {
                    "p_winner_id": int(real_winner_id),
                    "p_pool": int(pool),
                    "p_tax": int(tax),
                    "p_loan_repay": int(loan_repay),
                    "p_tax_receiver_id": int(TAX_RECEIVER_ID) if get_user(TAX_RECEIVER_ID) else None,
                }).execute().data
                if not result:
                    raise RuntimeError("empty settlement result")
                row = result[0] if isinstance(result, list) else result
                payout = int(row.get("payout", payout) or 0)
                tax = int(row.get("tax", tax) or 0)
                loan_repay = int(row.get("loan_repay", loan_repay) or 0)
            except Exception as e:
                logging.error(f"خطا در settlement اتمیک شرط {bet_id}: {e}")
                return
        else:
            update_diamonds(real_winner_id, payout)
            if get_user(TAX_RECEIVER_ID):
                update_diamonds(TAX_RECEIVER_ID, tax)
        if get_user(real_winner_id):
            register_bet_win(real_winner_id, chat_id, winner_name)
    else:
        payout = 0
        tax = int(pool * TAX_RATE)
        loan_repay = 0
        tax_rate_used = TAX_RATE
        loan_rate_used = LOAN_TAX_RATE

    set_bet_status(bet_id, "finished")

    winner_display = winner_name or "کاربر"
    loser_display = loser_name or "کاربر"
    text = (
        f"◈ ━━━━━ 𝗕𝗲𝘁 ━━━━━━ ◈\n"
        f"⎙ نتیجه باز‌ی ⎙\n\n"
        f"♧ برنده: {winner_display}\n"
        f"⌫ بازنده: {loser_display}\n"
        f"◈ ━━━━━ 𝗕𝗲𝘁 ━━━━━━ ◈"
    )
    result_amount = payout if real_winner_id is not None else 0
    markup = types.InlineKeyboardMarkup()
    markup.row(
        colored_button(
            f"$ مبلغ برد : {result_amount:,}",
            callback_data="bet_result_noop",
        ),
        colored_button(
            f"⍗ مالیات : {tax:,}",
            callback_data="bet_result_noop",
        ),
    )
    safe_edit_message(text, chat_id=chat_id, message_id=message_id, reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data == "bet_result_noop")
def bet_result_noop_callback(call):
    # دکمه‌های مبلغ برد و مالیات صرفاً نمایشی هستند و هیچ عملیاتی انجام نمی‌دهند.
    bot.answer_callback_query(call.id)

@bot.callback_query_handler(
    func=lambda call: call.data == "pending" or call.data.split("|")[0] in ("cancel", "join")
)
def handle_callback(call):
    if call.data == "pending":
        bot.answer_callback_query(call.id, "لطفاً چند لحظه صبر کن...")
        return

    action, bet_id_str = call.data.split("|")
    bet_id = int(bet_id_str)
    clicker_id = call.from_user.id
    clicker_name = get_display_name(call.from_user)

    # همه‌ی مراحل «چک کردن وضعیت» و «تغییر وضعیت» زیر یک قفل مخصوص همین شرط انجام
    # می‌شن؛ همون الگویی که در بازی دینامیت باعث شد کلیک‌های هم‌زمان (پیوستن/لغو/تایم‌اوت)
    # با هم تداخل نکنن و پیام هم درست ادیت بشه.
    outcome = None
    with _get_bet_lock(bet_id):
        bet = get_bet(bet_id)

        if not bet:
            bot.answer_callback_query(call.id, "این شرط پیدا نشد.", show_alert=True)
            return

        creator_id = bet.get('creator_id')
        creator_name = bet.get('creator_name')
        amount = bet.get('amount')
        chat_id = bet.get('chat_id')
        message_id = bet.get('message_id')
        status = bet.get('status')

        # ========== بهبود پیام‌های خطا برای وضعیت‌های مختلف ==========
        if status != "pending":
            if status == "timeout":
                msg = "⏱ زمان انتظار به پایان رسید و شرط لغو شد."
            elif status == "cancelled":
                msg = "❌ این شرط توسط سازنده لغو شده است."
            elif status == "finished":
                msg = "🏁 این شرط قبلاً به پایان رسیده است."
            else:
                msg = "این شرط دیگر فعال نیست."
            bot.answer_callback_query(call.id, msg, show_alert=True)
            return

        if action == "cancel":
            if clicker_id != creator_id:
                bot.answer_callback_query(call.id, "فقط سازنده شرط می‌تونه لغو کنه.", show_alert=True)
                return
            if ATOMIC_DB_MODE:
                try:
                    supabase.rpc("atomic_refund_bet", {"p_bet_id": int(bet_id), "p_status": "cancelled"}).execute()
                except Exception as e:
                    logging.error(f"خطا در لغو اتمیک شرط {bet_id}: {e}")
                    bot.answer_callback_query(call.id, "لغو شرط انجام نشد.", show_alert=True)
                    return
            else:
                update_diamonds(creator_id, amount)
                set_bet_status(bet_id, "cancelled")
            outcome = ("cancel", amount, chat_id, message_id)

        elif action == "join":
            if clicker_id == creator_id:
                bot.answer_callback_query(call.id, "سازنده حق شرکت در شرط خودش رو نداره!", show_alert=True)
                return
            if not get_user(clicker_id):
                bot.answer_callback_query(call.id, "شما باید ابتدا در بات /start را بزنید.", show_alert=True)
                return
            try:
                if ATOMIC_DB_MODE:
                    rpc_result = supabase.rpc("atomic_claim_bet", {
                        "p_bet_id": int(bet_id),
                        "p_mode": "join",
                        "p_opponent_id": int(clicker_id),
                    }).execute().data
                    row = rpc_result[0] if isinstance(rpc_result, list) and rpc_result else rpc_result
                    if not row or not row.get("ok"):
                        bot.answer_callback_query(call.id, "این شرط دیگر قابل پیوستن نیست.", show_alert=True)
                        return
                else:
                    if get_balance(clicker_id) < amount:
                        bot.answer_callback_query(call.id, "موجودی کافی برای پیوستن به این شرط ندارید.", show_alert=True)
                        return
                    if update_diamonds(clicker_id, -amount) is None:
                        bot.answer_callback_query(call.id, "رزرو مبلغ انجام نشد.", show_alert=True)
                        return
                    # بلافاصله وضعیت رو از pending خارج می‌کنیم تا یک کلیک هم‌زمان دیگه
                    # (لغو یا پیوستن دوباره) نتونه همین شرط رو دوباره پردازش کنه.
                    set_bet_status(bet_id, "finished")
            except Exception as e:
                logging.error(f"خطا در claim اتمیک شرط {bet_id}: {e}")
                bot.answer_callback_query(call.id, "پیوستن به شرط انجام نشد.", show_alert=True)
                return
            outcome = ("join", clicker_id, clicker_name)

    # از اینجا به بعد قفل آزاد شده؛ عملیات کند (ادیت پیام/محاسبه‌ی نتیجه) دیگه بقیه‌ی
    # کلیک‌ها روی همین شرط رو بلاک نمی‌کنه.
    if outcome is None:
        return
    if outcome[0] == "cancel":
        _, amount, chat_id, message_id = outcome
        safe_edit_message(
            f"⊗ | بازی لغو شد.\n"
            f"⎌ | {amount} الماس برگردونده شد.",
            chat_id=chat_id, message_id=message_id, reply_markup=None,
        )
        bot.answer_callback_query(call.id, "شرط لغو شد.")
    elif outcome[0] == "join":
        _, join_clicker_id, join_clicker_name = outcome
        resolve_bet(bet_id, join_clicker_id, join_clicker_name, is_bot=False)
        bot.answer_callback_query(call.id, "شما به شرط پیوستید. نتیجه اعلام شد.")

# ================== بازی دینامیت (۲ نفره، ۳ در ۳) ==================
DYNAMITE_GRID_SIZE = 9  # 3x3
TURN_TIMEOUT_SECONDS = 60  # هر نوبت ۶۰ ثانیه وقت داره
dynamite_lock = threading.RLock()
active_dynamites = {}  # message_id -> game dict
_dynamite_turn_seq = itertools.count(1)

# ---------- پایداری روی دیتابیس (برای اینکه با ری‌استارت شدن ربات از بین نره) ----------
def _dynamite_db_upsert(message_id, game):
    try:
        supabase.table("dynamite_games").upsert({
            "message_id": int(message_id),
            "chat_id": int(game["chat_id"]),
            "creator_id": int(game["creator_id"]),
            "creator_name": game["creator_name"],
            "opponent_id": int(game["opponent_id"]) if game["opponent_id"] else None,
            "opponent_name": game["opponent_name"],
            "amount": int(game["amount"]),
            "status": game["status"],
            "bomb_index": game["bomb_index"],
            "revealed": sorted(game["revealed"]),
            "turn_id": int(game["turn_id"]) if game["turn_id"] else None,
            "safe_remaining": game["safe_remaining"],
        }, on_conflict="message_id").execute()
    except Exception as e:
        logging.error(f"خطا در ذخیره دیتابیس دینامیت {message_id}: {e}")

def _dynamite_db_delete(message_id):
    try:
        supabase.table("dynamite_games").delete().eq("message_id", int(message_id)).execute()
    except Exception as e:
        logging.error(f"خطا در حذف دیتابیس دینامیت {message_id}: {e}")

def rehydrate_dynamite_games():
    """بعد از هر بار بالا اومدن ربات، بازی‌های نیمه‌کاره دینامیت رو از دیتابیس برمی‌گردونه."""
    try:
        rows = supabase.table("dynamite_games").select("*").in_("status", ["pending", "active"]).execute().data or []
    except Exception as e:
        logging.error(f"خطا در بازیابی بازی‌های دینامیت: {e}")
        return
    with dynamite_lock:
        for row in rows:
            message_id = row["message_id"]
            game = {
                "chat_id": row["chat_id"],
                "creator_id": row["creator_id"],
                "creator_name": row["creator_name"],
                "opponent_id": row.get("opponent_id"),
                "opponent_name": row.get("opponent_name"),
                "amount": row["amount"],
                "status": row["status"],
                "bomb_index": row.get("bomb_index"),
                "revealed": set(row.get("revealed") or []),
                "turn_id": row.get("turn_id"),
                "safe_remaining": row.get("safe_remaining"),
                "turn_token": None,
            }
            active_dynamites[message_id] = game
            if game["status"] == "pending":
                # به‌صورت ساده یک تایمر کامل جدید برای پیوستن در نظر می‌گیریم.
                _start_daemon_timer(JOIN_TIMEOUT_SECONDS, dynamite_timeout, message_id)
            elif game["status"] == "active":
                start_turn_timer(message_id, game)

def dynamite_pending_text(amount, creator_name):
    return (
        "◈ ━━━━ 𝗗𝘆𝗻𝗮𝗺𝗶𝘁𝗲 ━━━━━ ◈\n"
        "☻ | بازی : دینامیت 💣\n\n"
        f"$ | مقدار الماس : {amount:,}\n"
        f"♛ | سازنده: {creator_name}\n"
        "◈ ━━━━ 𝗗𝘆𝗻𝗮𝗺𝗶𝘁𝗲 ━━━━━ ◈"
    )

def dynamite_pending_markup():
    markup = types.InlineKeyboardMarkup()
    markup.row(
        colored_button("پیوستن ✓", callback_data="dynjoin"),
        colored_button("لغو ⊗", callback_data="dyncancel"),
    )
    return markup

def dynamite_active_text(game):
    turn_name = game["creator_name"] if game["turn_id"] == game["creator_id"] else game["opponent_name"]
    return (
        "◈ ━━━━ 𝗗𝘆𝗻𝗮𝗺𝗶𝘁𝗲 ━━━━━ ◈\n"
        "☻ | بازی : دینامیت 💣\n\n"
        f"$ | مقدار الماس : {game['amount']:,}\n"
        f"♛ | سازنده : {game['creator_name']}\n"
        f"♔ | شرکت کننده : {game['opponent_name']}\n\n"
        f"⎋ | نوبت: {turn_name}\n"
        f"⎔ | جاهای امن باقی‌مانده: {game['safe_remaining']}\n"
        "♧ | روی دکمه های زیر کلیک کنید.\n"
        "◈ ━━━━ 𝗗𝘆𝗻𝗮𝗺𝗶𝘁𝗲 ━━━━━ ◈"
    )

def dynamite_board_markup(game):
    markup = types.InlineKeyboardMarkup()
    for row in range(3):
        buttons = []
        for col in range(3):
            idx = row * 3 + col
            label = "💎" if idx in game["revealed"] else " "
            buttons.append(colored_button(label, callback_data=f"dyncell|{idx}"))
        markup.row(*buttons)
    return markup

def dynamite_result_markup(payout, tax):
    markup = types.InlineKeyboardMarkup()
    markup.row(
        colored_button(f"$ مبلغ برد : {payout:,}", callback_data="dynamite_result_noop"),
        colored_button(f"⊗ مالیات : {tax:,}", callback_data="dynamite_result_noop"),
    )
    return markup

@bot.callback_query_handler(func=lambda call: call.data == "dynamite_result_noop")
def dynamite_result_noop_callback(call):
    # دکمه‌های مبلغ برد و مالیات صرفاً نمایشی هستند و هیچ عملیاتی انجام نمی‌دهند.
    bot.answer_callback_query(call.id)

def _dynamite_lazy_load(message_id):
    """اگه بازی تو حافظه‌ی همین پردازش نبود (مثلاً به‌خاطر ری‌استارت یا چند-worker بودن هاست)،
    یه بار از دیتابیس می‌خونیمش تا بازی الکی «تموم‌شده» اعلام نشه."""
    try:
        rows = supabase.table("dynamite_games").select("*").eq("message_id", int(message_id)).execute().data
    except Exception as e:
        logging.error(f"خطا در لود دیتابیس دینامیت {message_id}: {e}")
        return None
    if not rows:
        return None
    row = rows[0]
    if row["status"] not in ("pending", "active"):
        return None
    game = {
        "chat_id": row["chat_id"],
        "creator_id": row["creator_id"],
        "creator_name": row["creator_name"],
        "opponent_id": row.get("opponent_id"),
        "opponent_name": row.get("opponent_name"),
        "amount": row["amount"],
        "status": row["status"],
        "bomb_index": row.get("bomb_index"),
        "revealed": set(row.get("revealed") or []),
        "turn_id": row.get("turn_id"),
        "safe_remaining": row.get("safe_remaining"),
        "turn_token": None,
        "turn_timer": None,
    }
    active_dynamites[message_id] = game
    if game["status"] == "pending":
        _start_daemon_timer(JOIN_TIMEOUT_SECONDS, dynamite_timeout, message_id)
    elif game["status"] == "active":
        start_turn_timer(message_id, game)
    return game

def dynamite_timeout(message_id):
    with dynamite_lock:
        game = active_dynamites.get(message_id)
        if not game or game["status"] != "pending":
            return
        update_diamonds(game["creator_id"], game["amount"])
        del active_dynamites[message_id]
        chat_id = game["chat_id"]
        amount = game["amount"]
    _dynamite_db_delete(message_id)
    safe_edit_message(
        f"⎋ | زمان تموم شد!\n"
        f"⎌ | {amount:,} الماس به سازنده برگردونده شد.",
        chat_id=chat_id, message_id=message_id, reply_markup=None,
    )

def start_turn_timer(message_id, game):
    """برای نوبت فعلیِ game یک توکن جدید و یک تایمر ۶۰ ثانیه‌ای می‌سازد."""
    old_timer = game.get("turn_timer")
    if old_timer is not None:
        try:
            old_timer.cancel()
        except Exception:
            pass
    token = next(_dynamite_turn_seq)
    game["turn_token"] = token
    timer = threading.Timer(TURN_TIMEOUT_SECONDS, dynamite_turn_timeout, args=[message_id, token])
    game["turn_timer"] = timer
    timer.start()

def dynamite_turn_timeout(message_id, token):
    with dynamite_lock:
        game = active_dynamites.get(message_id)
        if not game or game["status"] != "active" or game.get("turn_token") != token:
            return  # نوبت قبلاً عوض شده یا بازی تموم شده
        loser_id = game["turn_id"]
        if loser_id == game["creator_id"]:
            loser_name, winner_id, winner_name = game["creator_name"], game["opponent_id"], game["opponent_name"]
        else:
            loser_name, winner_id, winner_name = game["opponent_name"], game["creator_id"], game["creator_name"]
        reason = "⎋ | زمان تموم شد!\n⎌ | بازنده به دلیل انتخاب نکردن در تایم تعیین شده باخت."
        _dynamite_finish(message_id, game, winner_id, winner_name, loser_id, loser_name, reason)

def start_dynamite_flow(message, amount):
    user_id = message.from_user.id
    if not get_user(user_id):
        bot.reply_to(message, "اول /start بزن.")
        return
    if amount <= 0:
        bot.reply_to(message, "مقدار باید بزرگتر از صفر باشه.")
        return
    if get_balance(user_id) < amount:
        bot.reply_to(message, "موجودی الماس کافی نداری.")
        return

    creator_name = get_display_name(message.from_user)
    update_diamonds(user_id, -amount)

    sent = safe_send_message(
        message.chat.id,
        dynamite_pending_text(amount, creator_name),
        reply_to_message_id=message.message_id,
    )
    if not sent:
        update_diamonds(user_id, amount)
        bot.reply_to(message, "❌ ارسال پنل دینامیت انجام نشد؛ مبلغ شرط به موجودی شما برگشت داده شد.")
        return

    with dynamite_lock:
        game = {
            "chat_id": message.chat.id,
            "creator_id": user_id,
            "creator_name": creator_name,
            "opponent_id": None,
            "opponent_name": None,
            "amount": amount,
            "status": "pending",
            "bomb_index": None,
            "revealed": set(),
            "turn_id": None,
            "safe_remaining": DYNAMITE_GRID_SIZE - 1,
            "turn_token": None,
            "turn_timer": None,
        }
        active_dynamites[sent.message_id] = game

    _dynamite_db_upsert(sent.message_id, game)
    safe_edit_message(
        dynamite_pending_text(amount, creator_name),
        chat_id=message.chat.id, message_id=sent.message_id, reply_markup=dynamite_pending_markup(),
    )
    _start_daemon_timer(JOIN_TIMEOUT_SECONDS, dynamite_timeout, sent.message_id)

@bot.message_handler(commands=["dynamite"])
def cmd_dynamite(message):
    parts = message.text.split()
    amount = parse_amount(parts[1]) if len(parts) == 2 else None
    if amount is None:
        bot.reply_to(message, "استفاده درست: /dynamite <مقدار>\nمثال: /dynamite 20 یا /dynamite 20k")
        return
    start_dynamite_flow(message, amount)

@bot.message_handler(func=lambda m: m.text and re.search(r"دینامیت\s+(" + AMOUNT_TOKEN + r")", m.text, re.IGNORECASE))
def text_dynamite(message):
    match = re.search(r"دینامیت\s+(" + AMOUNT_TOKEN + r")", message.text, re.IGNORECASE)
    if not match:
        bot.reply_to(message, "فرمت اشتباه است. مثال: دینامیت 20 یا دینامیت 20k")
        return
    amount = parse_amount(match.group(1))
    if amount is None:
        bot.reply_to(message, "❌ مبلغ نامعتبره.")
        return
    start_dynamite_flow(message, amount)

@bot.callback_query_handler(func=lambda call: call.data == "dyncancel")
def dynamite_cancel_callback(call):
    with dynamite_lock:
        message_id = call.message.message_id
        game = active_dynamites.get(message_id) or _dynamite_lazy_load(message_id)
        if not game:
            bot.answer_callback_query(call.id, "این بازی دیگر فعال نیست.", show_alert=True)
            return
        if game["status"] != "pending":
            bot.answer_callback_query(call.id, "این بازی دیگر قابل لغو نیست.", show_alert=True)
            return
        if call.from_user.id != game["creator_id"]:
            bot.answer_callback_query(call.id, "فقط سازنده بازی می‌تونه لغو کنه.", show_alert=True)
            return
        update_diamonds(game["creator_id"], game["amount"])
        amount = game["amount"]
        chat_id = game["chat_id"]
        del active_dynamites[message_id]
    _dynamite_db_delete(message_id)
    safe_edit_message(
        f"⊗ | بازی لغو شد.\n"
        f"⎌ | {amount:,} الماس برگردونده شد.",
        chat_id=chat_id, message_id=message_id, reply_markup=None,
    )
    bot.answer_callback_query(call.id, "بازی لغو شد.")

@bot.callback_query_handler(func=lambda call: call.data == "dynjoin")
def dynamite_join_callback(call):
    with dynamite_lock:
        message_id = call.message.message_id
        game = active_dynamites.get(message_id) or _dynamite_lazy_load(message_id)
        if not game:
            bot.answer_callback_query(call.id, "این بازی پیدا نشد.", show_alert=True)
            return
        if game["status"] != "pending":
            bot.answer_callback_query(call.id, "این بازی دیگر قابل پیوستن نیست.", show_alert=True)
            return
        clicker_id = call.from_user.id
        if clicker_id == game["creator_id"]:
            bot.answer_callback_query(call.id, "سازنده حق شرکت در بازی خودش رو نداره!", show_alert=True)
            return
        if not get_user(clicker_id):
            bot.answer_callback_query(call.id, "شما باید ابتدا در بات /start را بزنید.", show_alert=True)
            return
        if get_balance(clicker_id) < game["amount"]:
            bot.answer_callback_query(call.id, "موجودی کافی برای پیوستن به این بازی ندارید.", show_alert=True)
            return
        if update_diamonds(clicker_id, -game["amount"]) is None:
            bot.answer_callback_query(call.id, "رزرو مبلغ انجام نشد.", show_alert=True)
            return

        clicker_name = get_display_name(call.from_user)
        game["opponent_id"] = clicker_id
        game["opponent_name"] = clicker_name
        game["status"] = "active"
        game["bomb_index"] = random.randint(0, DYNAMITE_GRID_SIZE - 1)
        game["revealed"] = set()
        game["safe_remaining"] = DYNAMITE_GRID_SIZE - 1
        game["turn_id"] = game["creator_id"]
        chat_id = game["chat_id"]
        start_turn_timer(message_id, game)
        text = dynamite_active_text(game)
        markup = dynamite_board_markup(game)

    _dynamite_db_upsert(message_id, game)
    safe_edit_message(text, chat_id=chat_id, message_id=message_id, reply_markup=markup)
    bot.answer_callback_query(call.id, "به بازی پیوستید.")

@bot.callback_query_handler(func=lambda call: call.data.startswith("dyncell|"))
def dynamite_cell_reveal(call):
    with dynamite_lock:
        _dynamite_cell_reveal_locked(call)

def _dynamite_finish(message_id, game, winner_id, winner_name, loser_id, loser_name, middle_text):
    """تسویه‌ی مبلغ بازی (چه با بمب، چه با تموم شدن وقت نوبت) و ادیت پیام نتیجه."""
    old_timer = game.get("turn_timer")
    if old_timer is not None:
        try:
            old_timer.cancel()
        except Exception:
            pass

    pool = game["amount"] * 2
    payout, tax, loan_repay, tax_rate_used, loan_rate_used = calculate_payout(winner_id, pool, context="bet")
    if ATOMIC_DB_MODE:
        try:
            result = supabase.rpc("atomic_settle_pool", {
                "p_winner_id": int(winner_id),
                "p_pool": int(pool),
                "p_tax": int(tax),
                "p_loan_repay": int(loan_repay),
                "p_tax_receiver_id": int(TAX_RECEIVER_ID) if get_user(TAX_RECEIVER_ID) else None,
            }).execute().data
            if not result:
                raise RuntimeError("empty settlement result")
            row = result[0] if isinstance(result, list) else result
            payout = int(row.get("payout", payout) or 0)
            tax = int(row.get("tax", tax) or 0)
        except Exception as e:
            logging.error(f"خطا در settlement اتمیک دینامیت {message_id}: {e}")
            return
    else:
        update_diamonds(winner_id, payout)
        if get_user(TAX_RECEIVER_ID):
            update_diamonds(TAX_RECEIVER_ID, tax)
    register_bet_win(winner_id, game["chat_id"], winner_name)

    chat_id = game["chat_id"]
    game["status"] = "finished"
    active_dynamites.pop(message_id, None)
    _dynamite_db_delete(message_id)

    text = (
        "◈ ━━━━ 𝗗𝘆𝗻𝗮𝗺𝗶𝘁𝗲 ━━━━━ ◈\n"
        " نتیجه باز‌ی ⎙\n\n"
        f"{middle_text}\n\n"
        f"♧ | برنده: {winner_name}\n"
        f"⌫ |  بازنده: {loser_name}\n"
        "◈ ━━━━ 𝗗𝘆𝗻𝗮𝗺𝗶𝘁𝗲 ━━━━━ ◈"
    )
    safe_edit_message(text, chat_id=chat_id, message_id=message_id, reply_markup=dynamite_result_markup(payout, tax))

def _dynamite_cell_reveal_locked(call):
    message_id = call.message.message_id
    game = active_dynamites.get(message_id) or _dynamite_lazy_load(message_id)
    if not game or game["status"] != "active":
        bot.answer_callback_query(call.id, "این بازی تموم شده.", show_alert=True)
        return

    clicker_id = call.from_user.id
    if clicker_id not in (game["creator_id"], game["opponent_id"]):
        bot.answer_callback_query(call.id, "شما در این بازی نیستید.", show_alert=True)
        return
    if clicker_id != game["turn_id"]:
        bot.answer_callback_query(call.id, "الان نوبت شما نیست!", show_alert=True)
        return

    idx = int(call.data.split("|")[1])
    if idx in game["revealed"]:
        bot.answer_callback_query(call.id)
        return
    bot.answer_callback_query(call.id)

    if idx == game["bomb_index"]:
        loser_id = clicker_id
        if clicker_id == game["creator_id"]:
            loser_name, winner_id, winner_name = game["creator_name"], game["opponent_id"], game["opponent_name"]
        else:
            loser_name, winner_id, winner_name = game["opponent_name"], game["creator_id"], game["creator_name"]
        middle_text = f"بازیکن {loser_name} منفجر شد!"
        _dynamite_finish(message_id, game, winner_id, winner_name, loser_id, loser_name, middle_text)
        return

    game["revealed"].add(idx)
    game["safe_remaining"] -= 1
    game["turn_id"] = game["opponent_id"] if clicker_id == game["creator_id"] else game["creator_id"]
    start_turn_timer(message_id, game)

    _dynamite_db_upsert(message_id, game)
    text = dynamite_active_text(game)
    markup = dynamite_board_markup(game)
    safe_edit_message(text, chat_id=game["chat_id"], message_id=message_id, reply_markup=markup)

# این تابع همین‌جا (در زمان import شدن فایل) صدا زده می‌شود، نه فقط داخل
# if __name__=="__main__"، چون بعضی سرویس‌های هاست (مثلاً gunicorn) فایل رو
# مستقیماً اجرا نمی‌کنن بلکه import می‌کنن؛ اینجوری همیشه بازی‌های نیمه‌کاره برمی‌گردن.
rehydrate_dynamite_games()

# ================== بخش کازینو ==================
CASINO_GAMES = {
    "dice": "🎲",
    "dart": "🎯",
    "basket": "🏀",
    "football": "⚽",
    "bowling": "🎳",
    "slot": "🎰",
}
CASINO_GAME_NAMES = {
    "dice": "تاس",
    "dart": "دارت",
    "basket": "بسکتبال",
    "football": "فوتبال",
    "bowling": "بولینگ",
    "slot": "اسلات",
}
CASINO_BET_PRESETS = [100000, 500000, 1000000, 5000000, 10000000]

def casino_games_keyboard(owner_id):
    markup = types.InlineKeyboardMarkup()
    games = list(CASINO_GAMES.items())
    for i in range(0, len(games), 3):
        row = []
        for key, emoji in games[i:i + 3]:
            row.append(colored_button(emoji, callback_data=f"cgame|{key}|{owner_id}"))
        markup.row(*row)
    return markup

@bot.callback_query_handler(func=lambda call: call.data == "casinomenu" or call.data.startswith("casinomenu|"))
def casino_from_main_menu(call):
    if "|" in call.data:
        owner_id = check_panel_owner(call)
        if owner_id is None:
            return
    else:
        owner_id = call.from_user.id
    bot.answer_callback_query(call.id)
    safe_edit_message(
        "◈ ━━━━━ 𝗕𝗲𝘁 ━━━━━━ ◈\n"
        "♧ | به بخش کازینو خوش اومدی!\n\n"
        "❖ | یکی از بازی‌ها رو انتخاب کن:\n"
        "◈ ━━━━━ 𝗕𝗲𝘁 ━━━━━━ ◈",
        chat_id=call.message.chat.id,
        message_id=call.message.message_id,
        reply_markup=casino_games_keyboard(owner_id)
    )

@bot.message_handler(func=lambda m: text_is(m, "کازینو"))
def casino_panel(message):
    if not get_user(message.from_user.id):
        bot.reply_to(message, "اول /start بزن.")
        return
    show_or_edit_panel(
        message, message.from_user.id, "casino",
        "◈ ━━━━━ 𝗕𝗲𝘁 ━━━━━━ ◈\n"
        "♧ | به بخش کازینو خوش اومدی!\n\n"
        "❖ | یکی از بازی‌ها رو انتخاب کن:\n"
        "◈ ━━━━━ 𝗕𝗲𝘁 ━━━━━━ ◈",
        casino_games_keyboard(message.from_user.id)
    )

@bot.callback_query_handler(func=lambda call: call.data.startswith("cgame|"))
def casino_game_select(call):
    owner_id = check_panel_owner(call)
    if owner_id is None:
        return
    if not get_user(owner_id):
        bot.answer_callback_query(call.id, "اول /start بزن.", show_alert=True)
        return
    bot.answer_callback_query(call.id)
    game_key = call.data.split("|")[1]

    safe_edit_message(
        f"◈ ━━━━━ 𝗕𝗲𝘁 ━━━━━━ ◈\n"
        f"☻ | بازی : {CASINO_GAME_NAMES[game_key]}\n\n"
        f"⌲ | مقدار الماسی که میخواید شرط ببندید رو ارسال کنید\n"
        f"◈ ━━━━━ 𝗕𝗲𝘁 ━━━━━━ ◈",
        chat_id=call.message.chat.id, message_id=call.message.message_id, reply_markup=None
    )
    register_timed_next_step_handler(call.message, casino_custom_amount_step, game_key, owner_id, call.message.message_id, expected_user_id=owner_id)

@bot.callback_query_handler(func=lambda call: call.data == "cback" or call.data.startswith("cback|"))
def casino_back(call):
    if "|" in call.data:
        owner_id = check_panel_owner(call)
        if owner_id is None:
            return
    else:
        owner_id = call.from_user.id
    bot.answer_callback_query(call.id)
    safe_edit_message(
        "◈ ━━━━━ 𝗕𝗲𝘁 ━━━━━━ ◈\n"
        "♧ | به بخش کازینو خوش اومدی!\n\n"
        "❖ | یکی از بازی‌ها رو انتخاب کن:\n"
        "◈ ━━━━━ 𝗕𝗲𝘁 ━━━━━━ ◈",
        chat_id=call.message.chat.id, message_id=call.message.message_id, reply_markup=casino_games_keyboard(owner_id)
    )

def cancel_casino_timer(msg_id):
    with casino_lock:
        if msg_id in casino_timers:
            casino_timers[msg_id].cancel()
            del casino_timers[msg_id]

def check_casino_timeout(msg_id):
    with casino_lock:
        game = active_casino_games.get(msg_id)
        if not game or game["player2"] is not None:
            return
        if update_diamonds(game["player1"]["id"], game["bet"]) is None:
            logging.error(f"بازگرداندن مبلغ کازینو {msg_id} انجام نشد")
            return
        del active_casino_games[msg_id]
        if msg_id in casino_timers:
            del casino_timers[msg_id]

    markup = types.InlineKeyboardMarkup()
    markup.add(colored_button("🎰 بازگشت به کازینو", callback_data="casinoback"))
    safe_edit_message(
        f"⎋ | زمان تموم شد!\n"
        f"⎌ | {game['bet']} الماس به سازنده برگردونده شد.",
        chat_id=game["chat_id"], message_id=msg_id, reply_markup=markup
    )

@bot.callback_query_handler(func=lambda call: call.data.startswith("cbet|"))
def casino_bet_select(call):
    owner_id = check_panel_owner(call)
    if owner_id is None:
        return
    _, game_key, amount, _owner = call.data.split("|")
    amount = int(amount)
    user = call.from_user  # == owner_id, تضمین‌شده توسط چک بالا

    if not get_user(user.id):
        bot.answer_callback_query(call.id, "اول /start بزن.", show_alert=True)
        return
    if get_balance(user.id) < amount:
        bot.answer_callback_query(call.id, "💎 موجودی الماس شما کافی نیست!", show_alert=True)
        return

    bot.answer_callback_query(call.id)
    reserved = update_diamonds(user.id, -amount)
    if reserved is None:
        bot.answer_callback_query(call.id, "💎 موجودی کافی نیست یا رزرو شرط انجام نشد.", show_alert=True)
        return

    markup = types.InlineKeyboardMarkup()
    markup.row(
        colored_button("لغو ⊗", callback_data=f"ccancel|{call.message.message_id}"),
        colored_button("پیوستن ✓", callback_data="cjoin"),
    )

    text = (
        f"◈ ━━━━━ 𝗕𝗲𝘁 ━━━━━━ ◈\n"
        f"☻ | بازی : {CASINO_GAME_NAMES[game_key]}\n\n"
        f"$ | مقدار الماس : {amount}\n"
        f"♛ | سازنده : {display_name_with_tag(user.id, get_display_name(user))}\n"
        f"◈ ━━━━━ 𝗕𝗲𝘁 ━━━━━━ ◈"
    )
    safe_edit_message(text, chat_id=call.message.chat.id, message_id=call.message.message_id, reply_markup=markup)
    msg_id = call.message.message_id

    with casino_lock:
        active_casino_games[msg_id] = {
            "game": game_key,
            "bet": amount,
            "chat_id": call.message.chat.id,
            "player1": {"id": user.id, "name": get_display_name(user)},
            "player2": None,
            "score1": None,
            "score2": None,
            "vs_bot": False,
        }
        timer = threading.Timer(JOIN_TIMEOUT_SECONDS, check_casino_timeout, args=[msg_id])
        casino_timers[msg_id] = timer
        timer.start()

@bot.callback_query_handler(func=lambda call: call.data.startswith("ccancel|"))
def casino_cancel(call):
    msg_id = int(call.data.split("|")[1])
    user_id = call.from_user.id

    with casino_lock:
        game = active_casino_games.get(msg_id)
        if not game:
            bot.answer_callback_query(call.id, "این بازی دیگه معتبر نیست.", show_alert=True)
            return
        if game["player2"] is not None:
            bot.answer_callback_query(call.id, "بازی شروع شده، نمی‌توان لغو کرد.", show_alert=True)
            return
        if user_id != game["player1"]["id"]:
            bot.answer_callback_query(call.id, "فقط سازنده می‌تونه بازی رو لغو کنه.", show_alert=True)
            return

        if update_diamonds(game["player1"]["id"], game["bet"]) is None:
            logging.error(f"بازگرداندن شرط کازینو {msg_id} انجام نشد")
            return
        del active_casino_games[msg_id]
        if msg_id in casino_timers:
            casino_timers[msg_id].cancel()
            del casino_timers[msg_id]

    bot.answer_callback_query(call.id, "بازی لغو شد.")
    markup = types.InlineKeyboardMarkup()
    markup.add(colored_button("🎰 بازگشت به کازینو", callback_data="casinoback"))
    safe_edit_message(
        f"⊗ | بازی لغو شد.\n"
        f"⎌ | {game['bet']} الماس برگردونده شد.",
        chat_id=game["chat_id"], message_id=msg_id, reply_markup=markup
    )

@bot.callback_query_handler(func=lambda call: call.data == "casinoback")
def casino_back_to_list(call):
    bot.answer_callback_query(call.id)
    safe_edit_message(
        "◈ ━━━━━ 𝗕𝗲𝘁 ━━━━━━ ◈\n"
        "♧ | به بخش کازینو خوش اومدی!\n\n"
        "❖ | یکی از بازی‌ها رو انتخاب کن:\n"
        "◈ ━━━━━ 𝗕𝗲𝘁 ━━━━━━ ◈",
        chat_id=call.message.chat.id,
        message_id=call.message.message_id,
        reply_markup=casino_games_keyboard(call.from_user.id)
    )

# ================== معدن الماس (مین‌زدن تکی) ==================
def mine_board_text(bet, found, multiplier, footer_line="❖ | الماس هارو پیدا کن"):
    payout = int(bet * multiplier)
    not_found = (MINE_GRID_SIZE - 1) - found
    mult_str = f"{multiplier:.2f}x" if multiplier > 0 else ""
    return (
        "◈ ━━━━━ 𝗕𝗲𝘁 ━━━━━━ ◈\n"
        "☻ | بازی : معدن الماس\n\n"
        f"$ | مبلغ ورودی : {bet:,}\n"
        f"♛ | مبلغ دریافتی : {payout:,} ({mult_str})\n\n"
        f"♧ | الماس های پیدا شده : {found}\n"
        f"⌫ | الماس های پیدا نشده : {not_found}\n\n"
        f"{footer_line}\n"
        "◈ ━━━━━ 𝗕𝗲𝘁 ━━━━━━ ◈"
    )

def mine_board_markup(revealed, owner_id):
    markup = types.InlineKeyboardMarkup()
    for row in range(3):
        buttons = []
        for col in range(3):
            idx = row * 3 + col
            label = "💎" if idx in revealed else " "
            buttons.append(colored_button(label, callback_data=f"mine|{idx}|{owner_id}"))
        markup.row(*buttons)
    markup.row(colored_button("💰 برداشت الان", callback_data=f"minecashout|{owner_id}"))
    return markup

def mine_result_markup():
    markup = types.InlineKeyboardMarkup()
    markup.add(colored_button("🎰 بازگشت به کازینو", callback_data="casinoback"))
    return markup

@bot.message_handler(func=lambda m: text_is(m, "معدن الماس", "معدن"))
def mine_panel_entry(message):
    if not get_user(message.from_user.id):
        bot.reply_to(message, "اول /start بزن.")
        return
    panel_id = show_or_edit_panel(
        message, message.from_user.id, "mine",
        "◈ ━━━━━ 𝗕𝗲𝘁 ━━━━━━ ◈\n"
        "☻ | بازی : معدن الماس\n\n"
        "⌲ | مقدار الماسی که میخواید شرط ببندید رو ارسال کنید\n"
        "◈ ━━━━━ 𝗕𝗲𝘁 ━━━━━━ ◈"
    )
    if panel_id:
        # مرحله ورودی با خود پنل ثبت می‌شود تا نتیجه هم همان پیام را ادیت کند.
        class _PanelMessage:
            pass
        panel = _PanelMessage()
        panel.chat = message.chat
        panel.message_id = panel_id
        from types import SimpleNamespace
        panel.from_user = SimpleNamespace(id=0, is_bot=True)
        register_timed_next_step_handler(panel, mine_bet_step, message.from_user.id, panel_id, expected_user_id=message.from_user.id)

def mine_bet_step(message, expected_user_id, prompt_msg_id):
    if not require_reply_to_panel(message, prompt_msg_id, "برای شروع معدن، روی همین پنل ریپلای کن و مبلغ را بفرست."):
        register_timed_next_step_handler(message, mine_bet_step, expected_user_id, prompt_msg_id, expected_user_id=expected_user_id)
        return
    if message.from_user.id != expected_user_id:
        # پیام از یه نفر دیگه بود؛ نادیده می‌گیریم ولی منتظر پیام خودِ کاربر می‌مونیم
        register_timed_next_step_handler(message, mine_bet_step, expected_user_id, prompt_msg_id, expected_user_id=expected_user_id)
        return
    amount = parse_amount(message.text)
    if amount is None:
        safe_edit_message("❌ مبلغ نامعتبره. روی همین پنل ریپلای کن و یه عدد درست بفرست (مثلاً 100000 یا 100k):", message.chat.id, prompt_msg_id, reply_markup=None)
        register_timed_next_step_handler(message, mine_bet_step, expected_user_id, prompt_msg_id, expected_user_id=expected_user_id)
        return
    if get_balance(expected_user_id) < amount:
        safe_edit_message("💎 موجودی کافی نیست. روی همین پنل ریپلای کن و مبلغ دیگه‌ای بفرست:", message.chat.id, prompt_msg_id, reply_markup=None)
        register_timed_next_step_handler(message, mine_bet_step, expected_user_id, prompt_msg_id, expected_user_id=expected_user_id)
        return

    update_diamonds(expected_user_id, -amount)
    bomb_index = random.randint(0, MINE_GRID_SIZE - 1)
    text = mine_board_text(amount, 0, 0.0)
    markup = mine_board_markup(set(), expected_user_id)
    # همون پیام اول (که مبلغ رو ازش پرسیده بودیم) ویرایش میشه، پیام جدید فرستاده نمیشه
    safe_edit_message(text, message.chat.id, prompt_msg_id, reply_markup=markup)
    active_mine_games[prompt_msg_id] = {
        "chat_id": message.chat.id,
        "owner_id": expected_user_id,
        "bet": amount,
        "bomb_index": bomb_index,
        "revealed": set(),
        "diamonds_found": 0,
    }

@bot.callback_query_handler(func=lambda call: call.data == "noop")
def noop_callback(call):
    bot.answer_callback_query(call.id)

@bot.callback_query_handler(func=lambda call: call.data.startswith("mine|"))
def mine_cell_reveal(call):
    with mine_lock:
        _mine_cell_reveal_locked(call)

def _mine_cell_reveal_locked(call):
    owner_id = check_panel_owner(call)
    if owner_id is None:
        return
    game = active_mine_games.get(call.message.message_id)
    if not game:
        bot.answer_callback_query(call.id, "این بازی تموم شده.", show_alert=True)
        return
    idx = int(call.data.split("|")[1])
    if idx in game["revealed"]:
        bot.answer_callback_query(call.id)
        return
    bot.answer_callback_query(call.id)

    if idx == game["bomb_index"]:
        del active_mine_games[call.message.message_id]
        markup = types.InlineKeyboardMarkup()
        for row in range(3):
            buttons = []
            for col in range(3):
                i = row * 3 + col
                if i == game["bomb_index"]:
                    label = "💥"
                elif i in game["revealed"]:
                    label = "💎"
                else:
                    label = " "
                buttons.append(colored_button(label, callback_data="noop"))
            markup.row(*buttons)
        markup.row(colored_button("🎰 بازگشت به کازینو", callback_data="casinoback"))
        not_found = (MINE_GRID_SIZE - 1) - game['diamonds_found']
        text = (
            "◈ ━━━━━ 𝗕𝗲𝘁 ━━━━━━ ◈\n"
            "☻ | بازی : معدن الماس\n\n"
            f"$ | مبلغ ورودی : {game['bet']:,} 💎\n"
            f"♛ | مبلغ دریافتی : 0 💎 (0.00x)\n\n"
            f"♧ | الماس های پیدا شده : {game['diamonds_found']}\n"
            f"⌫ | الماس های پیدا نشده : {not_found}\n\n"
            "✹ | بووووممم\n"
            "✕ | باختی کل الماس شرط از دست رفت\n"
            "◈ ━━━━━ 𝗕𝗲𝘁 ━━━━━━ ◈"
        )
        safe_edit_message(text, call.message.chat.id, call.message.message_id, reply_markup=markup)
        return

    game["revealed"].add(idx)
    game["diamonds_found"] += 1
    multiplier = game["diamonds_found"] * MINE_MULTIPLIER_STEP

    if game["diamonds_found"] >= MINE_GRID_SIZE - 1:
        # همه‌ی خونه‌های غیر بمب پیدا شدن؛ برد کامل و برداشت خودکار
        payout = int(game["bet"] * multiplier)
        if ATOMIC_DB_MODE:
            try:
                supabase.rpc("atomic_mine_payout", {"p_user_id": int(owner_id), "p_payout": int(payout)}).execute()
            except Exception as e:
                logging.error(f"خطا در پرداخت اتمیک معدن {owner_id}: {e}")
                bot.answer_callback_query(call.id, "پرداخت انجام نشد.", show_alert=True)
                return
        else:
            update_diamonds(owner_id, payout)
        del active_mine_games[call.message.message_id]
        text = mine_board_text(
            game["bet"], game["diamonds_found"], multiplier,
            footer_line="🎉 همه‌ی الماس‌ها رو پیدا کردی! مبلغ به حسابت اضافه شد."
        )
        safe_edit_message(text, call.message.chat.id, call.message.message_id, reply_markup=None)
        auto_return_to_casino(call.message.chat.id, call.message.message_id, owner_id, 5)
        return

    text = mine_board_text(game["bet"], game["diamonds_found"], multiplier)
    markup = mine_board_markup(game["revealed"], owner_id)
    safe_edit_message(text, call.message.chat.id, call.message.message_id, reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data.startswith("minecashout|"))
def mine_cash_out(call):
    with mine_lock:
        _mine_cash_out_locked(call)

def _mine_cash_out_locked(call):
    owner_id = check_panel_owner(call)
    if owner_id is None:
        return
    game = active_mine_games.get(call.message.message_id)
    if not game:
        bot.answer_callback_query(call.id, "این بازی تموم شده.", show_alert=True)
        return
    if game["diamonds_found"] == 0:
        bot.answer_callback_query(call.id, "هنوز هیچ الماسی پیدا نکردی!", show_alert=True)
        return
    bot.answer_callback_query(call.id)
    multiplier = game["diamonds_found"] * MINE_MULTIPLIER_STEP
    payout = int(game["bet"] * multiplier)
    if ATOMIC_DB_MODE:
        try:
            supabase.rpc("atomic_mine_payout", {"p_user_id": int(owner_id), "p_payout": int(payout)}).execute()
        except Exception as e:
            logging.error(f"خطا در پرداخت اتمیک معدن {owner_id}: {e}")
            bot.answer_callback_query(call.id, "پرداخت انجام نشد.", show_alert=True)
            return
    else:
        update_diamonds(owner_id, payout)
    del active_mine_games[call.message.message_id]
    text = mine_board_text(
        game["bet"], game["diamonds_found"], multiplier,
        footer_line=f"✓  | برداشت انجام شد! {payout:,} الماس به حسابت اضافه شد."
    )
    safe_edit_message(text, call.message.chat.id, call.message.message_id, reply_markup=mine_result_markup())

# ================== پنل کارخونه حفاری الماس ==================
def factory_panel_text(factory, owner_name):
    capacity = factory_warehouse_capacity(factory["warehouse_level"])
    stored = int(factory["warehouse_stored"])
    workers_max = factory_workers_max(factory["workers_level"])
    drill_seconds = factory_drill_seconds(factory["machine_level"])
    return (
        "◈ ━━━━━ 𝗙𝗮𝗰𝘁𝗼𝗿𝘆 ━━━━━━ ◈\n"
        "⌬ | حفاری\n\n"
        f"♛ | مدیر کارخونه : {owner_name}\n\n"
        "回 | انبار کارخونه\n"
        f"┘─ 回 | ظرفیت انبار : {stored:,} / {capacity:,} الماس\n"
        f"┘─ ❖ | سطح : {factory['warehouse_level']}\n\n"
        "☭ | کارگران حفار\n"
        f"┘─ ⎚ | تعداد کارگران : {factory['workers_hired']} / {workers_max} کارگر\n"
        f"┘─ ❖ | سطح : {factory['workers_level']}\n\n"
        "⍠ | دستگاه حفاری\n"
        f"┘─ ⍐ | زمان در آوردن هر الماس : {drill_seconds:.1f} ثانیه\n"
        f"┘─ ❖ | سطح : {factory['machine_level']}\n\n"
        "⎙ | شما درحال مدیریت کارخانه خود میباشید.\n"
        "◈ ━━━━━ 𝗙𝗮𝗰𝘁𝗼𝗿𝘆 ━━━━━━ ◈"
    )

def factory_main_markup(owner_id):
    markup = types.InlineKeyboardMarkup()
    markup.add(colored_button("📤 برداشت", callback_data=f"fprod|{owner_id}"))
    markup.row(
        colored_button("👷‍♂️ کارکنان", callback_data=f"fworkers|{owner_id}"),
        colored_button("🧳 انبار", callback_data=f"fwarehouse|{owner_id}"),
    )
    markup.add(colored_button("🖨 دستگاه‌های حفاری", callback_data=f"fmachine|{owner_id}"))
    return markup

def factory_unlock_markup(user_id):
    markup = types.InlineKeyboardMarkup()
    markup.add(colored_button("پرداخت 3000 الماس💎", callback_data=f"fopen|{user_id}"))
    return markup

def factory_unlock_text():
    return (
        "برای افتتاح بخش حفاری شما باید مبلغ 3000 الماس پرداخت کنید✅\n\n"
        "بخش حفاری را افتتاح کنید و الماس رایگان بگیرید🔥"
    )

def open_factory(user_id):
    factory = get_factory(user_id)
    if not factory:
        return False, "❌ خطا در بارگذاری کارخونه. دوباره امتحان کن."
    if factory.get("factory_unlocked"):
        return True, "بخش حفاری از قبل فعال است."
    if get_balance(user_id) < FACTORY_OPENING_FEE:
        return False, f"برای افتتاح بخش حفاری باید {FACTORY_OPENING_FEE:,} 💎 داشته باشی."
    try:
        if update_diamonds(user_id, -FACTORY_OPENING_FEE) is None:
            return False, "موجودی کافی نیست."
        supabase.table("factories").update({"factory_unlocked": True}).eq("user_id", user_id).execute()
        return True, "✅ بخش حفاری با موفقیت افتتاح شد!"
    except Exception as e:
        logging.error(f"خطا در open_factory: {e}")
        return False, "افتتاح بخش حفاری انجام نشد."

@bot.message_handler(func=lambda m: text_is(m, "حفاری"))
def factory_entry(message):
    if not get_user(message.from_user.id):
        bot.reply_to(message, "اول /start بزن.")
        return
    factory = sync_factory_production(get_factory(message.from_user.id))
    if not factory:
        bot.reply_to(message, "❌ خطا در بارگذاری کارخونه. دوباره امتحان کن.")
        return
    if not factory.get("factory_unlocked"):
        show_or_edit_panel(
            message, message.from_user.id, "factory",
            factory_unlock_text(), factory_unlock_markup(message.from_user.id)
        )
        return
    name = get_display_name(message.from_user)
    show_or_edit_panel(message, message.from_user.id, "factory", factory_panel_text(factory, name), factory_main_markup(message.from_user.id))

@bot.callback_query_handler(func=lambda call: call.data.startswith("fopen|"))
def factory_open(call):
    user_id = check_panel_owner(call)
    if user_id is None:
        return
    bot.answer_callback_query(call.id)
    ok, result_msg = open_factory(user_id)
    if not ok:
        safe_edit_message(f"❌ {result_msg}", call.message.chat.id, call.message.message_id, factory_unlock_markup(user_id))
        return
    factory = sync_factory_production(get_factory(user_id))
    name = get_display_name(call.from_user)
    safe_edit_message(
        result_msg + "\n\n" + factory_panel_text(factory, name),
        call.message.chat.id, call.message.message_id, factory_main_markup(user_id)
    )

@bot.callback_query_handler(func=lambda call: call.data.startswith("fback|"))
def factory_back(call):
    owner_id = check_panel_owner(call)
    if owner_id is None:
        return
    bot.answer_callback_query(call.id)
    factory = sync_factory_production(get_factory(owner_id))
    if not factory.get("factory_unlocked"):
        safe_edit_message(
            factory_unlock_text(), call.message.chat.id, call.message.message_id,
            factory_unlock_markup(owner_id)
        )
        return
    name = get_display_name(call.from_user)
    safe_edit_message(
        factory_panel_text(factory, name), call.message.chat.id, call.message.message_id,
        reply_markup=factory_main_markup(owner_id)
    )

# ---------- تولید (برداشت از انبار) ----------
@bot.callback_query_handler(func=lambda call: call.data.startswith("fprod|"))
def factory_production_prompt(call):
    owner_id = check_panel_owner(call)
    if owner_id is None:
        return
    factory = sync_factory_production(get_factory(owner_id))
    stored = int(factory["warehouse_stored"])
    if stored <= 0:
        bot.answer_callback_query(call.id, "هنوز الماسی توی انبار جمع نشده!", show_alert=True)
        return
    bot.answer_callback_query(call.id)
    text = f"◈ ━━━━━ 𝗙𝗮𝗰𝘁𝗼𝗿𝘆 ━━━━━━ ◈\n⎙ | چند تا الماس می‌خوای از انبار برداری؟\n回 | موجودی انبار: {stored:,} الماس\n\n⌲ | مقداری که میخوای برداشت کنی رو بفرست.\n◈ ━━━━━ 𝗙𝗮𝗰𝘁𝗼𝗿𝘆 ━━━━━━ ◈"
    safe_edit_message(text, call.message.chat.id, call.message.message_id, reply_markup=None)
    register_timed_next_step_handler(call.message, factory_production_step, owner_id, call.message.message_id, expected_user_id=owner_id)

def factory_production_step(message, expected_user_id, panel_msg_id):
    if not require_reply_to_panel(message, panel_msg_id, "برای برداشت از انبار، روی همین پنل حفاری ریپلای کن و مقدار را بفرست."):
        register_timed_next_step_handler(message, factory_production_step, expected_user_id, panel_msg_id, expected_user_id=expected_user_id)
        return
    if message.from_user.id != expected_user_id:
        register_timed_next_step_handler(message, factory_production_step, expected_user_id, panel_msg_id, expected_user_id=expected_user_id)
        return
    factory = sync_factory_production(get_factory(expected_user_id))
    stored = int(factory["warehouse_stored"])
    amount = parse_amount(message.text)
    if amount is None or amount <= 0:
        safe_edit_message(f"❌ مبلغ نامعتبره. روی همین پنل ریپلای کن. بین 1 تا {stored:,} بفرست:", message.chat.id, panel_msg_id, reply_markup=None)
        register_timed_next_step_handler(message, factory_production_step, expected_user_id, panel_msg_id, expected_user_id=expected_user_id)
        return
    if amount > stored:
        safe_edit_message(f"❌ انبار فقط {stored:,} الماس داره. روی همین پنل ریپلای کن و یه مقدار کمتر بفرست:", message.chat.id, panel_msg_id, reply_markup=None)
        register_timed_next_step_handler(message, factory_production_step, expected_user_id, panel_msg_id, expected_user_id=expected_user_id)
        return

    new_stored = stored - amount
    update_diamonds(expected_user_id, amount)
    xp_gain = amount // FACTORY_XP_PER_HARVEST_UNIT
    new_xp = factory["factory_xp"] + xp_gain
    new_level = factory["factory_level"]
    needed = factory_xp_needed(new_level)
    leveled_up = False
    while new_level < FACTORY_MAX_LEVEL and needed > 0 and new_xp >= needed:
        new_xp -= needed
        new_level += 1
        leveled_up = True
        needed = factory_xp_needed(new_level)
    try:
        supabase.table("factories").update({
            "warehouse_stored": new_stored, "factory_xp": new_xp, "factory_level": new_level
        }).eq("user_id", expected_user_id).execute()
    except Exception as e:
        logging.error(f"خطا در ثبت برداشت کارخونه: {e}")

    level_line = f"\n🎉 سطح کارخونه رفت بالا! سطح جدید: {new_level}" if leveled_up else ""
    result = bot.reply_to(
        message,
        f"✅ {amount:,} 💎 از انبار برداشت شد و به موجودیت اضافه شد.{level_line}"
    )
    if result:
        auto_return_to_factory(message.chat.id, result.message_id, expected_user_id, 5)

# ---------- انبار ----------
def render_warehouse_panel(call, owner_id, factory):
    level = factory["warehouse_level"]
    cap = factory_warehouse_capacity(level)
    cost = factory_warehouse_upgrade_cost(level)
    markup = types.InlineKeyboardMarkup()
    if level < FACTORY_MAX_LEVEL:
        next_cap = factory_warehouse_capacity(level + 1)
        text = (
            "🧳 انبار کارخونه\n\n"
            f"⭐️ سطح فعلی: {level}\n"
            f"🔺 ظرفیت فعلی: {int(factory['warehouse_stored']):,} / {cap:,} الماس\n\n"
            f"⬆️ هزینه ارتقا به سطح {level + 1}: {cost:,} 💎\n"
            f"🔺 ظرفیت بعد از ارتقا: {next_cap:,} الماس"
        )
        markup.add(colored_button(f"⬆️ ارتقا ({cost:,} 💎)", callback_data=f"fwhup|{owner_id}"))
    else:
        text = (
            "🧳 انبار کارخونه\n\n"
            f"⭐️ سطح فعلی: {level} (حداکثر)\n"
            f"🔺 ظرفیت فعلی: {int(factory['warehouse_stored']):,} / {cap:,} الماس\n\n"
            "🏆 انبار به حداکثر سطح رسیده است."
        )
    markup.add(colored_button("🔙 بازگشت به پنل حفاری 🏗️", callback_data=f"fback|{owner_id}"))
    safe_edit_message(text, call.message.chat.id, call.message.message_id, reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data.startswith("fwarehouse|"))
def factory_warehouse_panel(call):
    owner_id = check_panel_owner(call)
    if owner_id is None:
        return
    bot.answer_callback_query(call.id)
    render_warehouse_panel(call, owner_id, sync_factory_production(get_factory(owner_id)))

@bot.callback_query_handler(func=lambda call: call.data.startswith("fwhup|"))
def factory_warehouse_upgrade(call):
    owner_id = check_panel_owner(call)
    if owner_id is None:
        return
    factory = sync_factory_production(get_factory(owner_id))
    level = factory["warehouse_level"]
    if level >= FACTORY_MAX_LEVEL:
        bot.answer_callback_query(call.id, "🏆 انبار به حداکثر سطح ۱۰ رسیده است.", show_alert=True)
        render_warehouse_panel(call, owner_id, factory)
        return
    cost = factory_warehouse_upgrade_cost(level)
    if get_balance(owner_id) < cost:
        bot.answer_callback_query(call.id, "💎 موجودی کافی نیست!", show_alert=True)
        return
    update_diamonds(owner_id, -cost)
    try:
        supabase.table("factories").update({"warehouse_level": level + 1}).eq("user_id", owner_id).execute()
    except Exception as e:
        logging.error(f"خطا در ارتقای انبار: {e}")
    bot.answer_callback_query(call.id, "✅ ارتقا انجام شد!")
    factory["warehouse_level"] = level + 1
    render_warehouse_panel(call, owner_id, factory)

# ---------- کارکنان ----------
def render_workers_panel(call, owner_id, factory):
    level = factory["workers_level"]
    max_workers = factory_workers_max(level)
    hired = factory["workers_hired"]
    wage = factory_wage_per_worker(level)
    upgrade_cost = factory_workers_upgrade_cost(level)
    if level < FACTORY_MAX_LEVEL:
        text = (
            "👷‍♂️ کارگران حفار\n"
            f"┘─ 👤 تعداد کارگران : {hired} / {max_workers}\n"
            f"┘─ ⭐️ سطح : {level}\n\n"
            f"💰 دستمزد هر کارگر: {wage:,} 💎 در روز\n"
            f"⬆️ هزینه ارتقا به سطح {level + 1}: {upgrade_cost:,} 💎\n"
            f"👤 حداکثر کارگر بعد از ارتقا: {factory_workers_max(level + 1)}\n\n"
            "ℹ️ هر کارگر به‌صورت خودکار در تولید الماس سهم دارد."
        )
    else:
        text = (
            "👷‍♂️ کارگران حفار\n"
            f"┘─ 👤 تعداد کارگران : {hired} / {max_workers}\n"
            f"┘─ ⭐️ سطح : {level} (حداکثر)\n\n"
            f"💰 دستمزد هر کارگر: {wage:,} 💎 در روز\n\n"
            "🏆 سطح کارکنان به حداکثر رسیده است.\n"
            "ℹ️ هر کارگر به‌صورت خودکار در تولید الماس سهم دارد."
        )
    markup = types.InlineKeyboardMarkup()
    if hired < max_workers:
        markup.add(colored_button("➕ استخدام یک کارگر", callback_data=f"fhire|{owner_id}"))
    if level < FACTORY_MAX_LEVEL:
        markup.add(colored_button(f"⬆️ ارتقا ({upgrade_cost:,} 💎)", callback_data=f"fwkup|{owner_id}"))
    markup.add(colored_button("🔙 بازگشت", callback_data=f"fback|{owner_id}"))
    safe_edit_message(text, call.message.chat.id, call.message.message_id, reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data.startswith("fworkers|"))
def factory_workers_panel(call):
    owner_id = check_panel_owner(call)
    if owner_id is None:
        return
    bot.answer_callback_query(call.id)
    render_workers_panel(call, owner_id, sync_factory_production(get_factory(owner_id)))

@bot.callback_query_handler(func=lambda call: call.data.startswith("fhire|"))
def factory_hire_worker(call):
    owner_id = check_panel_owner(call)
    if owner_id is None:
        return
    factory = sync_factory_production(get_factory(owner_id))
    max_workers = factory_workers_max(factory["workers_level"])
    if factory["workers_hired"] >= max_workers:
        bot.answer_callback_query(call.id, "به حداکثر ظرفیت کارگر رسیدی!", show_alert=True)
        return
    new_hired = min(factory["workers_hired"] + 1, max_workers)
    try:
        supabase.table("factories").update({"workers_hired": new_hired}).eq("user_id", owner_id).execute()
    except Exception as e:
        logging.error(f"خطا در استخدام کارگر: {e}")
    bot.answer_callback_query(call.id, "✅ کارگر استخدام شد!")
    factory["workers_hired"] = new_hired
    render_workers_panel(call, owner_id, factory)

@bot.callback_query_handler(func=lambda call: call.data.startswith("fwkup|"))
def factory_workers_upgrade(call):
    owner_id = check_panel_owner(call)
    if owner_id is None:
        return
    factory = sync_factory_production(get_factory(owner_id))
    level = factory["workers_level"]
    if level >= FACTORY_MAX_LEVEL:
        bot.answer_callback_query(call.id, "🏆 سطح کارکنان به حداکثر ۱۰ رسیده است.", show_alert=True)
        render_workers_panel(call, owner_id, factory)
        return
    cost = factory_workers_upgrade_cost(level)
    if get_balance(owner_id) < cost:
        bot.answer_callback_query(call.id, "💎 موجودی کافی نیست!", show_alert=True)
        return
    update_diamonds(owner_id, -cost)
    try:
        supabase.table("factories").update({"workers_level": level + 1}).eq("user_id", owner_id).execute()
    except Exception as e:
        logging.error(f"خطا در ارتقای کارگران: {e}")
    bot.answer_callback_query(call.id, "✅ ارتقا انجام شد!")
    factory["workers_level"] = level + 1
    render_workers_panel(call, owner_id, factory)

# ---------- دستگاه حفاری ----------
def render_machine_panel(call, owner_id, factory):
    level = factory["machine_level"]
    drill = factory_drill_seconds(level)
    cost = factory_machine_upgrade_cost(level)
    next_drill = factory_drill_seconds(level + 1)
    markup = types.InlineKeyboardMarkup()
    if level < FACTORY_MAX_LEVEL:
        text = (
            "🖨 دستگاه حفاری\n\n"
            f"⭐️ سطح فعلی: {level}\n"
            f"⏳ زمان در آوردن هر الماس: {drill:.1f} ثانیه\n\n"
            f"⬆️ هزینه ارتقا به سطح {level + 1}: {cost:,} 💎\n"
            f"⏳ زمان جدید بعد از ارتقا: {next_drill:.1f} ثانیه"
        )
        markup.add(colored_button(f"⬆️ ارتقا ({cost:,} 💎)", callback_data=f"fmcup|{owner_id}"))
    else:
        text = (
            "🖨 دستگاه حفاری\n\n"
            f"⭐️ سطح فعلی: {level} (حداکثر)\n"
            f"⏳ زمان در آوردن هر الماس: {drill:.1f} ثانیه\n\n"
            "🏆 دستگاه به حداکثر سطح رسیده است."
        )
    markup.add(colored_button("🔙 بازگشت", callback_data=f"fback|{owner_id}"))
    safe_edit_message(text, call.message.chat.id, call.message.message_id, reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data.startswith("fmachine|"))
def factory_machine_panel(call):
    owner_id = check_panel_owner(call)
    if owner_id is None:
        return
    bot.answer_callback_query(call.id)
    render_machine_panel(call, owner_id, sync_factory_production(get_factory(owner_id)))

@bot.callback_query_handler(func=lambda call: call.data.startswith("fmcup|"))
def factory_machine_upgrade(call):
    owner_id = check_panel_owner(call)
    if owner_id is None:
        return
    factory = sync_factory_production(get_factory(owner_id))
    level = factory["machine_level"]
    if level >= FACTORY_MAX_LEVEL:
        bot.answer_callback_query(call.id, "🏆 دستگاه به حداکثر سطح ۱۰ رسیده است.", show_alert=True)
        render_machine_panel(call, owner_id, factory)
        return
    cost = factory_machine_upgrade_cost(level)
    if get_balance(owner_id) < cost:
        bot.answer_callback_query(call.id, "💎 موجودی کافی نیست!", show_alert=True)
        return
    update_diamonds(owner_id, -cost)
    try:
        supabase.table("factories").update({"machine_level": level + 1}).eq("user_id", owner_id).execute()
    except Exception as e:
        logging.error(f"خطا در ارتقای دستگاه: {e}")
    bot.answer_callback_query(call.id, "✅ ارتقا انجام شد!")
    factory["machine_level"] = level + 1
    render_machine_panel(call, owner_id, factory)

@bot.callback_query_handler(func=lambda call: call.data.startswith("ccustom|"))
def casino_custom_amount_prompt(call):
    owner_id = check_panel_owner(call)
    if owner_id is None:
        return
    game_key = call.data.split("|")[1]
    if not get_user(owner_id):
        bot.answer_callback_query(call.id, "اول /start بزن.", show_alert=True)
        return
    bot.answer_callback_query(call.id)
    safe_edit_message(
        "✏️ لطفاً مبلغ شرط رو به عدد بفرست (مثلاً 250 یا 250k):",
        chat_id=call.message.chat.id, message_id=call.message.message_id, reply_markup=None
    )
    register_timed_next_step_handler(call.message, casino_custom_amount_step, game_key, owner_id, call.message.message_id, expected_user_id=owner_id)

def casino_custom_amount_step(message, game_key, expected_user_id, panel_msg_id):
    if message.from_user.id != expected_user_id:
        register_timed_next_step_handler(message, casino_custom_amount_step, game_key, expected_user_id, panel_msg_id, expected_user_id=expected_user_id)
        return
    if not require_reply_to_panel(message, panel_msg_id, "برای ثبت مبلغ، روی همین پیام کازینو ریپلای کن و مبلغ را بفرست."):
        register_timed_next_step_handler(message, casino_custom_amount_step, game_key, expected_user_id, panel_msg_id, expected_user_id=expected_user_id)
        return

    amount = parse_amount(message.text)
    if amount is None:
        safe_edit_message("❌ مبلغ نامعتبره. روی همین پنل ریپلای کن و مبلغ درست بفرست؛ مثال: 250 یا 250k", message.chat.id, panel_msg_id, reply_markup=None)
        register_timed_next_step_handler(message, casino_custom_amount_step, game_key, expected_user_id, panel_msg_id, expected_user_id=expected_user_id)
        return

    if amount <= 0:
        safe_edit_message("❌ مبلغ باید بزرگتر از صفر باشه. روی همین پنل ریپلای کن و دوباره بفرست:", message.chat.id, panel_msg_id, reply_markup=None)
        register_timed_next_step_handler(message, casino_custom_amount_step, game_key, expected_user_id, panel_msg_id, expected_user_id=expected_user_id)
        return

    user = message.from_user
    if get_balance(user.id) < amount:
        safe_edit_message("💎 موجودی الماس شما کافی نیست!", message.chat.id, panel_msg_id, reply_markup=None)
        return

    update_diamonds(user.id, -amount)

    markup = types.InlineKeyboardMarkup()
    markup.row(
        colored_button("لغو ⊗", callback_data=f"ccancel|{panel_msg_id}"),
        colored_button("پیوستن ✓", callback_data="cjoin"),
    )

    text = (
        f"◈ ━━━━━ 𝗕𝗲𝘁 ━━━━━━ ◈\n"
        f"☻ | بازی : {CASINO_GAME_NAMES[game_key]}\n\n"
        f"$ | مقدار الماس : {amount}\n"
        f"♛ | سازنده : {display_name_with_tag(user.id, get_display_name(user))}\n"
        f"◈ ━━━━━ 𝗕𝗲𝘁 ━━━━━━ ◈"
    )
    try:
        bot.delete_message(message.chat.id, message.message_id)
    except Exception:
        pass
    safe_edit_message(text, chat_id=message.chat.id, message_id=panel_msg_id, reply_markup=markup)
    msg_id = panel_msg_id

    with casino_lock:
        active_casino_games[msg_id] = {
            "game": game_key,
            "bet": amount,
            "chat_id": message.chat.id,
            "player1": {"id": user.id, "name": get_display_name(user)},
            "player2": None,
            "score1": None,
            "score2": None,
            "vs_bot": False,
        }
        timer = threading.Timer(JOIN_TIMEOUT_SECONDS, check_casino_timeout, args=[msg_id])
        casino_timers[msg_id] = timer
        timer.start()

@bot.callback_query_handler(func=lambda call: call.data == "cjoin")
def casino_join(call):
    msg_id = call.message.message_id
    with casino_lock:
        game = active_casino_games.get(msg_id)
        if not game:
            bot.answer_callback_query(call.id, "این بازی دیگه معتبر نیست.", show_alert=True)
            return
        if game["player2"] is not None:
            bot.answer_callback_query(call.id, "بازی قبلاً پر شده.", show_alert=True)
            return

        user = call.from_user
        if user.id == game["player1"]["id"]:
            bot.answer_callback_query(call.id, "نمی‌تونی با خودت بازی کنی!", show_alert=True)
            return
        if not get_user(user.id):
            bot.answer_callback_query(call.id, "اول /start بزن.", show_alert=True)
            return
        if get_balance(user.id) < game["bet"]:
            bot.answer_callback_query(call.id, "💎 موجودی الماس شما کافی نیست!", show_alert=True)
            return

        reserved = update_diamonds(user.id, -game["bet"])
        if reserved is None:
            bot.answer_callback_query(call.id, "💎 رزرو مبلغ شرط انجام نشد.", show_alert=True)
            return
        game["player2"] = {"id": user.id, "name": get_display_name(user)}
        if msg_id in casino_timers:
            casino_timers[msg_id].cancel()
            del casino_timers[msg_id]

    bot.answer_callback_query(call.id)
    emoji = CASINO_GAMES[game["game"]]
    markup = types.InlineKeyboardMarkup()
    markup.add(colored_button("🎰 بازگشت به کازینو", callback_data="casinoback"))
    game_name = CASINO_GAME_NAMES[game["game"]]
    safe_edit_message(
        f"◈ ━━━━━ 𝗕𝗲𝘁 ━━━━━━ ◈\n"
        f"☻ | بازی: {game_name}\n\n"
        f"$ | مقدار الماس : {game['bet']}\n"
        f"♛ | سازنده : {casino_name_with_tag(game['player1'])}\n"
        f"♔ | شرکت کننده : {casino_name_with_tag(game['player2'])}\n\n"
        f"⌲ | {game_name} های خودتون رو ارسال کنید.\n"
        f"◈ ━━━━━ 𝗕𝗲𝘁 ━━━━━━ ◈",
        chat_id=game["chat_id"], message_id=msg_id, reply_markup=markup
    )

@bot.message_handler(content_types=["dice"])
def handle_dice_throw(message):
    to_finalize = None
    bot_throw_needed = None

    with casino_lock:
        for msg_id, game in active_casino_games.items():
            if game["chat_id"] != message.chat.id or game["player2"] is None:
                continue
            emoji = CASINO_GAMES[game["game"]]
            if message.dice.emoji != emoji:
                continue

            # تاس/دارت/بسکتبال/فوتبال/بولینگ/اسلات فقط با ریپلای مستقیم
            # به همان پیام پنل بازی ثبت می‌شود. پیام عادی کاملاً نادیده گرفته می‌شود.
            reply = getattr(message, "reply_to_message", None)
            if not reply or reply.message_id != msg_id:
                continue
            reply_sender = getattr(reply, "from_user", None)
            if not reply_sender or not getattr(reply_sender, "is_bot", False):
                continue

            user_id = message.from_user.id
            vs_bot = game.get("vs_bot", False)

            if user_id == game["player1"]["id"] and game["score1"] is None:
                game["score1"] = message.dice.value
            elif (not vs_bot) and user_id == game["player2"]["id"] and game["score2"] is None:
                game["score2"] = message.dice.value
            else:
                continue

            if vs_bot and game["score1"] is not None and game["score2"] is None:
                bot_throw_needed = (msg_id, game["chat_id"], emoji)
            elif game["score1"] is not None and game["score2"] is not None:
                to_finalize = msg_id
            break

    if bot_throw_needed:
        b_msg_id, b_chat_id, b_emoji = bot_throw_needed
        bot_dice = bot.send_dice(b_chat_id, emoji=b_emoji)
        with casino_lock:
            game = active_casino_games.get(b_msg_id)
            if game and game["score2"] is None:
                game["score2"] = bot_dice.dice.value
                if game["score1"] is not None and game["score2"] is not None:
                    to_finalize = b_msg_id

    if to_finalize:
        finalize_casino_game(to_finalize)

def finalize_casino_game(msg_id):
    with casino_lock:
        game = active_casino_games.pop(msg_id, None)
        if msg_id in casino_timers:
            casino_timers[msg_id].cancel()
            del casino_timers[msg_id]
    if not game:
        return

    emoji = CASINO_GAMES[game["game"]]
    chat_id = game["chat_id"]
    player1, player2 = game["player1"], game["player2"]
    score1, score2 = game["score1"], game["score2"]
    bet = game["bet"]
    vs_bot = game.get("vs_bot", False)

    score1 = score1 if score1 is not None else 0
    score2 = score2 if score2 is not None else 0
    result_markup = None

    if score1 == score2:
        if ATOMIC_DB_MODE:
            draw_ids = [int(player1["id"])] if vs_bot else [int(player1["id"]), int(player2["id"])]
            try:
                supabase.rpc("atomic_casino_settle", {
                    "p_winner_id": int(player1["id"]),
                    "p_pool": int(bet if vs_bot else bet * 2),
                    "p_tax": 0,
                    "p_loan_repay": 0,
                    "p_tax_receiver_id": None,
                    "p_draw_user_ids": draw_ids,
                }).execute()
            except Exception as e:
                logging.error(f"خطا در settlement مساوی کازینو {msg_id}: {e}")
                return
        else:
            update_diamonds(player1["id"], bet)
            if not vs_bot:
                update_diamonds(player2["id"], bet)
        p1_display = casino_name_with_tag(player1)
        p2_display = casino_name_with_tag(player2)
        result_text = (
            f"{emoji} شرط تموم شد!\n"
            f"💎 مبلغ: {bet}\n"
            f"⚔️ {p1_display} در برابر {p2_display}\n\n"
            f"🤝 مساوی شد!\n"
            f"امتیاز {p1_display} : {score1}\n"
            f"امتیاز {p2_display} : {score2}\n\n"
            f"💰 مبلغ به {'سازنده' if vs_bot else 'هر دو نفر'} برگشت داده شد."
        )
    else:
        if score1 > score2:
            winner, loser, w_score, l_score = player1, player2, score1, score2
        else:
            winner, loser, w_score, l_score = player2, player1, score2, score1

        total_pot = bet if vs_bot else bet * 2
        winner_id = winner["id"]

        if winner_id is not None:
            final_amount, tax, loan_repay, tax_rate_used, loan_rate_used = calculate_payout(winner_id, total_pot, context="casino")
            if ATOMIC_DB_MODE:
                try:
                    result = supabase.rpc("atomic_casino_settle", {
                        "p_winner_id": int(winner_id),
                        "p_pool": int(total_pot),
                        "p_tax": int(tax),
                        "p_loan_repay": int(loan_repay),
                        "p_tax_receiver_id": int(TAX_RECEIVER_ID) if get_user(TAX_RECEIVER_ID) else None,
                        "p_draw_user_ids": None,
                    }).execute().data
                    if not result:
                        raise RuntimeError("empty casino settlement")
                    row = result[0] if isinstance(result, list) else result
                    final_amount = int(row.get("payout", final_amount) or 0)
                    tax = int(row.get("tax", tax) or 0)
                    loan_repay = int(row.get("loan_repay", loan_repay) or 0)
                except Exception as e:
                    logging.error(f"خطا در settlement اتمیک کازینو {msg_id}: {e}")
                    return
            else:
                update_diamonds(winner_id, final_amount)
                if get_user(TAX_RECEIVER_ID):
                    update_diamonds(TAX_RECEIVER_ID, tax)
            if get_user(winner_id):
                register_casino_win(winner_id, chat_id, winner["name"], amount_won=final_amount)
        else:
            final_amount = None
            loan_repay = 0
            tax = int(total_pot * TAX_RATE)
            tax_rate_used = TAX_RATE
            loan_rate_used = LOAN_TAX_RATE

        extra_line = f"💳 کسر بابت وام ({int(loan_rate_used*100)}٪): {loan_repay}\n" if loan_repay > 0 else ""
        p1_display = casino_name_with_tag(player1)
        p2_display = casino_name_with_tag(player2)
        winner_display = casino_name_with_tag(winner)
        loser_display = casino_name_with_tag(loser)
        result_text = (
            f"◈ ━━━━━ 𝗕𝗲𝘁 ━━━━━━ ◈\n"
            f"✓ بازی تموم شد\n\n"
            f"⎌ | {p1_display} در برابر {p2_display}\n\n"
            f"♛ | برنده با {w_score} امتیاز : {winner_display}\n"
            f"⏣ | بازنده با {l_score} امتیاز : {loser_display}\n"
            f"{extra_line}"
            f"◈ ━━━━━ 𝗕𝗲𝘁 ━━━━━━ ◈"
        )
        result_markup = types.InlineKeyboardMarkup()
        win_amount = final_amount if final_amount is not None else 0
        result_markup.row(colored_button(f"$ مبلغ برد : {win_amount:,}", callback_data="bet_result_noop"))
        result_markup.row(colored_button(f"⊗ مالیات : {tax:,}", callback_data="bet_result_noop"))

    safe_edit_message(result_text, chat_id=chat_id, message_id=msg_id, reply_markup=result_markup)

def _spin_user(user_id):
    """چرخاندن اتمیک‌تر گردونه در یک process؛ بین دو کلیک همزمان فقط یکی برنده می‌شود."""
    with spin_lock:
        now = int(time.time())
        cooldown = SPIN_COOLDOWN_HOURS * 3600
        elapsed = now - int(get_last_spin(user_id) or 0)
        if elapsed < cooldown:
            return None, cooldown - elapsed
        won = random.randint(SPIN_MIN, SPIN_MAX)
        if ATOMIC_DB_MODE:
            result = supabase.rpc("atomic_spin", {
                "p_user_id": int(user_id),
                "p_now": int(now),
                "p_cooldown_seconds": int(cooldown),
                "p_reward": int(won),
            }).execute().data
            if not result:
                return None, cooldown
            row = result[0] if isinstance(result, list) else result
            if not row.get("ok", False):
                return None, int(row.get("remaining", cooldown))
            won = int(row.get("reward", won))
        else:
            update_diamonds(user_id, won)
            set_last_spin(user_id, now)
        return won, 0

@bot.message_handler(func=lambda m: text_is(m, "گردونه", "گردونه الماس"))
def text_spin(message):
    uid=message.from_user.id
    if not get_user(uid): bot.reply_to(message,"اول /start بزن."); return
    won, remaining = _spin_user(uid)
    if won is None:
        show_or_edit_panel(message, uid, "spin", f"⏳ گردونه آماده نیست. {remaining//3600} ساعت و {(remaining%3600)//60} دقیقه مونده.", None); return
    register_daily_gift(uid,message.chat.id,get_display_name(message.from_user))
    show_or_edit_panel(message, uid, "spin", f"🎡 گردونه چرخید!\n💎 تبریک، {won:,} الماس بردی!\n💰 موجودی جدید: {get_balance(uid):,} 💎", None)

@bot.message_handler(func=lambda m: text_is(m, "جام ها", "جام‌ها", "جام های من", "جام‌های من"))
def text_trophies(message):
    uid=message.from_user.id
    if not get_user(uid): bot.reply_to(message,"اول /start بزن."); return
    show_or_edit_panel(message, uid, "trophies", trophies_text_for_user(uid), None)

@bot.message_handler(func=lambda m: text_is(m, "تورنومنت", "تورنامنت"))
def text_tournament(message):
    t=get_active_tournament()
    if not t:
        show_or_edit_panel(message, message.from_user.id, "tournament", "🏆 هیچ تورنومنتی فعال نیست.\nلطفاً بعداً مراجعه کنید.", None); return
    tid=t["tournament_id"]; ranking=get_tournament_ranking(tid,limit=10); prizes=t["prizes"]; text="🏆 تورنومنت ربات شرط‌بندی\n\n"
    if ranking:
        text+="🔹 رتبه‌بندی فعلی:\n"
        for idx,(uid,votes) in enumerate(ranking,1):
            u=get_user(uid) or {}; name=display_name_with_tag(uid,u.get("username") or f"کاربر {uid}"); text+=f"{rank_number_emoji(idx)} {name} — {votes} رأی\n"
    else: text+="هنوز رأی‌ای ثبت نشده است.\n"
    if prizes:
        text+="\n🎁 جوایز:\n"
        for rank in range(1,11):
            prize=prizes.get(str(rank),0)
            if prize>0: text+=f"نفر {rank}: {prize:,} 💎\n"
    show_or_edit_panel(message, message.from_user.id, "tournament", text, None)

# ================== لیدربرد جهانی میویی ==================
RANK_PAGE_SIZE = 5

def _rank_rows():
    try:
        response = (
            supabase.table("users")
            .select("user_id, username, diamonds")
            .order("diamonds", desc=True)
            .execute()
        )
        return response.data or []
    except Exception as e:
        logging.error(f"خطا در دریافت لیدربرد: {e}")
        return []

def _rank_name(row):
    # ستون username در این بات همان نام اکانت ذخیره‌شده است؛
    # عمداً یوزرنیم تلگرام نمایش داده نمی‌شود.
    return (row.get("username") or f"کاربر {row.get('user_id', '')}").strip()

def _user_global_rank(user_id, rows=None):
    rows = rows if rows is not None else _rank_rows()
    for idx, row in enumerate(rows, 1):
        if int(row.get("user_id", 0)) == int(user_id):
            return idx
    return "نامشخص"

def _rank_number_emoji(n):
    nums = {
        1:"🥇", 2:"🥈", 3:"🥉", 4:"🎖", 5:"🏅",
        6:"6️⃣", 7:"7️⃣", 8:"8️⃣", 9:"9️⃣",
        10:"🔟", 11:"1️⃣1️⃣", 12:"1️⃣2️⃣", 13:"1️⃣3️⃣",
        14:"1️⃣4️⃣", 15:"1️⃣5️⃣"
    }
    return nums.get(n, f"{n}️⃣")

def _rank_page_text(page, user_id):
    rows = _rank_rows()
    total = len(rows)
    start = (page - 1) * RANK_PAGE_SIZE
    page_rows = rows[start:start + RANK_PAGE_SIZE]

    title = (
        "🏆 رتبه بندی جهانی 💎\n\n"
        "💎 رتبه بندی : ثروتمند ترین الماس یاب ها با بیشترین الماس\n\n"
    )

    labels = {
        1: "پادشاه الماس یاب ها",
        2: "سرور الماس یاب ها",
        3: "وزیرالماس یاب ها",
        4: "الماس یاب برتر",
        5: "الماس یاب برتر",
    }

    text = title
    for idx, row in enumerate(page_rows, start + 1):
        name = _rank_name(row)
        diamonds = int(row.get("diamonds") or 0)
        if idx <= 5:
            text += f"{_rank_number_emoji(idx)} {labels[idx]} : {name} 🏆\n"
        else:
            text += f"{_rank_number_emoji(idx)} الماس یاب : {name}\n"
        text += f"┘─ 💰 الماس ها : {diamonds:,} 💎\n\n"

    my_rank = _user_global_rank(user_id, rows)
    text += f"🎖️ رتبه شما : {my_rank}"
    return text, total

def _rank_markup(page, total, user_id):
    markup = types.InlineKeyboardMarkup()
    max_page = max(1, (total + RANK_PAGE_SIZE - 1) // RANK_PAGE_SIZE)

    if page < max_page:
        markup.row(
            colored_button(
                "بعدی ➡️",
                callback_data=f"rankpage|{page + 1}|{user_id}"
            )
        )
    if page > 1:
        markup.row(
            colored_button(
                "⬅️ برگشت",
                callback_data=f"rankpage|{page - 1}|{user_id}"
            )
        )
    return markup

def _send_rank(message):
    rows = _rank_rows()
    if not rows:
        show_or_edit_panel(message, message.from_user.id, "rank", "هنوز کاربری ثبت‌نام نکرده.", None)
        return
    text, total = _rank_page_text(1, message.from_user.id)
    show_or_edit_panel(message, message.from_user.id, "rank", text, _rank_markup(1, total, message.from_user.id))

@bot.message_handler(commands=["rank", "رتبه‌بندی"])
def cmd_rank(message):
    _send_rank(message)

@bot.message_handler(func=lambda m: text_is(m, "رنک", "رتبه بندی", "رتبه‌بندی"))
def text_rank(message):
    _send_rank(message)

@bot.callback_query_handler(func=lambda call: call.data.startswith("rankpage|"))
def rank_page_callback(call):
    try:
        _, page_s, owner_s = call.data.split("|", 2)
        page = max(1, int(page_s))
        owner_id = int(owner_s)
    except Exception:
        bot.answer_callback_query(call.id, "صفحه نامعتبر است.", show_alert=True)
        return

    if call.from_user.id != owner_id:
        bot.answer_callback_query(call.id, "این پنل برای شخص دیگری است.", show_alert=True)
        return

    bot.answer_callback_query(call.id)
    text, total = _rank_page_text(page, owner_id)
    safe_edit_message(
        text,
        call.message.chat.id,
        call.message.message_id,
        reply_markup=_rank_markup(page, total, owner_id)
    )

# ================== موجودی ==================
@bot.message_handler(commands=["balance", "موجودی"])
def cmd_balance(message):
    show_balance(message)

@bot.message_handler(func=lambda m: text_is(m, "موجودی"))
def text_balance(message):
    show_balance(message)

def show_balance(message):
    user_id = message.from_user.id
    if not get_user(user_id):
        bot.reply_to(message, "اول باید یه‌بار /start بزنی (توی پیوی بات).")
        return

    if message.reply_to_message:
        target_id = message.reply_to_message.from_user.id
        if not get_user(target_id):
            bot.reply_to(message, "این کاربر هنوز /start نزده، نمی‌تونم موجودیش رو ببینم.")
            return
        target_name = get_display_name(message.reply_to_message.from_user)
        balance = get_balance(target_id)
        text = f"💎 موجودی الماس {target_name}"
        markup = types.InlineKeyboardMarkup()
        markup.add(colored_button(f"💎 {balance}", callback_data="pending"))
        show_or_edit_panel(message, user_id, "balance", text, markup)
    else:
        balance = get_balance(user_id)
        text = "$ | موجودی الماس شما"
        markup = types.InlineKeyboardMarkup()
        markup.add(colored_button(f"💎 {balance}", callback_data="pending"))
        show_or_edit_panel(message, user_id, "balance", text, markup)

# ================== بخش تورنومنت ==================
@bot.callback_query_handler(func=lambda call: call.data == "tournament_menu" or call.data.startswith("tournament_menu|"))
def tournament_menu(call):
    if "|" in call.data:
        user_id = check_panel_owner(call)
        if user_id is None:
            return
    else:
        user_id = call.from_user.id
    bot.answer_callback_query(call.id)
    if not get_user(user_id):
        bot.send_message(call.message.chat.id, "اول /start بزن.")
        return

    tournament = get_active_tournament()
    if not tournament:
        text = "🏆 هیچ تورنومنتی فعال نیست.\nلطفاً بعداً مراجعه کنید."
        safe_edit_message(text, call.message.chat.id, call.message.message_id, reply_markup=None)
        return

    tournament_id = tournament['tournament_id']
    prizes = tournament['prizes']  # json

    # دریافت رتبه‌بندی
    ranking = get_tournament_ranking(tournament_id, limit=10)
    text = "🏆 تورنومنت ربات شرطبندی\n\n"
    if ranking:
        text += "🔹 رتبه‌بندی فعلی:\n"
        for idx, (uid, votes) in enumerate(ranking, 1):
            user_info = get_user(uid)
            name = user_info['username'] if user_info and user_info['username'] else f"کاربر {uid}"
            text += f"{rank_number_emoji(idx)} {name} — {votes} رأی\n"
    else:
        text += "هنوز رأی‌ای ثبت نشده است.\n"

    # نمایش جوایز
    if prizes:
        text += "\n🎁 جوایز:\n"
        for rank in range(1, 11):
            prize = prizes.get(str(rank), 0)
            if prize > 0:
                text += f"نفر {rank}: {prize} 💎\n"

    markup = types.InlineKeyboardMarkup()
    # نکته: دریافت کد فقط برای صاحب پنل قفله (owner embedded)، ولی ثبت رأی عمداً
    # باز می‌مونه چون هر کسی که این پیام رو می‌بینه باید بتونه با کد یه نفر دیگه رأی بده.
    markup.add(colored_button("📋 دریافت کد رأی", callback_data=f"getvote|{tournament_id}|{user_id}"))
    markup.add(colored_button("✍️ ثبت رأی", callback_data=f"submitvote|{tournament_id}"))
    safe_edit_message(text, call.message.chat.id, call.message.message_id, reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data.startswith("getvote|"))
def get_vote_code(call):
    owner_id = check_panel_owner(call)
    if owner_id is None:
        return
    bot.answer_callback_query(call.id)
    tournament_id = int(call.data.split("|")[1])
    user_id = owner_id
    code = get_user_code(tournament_id, user_id)
    if code:
        text = f"🔑 کد رأی شما برای این تورنومنت:\n`{code}`\n\nاین کد را با دوستان خود به اشتراک بگذارید تا به شما رأی دهند."
    else:
        text = "خطا در دریافت کد. لطفاً دوباره تلاش کنید."
    markup = types.InlineKeyboardMarkup()
    markup.add(colored_button("🔙 بازگشت", callback_data=f"tournament_menu|{owner_id}"))
    safe_edit_message(text, call.message.chat.id, call.message.message_id, reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data.startswith("submitvote|"))
def submit_vote_prompt(call):
    bot.answer_callback_query(call.id)
    tournament_id = int(call.data.split("|")[1])
    voter_id = call.from_user.id  # عمداً باز است: هر کسی که این پیام رو ببینه می‌تونه رأی بده
    text = "✍️ لطفاً کد رأی شخص مورد نظر را وارد کنید (۶ کاراکتر):"
    markup = types.InlineKeyboardMarkup()
    markup.add(colored_button("🔙 بازگشت", callback_data=f"tournament_menu|{voter_id}"))
    safe_edit_message(text, call.message.chat.id, call.message.message_id, reply_markup=markup)
    register_timed_next_step_handler(call.message, process_vote_code, tournament_id, voter_id, call.message.message_id, expected_user_id=voter_id)

def process_vote_code(message, tournament_id, voter_id, original_msg_id):
    if message.from_user.id != voter_id:
        return
    code = message.text.strip().lower()
    if len(code) != 6:
        bot.reply_to(message, "❌ کد باید دقیقاً ۶ کاراکتر باشد. دوباره تلاش کنید.")
        register_timed_next_step_handler(message, process_vote_code, tournament_id, voter_id, original_msg_id, expected_user_id=voter_id)
        return
    # ثبت رأی
    success, msg = add_vote(tournament_id, voter_id, code)
    if success:
        # حذف پیام ورودی و نمایش نتیجه در پیام اصلی
        try:
            bot.delete_message(message.chat.id, message.message_id)
        except:
            pass
        # ویرایش پیام اصلی
        markup = types.InlineKeyboardMarkup()
        markup.add(colored_button("🔙 بازگشت به تورنومنت", callback_data=f"tournament_menu|{voter_id}"))
        safe_edit_message(f"✅ رأی شما با موفقیت ثبت شد.\n{msg}", chat_id=message.chat.id, message_id=original_msg_id, reply_markup=markup)
    else:
        bot.reply_to(message, f"❌ {msg}\nلطفاً کد را دوباره وارد کنید:")
        register_timed_next_step_handler(message, process_vote_code, tournament_id, voter_id, original_msg_id, expected_user_id=voter_id)

# ================== بخش پنل مدیریت ==================
@bot.callback_query_handler(func=lambda call: call.data == "admin_panel" or call.data.startswith("admin_panel|"))
def admin_panel(call):
    if call.from_user.id not in ADMIN_IDS:
        bot.answer_callback_query(call.id, "⛔ دسترسی غیرمجاز", show_alert=True)
        return
    bot.answer_callback_query(call.id)
    owner_id = call.from_user.id
    text = "⚙️ پنل مدیریت\n\nلطفاً یکی از گزینه‌ها را انتخاب کنید:"
    markup = types.InlineKeyboardMarkup()
    markup.add(colored_button("🏆 شروع تورنومنت", callback_data="admin_start_tournament"))
    markup.add(colored_button("🏁 اتمام تورنومنت", callback_data="admin_end_tournament"))
    markup.add(colored_button("📢 پیام همگانی", callback_data="admin_broadcast"))
    markup.add(colored_button("➕ افزودن الماس به همه", callback_data="admin_add_diamond_all"))
    markup.add(colored_button("➖ کم کردن الماس از همه", callback_data="admin_remove_diamond_all"))
    markup.add(colored_button("🎁 ساخت کد هدیه", callback_data="admin_create_giftcode"))
    safe_edit_message(text, call.message.chat.id, call.message.message_id, reply_markup=markup)

@bot.message_handler(commands=["admin"])
def cmd_admin(message):
    if message.from_user.id not in ADMIN_IDS:
        bot.reply_to(message, "⛔ دسترسی غیرمجاز")
        return
    text = "⚙️ پنل مدیریت\n\nلطفاً یکی از گزینه‌ها را انتخاب کنید:"
    markup = types.InlineKeyboardMarkup()
    markup.add(colored_button("🏆 شروع تورنومنت", callback_data="admin_start_tournament"))
    markup.add(colored_button("🏁 اتمام تورنومنت", callback_data="admin_end_tournament"))
    markup.add(colored_button("📢 پیام همگانی", callback_data="admin_broadcast"))
    markup.add(colored_button("➕ افزودن الماس به همه", callback_data="admin_add_diamond_all"))
    markup.add(colored_button("➖ کم کردن الماس از همه", callback_data="admin_remove_diamond_all"))
    markup.add(colored_button("🎁 ساخت کد هدیه", callback_data="admin_create_giftcode"))
    bot.reply_to(message, text, reply_markup=markup)

@bot.message_handler(func=lambda m: text_is(m, "مدیریت"))
def text_admin(message):
    cmd_admin(message)

# ---------- شروع تورنومنت ----------
@bot.callback_query_handler(func=lambda call: call.data == "admin_start_tournament")
def admin_start_tournament(call):
    if call.from_user.id not in ADMIN_IDS:
        bot.answer_callback_query(call.id, "⛔ دسترسی غیرمجاز", show_alert=True)
        return
    bot.answer_callback_query(call.id)
    # بررسی وجود تورنومنت فعال
    active = get_active_tournament()
    if active:
        bot.send_message(call.message.chat.id, "⚠️ در حال حاضر یک تورنومنت فعال وجود دارد. ابتدا آن را پایان دهید.")
        return
    # شروع مراحل دریافت جوایز
    text = "🎯 لطفاً جایزه نفر اول را به عدد وارد کنید (یا 0 برای عدم جایزه):"
    safe_edit_message(text, call.message.chat.id, call.message.message_id, reply_markup=None)
    register_timed_next_step_handler(call.message, admin_set_prize_step, 1, {}, call.from_user.id, expected_user_id=call.from_user.id)  # step 1, prizes dict

# ========== اصلاح تابع شروع تورنومنت ==========
def admin_set_prize_step(message, rank, prizes, admin_id):
    if message.from_user.id not in ADMIN_IDS:
        return
    raw = (message.text or "").strip()
    amount = 0 if raw == "0" else parse_amount(raw)
    if amount is None:
        msg = bot.reply_to(message, "لطفاً یه مبلغ درست وارد کنید (مثلاً 1000 یا 1میل) یا 0 برای عدم جایزه:")
        register_timed_next_step_handler(msg, admin_set_prize_step, rank, prizes, admin_id, expected_user_id=admin_id)
        return
    prizes[str(rank)] = amount
    if rank < 10:
        next_rank = rank + 1
        text = f"جایزه نفر {next_rank} را وارد کنید (یا 0):"
        bot.reply_to(message, text)
        register_timed_next_step_handler(message, admin_set_prize_step, next_rank, prizes, admin_id, expected_user_id=admin_id)
    else:
        # همه جوایز دریافت شد، ایجاد تورنومنت
        try:
            # ذخیره به‌صورت دیکشنری (Supabase خودش به JSONB تبدیل می‌کند)
            supabase.table("tournaments").insert({
                "status": "active",
                "prizes": prizes   # ← اینجا دیگر json.dumps نمی‌زنیم
            }).execute()
            bot.reply_to(message, "✅ تورنومنت با موفقیت شروع شد! کاربران می‌توانند وارد بخش تورنومنت شوند.")
        except Exception as e:
            logging.error(f"خطا در شروع تورنومنت: {e}")
            bot.reply_to(message, f"❌ خطا در شروع تورنومنت: {e}")

# ---------- پایان تورنومنت ----------
@bot.callback_query_handler(func=lambda call: call.data == "admin_end_tournament")
def admin_end_tournament(call):
    if call.from_user.id not in ADMIN_IDS:
        bot.answer_callback_query(call.id, "⛔ دسترسی غیرمجاز", show_alert=True)
        return
    bot.answer_callback_query(call.id)
    tournament = get_active_tournament()
    if not tournament:
        bot.send_message(call.message.chat.id, "❌ هیچ تورنومنت فعالی وجود ندارد.")
        return
    tid = tournament['tournament_id']
    success, msg = end_tournament(tid)
    bot.send_message(call.message.chat.id, msg)
    if success:
        # ارسال پیام به همه کاربران (اختیاری)
        pass

# ---------- پیام همگانی ----------
@bot.callback_query_handler(func=lambda call: call.data == "admin_broadcast")
def admin_broadcast(call):
    if call.from_user.id not in ADMIN_IDS:
        bot.answer_callback_query(call.id, "⛔ دسترسی غیرمجاز", show_alert=True)
        return
    bot.answer_callback_query(call.id)
    text = "📢 لطفاً پیام همگانی خود را بنویسید (متن یا با فرمت HTML):"
    safe_edit_message(text, call.message.chat.id, call.message.message_id, reply_markup=None)
    register_timed_next_step_handler(call.message, admin_send_broadcast, expected_user_id=call.from_user.id)

def admin_send_broadcast(message):
    if message.from_user.id not in ADMIN_IDS:
        return
    broadcast_text = message.text
    # دریافت تمام کاربران
    try:
        users = supabase.table("users").select("user_id").execute()
        if not users.data:
            bot.reply_to(message, "هیچ کاربری یافت نشد.")
            return
        count = 0
        for user in users.data:
            try:
                bot.send_message(user['user_id'], broadcast_text)
                count += 1
                time.sleep(0.05)  # جلوگیری از محدودیت
            except Exception:
                continue
        bot.reply_to(message, f"✅ پیام به {count} کاربر ارسال شد.")
    except Exception as e:
        bot.reply_to(message, f"❌ خطا در ارسال پیام همگانی: {e}")

# ---------- افزودن الماس (مدیریت) ----------
@bot.callback_query_handler(func=lambda call: call.data == "admin_add_diamond")
def admin_add_diamond_prompt(call):
    if call.from_user.id not in ADMIN_IDS:
        bot.answer_callback_query(call.id, "⛔ دسترسی غیرمجاز", show_alert=True)
        return
    bot.answer_callback_query(call.id)
    text = "➕ لطفاً آیدی عددی کاربر و مقدار الماس را به صورت زیر وارد کنید:\n`<user_id> <amount>`\nمثال: `123456789 100`"
    safe_edit_message(text, call.message.chat.id, call.message.message_id, reply_markup=None)
    register_timed_next_step_handler(call.message, admin_add_diamond_execute, expected_user_id=call.from_user.id)

def admin_add_diamond_execute(message):
    if message.from_user.id not in ADMIN_IDS:
        return
    parts = message.text.split()
    amount = parse_amount(parts[1]) if len(parts) == 2 and parts[0].isdigit() else None
    if len(parts) != 2 or not parts[0].isdigit() or amount is None:
        bot.reply_to(message, "❌ فرمت نامعتبر. مجدداً تلاش کنید. مثال: 123456789 100 یا 123456789 100k")
        return
    user_id = int(parts[0])
    if not get_user(user_id):
        bot.reply_to(message, "کاربر یافت نشد.")
        return
    update_diamonds(user_id, amount)
    bot.reply_to(message, f"✅ {amount} الماس به کاربر {user_id} اضافه شد. موجودی جدید: {get_balance(user_id)}")

# ---------- کم کردن الماس (مدیریت) ----------
@bot.callback_query_handler(func=lambda call: call.data == "admin_remove_diamond")
def admin_remove_diamond_prompt(call):
    if call.from_user.id not in ADMIN_IDS:
        bot.answer_callback_query(call.id, "⛔ دسترسی غیرمجاز", show_alert=True)
        return
    bot.answer_callback_query(call.id)
    text = "➖ لطفاً آیدی عددی کاربر و مقدار الماس را به صورت زیر وارد کنید:\n`<user_id> <amount>`\nمثال: `123456789 50`"
    safe_edit_message(text, call.message.chat.id, call.message.message_id, reply_markup=None)
    register_timed_next_step_handler(call.message, admin_remove_diamond_execute, expected_user_id=call.from_user.id)

def admin_remove_diamond_execute(message):
    if message.from_user.id not in ADMIN_IDS:
        return
    parts = message.text.split()
    amount = parse_amount(parts[1]) if len(parts) == 2 and parts[0].isdigit() else None
    if len(parts) != 2 or not parts[0].isdigit() or amount is None:
        bot.reply_to(message, "❌ فرمت نامعتبر. مجدداً تلاش کنید. مثال: 123456789 50 یا 123456789 50k")
        return
    user_id = int(parts[0])
    if not get_user(user_id):
        bot.reply_to(message, "کاربر یافت نشد.")
        return
    balance = get_balance(user_id)
    deduct = min(amount, balance)
    update_diamonds(user_id, -deduct)
    bot.reply_to(message, f"✅ {deduct} الماس از کاربر {user_id} کم شد. موجودی جدید: {get_balance(user_id)}")

# ---------- افزودن الماس به همه کاربران (مدیریت) ----------
@bot.callback_query_handler(func=lambda call: call.data == "admin_add_diamond_all")
def admin_add_diamond_all_prompt(call):
    if call.from_user.id not in ADMIN_IDS:
        bot.answer_callback_query(call.id, "⛔ دسترسی غیرمجاز", show_alert=True)
        return
    bot.answer_callback_query(call.id)
    text = "➕ لطفاً مقدار الماسی که می‌خواهید به همه‌ی کاربران اضافه شود را وارد کنید:\nمثال: `100` یا `100k`"
    safe_edit_message(text, call.message.chat.id, call.message.message_id, reply_markup=None)
    register_timed_next_step_handler(call.message, admin_add_diamond_all_execute, expected_user_id=call.from_user.id)

def admin_add_diamond_all_execute(message):
    if message.from_user.id not in ADMIN_IDS:
        return
    amount = parse_amount(message.text.strip())
    if amount is None or amount <= 0:
        bot.reply_to(message, "❌ مقدار نامعتبر. یک عدد مثبت وارد کن. مثال: 100 یا 100k")
        return
    try:
        users = supabase.table("users").select("user_id, diamonds").execute()
        rows = users.data or []
    except Exception as e:
        logging.error(f"خطا در دریافت لیست کاربران برای افزودن الماس همگانی: {e}")
        bot.reply_to(message, "❌ خطا در دریافت لیست کاربران.")
        return
    count = 0
    for row in rows:
        try:
            new_balance = int(row.get("diamonds", 0) or 0) + amount
            supabase.table("users").update({"diamonds": new_balance}).eq("user_id", row["user_id"]).execute()
            count += 1
        except Exception as e:
            logging.error(f"خطا در افزودن الماس همگانی به {row.get('user_id')}: {e}")
            continue
    bot.reply_to(message, f"✅ {amount:,} 💎 به {count} کاربر اضافه شد.")

# ---------- کم کردن الماس از همه کاربران (مدیریت) ----------
@bot.callback_query_handler(func=lambda call: call.data == "admin_remove_diamond_all")
def admin_remove_diamond_all_prompt(call):
    if call.from_user.id not in ADMIN_IDS:
        bot.answer_callback_query(call.id, "⛔ دسترسی غیرمجاز", show_alert=True)
        return
    bot.answer_callback_query(call.id)
    text = (
        "➖ لطفاً مقدار الماسی که می‌خواهید از همه‌ی کاربران کم شود را وارد کنید:\n"
        "مثال: `50` یا `50k`\n"
        "(اگر موجودی کسی کمتر از این مقدار باشد، فقط تا صفر کم می‌شود.)"
    )
    safe_edit_message(text, call.message.chat.id, call.message.message_id, reply_markup=None)
    register_timed_next_step_handler(call.message, admin_remove_diamond_all_execute, expected_user_id=call.from_user.id)

def admin_remove_diamond_all_execute(message):
    if message.from_user.id not in ADMIN_IDS:
        return
    amount = parse_amount(message.text.strip())
    if amount is None or amount <= 0:
        bot.reply_to(message, "❌ مقدار نامعتبر. یک عدد مثبت وارد کن. مثال: 50 یا 50k")
        return
    try:
        users = supabase.table("users").select("user_id, diamonds").execute()
        rows = users.data or []
    except Exception as e:
        logging.error(f"خطا در دریافت لیست کاربران برای کم کردن الماس همگانی: {e}")
        bot.reply_to(message, "❌ خطا در دریافت لیست کاربران.")
        return
    count = 0
    for row in rows:
        try:
            balance = int(row.get("diamonds", 0) or 0)
            deduct = min(amount, balance)
            if deduct <= 0:
                continue
            new_balance = balance - deduct
            supabase.table("users").update({"diamonds": new_balance}).eq("user_id", row["user_id"]).execute()
            count += 1
        except Exception as e:
            logging.error(f"خطا در کم کردن الماس همگانی از {row.get('user_id')}: {e}")
            continue
    bot.reply_to(message, f"✅ حداکثر {amount:,} 💎 از {count} کاربر کم شد.")

# ---------- ساخت کد هدیه (مدیریت) ----------
@bot.callback_query_handler(func=lambda call: call.data == "admin_create_giftcode")
def admin_create_giftcode_prompt(call):
    if call.from_user.id not in ADMIN_IDS:
        bot.answer_callback_query(call.id, "⛔ دسترسی غیرمجاز", show_alert=True)
        return
    bot.answer_callback_query(call.id)
    text = "🎁 لطفاً مقدار جایزه‌ی هر کد هدیه را وارد کنید:\nمثال: `1000` یا `1میل`"
    safe_edit_message(text, call.message.chat.id, call.message.message_id, reply_markup=None)
    register_timed_next_step_handler(call.message, admin_giftcode_amount_step, expected_user_id=call.from_user.id)

def admin_giftcode_amount_step(message):
    if message.from_user.id not in ADMIN_IDS:
        return
    amount = parse_amount(message.text.strip() if message.text else "")
    if amount is None:
        msg = bot.reply_to(message, "❌ مقدار نامعتبر. یک عدد مثبت وارد کن. مثال: 1000 یا 1میل")
        register_timed_next_step_handler(msg, admin_giftcode_amount_step, expected_user_id=message.from_user.id)
        return
    msg = bot.reply_to(message, "👤 برای چند نفر قابل فعال‌سازی باشد؟\nمثال: 50")
    register_timed_next_step_handler(msg, admin_giftcode_capacity_step, amount, expected_user_id=message.from_user.id)

def admin_giftcode_capacity_step(message, amount):
    if message.from_user.id not in ADMIN_IDS:
        return
    capacity = parse_amount(message.text.strip() if message.text else "")
    if capacity is None:
        msg = bot.reply_to(message, "❌ عدد نامعتبر. یک عدد صحیح مثبت وارد کن. مثال: 50")
        register_timed_next_step_handler(msg, admin_giftcode_capacity_step, amount, expected_user_id=message.from_user.id)
        return
    code = create_gift_code(message.from_user.id, amount, capacity)
    if not code:
        bot.reply_to(message, "❌ خطا در ساخت کد هدیه. دوباره تلاش کنید.")
        return
    text = (
        "کد هدیه جدید ساخته شد.🎁\n\n"
        f"کد : `{code}`\n"
        f"جایزه : {amount:,} الماس💎\n"
        f"ظرفیت : {capacity:,} 👤"
    )
    bot.reply_to(message, text, parse_mode="Markdown")

# ---------- فعال‌سازی کد هدیه (توسط کاربران) ----------
_GIFT_CODE_PATTERN = re.compile(r"^[A-Z0-9]{8}$")

def _looks_like_gift_code(message):
    if not getattr(message, "text", None):
        return False
    if getattr(message, "from_user", None) is None or getattr(message.from_user, "is_bot", False):
        return False
    # اگر کاربر در وسط یک مرحله‌ی دیگر (مثلاً وارد کردن مبلغ بانک) است،
    # اولویت با همان مرحله است؛ کد هدیه را بررسی نمی‌کنیم.
    if _has_pending_step(message):
        return False
    text = message.text.strip().upper()
    return bool(_GIFT_CODE_PATTERN.match(text))

@bot.message_handler(func=_looks_like_gift_code)
def handle_gift_code_message(message):
    code = message.text.strip().upper()
    user_id = message.from_user.id
    if not get_user(user_id):
        create_user(user_id, get_display_name(message.from_user))
    success, msg, amount = redeem_gift_code(user_id, code)
    if success:
        bot.reply_to(message, f"کد هدیه ثبت شد😉\nجایزه شما {amount:,} الماس💎")
    elif msg:
        bot.reply_to(message, msg)
    # اگر msg هم None باشد یعنی اصلاً کدی با این متن وجود نداشته (پیام عادی
    # کاربر بوده)، پس هیچ پاسخی داده نمی‌شود.

# ================== مصرف‌کننده‌ی نهایی مراحل در انتظار ==================
# این هندلر باید آخرین @bot.message_handler ثبت‌شده در کل فایل باشد (به همین
# دلیل اینجا، درست قبل از بخش Webhook، قرار گرفته). چون TeleBot برای هر پیام
# فقط اولین هندلرِ منطبق را اجرا می‌کند، این هندلر فقط زمانی اجرا می‌شود که
# هیچ‌کدام از هندلرهای اختصاصی‌تر بالا (دستورات، عبارات متنی خاص و...) روی آن
# پیام match نشده باشند؛ یعنی دقیقاً برای پیام‌های «آزاد» مثل یک عدد ساده که
# قرار است مبلغ یک مرحله‌ی در انتظار (شرط، بانک، وام، کازینو و...) باشد.
def _has_pending_step(message):
    chat_id = getattr(getattr(message, "chat", None), "id", None)
    user_id = getattr(getattr(message, "from_user", None), "id", None)
    if chat_id is None or user_id is None:
        return False
    with _next_step_lock:
        return (chat_id, user_id) in _next_step_pending

@bot.message_handler(func=_has_pending_step)
def _pending_step_catch_all(message):
    _consume_pending_step(message)

# ================== Webhook ==================
@app.route("/", methods=["GET"])
def health_check():
    return "Bot is running!", 200

@app.route("/webhook", methods=["POST"])
def webhook():
    if TELEGRAM_WEBHOOK_SECRET:
        provided = request.headers.get("X-Telegram-Bot-Api-Secret-Token")
        if provided != TELEGRAM_WEBHOOK_SECRET:
            return "Forbidden", 403
    if request.is_json:
        json_str = request.get_data().decode("utf-8")
        update = telebot.types.Update.de_json(json_str)

        # اول خود آپدیت را به TeleBot بده تا هندلرهای کلمات و دکمه‌ها
        # بدون وابستگی به سیستم شمارش الماس اجرا شوند.
        # سیستم الماس گروه جداگانه بعد از آن اجرا می‌شود؛ بنابراین اگر
        # دیتابیس الماس کند/موقتاً مشکل‌دار باشد، کلمات بات از کار نمی‌افتند.
        incoming_message = getattr(update, "message", None)
        if incoming_message is not None and getattr(incoming_message, "text", None):
            # فقط برای پیام‌های متنی واقعیِ کاربر (نه callback دکمه‌ها) کانتکست
            # ریپلای رو ست می‌کنیم تا پیام‌های جدیدِ بات به همین پیام ریپلای بزنن.
            _reply_ctx.chat_id = incoming_message.chat.id
            _reply_ctx.message_id = incoming_message.message_id
        else:
            _reply_ctx.chat_id = None
            _reply_ctx.message_id = None
        try:
            bot.process_new_updates([update])
        finally:
            _reply_ctx.chat_id = None
            _reply_ctx.message_id = None

        # همه پیام‌های معمولی تلگرام که در فیلد message می‌آیند شمارش می‌شوند.
        # از جمله متن، عکس، ویدیو، استیکر، گیف، صدا، ویس، فایل، لوکیشن،
        # مخاطب، دایس و پیام‌های سرویس.
        if incoming_message is not None:
            try:
                process_group_message_for_diamond_hunt(incoming_message)
            except Exception as e:
                logging.error(
                    f"خطا در شمارش پیام گروه برای الماس: {e}"
                )

        return "", 200
    return "", 403

# ================== اجرا ==================
if __name__ == "__main__":
    WEBHOOK_URL = "https://bet-bot-e1c2.onrender.com/webhook"  # آدرس خود را جایگزین کنید
    bot.remove_webhook()
    bot.set_webhook(
        url=WEBHOOK_URL,
        allowed_updates=["message", "callback_query", "my_chat_member"]
    )
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, threaded=True)
