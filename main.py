import os
import asyncio
import json
import logging
import re
import httpx
from threading import Thread
from flask import Flask, request
from telegram import Update, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, filters, CallbackQueryHandler, ContextTypes

app = Flask(__name__)
telegram_application = None

@app.route("/")
def home():
    return "Bot is running", 200

@app.route("/telegram/webhook", methods=["POST"])
def telegram_webhook():
    global telegram_application
    if telegram_application is None:
        return "Bot is starting", 503
    secret = os.getenv("WEBHOOK_SECRET")
    if secret and request.headers.get("X-Telegram-Bot-Api-Secret-Token") != secret:
        return "Forbidden", 403
    try:
        data = request.get_json(silent=True) or {}
        update = Update.de_json(data, telegram_application.bot)
        telegram_application.update_queue.put_nowait(update)
        return "OK", 200
    except Exception:
        logging.exception("Webhook update failed")
        return "Bad Request", 400

def run_web():
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 10000)), use_reloader=False)

Thread(target=run_web, daemon=True).start()

from database import (
    init_db, create_or_update_user, get_balance, get_user_channels,
    register_referral, get_referral_stats, get_subscription_expiry,
    has_active_subscription, buy_month_subscription, set_user_channel,
    channel_exists, register_channel, create_receipt,
    get_receipt, set_receipt_status, get_receipt_status, approve_receipt
)

logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.ERROR)

BOT_TOKEN = os.getenv("BOT_TOKEN")
SUPPORT_ID = "8904869158" #ایدی عددی ادمین
SUPPORT_USERNAME = "Par3aYT"
CHANNEL_ID = "@PreEmoji_Free"
CHANNEL_PRICE = 15000 # مبلغ اشتراک ماهانه
MIN_DEPOSIT = 15000 # حداقل افزایش موجودی

def replace_emoji_ids(text):
    pattern = r'\[(\d+)\]'
    matches = re.findall(pattern, text)
    new_text = text
    for emoji_id in matches:
        replacement = f'<tg-emoji emoji-id="{emoji_id}">😎</tg-emoji>'
        new_text = new_text.replace(f'[{emoji_id}]', replacement)
    return new_text




async def send_custom_emoji_post(context: ContextTypes.DEFAULT_TYPE, channel: str, text: str):
    """Send directly to a channel with Bot API Rich Messages.

    [123...] placeholders are converted to real Custom Emoji rich-text nodes.
    No Telethon, user account, session, forwarding, or staged message is used.
    A classic sendMessage/entity fallback is attempted for maximum compatibility.
    """
    if not text or not text.strip():
        raise ValueError("متن پست خالی است")

    pattern = re.compile(r'\[(\d+)\]')
    matches = list(pattern.finditer(text))
    if not matches:
        return await context.bot.send_message(chat_id=channel, text=text)

    ids = list(dict.fromkeys(m.group(1) for m in matches))
    stickers = await context.bot.get_custom_emoji_stickers(custom_emoji_ids=ids)
    sticker_by_id = {
        str(st.custom_emoji_id): st
        for st in stickers
        if getattr(st, 'custom_emoji_id', None)
    }

    pieces = []
    entities = []
    last = 0
    clean_parts = []
    for m in matches:
        before = text[last:m.start()]
        clean_parts.append(before)
        pieces.append(before)
        emoji_id = m.group(1)
        sticker = sticker_by_id.get(emoji_id)
        if sticker is None:
            raise ValueError(f"Custom emoji پیدا نشد: {emoji_id}")
        alt = getattr(sticker, 'emoji', None)
        if not alt:
            raise ValueError(f"Alternative emoji پیدا نشد: {emoji_id}")

        # Rich Markdown form officially supported by Bot API Rich Messages.
        pieces.append(f'![Image: {alt}](tg://emoji?id={emoji_id})')
        clean_parts.append(alt)
        last = m.end()
    tail = text[last:]
    pieces.append(tail)
    clean_parts.append(tail)
    rich_markdown = ''.join(pieces)
    clean_text = ''.join(clean_parts)

    token = BOT_TOKEN
    if not token:
        raise RuntimeError('BOT_TOKEN تنظیم نشده است')

    async with httpx.AsyncClient(timeout=30.0) as client:
        # Primary route: Bot API 10.1+ Rich Messages.
        rich_url = f'https://api.telegram.org/bot{token}/sendRichMessage'
        rich_payload = {
            'chat_id': channel,
            'rich_message': json.dumps({
                'markdown': rich_markdown,
                'is_rtl': True,
            }, ensure_ascii=False),
        }
        rich_response = await client.post(rich_url, data=rich_payload)
        try:
            rich_data = rich_response.json()
        except Exception:
            rich_data = {'ok': False, 'description': rich_response.text}

        if rich_response.status_code == 200 and rich_data.get('ok'):
            logging.info('Custom-emoji post sent with sendRichMessage to %s', channel)
            return rich_data.get('result')

        # Fallback: traditional custom_emoji MessageEntity.
        entities_payload = []
        pos_utf16 = 0
        last_match_end = 0
        for m in matches:
            before = text[last_match_end:m.start()]
            pos_utf16 += len(before.encode('utf-16-le')) // 2
            emoji_id = m.group(1)
            sticker = sticker_by_id[emoji_id]
            alt = getattr(sticker, 'emoji', None)
            if not alt:
                raise ValueError(f"Alternative emoji پیدا نشد: {emoji_id}")
            alt_len = len(alt.encode('utf-16-le')) // 2
            entities_payload.append({
                'type': 'custom_emoji',
                'offset': pos_utf16,
                'length': alt_len,
                'custom_emoji_id': emoji_id,
            })
            pos_utf16 += alt_len
            last_match_end = m.end()

        send_url = f'https://api.telegram.org/bot{token}/sendMessage'
        send_payload = {
            'chat_id': channel,
            'text': clean_text,
            'entities': json.dumps(entities_payload, ensure_ascii=False),
        }
        send_response = await client.post(send_url, data=send_payload)
        try:
            send_data = send_response.json()
        except Exception:
            send_data = {'ok': False, 'description': send_response.text}

    if send_response.status_code == 200 and send_data.get('ok'):
        logging.info('Custom-emoji post sent with sendMessage/entities to %s', channel)
        return send_data.get('result')

    rich_error = rich_data.get('description', 'unknown Rich Message error')
    classic_error = send_data.get('description', 'unknown sendMessage error')
    raise RuntimeError(
        f'Telegram could not send custom emoji post. '
        f'RichMessage={rich_error}; sendMessage={classic_error}'
    )

async def check_user_joined(user_id, context):
    try:
        chat_id = CHANNEL_ID
        if CHANNEL_ID.startswith('@'):
            chat = await context.bot.get_chat(CHANNEL_ID)
            chat_id = chat.id
        member = await context.bot.get_chat_member(chat_id=chat_id, user_id=user_id)
        if member.status in ['member', 'administrator', 'creator']:
            return True
        return False
    except:
        return False

def create_join_keyboard():
    keyboard = {
        "inline_keyboard": [
            [
                {"text": "عضویت در کانال", "url": "https://t.me/emojiperim", "style": "primary"},
                {"text": "بررسی عضویت", "callback_data": "check_join", "style": "success", "icon_custom_emoji_id": "6258234230396949553"}
            ]
        ]
    }
    return InlineKeyboardMarkup.de_json(keyboard, None)

def create_main_keyboard():
    keyboard = {
        "inline_keyboard": [
            [{"text": "ارسال پست", "callback_data": "convert_emoji", "style": "primary", "icon_custom_emoji_id": "5105062921902229396"}],
            [{"text": "خرید اکانت یک ماهه", "callback_data": "buy_account", "style": "success", "icon_custom_emoji_id": "5105285714740774968"}],
            [
                {"text": "افزایش موجودی", "callback_data": "increase_balance", "style": "success", "icon_custom_emoji_id": "5105285714740774968"},
                {"text": "راهنما ربات", "callback_data": "help", "style": "danger", "icon_custom_emoji_id": "5105130477442827969"}
            ],
            [{"text": "زیرمجموعه گیری", "callback_data": "referral", "style": "primary", "icon_custom_emoji_id": "5102788607869978573"}],
            [
                {"text": "حساب کاربری", "callback_data": "user_account", "style": "success", "icon_custom_emoji_id": "5105267113237415580"},
                {"text": "پشتیبانی", "callback_data": "support", "style": "danger", "icon_custom_emoji_id": "5102958950567905106"}
            ]
        ]
    }
    return InlineKeyboardMarkup.de_json(keyboard, None)

def create_channel_keyboard(user_id):
    channels = get_user_channels(user_id)
    if not channels:
        keyboard = {
            "inline_keyboard": [
                [{"text": "ثبت کانال", "callback_data": "register_channel", "style": "primary", "icon_custom_emoji_id": "5789782521084385229"}],
                [{"text": "بازگشت", "callback_data": "back_main", "style": "danger", "icon_custom_emoji_id": "5107127053119915925"}]
            ]
        }
        return InlineKeyboardMarkup.de_json(keyboard, None)
    
    inline_keyboard = []
    for channel in channels:
        button_text = f"[5985379274524202415] {channel}"
        button_text = replace_emoji_ids(button_text)
        inline_keyboard.append([{"text": button_text, "callback_data": f"channel_{channel}", "style": "primary"}])
    
    inline_keyboard.append([{"text": "ثبت کانال", "callback_data": "register_channel", "style": "primary", "icon_custom_emoji_id": "5789782521084385229"}])
    inline_keyboard.append([{"text": "بازگشت", "callback_data": "back_main", "style": "danger", "icon_custom_emoji_id": "5107127053119915925"}])
    
    keyboard = {"inline_keyboard": inline_keyboard}
    return InlineKeyboardMarkup.de_json(keyboard, None)

def create_back_keyboard():
    keyboard = {
        "inline_keyboard": [
            [{"text": "بازگشت", "callback_data": "back_main", "style": "danger", "icon_custom_emoji_id": "5107127053119915925"}]
        ]
    }
    return InlineKeyboardMarkup.de_json(keyboard, None)

def create_agency_keyboard():
    keyboard = {
        "inline_keyboard": [
            [{"text": "بازگشت", "callback_data": "back_main", "style": "danger", "icon_custom_emoji_id": "5107127053119915925"}]
        ]
    }
    return InlineKeyboardMarkup.de_json(keyboard, None)

def create_support_buttons():
    keyboard = {
        "inline_keyboard": [
            [
                {"text": "پیوی پشتیبانی", "url": "https://t.me/Par3aYT", "style": "primary", "icon_custom_emoji_id": "5102958950567905106"},
                {"text": "پشتیبانی ربات", "callback_data": "support_bot", "style": "primary", "icon_custom_emoji_id": "5102788607869978573"}
            ],
            [{"text": "بازگشت", "callback_data": "back_main", "style": "danger", "icon_custom_emoji_id": "5107127053119915925"}]
        ]
    }
    return InlineKeyboardMarkup.de_json(keyboard, None)

def create_support_bot_keyboard():
    keyboard = {
        "inline_keyboard": [
            [{"text": "بازگشت", "callback_data": "back_support", "style": "danger", "icon_custom_emoji_id": "5107127053119915925"}]
        ]
    }
    return InlineKeyboardMarkup.de_json(keyboard, None)

def create_admin_reply_keyboard(user_id):
    keyboard = {
        "inline_keyboard": [
            [{"text": "پاسخ به کاربر", "callback_data": f"reply_user:{user_id}", "style": "primary", "icon_custom_emoji_id": "5312523882547150460"}],
            [{"text": "بازگشت", "callback_data": "back_support", "style": "danger", "icon_custom_emoji_id": "5107127053119915925"}]
        ]
    }
    return InlineKeyboardMarkup.de_json(keyboard, None)

def create_amount_keyboard():
    keyboard = {
        "inline_keyboard": [
            [{"text": "1", "callback_data": "num_1"}, {"text": "2", "callback_data": "num_2"}, {"text": "3", "callback_data": "num_3"}],
            [{"text": "4", "callback_data": "num_4"}, {"text": "5", "callback_data": "num_5"}, {"text": "6", "callback_data": "num_6"}],
            [{"text": "7", "callback_data": "num_7"}, {"text": "8", "callback_data": "num_8"}, {"text": "9", "callback_data": "num_9"}],
            [
                {"text": "حذف", "callback_data": "num_delete", "style": "danger", "icon_custom_emoji_id": "5814503317753040871"},
                {"text": "0", "callback_data": "num_0"},
                {"text": "تایید", "callback_data": "num_confirm", "style": "success", "icon_custom_emoji_id": "5814669863699878746"}
            ],
            [{"text": "بازگشت", "callback_data": "back_main", "style": "danger", "icon_custom_emoji_id": "5107127053119915925"}]
        ]
    }
    return InlineKeyboardMarkup.de_json(keyboard, None)

def create_admin_verify_keyboard(receipt_id):
    keyboard = {
        "inline_keyboard": [
            [
                {"text": "تایید", "callback_data": f"verify_accept:{receipt_id}", "style": "success", "icon_custom_emoji_id": "6257971296794057056"},
                {"text": "رد کردن", "callback_data": f"verify_reject:{receipt_id}", "style": "danger", "icon_custom_emoji_id": "5830451652309553634"}
            ]
        ]
    }
    return InlineKeyboardMarkup.de_json(keyboard, None)

def create_receipt_sent_keyboard():
    keyboard = {
        "inline_keyboard": [
            [{"text": "پیوی ادمین", "url": "https://t.me/Par3aYT", "style": "primary", "icon_custom_emoji_id": "5814670671153730702"}],
            [{"text": "بازگشت", "callback_data": "back_main", "style": "danger", "icon_custom_emoji_id": "5107127053119915925"}]
        ]
    }
    return InlineKeyboardMarkup.de_json(keyboard, None)

def create_not_enough_balance_keyboard():
    keyboard = {
        "inline_keyboard": [
            [{"text": "افزایش موجودی", "callback_data": "increase_balance", "style": "success", "icon_custom_emoji_id": "5951762148886582569"}],
            [{"text": "بازگشت", "callback_data": "back_main", "style": "danger", "icon_custom_emoji_id": "5107127053119915925"}]
        ]
    }
    return InlineKeyboardMarkup.de_json(keyboard, None)

def create_channel_registered_keyboard():
    keyboard = {
        "inline_keyboard": [
            [{"text": "برگشت", "callback_data": "back_main", "style": "danger", "icon_custom_emoji_id": "5107127053119915925"}]
        ]
    }
    return InlineKeyboardMarkup.de_json(keyboard, None)

async def show_join_message(update, context):
    join_text = (
        f'<b>[6260176972953949338] سلام عشقم</b>\n\n'
        f'<b>[6258234230396949553] خوش اومدی به ربات</b>\n\n'
        f'<b>[6257971296794057056] اول یه جوین توی چنل زیر بده بعد بریم حال کنیم :)</b>\n'
        f'<b>🔗 <a href="https://t.me/emojiperim">https://t.me/emojiperim</a></b>'
    )
    final_text = replace_emoji_ids(join_text)
    reply_markup = create_join_keyboard()
    if update.callback_query:
        await update.callback_query.edit_message_text(final_text, parse_mode="HTML", reply_markup=reply_markup, disable_web_page_preview=True)
    else:
        await update.message.reply_text(final_text, parse_mode="HTML", reply_markup=reply_markup, disable_web_page_preview=True)

async def show_main_panel(update, context):
    user = update.effective_user if update.effective_user else update.callback_query.from_user
    first_name = user.first_name if user.first_name else user.username if user.username else "کاربر"
    if user.id != SUPPORT_ID:
        is_joined = await check_user_joined(user.id, context)
        if not is_joined:
            await show_join_message(update, context)
            return
    welcome_text = (
        f'<blockquote><b>[5417969813609795944] سلام {first_name} خوش اومدی به ربات ایموجی پرمیوم [5210783786706436474]</b></blockquote>\n\n'
        f'<b>با این ربات راحت میتونی ایموجی پرمیوم به کانالت ارسال کنی :) [5104937770850191412]</b>'
    )
    final_text = replace_emoji_ids(welcome_text)
    reply_markup = create_main_keyboard()
    if update.callback_query:
        await update.callback_query.edit_message_text(final_text, parse_mode="HTML", reply_markup=reply_markup)
    else:
        await update.message.reply_text(final_text, parse_mode="HTML", reply_markup=reply_markup)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    create_or_update_user(user.id, user.username, user.first_name)

    # Referral is credited only after the new user passes the normal join check.
    referral_id = None
    if context.args:
        try:
            candidate = int(context.args[0])
            if candidate != user.id:
                referral_id = candidate
        except (TypeError, ValueError):
            referral_id = None

    is_joined = await check_user_joined(user.id, context)
    if not is_joined and user.id != SUPPORT_ID:
        await show_join_message(update, context)
        return

    if referral_id is not None:
        try:
            register_referral(referral_id, user.id, 2500)
        except Exception:
            logging.exception("Failed to register referral")

    await show_main_panel(update, context)

async def check_join(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user = query.from_user
    is_joined = await check_user_joined(user.id, context)
    if is_joined:
        success_text = f'<b>[6258234230396949553] عضویت شما تایید شد</b>\n\n<b>[6260176972953949338] خوش اومدی به ربات عزیزم</b>'
        final_text = replace_emoji_ids(success_text)
        await query.edit_message_text(final_text, parse_mode="HTML")
        await show_main_panel(update, context)
    else:
        not_joined_text = f'<b>[6257971296794057056] شما هنوز در کانال عضو نشدید!</b>\n\n<b>لطفاً ابتدا روی دکمه "عضویت در کانال" کلیک کنید و عضو شوید</b>\n<b>سپس دکمه "بررسی عضویت" را بزنید.</b>'
        final_text = replace_emoji_ids(not_joined_text)
        await query.edit_message_text(final_text, parse_mode="HTML", reply_markup=create_join_keyboard(), disable_web_page_preview=True)

async def show_convert_emoji(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user if update.effective_user else update.callback_query.from_user
    if user.id != SUPPORT_ID and not await check_user_joined(user.id, context):
        await show_join_message(update, context)
        return
    if not has_active_subscription(user.id):
        text = '[5922608666795580060] اشتراک شما فعال نیست. برای ارسال پست باید اکانت یک ماهه 15 هزار تومان داشته باشید. اول اشتراک را بخرید. [5922608666795580060]'
        final = replace_emoji_ids(text)
        markup = InlineKeyboardMarkup.de_json({"inline_keyboard":[
            [{"text":"خرید اکانت یک ماهه","callback_data":"buy_account","style":"success"}],
            [{"text":"بازگشت","callback_data":"back_main","style":"danger"}]
        ]}, None)
    else:
        channels = get_user_channels(user.id)
        if not channels:
            # Old users without a saved channel must set one before posting.
            text = '⚠️ هنوز کانالی برای حساب شما ثبت نشده است.\n\nابتدا روی «خرید اکانت یک ماهه» بزنید و آیدی کانال را ثبت کنید.'
            final = replace_emoji_ids(text)
            markup = InlineKeyboardMarkup.de_json({"inline_keyboard":[
                [{"text":"خرید اکانت یک ماهه","callback_data":"buy_account","style":"success"}],
                [{"text":"بازگشت","callback_data":"back_main","style":"danger"}]
            ]}, None)
        else:
            text = ('برای ارسال پست، متن خودت را همراه با آیدی ایموجی‌های پرمیوم بفرست.\n'
                    'مثال: <code>سلام [5809816447576183225]</code>\n\n'
                    'پست مستقیماً در کانال ثبت‌شده شما ارسال می‌شود. ✨')
            final = replace_emoji_ids(text)
            markup = create_back_keyboard()
            context.user_data['waiting_for_post'] = True
    if update.callback_query:
        await update.callback_query.edit_message_text(final, parse_mode="HTML", reply_markup=markup)
        await update.callback_query.answer()
    else:
        await update.message.reply_text(final, parse_mode="HTML", reply_markup=markup)

async def buy_account(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user = query.from_user
    if has_active_subscription(user.id):
        expiry = get_subscription_expiry(user.id)
        channels = get_user_channels(user.id)
        channel = channels[0] if channels else 'ثبت نشده'
        text = f'✅ اشتراک شما فعال است.\n\n📢 کانال: <b>{channel}</b>\n⏳ تا تاریخ: <b>{expiry:%Y-%m-%d %H:%M}</b>\n\nبعد از پایان اشتراک، دوباره «خرید اکانت یک ماهه» را بزنید تا کانال را مجدداً تأیید و ۳۰ روز تمدید کنید.'
        await query.edit_message_text(text, parse_mode="HTML", reply_markup=create_back_keyboard())
        return

    if get_balance(user.id) < CHANNEL_PRICE:
        text = '[5922608666795580060] موجودی کافی نیست. برای خرید اکانت یک ماهه و ثبت کانال، 15,000 تومان موجودی لازم داری. اول موجودی را افزایش بده. [5922608666795580060]'
        markup = InlineKeyboardMarkup.de_json({"inline_keyboard":[
            [{"text":"افزایش موجودی","callback_data":"increase_balance","style":"success"}],
            [{"text":"بازگشت","callback_data":"back_main","style":"danger"}]
        ]}, None)
        final = replace_emoji_ids(text)
        await query.edit_message_text(final, parse_mode="HTML", reply_markup=markup)
        return

    text = ('برای فعال‌سازی اکانت یک ماهه، آیدی کانالت را با @ بفرست.\n\n'
            'مثال: <code>@MyChannel</code>\n\n'
            '⚠️ ربات را داخل همان کانال <b>ادمین کامل</b> کن و دسترسی ارسال پست را داشته باشد.\n'
            'بعد از ارسال آیدی، ربات دسترسی را بررسی می‌کند و در صورت تأیید، 15,000 تومان کسر و اشتراک 30 روزه فعال می‌شود.\n\n'
            'هر کاربر فقط <b>یک کانال</b> می‌تواند داشته باشد.')
    markup = InlineKeyboardMarkup.de_json({"inline_keyboard":[
        [{"text":"بازگشت","callback_data":"back_main","style":"danger"}]
    ]}, None)
    context.user_data['waiting_for_channel_purchase'] = True
    await query.edit_message_text(text, parse_mode="HTML", reply_markup=markup)

async def handle_channel_purchase(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    channel_input = (update.message.text or '').strip()
    if not context.user_data.get('waiting_for_channel_purchase'):
        return
    if not channel_input.startswith('@') or len(channel_input) < 2 or ' ' in channel_input:
        await update.message.reply_text('❌ آیدی کانال را با @ بفرست.\nمثال: <code>@MyChannel</code>', parse_mode="HTML")
        return
    try:
        chat = await context.bot.get_chat(channel_input)
        member = await context.bot.get_chat_member(chat_id=chat.id, user_id=context.bot.id)
        if member.status not in ['administrator', 'creator']:
            await update.message.reply_text('❌ ربات ادمین این کانال نیست. ربات را داخل کانال <b>ادمین کامل</b> کن و دوباره آیدی را بفرست.', parse_mode="HTML")
            return
        if getattr(member, 'can_post_messages', True) is False:
            await update.message.reply_text('❌ ربات دسترسی ارسال پست ندارد. دسترسی ارسال پست را فعال کن و دوباره آیدی را بفرست.', parse_mode="HTML")
            return

        create_or_update_user(user.id, user.username, user.first_name)
        if has_active_subscription(user.id):
            set_user_channel(user.id, channel_input)
            expiry = get_subscription_expiry(user.id)
        else:
            expiry = buy_month_subscription(user.id, CHANNEL_PRICE, channel_input)
            if expiry is None:
                await update.message.reply_text('❌ موجودی کافی نیست یا فعال‌سازی اشتراک ناموفق بود. دوباره از دکمه خرید اقدام کن.', parse_mode="HTML")
                return

        context.user_data['waiting_for_channel_purchase'] = False
        context.user_data['waiting_for_post'] = True
        text = (f'✅ اشتراک یک ماهه با موفقیت فعال شد.\n\n📢 کانال ثبت‌شده: <b>{channel_input}</b>\n'
                f'⏳ اعتبار تا: <b>{expiry:%Y-%m-%d %H:%M}</b>\n\n'
                'حالا متن پست را همراه با آیدی ایموجی‌های پرمیوم بفرست؛ پست مستقیم داخل کانالت ارسال می‌شود.')
        await update.message.reply_text(text, parse_mode="HTML", reply_markup=create_back_keyboard())
        await context.bot.send_message(chat_id=SUPPORT_ID, text=f'✅ اشتراک کانال فعال شد\\n👤 {user.first_name}\\n🆔 {user.id}\\n📢 {channel_input}\\n⏳ {expiry:%Y-%m-%d %H:%M}', parse_mode="HTML")
    except Exception:
        logging.exception('Channel purchase/verification failed')
        await update.message.reply_text('❌ نتوانستم کانال را بررسی کنم. مطمئن شو آیدی درست است و ربات در کانال ادمین کامل است.', parse_mode="HTML")

async def show_select_channel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user if update.effective_user else update.callback_query.from_user
    if user.id != SUPPORT_ID:
        is_joined = await check_user_joined(user.id, context)
        if not is_joined:
            await show_join_message(update, context)
            return
    user_id = user.id
    channels = get_user_channels(user_id)
    if not channels:
        channel_text = f'[6258046600455656031] اوخ هیچ کانال که ثبت نکردی [6219810752887262728]\nروی دکمه ثبت کانال بزن کانال ثبت کن :) [6298514001361897127]'
        final_text = replace_emoji_ids(channel_text)
        reply_markup = create_channel_keyboard(user_id)
        if update.callback_query:
            await update.callback_query.edit_message_text(final_text, parse_mode="HTML", reply_markup=reply_markup)
            await update.callback_query.answer()
        else:
            await update.message.reply_text(final_text, parse_mode="HTML", reply_markup=reply_markup)
    else:
        channel_text = f'[5785054788588673518] برای ارسال پست روی اسم کانالی که میخوای پست ارسال بشه کلیک کن :)[5789636015454952676]'
        final_text = replace_emoji_ids(channel_text)
        reply_markup = create_channel_keyboard(user_id)
        if update.callback_query:
            await update.callback_query.edit_message_text(final_text, parse_mode="HTML", reply_markup=reply_markup)
            await update.callback_query.answer()
        else:
            await update.message.reply_text(final_text, parse_mode="HTML", reply_markup=reply_markup)

async def register_channel_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user = query.from_user
    user_id = user.id
    balance = get_balance(user_id)
    if balance < CHANNEL_PRICE:
        not_enough_text = f'[5922608666795580060] ههههههه موجودی نداری [5922608666795580060] [5922608666795580060] [5922608666795580060] [5922608666795580060]\n\nبرو اول هر کانال که میخوای ثبت کنی 15 تومنه برو اول موجودی افزایش بده بعد بیا [5922608666795580060]'
        final_text = replace_emoji_ids(not_enough_text)
        await query.edit_message_text(final_text, parse_mode="HTML", reply_markup=create_not_enough_balance_keyboard())
        return
    register_text = f'[5922626194557115284] حله داش چنل ثبت کن [5922626194557115284]\n\nبرای ثبت چنلت اول رباتو توی کانالی که میخوای اد فول کن بعد یوزرنیم (ایدی) کانالو بفرست چک کنم [5920529949868964881]'
    final_text = replace_emoji_ids(register_text)
    back_keyboard = {
        "inline_keyboard": [
            [{"text": "بازگشت", "callback_data": "back_select_channel", "style": "danger", "icon_custom_emoji_id": "5107127053119915925"}]
        ]
    }
    reply_markup = InlineKeyboardMarkup.de_json(back_keyboard, None)
    await query.edit_message_text(final_text, parse_mode="HTML", reply_markup=reply_markup)
    context.user_data['waiting_for_channel'] = True

async def handle_channel_registration(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    create_or_update_user(user.id, user.username, user.first_name)
    user_id = user.id
    channel_input = update.message.text.strip()
    if not context.user_data.get('waiting_for_channel'):
        return
    if not channel_input.startswith('@'):
        await update.message.reply_text("❌ لطفاً آیدی کانال را با @ وارد کنید.\nمثال: @my_channel", parse_mode="HTML")
        return
    try:
        chat = await context.bot.get_chat(channel_input)
        try:
            test_text = "[5969739636447122230] تست ادمینی ربات"
            test_text_final = replace_emoji_ids(test_text)
            test_message = await context.bot.send_message(chat_id=chat.id, text=test_text_final, parse_mode="HTML")
            try:
                await context.bot.delete_message(chat_id=chat.id, message_id=test_message.message_id)
            except:
                pass
        except:
            not_admin_text = f'[5981136177548235329] نشد داش ربات ادمین نی اول اد کن دوباره یوزرنیم بفرست'
            final_text = replace_emoji_ids(not_admin_text)
            await update.message.reply_text(final_text, parse_mode="HTML")
            return
        try:
            member = await context.bot.get_chat_member(chat_id=chat.id, user_id=user_id)
            if member.status not in ['administrator', 'creator']:
                not_admin_text = f'[5981136177548235329] نشد داش ربات ادمین نی اول اد کن دوباره یوزرنیم بفرست'
                final_text = replace_emoji_ids(not_admin_text)
                await update.message.reply_text(final_text, parse_mode="HTML")
                return
        except:
            not_admin_text = f'[5981136177548235329] نشد داش ربات ادمین نی اول اد کن دوباره یوزرنیم بفرست'
            final_text = replace_emoji_ids(not_admin_text)
            await update.message.reply_text(final_text, parse_mode="HTML")
            return
        if channel_exists(user_id, channel_input):
            duplicate_text = f'[5961042782939255288] کانال قبلا ثبت شده داش ریدی [5961042782939255288] مبلغو بک میزنم بت ی کانال دیگه ثبت کن اشحححح[5961042782939255288]'
            final_text = replace_emoji_ids(duplicate_text)
            await update.message.reply_text(final_text, parse_mode="HTML")
            return

        new_balance = register_channel(user_id, channel_input, CHANNEL_PRICE)
        if new_balance is None:
            await update.message.reply_text("❌ موجودی کافی نیست یا ثبت کانال ناموفق بود.", parse_mode="HTML")
            return
        success_text = f'[5271801931814165886] کانالت ثبت شد جیگر بزن رو دکمه زیر از اول بیا [5422444280473998663]'
        final_text = replace_emoji_ids(success_text)
        await update.message.reply_text(final_text, parse_mode="HTML", reply_markup=create_channel_registered_keyboard())
        context.user_data['waiting_for_channel'] = False
        await context.bot.send_message(
            chat_id=SUPPORT_ID,
            text=f"✅ کانال جدید ثبت شد\n\n👤 کاربر: {user.first_name} (@{user.username if user.username else 'ندارد'})\n🆔 آیدی: {user.id}\n📢 کانال: {channel_input}\n💰 موجودی باقی‌مانده: {new_balance:,} تومان",
            parse_mode="HTML"
        )
    except:
        await update.message.reply_text("❌ خطا در ثبت کانال! لطفاً آیدی را به درستی وارد کنید.\nمثال: @my_channel", parse_mode="HTML")

async def show_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user if update.effective_user else update.callback_query.from_user
    if user.id != SUPPORT_ID:
        is_joined = await check_user_joined(user.id, context)
        if not is_joined:
            await show_join_message(update, context)
            return
    help_text = (
        f'<blockquote><b>[5105328363766024275] راهنمای کامل ربات [5105201194079356308]</b></blockquote>\n\n'
        f'<blockquote><b>[5104937770850191412] هزینه اشتراک یکماه برای هر کانال: 15 هزار تومان هست که میتونید برای کانال خود یکماه اشتراک خرید کرده و یا اینکه با دعوت چند نفر دوستاتون میتونید اشتراک بگیرید [5102719042284685213]</b></blockquote>\n\n'
        f'<blockquote><b>راهنما ارسال پست [5309758950105696330]</b></blockquote>\n'
        f'<b>1.</b> ابتدا روی دکمه انتخاب کانال کلیک کرده و سپس کانالی که میخواید پست ارسال کنید رو انتخاب کنید و روی اسم کانال کلیک کنید [5816711927375602899]\n\n'
        f'[5818716826699307883] (اگر کانالی ندارید بر روی دکمه ثبت کانال کلیک کنید اول ربات رو توی کانال خودتون ادمین فول کنید و سپس ایدی کانال خود را ارسال کنید) [5818716826699307883]\n\n'
        f'<b>2.</b> بعد از اینکه کانال خودتونو انتخاب کردین روی کانال کلیک کردین پنل ربات ویرایش شد از کانال ایموجی ها میتونید ایموجی خودتون کد ایموجی رو کپی کنید و به ربات همراه متن ارسال کنید [5816913107938712568]\n\n'
        f'مثلا: \nسلام (این بخش کد ایموجی) \nقرار بدید و به ربات ارسال کنید\n\n'
        f'<blockquote><b>[5819051035284479206] متنی که به کانال شما ارسال میشه به صورت زیر خواهد بود با ایموجی که قرار داده اید.</b></blockquote>\n'
        f'سلام [5818704981179505821]'
    )
    final_text = replace_emoji_ids(help_text)
    if update.callback_query:
        await update.callback_query.edit_message_text(final_text, parse_mode="HTML", reply_markup=create_back_keyboard())
        await update.callback_query.answer()
    else:
        await update.message.reply_text(final_text, parse_mode="HTML", reply_markup=create_back_keyboard())

async def show_agency(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user if update.effective_user else update.callback_query.from_user
    if user.id != SUPPORT_ID:
        is_joined = await check_user_joined(user.id, context)
        if not is_joined:
            await show_join_message(update, context)
            return
    agency_text = (
        f'<blockquote><b>[5309964275312249008] پنل نمایندگی ربات ایموجی پرمیوم [5309964275312249008]</b></blockquote>\n\n'
        f'<blockquote><b>[5105188334947272972] قابلیت های اصلی:</b></blockquote>\n'
        f'پنل ادمینی کامل تحت اختیار خودتون [5102580731452851920]\n'
        f'مدیریت کاربران + مدیریت کامل حساب [5104964872093828911]\n'
        f'رایگان شدن پنل برای کانال های خودتون [5105308976283649855]\n\n'
        f'کسب درامد + اسپانسری کانالتون  [5105062921902229396]\n\n'
        f'<blockquote><b>[5105288081267754884] هزینه اسپانسری دائمی ربات به قیمت 450T ارائه میشود و به صورت کامل میتوانید ربات خودتون رو داشته باشید. [5105267113237415580]</b></blockquote>'
    )
    final_text = replace_emoji_ids(agency_text)
    if update.callback_query:
        await update.callback_query.edit_message_text(final_text, parse_mode="HTML", reply_markup=create_agency_keyboard())
        await update.callback_query.answer()
    else:
        await update.message.reply_text(final_text, parse_mode="HTML", reply_markup=create_agency_keyboard())

async def show_referral(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user if update.effective_user else update.callback_query.from_user
    bot = context.bot
    me = await bot.get_me()
    link = f"https://t.me/{me.username}?start={user.id}"
    count, earned = get_referral_stats(user.id)
    text = (
        f"❤️ <b>زیرمجموعه گیری</b>\n\n"
        f"لینک اختصاصی شما:\n<code>{link}</code>\n\n"
        f"👥 تعداد زیرمجموعه‌های موفق: <b>{count}</b>\n"
        f"💰 درآمد از زیرمجموعه‌ها: <b>{earned:,} تومان</b>\n\n"
        f"🎁 به ازای هر زیرمجموعه موفق <b>2500 تومان</b> به موجودی شما اضافه می‌شود."
    )
    if update.callback_query:
        await update.callback_query.edit_message_text(text, parse_mode="HTML", reply_markup=create_agency_keyboard())
        await update.callback_query.answer()
    else:
        await update.message.reply_text(text, parse_mode="HTML", reply_markup=create_agency_keyboard())

async def show_support(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user if update.effective_user else update.callback_query.from_user
    if user.id != SUPPORT_ID:
        is_joined = await check_user_joined(user.id, context)
        if not is_joined:
            await show_join_message(update, context)
            return
    support_text = f'[5105267113237415580] شما به پشتیبانی وصل شدید [5105267113237415580]\nاز دکمه های زیر میتوانید با پشتیبانی ارتباط بگیرید [5105188334947272972]\nبرای پیگیری سریع مشکل یا سوالتون به پیوی پشتیبانی مراجعه کنید و یا میتوانید از دکمه پشتیبانی ربات ارتباط بگیرید [5105241751455533359]'
    final_text = replace_emoji_ids(support_text)
    if update.callback_query:
        await update.callback_query.edit_message_text(final_text, parse_mode="HTML", reply_markup=create_support_buttons())
        await update.callback_query.answer()

async def show_support_bot(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user if update.effective_user else update.callback_query.from_user
    if user.id != SUPPORT_ID:
        is_joined = await check_user_joined(user.id, context)
        if not is_joined:
            await show_join_message(update, context)
            return
    support_bot_text = (
        f'<blockquote><b>[5102788607869978573] پشتیبانی ربات</b></blockquote>\n'
        f'[5102938893070632240] کاربر گرامی در صورت ارسال هرگونه پیام نامربوط پشتیبانی اجازه مسدود کردن حساب شمارا دارد. [5102938893070632240]\n\n'
        f'<b>[5352647939472760941] پیام خود را ارسال کنید:</b>'
    )
    final_text = replace_emoji_ids(support_bot_text)
    if update.callback_query:
        await update.callback_query.edit_message_text(final_text, parse_mode="HTML", reply_markup=create_support_bot_keyboard())
        await update.callback_query.answer()
        context.user_data['waiting_for_support_message'] = True

async def forward_to_admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    user_text = update.message.text
    admin_text = (
        f'[6024048153580277867] پیام جدید از سوی کاربر\n'
        f'[6296577138615125756] <a href="tg://user?id={user.id}">ایدی عددی کاربر: {user.id}</a>\n'
        f'[5253478042256308885] یوزرنیم کاربر: @{user.username if user.username else "ندارد"}\n'
        f'[5474667187258006816] موجودی حساب: {get_balance(user.id):,} تومان\n'
        f'[5472363852131736400] متن پیام کاربر: {user_text}'
    )
    final_text = replace_emoji_ids(admin_text)
    try:
        await context.bot.send_message(chat_id=SUPPORT_ID, text=final_text, parse_mode="HTML", reply_markup=create_admin_reply_keyboard(user.id))
        confirm_text = f'[5105267113237415580] <b>متن شما به پشتیبانی ارسال شد</b> [5105267113237415580]\n\n[5105188334947272972] پیام شما دریافت و به پشتیبانی ارسال گردید\n[5105241751455533359] در اسرع وقت پاسخ داده خواهد شد'
        final_confirm = replace_emoji_ids(confirm_text)
        await update.message.reply_text(final_confirm, parse_mode="HTML")
    except:
        await update.message.reply_text("❌ خطا در ارسال پیام! لطفاً دوباره تلاش کنید.", parse_mode="HTML")
    context.user_data['waiting_for_support_message'] = False

async def admin_reply_to_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    reply_text = f'<b>[5422388729366992632] پیام خود را ارسال کنید:</b>'
    final_text = replace_emoji_ids(reply_text)
    back_keyboard = {
        "inline_keyboard": [
            [{"text": "بازگشت", "callback_data": "back_support", "style": "danger", "icon_custom_emoji_id": "5107127053119915925"}]
        ]
    }
    reply_markup = InlineKeyboardMarkup.de_json(back_keyboard, None)
    await query.edit_message_text(final_text, parse_mode="HTML", reply_markup=reply_markup)
    context.user_data['waiting_for_admin_reply'] = True

async def send_admin_reply(update: Update, context: ContextTypes.DEFAULT_TYPE):
    admin_text = update.message.text
    user_id = context.user_data.get('reply_user_id')
    if not user_id:
        await update.message.reply_text("❌ خطا: کاربر یافت نشد!", parse_mode="HTML")
        return
    user_message = f'[5980933747149640196] <b>پیام از سوی ادمین:</b>\n\n{admin_text}'
    final_text = replace_emoji_ids(user_message)
    try:
        await context.bot.send_message(chat_id=user_id, text=final_text, parse_mode="HTML")
        await update.message.reply_text("✅ پیام با موفقیت به کاربر ارسال شد!", parse_mode="HTML")
        context.user_data['waiting_for_admin_reply'] = False
    except:
        await update.message.reply_text("❌ خطا در ارسال پیام!", parse_mode="HTML")

async def show_increase_balance(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user if update.effective_user else update.callback_query.from_user
    if user.id != SUPPORT_ID:
        is_joined = await check_user_joined(user.id, context)
        if not is_joined:
            await show_join_message(update, context)
            return
    balance_text = (
        f'<blockquote><b>[4999002445444023072] افزایش موجودی [4999002445444023072]</b></blockquote>\n'
        f'حداقل مبلغ افزایش موجودی 15,000 تومان هست[5834643712189141114]\n'
        f'[5830223696920318502] از منو زیر میتوانید مبلغ مورد نظر برای افزایش موجودی وارد کنید.\n\n'
        f'<b>[5814670671153730702]مبلغ وارد شده: {context.user_data.get("amount", "")}</b>'
    )
    final_text = replace_emoji_ids(balance_text)
    if update.callback_query:
        await update.callback_query.edit_message_text(final_text, parse_mode="HTML", reply_markup=create_amount_keyboard())
        await update.callback_query.answer()
    else:
        await update.message.reply_text(final_text, parse_mode="HTML", reply_markup=create_amount_keyboard())

async def show_payment_info(update: Update, context: ContextTypes.DEFAULT_TYPE):
    amount = context.user_data.get('amount', '0')
    user = update.effective_user
    first_name = user.first_name if user.first_name else user.username if user.username else "کاربر"
    payment_text = (
        f'<b>[5830326445422940546] مبلغ تعیین شده: {amount} تومان</b>\n'
        f'<b>[5830221171479548287]شماره کارت برای افزایش موجودی:</b>\n<b>5859831035810414</b>\n'
        f'<b>[5830204369567485741]نام: @Par3aYT</b>\n\n'
        f'<blockquote><b>[5830203935775789535]{first_name} ابتدا مبلغ تعیین شده را به شماره کارت بالا انتقال داده و سپس عکس رسید را در همین بخش ارسال کنید.[5834933356193649751]</b></blockquote>\n\n'
        f'<b>[5830348293921576631]رسید شما: </b>'
    )
    final_text = replace_emoji_ids(payment_text)
    if update.callback_query:
        await update.callback_query.edit_message_text(final_text, parse_mode="HTML", reply_markup=create_back_keyboard())
        await update.callback_query.answer()
    context.user_data['waiting_for_receipt'] = True


async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        query = update.callback_query
        await query.answer()
        if query.data == "check_join":
            await check_join(update, context)
        elif query.data == "select_channel" or query.data == "convert_emoji":
            await show_convert_emoji(update, context)
        elif query.data == "register_channel":
            await buy_account(update, context)
        elif query.data == "buy_account":
            await buy_account(update, context)
        elif query.data == "back_select_channel":
            await show_convert_emoji(update, context)
        elif query.data.startswith("channel_"):
            await show_convert_emoji(update, context)
        elif query.data == "increase_balance":
            context.user_data['amount'] = ''
            await show_increase_balance(update, context)
        elif query.data.startswith("num_"):
            action = query.data.replace("num_", "")
            current_amount = context.user_data.get('amount', '')
            if action == "delete":
                current_amount = current_amount[:-1]
            elif action == "confirm":
                if not current_amount:
                    await query.answer("⚠️ لطفاً مبلغ را وارد کنید!")
                    return
                try:
                    amount_int = int(current_amount)
                    if amount_int < MIN_DEPOSIT:
                        await query.answer("⚠️ حداقل مبلغ 15,000 تومان است!", show_alert=True)
                        return
                    else:
                        await show_payment_info(update, context)
                        return
                except ValueError:
                    await query.answer("⚠️ لطفاً عدد معتبر وارد کنید!", show_alert=True)
                    return
            else:
                current_amount += action
            context.user_data['amount'] = current_amount
            await show_increase_balance(update, context)
        elif query.data == "help":
            await show_help(update, context)
        elif query.data == "agency" or query.data == "referral":
            await show_referral(update, context)
        elif query.data == "user_account":
            user = query.from_user
            if user.id != SUPPORT_ID:
                is_joined = await check_user_joined(user.id, context)
                if not is_joined:
                    await show_join_message(update, context)
                    return
            balance = get_balance(user.id)
            account_text = f'<blockquote><b>[5105267113237415580] حساب کاربری [5105267113237415580]</b></blockquote>\n\n<b>[5104964872093828911] آیدی عددی:</b> <code>{user.id}</code>\n<b>[5102580731452851920] نام:</b> {user.first_name}\n<b>[5105308976283649855] موجودی:</b> {balance:,} تومان\n<b>[5105062921902229396] وضعیت:</b> فعال'
            final_text = replace_emoji_ids(account_text)
            await query.edit_message_text(final_text, parse_mode="HTML", reply_markup=create_back_keyboard())
        elif query.data == "support":
            await show_support(update, context)
        elif query.data == "support_bot":
            await show_support_bot(update, context)
        elif query.data == "reply_user":
            await admin_reply_to_user(update, context)
        elif query.data.startswith("reply_user:"):
            target_user_id = int(query.data.split(":", 1)[1])
            context.user_data['reply_user_id'] = target_user_id
            await admin_reply_to_user(update, context)
        elif query.data == "back_support":
            await show_support(update, context)
        elif query.data == "back_main":
            user = query.from_user
            first_name = user.first_name if user.first_name else user.username if user.username else "کاربر"
            if user.id != SUPPORT_ID:
                is_joined = await check_user_joined(user.id, context)
                if not is_joined:
                    await show_join_message(update, context)
                    return
            context.user_data.clear()
            welcome_text = f'<blockquote><b>[5417969813609795944] سلام {first_name} خوش اومدی به ربات ایموجی پرمیوم [5210783786706436474]</b></blockquote>\n\n<b>با این ربات راحت میتونی ایموجی پرمیوم به کانالت ارسال کنی :) [5104937770850191412]</b>'
            final_text = replace_emoji_ids(welcome_text)
            await query.edit_message_text(final_text, parse_mode="HTML", reply_markup=create_main_keyboard())
        elif query.data.startswith("verify_accept:"):
            receipt_id = int(query.data.split(":", 1)[1])
            await verify_receipt(update, context, receipt_id, "verify_accept")
        elif query.data.startswith("verify_reject:"):
            receipt_id = int(query.data.split(":", 1)[1])
            await verify_receipt(update, context, receipt_id, "verify_reject")
    except:
        pass

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        user = update.effective_user
        if user.id != SUPPORT_ID:
            is_joined = await check_user_joined(user.id, context)
            if not is_joined:
                join_text = f'<b>[6257971296794057056] شما در کانال عضو نیستید!</b>\n\n<b>لطفاً ابتدا در کانال زیر عضو شوید:</b>\n<b>🔗 <a href="https://t.me/emojiperim">https://t.me/emojiperim</a></b>'
                final_text = replace_emoji_ids(join_text)
                await update.message.reply_text(final_text, parse_mode="HTML", reply_markup=create_join_keyboard(), disable_web_page_preview=True)
                return
        if context.user_data.get('waiting_for_channel_purchase'):
            await handle_channel_purchase(update, context)
            return
        if context.user_data.get('waiting_for_channel'):
            await handle_channel_registration(update, context)
            return
        if context.user_data.get('waiting_for_post'):
            if not has_active_subscription(user.id):
                context.user_data['waiting_for_post'] = False
                await show_convert_emoji(update, context)
                return
            channels = get_user_channels(user.id)
            if not channels:
                context.user_data['waiting_for_post'] = False
                await show_convert_emoji(update, context)
                return
            try:
                await send_custom_emoji_post(context, channels[0], update.message.text or '')
                await update.message.reply_text('✅ پست با ایموجی پرمیوم با موفقیت در کانال ثبت‌شده ارسال شد.', parse_mode="HTML")
            except Exception as exc:
                logging.exception('Channel custom emoji post failed')
                msg=str(exc)
                if 'PREMIUM' in msg.upper():
                    await update.message.reply_text('❌ تلگرام اجازه ارسال این ایموجی پرمیوم را برای اکانت API فعلی نداد. این محدودیت از سمت تلگرام است.', parse_mode="HTML")
                else:
                    await update.message.reply_text('❌ ارسال پست ناموفق بود. آیدی ایموجی و دسترسی ادمینی ربات را بررسی کن.', parse_mode="HTML")
            return
        if context.user_data.get('waiting_for_receipt'):
            if update.message.photo:
                await handle_receipt(update, context)
                return
            else:
                await update.message.reply_text("⚠️ لطفاً عکس رسید خود را ارسال کنید.", parse_mode="HTML")
                return
        if context.user_data.get('waiting_for_support_message'):
            if user.id != SUPPORT_ID:
                await forward_to_admin(update, context)
                return
            else:
                context.user_data['waiting_for_support_message'] = False
                await update.message.reply_text("شما به عنوان ادمین در حالت پشتیبانی هستید.", parse_mode="HTML")
                return
        if context.user_data.get('waiting_for_admin_reply'):
            if user.id == SUPPORT_ID:
                await send_admin_reply(update, context)
                return
        if user.id == SUPPORT_ID:
            pattern = r'\[(\d+)\]'
            matches = re.findall(pattern, update.message.text)
            if matches:
                new_text = update.message.text
                for emoji_id in matches:
                    replacement = f'<tg-emoji emoji-id="{emoji_id}">😎</tg-emoji>'
                    new_text = new_text.replace(f'[{emoji_id}]', replacement)
                await update.message.reply_text(new_text, parse_mode="HTML")
                return
        if update.message.text and update.message.text.startswith('/help'):
            await show_help(update, context)
            return
        elif update.message.text and update.message.text.startswith('/agency'):
            await show_agency(update, context)
            return
        elif update.message.text and update.message.text.startswith('/support'):
            await show_support(update, context)
            return
        if update.message.text:
            await update.message.reply_text(f"📩 پیام شما دریافت شد:\n\n{update.message.text}", parse_mode="HTML")
    except:
        pass

def main():
    if not BOT_TOKEN:
        raise RuntimeError("BOT_TOKEN environment variable is not set")
    init_db()
    app = (
        Application.builder()
        .token(BOT_TOKEN)
        .build()
    )
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", show_help))
    app.add_handler(CommandHandler("agency", show_agency))
    app.add_handler(CommandHandler("support", show_support))
    app.add_handler(CallbackQueryHandler(button_callback))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app.add_handler(MessageHandler(filters.PHOTO, handle_message))
    global telegram_application
    telegram_application = app

    async def runner():
        await app.initialize()
        await app.start()
        webhook_base = os.getenv("RENDER_EXTERNAL_URL")
        if not webhook_base:
            host = os.getenv("RENDER_EXTERNAL_HOSTNAME")
            if host:
                webhook_base = f"https://{host}"
        if not webhook_base:
            webhook_base = "https://emoji-premium.onrender.com"
        webhook_url = webhook_base.rstrip("/") + "/telegram/webhook"
        secret = os.getenv("WEBHOOK_SECRET") or None
        await app.bot.set_webhook(url=webhook_url, secret_token=secret, allowed_updates=Update.ALL_TYPES)
        logging.error("Telegram webhook set: %s", webhook_url)
        try:
            await asyncio.Event().wait()
        finally:
            try:
                await app.bot.delete_webhook(drop_pending_updates=False)
            except Exception:
                pass
            await app.stop()
            await app.shutdown()

    print("start - webhook mode")
    asyncio.run(runner())

if __name__ == "__main__":
    main()
