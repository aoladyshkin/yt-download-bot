import os
import uuid
import asyncio
from collections import deque
from pathlib import Path

from dotenv import load_dotenv
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, BotCommand, LabeledPrice
from telegram.ext import Application, CommandHandler, MessageHandler, filters, CallbackContext, CallbackQueryHandler, PreCheckoutQueryHandler

from yt_downloader import get_video_streams
from balance import get_balance, update_balance, calculate_video_cost, add_balance
from queue_manager import add_to_queue, queue_processor

# Загружаем переменные окружения
load_dotenv()
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")

# Директория для скачивания
DOWNLOAD_DIR = Path("downloads")
DOWNLOAD_DIR.mkdir(exist_ok=True)

# Настройка логирования
import logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Пакеты для пополнения
TOPUP_PACKAGES = [
    {"credits": 100, "stars": 50},
    {"credits": 200, "stars": 90},
    {"credits": 300, "stars": 130},
]


async def start(update: Update, context: CallbackContext) -> None:
    """Отправляет приветственное сообщение и баланс."""
    user_id = update.message.from_user.id
    balance = get_balance(user_id)
    await update.message.reply_text(
        "Привет! Отправь мне ссылку на YouTube видео, и я скачаю его для тебя.\n" 
        f"Ваш баланс: {balance} кредитов."
    )

async def balance_command(update: Update, context: CallbackContext) -> None:
    """Показывает баланс пользователя."""
    user_id = update.message.from_user.id
    balance = get_balance(user_id)
    await update.message.reply_text(f"Ваш баланс: {balance} кредитов.")


async def topup_command(update: Update, context: CallbackContext) -> None:
    """Показывает варианты пополнения баланса."""
    keyboard = []
    for i, package in enumerate(TOPUP_PACKAGES):
        text = f"{package['credits']} кредитов за {package['stars']} звёзд"
        callback_data = f"topup:{i}"
        keyboard.append([InlineKeyboardButton(text, callback_data=callback_data)])
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text("Выберите пакет для пополнения баланса:", reply_markup=reply_markup)


async def select_package_handler(update: Update, context: CallbackContext) -> None:
    """Отправляет инвойс для выбранного пакета."""
    query = update.callback_query
    await query.answer()

    try:
        _, package_index_str = query.data.split(":")
        package_index = int(package_index_str)
        package = TOPUP_PACKAGES[package_index]

        title = f"Пополнение на {package['credits']} кредитов"
        description = f"Покупка {package['credits']} кредитов за {package['stars']} звёзд Telegram Stars"
        payload = f"topup_{package['credits']}_{package['stars']}"
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
        logger.error(f"Error in select_package_handler: {e}", exc_info=True)
        await query.message.reply_text("Произошла ошибка при выборе пакета. Попробуйте снова.")


async def precheckout_handler(update: Update, context: CallbackContext) -> None:
    """Обрабатывает pre-checkout запросы."""
    query = update.pre_checkout_query
    if query.invoice_payload.startswith("topup_"):
        await query.answer(ok=True)
    else:
        await query.answer(ok=False, error_message="Что-то пошло не так...")


async def successful_payment_handler(update: Update, context: CallbackContext) -> None:
    """Обрабатывает успешные платежи."""
    payment_info = update.message.successful_payment
    payload = payment_info.invoice_payload
    
    if payload.startswith("topup_"):
        _, credits_str, _ = payload.split("_")
        credits_to_add = int(credits_str)
        user_id = update.message.from_user.id
        
        add_balance(user_id, credits_to_add)
        new_balance = get_balance(user_id)
        
        await update.message.reply_text(
            f"✅ Платёж прошёл успешно! Ваш баланс пополнен на {credits_to_add} кредитов.\n"
            f"Новый баланс: {new_balance} кредитов."
        )


async def show_format_selection(update: Update, context: CallbackContext, url: str, message) -> None:
    """Показывает клавиатуру с выбором формата."""
    try:
        streams, title = get_video_streams(url)
        
        if not streams:
            await message.edit_text("Не удалось найти доступные форматы для скачивания.")
            return

        keyboard = []
        url_key = str(uuid.uuid4())
        context.user_data[url_key] = url

        for stream in streams:
            filesize_mb = stream.get('filesize', 0) / 1_048_576
            cost = 0
            if stream['type'] == 'video':
                try:
                    cost = calculate_video_cost(stream['resolution'], int(filesize_mb))
                except (ValueError, IndexError):
                    cost = 1 # Fallback cost
                text = f"📹 {stream['resolution']} ({filesize_mb:.1f} MB) - {f'{cost} кред.' if cost > 0 else 'Бесплатно 💸'}"
            else:  # audio
                cost = max(1, int(filesize_mb // 50) + 1)
                text = f"🎵 {stream['abr']} ({filesize_mb:.1f} MB) - {cost} кред."
            
            callback_data = f"select:{stream['itag']}:{cost}:{url_key}"
            keyboard.append([InlineKeyboardButton(text, callback_data=callback_data)])

        if not keyboard:
            await message.edit_text("Не найдено подходящих форматов (mp4, до 720p).")
            return

        reply_markup = InlineKeyboardMarkup(keyboard)
        user_id = update.effective_user.id
        balance = get_balance(user_id)
        await message.edit_text(
            f'Выберите формат для видео "{title}":\n\nВаш баланс: {balance} кредитов.', 
            reply_markup=reply_markup
        )

    except Exception as e:
        logger.error(f"Error in show_format_selection: {e}", exc_info=True)
        await message.edit_text(f"Произошла ошибка при получении информации о видео: {e}")


async def handle_message(update: Update, context: CallbackContext) -> None:
    """Обрабатывает входящие сообщения, показывает выбор формата."""
    message = update.message
    if not message.text or ("youtube.com/" not in message.text and "youtu.be/" not in message.text):
        await message.reply_text("Пожалуйста, отправьте действительную ссылку на YouTube.")
        return

    url = message.text
    sent_message = await message.reply_text("🔎 Получаю информацию о видео...")
    await show_format_selection(update, context, url, sent_message)


async def ask_for_confirmation(update: Update, context: CallbackContext) -> None:
    """Спрашивает у пользователя подтверждение на скачивание."""
    query = update.callback_query
    await query.answer()

    try:
        _, itag_str, cost_str, url_key = query.data.split(":", 3)
        cost = int(cost_str)
        
        keyboard = [
            [
                InlineKeyboardButton("✅ Подтвердить", callback_data=f"confirm:{itag_str}:{cost_str}:{url_key}"),
                InlineKeyboardButton("❌ Отмена", callback_data=f"cancel:0:0:{url_key}"),
            ]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.edit_message_text(
            f"С вашего баланса будет списано {cost} кредитов. Подтверждаете?",
            reply_markup=reply_markup
        )

    except Exception as e:
        logger.error(f"Error in ask_for_confirmation: {e}", exc_info=True)
        await query.edit_message_text("❌ Произошла ошибка. Попробуйте снова.")


async def process_confirmation(update: Update, context: CallbackContext) -> None:
    """Обрабатывает подтверждение или отмену скачивания."""
    query = update.callback_query
    user_id = query.from_user.id
    await query.answer()

    try:
        action, itag_str, cost_str, url_key = query.data.split(":")
        
        if action == "cancel":
            url = context.user_data.get(url_key)
            if not url:
                await query.edit_message_text("❌ Ошибка: URL видео не найден. Пожалуйста, отправьте ссылку заново.")
                return
            await show_format_selection(update, context, url, query.message)
            return

        if action == "confirm":
            itag = int(itag_str)
            cost = int(cost_str)
            
            url = context.user_data.get(url_key)
            if not url:
                await query.edit_message_text("❌ Ошибка: URL видео не найден. Пожалуйста, отправьте ссылку заново.")
                return

            current_balance = get_balance(user_id)
            if current_balance < cost:
                await query.edit_message_text(
                    f"❌ Недостаточно кредитов. Ваш баланс: {current_balance}, стоимость: {cost}."
                )
                return

            if not update_balance(user_id, cost):
                await query.edit_message_text("❌ Ошибка при списании кредитов. Попробуйте снова.")
                return

            streams, _ = get_video_streams(url)
            selected_format_text = "неизвестный формат"
            for stream_info in streams:
                if stream_info['itag'] == itag:
                    filesize_mb = stream_info.get('filesize', 0) / 1_048_576
                    if stream_info['type'] == 'video':
                        selected_format_text = f"📹 {stream_info['resolution']} | {filesize_mb:.1f} MB"
                    else:
                        selected_format_text = f"🎵 {stream_info['abr']} | {filesize_mb:.1f} MB"
                    break
            
            queue_len = add_to_queue(context, query.message.chat_id, query.message.message_id, url, itag, selected_format_text)

            new_balance = get_balance(user_id)
            await query.edit_message_text(
                f"✅ Заявка добавлена в очередь. Место: {queue_len}\n"
                f"Списано {cost} кредитов. Новый баланс: {new_balance}."
            )

            if url_key in context.user_data:
                del context.user_data[url_key]

    except Exception as e:
        logger.exception(f"Error in process_confirmation for query data: {query.data}")
        await query.edit_message_text(f"❌ Произошла ошибка при обработке вашего выбора: {e}")


async def post_init(application: Application) -> None:
    """Post initialization hook for the bot."""
    await application.bot.set_my_commands([
        BotCommand("start", "Запустить бота"),
        BotCommand("balance", "Проверить баланс"),
        BotCommand("topup", "Пополнить баланс"),
    ])
    application.bot_data['download_queue'] = deque()
    asyncio.create_task(queue_processor(application))


def main() -> None:
    """Запускает бота."""
    if not TELEGRAM_BOT_TOKEN:
        logger.error("Ошибка: Токен TELEGRAM_BOT_TOKEN не найден в .env файле.")
        return

    application = Application.builder().token(TELEGRAM_BOT_TOKEN).post_init(post_init).base_url("http://telegram-bot-api:8081/bot").base_file_url("http://telegram-bot-api:8081/file/bot").build()

    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("balance", balance_command))
    application.add_handler(CommandHandler("topup", topup_command))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    
    # Обработчики для скачивания
    application.add_handler(CallbackQueryHandler(ask_for_confirmation, pattern="^select:"))
    application.add_handler(CallbackQueryHandler(process_confirmation, pattern="^(confirm|cancel):"))

    # Обработчики для пополнения
    application.add_handler(CallbackQueryHandler(select_package_handler, pattern="^topup:"))
    application.add_handler(PreCheckoutQueryHandler(precheckout_handler))
    application.add_handler(MessageHandler(filters.SUCCESSFUL_PAYMENT, successful_payment_handler))

    logger.info("Бот запущен...")
    application.run_polling()


if __name__ == "__main__":
    main()