import sqlite3
from pathlib import Path
import logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

DB_FILE = Path("balances.db")
STARTING_BALANCE = 100  # Credits for new users

def init_db():
    """Initializes the database and creates the users table if it doesn't exist."""
    with sqlite3.connect(DB_FILE) as conn:
        cursor = conn.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                balance INTEGER NOT NULL
            )
        """)
        conn.commit()

def get_balance(user_id: int) -> int:
    """Gets a user's balance, creating a new record if they are new."""
    with sqlite3.connect(DB_FILE) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT balance FROM users WHERE user_id = ?", (user_id,))
        result = cursor.fetchone()
        
        if result:
            return result[0]
        else:
            # User not found, create a new entry
            cursor.execute(
                "INSERT INTO users (user_id, balance) VALUES (?, ?)", 
                (user_id, STARTING_BALANCE)
            )
            conn.commit()
            return STARTING_BALANCE

def add_balance(user_id: int, amount: int) -> None:
    """Adds the specified amount to the user's balance."""
    with sqlite3.connect(DB_FILE) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT balance FROM users WHERE user_id = ?", (user_id,))
        result = cursor.fetchone()
        
        if result:
            new_balance = result[0] + amount
            cursor.execute(
                "UPDATE users SET balance = ? WHERE user_id = ?", 
                (new_balance, user_id)
            )
        else:
            # User not found, create a new entry with the topped-up balance
            cursor.execute(
                "INSERT INTO users (user_id, balance) VALUES (?, ?)", 
                (user_id, STARTING_BALANCE + amount)
            )
        conn.commit()

def update_balance(user_id: int, cost: int) -> bool:
    """
    Updates a user's balance by deducting the cost in a transaction-safe way.
    Returns True if the balance was sufficient, False otherwise.
    """
    with sqlite3.connect(DB_FILE) as conn:
        cursor = conn.cursor()
        try:
            # Get current balance
            cursor.execute("SELECT balance FROM users WHERE user_id = ?", (user_id,))
            result = cursor.fetchone()
            
            current_balance = 0
            if result:
                current_balance = result[0]
            else:
                # This case should ideally not be hit if get_balance is always called first
                # But as a fallback, we can create the user.
                cursor.execute(
                    "INSERT INTO users (user_id, balance) VALUES (?, ?)", 
                    (user_id, STARTING_BALANCE)
                )
                current_balance = STARTING_BALANCE

            if current_balance >= cost:
                new_balance = current_balance - cost
                cursor.execute(
                    "UPDATE users SET balance = ? WHERE user_id = ?", 
                    (new_balance, user_id)
                )
                conn.commit()
                return True
            else:
                # Not enough balance, roll back any potential changes (like user creation)
                conn.rollback()
                return False
        except sqlite3.Error as e:
            logger.error(f"Database error: {e}")
            conn.rollback()
            return False

def calculate_video_cost(resolution: str, filesize_mb: int) -> int:
    # Настраиваемые параметры:
    base_cost_by_resolution = {
        "480p": 1,
        "720p": 3,
        "1080p": 6,
        "1440p": 9,
        "4K": 12,
    }

    # Максимальное качество и размер, при которых видео можно скачать бесплатно
    max_free_filesize_mb = 100  # MB
    max_free_resolution = "720p"  # всё ниже или равно — может быть бесплатным

    # Функция сравнения разрешений (по порядку качества)
    resolution_order = ["144p", "240p", "360p", "480p", "720p", "1080p", "1440p", "4K", "8K"]

    def resolution_leq(r1, r2):
        try:
            return resolution_order.index(r1) <= resolution_order.index(r2)
        except ValueError:
            return False

    # Проверка на бесплатность
    if filesize_mb <= max_free_filesize_mb and resolution_leq(resolution, max_free_resolution):
        return 0

    # Получаем базовую цену
    base_cost = base_cost_by_resolution.get(resolution)
    if base_cost is None:
        if resolution_leq(resolution, "480p"):
            base_cost = 1
        else:
            base_cost = max(base_cost_by_resolution.values())

    # Расчёт стоимости с учётом размера (чем больше — тем дороже)
    if filesize_mb <= 50:
        multiplier = 1
    elif filesize_mb <= 200:
        multiplier = 2
    elif filesize_mb <= 500:
        multiplier = 3
    elif filesize_mb <= 1024: # 1GB
        multiplier = 4
    elif filesize_mb <= 2048: # 2GB
        multiplier = 5
    else:
        multiplier = 10

    # Итоговая цена
    final_cost = round(base_cost * multiplier)
    return final_cost

# Initialize the database when the module is loaded
init_db()