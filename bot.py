import os
import uuid
import asyncio
from collections import deque
from pathlib import Path

from dotenv import load_dotenv
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, BotCommand
from telegram.ext import Application, CommandHandler, MessageHandler, filters, CallbackContext, CallbackQueryHandler

from yt_downloader import get_video_streams
from balance import get_balance, update_balance, calculate_video_cost
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


async def handle_message(update: Update, context: CallbackContext) -> None:
    """Обрабатывает входящие сообщения, показывает выбор формата."""
    message = update.message
    if not message.text or ("youtube.com/" not in message.text and "youtu.be/" not in message.text):
        await message.reply_text("Пожалуйста, отправьте действительную ссылку на YouTube.")
        return

    url = message.text
    sent_message = await message.reply_text("🔎 Получаю информацию о видео...")

    try:
        streams, title = get_video_streams(url)
        
        if not streams:
            await sent_message.edit_text("Не удалось найти доступные форматы для скачивания.")
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
            
            callback_data = f"{stream['itag']}:{cost}:{url_key}"
            keyboard.append([InlineKeyboardButton(text, callback_data=callback_data)])

        if not keyboard:
            await sent_message.edit_text("Не найдено подходящих форматов (mp4, до 720p).")
            return

        reply_markup = InlineKeyboardMarkup(keyboard)
        user_id = message.from_user.id
        balance = get_balance(user_id)
        await sent_message.edit_text(
            f'Выберите формат для видео "{title}":\n\nВаш баланс: {balance} кредитов.', 
            reply_markup=reply_markup
        )

    except Exception as e:
        logger.error(f"Error in handle_message: {e}", exc_info=True)
        await sent_message.edit_text(f"Произошла ошибка при получении информации о видео: {e}")


async def download_selection(update: Update, context: CallbackContext) -> None:
    """Обрабатывает выбор формата, проверяет баланс и добавляет в очередь."""
    query = update.callback_query
    user_id = query.from_user.id
    await query.answer()

    try:
        itag_str, cost_str, url_key = query.data.split(":", 2)
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
        logger.exception(f"Error in download_selection for query data: {query.data}")
        await query.edit_message_text(f"❌ Произошла ошибка при добавлении в очередь: {e}")


async def post_init(application: Application) -> None:
    """Post initialization hook for the bot."""
    await application.bot.set_my_commands([
        BotCommand("start", "Запустить бота"),
        BotCommand("balance", "Проверить баланс"),
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
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    application.add_handler(CallbackQueryHandler(download_selection))

    logger.info("Бот запущен...")
    application.run_polling()


if __name__ == "__main__":
    main()
