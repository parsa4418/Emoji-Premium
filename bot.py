# -*- coding: utf-8 -*-
"""
بات شرط‌بندی الماس با Webhook - نسخه Supabase (کامل)
اضافه شده: پنل مدیریت، رفع باگ شرط
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

    icon_custom_emoji_id: در صورت پاس‌دادن، آیدی ایموجی سفارشی/پرمیومی که باید
    قبل از متن دکمه نمایش داده شود (فیلد رسمی Bot API 9.4، icon_custom_emoji_id).
    توجه: طبق مستندات تلگرام این فیلد فقط زمانی روی کلاینت واقعاً رندر می‌شود که
    مالک بات (اکانتی که از طریق BotFather بات رو ساخته) اشتراک Telegram Premium
    داشته باشد؛ در غیر این صورت تلگرام این فیلد را نادیده می‌گیرد و فقط متن دکمه دیده می‌شود.
    """
    icon_emoji_id = kwargs.pop("icon_custom_emoji_id", None)

    if "style" in kwargs:
        button = types.InlineKeyboardButton(*args, **kwargs)
    else:
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
        except TypeError:
            # اگر نسخه قدیمی کتابخانه style را در سازنده قبول نکند، دکمه عادی ساخته می‌شود.
            # (برای فعال شدن رنگ‌ها، کتابخانه باید نسخه‌ای با پشتیبانی style داشته باشد.)
            button = types.InlineKeyboardButton(*args, **kwargs)

    if icon_emoji_id is not None:
        try:
            setattr(button, "icon_custom_emoji_id", str(icon_emoji_id))
        except Exception:
            pass

    return button


BACK_EMOJI_ID = "5832364184066614283"


def back_button(callback_data):
    """دکمه‌ی یکسان «بازگشت»: فقط ایموجی پرمیوم، بدون متن قابل‌دیدن.
    تلگرام متن خالی قبول نمی‌کند، پس یک کاراکتر نامرئی (Braille blank) می‌گذاریم."""
    button = colored_button("\u2800", callback_data=callback_data, icon_custom_emoji_id=BACK_EMOJI_ID)
    # رنگ قرمز قبلی (هم‌رنگ دکمه‌های «بازگشت» قدیمی) حفظ شود
    setattr(button, "style", "danger")
    return button


load_dotenv()

# ================== تنظیمات ==================
BOT_TOKEN = os.environ.get("BOT_TOKEN", "توکن-خودت-رو-اینجا-بذار")
ADMIN_IDS = [8904869158, 8196150649,]  # آیدی عددی خود را اینجا قرار دهید
START_DIAMONDS = 25000
TAX_RATE = 0.10
TAX_RECEIVER_ID = ADMIN_IDS[0]
JOIN_TIMEOUT_SECONDS = 60

# ================== جواهری / انگشترسازی ==================
# هر الماس انگشتر هنگام پیدا شدن به‌صورت شانسی به یکی از این سنگ‌ها تبدیل می‌شود.
JEWELRY_GEMS = {
    "agate":      {"name": "عقیق",       "emoji": "🔴", "tier": "🟢 معمولی",   "price": 500},
    "turquoise":  {"name": "فیروزه",     "emoji": "🩵", "tier": "🟢 معمولی",   "price": 500},
    "amethyst":   {"name": "آمیتیست",    "emoji": "🟣", "tier": "🔵 کمیاب",    "price": 1_500},
    "garnet":     {"name": "گارنت",      "emoji": "❤️", "tier": "🔵 کمیاب",    "price": 1_500},
    "sapphire":   {"name": "یاقوت کبود", "emoji": "🔵", "tier": "🟣 حماسی",    "price": 4_000},
    "emerald":    {"name": "زمرد",       "emoji": "💚", "tier": "🟣 حماسی",    "price": 4_000},
    "ruby":       {"name": "یاقوت سرخ",  "emoji": "❤️", "tier": "🟣 حماسی",    "price": 4_000},
    "diamond":    {"name": "الماس",      "emoji": "💎", "tier": "🔴 افسانه‌ای", "price": 10_000},
}
# احتمال رده‌ها: معمولی 50٪، کمیاب 30٪، حماسی 15٪، افسانه‌ای 5٪
JEWELRY_TIER_WEIGHTS = [("common", 50), ("rare", 30), ("epic", 15), ("legendary", 5)]
JEWELRY_TIER_GEMS = {
    "common": ["agate", "turquoise"],
    "rare": ["amethyst", "garnet"],
    "epic": ["sapphire", "emerald", "ruby"],
    "legendary": ["diamond"],
}
JEWELRY_WORK_SECONDS = 90 * 60


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

XP_PER_BET_WIN = 10
XP_PER_CASINO_WIN = 15
XP_PER_RING_DIAMOND = 50
XP_PER_DAILY_GIFT = 5
XP_BONUS_PER_CASINO_100K = 1     # هر ۱۰۰,۰۰۰ الماس برد در کازینو ۱ XP اضافه
XP_BONUS_CASINO_CAP = 50

# ================== لقب‌های ویژه (جعبه شانس حذف شد؛ لقب‌ها نگه داشته شده‌اند) ==================
LOOTBOX_TAGS = ["🗣️ خوشتیپ", "🗿 کصخل", "🎲 قمارباز", "🤌 بچه مثبت", "💰 بچه پولدار", "❤️ عشق", "😍 خوشگله", "🧑‍🦯 بچه روبیکایی", "🤓 نمک"]

# ================== تنظیمات پیش‌فرض اعلان‌های گروه ==================
NOTIFY_DEFAULTS = {
    "level_up": True,
    "new_diamond": True,
    "daily_gift": False,
    "diamond_timer": True,
    "betting": False,
}
NOTIFY_LABELS = {
    "level_up": "🏆 ارتقا سطح",
    "new_diamond": "💎 الماس جدید",
    "daily_gift": "🎁 هدیه روزانه",
    "diamond_timer": "⏰ تایمر الماس",
    "betting": "🎲 شرط‌بندی",
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
    if isinstance(text, str) and "<tg-emoji" in text and kwargs.get("parse_mode") is None:
        kwargs["parse_mode"] = "HTML"
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
        colored_button("بله", callback_data=f"diamondtransfer|yes|{user_id}", icon_custom_emoji_id="5938109560249127910"),
        colored_button("خیر", callback_data=f"diamondtransfer|no|{user_id}", icon_custom_emoji_id="5819154526816444042"),
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
        f'{_gift_emoji(5832240029446971049, "❓")} از انتقال الماس مطمئن هستید{_gift_emoji(5938506518306492774, "❔")}\n\n'
        f'{_gift_emoji(5823445637231814311, "💰")} مبلغ : {amount:,}{_gift_emoji(5940725397195853882, "💎")}',
        reply_markup=_transfer_confirmation_markup(sender_id),
        parse_mode="HTML",
    )
    _store_transfer_confirmation(
        sender_id, target_id, amount, confirmation.chat.id, confirmation.message_id
    )
    return confirmation

@bot.callback_query_handler(func=lambda call: call.data.startswith("diamondtransfer|"))
def diamond_transfer_confirmation_callback(call):
    parts = call.data.split("|")
    if len(parts) != 3:
        bot.answer_callback_query(call.id)
        return
    try:
        user_id = int(parts[2])
    except ValueError:
        bot.answer_callback_query(call.id)
        return
    if call.from_user.id != user_id:
        bot.answer_callback_query(call.id)
        return

    with _transfer_confirm_lock:
        pending = _transfer_confirmations.get(user_id)
    if not pending:
        bot.answer_callback_query(call.id)
        return

    if parts[1] == "no":
        _clear_transfer_confirmation(user_id)
        bot.answer_callback_query(call.id)
        e = _gift_emoji
        safe_edit_message(
            f'انتقال الماس لغو شد.{e(5819154526816444042, "❌")}\n'
            f'{e(5830338333892418460, "💰")} هیچ مبلغی از موجودی شما کم نشد.{e(5832240029446971049, "✅")}',
            call.message.chat.id, call.message.message_id, reply_markup=None, parse_mode="HTML"
        )
        return

    if parts[1] != "yes":
        bot.answer_callback_query(call.id)
        return

    _clear_transfer_confirmation(user_id)
    target_id = int(pending["target_id"])
    amount = int(pending["amount"])
    ok, result_msg, sender_balance, target_balance, target_name = perform_transfer(user_id, target_id, amount)
    bot.answer_callback_query(call.id)
    safe_edit_message(
        result_msg, call.message.chat.id, call.message.message_id,
        reply_markup=None, parse_mode="HTML"
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
                    f'{_gift_emoji(5825656411517886523, "⏰")} زمان وارد کردن اطلاعات تمام شد{_gift_emoji(5818716826699307883, "⌛")}',
                    chat_id, prompt_id, reply_markup=None, parse_mode="HTML"
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

_mine_word_meta_lock = threading.Lock()
_mine_word_locks = {}

def _get_mine_word_lock(user_id):
    user_id = int(user_id)
    with _mine_word_meta_lock:
        lock = _mine_word_locks.get(user_id)
        if lock is None:
            lock = threading.Lock()
            _mine_word_locks[user_id] = lock
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
            "last_spin": 0,
            "bank_balance": 0,
            "bank_account_number": None,
            "bank_interest_date": None,
            "ring_diamonds": 0
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
# زمان شروع آخرین الماس فعال هر گروه (در حافظه)؛ برای تشخیص الماس‌های گیرکرده.
_diamond_hunt_started = {}
DIAMOND_HUNT_STALE_SECONDS = 150

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

def _choose_jewelry_gem():
    tier = random.choices([x[0] for x in JEWELRY_TIER_WEIGHTS], weights=[x[1] for x in JEWELRY_TIER_WEIGHTS], k=1)[0]
    return random.choice(JEWELRY_TIER_GEMS[tier])

def _add_ring_diamond(user_id):
    """یک الماس انگشتر به موجودی قابل تبدیل کاربر اضافه می‌کند."""
    try:
        user = get_user(user_id)
        if not user:
            return False
        total_ring = int(user.get("ring_diamonds", 0) or 0) + 1
        supabase.table("users").update({"ring_diamonds": total_ring}).eq("user_id", user_id).execute()
        return True
    except Exception as e:
        logging.error(f"خطا در ثبت الماس انگشتر برای {user_id}: {e}")
        return False

def _format_attempt_history(attempts):
    lines = []
    for idx, attempt in enumerate(attempts, 1):
        lines.append(f"در تلاش {idx} {attempt['name']} {attempt['reason']}")
    return "\n".join(lines)

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
        
        hunt_caption = (
            "💎 یک الماس انگشتر در شهر پیدا شد!\n\n"
            "این الماس قابلیت تبدیل به انگشتر داره 💍\n\n"
            "تا از دست نرفته تلاش خودت رو برای بدست آوردنش بکن ✅\n\n"
            "از دکمه زیر برای برداشتن الماس استفاده کنید❗\n\n"
            f"💰 هزینه تلاش برای برداشتن الماس: {DIAMOND_HUNT_COSTS[0]:,} الماس💎"
        )
        try:
            msg = bot.send_photo(chat_id, photo=photo_url, caption=hunt_caption)
        except Exception as photo_error:
            # اگر ارسال عکس ممکن نبود (لینک عکس باز نشد یا گروه ارسال رسانه را بسته)،
            # الماس به‌صورت متن ساده ارسال می‌شود تا گروه بی‌الماس نماند.
            logging.warning(f"ارسال عکس الماس در گروه {chat_id} ناموفق بود، متن ارسال می‌شود: {photo_error}")
            msg = bot.send_message(chat_id, hunt_caption)

        _diamond_hunt_started[chat_id] = time.time()
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

def _reset_stale_diamond_hunts_on_boot():
    """تایمر انقضای الماس فقط در حافظه است و با ری‌استارت بات از بین می‌رود؛ اگر
    موقع ری‌استارت الماسی فعال بوده، آن گروه برای همیشه active می‌ماند و دیگر
    الماسی نمی‌گیرد. پس هنگام بالا آمدن بات، همه‌ی الماس‌های فعال بسته می‌شوند."""
    try:
        supabase.table("diamond_hunts").update(
            {"active": False, "hunt_message_id": None, "attempts": []}
        ).eq("active", True).execute()
    except Exception as e:
        logging.error(f"خطا در پاک‌کردن الماس‌های گیرکرده هنگام راه‌اندازی: {e}")


_reset_stale_diamond_hunts_on_boot()


def process_group_message_for_diamond_hunt(message):
    if not message or message.chat.type not in ("group", "supergroup"):
        return

    if getattr(message.from_user, "is_bot", False):
        return

    text = (message.text or "").strip()

    if text.replace("ي", "ی") == "ماین":
        try:
            if get_user(message.from_user.id):
                register_mine_word(message.from_user.id, message)
        except Exception as e:
            logging.error(f"خطا در ثبت پاداش کلمه ماین: {e}")

    chat_id = message.chat.id
    with _get_diamond_hunt_lock(chat_id):
        row = _ensure_diamond_hunt_row(chat_id)
        if not row:
            return

        # تا وقتی یک الماس فعال است، پیام‌ها برای چرخه بعدی حساب نمی‌شوند.
        # شمارش بعد از پایان/انقضای همین الماس دوباره ادامه پیدا می‌کند.
        if row.get("active"):
            started = _diamond_hunt_started.get(chat_id)
            if started is None:
                # الماس فعالی که این پروسه شروعش نکرده؛ از همین لحظه زمانش را می‌سنجیم.
                _diamond_hunt_started[chat_id] = time.time()
                return
            if time.time() - started < DIAMOND_HUNT_STALE_SECONDS:
                return
            # الماس بیش از زمان مجاز فعال مانده (تایمر انقضا گم شده): آزادش کن.
            _set_diamond_hunt(chat_id, active=False, hunt_message_id=None, attempts=[])
            _diamond_hunt_started.pop(chat_id, None)

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
        bot.answer_callback_query(call.id)
        return

    try:
        message_id = int(parts[1])
        attempt_no = int(parts[2])
    except ValueError:
        bot.answer_callback_query(call.id)
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
            _add_ring_diamond(user_id)
            register_ring_diamond_win(user_id, chat_id, name)
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
                            f"{name} با موفقیت الماس رو بدست آورد.💍\n\n"
                            "🎁 پاداش ⬇️\n"
                            "‏┘─ یک الماس با قابلیت تبدیل به انگشتر.💍",
                    reply_markup=None
                )
                
            except Exception as e:
                logging.error(f"خطا در نتیجه برد الماس: {e}")
                try:
                    safe_edit_message(
                        f"الماس بعد از {total_attempts} تلاش با موفقیت نجات یافت و صاحب جدید پیدا کرد!💎\n\n"
                        f"{name} با موفقیت الماس رو بدست آورد.💍\n\n"
                        "🎁 پاداش ⬇️\n"
                        "‏┘─ یک الماس با قابلیت تبدیل به انگشتر.💍",
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

def get_balance(user_id):
    user = get_user(user_id)
    return user.get('diamonds', 0) if user else 0

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

def safe_html_name(user):
    """اسم کاربر برای پیام‌های HTML: ایموجی گیفت (اگر دارد) + نام escape‌شده."""
    name = html.escape((getattr(user, "first_name", None) or "کاربر").strip())
    uid = getattr(user, "id", None)
    if uid:
        try:
            g = display_gift_for_user(uid)
            if g:
                return f"{g} {name}"
        except Exception:
            pass
    return name


def get_display_name(user):
    name=(getattr(user,"first_name",None) or "کاربر").strip();uid=getattr(user,"id",None)
    if uid:
        try:
            g=display_gift_for_user(uid)
            if g:return f"{g} {name}"
        except Exception:pass
    return name

# ================== سیستم گیفت‌های پرمیوم ==================
GIFT_BOX_PRICE=100_000_000
GIFT_MAX_PRICE_UP=5_000_000
GIFT_MAX_PRICE_DOWN=5_000_000
GIFT_MARKET_INTERVAL_SECONDS=6*60*60
GIFT_MIN_VALUE=10_000_000
GIFT_MAX_VALUE=40_000_000
GIFT_TOTAL_DISPLAY=1

# ---------- کاتالوگ گیفت‌ها ----------
# هر «نوع» چند «مدل» داره و هر مدل یه ایموجی پرمیوم (gift_code) جداست.
# تگ (gift_id) برای هر مدل جدا از ۱ شروع می‌شه و به ترتیب بالا می‌ره.
# قیمت (min/max) و شانس (weight) هر نوع از اینجا تنظیم می‌شه.
GIFT_CATALOG = {
    "plush_pepe": {
        "name": "Plush Pepe", "min": 150_000_000, "max": 200_000_000, "weight": 0.15,
        "models": {
            5454286330487922571: "Sketchy",
            5456504676801338603: "Midas Pepe",
            5453887869192003779: "Frozen",
        },
    },
    "diamond_ring": {
        "name": "Diamond Ring", "min": 50_000_000, "max": 100_000_000, "weight": 0.5,
        "models": {
            5852783592463147155: "Vice City",
            5850247611843354746: "Twilight",
            5852457862143418180: "Sketch",
        },
    },
    "toy_bear": {
        "name": "Toy Bear", "min": 20_000_000, "max": 40_000_000, "weight": 0.35,
        "models": {
            5845768128457350256: "Snowman",
            5846006477667443242: "Blueprint",
            5846007366725673296: "Golden Cub",
            5845836989668008156: "Angel",
            5845901246673723045: "The Devil",
        },
    },
    "timeless_book": {
        "name": "Timeless Book", "min": 15_000_000, "max": 30_000_000, "weight": 1.0,
        "models": {
            5850333296440911189: "Death Note",
            5852690937133670577: "Library Scroll",
            5852758806206882465: "Secret Chapter",
            5850186069256969840: "Rocket Science",
            5850534180651277908: "Journal 1",
        },
    },
    "snoop_dog": {
        "name": "Snoop Dog", "min": 25_000_000, "max": 40_000_000, "weight": 1.0,
        "models": {
            5846078001757823356: "Goldizzle",
            5845876615036281264: "King Snoop",
            5846103900410618639: "Silver",
            5845827089768390239: "Chrome",
            5845684947825728788: "Woofee",
            5845757120456172182: "Black Gold",
        },
    },
    "heroic_helmet": {
        "name": "Heroic Helmet", "min": 50_000_000, "max": 100_000_000, "weight": 0.5,
        "models": {
            5879964524924114989: "Mercurial",
            5879840138376255988: "King Midas",
            5879465789026736965: "Unicorn",
        },
    },
}
GIFT_MODEL_INDEX = {
    code: (type_key, model_name)
    for type_key, cfg in GIFT_CATALOG.items()
    for code, model_name in cfg["models"].items()
}

def _gift_type(gift_code):
    try:
        return GIFT_MODEL_INDEX[int(gift_code)][0]
    except Exception:
        return None

def _gift_type_name(gift_code):
    typ = _gift_type(gift_code)
    return GIFT_CATALOG[typ]["name"] if typ else "-"

def _gift_model_name(gift_code):
    try:
        return GIFT_MODEL_INDEX[int(gift_code)][1]
    except Exception:
        return "-"

def _gift_price_range(gift_code):
    typ=_gift_type(gift_code)
    if typ: return GIFT_CATALOG[typ]["min"], GIFT_CATALOG[typ]["max"]
    return 10_000_000,35_000_000

def _random_gift_price(gift_code):
    lo, hi = _gift_price_range(gift_code)
    # قیمت کاملاً تصادفی است، ولی برای جلوگیری از قیمت‌های خیلی رُند،
    # ضرایب میلیون/ده‌هزار به‌صورت تصادفی شکسته می‌شوند.
    for _ in range(20):
        price = random.randint(lo, hi)
        if price % 1_000_000 != 0:
            return price
    return random.randint(lo, hi)

def _gift_emoji(emoji_id,fallback="🎁"):
    return f'<tg-emoji emoji-id="{int(emoji_id)}">{fallback}</tg-emoji>'

def _gift_value_from_id(gift_id,gift_code):
    return _random_gift_price(gift_code)

def _gift_ready():
    try:supabase.table("premium_gifts").select("instance_id").limit(1).execute();return True
    except Exception as e:logging.error(f"جدول premium_gifts در دسترس نیست: {e}");return False

def gift_box_text(uid):
    e = _gift_emoji
    return (
        f'{e(5927029738626359516, "🎁")} گیفت شانسی\n\n'
        f'{e(5823445637231814311, "💰")} قیمت گیفت باکس شانسی : {GIFT_BOX_PRICE:,}{e(5940725397195853882, "💎")}\n\n'
        f'{e(5825623013852192219, "💎")} موجودی شما : {get_balance(uid):,}{e(5940725397195853882, "💎")}\n\n'
        f'{e(5816913107938712568, "ℹ️")} جهت خرید گیفت باکس از دکمه خرید گیفت زیر استفاده کن{e(5820903824046432799, "👇")}'
    )

def count_owned_by_code(uid,gift_code):
    try:
        return len(supabase.table("premium_gifts").select("instance_id").eq("owner_id",int(uid)).eq("gift_code",int(gift_code)).execute().data or [])
    except Exception: return 0

def _gift_model_total(gift_code):
    """تعداد کل گیفت‌های ساخته‌شده‌ی این مدل (= بالاترین تگ)."""
    try:
        r = (supabase.table("premium_gifts").select("gift_id")
             .eq("gift_code", int(gift_code)).order("gift_id", desc=True).limit(1).execute())
        return int(r.data[0]["gift_id"]) if r.data else 0
    except Exception as e:
        logging.error(f"خطا در _gift_model_total: {e}")
        return 0

def _gift_pick_model():
    """نوع رو با شانس هر نوع انتخاب می‌کنه و یکی از مدل‌هاش رو یکنواخت."""
    keys = list(GIFT_CATALOG.keys())
    type_key = random.choices(keys, weights=[GIFT_CATALOG[k]["weight"] for k in keys], k=1)[0]
    return random.choice(list(GIFT_CATALOG[type_key]["models"].keys()))

_gift_mint_lock = threading.Lock()

def _gift_buy(uid):
    """گیفت‌باکس: یه گیفت جدید از یه مدل شانسی می‌سازه و تگ بعدیِ همون مدل رو بهش می‌ده."""
    if not _gift_ready():return False,"❌ جدول premium_gifts ساخته نشده است."
    if get_balance(uid)<GIFT_BOX_PRICE:return False,f"❌ موجودی کافی نیست. قیمت گیفت باکس {GIFT_BOX_PRICE:,} 💎 است."
    code=_gift_pick_model()
    value=_random_gift_price(code)
    with _gift_mint_lock:
        try:
            if update_diamonds(uid,-GIFT_BOX_PRICE) is None:return False,"❌ کسر مبلغ انجام نشد."
        except Exception as e:
            logging.error("gift buy (deduct): %s",e);return False,"❌ کسر مبلغ انجام نشد."
        last_err=None
        for _ in range(5):
            tag=_gift_model_total(code)+1
            now_iso=datetime.now(TEHRAN_TZ).isoformat()
            try:
                up=supabase.table("premium_gifts").insert({
                    "gift_id":tag,"gift_code":int(code),"owner_id":int(uid),
                    "current_value":value,"base_value":value,"acquired_price":value,
                    "active":False,"acquired_at":now_iso,"last_market_update":now_iso,
                }).execute()
                if up.data:return True,up.data[0]
            except Exception as e:
                last_err=e  # احتمالاً تگ تکراری (هم‌زمانی)؛ دوباره با تگ بعدی تلاش می‌کنیم
        logging.error("gift buy (insert): %s",last_err)
        update_diamonds(uid,GIFT_BOX_PRICE)
        return False,"❌ باز کردن گیفت ناموفق بود."

def get_user_gifts(uid):
    try:return supabase.table("premium_gifts").select("*").eq("owner_id",int(uid)).order("current_value",desc=True).execute().data or []
    except Exception as e:logging.error(f"خطا در get_user_gifts({uid}): {e}");return []

def get_active_gift(uid):
    try:
        r=supabase.table("premium_gifts").select("*").eq("owner_id",int(uid)).eq("active",True).limit(1).execute();return r.data[0] if r.data else None
    except Exception as e:logging.error(f"خطا در get_active_gift: {e}");return None

def display_gift_for_user(uid):
    g=get_active_gift(uid);return _gift_emoji(g["gift_code"],"✨") if g else ""

def set_active_gift(uid,iid):
    try:
        r=supabase.table("premium_gifts").select("*").eq("instance_id",int(iid)).eq("owner_id",int(uid)).limit(1).execute()
        if not r.data:return False,"این گیفت متعلق به شما نیست."
        supabase.table("premium_gifts").update({"active":False}).eq("owner_id",int(uid)).eq("active",True).execute();supabase.table("premium_gifts").update({"active":True}).eq("instance_id",int(iid)).execute();return True,r.data[0]
    except Exception as e:logging.error(f"خطا در set_active_gift: {e}");return False,"خطا در فعال‌سازی گیفت."

def sell_gift(uid,iid):
    try:
        r=supabase.table("premium_gifts").select("*").eq("instance_id",int(iid)).eq("owner_id",int(uid)).limit(1).execute()
        if not r.data:return False,"این گیفت متعلق به شما نیست."
        price=int(r.data[0].get("current_value",0))
        supabase.table("premium_gifts").update({"owner_id":None,"active":False}).eq("instance_id",int(iid)).execute()
        update_diamonds(uid,price);return True,price
    except Exception as e:logging.error(f"خطا در sell_gift: {e}");return False,"فروش گیفت ناموفق بود."

def transfer_gift(sender,target,iid):
    try:
        if int(sender)==int(target):return False,"نمی‌توانی گیفت را به خودت منتقل کنی."
        if not get_user(target):return False,"کاربر مقصد هنوز /start نزده است."
        r=supabase.table("premium_gifts").select("*").eq("instance_id",int(iid)).eq("owner_id",int(sender)).limit(1).execute()
        if not r.data:return False,"این گیفت متعلق به شما نیست."
        supabase.table("premium_gifts").update({"owner_id":int(target),"active":False}).eq("instance_id",int(iid)).execute();return True,r.data[0]
    except Exception as e:logging.error(f"خطا در transfer_gift: {e}");return False,"انتقال گیفت ناموفق بود."

def update_gift_market():
    try:
        rows=supabase.table("premium_gifts").select("instance_id,gift_code,current_value").not_.is_("owner_id","null").execute().data or []
        for r in rows:
            code=int(r.get("gift_code"));lo,hi=_gift_price_range(code)
            cur=int(r.get("current_value") or _random_gift_price(code))
            new=max(lo,min(hi,cur+random.randint(-GIFT_MAX_PRICE_DOWN,GIFT_MAX_PRICE_UP)))
            supabase.table("premium_gifts").update({"current_value":new,"last_market_update":datetime.now(TEHRAN_TZ).isoformat()}).eq("instance_id",r["instance_id"]).execute()
    except Exception as e:logging.error("gift market: %s",e)

try:
    premium_gift_scheduler=BackgroundScheduler(timezone=TEHRAN_TZ);premium_gift_scheduler.add_job(update_gift_market,"interval",seconds=GIFT_MARKET_INTERVAL_SECONDS,id="premium_gift_market",replace_existing=True,max_instances=1,coalesce=True);premium_gift_scheduler.start()
except Exception:premium_gift_scheduler=None

def gift_rarity_name(value):
    try:
        v = int(value)
    except Exception:
        v = GIFT_MIN_VALUE
    span = max(1, GIFT_MAX_VALUE - GIFT_MIN_VALUE)
    ratio = (v - GIFT_MIN_VALUE) / span
    if ratio >= 0.85:
        return "🔴 افسانه‌ای"
    if ratio >= 0.55:
        return "🟣 حماسی"
    if ratio >= 0.25:
        return "🔵 کمیاب"
    return "🟢 معمولی"

def gift_pnl_text(current_value, acquired_price):
    try:
        cur = int(current_value)
        base = int(acquired_price)
    except Exception:
        return "نامشخص"
    diff = cur - base
    if base <= 0:
        return "نامشخص"
    percent = (diff / base) * 100
    if diff > 0:
        return f"📈 سود {diff:,} 💎 (%{percent:.1f}+)"
    if diff < 0:
        return f"📉 ضرر {abs(diff):,} 💎 (%{abs(percent):.1f}-)"
    return "➖ بدون سود و ضرر"

def _safe_gift_id(g):
    try:
        return int(g.get("gift_id") or 0)
    except Exception:
        return 0

GIFT_LIST_SEPARATOR = "ـ" * 45


def gifts_text(uid):
    e = _gift_emoji
    title = f'{e(5830144944399981619, "🎁")} گیفت‌های من'
    gs = get_user_gifts(uid)
    if not gs:
        return f'{title}\n\nهنوز هیچ گیفتی نداری.'
    diamond = e(5940725397195853882, "💎")

    def line(i, g):
        return f"{i}. {e(g['gift_code'], '✨')} | تگ: {_safe_gift_id(g):,} | ارزش: {int(g['current_value']):,}{diamond}"

    total = sum(int(g.get("current_value") or 0) for g in gs)
    rows = [line(i, g) for i, g in enumerate(gs, 1)]
    active = next(((i, g) for i, g in enumerate(gs, 1) if g.get("active")), None)
    parts = [title, ""]
    if active:
        parts += [f'گیفت درحال نمایش{e(5938388342281343001, "👁")}', line(*active), GIFT_LIST_SEPARATOR]
    parts += rows
    parts += [GIFT_LIST_SEPARATOR, f'{e(5823592920250327036, "💰")} ارزش کل گیفت ها: {total:,}{diamond}']
    return "\n".join(parts)

@bot.message_handler(func=lambda m:text_is(m,"گیفت","گیفت شانسی","گیفت باکس"))
def text_gift_box(message):
    uid=message.from_user.id
    if not get_user(uid):bot.reply_to(message,"اول /start بزن.");return
    m=types.InlineKeyboardMarkup();m.row(colored_button("خرید گیفت باکس",callback_data=f"giftbuy|{uid}",icon_custom_emoji_id="5927029738626359516"));m.row(colored_button("گیفت های من",callback_data=f"giftmine|{uid}",icon_custom_emoji_id="5818976337213266965"));show_or_edit_panel(message,uid,"giftbox",gift_box_text(uid),m,parse_mode="HTML")

@bot.callback_query_handler(func=lambda c:c.data.startswith("giftbuy|"))
def gift_buy_callback(call):
    uid=check_panel_owner(call)
    if uid is None:return
    ok,g=_gift_buy(uid)
    if not ok:bot.answer_callback_query(call.id);return
    bot.answer_callback_query(call.id)
    owned_count = count_owned_by_code(uid, g['gift_code'])
    e = _gift_emoji
    gcode = int(g["gift_code"])
    safe_send_message(
        uid,
        f'شما با موفقیت گیفت باکس خود را باز کردید{e(5938109560249127910, "🎉")}\n\n'
        f'{e(5929398662198206659, "🎁")} گیفت جدید{e(5820903824046432799, "👇")}\n\n'
        f'{e(gcode, "✨")}\n'
        f'┘─ {e(5818976337213266965, "🎁")} نوع گیفت: {_gift_type_name(gcode)}\n'
        f'┘─ {e(5938348905891632091, "🏷")} مدل گیفت: {_gift_model_name(gcode)}\n'
        f'┘─ {e(5819046718842347822, "🆔")} آیدی گیفت: {int(g["gift_id"]):,}\n'
        f'┘─ {e(5823592920250327036, "💰")} ارزش گیفت: {int(g["current_value"]):,}{e(5940725397195853882, "💎")}\n\n'
        f'{e(5830338333892418460, "✅")} شما تعداد {owned_count:,} از این گیفت داری{e(5938109560249127910, "🎉")}\n'
        f'{e(5832397371278892338, "📊")} درکل تعداد {max(_gift_model_total(gcode), int(g["gift_id"])):,} از این نوع گیفت وجود دارد{e(5938109560249127910, "🎉")}',
        parse_mode="HTML",
    )
    safe_edit_message(f'{_gift_emoji(5830144944399981619, "🎁")} گیفت باز شد پیوی خودت رو چک کن{_gift_emoji(5938311423712039050, "📩")}',call.message.chat.id,call.message.message_id,parse_mode="HTML")

@bot.callback_query_handler(func=lambda c:c.data.startswith("giftmine|"))
def gift_mine_callback(call):
    uid=check_panel_owner(call)
    if uid is None:return
    try:
        gs=get_user_gifts(uid);m=types.InlineKeyboardMarkup()
        gift_buttons=[colored_button("\u2800",callback_data=f"giftshow|{g['instance_id']}|{uid}",icon_custom_emoji_id=g['gift_code']) for g in gs[:50]]
        for k in range(0,len(gift_buttons),3):
            m.row(*gift_buttons[k:k+3])
        bot.answer_callback_query(call.id)
        safe_edit_message(gifts_text(uid),call.message.chat.id,call.message.message_id,reply_markup=m,parse_mode="HTML")
    except Exception as e:
        logging.error(f"خطا در gift_mine_callback({uid}): {e}")
        bot.answer_callback_query(call.id)

@bot.callback_query_handler(func=lambda c:c.data.startswith("giftshow|"))
def gift_show_callback(call):
    uid=check_panel_owner(call)
    if uid is None:return
    try:
        iid=int(call.data.split("|")[1]);gs=[g for g in get_user_gifts(uid) if int(g["instance_id"])==iid]
        if not gs:bot.answer_callback_query(call.id);return
        g=gs[0];m=types.InlineKeyboardMarkup();m.row(colored_button("👤 نمایش کنار اسم",callback_data=f"giftactive|{iid}|{uid}"));m.row(colored_button("💰 فروش گیفت",callback_data=f"giftsell|{iid}|{uid}"),colored_button("🔄 انتقال گیفت",callback_data=f"gifttransfer|{iid}|{uid}"));m.row(colored_button("🔙 گیفت‌های من",callback_data=f"giftmine|{uid}"))
        acquired_price = g.get("acquired_price", g.get("base_value", g.get("current_value")))
        info_text = (
            f"{_gift_emoji(g['gift_code'],'✨')} گیفت شما\n\n"
            f"┘─ نام : {gift_rarity_name(g['current_value'])}\n"
            f"┘─ آیدی گیفت : {_safe_gift_id(g):,}\n"
            f"┘─ قیمت فعلی : {int(g['current_value']):,} 💎\n"
            f"┘─ قیمت خرید : {int(acquired_price):,} 💎\n"
            f"┘─ وضعیت سود/ضرر : {gift_pnl_text(g['current_value'], acquired_price)}\n"
            f"┘─ وضعیت نمایش : {'فعال کنار اسم ✅' if g.get('active') else 'غیرفعال'}"
        )
        bot.answer_callback_query(call.id)
        safe_edit_message(info_text,call.message.chat.id,call.message.message_id,reply_markup=m,parse_mode="HTML")
    except Exception as e:
        logging.error(f"خطا در gift_show_callback({uid}): {e}")
        bot.answer_callback_query(call.id)

@bot.callback_query_handler(func=lambda c:c.data.startswith("giftactive|"))
def gift_active_callback(call):
    uid=check_panel_owner(call)
    if uid is None:return
    ok,r=set_active_gift(uid,int(call.data.split("|")[1]));bot.answer_callback_query(call.id)

@bot.callback_query_handler(func=lambda c:c.data.startswith("giftsell|"))
def gift_sell_callback(call):
    uid=check_panel_owner(call)
    if uid is None:return
    ok,r=sell_gift(uid,int(call.data.split("|")[1]));bot.answer_callback_query(call.id);safe_edit_message(gifts_text(uid),call.message.chat.id,call.message.message_id,reply_markup=None,parse_mode="HTML")

@bot.callback_query_handler(func=lambda c:c.data.startswith("gifttransfer|"))
def gift_transfer_prompt(call):
    uid=check_panel_owner(call)
    if uid is None:return
    iid=int(call.data.split("|")[1]);safe_edit_message("🔄 آیدی عددی گیرنده را در پاسخ همین پیام بفرست.",call.message.chat.id,call.message.message_id);register_timed_next_step_handler(call.message,gift_transfer_step,uid,iid,call.message.message_id,expected_user_id=uid)

def gift_transfer_step(message,expected_user_id,instance_id,panel_msg_id):
    if message.from_user.id!=expected_user_id:return
    try:target=int(_normalize_digits(message.text.strip()))
    except Exception:safe_edit_message("❌ آیدی عددی معتبر نیست.",message.chat.id,panel_msg_id);return
    ok,r=transfer_gift(expected_user_id,target,instance_id);safe_edit_message("✅ گیفت با موفقیت منتقل شد." if ok else f"❌ {r}",message.chat.id,panel_msg_id)
    if ok:
        try:safe_send_message(target,"🎁 یک گیفت برایت منتقل شد! پیوی خودت را چک کن.")
        except Exception:pass

# ================== سیستم سطح‌بندی، آمار و اعلان‌ها ==================
# نکته پیاده‌سازی: این بخش به جداول زیر در Supabase نیاز دارد که باید از قبل
# ساخته شده باشند (به فایل new_tables.sql مراجعه کن):
#   user_progress(user_id PK, xp int, level int, messages_count int,
#                  bets_won_count int, casino_wins_count int, cosmetics jsonb)
#   group_notify_settings(chat_id PK, level_up bool, new_diamond bool,
#                          daily_gift bool, diamond_timer bool, betting bool)

def get_progress(user_id):
    try:
        resp = supabase.table("user_progress").select("*").eq("user_id", user_id).execute()
        if resp.data:
            return resp.data[0]
        default = {
            "user_id": user_id, "xp": 0, "level": 1,
            "messages_count": 0, "bets_won_count": 0, "casino_wins_count": 0,
            "cosmetics": {}
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


def _format_mmss(seconds):
    seconds = max(0, int(round(seconds)))
    m, s = divmod(seconds, 60)
    return f"{m:02d}:{s:02d}"


# ================== کلمه «ماین» ==================
# هر کاربر هر ۵ دقیقه یک بار با گفتن «ماین» در گروه الماس می‌گیرد.
# پاداش پله‌پله و کم‌کم بالا می‌رود: (از دفعه‌ی، پاداش پایه، کمترین افزایش، بیشترین افزایش)
MINE_WORD_COOLDOWN_SECONDS = 5 * 60
MINE_WORD_STAGES = [
    (1, 50, 2, 7),
    (11, 100, 5, 15),
    (21, 200, 5, 15),
    (50, 500, 5, 15),
    (100, 1000, 0, 0),
]


def _mine_word_floor(claim_no):
    """کمترین پاداشی که در این دفعه حتماً باید داده شود."""
    base = MINE_WORD_STAGES[0][1]
    for start, stage_base, _lo, _hi in MINE_WORD_STAGES:
        if claim_no >= start:
            base = stage_base
    return base


def _mine_word_next_reward(current, next_claim_no):
    """پاداش دفعه‌ی بعد: کمی بیشتر از فعلی، بدون عبور از پایه‌ی پله‌ی بعدی."""
    idx = 0
    for i, stage in enumerate(MINE_WORD_STAGES):
        if current >= stage[1]:
            idx = i
    stage = MINE_WORD_STAGES[idx]
    if idx == len(MINE_WORD_STAGES) - 1:
        return stage[1]
    cap = MINE_WORD_STAGES[idx + 1][1]
    nxt = min(current + random.randint(stage[2], stage[3]), cap)
    return max(nxt, _mine_word_floor(next_claim_no))


def register_mine_word(user_id, message=None):
    try:
        with _get_mine_word_lock(user_id):
            progress = get_progress(user_id)
            now_ts = time.time()
            try:
                last_ts = float(progress.get("last_mine_word_at") or 0)
            except (TypeError, ValueError):
                last_ts = 0
            elapsed = now_ts - last_ts
            if elapsed < MINE_WORD_COOLDOWN_SECONDS:
                if message is not None:
                    e = _gift_emoji
                    bot.reply_to(
                        message,
                        f'تازه ماین کردی{e(5818716826699307883, "❗")}\n'
                        f'{e(5825656411517886523, "⏳")} تا ماین بعدی: {_format_mmss(MINE_WORD_COOLDOWN_SECONDS - elapsed)}{e(5830144944399981619, "⏱")}',
                        parse_mode="HTML",
                    )
                return

            count = int(progress.get("mine_word_count") or 0)
            stored = int(progress.get("mine_word_reward") or 0)
            reward = max(stored, _mine_word_floor(count + 1))
            next_reward = _mine_word_next_reward(reward, count + 2)

            # اول پیشرفت و زمان ذخیره می‌شود؛ اگر ذخیره نشد (مثلاً ستون‌ها ساخته نشده)
            # پاداشی داده نمی‌شود تا کولداون دور زده نشود.
            try:
                supabase.table("user_progress").update({
                    "mine_word_count": count + 1,
                    "mine_word_reward": next_reward,
                    "last_mine_word_at": now_ts,
                }).eq("user_id", user_id).execute()
            except Exception as e:
                logging.error(f"ذخیره‌ی پیشرفت ماین برای {user_id} ناموفق بود (ستون‌ها ساخته شده؟): {e}")
                return

            new_balance = update_diamonds(user_id, reward)
            if new_balance is None:
                logging.error(f"پاداش ماین برای {user_id} ثبت نشد؛ پیشرفت برگردانده می‌شود.")
                try:
                    supabase.table("user_progress").update({
                        "mine_word_count": count,
                        "mine_word_reward": stored,
                        "last_mine_word_at": last_ts,
                    }).eq("user_id", user_id).execute()
                except Exception as revert_error:
                    logging.error(f"برگرداندن پیشرفت ماین ناموفق بود: {revert_error}")
                return

            if message is not None:
                e = _gift_emoji
                if not isinstance(new_balance, int):
                    new_balance = get_balance(user_id)
                bot.reply_to(
                    message,
                    f'{reward:,} الماس{e(5940725397195853882, "💎")} گرفتی{e(5938109560249127910, "✅")}\n'
                    f'{e(5823592920250327036, "💰")} الماس هات : {int(new_balance or 0):,}{e(5940725397195853882, "💎")}\n'
                    f'{e(5818984798298841943, "⏰")} بعد از {MINE_WORD_COOLDOWN_SECONDS // 60} دقیقه میتونی دوباره ماین کنی{e(5938024562846340196, "⛏")}',
                    parse_mode="HTML",
                )
    except Exception as e:
        logging.error(f"خطا در register_mine_word: {e}")


def register_ring_diamond_win(user_id, chat_id, display_name):
    add_xp(user_id, XP_PER_RING_DIAMOND, chat_id=chat_id, display_name=display_name)
    user = get_user(user_id)
    _notify_group_if_enabled(chat_id, "new_diamond", f"💎 {display_name} یک الماس انگشتر پیدا کرد!")

def register_bet_win(user_id, chat_id, display_name):
    try:
        progress = get_progress(user_id)
        count = int(progress.get("bets_won_count", 0) or 0) + 1
        supabase.table("user_progress").update({"bets_won_count": count}).eq("user_id", user_id).execute()
        add_xp(user_id, XP_PER_BET_WIN, chat_id=chat_id, display_name=display_name)
    except Exception as e:
        logging.error(f"خطا در register_bet_win: {e}")

def register_casino_win(user_id, chat_id, display_name, amount_won=0):
    try:
        progress = get_progress(user_id)
        count = int(progress.get("casino_wins_count", 0) or 0) + 1
        supabase.table("user_progress").update({"casino_wins_count": count}).eq("user_id", user_id).execute()
        bonus = min(XP_BONUS_CASINO_CAP, (amount_won // 100_000) * XP_BONUS_PER_CASINO_100K)
        add_xp(user_id, XP_PER_CASINO_WIN + bonus, chat_id=chat_id, display_name=display_name)
    except Exception as e:
        logging.error(f"خطا در register_casino_win: {e}")


def register_daily_gift(user_id, chat_id, display_name):
    add_xp(user_id, XP_PER_DAILY_GIFT, chat_id=chat_id, display_name=display_name)
    _notify_group_if_enabled(chat_id, "daily_gift", f"🎁 {display_name} هدیه روزانه گرفت!")

def stats_text_for_user(user_id, display_name):
    user = get_user(user_id) or {}
    progress = get_progress(user_id)
    bets_won = int(progress.get("bets_won_count", 0) or 0)
    casino_wins = int(progress.get("casino_wins_count", 0) or 0)
    diamonds = user.get("diamonds", 0)
    return (
        "◈ ━━━━━ 𝗦𝘁𝗮𝘁𝗶𝘀𝘁𝗶𝗰𝘀 ━━━━━ ◈\n"
        "⏣ | آمار شما\n\n"
        f"❖ | شرط‌های برده: {bets_won:,}\n"
        f"❖ | بازی‌های کازینو برده: {casino_wins:,}\n"
        f"$ | موجودی فعلی: {diamonds:,}\n"
        "◈ ━━━━━ 𝗦𝘁𝗮𝘁𝗶𝘀𝘁𝗶𝗰𝘀 ━━━━━ ◈"
    )

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
    name=(display_name or "کاربر").strip()
    if "<tg-emoji" in name:
        return name
    if "🤖" in name or name=="ربات":return "🤖 ربات" if "ربات" in name else name
    try:
        g=display_gift_for_user(user_id)
        if g:return f"{g} {name}"
    except Exception:pass
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
    """نرخ مالیات ثابت."""
    return TAX_RATE

def calculate_payout(winner_id, pool, context="bet"):
    tax_rate = get_effective_tax_rate(winner_id, context)
    admin_tax = int(pool * tax_rate)
    return max(0, pool - admin_tax), admin_tax, 0, tax_rate, 0


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


# ================== دکمه‌ها و توابع کمکی ==================
MAIN_MENU_CAPTION = (
    '<tg-emoji emoji-id="6028360176191411591">🌹</tg-emoji> به بات الماسی خوش آمدید.\n\n'
    '<tg-emoji emoji-id="5889002570633977838">🤖</tg-emoji> من رو تو گروهتون اد کنید و الماس جمع کنید.\n\n'
    '<tg-emoji emoji-id="5825623013852192219">💎</tg-emoji> با گفتن کلمه «ماین» تو گروه الماس رایگان بگیرید.'
)


def main_menu_markup(user_id=None):
    # منوی اصلی فقط یک دکمه دارد: افزودن بات به گروه.
    markup = types.InlineKeyboardMarkup()
    markup.row(colored_button(
        "افزودن من به گروهتون",
        url="https://t.me/FreePremiiumBot?startgroup=true",
        icon_custom_emoji_id="5938185469501116312",
    ))
    return markup


def account_menu_markup(user_id):
    markup = types.InlineKeyboardMarkup()
    markup.row(colored_button("لقب‌ها", callback_data=f"showtags|{user_id}", icon_custom_emoji_id="5937997075055644696"))
    markup.row(colored_button("آمار من", callback_data=f"showstats|{user_id}", icon_custom_emoji_id="5938072524746137114"))
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
    نادیده گرفته بشه (باگ «تو بانک واریز/برداشت نمیشه»). چون هر مرحله
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
        text = instruction if "<tg-emoji" in instruction else f"↩️ {instruction}"
        safe_edit_message(text, message.chat.id, panel_message_id, reply_markup=None)
    return False

def safe_edit_message(text, chat_id, message_id, reply_markup=None, parse_mode=None, retries=2):
    """Reliable edit: suppress only a known-successful duplicate; never drop a new edit."""
    if isinstance(text, str) and "<tg-emoji" in text and parse_mode is None:
        parse_mode = "HTML"
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
        logging.error("خطا در ارسال پیام به chat_id=%s: %s", chat_id, exc)
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
        MAIN_MENU_CAPTION,
        main_menu_markup(user_id),
        parse_mode="HTML"
    )


def auto_return_to_bank(chat_id, message_id, user_id, delay=5):
    _auto_edit_after_delay(
        chat_id, message_id, delay,
        bank_text(user_id),
        bank_markup(user_id),
        parse_mode="HTML"
    )


def auto_return_to_casino(chat_id, message_id, user_id, delay=5):
    _auto_edit_after_delay(
        chat_id, message_id, delay,
        CASINO_MENU_TEXT,
        casino_games_keyboard(user_id),
        parse_mode="HTML"
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

def build_account_text(user_id, user, tg_user):
    diamonds = user.get('diamonds', 0)
    ring_diamonds = user.get('ring_diamonds', 0) or 0
    progress = get_progress(user_id)
    level = int(progress.get("level", 1) or 1)
    xp = int(progress.get("xp", 0) or 0)
    _, title, _need, _reward = level_info(level)
    next_need = xp_needed_for_next_level(level)
    xp_line = f"{xp} / {next_need}" if next_need is not None else f"{xp} (حداکثر سطح)"

    # نام کاربر باید برای HTML escape شود؛ ایموجی گیفت (tg-emoji) دست‌نخورده می‌ماند.
    name = html.escape((getattr(tg_user, "first_name", None) or "کاربر").strip())
    try:
        g = display_gift_for_user(user_id)
        if g:
            name = f"{g} {name}"
    except Exception:
        pass

    return (
        '<tg-emoji emoji-id="5938508592775696902">👤</tg-emoji> پروفایل شما\n\n'
        f'<tg-emoji emoji-id="5843973755545590553">👤</tg-emoji> نام: {name}\n'
        f'<tg-emoji emoji-id="5938398023137628324">🆔</tg-emoji> آیدی عددی : {user_id}\n'
        f'<tg-emoji emoji-id="6028360176191411591">💎</tg-emoji> موجودی الماس : {int(diamonds or 0):,}\n'
        f'<tg-emoji emoji-id="5805686638952584277">💍</tg-emoji> الماس انگشتر: {int(ring_diamonds or 0):,}\n'
        f'<tg-emoji emoji-id="5938515112536051725">⭐</tg-emoji> سطح : {level} ({html.escape(str(title))})\n'
        f'<tg-emoji emoji-id="5897595485933280320">🏆</tg-emoji> امتیاز : {xp_line}'
    )


# ================== هندلر start ==================
@bot.message_handler(commands=["start"])
def cmd_start(message):
    user_id = message.from_user.id
    username = get_display_name(message.from_user)
    is_new = not get_user(user_id)

    if is_new:
        create_user(user_id, username)

    safe_send_message(message.chat.id, MAIN_MENU_CAPTION, reply_markup=main_menu_markup(user_id), parse_mode="HTML", reply_to_message_id=message.message_id)

# ================== کالبک منوی اصلی ==================
@bot.callback_query_handler(func=lambda call: call.data == "mainmenu" or call.data.startswith("mainmenu|"))
def main_menu(call):
    # اگه این دکمه داخل یه پنل شخصی (مثل بانک، حساب، رفرال، راهنما) قرار
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
    # اگر کاربر وسط برداشت/واریز «منوی اصلی» را بزند، باید آن مرحله هم
    # همان لحظه لغو شود تا پیام بعدی او دوباره توسط مرحله‌ی قدیمی بلعیده نشود.
    cancel_pending_step(call.message.chat.id, clicker_id)
    bot.clear_step_handler(call.message)

    caption = MAIN_MENU_CAPTION
    # همون پیام قبلی ویرایش میشه (نه پیام جدید). این کار امنه چون بالاتر مالکیت
    # پنل‌های شخصی چک شده؛ فقط اگه ویرایش به هر دلیلی (مثلاً پیام اصلی عکس بود)
    # شکست بخوره، به‌عنوان فالبک یه پیام تازه فرستاده میشه.
    edited = safe_edit_message(caption, call.message.chat.id, call.message.message_id, main_menu_markup(clicker_id))
    if not edited:
        safe_send_message(call.message.chat.id, caption, reply_markup=main_menu_markup(clicker_id), parse_mode="HTML")

# ================== دستور /account ==================
@bot.message_handler(commands=["account"])
def cmd_account(message):
    user_id = message.from_user.id
    user = get_user(user_id)
    if not user:
        bot.reply_to(message, "اول /start بزن.")
        return

    text = build_account_text(user_id, user, message.from_user)
    show_or_edit_panel(message, user_id, "account", text, account_menu_markup(user_id), parse_mode="HTML")

# دسترسی متنی منوی اصلی
@bot.message_handler(func=lambda m: text_is(m, "حساب کاربری"))
def text_account(message):
    cmd_account(message)

@bot.message_handler(func=lambda m: text_is(m, "راهنما", "کمک"))
def text_help(message):
    show_or_edit_panel(message, message.from_user.id, "help", HELP_MENU_TEXT, help_main_markup(message.from_user.id), parse_mode="HTML")

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
    text = build_account_text(user_id, user, call.from_user)
    safe_edit_message(text, call.message.chat.id, call.message.message_id, reply_markup=account_menu_markup(user_id), parse_mode="HTML")

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
    markup.row(back_button(callback_data=f"showaccount|{user_id}"))
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
    markup.row(back_button(callback_data=f"showaccount|{user_id}"))
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
        markup.row(back_button(callback_data=f"showaccount|{user_id}"))
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
# مقایسه می‌کنند (به همان الگوی بقیه پنل‌ها).
def bank_markup(user_id):
    markup = types.InlineKeyboardMarkup()
    markup.row(
        colored_button("واریز", callback_data=f"bankdeposit|{user_id}", icon_custom_emoji_id="5938558852482994666"),
        colored_button("برداشت", callback_data=f"bankwithdraw|{user_id}", icon_custom_emoji_id="5936151695112278046")
    )
    return markup


def bank_back_markup(user_id):
    markup = types.InlineKeyboardMarkup()
    markup.add(back_button(callback_data=f"bankmenu|{user_id}"))
    return markup

def bank_open_markup(user_id):
    markup = types.InlineKeyboardMarkup()
    markup.add(colored_button("افتتاح حساب", callback_data=f"bankopen|{user_id}"))
    return markup

def _bank_err(text):
    return f'{text} {_gift_emoji(5938290000415167172, "❌")}'


def bank_open_text(user_id):
    e = _gift_emoji
    return (
        f'{e(5886285995229323603, "🏦")} بانک الماس\n\n'
        f'برای اولین بار باید حساب بانکی خودت رو با پرداخت {BANK_OPENING_FEE:,} {e(5940725397195853882, "💎")} افتتاح کنی.\n\n'
        f'{e(5823445637231814311, "💰")} موجودی فعلی: {get_balance(user_id):,} {e(5940725397195853882, "💎")}'
    )

def bank_text(user_id):
    apply_bank_interest(user_id)
    user = get_user(user_id)
    bank_balance = get_bank_balance(user_id)
    account_number = user.get("bank_account_number")
    display_name = html.escape(str(user.get('username') or user_id))
    today_interest = min(int(bank_balance * BANK_INTEREST_RATE), BANK_DAILY_INTEREST_MAX)
    e = _gift_emoji
    rate_emoji = e(5938489471581293873, "📈")
    return (
        f'{e(5886285995229323603, "🏦")} بانک الماس\n\n'
        f'{e(5888625992196431593, "💳")} شماره حساب : <code>{account_number}</code>\n'
        f'{e(5938272154826052187, "👤")} به نام : {display_name}\n\n'
        f'{e(5823445637231814311, "💰")} موجودی حساب : {bank_balance:,} الماس {e(5940725397195853882, "💎")}\n\n'
        " سود بانکی\n"
        f'┘─ {rate_emoji} درصد سود : {int(BANK_INTEREST_RATE * 100)}% {rate_emoji}\n'
        f'┘─ {e(5889002570633977838, "💸")} سود روزانه : {today_interest:,} الماس {rate_emoji}\n'
        f'┘─  {e(5818984798298841943, "⏰")} زمان واریز : 00:00\n\n'
        f'{e(5938167138580741203, "ℹ️")} برای مدیریت حساب بانکی از گزینه های زیر استفاده کنید. {e(5820903824046432799, "👇")}'
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

    # ورود به بانک یک navigation action است؛ اگر مرحله‌ی قبلی (برداشت/واریز)
    # هنوز فعال باشد، باید آن را ببندیم.
    cancel_pending_step(call.message.chat.id, user_id)
    bot.clear_step_handler(call.message)

    user = get_user(user_id)
    if not user:
        bot.send_message(call.message.chat.id, "اول /start بزن.")
        return
    if not user.get("bank_account_number"):
        safe_edit_message(
            bank_open_text(user_id),
            call.message.chat.id, call.message.message_id, bank_open_markup(user_id), parse_mode="HTML"
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
        f'حساب بانکی با موفقیت افتتاح شد! {_gift_emoji(5938109560249127910, "✅")}\n\n' + bank_text(user_id),
        call.message.chat.id, call.message.message_id, bank_markup(user_id), parse_mode="HTML"
    )

@bot.callback_query_handler(func=lambda call: call.data.startswith("bankdeposit|"))
def bank_deposit_prompt(call):
    user_id = check_panel_owner(call)
    if user_id is None:
        return
    bot.answer_callback_query(call.id)
    if not get_bank_account_number(user_id):
        safe_edit_message(_bank_err("اول حساب بانکی خودت رو افتتاح کن."), call.message.chat.id, call.message.message_id, bank_open_markup(user_id))
        return
    safe_edit_message(
        f'{_gift_emoji(5938558852482994666, "📥")} واریز به بانک الماس\n\n'
        f'{_gift_emoji(5823445637231814311, "💰")} موجودی حساب : {get_bank_balance(user_id):,} الماس {_gift_emoji(5940725397195853882, "💎")}\n\n'
        f'{_gift_emoji(5938290532991111041, "ℹ️")} شما درحال واریز الماس به حساب بانکی خود میباشید.\n\n'
        f'{_gift_emoji(5938311423712039050, "✍️")} لطفا مبلغ مورد نظر جهت واریز رو در جواب همین پنل ارسال کنید.',
        call.message.chat.id, call.message.message_id, bank_back_markup(user_id), parse_mode="HTML"
    )
    register_timed_next_step_handler(call.message, bank_deposit_step, user_id, call.message.message_id, expected_user_id=user_id)

def _bank_confirmation_markup(user_id):
    markup = types.InlineKeyboardMarkup()
    markup.row(
        colored_button("تایید", callback_data=f"bankconfirm|yes|{user_id}", icon_custom_emoji_id="5938109560249127910"),
        colored_button("لغو", callback_data=f"bankconfirm|no|{user_id}", icon_custom_emoji_id="5938290000415167172"),
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
        bot.answer_callback_query(call.id)
        return
    try:
        user_id = int(parts[2])
    except ValueError:
        bot.answer_callback_query(call.id)
        return
    if call.from_user.id != user_id:
        bot.answer_callback_query(call.id)
        return
    with _bank_confirm_lock:
        pending = _bank_confirmations.get(user_id)
    if not pending:
        bot.answer_callback_query(call.id)
        return
    action, amount = pending["action"], int(pending["amount"])
    if parts[1] == "no":
        _clear_bank_confirmation(user_id)
        bot.answer_callback_query(call.id)
        safe_edit_message(_bank_err("عملیات لغو شد"), call.message.chat.id, call.message.message_id, reply_markup=None)
        auto_return_to_bank(call.message.chat.id, call.message.message_id, user_id, 3)
        return
    if parts[1] != "yes":
        bot.answer_callback_query(call.id)
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
            bot.answer_callback_query(call.id)
            safe_edit_message(_bank_err("ثبت واریز انجام نشد و موجودی شما تغییر نکرد"), call.message.chat.id, call.message.message_id, reply_markup=None)
            auto_return_to_bank(call.message.chat.id, call.message.message_id, user_id, 3)
            return
        result_text = (f'تعداد {amount:,} الماس {_gift_emoji(5940725397195853882, "💎")} به حساب بانکی واریز شد. {_gift_emoji(5938109560249127910, "✅")}\n\n'
                       f'{_gift_emoji(5823445637231814311, "💰")} موجودی بانک: {get_bank_balance(user_id):,} {_gift_emoji(5940725397195853882, "💎")}')
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
            bot.answer_callback_query(call.id)
            safe_edit_message(_bank_err("ثبت برداشت انجام نشد و موجودی شما تغییر نکرد"), call.message.chat.id, call.message.message_id, reply_markup=None)
            auto_return_to_bank(call.message.chat.id, call.message.message_id, user_id, 3)
            return
        result_text = (f'تعداد {amount:,} الماس {_gift_emoji(5940725397195853882, "💎")} از حساب بانکی برداشت شد. {_gift_emoji(5938109560249127910, "✅")}\n\n'
                       f'{_gift_emoji(5823445637231814311, "💰")} موجودی بانک: {get_bank_balance(user_id):,} {_gift_emoji(5940725397195853882, "💎")}')
    _clear_bank_confirmation(user_id)
    bot.answer_callback_query(call.id)
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
        safe_edit_message(_bank_err("فرمت پیام درست نیست روی همین پیام ریپلای کن. مثال: 5000 یا 5کا."), message.chat.id, panel_msg_id, reply_markup=bank_back_markup(expected_user_id))
        register_timed_next_step_handler(message, bank_deposit_step, expected_user_id, panel_msg_id, expected_user_id=expected_user_id)
        return
    if amount <= 0:
        safe_edit_message(_bank_err("مبلغ باید بیشتر از صفر باشه مشتی روی همین پیام ریپلای کن و دوباره عدد بفرست."), message.chat.id, panel_msg_id, reply_markup=bank_back_markup(expected_user_id))
        register_timed_next_step_handler(message, bank_deposit_step, expected_user_id, panel_msg_id, expected_user_id=expected_user_id)
        return
    if get_balance(expected_user_id) < amount:
        safe_edit_message(_bank_err("موجودی الماس شما کافی نیست."), message.chat.id, panel_msg_id, reply_markup=bank_markup(expected_user_id))
        return
    safe_edit_message(f'{_gift_emoji(5938558852482994666, "📥")} آیا از واریز اطمینان دارید؟\n\nمبلغ درحال واریز: {amount:,} {_gift_emoji(5940725397195853882, "💎")}', message.chat.id, panel_msg_id, reply_markup=_bank_confirmation_markup(expected_user_id))
    _store_bank_confirmation(expected_user_id, "deposit", amount, message.chat.id, panel_msg_id)

@bot.callback_query_handler(func=lambda call: call.data.startswith("bankwithdraw|"))
def bank_withdraw_prompt(call):
    user_id = check_panel_owner(call)
    if user_id is None:
        return
    bot.answer_callback_query(call.id)
    if not get_bank_account_number(user_id):
        safe_edit_message(_bank_err("اول حساب بانکی خودت رو افتتاح کن."), call.message.chat.id, call.message.message_id, bank_open_markup(user_id))
        return
    apply_bank_interest(user_id)
    safe_edit_message(
        f'{_gift_emoji(5936151695112278046, "📤")} برداشت از بانک الماس\n\n'
        f'{_gift_emoji(5823445637231814311, "💰")} موجودی قابل برداشت : {get_bank_balance(user_id):,} الماس {_gift_emoji(5938489471581293873, "📈")}\n\n'
        f'{_gift_emoji(5936151695112278046, "📤")} شما درحال برداشت الماس از حساب بانکی خود میباشید.\n\n'
        f'{_gift_emoji(5938348905891632091, "✍️")} لطفا مبلغ مورد نظر جهت برداشت رو در جواب همین پنل ارسال کنید.',
        call.message.chat.id, call.message.message_id, bank_back_markup(user_id), parse_mode="HTML"
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
        safe_edit_message(_bank_err("فرمت پیام درست نیست روی همین پیام ریپلای کن. مثال: 5000 یا 5کا."), message.chat.id, panel_msg_id, reply_markup=bank_back_markup(expected_user_id))
        register_timed_next_step_handler(message, bank_withdraw_step, expected_user_id, panel_msg_id, expected_user_id=expected_user_id)
        return
    if amount <= 0:
        safe_edit_message(_bank_err("مبلغ باید بیشتر از صفر باشه مشتی روی همین پیام ریپلای کن و دوباره عدد بفرست."), message.chat.id, panel_msg_id, reply_markup=bank_back_markup(expected_user_id))
        register_timed_next_step_handler(message, bank_withdraw_step, expected_user_id, panel_msg_id, expected_user_id=expected_user_id)
        return
    apply_bank_interest(expected_user_id)
    if get_bank_balance(expected_user_id) < amount:
        safe_edit_message(_bank_err("موجودی بانک برای این برداشت کافی نیست."), message.chat.id, panel_msg_id, reply_markup=bank_markup(expected_user_id))
        return
    safe_edit_message(f'{_gift_emoji(5936151695112278046, "📤")} آیا از برداشت اطمینان دارید؟\n\nمبلغ درحال برداشت: {amount:,} {_gift_emoji(5940725397195853882, "💎")}', message.chat.id, panel_msg_id, reply_markup=_bank_confirmation_markup(expected_user_id))
    _store_bank_confirmation(expected_user_id, "withdraw", amount, message.chat.id, panel_msg_id)

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
            bank_open_text(user_id),
            bank_open_markup(user_id),
            parse_mode="HTML"
        )
        return
    show_or_edit_panel(message, user_id, "bank", bank_text(user_id), bank_markup(user_id), parse_mode="HTML")

# ================== بخش راهنما ==================
# ================== راهنمای شیشه‌ای ==================
HELP_MENU_TEXT = 'هر بخشی که نیاز به راهنمایی دارید رو انتخاب کنید\u200c.<tg-emoji emoji-id="5942718468179628637">🌹</tg-emoji>'


def help_main_markup(user_id):
    def topic(label, emoji_id, key):
        return colored_button(label, callback_data=f"help_topic|{user_id}|{key}", icon_custom_emoji_id=emoji_id)

    markup = types.InlineKeyboardMarkup()
    markup.row(
        topic("موجودی", "5825783216132334124", "balance"),
        topic("موجودی دیگران", "5825783216132334124", "other_balance")
    )
    markup.row(topic("گیفت", "5927029738626359516", "gift"))
    markup.row(
        topic("بانک الماس", "5886285995229323603", "bank"),
        topic("کازینو", "5938026800524301051", "casino")
    )
    markup.row(
        topic("شرطبندی", "5904440688845527733", "bet"),
        topic("معدن الماس", "5940725397195853882", "mine")
    )
    markup.row(
        topic("دینامیت", "5938458195629445238", "dynamite"),
        topic("انگشتر سازی", "5805686638952584277", "jewelry")
    )
    leaderboard_btn = topic("لیدربرد", "5935933089866846598", "rank")
    # «لیدربرد» شامل «رد» است و خودکار قرمز می‌شد؛ دستی آبی می‌کنیم.
    setattr(leaderboard_btn, "style", "primary")
    markup.row(leaderboard_btn)
    return markup

HELP_TOPIC_TEXTS = {
    "balance": f'{_gift_emoji(5904440688845527733, "💰")} موجودی:\nکلمه «موجودی» را در چت ارسال کنید.',
    "other_balance": f'{_gift_emoji(5825783216132334124, "💰")} موجودی دیگران:\nکلمه «موجودی» را در چت به همراه ریپلای روی پیام شخص ارسال کنید.',
    "gift": f'{_gift_emoji(5927029738626359516, "🎁")} گیفت شانسی:\nکلمه «گیفت» را در گروه ارسال کنید.',
    "bank": f'{_gift_emoji(5886285995229323603, "🏦")} بانک الماس:\nکلمه «بانک» را ارسال کنید.',
    "casino": f'{_gift_emoji(5938026800524301051, "🎰")} کازینو:\nکلمه «کازینو» را در چت ارسال کنید.',
    "bet": f'{_gift_emoji(5904440688845527733, "🎲")} شرطبندی:\nبرای شروع شرط بنویسید «شرطبندی عدد دلخواه»',
    "mine": f'{_gift_emoji(5940725397195853882, "💎")} معدن الماس:\nکلمه «معدن الماس» را ارسال کنید.',
    "dynamite": f'{_gift_emoji(5938458195629445238, "💣")} دینامیت:\nبرای شروع بنویسید «دینامیت عدد دلخواه»',
    "jewelry": f'{_gift_emoji(5805686638952584277, "💍")} انگشترسازی:\nکلمه «جواهری» یا «انگشتر سازی» را ارسال کنید.',
    "rank": f'{_gift_emoji(5935933089866846598, "🏆")} رتبه‌بندی:\nکلمه «رنک» را ارسال کنید.',
}

@bot.callback_query_handler(func=lambda call: call.data == "showhelp" or call.data.startswith("showhelp|"))
def handle_show_help(call):
    owner_id = check_panel_owner(call) if "|" in call.data else call.from_user.id
    if owner_id is None:
        return
    bot.answer_callback_query(call.id)
    safe_edit_message(
        HELP_MENU_TEXT,
        call.message.chat.id, call.message.message_id,
        reply_markup=help_main_markup(owner_id),
        parse_mode="HTML"
    )

@bot.callback_query_handler(func=lambda call: call.data.startswith("help_topic|"))
def handle_help_topic(call):
    parts = call.data.split("|", 2)
    if len(parts) != 3:
        return
    owner_id = int(parts[1])
    if call.from_user.id != owner_id:
        bot.answer_callback_query(call.id)
        return
    topic = parts[2]
    text = HELP_TOPIC_TEXTS.get(topic, "راهنمای این بخش پیدا نشد.")
    bot.answer_callback_query(call.id)
    safe_edit_message(text, call.message.chat.id, call.message.message_id, reply_markup=None)

@bot.callback_query_handler(func=lambda call: call.data.startswith("help_tags|"))
def handle_help_tags(call):
    owner_id = int(call.data.split("|", 1)[1])
    if call.from_user.id != owner_id:
        bot.answer_callback_query(call.id)
        return
    bot.answer_callback_query(call.id)
    markup = types.InlineKeyboardMarkup()
    for i in range(0, len(TAGS), 2):
        row = [colored_button(tag, callback_data=f"help_tag_noop|{owner_id}") for tag in TAGS[i:i+2]]
        markup.row(*row)
    markup.row(back_button(callback_data=f"showhelp|{owner_id}"))
    safe_edit_message("تمام لقب ها نمایشی هستند 💎", call.message.chat.id, call.message.message_id, reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data.startswith("help_tag_noop|"))
def handle_help_tag_noop(call):
    owner_id = int(call.data.split("|", 1)[1])
    if call.from_user.id != owner_id:
        bot.answer_callback_query(call.id)
        return
    bot.answer_callback_query(call.id)


# ================== بخش انتقال الماس ==================


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
    markup.add(colored_button(f"$ | موجودی جدید کاربر : {int(new_balance or 0):,} الماس", callback_data="pending", style="primary"))
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
        return False, _casino_err("مقدار باید بزرگتر از صفر باشه"), None, None, None
    if target_id == sender_id:
        return False, _casino_err("نمیشه به خودت انتقال بدی"), None, None, None
    target_user = get_user(target_id)
    if not target_user:
        return False, _casino_err("کاربر مقصد هنوز /start نزده"), None, None, None
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
                return False, _casino_err("انتقال انجام نشد"), None, None, None
            row = result[0] if isinstance(result, list) else result
            sender_balance = int(row.get('sender_balance', 0))
            target_balance = get_balance(target_id)
            return True, f'{_gift_emoji(5888594273862950655, "✅")} مقدار {amount:,} الماس{_gift_emoji(5940725397195853882, "💎")} به {html_escape_keep_emoji(target_name)} منتقل شد.{_gift_emoji(5938109560249127910, "✅")}', sender_balance, target_balance, target_name
        if get_balance(sender_id) < amount:
            return False, _casino_err("موجودی کافی نداری"), None, None, None
        if update_diamonds(sender_id, -amount) is None:
            return False, _casino_err("کسر از موجودی انجام نشد"), None, None, None
        if update_diamonds(target_id, amount) is None:
            update_diamonds(sender_id, amount)
            return False, _casino_err("انتقال کامل نشد و مبلغ برگشت داده شد"), None, None, None
        sender_balance = get_balance(sender_id)
        target_balance = get_balance(target_id)
        return True, f'{_gift_emoji(5888594273862950655, "✅")} مقدار {amount:,} الماس{_gift_emoji(5940725397195853882, "💎")} به {html_escape_keep_emoji(target_name)} منتقل شد.{_gift_emoji(5938109560249127910, "✅")}', sender_balance, target_balance, target_name
    except Exception as e:
        logging.error(f"خطا در perform_transfer: {e}")
        return False, _casino_err("انتقال انجام نشد"), None, None, None

@bot.message_handler(commands=["transfer"])
def cmd_transfer(message):
    sender_id = message.from_user.id
    if not get_user(sender_id):
        bot.reply_to(message, "اول /start بزن.")
        return
    if not message.reply_to_message:
        bot.reply_to(message, _casino_err("روی پیام مقصد ریپلای کن: /transfer <مقدار>"))
        return
    parts = message.text.split()
    amount = parse_amount(parts[1]) if len(parts) >= 2 else None
    if amount is None:
        bot.reply_to(message, _casino_err("مثال: /transfer 20 یا /transfer 20k"))
        return
    target_id = message.reply_to_message.from_user.id
    if not get_user(target_id):
        bot.reply_to(message, _casino_err("کاربر مقصد هنوز /start نزده"))
        return
    _show_transfer_confirmation(message, sender_id, target_id, amount)

@bot.message_handler(func=lambda m: m.text and re.search(r"انتقال\s+الماس\s+(" + AMOUNT_TOKEN + r")", m.text, re.IGNORECASE))
def text_transfer(message):
    sender_id = message.from_user.id
    if not get_user(sender_id):
        bot.reply_to(message, _casino_err("اول باید یه‌بار /start بزنی (توی پیوی بات)"))
        return
    if not message.reply_to_message:
        bot.reply_to(message, _casino_err("روی پیام کاربر مقصد ریپلای کن و بنویس:\nانتقال الماس <مقدار>\nمثال: انتقال الماس 200"))
        return

    match = re.search(r"انتقال\s+الماس\s+(" + AMOUNT_TOKEN + r")", message.text, re.IGNORECASE)
    if not match:
        bot.reply_to(message, _casino_err("فرمت اشتباه است"))
        return
    amount = parse_amount(match.group(1))
    if amount is None:
        bot.reply_to(message, _casino_err("مبلغ نامعتبره"))
        return
    target_id = message.reply_to_message.from_user.id
    if not get_user(target_id):
        bot.reply_to(message, _casino_err("کاربر مقصد هنوز /start نزده"))
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
    e = _gift_emoji
    safe_edit_message(
        f'{e(5825656411517886523, "⏰")} زمان تموم شد{e(5818716826699307883, "⌛")}\n'
        f'{e(5830338333892418460, "💰")} {amount:,} الماس {e(5940725397195853882, "💎")} به سازنده برگردونده شد.{e(5830144944399981619, "✅")}',
        chat_id=chat_id, message_id=message_id, reply_markup=None, parse_mode="HTML",
    )

def start_bet_flow(message, amount):
    user_id = message.from_user.id
    if not get_user(user_id):
        bot.reply_to(message, _start_first_err())
        return

    if amount <= 0:
        bot.reply_to(message, _casino_err("مقدار باید بزرگتر از صفر باشه"))
        return
    if get_balance(user_id) < amount:
        bot.reply_to(message, _casino_err("موجودی الماس کافی نداری"))
        return

    creator_name = get_display_name(message.from_user)
    update_diamonds(user_id, -amount)

    e = _gift_emoji
    panel_text = (
        f'{e(5818704981179505821, "🎲")} شرطبندی {e(5857454223368657979, "🎯")}\n\n'
        f'{e(5823445637231814311, "💰")} مقدار الماس : {amount:,}{e(5940725397195853882, "💎")}\n'
        f'{e(5843973755545590553, "👤")} سازنده : {safe_html_name(message.from_user)}'
    )
    sent = safe_send_message(
        message.chat.id,
        panel_text,
        parse_mode="HTML",
        reply_to_message_id=message.message_id,
    )
    if not sent:
        # پیام ساخته نشد؛ مبلغ رزرو شده باید فوراً برگردد.
        update_diamonds(user_id, amount)
        bot.reply_to(message, _casino_err("ارسال پنل شرط انجام نشد و مبلغ شرط به موجودی شما برگشت داده شد"))
        return

    bet_id = create_bet(user_id, creator_name, amount, message.chat.id, sent.message_id)
    if bet_id is None:
        # رکورد شرط ساخته نشد؛ نگذاریم مبلغ کاربر گم شود.
        update_diamonds(user_id, amount)
        safe_edit_message(
            _casino_err("نمایش دکمه‌های شرط با مشکل مواجه شد و مقداری که شرط بسته بودید به حساب شما برگشت"),
            chat_id=message.chat.id, message_id=sent.message_id, reply_markup=None
        )
        return

    markup = types.InlineKeyboardMarkup()
    markup.row(
        colored_button("پیوستن", callback_data=f"join|{bet_id}", icon_custom_emoji_id="5938109560249127910"),
        colored_button("لغو", callback_data=f"cancel|{bet_id}", icon_custom_emoji_id="5819154526816444042"),
    )
    edited_ok = safe_edit_message(panel_text, chat_id=message.chat.id, message_id=sent.message_id, reply_markup=markup, parse_mode="HTML")
    if not edited_ok:
        # دکمه‌ها اضافه نشدن؛ نگذاریم شرط بدون امکان لغو/پیوستن باقی بمونه و پول بلوکه بشه.
        with _get_bet_lock(bet_id):
            fresh = get_bet(bet_id)
            if fresh and fresh.get("status") == "pending":
                update_diamonds(user_id, amount)
                set_bet_status(bet_id, "cancelled")
        safe_edit_message(
            _casino_err("نمایش دکمه‌های شرط با مشکل مواجه شد و مقداری که شرط بسته بودید به حساب شما برگشت"),
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
        bot.reply_to(message, _casino_err("فرمت اشتباه است. مثال: شرط بندی 20 یا شرط بندی 20k"))
        return
    amount = parse_amount(match.group(1))
    if amount is None:
        bot.reply_to(message, _casino_err("مبلغ نامعتبره"))
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
                    "p_loan_repay": 0,
                    "p_tax_receiver_id": int(TAX_RECEIVER_ID) if get_user(TAX_RECEIVER_ID) else None,
                }).execute().data
                if not result:
                    raise RuntimeError("empty settlement result")
                row = result[0] if isinstance(result, list) else result
                payout = int(row.get("payout", payout) or 0)
                tax = int(row.get("tax", tax) or 0)
                loan_repay = 0
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
        loan_rate_used = 0

    set_bet_status(bet_id, "finished")

    winner_display = html_escape_keep_emoji(display_name_with_tag(winner_id, winner_name or "کاربر"))
    loser_display = html_escape_keep_emoji(display_name_with_tag(loser_id, loser_name or "کاربر"))
    e = _gift_emoji
    text = (
        f'{e(5818704981179505821, "🎲")} نتیجه باز\u200cی {e(5888937012253171131, "🏁")}\n\n'
        f'{e(6014651259057873388, "🏆")} برنده: {winner_display}\n'
        f'{e(5839270298205035832, "🥈")} بازنده: {loser_display}'
    )
    result_amount = payout if real_winner_id is not None else 0
    markup = types.InlineKeyboardMarkup()
    markup.row(
        colored_button(
            f"مبلغ برد: {result_amount:,}",
            callback_data="bet_result_noop",
            icon_custom_emoji_id="5823445637231814311",
        ),
        colored_button(
            f"مالیات: {tax:,}",
            callback_data="bet_result_noop",
            icon_custom_emoji_id="5889002570633977838",
        ),
    )
    safe_edit_message(text, chat_id=chat_id, message_id=message_id, reply_markup=markup, parse_mode="HTML")

@bot.callback_query_handler(func=lambda call: call.data == "bet_result_noop")
def bet_result_noop_callback(call):
    # دکمه‌های مبلغ برد و مالیات صرفاً نمایشی هستند و هیچ عملیاتی انجام نمی‌دهند.
    bot.answer_callback_query(call.id)

@bot.callback_query_handler(
    func=lambda call: call.data == "pending" or call.data.split("|")[0] in ("cancel", "join")
)
def handle_callback(call):
    if call.data == "pending":
        bot.answer_callback_query(call.id)
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
            bot.answer_callback_query(call.id)
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
            bot.answer_callback_query(call.id)
            return

        if action == "cancel":
            if clicker_id != creator_id:
                bot.answer_callback_query(call.id)
                return
            if ATOMIC_DB_MODE:
                try:
                    supabase.rpc("atomic_refund_bet", {"p_bet_id": int(bet_id), "p_status": "cancelled"}).execute()
                except Exception as e:
                    logging.error(f"خطا در لغو اتمیک شرط {bet_id}: {e}")
                    bot.answer_callback_query(call.id)
                    return
            else:
                update_diamonds(creator_id, amount)
                set_bet_status(bet_id, "cancelled")
            outcome = ("cancel", amount, chat_id, message_id)

        elif action == "join":
            if clicker_id == creator_id:
                bot.answer_callback_query(call.id)
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
                        bot.answer_callback_query(call.id)
                        return
                else:
                    if get_balance(clicker_id) < amount:
                        bot.answer_callback_query(call.id)
                        return
                    if update_diamonds(clicker_id, -amount) is None:
                        bot.answer_callback_query(call.id)
                        return
                    # بلافاصله وضعیت رو از pending خارج می‌کنیم تا یک کلیک هم‌زمان دیگه
                    # (لغو یا پیوستن دوباره) نتونه همین شرط رو دوباره پردازش کنه.
                    set_bet_status(bet_id, "finished")
            except Exception as e:
                logging.error(f"خطا در claim اتمیک شرط {bet_id}: {e}")
                bot.answer_callback_query(call.id)
                return
            outcome = ("join", clicker_id, clicker_name)

    # از اینجا به بعد قفل آزاد شده؛ عملیات کند (ادیت پیام/محاسبه‌ی نتیجه) دیگه بقیه‌ی
    # کلیک‌ها روی همین شرط رو بلاک نمی‌کنه.
    if outcome is None:
        return
    if outcome[0] == "cancel":
        _, amount, chat_id, message_id = outcome
        e = _gift_emoji
        safe_edit_message(
            f'{e(5818704981179505821, "🎲")} بازی لغو شد.{e(5819154526816444042, "❌")}\n'
            f'{e(5830338333892418460, "💰")} {amount:,} الماس {e(5940725397195853882, "💎")} برگردونده شد.{e(5830144944399981619, "✅")}',
            chat_id=chat_id, message_id=message_id, reply_markup=None, parse_mode="HTML",
        )
        bot.answer_callback_query(call.id)
    elif outcome[0] == "join":
        _, join_clicker_id, join_clicker_name = outcome
        resolve_bet(bet_id, join_clicker_id, join_clicker_name, is_bot=False)
        bot.answer_callback_query(call.id)

# ================== بازی دینامیت (۲ نفره، ۳ در ۳) ==================
DYNAMITE_GRID_SIZE = 9  # 3x3
TURN_TIMEOUT_SECONDS = 60  # هر نوبت ۶۰ ثانیه وقت داره
dynamite_lock = threading.RLock()
active_dynamites = {}  # message_id -> game dict
_dynamite_turn_seq = itertools.count(1)

# آیدی ایموجی‌های پرمیوم بازی دینامیت
DYN_DIAMOND_EMOJI_ID = 5940725397195853882  # الماس (خونه‌ی امن)
DYN_BOMB_EMOJI_ID = 5929177175029718803     # بمب

def _dyn_name(user_id, name):
    """اسم بازیکن برای پیام HTML (escape شده؛ ایموجی گیفت دست‌نخورده)."""
    return html_escape_keep_emoji(display_name_with_tag(user_id, name))

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

def dynamite_pending_text(amount, creator_id, creator_name):
    e = _gift_emoji
    return (
        f'{e(5818704981179505821, "🎲")} دینامیت {e(5929177175029718803, "💣")}\n\n'
        f'{e(5823445637231814311, "💰")} مقدار الماس : {amount:,}{e(5940725397195853882, "💎")}\n'
        f'{e(5843973755545590553, "👤")} سازنده: {_dyn_name(creator_id, creator_name)}'
    )

def dynamite_pending_markup():
    markup = types.InlineKeyboardMarkup()
    markup.row(
        colored_button("پیوستن", callback_data="dynjoin", icon_custom_emoji_id="5830144944399981619"),
        colored_button("لغو", callback_data="dyncancel", icon_custom_emoji_id="5819154526816444042"),
    )
    return markup

def dynamite_active_text(game):
    e = _gift_emoji
    creator_display = _dyn_name(game["creator_id"], game["creator_name"])
    opponent_display = _dyn_name(game["opponent_id"], game["opponent_name"])
    turn_name = creator_display if game["turn_id"] == game["creator_id"] else opponent_display
    return (
        f'{e(5821026698765803333, "🎲")} دینامیت {e(5929177175029718803, "💣")}\n\n'
        f'{e(5823445637231814311, "💰")} مقدار الماس : {game["amount"]:,}{e(5940725397195853882, "💎")}\n'
        f'{e(5843973755545590553, "👤")} سازنده : {creator_display}\n'
        f'{e(5859432880442187580, "👥")} شرکت کننده : {opponent_display}\n\n'
        f'{e(5938348905891632091, "⏳")} نوبت: {turn_name}\n'
        f'{e(5938098930205069821, "🛡")} جاهای امن باقی‌مانده: {game["safe_remaining"]}{e(5830144944399981619, "✅")}\n\n'
        f'{e(5819051035284479206, "👇")} روی دکمه های زیر کلیک کنید.{e(5820903824046432799, "👇")}'
    )

def dynamite_board_markup(game):
    markup = types.InlineKeyboardMarkup()
    for row in range(3):
        buttons = []
        for col in range(3):
            idx = row * 3 + col
            if idx in game["revealed"]:
                buttons.append(colored_button("\u2800", callback_data=f"dyncell|{idx}",
                                              icon_custom_emoji_id=str(DYN_DIAMOND_EMOJI_ID)))
            else:
                buttons.append(colored_button(" ", callback_data=f"dyncell|{idx}"))
        markup.row(*buttons)
    return markup

def dynamite_result_markup(payout, tax, game=None, reveal_bomb=False):
    """صفحه‌ی ۳×۳ بعد از پایان بازی هم روی پیام می‌مونه (دکمه‌ها بی‌اثر)؛ الماس‌های
    باز‌شده می‌مونن و اگه بازی با انفجار تموم شده باشه، فقط دکمه‌ی بمب قرمز می‌شه."""
    markup = types.InlineKeyboardMarkup()
    if game is not None:
        for row in range(3):
            buttons = []
            for col in range(3):
                idx = row * 3 + col
                if reveal_bomb and idx == game.get("bomb_index"):
                    buttons.append(colored_button("\u2800", callback_data="dynamite_result_noop",
                                                  style="danger",
                                                  icon_custom_emoji_id=str(DYN_BOMB_EMOJI_ID)))
                elif idx in game["revealed"]:
                    buttons.append(colored_button("\u2800", callback_data="dynamite_result_noop",
                                                  icon_custom_emoji_id=str(DYN_DIAMOND_EMOJI_ID)))
                else:
                    buttons.append(colored_button(" ", callback_data="dynamite_result_noop"))
            markup.row(*buttons)
    markup.row(
        colored_button(f"مبلغ برد: {payout:,}", callback_data="dynamite_result_noop",
                       icon_custom_emoji_id="5823445637231814311"),
        colored_button(f"مالیات: {tax:,}", callback_data="dynamite_result_noop",
                       icon_custom_emoji_id="5889002570633977838"),
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
    e = _gift_emoji
    safe_edit_message(
        f'{e(5825656411517886523, "⏰")} زمان تموم شد{e(5818716826699307883, "⌛")}\n'
        f'{e(5830338333892418460, "💰")} {amount:,} الماس {e(5940725397195853882, "💎")} به سازنده برگردونده شد.{e(5830144944399981619, "✅")}',
        chat_id=chat_id, message_id=message_id, reply_markup=None, parse_mode="HTML",
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
        e = _gift_emoji
        reason = (
            f'{e(5825656411517886523, "⏰")} زمان تموم شد\n'
            f'{e(5872823922751185495, "⚠️")} بازنده به دلیل انتخاب نکردن در تایم تعیین شده باخت.{e(5875037024909532569, "❌")}'
        )
        _dynamite_finish(message_id, game, winner_id, winner_name, loser_id, loser_name, reason)

def start_dynamite_flow(message, amount):
    user_id = message.from_user.id
    if not get_user(user_id):
        bot.reply_to(message, _start_first_err())
        return
    if amount <= 0:
        bot.reply_to(message, _casino_err("مقدار باید بزرگتر از صفر باشه"))
        return
    if get_balance(user_id) < amount:
        bot.reply_to(message, _casino_err("موجودی الماس کافی نداری"))
        return

    creator_name = get_display_name(message.from_user)
    update_diamonds(user_id, -amount)

    sent = safe_send_message(
        message.chat.id,
        dynamite_pending_text(amount, user_id, creator_name),
        parse_mode="HTML",
        reply_to_message_id=message.message_id,
    )
    if not sent:
        update_diamonds(user_id, amount)
        bot.reply_to(message, _casino_err("ارسال پنل دینامیت انجام نشد و مبلغ شرط به موجودی شما برگشت داده شد"))
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
        dynamite_pending_text(amount, user_id, creator_name),
        chat_id=message.chat.id, message_id=sent.message_id, reply_markup=dynamite_pending_markup(),
        parse_mode="HTML",
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
        bot.reply_to(message, _casino_err("فرمت اشتباه است. مثال: دینامیت 20 یا دینامیت 20k"))
        return
    amount = parse_amount(match.group(1))
    if amount is None:
        bot.reply_to(message, _casino_err("مبلغ نامعتبره"))
        return
    start_dynamite_flow(message, amount)

@bot.callback_query_handler(func=lambda call: call.data == "dyncancel")
def dynamite_cancel_callback(call):
    with dynamite_lock:
        message_id = call.message.message_id
        game = active_dynamites.get(message_id) or _dynamite_lazy_load(message_id)
        if not game:
            bot.answer_callback_query(call.id)
            return
        if game["status"] != "pending":
            bot.answer_callback_query(call.id)
            return
        if call.from_user.id != game["creator_id"]:
            bot.answer_callback_query(call.id)
            return
        update_diamonds(game["creator_id"], game["amount"])
        amount = game["amount"]
        chat_id = game["chat_id"]
        del active_dynamites[message_id]
    _dynamite_db_delete(message_id)
    e = _gift_emoji
    safe_edit_message(
        f'{e(5818704981179505821, "🎲")} بازی لغو شد.{e(5819154526816444042, "❌")}\n'
        f'{e(5830338333892418460, "💰")} {amount:,} الماس {e(5940725397195853882, "💎")} برگردونده شد.{e(5830144944399981619, "✅")}',
        chat_id=chat_id, message_id=message_id, reply_markup=None, parse_mode="HTML",
    )
    bot.answer_callback_query(call.id)

@bot.callback_query_handler(func=lambda call: call.data == "dynjoin")
def dynamite_join_callback(call):
    with dynamite_lock:
        message_id = call.message.message_id
        game = active_dynamites.get(message_id) or _dynamite_lazy_load(message_id)
        if not game:
            bot.answer_callback_query(call.id)
            return
        if game["status"] != "pending":
            bot.answer_callback_query(call.id)
            return
        clicker_id = call.from_user.id
        if clicker_id == game["creator_id"]:
            bot.answer_callback_query(call.id)
            return
        if not get_user(clicker_id):
            bot.answer_callback_query(call.id)
            return
        if get_balance(clicker_id) < game["amount"]:
            bot.answer_callback_query(call.id)
            return
        if update_diamonds(clicker_id, -game["amount"]) is None:
            bot.answer_callback_query(call.id)
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
    safe_edit_message(text, chat_id=chat_id, message_id=message_id, reply_markup=markup, parse_mode="HTML")
    bot.answer_callback_query(call.id)

@bot.callback_query_handler(func=lambda call: call.data.startswith("dyncell|"))
def dynamite_cell_reveal(call):
    with dynamite_lock:
        _dynamite_cell_reveal_locked(call)

def _dynamite_finish(message_id, game, winner_id, winner_name, loser_id, loser_name, middle_text, reveal_bomb=False):
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
                "p_loan_repay": 0,
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

    e = _gift_emoji
    text = (
        f'{e(5818704981179505821, "🎲")} نتیجه بازی {e(5888937012253171131, "🏁")}\n\n'
        f'{middle_text}\n'
        f'{e(5837050654811496370, "🏆")} برنده: {_dyn_name(winner_id, winner_name)}\n'
        f'{e(5856946687083290613, "🥈")} بازنده: {_dyn_name(loser_id, loser_name)}'
    )
    safe_edit_message(text, chat_id=chat_id, message_id=message_id,
                      reply_markup=dynamite_result_markup(payout, tax, game, reveal_bomb), parse_mode="HTML")

def _dynamite_cell_reveal_locked(call):
    message_id = call.message.message_id
    game = active_dynamites.get(message_id) or _dynamite_lazy_load(message_id)
    if not game or game["status"] != "active":
        bot.answer_callback_query(call.id)
        return

    clicker_id = call.from_user.id
    if clicker_id not in (game["creator_id"], game["opponent_id"]):
        bot.answer_callback_query(call.id)
        return
    if clicker_id != game["turn_id"]:
        bot.answer_callback_query(call.id)
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
        e = _gift_emoji
        middle_text = (
            f'{e(5839270298205035832, "💥")} بازیکن {_dyn_name(loser_id, loser_name)} منفجر شد'
            f'{e(5938458195629445238, "💣")}\u200f'
        )
        _dynamite_finish(message_id, game, winner_id, winner_name, loser_id, loser_name, middle_text, reveal_bomb=True)
        return

    game["revealed"].add(idx)
    game["safe_remaining"] -= 1
    game["turn_id"] = game["opponent_id"] if clicker_id == game["creator_id"] else game["creator_id"]
    start_turn_timer(message_id, game)

    _dynamite_db_upsert(message_id, game)
    text = dynamite_active_text(game)
    markup = dynamite_board_markup(game)
    safe_edit_message(text, chat_id=game["chat_id"], message_id=message_id, reply_markup=markup, parse_mode="HTML")

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
CASINO_MENU_TEXT = (
    f'{_gift_emoji(6012438204144165493, "🎰")} به بخش کازینو خوش اومدی!\n\n'
    f'{_gift_emoji(5818704981179505821, "🎮")} یکی از بازی‌ها رو انتخاب کن{_gift_emoji(5820903824046432799, "👇")}'
)
# آیکون پرمیوم دکمه‌های منوی کازینو (فوتبال آیکون ندارد و همان ⚽ می‌ماند)
CASINO_ICON_IDS = {
    "dice": "5875483791702630534",
    "dart": "5832335747088130009",
    "basket": "5929547568714359397",
    "bowling": "5929469353064931405",
    "slot": "5875360259853263196",
}
def _casino_err(text):
    return f'{html.escape(text)} {_gift_emoji(5819154526816444042, "❌")}'

def _start_first_err():
    return _casino_err("اول باید بات رو استارت کنی")


def html_escape_keep_emoji(text):
    """متن را برای HTML امن می‌کند ولی تگ‌های <tg-emoji> (ایموجی گیفت) را دست‌نخورده می‌گذارد."""
    parts = re.split(r'(<tg-emoji[^>]*>.*?</tg-emoji>)', str(text or ""))
    return "".join(p if p.startswith("<tg-emoji") else html.escape(p) for p in parts)


def casino_player_html(player):
    """اسم بازیکن برای پیام HTML (escape شده؛ ایموجی گیفت دست‌نخورده)."""
    if player.get("html_name"):
        return player["html_name"]
    return html_escape_keep_emoji(player.get("name") or "کاربر")


CASINO_SEND_PHRASES = {
    "basket": "بسکتبال های خودتون رو ارسال کنید.",
    "dice": "تاس های خودتون رو ارسال کنید.",
    "bowling": "بولینگ های خودتون رو ارسال کنید.",
    "slot": "اسلات های خودتون رو ارسال کنید.",
    "dart": "دارت های خودتون رو ارسال کنید.",
    "football": "توپ های فوتبال خودتون رو ارسال کنید.",
}


def casino_game_icon(game_key):
    e = _gift_emoji
    return e(int(CASINO_ICON_IDS[game_key]), CASINO_GAMES[game_key]) if game_key in CASINO_ICON_IDS else CASINO_GAMES[game_key]


def casino_game_title(game_key):
    """خط اول صفحه‌های کازینو: ایموجی + اسم بازی + آیکون بازی."""
    e = _gift_emoji
    return f'{e(5818704981179505821, "🎮")} {CASINO_PAGE_NAMES[game_key]} {casino_game_icon(game_key)}'


# اسم بازی‌ها برای صفحه‌ی «ارسال مبلغ شرط»
CASINO_PAGE_NAMES = {
    "dice": "تاس",
    "dart": "دارت",
    "basket": "بسکت",
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
            icon_id = CASINO_ICON_IDS.get(key)
            if icon_id:
                row.append(colored_button("\u2800", callback_data=f"cgame|{key}|{owner_id}", icon_custom_emoji_id=icon_id))
            else:
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
        CASINO_MENU_TEXT,
        chat_id=call.message.chat.id,
        message_id=call.message.message_id,
        reply_markup=casino_games_keyboard(owner_id),
        parse_mode="HTML"
    )

@bot.message_handler(func=lambda m: text_is(m, "کازینو"))
def casino_panel(message):
    if not get_user(message.from_user.id):
        bot.reply_to(message, _start_first_err())
        return
    show_or_edit_panel(
        message, message.from_user.id, "casino",
        CASINO_MENU_TEXT,
        casino_games_keyboard(message.from_user.id),
        parse_mode="HTML"
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

    e = _gift_emoji
    game_icon = e(int(CASINO_ICON_IDS[game_key]), CASINO_GAMES[game_key]) if game_key in CASINO_ICON_IDS else CASINO_GAMES[game_key]
    back_markup = types.InlineKeyboardMarkup()
    back_markup.row(back_button(callback_data=f"cback|{owner_id}"))
    safe_edit_message(
        f'{e(5818704981179505821, "🎮")} {CASINO_PAGE_NAMES[game_key]} {game_icon}\n\n'
        f'{e(5938311423712039050, "✍️")} مقدار الماسی که میخواید شرط ببندید رو ارسال کنید {e(5820903824046432799, "👇")}',
        chat_id=call.message.chat.id, message_id=call.message.message_id, reply_markup=back_markup, parse_mode="HTML"
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
    # اگر کاربر از صفحه‌ی «ارسال مبلغ» برگشت، منتظرماندن برای مبلغ را لغو کن
    with _next_step_lock:
        pending = _next_step_pending.pop((call.message.chat.id, owner_id), None)
    if pending and pending.get("timer"):
        try:
            pending["timer"].cancel()
        except Exception:
            pass
    safe_edit_message(
        CASINO_MENU_TEXT,
        chat_id=call.message.chat.id, message_id=call.message.message_id, reply_markup=casino_games_keyboard(owner_id), parse_mode="HTML"
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

    markup = None
    safe_edit_message(
        f'{_gift_emoji(5825656411517886523, "⏰")} زمان تموم شد {_gift_emoji(5938490450833838343, "⌛")}\n'
        f'{_gift_emoji(5830338333892418460, "💰")} {game["bet"]} الماس {_gift_emoji(5940725397195853882, "💎")} به سازنده برگردونده شد.',
        chat_id=game["chat_id"], message_id=msg_id, reply_markup=markup, parse_mode="HTML"
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
        bot.answer_callback_query(call.id)
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
            bot.answer_callback_query(call.id)
            return
        if game["player2"] is not None:
            bot.answer_callback_query(call.id)
            return
        if user_id != game["player1"]["id"]:
            bot.answer_callback_query(call.id)
            return

        if update_diamonds(game["player1"]["id"], game["bet"]) is None:
            logging.error(f"بازگرداندن شرط کازینو {msg_id} انجام نشد")
            return
        del active_casino_games[msg_id]
        if msg_id in casino_timers:
            casino_timers[msg_id].cancel()
            del casino_timers[msg_id]

    bot.answer_callback_query(call.id)
    markup = None
    safe_edit_message(
        f'{_gift_emoji(5818704981179505821, "🎮")} بازی لغو شد. {_gift_emoji(5819154526816444042, "❌")}\n'
        f'{_gift_emoji(5830338333892418460, "💰")} {game["bet"]} الماس {_gift_emoji(5940725397195853882, "💎")} برگردونده شد.',
        chat_id=game["chat_id"], message_id=msg_id, reply_markup=markup, parse_mode="HTML"
    )

@bot.callback_query_handler(func=lambda call: call.data == "casinoback")
def casino_back_to_list(call):
    bot.answer_callback_query(call.id)
    safe_edit_message(
        CASINO_MENU_TEXT,
        chat_id=call.message.chat.id,
        message_id=call.message.message_id,
        reply_markup=casino_games_keyboard(call.from_user.id),
        parse_mode="HTML"
    )

# ================== معدن الماس (مین‌زدن تکی) ==================
MINE_DIAMOND_EMOJI_ID = 5940725397195853882  # الماس
MINE_BOMB_EMOJI_ID = 5929177175029718803     # بمب

def _mine_title():
    e = _gift_emoji
    return f'{e(5818704981179505821, "⛏")} معدن الماس{e(5929177175029718803, "💣")}'

def mine_board_text(bet, found, multiplier, footer_line=None):
    e = _gift_emoji
    payout = int(bet * multiplier)
    not_found = (MINE_GRID_SIZE - 1) - found
    mult_str = f"{multiplier:.2f}x" if multiplier > 0 else ""
    if footer_line is None:
        footer_line = f'{e(5940725397195853882, "💎")} الماس هارو پیدا کن{e(5820903824046432799, "👇")}'
    return (
        f'{_mine_title()}\n\n'
        f'{e(5823445637231814311, "💰")} مبلغ ورودی : {bet:,}\n'
        f'{e(5940582340425159463, "💵")} مبلغ دریافتی : {payout:,} ({mult_str})\n\n'
        f'{e(5940396943866859681, "✅")} الماس های پیدا شده : {found}\n'
        f'{e(5942718468179628637, "❔")} الماس های پیدا نشده : {not_found}\n\n'
        f'{footer_line}'
    )

def mine_board_markup(revealed, owner_id):
    markup = types.InlineKeyboardMarkup()
    for row in range(3):
        buttons = []
        for col in range(3):
            idx = row * 3 + col
            if idx in revealed:
                buttons.append(colored_button("\u2800", callback_data=f"mine|{idx}|{owner_id}",
                                              icon_custom_emoji_id=str(MINE_DIAMOND_EMOJI_ID)))
            else:
                buttons.append(colored_button(" ", callback_data=f"mine|{idx}|{owner_id}"))
        markup.row(*buttons)
    markup.row(colored_button("برداشت الان", callback_data=f"minecashout|{owner_id}",
                              icon_custom_emoji_id="5830144944399981619"))
    return markup

def mine_final_markup(game, reveal_bomb=False):
    """صفحه‌ی ۳×۳ بعد از پایان بازی روی پیام می‌مونه (مثل دینامیت): الماس‌های باز‌شده
    می‌مونن و فقط در صورت انفجار، دکمه‌ی بمب قرمز می‌شه. دکمه‌ها بی‌اثرن."""
    markup = types.InlineKeyboardMarkup()
    for row in range(3):
        buttons = []
        for col in range(3):
            idx = row * 3 + col
            if reveal_bomb and idx == game["bomb_index"]:
                buttons.append(colored_button("\u2800", callback_data="noop", style="danger",
                                              icon_custom_emoji_id=str(MINE_BOMB_EMOJI_ID)))
            elif idx in game["revealed"]:
                buttons.append(colored_button("\u2800", callback_data="noop",
                                              icon_custom_emoji_id=str(MINE_DIAMOND_EMOJI_ID)))
            else:
                buttons.append(colored_button(" ", callback_data="noop"))
        markup.row(*buttons)
    return markup

@bot.message_handler(func=lambda m: text_is(m, "معدن الماس", "معدن"))
def mine_panel_entry(message):
    if not get_user(message.from_user.id):
        bot.reply_to(message, _start_first_err())
        return
    e = _gift_emoji
    panel_id = show_or_edit_panel(
        message, message.from_user.id, "mine",
        f'{_mine_title()}\n\n'
        f'{e(5816913107938712568, "✏️")} مقدار الماسی که میخواید شرط ببندید رو ارسال کنید{e(5820903824046432799, "👇")}',
        parse_mode="HTML",
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
    if not require_reply_to_panel(message, prompt_msg_id, _casino_err("برای شروع معدن، روی همین پنل ریپلای کن و مبلغ را بفرست")):
        register_timed_next_step_handler(message, mine_bet_step, expected_user_id, prompt_msg_id, expected_user_id=expected_user_id)
        return
    if message.from_user.id != expected_user_id:
        # پیام از یه نفر دیگه بود؛ نادیده می‌گیریم ولی منتظر پیام خودِ کاربر می‌مونیم
        register_timed_next_step_handler(message, mine_bet_step, expected_user_id, prompt_msg_id, expected_user_id=expected_user_id)
        return
    amount = parse_amount(message.text)
    if amount is None:
        safe_edit_message(_casino_err("مبلغ نامعتبره. روی همین پنل ریپلای کن و یه عدد درست بفرست (مثلاً 100000 یا 100k)"), message.chat.id, prompt_msg_id, reply_markup=None)
        register_timed_next_step_handler(message, mine_bet_step, expected_user_id, prompt_msg_id, expected_user_id=expected_user_id)
        return
    if get_balance(expected_user_id) < amount:
        safe_edit_message(_casino_err("موجودی کافی نیست. روی همین پنل ریپلای کن و مبلغ دیگه‌ای بفرست"), message.chat.id, prompt_msg_id, reply_markup=None)
        register_timed_next_step_handler(message, mine_bet_step, expected_user_id, prompt_msg_id, expected_user_id=expected_user_id)
        return

    update_diamonds(expected_user_id, -amount)
    bomb_index = random.randint(0, MINE_GRID_SIZE - 1)
    text = mine_board_text(amount, 0, 0.0)
    markup = mine_board_markup(set(), expected_user_id)
    # همون پیام اول (که مبلغ رو ازش پرسیده بودیم) ویرایش میشه، پیام جدید فرستاده نمیشه
    safe_edit_message(text, message.chat.id, prompt_msg_id, reply_markup=markup, parse_mode="HTML")
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
        bot.answer_callback_query(call.id)
        return
    idx = int(call.data.split("|")[1])
    if idx in game["revealed"]:
        bot.answer_callback_query(call.id)
        return
    bot.answer_callback_query(call.id)

    if idx == game["bomb_index"]:
        del active_mine_games[call.message.message_id]
        e = _gift_emoji
        not_found = (MINE_GRID_SIZE - 1) - game['diamonds_found']
        text = (
            f'{_mine_title()}\n\n'
            f'{e(5823445637231814311, "💰")} مبلغ ورودی : {game["bet"]:,} {e(5940725397195853882, "💎")}\n'
            f'{e(5940582340425159463, "💵")} مبلغ دریافتی : 0 {e(5940725397195853882, "💎")} (0.00x)\n\n'
            f'{e(5940396943866859681, "✅")} الماس های پیدا شده : {game["diamonds_found"]}\n'
            f'{e(5942718468179628637, "❔")} الماس های پیدا نشده : {not_found}\n\n'
            f'{e(5884330316230827477, "💥")} بووووممم{e(5929177175029718803, "💣")}\n\n'
            f'{e(5856946687083290613, "❌")} باختی کل الماس شرط از دست رفت {e(5848202125078699135, "💸")}'
        )
        safe_edit_message(text, call.message.chat.id, call.message.message_id,
                          reply_markup=mine_final_markup(game, reveal_bomb=True), parse_mode="HTML")
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
            except Exception as ex:
                logging.error(f"خطا در پرداخت اتمیک معدن {owner_id}: {ex}")
                return
        else:
            update_diamonds(owner_id, payout)
        del active_mine_games[call.message.message_id]
        e = _gift_emoji
        text = mine_board_text(
            game["bet"], game["diamonds_found"], multiplier,
            footer_line=(f'{e(5830338333892418460, "💰")} بنازم همه‌ی الماس‌ها رو پیدا کردی مبلغ {payout:,} '
                         f'الماس{e(5940725397195853882, "💎")} به حسابت اضافه شد.{e(5830144944399981619, "✅")}')
        )
        safe_edit_message(text, call.message.chat.id, call.message.message_id,
                          reply_markup=mine_final_markup(game), parse_mode="HTML")
        return

    text = mine_board_text(game["bet"], game["diamonds_found"], multiplier)
    markup = mine_board_markup(game["revealed"], owner_id)
    safe_edit_message(text, call.message.chat.id, call.message.message_id, reply_markup=markup, parse_mode="HTML")

@bot.callback_query_handler(func=lambda call: call.data.startswith("minecashout|"))
def mine_cash_out(call):
    with mine_lock:
        _mine_cash_out_locked(call)

def _mine_cash_out_locked(call):
    owner_id = check_panel_owner(call)
    if owner_id is None:
        return
    game = active_mine_games.get(call.message.message_id)
    if not game or game["diamonds_found"] == 0:
        bot.answer_callback_query(call.id)
        return
    bot.answer_callback_query(call.id)
    multiplier = game["diamonds_found"] * MINE_MULTIPLIER_STEP
    payout = int(game["bet"] * multiplier)
    if ATOMIC_DB_MODE:
        try:
            supabase.rpc("atomic_mine_payout", {"p_user_id": int(owner_id), "p_payout": int(payout)}).execute()
        except Exception as ex:
            logging.error(f"خطا در پرداخت اتمیک معدن {owner_id}: {ex}")
            return
    else:
        update_diamonds(owner_id, payout)
    del active_mine_games[call.message.message_id]
    e = _gift_emoji
    text = mine_board_text(
        game["bet"], game["diamonds_found"], multiplier,
        footer_line=(f'{e(5830338333892418460, "💰")} برداشت انجام شد {payout:,} '
                     f'الماس{e(5940725397195853882, "💎")} به حسابت اضافه شد.{e(5830144944399981619, "✅")}')
    )
    safe_edit_message(text, call.message.chat.id, call.message.message_id,
                      reply_markup=mine_final_markup(game), parse_mode="HTML")

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
    if not require_reply_to_panel(message, panel_msg_id, _casino_err("برای ثبت مبلغ، روی همین پیام کازینو ریپلای کن و مبلغ را بفرست")):
        register_timed_next_step_handler(message, casino_custom_amount_step, game_key, expected_user_id, panel_msg_id, expected_user_id=expected_user_id)
        return

    amount = parse_amount(message.text)
    if amount is None:
        safe_edit_message(_casino_err("مبلغ نامعتبره. روی همین پنل ریپلای کن و مبلغ درست بفرست؛ مثال: 250 یا 250k"), message.chat.id, panel_msg_id, reply_markup=None)
        register_timed_next_step_handler(message, casino_custom_amount_step, game_key, expected_user_id, panel_msg_id, expected_user_id=expected_user_id)
        return

    if amount <= 0:
        safe_edit_message(_casino_err("مبلغ باید بزرگتر از صفر باشه. روی همین پنل ریپلای کن و دوباره بفرست"), message.chat.id, panel_msg_id, reply_markup=None)
        register_timed_next_step_handler(message, casino_custom_amount_step, game_key, expected_user_id, panel_msg_id, expected_user_id=expected_user_id)
        return

    user = message.from_user
    if get_balance(user.id) < amount:
        safe_edit_message(_casino_err("موجودی الماس شما کافی نیست"), message.chat.id, panel_msg_id, reply_markup=None)
        return

    update_diamonds(user.id, -amount)

    markup = types.InlineKeyboardMarkup()
    markup.row(
        colored_button("پیوستن", callback_data="cjoin", icon_custom_emoji_id="5938109560249127910"),
        colored_button("لغو", callback_data=f"ccancel|{panel_msg_id}", icon_custom_emoji_id="5819154526816444042"),
    )

    e = _gift_emoji
    text = (
        f'{casino_game_title(game_key)}\n\n'
        f'{e(5823445637231814311, "💰")} مقدار الماس : {amount} الماس {e(5940725397195853882, "💎")}\n\n'
        f'{e(5843973755545590553, "👤")} سازنده : {safe_html_name(user)}'
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
            "player1": {"id": user.id, "name": get_display_name(user), "html_name": safe_html_name(user)},
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
            bot.answer_callback_query(call.id)
            return
        if game["player2"] is not None:
            bot.answer_callback_query(call.id)
            return

        user = call.from_user
        if user.id == game["player1"]["id"]:
            bot.answer_callback_query(call.id)
            return
        if not get_user(user.id):
            bot.answer_callback_query(call.id, "اول /start بزن.", show_alert=True)
            return
        if get_balance(user.id) < game["bet"]:
            bot.answer_callback_query(call.id)
            return

        reserved = update_diamonds(user.id, -game["bet"])
        if reserved is None:
            bot.answer_callback_query(call.id)
            return
        game["player2"] = {"id": user.id, "name": get_display_name(user), "html_name": safe_html_name(user)}
        if msg_id in casino_timers:
            casino_timers[msg_id].cancel()
            del casino_timers[msg_id]

    bot.answer_callback_query(call.id)
    e = _gift_emoji
    safe_edit_message(
        f'{casino_game_title(game["game"])}\n\n'
        f'{e(5823445637231814311, "💰")} مقدار الماس : {game["bet"]} الماس{e(5940725397195853882, "💎")}\n'
        f'{e(5843973755545590553, "👤")} سازنده : {casino_player_html(game["player1"])}\n'
        f'{e(5859432880442187580, "👥")} شرکت کننده : {casino_player_html(game["player2"])}\n\n'
        f'{e(5857454223368657979, "🎯")} {CASINO_SEND_PHRASES[game["game"]]} {e(5820903824046432799, "👇")}',
        chat_id=game["chat_id"], message_id=msg_id, reply_markup=None, parse_mode="HTML"
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
        e = _gift_emoji
        p1_display = casino_player_html(player1)
        p2_display = casino_player_html(player2)
        result_text = (
            f'{e(5818704981179505821, "🎮")} شرط تموم شد {casino_game_icon(game["game"])}\n\n'
            f'{e(5823445637231814311, "💰")} مبلغ: {bet} الماس{e(5940725397195853882, "💎")}\n\n'
            f'{e(5816571237131885795, "⚔️")} {p1_display} در برابر {p2_display}\n'
            f'{e(5818716826699307883, "🤝")} بازی مساوی شد\n'
            f'{e(5938348905891632091, "📊")} امتیاز {p1_display} : {score1}\n'
            f'{e(5938348905891632091, "📊")} امتیاز {p2_display} : {score2}\n\n'
            f'{e(5823445637231814311, "💰")} مبلغ شرط به هر دو نفر برگشت داده شد. {e(5830144944399981619, "✅")}'
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
                        "p_loan_repay": 0,
                        "p_tax_receiver_id": int(TAX_RECEIVER_ID) if get_user(TAX_RECEIVER_ID) else None,
                        "p_draw_user_ids": None,
                    }).execute().data
                    if not result:
                        raise RuntimeError("empty casino settlement")
                    row = result[0] if isinstance(result, list) else result
                    final_amount = int(row.get("payout", final_amount) or 0)
                    tax = int(row.get("tax", tax) or 0)
                    loan_repay = 0
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
            loan_rate_used = 0

        e = _gift_emoji
        p1_display = casino_player_html(player1)
        p2_display = casino_player_html(player2)
        winner_display = casino_player_html(winner)
        loser_display = casino_player_html(loser)
        result_text = (
            f'{e(5818704981179505821, "🎮")} بازی تموم شد {casino_game_icon(game["game"])}\n\n'
            f'{e(5816571237131885795, "⚔️")} {p1_display} در برابر {p2_display}\n\n'
            f'{e(6014651259057873388, "🏆")} برنده با {w_score} امتیاز : {winner_display}\n'
            f'{e(5839270298205035832, "🥈")} بازنده با {l_score} امتیاز : {loser_display}'
        )
        result_markup = types.InlineKeyboardMarkup()
        win_amount = final_amount if final_amount is not None else 0
        result_markup.row(colored_button(f"مبلغ برد: {win_amount:,}", callback_data="bet_result_noop", icon_custom_emoji_id="5823445637231814311"))
        result_markup.row(colored_button(f"مالیات: {tax:,}", callback_data="bet_result_noop", icon_custom_emoji_id="5889002570633977838"))

    safe_edit_message(result_text, chat_id=chat_id, message_id=msg_id, reply_markup=result_markup, parse_mode="HTML")


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

# آیدی ایموجی پرمیوم هر رتبه: ۱، ۲، ۳ هرکدوم مخصوص خودشون؛ از ۴ به بعد همه یکسان (بدون عدد)
RANK_EMOJI_IDS = {1: 5832692422647226240, 2: 5834620746999012948, 3: 5832346686369832003}
RANK_DEFAULT_EMOJI_ID = 5836866392124563486
RANK_FALLBACK_EMOJIS = {1: "🥇", 2: "🥈", 3: "🥉"}

def _rank_emoji(idx):
    return _gift_emoji(RANK_EMOJI_IDS.get(idx, RANK_DEFAULT_EMOJI_ID), RANK_FALLBACK_EMOJIS.get(idx, "🏅"))

def _rank_page_text(page, user_id):
    e = _gift_emoji
    rows = _rank_rows()
    total = len(rows)
    start = (page - 1) * RANK_PAGE_SIZE
    page_rows = rows[start:start + RANK_PAGE_SIZE]

    text = (
        f'{e(5818913299978263825, "🏆")} رتبه بندی جهانی {e(5938398023137628324, "🌍")}\n\n'
        f'{e(5938515112536051725, "💎")} رتبه بندی ثروتمند ترین ها\n\n'
    )
    for idx, row in enumerate(page_rows, start + 1):
        name = html_escape_keep_emoji(display_name_with_tag(row.get("user_id"), _rank_name(row)))
        diamonds = int(row.get("diamonds") or 0)
        text += f'{_rank_emoji(idx)} {name}\n'
        text += f'┘─ {e(5823445637231814311, "💰")} الماس ها : {diamonds:,} {e(5940725397195853882, "💎")}\n\n'

    my_rank = _user_global_rank(user_id, rows)
    text += f'{e(5845858434439716957, "🎖")} رتبه شما : {my_rank}'
    return text, total

def _rank_markup(page, total, user_id):
    markup = types.InlineKeyboardMarkup()
    max_page = max(1, (total + RANK_PAGE_SIZE - 1) // RANK_PAGE_SIZE)

    if page < max_page:
        markup.row(
            colored_button(
                "بعدی",
                callback_data=f"rankpage|{page + 1}|{user_id}",
                icon_custom_emoji_id="5843732253829503840",
            )
        )
    if page > 1:
        markup.row(
            colored_button(
                "قبلی",
                callback_data=f"rankpage|{page - 1}|{user_id}",
                icon_custom_emoji_id="5845874566336880660",
            )
        )
    return markup

def _send_rank(message):
    rows = _rank_rows()
    if not rows:
        show_or_edit_panel(message, message.from_user.id, "rank", "هنوز کاربری ثبت‌نام نکرده.", None)
        return
    text, total = _rank_page_text(1, message.from_user.id)
    show_or_edit_panel(message, message.from_user.id, "rank", text, _rank_markup(1, total, message.from_user.id), parse_mode="HTML")

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
        bot.answer_callback_query(call.id)
        return

    if call.from_user.id != owner_id:
        bot.answer_callback_query(call.id)
        return

    bot.answer_callback_query(call.id)
    text, total = _rank_page_text(page, owner_id)
    safe_edit_message(
        text,
        call.message.chat.id,
        call.message.message_id,
        reply_markup=_rank_markup(page, total, owner_id),
        parse_mode="HTML"
    )

# ================== جواهری / انگشترسازی ==================
# نسخه جدید: هر الماس انگشتر = یک انگشتر. هر انگشتر ۹۰ دقیقه زمان ساخت دارد.
# مدل/سطح هر انگشتر هنگام شروع ساخت به‌صورت شانسی تعیین می‌شود.
JEWELRY_PENDING_CUSTOM = {}
JEWELRY_CUSTOM_TIMERS = {}
JEWELRY_TIMER_INTERVAL = 10
JEWELRY_CUSTOM_TIMEOUT = 60

def _expire_jewelry_custom(user_id):
    panel = JEWELRY_PENDING_CUSTOM.pop(user_id, None)
    JEWELRY_CUSTOM_TIMERS.pop(user_id, None)
    if panel:
        try:
            safe_edit_message(
                "⏰ زمان وارد کردن تعداد انگشتر تمام شد. دوباره «جواهری» را بزنید.",
                panel[0], panel[1]
            )
        except Exception:
            pass


def _jewelry_choose_gem():
    tier = random.choices(
        [x[0] for x in JEWELRY_TIER_WEIGHTS],
        weights=[x[1] for x in JEWELRY_TIER_WEIGHTS],
        k=1,
    )[0]
    return random.choice(JEWELRY_TIER_GEMS[tier])


def _jewelry_now():
    return datetime.utcnow()


def _format_jewelry_duration(seconds):
    seconds = max(0, int(seconds))
    days, rem = divmod(seconds, 86400)
    hours, rem = divmod(rem, 3600)
    minutes, secs = divmod(rem, 60)
    if days:
        return f"{days} روز و {hours} ساعت و {minutes} دقیقه"
    return f"{hours:02d}:{minutes:02d}:{secs:02d}"


def _jewelry_ready_orders(user_id):
    try:
        rows = supabase.table("jewelry_orders").select(
            "id,user_id,chat_id,panel_message_id,notified,quantity,gem_key,payout_total,finish_at,claimed"
        ).eq("user_id", user_id).eq("claimed", False).lte("finish_at", _jewelry_now().isoformat()).order("finish_at").execute()
        return rows.data or []
    except Exception as e:
        logging.error(f"خطا در دریافت انگشترهای آماده {user_id}: {e}")
        return []


def _jewelry_active_orders(user_id):
    try:
        rows = supabase.table("jewelry_orders").select(
            "id,user_id,chat_id,panel_message_id,notified,quantity,gem_key,payout_total,finish_at,claimed"
        ).eq("user_id", user_id).eq("claimed", False).gt("finish_at", _jewelry_now().isoformat()).order("finish_at").execute()
        return rows.data or []
    except Exception as e:
        logging.error(f"خطا در دریافت ساخت‌های فعال {user_id}: {e}")
        return []


def _jewelry_ready_text(rows):
    from collections import Counter
    counts = Counter()
    total = 0
    for row in rows:
        gem = JEWELRY_GEMS.get(row.get("gem_key"), JEWELRY_GEMS["agate"])
        qty = int(row.get("quantity", 1) or 1)
        counts[row.get("gem_key", "agate")] += qty
        total += int(row.get("payout_total", 0) or 0)
    lines = [f"💍 {sum(counts.values())} انگشتر با موفقیت ساخته شد! ✅", ""]
    for gem_key, qty in counts.items():
        gem = JEWELRY_GEMS.get(gem_key, JEWELRY_GEMS["agate"])
        lines.append(f"• {gem['name']} {gem['emoji']} × {qty}")
    lines.extend(["", f"💎 مبلغ کل قابل برداشت: {total:,} الماس", "", "برای برداشت، دکمه زیر را بزنید. 👇"])
    return "\n".join(lines), total


def _jewelry_ready_markup(user_id, total):
    markup = types.InlineKeyboardMarkup()
    if total > 0:
        markup.add(colored_button(
            f"🌹 برداشت {total:,} 💎",
            callback_data=f"jewel_claim|{user_id}"
        ))
    return markup


def _jewelry_build_markup(user_id):
    markup = types.InlineKeyboardMarkup(row_width=2)
    buttons = [
        colored_button("1 انگشتر 💍", callback_data=f"jewel_build|1|{user_id}"),
        colored_button("2 انگشتر 💍", callback_data=f"jewel_build|2|{user_id}"),
        colored_button("3 انگشتر 💍", callback_data=f"jewel_build|3|{user_id}"),
        colored_button("5 انگشتر 💍", callback_data=f"jewel_build|5|{user_id}"),
        colored_button("تعداد دلخواه 💎", callback_data=f"jewel_custom|{user_id}"),
    ]
    markup.add(*buttons[:2])
    markup.add(*buttons[2:4])
    markup.add(buttons[4])
    return markup


def _jewelry_build_text():
    return (
        "💍 ساخت انگشتر\n\n"
        "تعداد الماس مد نظر خود را برای تبدیل به انگشتر انتخاب کنید 💎"
    )


def _jewelry_active_text(rows):
    if not rows:
        return None
    remaining = max(
        0,
        int((max(
            datetime.fromisoformat(str(r["finish_at"]).replace("Z", "+00:00")).replace(tzinfo=None)
            for r in rows
        ) - _jewelry_now()).total_seconds())
    )
    return (
        "💍 ساخت انگشتر\n\n"
        f"تعداد انگشتر درحال ساخت {len(rows)} عدد 💍\n"
        f"زمان باقی‌مانده تا پایان همه: {_format_jewelry_duration(remaining)} ⏳"
    )


def _show_jewelry_main(chat_id, message_id, user_id):
    """پنل جواهری را با اولویت ساخت فعال و سپس انگشترهای آماده نمایش می‌دهد."""
    active = _jewelry_active_orders(user_id)
    if active:
        safe_edit_message(_jewelry_active_text(active), chat_id, message_id, reply_markup=None)
        return
    ready = _jewelry_ready_orders(user_id)
    if ready:
        text, total = _jewelry_ready_text(ready)
        # در صورت آماده بودن، پنل دقیقاً برای برداشت ساخته‌شده‌هاست.
        safe_edit_message(text, chat_id, message_id, reply_markup=_jewelry_ready_markup(user_id, total))
    else:
        safe_edit_message(_jewelry_build_text(), chat_id, message_id, reply_markup=_jewelry_build_markup(user_id))


def _start_jewelry_build(call, user_id, qty):
    try:
        if qty <= 0:
            raise ValueError
        user = get_user(user_id)
        available = int((user or {}).get("ring_diamonds", 0) or 0)
        if available < qty:
            bot.answer_callback_query(call.id, f"الماس انگشتر کافی نداری. موجودی: {available:,} 💎", show_alert=True)
            return

        now = _jewelry_now()
        orders = []
        for i in range(qty):
            gem_key = _jewelry_choose_gem()
            gem = JEWELRY_GEMS[gem_key]
            finish_at = now + timedelta(seconds=(i + 1) * JEWELRY_WORK_SECONDS)
            orders.append({
                "user_id": int(user_id),
                "chat_id": int(call.message.chat.id),
                "panel_message_id": int(call.message.message_id),
                "notified": False,
                "quantity": 1,
                "gem_key": gem_key,
                "payout_total": int(gem["price"]),
                "finish_at": finish_at.isoformat(),
                "claimed": False,
            })

        if ATOMIC_DB_MODE:
            result = supabase.rpc("atomic_start_jewelry_build", {
                "p_user_id": int(user_id),
                "p_orders": orders,
            }).execute().data
            if not result:
                raise RuntimeError("atomic_start_jewelry_build failed")
        else:
            new_balance = available - qty
            supabase.table("users").update({"ring_diamonds": new_balance}).eq("user_id", user_id).execute()
            resp = supabase.table("jewelry_orders").insert(orders).execute()
            if not resp.data or len(resp.data) != qty:
                supabase.table("users").update({"ring_diamonds": available}).eq("user_id", user_id).execute()
                raise RuntimeError("ثبت سفارش کامل نشد")

        if getattr(call, "id", None):
            bot.answer_callback_query(call.id, "ساخت انگشتر شروع شد! 💍")
        active = _jewelry_active_orders(user_id)
        safe_edit_message(_jewelry_active_text(active), call.message.chat.id, call.message.message_id, reply_markup=None)
    except Exception as e:
        logging.error(f"خطا در شروع ساخت انگشتر {user_id}: {e}")
        if getattr(call, "id", None):
            bot.answer_callback_query(call.id, "خطایی در شروع ساخت رخ داد.", show_alert=True)
        else:
            bot.send_message(call.message.chat.id, "❌ خطایی در شروع ساخت رخ داد.")


@bot.message_handler(func=lambda m: text_is(m, "انگشتر سازی", "انگشترسازی", "زرگری", "جواهری"))
def text_jewelry(message):
    user_id = message.from_user.id
    # اگر همین کاربر در مرحله وارد کردن تعداد دلخواه است، همان پیام فقط برای خودش مصرف شود.
    if user_id in JEWELRY_PENDING_CUSTOM:
        jewelry_custom_amount(message)
        return
    if not get_user(user_id):
        bot.reply_to(message, "اول /start بزن.")
        return
    active = _jewelry_active_orders(user_id)
    if active:
        show_or_edit_panel(message, user_id, "jewelry", _jewelry_active_text(active), None)
        return
    ready = _jewelry_ready_orders(user_id)
    if ready:
        text, total = _jewelry_ready_text(ready)
        show_or_edit_panel(message, user_id, "jewelry", text, _jewelry_ready_markup(user_id, total))
    else:
        show_or_edit_panel(message, user_id, "jewelry", _jewelry_build_text(), _jewelry_build_markup(user_id))


@bot.callback_query_handler(func=lambda call: call.data.startswith("jewel_build|"))
def jewelry_build(call):
    parts = call.data.split("|")
    if len(parts) != 3:
        return
    user_id = check_panel_owner(call)
    if user_id is None:
        return
    try:
        # فرمت امن: jewel_build|تعداد|شناسه_صاحب_پنل
        qty = int(parts[1])
    except ValueError:
        bot.answer_callback_query(call.id, "تعداد نامعتبر است.", show_alert=True)
        return
    _start_jewelry_build(call, user_id, qty)


@bot.callback_query_handler(func=lambda call: call.data.startswith("jewel_custom|"))
def jewelry_custom_prompt(call):
    user_id = check_panel_owner(call)
    if user_id is None:
        return
    JEWELRY_PENDING_CUSTOM[user_id] = (call.message.chat.id, call.message.message_id)
    old_timer = JEWELRY_CUSTOM_TIMERS.pop(user_id, None)
    if old_timer:
        old_timer.cancel()
    timer = threading.Timer(JEWELRY_CUSTOM_TIMEOUT, _expire_jewelry_custom, args=(user_id,))
    timer.daemon = True
    JEWELRY_CUSTOM_TIMERS[user_id] = timer
    timer.start()
    bot.answer_callback_query(call.id)
    safe_edit_message(
        "💍 ساخت انگشتر\n\n"
        "تعداد الماس مورد نظر را به صورت یک عدد ارسال کن 💎\n\n"
        "مثال: 10",
        call.message.chat.id,
        call.message.message_id,
        reply_markup=None,
    )


@bot.message_handler(func=lambda m: m.from_user and m.from_user.id in JEWELRY_PENDING_CUSTOM)
def jewelry_custom_amount(message):
    user_id = message.from_user.id
    panel = JEWELRY_PENDING_CUSTOM.pop(user_id, None)
    timer = JEWELRY_CUSTOM_TIMERS.pop(user_id, None)
    if timer:
        timer.cancel()
    if not panel:
        return
    panel_msg_id = panel[1]
    if not require_reply_to_panel(message, panel_msg_id, "برای ساخت انگشتر، روی همین پنل جواهری ریپلای کن و تعداد را بفرست."):
        JEWELRY_PENDING_CUSTOM[user_id] = panel
        return
    qty = parse_amount(message.text or "")
    if qty is None or qty <= 0:
        JEWELRY_PENDING_CUSTOM[user_id] = panel
        safe_edit_message("❌ تعداد نامعتبره. روی همین پنل ریپلای کن و فقط عدد مثبت بفرست؛ مثلاً 10", message.chat.id, panel_msg_id, reply_markup=None)
        return
    available = int((get_user(user_id) or {}).get("ring_diamonds", 0) or 0)
    if available < qty:
        JEWELRY_PENDING_CUSTOM[user_id] = panel
        safe_edit_message(f"❌ الماس انگشتر کافی نداری. موجودی: {available:,} 💎", message.chat.id, panel_msg_id, reply_markup=None)
        return
    # برای استفاده از همان منطق ثبت سفارش، یک شیء سبک با APIهای موردنیاز می‌سازیم.
    class _PanelCall:
        pass
    call = _PanelCall()
    call.id = None
    call.from_user = message.from_user
    call.message = types.Message.de_json(message.json)
    call.message.chat.id = panel[0]
    call.message.message_id = panel[1]
    _start_jewelry_build(call, user_id, qty)


# این هندلر بعد از دریافت تعداد دلخواه، پنل قبلی را به وضعیت ساخت تبدیل می‌کند.
# _start_jewelry_build برای callback از answer_callback_query استفاده می‌کند؛ برای پیام متنی آن را نادیده می‌گیریم.


@bot.callback_query_handler(func=lambda call: call.data.startswith("jewel_claim|"))
def jewelry_claim(call):
    user_id = check_panel_owner(call)
    if user_id is None:
        return
    try:
        rows = _jewelry_ready_orders(user_id)
        total = sum(int(r.get("payout_total", 0) or 0) for r in rows)
        if total <= 0:
            bot.answer_callback_query(call.id, "هنوز انگشتر آماده‌ای برای دریافت نداری.", show_alert=True)
            return
        if ATOMIC_DB_MODE:
            result = supabase.rpc("atomic_claim_jewelry", {"p_user_id": int(user_id)}).execute().data
            if not result:
                bot.answer_callback_query(call.id, "دریافت جواهرات انجام نشد.", show_alert=True)
                return
            row = result[0] if isinstance(result, list) else result
            total = int(row.get("total_payout", total) or 0)
            if total <= 0:
                bot.answer_callback_query(call.id, "هنوز انگشتر آماده‌ای برای دریافت نداری.", show_alert=True)
                return
        else:
            ids = [r["id"] for r in rows]
            supabase.table("jewelry_orders").update({"claimed": True}).in_("id", ids).eq("user_id", user_id).execute()
            update_diamonds(user_id, total)
        bot.answer_callback_query(call.id, f"{total:,} 💎 دریافت شد!")
        # بعد از برداشت، دوباره پنل ساخت نمایش داده شود.
        safe_edit_message(_jewelry_build_text(), call.message.chat.id, call.message.message_id, _jewelry_build_markup(user_id))
    except Exception as e:
        logging.error(f"خطا در دریافت جواهرات {user_id}: {e}")
        bot.answer_callback_query(call.id, "خطایی رخ داد. دوباره امتحان کن.", show_alert=True)


def process_jewelry_orders():
    """هر ۱۰ ثانیه تایمر پنل‌ها را تازه می‌کند و سفارش‌های تمام‌شده را به PV اعلام می‌کند."""
    try:
        now = _jewelry_now()
        active_rows = supabase.table("jewelry_orders").select(
            "id,user_id,chat_id,panel_message_id,notified,quantity,gem_key,payout_total,finish_at,claimed"
        ).eq("claimed", False).gt("finish_at", now.isoformat()).execute()
        by_panel = {}
        for row in (active_rows.data or []):
            key = (row.get("chat_id"), row.get("panel_message_id"), row.get("user_id"))
            by_panel.setdefault(key, []).append(row)

        for (chat_id, panel_message_id, user_id), rows in by_panel.items():
            if chat_id and panel_message_id:
                try:
                    safe_edit_message(_jewelry_active_text(rows), chat_id, panel_message_id, reply_markup=None)
                except Exception as e:
                    logging.debug(f"تازه‌سازی تایمر جواهری ناموفق بود: {e}")

        ready_rows = supabase.table("jewelry_orders").select(
            "id,user_id,chat_id,panel_message_id,notified,quantity,gem_key,payout_total,finish_at,claimed"
        ).eq("claimed", False).lte("finish_at", now.isoformat()).execute()
        for row in (ready_rows.data or []):
            if not row.get("notified", False):
                gem = JEWELRY_GEMS.get(row.get("gem_key"), JEWELRY_GEMS["agate"])
                try:
                    bot.send_message(
                        row["user_id"],
                        f"💍 انگشتر شما با موفقیت ساخته شد! ✅\n\n"
                        f"مدل : {gem['name']} {gem['emoji']}\n"
                        f"سطح : {gem['tier']} 🎖️\n"
                        f"قیمت : {int(row.get('payout_total', 0) or 0):,} الماس 💎\n\n"
                        "برای مشاهده و برداشت، در چت بنویس: جواهری 💍"
                    )
                    supabase.table("jewelry_orders").update({"notified": True}).eq("id", row["id"]).execute()
                except Exception as e:
                    logging.error(f"خطا در ارسال اعلان PV انگشتر {row.get('id')}: {e}")

        # اگر همه سفارش‌های یک پنل تمام شده‌اند، پنل به وضعیت انگشترهای آماده تبدیل می‌شود.
        panel_keys = set()
        for row in (ready_rows.data or []):
            if row.get("chat_id") and row.get("panel_message_id"):
                panel_keys.add((row["chat_id"], row["panel_message_id"], row["user_id"]))
        for chat_id, panel_message_id, user_id in panel_keys:
            if not _jewelry_active_orders(user_id):
                ready = _jewelry_ready_orders(user_id)
                if ready and chat_id and panel_message_id:
                    text, total = _jewelry_ready_text(ready)
                    safe_edit_message(text, chat_id, panel_message_id, _jewelry_ready_markup(user_id, total))
    except Exception as e:
        logging.error(f"خطا در پردازش سفارش‌های جواهری: {e}")


# زمان‌بندی مستقل جواهری؛ با ری‌استارت بات نیز سفارش‌ها از دیتابیس دوباره خوانده می‌شوند.
jewelry_scheduler = BackgroundScheduler(timezone=TEHRAN_TZ)
jewelry_scheduler.add_job(
    process_jewelry_orders,
    "interval",
    seconds=JEWELRY_TIMER_INTERVAL,
    id="jewelry_orders_processor",
    replace_existing=True,
    max_instances=1,
    coalesce=True,
)
jewelry_scheduler.start()

# ================== موجودی ==================
@bot.message_handler(commands=["balance", "موجودی"])
def cmd_balance(message):
    show_balance(message)

@bot.message_handler(func=lambda m: text_is(m, "موجودی"))
def text_balance(message):
    show_balance(message)

def _glass_balance_button(balance):
    """دکمه‌ی آبی با عدد موجودی (با جداکننده‌ی هزارگان) و ایموجی پرمیوم الماس."""
    return colored_button(f"{int(balance or 0):,}", callback_data="pending",
                          style="primary", icon_custom_emoji_id="5940725397195853882")

def show_balance(message):
    user_id = message.from_user.id
    if not get_user(user_id):
        bot.reply_to(message, _start_first_err())
        return

    if message.reply_to_message:
        target_id = message.reply_to_message.from_user.id
        if not get_user(target_id):
            bot.reply_to(message, "این کاربر هنوز /start نزده، نمی‌تونم موجودیش رو ببینم.")
            return
        target_name = get_display_name(message.reply_to_message.from_user)
        balance = get_balance(target_id)
        e = _gift_emoji
        text = f'{e(5823445637231814311, "💰")} موجودی الماس{e(5940725397195853882, "💎")} {html_escape_keep_emoji(target_name)}'
        markup = types.InlineKeyboardMarkup()
        markup.add(_glass_balance_button(balance))
        show_or_edit_panel(message, user_id, "balance", text, markup, parse_mode="HTML")
    else:
        balance = get_balance(user_id)
        e = _gift_emoji
        text = f'{e(5823445637231814311, "💰")} موجودی الماس{e(5940725397195853882, "💎")} شما'
        markup = types.InlineKeyboardMarkup()
        markup.add(_glass_balance_button(balance))
        show_or_edit_panel(message, user_id, "balance", text, markup, parse_mode="HTML")


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
    markup.add(colored_button("📢 پیام همگانی", callback_data="admin_broadcast"))
    markup.add(colored_button("➕ افزودن الماس به همه", callback_data="admin_add_diamond_all"))
    markup.add(colored_button("➖ کم کردن الماس از همه", callback_data="admin_remove_diamond_all"))
    markup.add(colored_button("🎁 ساخت کد هدیه", callback_data="admin_create_giftcode"))
    bot.reply_to(message, text, reply_markup=markup)

@bot.message_handler(func=lambda m: text_is(m, "مدیریت"))
def text_admin(message):
    cmd_admin(message)


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
# قرار است مبلغ یک مرحله‌ی در انتظار (شرط، بانک، کازینو و...) باشد.
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

# ================== Webhook / Render ==================
@app.route("/", methods=["GET", "HEAD"])
def health_check():
    return "Bot is running!", 200

@app.route("/webhook", methods=["GET", "POST"])
def webhook():
    # GET is intentionally supported so the Render URL can be checked in a browser.
    if request.method == "GET":
        return "Webhook endpoint is alive", 200

    if TELEGRAM_WEBHOOK_SECRET:
        provided = request.headers.get("X-Telegram-Bot-Api-Secret-Token", "")
        if provided != TELEGRAM_WEBHOOK_SECRET:
            return "Forbidden", 403

    try:
        update_json = request.get_json(silent=True)
        if not update_json:
            return "Bad Request", 400

        update = telebot.types.Update.de_json(update_json)

        # اول خود آپدیت را به TeleBot بده تا هندلرهای کلمات و دکمه‌ها
        # بدون وابستگی به سیستم شمارش الماس اجرا شوند.
        incoming_message = getattr(update, "message", None)
        if incoming_message is not None and getattr(incoming_message, "text", None):
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

        # شمارش پیام‌های گروه بعد از پردازش اصلی بات؛ اگر این بخش خطا بدهد
        # دریافت و اجرای هندلرهای اصلی بات مختل نمی‌شود.
        if incoming_message is not None:
            try:
                process_group_message_for_diamond_hunt(incoming_message)
            except Exception as e:
                logging.error(f"خطا در شمارش پیام گروه برای الماس: {e}")

        return "OK", 200
    except Exception as e:
        logging.exception("Telegram webhook update processing failed: %s", e)
        # خطای داخلی نباید باعث retry بی‌نهایت Telegram شود.
        return "OK", 200

# ================== اجرا ==================
if __name__ == "__main__":
    # فقط URL همین سرویس فعلی Render استفاده می‌شود؛ هیچ URL قدیمی/ثابتی در کد نیست.
    render_url = os.environ.get("RENDER_EXTERNAL_URL", "").strip().rstrip("/")
    if not render_url:
        render_host = os.environ.get("RENDER_EXTERNAL_HOSTNAME", "").strip().strip("/")
        if render_host:
            render_url = f"https://{render_host}"

    configured_url = os.environ.get("WEBHOOK_URL", "").strip().rstrip("/")
    if configured_url:
        WEBHOOK_URL = configured_url
    elif render_url:
        WEBHOOK_URL = f"{render_url}/webhook"
    else:
        raise RuntimeError(
            "Render URL پیدا نشد. WEBHOOK_URL یا RENDER_EXTERNAL_URL "
            "یا RENDER_EXTERNAL_HOSTNAME را تنظیم کنید."
        )

    try:
        # هر webhook قبلی حذف می‌شود تا فقط آدرس سرویس فعلی باقی بماند.
        bot.remove_webhook()
        time.sleep(0.5)
        bot.set_webhook(
            url=WEBHOOK_URL,
            secret_token=TELEGRAM_WEBHOOK_SECRET or None,
            allowed_updates=["message", "callback_query", "my_chat_member"]
        )
        logging.info("Telegram webhook configured successfully: %s", WEBHOOK_URL)
    except Exception as e:
        logging.exception("Failed to configure Telegram webhook: %s", e)
        raise

    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, threaded=True)
