import os
import uuid
import asyncio
from collections import deque
from pathlib import Path

from dotenv import load_dotenv
from aiocryptopay import AioCryptoPay, Networks
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, BotCommand, LabeledPrice
from telegram.error import BadRequest
from telegram.ext import Application, CommandHandler, MessageHandler, filters, CallbackContext, CallbackQueryHandler, PreCheckoutQueryHandler

from yt_downloader import get_video_streams
from balance import get_balance, update_balance, calculate_video_cost, add_balance
from queue_manager import add_to_queue, queue_processor
from topup_stars import show_stars_packages, select_stars_package_handler
from topup_crypto import handle_crypto_topup, check_crypto_payment_handler

# Загружаем переменные окружения
load_dotenv()
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
ADMIN_USER_IDS = [int(x) for x in os.getenv("ADMIN_USER_IDS", "").split(",") if x]
CRYPTO_BOT_TOKEN = os.getenv("CRYPTO_BOT_TOKEN")

# Инициализация CryptoBot
if CRYPTO_BOT_TOKEN:
    cryptopay = AioCryptoPay(token=CRYPTO_BOT_TOKEN, network=Networks.MAIN_NET)
else:
    cryptopay = None

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
    
    keyboard = [[InlineKeyboardButton("Пополнить баланс", callback_data="topup")]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(
        f"Ваш баланс: {balance} кредитов.",
        reply_markup=reply_markup
    )


async def topup_command(update: Update, context: CallbackContext) -> None:
    """Показывает выбор способа пополнения."""
    keyboard = [
        [InlineKeyboardButton("⭐️ Telegram Stars", callback_data="topup_method:stars")],
        [InlineKeyboardButton("💎 CryptoBot", callback_data="topup_method:crypto")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text("Выберите способ пополнения:", reply_markup=reply_markup)


async def topup_button_handler(update: Update, context: CallbackContext) -> None:
    """Handles the top-up button from the balance message."""
    query = update.callback_query
    await query.answer()
    
    keyboard = [
        [InlineKeyboardButton("⭐️ Telegram Stars", callback_data="topup_method:stars")],
        [InlineKeyboardButton("💎 CryptoBot", callback_data="topup_method:crypto")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.edit_message_text("Выберите способ пополнения:", reply_markup=reply_markup)


async def select_topup_method_handler(update: Update, context: CallbackContext) -> None:
    """Обрабатывает выбор способа пополнения."""
    query = update.callback_query
    await query.answer()
    
    _, method = query.data.split(":")
    
    if method == "stars":
        await show_stars_packages(query.message)
    elif method == "crypto":
        if not cryptopay:
            await query.edit_message_text("Пополнение через CryptoBot временно недоступно.")
            return
        
        keyboard = [[InlineKeyboardButton("⬅️ Назад", callback_data="back_to_topup_method")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.edit_message_text(
            "Введите сумму в кредитах, которую хотите купить (1 кредит = $0.01):",
            reply_markup=reply_markup
        )
        context.user_data['crypto_topup'] = True


async def back_to_topup_method_handler(update: Update, context: CallbackContext) -> None:
    """Handles the back to topup method button."""
    query = update.callback_query
    await query.answer()
    
    keyboard = [
        [InlineKeyboardButton("⭐️ Telegram Stars", callback_data="topup_method:stars")],
        [InlineKeyboardButton("💎 CryptoBot", callback_data="topup_method:crypto")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.edit_message_text("Выберите способ пополнения:", reply_markup=reply_markup)


async def add_credits_command(update: Update, context: CallbackContext) -> None:
    """Добавляет кредиты пользователю (только для админов)."""
    user_id = update.message.from_user.id
    if user_id not in ADMIN_USER_IDS:
        await update.message.reply_text("У вас нет прав для выполнения этой команды.")
        return

    try:
        _, target_user_id_str, amount_str = update.message.text.split()
        target_user_id = int(target_user_id_str)
        amount = int(amount_str)
    except (ValueError, IndexError):
        await update.message.reply_text("Использование: /addcredits <user_id> <amount>")
        return

    add_balance(target_user_id, amount)
    new_balance = get_balance(target_user_id)

    await update.message.reply_text(
        f"Пользователю {target_user_id} успешно добавлено {amount} кредитов.\n"
        f"Новый баланс: {new_balance} кредитов."
    )


async def precheckout_handler(update: Update, context: CallbackContext) -> None:
    """Обрабатывает pre-checkout запросы."""
    query = update.pre_checkout_query
    if query.invoice_payload.startswith("topup_stars"):
        await query.answer(ok=True)
    else:
        await query.answer(ok=False, error_message="Что-то пошло не так...")


async def successful_payment_handler(update: Update, context: CallbackContext) -> None:
    """Обрабатывает успешные платежи."""
    payment_info = update.message.successful_payment
    payload = payment_info.invoice_payload
    
    if payload.startswith("topup_stars"):
        _, _, credits_str, _ = payload.split("_")
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
    """Обрабатывает входящие сообщения."""
    message = update.message
    if context.user_data.get('crypto_topup'):
        await handle_crypto_topup(update, context, cryptopay)
        return

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
    # Add admin commands separately
    for admin_id in ADMIN_USER_IDS:
        try:
            await application.bot.set_my_commands([
                BotCommand("start", "Запустить бота"),
                BotCommand("balance", "Проверить баланс"),
                BotCommand("topup", "Пополнить баланс"),
                BotCommand("addcredits", "Добавить кредиты пользователю"),
            ], scope={"type": "chat", "chat_id": admin_id})
        except BadRequest as e:
            logger.error(f"Failed to set commands for admin {admin_id}: {e}")

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
    application.add_handler(CommandHandler("addcredits", add_credits_command))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    
    # Обработчики для скачивания
    application.add_handler(CallbackQueryHandler(ask_for_confirmation, pattern="^select:"))
    application.add_handler(CallbackQueryHandler(process_confirmation, pattern="^(confirm|cancel):\d+:\d+:[0-9a-fA-F-]+"))

    # Обработчики для пополнения
    application.add_handler(CallbackQueryHandler(topup_button_handler, pattern="^topup$"))
    application.add_handler(CallbackQueryHandler(select_topup_method_handler, pattern="^topup_method:"))
    application.add_handler(CallbackQueryHandler(select_stars_package_handler, pattern="^topup_stars:"))
    application.add_handler(CallbackQueryHandler(lambda update, context: check_crypto_payment_handler(update, context, cryptopay), pattern="^check_crypto_payment:"))
    application.add_handler(CallbackQueryHandler(back_to_topup_method_handler, pattern="^back_to_topup_method$"))
    application.add_handler(PreCheckoutQueryHandler(precheckout_handler))
    application.add_handler(MessageHandler(filters.SUCCESSFUL_PAYMENT, successful_payment_handler))

    logger.info("Бот запущен...")
    application.run_polling()


if __name__ == "__main__":
    main()