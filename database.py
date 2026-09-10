import os
import psycopg
from contextlib import contextmanager

DATABASE_URL = os.getenv("DATABASE_URL")


def _connect():
    if not DATABASE_URL:
        raise RuntimeError("DATABASE_URL environment variable is not set")
    return psycopg.connect(DATABASE_URL)


@contextmanager
def db():
    conn = _connect()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db():
    with db() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    user_id BIGINT PRIMARY KEY,
                    username TEXT,
                    first_name TEXT,
                    balance BIGINT NOT NULL DEFAULT 0,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                )
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS user_channels (
                    id BIGSERIAL PRIMARY KEY,
                    user_id BIGINT NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
                    channel_username TEXT NOT NULL,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    UNIQUE(user_id, channel_username)
                )
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS receipts (
                    id BIGSERIAL PRIMARY KEY,
                    user_id BIGINT NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
                    amount BIGINT NOT NULL CHECK(amount > 0),
                    photo_file_id TEXT NOT NULL,
                    username TEXT,
                    admin_message_id BIGINT,
                    status TEXT NOT NULL DEFAULT 'pending'
                        CHECK(status IN ('pending', 'approved', 'rejected')),
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    reviewed_at TIMESTAMPTZ
                )
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS referrals (
                    id BIGSERIAL PRIMARY KEY,
                    referrer_id BIGINT NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
                    referred_id BIGINT NOT NULL UNIQUE REFERENCES users(user_id) ON DELETE CASCADE,
                    reward BIGINT NOT NULL DEFAULT 2500,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                )
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS transactions (
                    id BIGSERIAL PRIMARY KEY,
                    user_id BIGINT NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
                    amount BIGINT NOT NULL,
                    transaction_type TEXT NOT NULL,
                    description TEXT,
                    receipt_id BIGINT REFERENCES receipts(id) ON DELETE SET NULL,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                )
            """)
            # Normalize legacy data and enforce exactly one channel per user.
            cur.execute("""
                DELETE FROM user_channels a
                USING user_channels b
                WHERE a.user_id=b.user_id AND a.id < b.id
            """)
            cur.execute("""
                CREATE UNIQUE INDEX IF NOT EXISTS uq_user_channels_one_per_user
                ON user_channels(user_id)
            """)
            cur.execute("ALTER TABLE user_channels ADD COLUMN IF NOT EXISTS channel_id BIGINT")
            cur.execute("ALTER TABLE user_channels ADD COLUMN IF NOT EXISTS channel_type TEXT")
            cur.execute("ALTER TABLE user_channels ADD COLUMN IF NOT EXISTS channel_title TEXT")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_user_channels_user_id ON user_channels(user_id)")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_receipts_user_id ON receipts(user_id)")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_receipts_status ON receipts(status)")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_transactions_user_id ON transactions(user_id)")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_referrals_referrer_id ON referrals(referrer_id)")
            cur.execute("""
                CREATE TABLE IF NOT EXISTS subscriptions (
                    user_id BIGINT PRIMARY KEY REFERENCES users(user_id) ON DELETE CASCADE,
                    expires_at TIMESTAMPTZ NOT NULL,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                )
            """)



def create_or_update_user(user_id, username=None, first_name=None):
    with db() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO users (user_id, username, first_name)
                VALUES (%s, %s, %s)
                ON CONFLICT (user_id) DO UPDATE SET
                    username = EXCLUDED.username,
                    first_name = EXCLUDED.first_name,
                    updated_at = NOW()
            """, (user_id, username, first_name))


def get_balance(user_id):
    with db() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT balance FROM users WHERE user_id=%s", (user_id,))
            row = cur.fetchone()
            return int(row[0]) if row else 0


def get_user_channels(user_id):
    with db() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT channel_username FROM user_channels
                WHERE user_id=%s ORDER BY id DESC LIMIT 1
            """, (user_id,))
            return [row[0] for row in cur.fetchall()]


def get_user_channel_target(user_id):
    """Return the stable Telegram chat_id when available, otherwise the legacy username."""
    with db() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT COALESCE(channel_id, NULL), channel_username, channel_type, channel_title
                FROM user_channels
                WHERE user_id=%s ORDER BY id DESC LIMIT 1
            """, (user_id,))
            row = cur.fetchone()
            if not row:
                return None
            return {"chat_id": row[0] or row[1], "username": row[1], "type": row[2], "title": row[3]}


def channel_exists(user_id, channel_username):
    with db() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT 1 FROM user_channels
                WHERE user_id=%s AND channel_username=%s
            """, (user_id, channel_username))
            return cur.fetchone() is not None


def register_channel(user_id, channel_username, price, channel_id=None, channel_type=None, channel_title=None):
    """Atomically check balance, deduct price, and register a validated Telegram destination."""
    with db() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT balance FROM users WHERE user_id=%s FOR UPDATE", (user_id,))
            row = cur.fetchone()
            if not row or row[0] < price:
                return None
            cur.execute("UPDATE users SET balance=balance-%s, updated_at=NOW() WHERE user_id=%s", (price, user_id))
            cur.execute("DELETE FROM user_channels WHERE user_id=%s", (user_id,))
            cur.execute("""
                INSERT INTO user_channels(user_id, channel_username, channel_id, channel_type, channel_title)
                VALUES (%s, %s, %s, %s, %s)
            """, (user_id, channel_username, channel_id, channel_type, channel_title))
            cur.execute("""
                INSERT INTO transactions(user_id, amount, transaction_type, description)
                VALUES (%s, %s, 'channel_registration', %s)
            """, (user_id, -price, f"ثبت کانال {channel_username}"))
            cur.execute("SELECT balance FROM users WHERE user_id=%s", (user_id,))
            return int(cur.fetchone()[0])


def set_user_channel(user_id, channel_username, channel_id=None, channel_type=None, channel_title=None):
    """Replace the user's destination without touching subscription expiry or balance."""
    with db() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM user_channels WHERE user_id=%s", (user_id,))
            cur.execute("""
                INSERT INTO user_channels(user_id, channel_username, channel_id, channel_type, channel_title)
                VALUES (%s, %s, %s, %s, %s)
            """, (user_id, channel_username, channel_id, channel_type, channel_title))


def add_balance(user_id, amount, description=None, receipt_id=None):
    with db() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO users(user_id, balance)
                VALUES (%s, 0)
                ON CONFLICT (user_id) DO NOTHING
            """, (user_id,))
            cur.execute("""
                UPDATE users SET balance=balance+%s, updated_at=NOW()
                WHERE user_id=%s RETURNING balance
            """, (amount, user_id))
            new_balance = int(cur.fetchone()[0])
            cur.execute("""
                INSERT INTO transactions(user_id, amount, transaction_type, description, receipt_id)
                VALUES (%s, %s, 'deposit', %s, %s)
            """, (user_id, amount, description or "افزایش موجودی", receipt_id))
            return new_balance


def create_receipt(user_id, amount, photo_file_id, username=None):
    with db() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO receipts(user_id, amount, photo_file_id, username)
                VALUES (%s, %s, %s, %s) RETURNING id
            """, (user_id, amount, photo_file_id, username))
            return int(cur.fetchone()[0])


def set_receipt_admin_message(receipt_id, admin_message_id):
    with db() as conn:
        with conn.cursor() as cur:
            cur.execute("UPDATE receipts SET admin_message_id=%s WHERE id=%s", (admin_message_id, receipt_id))


def get_receipt(receipt_id):
    with db() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT id, user_id, amount, photo_file_id, username,
                       admin_message_id, status, created_at, reviewed_at
                FROM receipts WHERE id=%s
            """, (receipt_id,))
            row = cur.fetchone()
            if not row:
                return None
            keys = ["id", "user_id", "amount", "photo_file_id", "username", "admin_message_id", "status", "created_at", "reviewed_at"]
            return dict(zip(keys, row))


def get_receipt_status(receipt_id):
    with db() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT status FROM receipts WHERE id=%s", (receipt_id,))
            row = cur.fetchone()
            return row[0] if row else None



def approve_receipt(receipt_id):
    """Atomically approve a pending receipt, credit the user, and record the transaction.
    Returns (user_id, amount, new_balance, admin_message_id) or None if already reviewed/not found.
    """
    with db() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT user_id, amount, admin_message_id
                FROM receipts
                WHERE id=%s AND status='pending'
                FOR UPDATE
            """, (receipt_id,))
            row = cur.fetchone()
            if not row:
                return None
            user_id, amount, admin_message_id = row
            cur.execute("""
                UPDATE users
                SET balance=balance+%s, updated_at=NOW()
                WHERE user_id=%s
                RETURNING balance
            """, (amount, user_id))
            balance_row = cur.fetchone()
            if not balance_row:
                return None
            new_balance = int(balance_row[0])
            cur.execute("""
                INSERT INTO transactions(user_id, amount, transaction_type, description, receipt_id)
                VALUES (%s, %s, 'deposit', 'تایید رسید', %s)
            """, (user_id, amount, receipt_id))
            cur.execute("""
                UPDATE receipts SET status='approved', reviewed_at=NOW()
                WHERE id=%s
            """, (receipt_id,))
            return user_id, int(amount), new_balance, admin_message_id

def set_receipt_status(receipt_id, status):
    """Change status only if still pending; returns True when this call won the race."""
    with db() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                UPDATE receipts
                SET status=%s, reviewed_at=NOW()
                WHERE id=%s AND status='pending'
            """, (status, receipt_id))
            return cur.rowcount == 1


def register_referral(referrer_id, referred_id, reward=2500):
    """Register a referral exactly once and atomically credit the referrer."""
    if not referrer_id or not referred_id or int(referrer_id) == int(referred_id):
        return False
    with db() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT 1 FROM users WHERE user_id=%s", (referrer_id,))
            if not cur.fetchone():
                return False
            cur.execute("SELECT 1 FROM referrals WHERE referred_id=%s", (referred_id,))
            if cur.fetchone():
                return False
            cur.execute("""
                INSERT INTO referrals(referrer_id, referred_id, reward)
                VALUES (%s, %s, %s)
                ON CONFLICT (referred_id) DO NOTHING
                RETURNING id
            """, (referrer_id, referred_id, reward))
            if not cur.fetchone():
                return False
            cur.execute("""
                UPDATE users SET balance=balance+%s, updated_at=NOW()
                WHERE user_id=%s
                RETURNING balance
            """, (reward, referrer_id))
            row = cur.fetchone()
            if not row:
                return False
            cur.execute("""
                INSERT INTO transactions(user_id, amount, transaction_type, description)
                VALUES (%s, %s, 'referral_reward', %s)
            """, (referrer_id, reward, f'پاداش زیرمجموعه کاربر {referred_id}'))
            return True


def get_referral_stats(user_id):
    with db() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT COUNT(*), COALESCE(SUM(reward), 0)
                FROM referrals WHERE referrer_id=%s
            """, (user_id,))
            count, earned = cur.fetchone()
            return int(count), int(earned)


def get_subscription_expiry(user_id):
    with db() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT expires_at FROM subscriptions WHERE user_id=%s", (user_id,))
            row = cur.fetchone()
            return row[0] if row else None

def has_active_subscription(user_id):
    with db() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT 1 FROM subscriptions WHERE user_id=%s AND expires_at > NOW()", (user_id,))
            return cur.fetchone() is not None

def buy_month_subscription(user_id, price=15000, channel_username=None):
    with db() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT balance FROM users WHERE user_id=%s FOR UPDATE", (user_id,))
            row = cur.fetchone()
            if not row or row[0] < price:
                return None
            cur.execute("SELECT expires_at FROM subscriptions WHERE user_id=%s FOR UPDATE", (user_id,))
            existing = cur.fetchone()
            if existing and existing[0] > __import__('datetime').datetime.now(__import__('datetime').timezone.utc):
                return existing[0]
            cur.execute("UPDATE users SET balance=balance-%s, updated_at=NOW() WHERE user_id=%s", (price, user_id))
            if channel_username:
                # One destination channel per user; replace the previous value on renewal.
                cur.execute("DELETE FROM user_channels WHERE user_id=%s", (user_id,))
                cur.execute("""
                    INSERT INTO user_channels(user_id, channel_username)
                    VALUES (%s, %s)
                """, (user_id, channel_username))
            cur.execute("""
                INSERT INTO subscriptions(user_id, expires_at)
                VALUES (%s, NOW() + INTERVAL '30 days')
                ON CONFLICT (user_id) DO UPDATE SET expires_at=NOW() + INTERVAL '30 days', updated_at=NOW()
                RETURNING expires_at
            """, (user_id,))
            expiry = cur.fetchone()[0]
            cur.execute("""
                INSERT INTO transactions(user_id, amount, transaction_type, description)
                VALUES (%s, %s, 'subscription_purchase', 'خرید اکانت یک ماهه')
            """, (user_id, -price))
            return expiry
