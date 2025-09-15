import os
import uuid
import asyncio
from collections import deque
from pathlib import Path

from dotenv import load_dotenv
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, BotCommand, InputFile
from telegram.ext import Application, CommandHandler, MessageHandler, filters, CallbackContext, CallbackQueryHandler

from yt_downloader import process_youtube_url, get_video_streams

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
    """Отправляет приветственное сообщение."""
    await update.message.reply_text(
        "Привет! Отправь мне ссылку на YouTube видео, и я скачаю его для тебя."
    )


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
        # Store URL in user_data with a unique key for this request
        url_key = str(uuid.uuid4())
        context.user_data[url_key] = url

        for stream in streams:
            filesize_mb = stream.get('filesize', 0) / 1_048_576
            if stream['type'] == 'video':
                text = f"📹 {stream['resolution']} ({filesize_mb:.1f} MB)"
            else:  # audio
                text = f"🎵 {stream['abr']} ({filesize_mb:.1f} MB)"
            
            callback_data = f"{stream['itag']}:{url_key}"
            keyboard.append([InlineKeyboardButton(text, callback_data=callback_data)])

        if not keyboard:
            await sent_message.edit_text("Не найдено подходящих форматов (mp4, до 720p).")
            return

        reply_markup = InlineKeyboardMarkup(keyboard)
        await sent_message.edit_text(f'Выберите формат для видео "{title}":', reply_markup=reply_markup)

    except Exception as e:
        await sent_message.edit_text(f"Произошла ошибка при получении информации о видео: {e}")


async def update_queue_messages(application: Application):
    """Updates all messages for users waiting in the queue."""
    queue = application.bot_data['download_queue']
    for i, (chat_id, message_id, _, _, _) in enumerate(queue):
        try:
            await application.bot.edit_message_text(
                chat_id=chat_id,
                message_id=message_id,
                text=f"⏳ Ваше место в очереди: {i + 1}"
            )
        except Exception as e:
            logger.warning(f"Failed to update queue message for chat {chat_id}: {e}")


async def queue_processor(application: Application):
    """The main worker task that processes the download queue."""
    queue = application.bot_data['download_queue']
    
    while True:
        if not queue:
            await asyncio.sleep(1)
            continue

        # Get the next job
        chat_id, message_id, url, itag, selected_format_text = queue.popleft()
        output_path = None

        try:
            await application.bot.edit_message_text(
                chat_id=chat_id,
                message_id=message_id,
                text=f"⏳ Начинаю скачивание ({selected_format_text})... Это может занять некоторое время."
            )

            # Update queue for everyone else
            await update_queue_messages(application)

            output_path = await asyncio.to_thread(process_youtube_url, url, DOWNLOAD_DIR, itag)

            if not output_path or not Path(output_path).exists():
                await application.bot.edit_message_text(chat_id=chat_id, message_id=message_id, text="❌ Не удалось скачать видео.")
                continue

            file_size = os.path.getsize(output_path)
            if file_size > 2 * 1024 * 1024 * 1024:
                await application.bot.edit_message_text(chat_id=chat_id, message_id=message_id, text="❌ Ошибка: Файл слишком большой для отправки через Telegram (больше 2 ГБ).")
                continue

            safe_name = Path(output_path).name.encode('utf-8', 'ignore').decode('utf-8')
            await application.bot.edit_message_text(chat_id=chat_id, message_id=message_id, text="⬆️ Отправляю видео...")

            with open(output_path, "rb") as fh:
                video_if = InputFile(fh, filename=safe_name)
                await application.bot.send_document(
                    chat_id=chat_id,
                    document=video_if,
                    read_timeout=3600,
                    write_timeout=3600,
                    connect_timeout=3600,
                )
            
            await application.bot.edit_message_text(chat_id=chat_id, message_id=message_id, text=f"✅ Готово! Видео скачано ({selected_format_text}).")

        except Exception as e:
            logger.exception(f"Error processing download for chat {chat_id}")
            error_message = f"❌ Произошла ошибка: {e}"
            if len(error_message) > 400:
                error_message = error_message[:400] + "..."
            try:
                await application.bot.edit_message_text(chat_id=chat_id, message_id=message_id, text=error_message)
            except Exception as e2:
                logger.error(f"Failed to even send error message to chat {chat_id}: {e2}")

        finally:
            if output_path and Path(output_path).exists():
                try:
                    os.remove(output_path)
                except Exception:
                    logger.warning("Temp file remove failed", exc_info=True)
            # Process next item in the queue in the next iteration
            await update_queue_messages(application)


async def download_selection(update: Update, context: CallbackContext) -> None:
    """Adds a download request to the queue."""
    query = update.callback_query
    await query.answer()

    try:
        itag_str, url_key = query.data.split(":", 1)
        itag = int(itag_str)
        url = context.user_data.get(url_key)

        if not url:
            await query.edit_message_text("❌ Ошибка: URL видео не найден. Пожалуйста, отправьте ссылку заново.")
            return

        # Re-fetch streams to get details of the selected format
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
        
        # Add to queue
        queue = context.bot_data['download_queue']
        queue.append((query.message.chat_id, query.message.message_id, url, itag, selected_format_text))

        # Notify user of queue position
        await query.edit_message_text(f"✅ Ваша заявка добавлена в очередь. Место в очереди: {len(queue)}")

        # Clean up user_data for the URL key
        if url_key in context.user_data:
            del context.user_data[url_key]

    except Exception as e:
        logger.exception(f"Error in download_selection for query data: {query.data}")
        await query.edit_message_text(f"❌ Произошла ошибка при добавлении в очередь: {e}")


async def post_init(application: Application) -> None:
    """Post initialization hook for the bot."""
    await application.bot.set_my_commands([
        BotCommand("start", "Запустить бота"),
    ])
    # Initialize queue
    application.bot_data['download_queue'] = deque()
    # Start the queue processor
    asyncio.create_task(queue_processor(application))


def main() -> None:
    """Запускает бота."""
    if not TELEGRAM_BOT_TOKEN:
        logger.error("Ошибка: Токен TELEGRAM_BOT_TOKEN не найден в .env файле.")
        return

    application = Application.builder().token(TELEGRAM_BOT_TOKEN).post_init(post_init).base_url("http://telegram-bot-api:8081/bot").base_file_url("http://telegram-bot-api:8081/file/bot").build()

    application.add_handler(CommandHandler("start", start))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    application.add_handler(CallbackQueryHandler(download_selection))

    logger.info("Бот запущен...")
    application.run_polling()


if __name__ == "__main__":
    main()