from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, LabeledPrice
from telegram.ext import CallbackContext

# Пакеты для пополнения
TOPUP_PACKAGES = [
    {"credits": 10, "stars": 1},
    {"credits": 200, "stars": 90},
    {"credits": 300, "stars": 130},
]

async def show_stars_packages(message) -> None:
    """Показывает пакеты пополнения за Telegram Stars."""
    keyboard = []
    for i, package in enumerate(TOPUP_PACKAGES):
        text = f"{package['credits']} кредитов за {package['stars']} звёзд"
        callback_data = f"topup_stars:{i}"
        keyboard.append([InlineKeyboardButton(text, callback_data=callback_data)])
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    await message.edit_text("Выберите пакет для пополнения баланса:", reply_markup=reply_markup)


async def select_stars_package_handler(update: Update, context: CallbackContext) -> None:
    """Отправляет инвойс для выбранного пакета Stars."""
    query = update.callback_query
    await query.answer()

    try:
        _, package_index_str = query.data.split(":")
        package_index = int(package_index_str)
        package = TOPUP_PACKAGES[package_index]

        title = f"Пополнение на {package['credits']} кредитов"
        description = f"Покупка {package['credits']} кредитов за {package['stars']} звёзд Telegram Stars"
        payload = f"topup_stars_{package['credits']}_{package['stars']}"
        currency = "XTR"
        prices = [LabeledPrice(label=f"{package['credits']} кредитов", amount=package['stars'])]

        await context.bot.send_invoice(
            chat_id=query.message.chat_id,
            title=title,
            description=description,
            payload=payload,
            provider_token=None,  # Не требуется для Telegram Stars
            currency=currency,
            prices=prices
        )
    except (IndexError, ValueError) as e:
        # logger.error(f"Error in select_stars_package_handler: {e}", exc_info=True)
        await query.message.reply_text("Произошла ошибка при выборе пакета. Попробуйте снова.")
