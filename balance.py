
import json
from pathlib import Path

BALANCES_FILE = Path("balances.json")
STARTING_BALANCE = 10  # Credits for new users

def load_balances():
    """Loads user balances from the JSON file."""
    if not BALANCES_FILE.exists():
        return {}
    with open(BALANCES_FILE, "r") as f:
        try:
            return json.load(f)
        except json.JSONDecodeError:
            return {}

def save_balances(balances):
    """Saves the balances dictionary to the JSON file."""
    with open(BALANCES_FILE, "w") as f:
        json.dump(balances, f, indent=4)

def get_balance(user_id):
    """Gets a user's balance, giving a starting balance if they are new."""
    balances = load_balances()
    user_id_str = str(user_id)
    if user_id_str not in balances:
        balances[user_id_str] = STARTING_BALANCE
        save_balances(balances)
    return balances[user_id_str]

def update_balance(user_id, cost):
    """
    Updates a user's balance by deducting the cost.
    Returns True if the balance was sufficient, False otherwise.
    """
    balances = load_balances()
    user_id_str = str(user_id)
    current_balance = balances.get(user_id_str, 0)

    if current_balance >= cost:
        balances[user_id_str] = current_balance - cost
        save_balances(balances)
        return True
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
        multiplier = 1.5
    elif filesize_mb <= 500:
        multiplier = 2
    elif filesize_mb <= 1024: # 1GB
        multiplier = 3
    elif filesize_mb <= 2048: # 2GB
        multiplier = 4
    else:
        multiplier = 5

    # Итоговая цена
    final_cost = round(base_cost * multiplier)
    return final_cost

