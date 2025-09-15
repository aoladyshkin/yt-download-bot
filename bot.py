import os
import uuid
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


async def download_selection(update: Update, context: CallbackContext) -> None:
    """Обрабатывает клики по кнопкам для скачивания выбранного формата."""
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
                if stream_info['type'] == 'video':
                    selected_format_text = f"📹 {stream_info['resolution']}"
                else:
                    selected_format_text = f"🎵 {stream_info['abr']}"
                break

        await query.edit_message_text(f"⏳ Начинаю скачивание ({selected_format_text})... Это может занять некоторое время.")

        output_path = process_youtube_url(url, DOWNLOAD_DIR, itag=itag)

        if not output_path or not Path(output_path).exists():
             await query.edit_message_text("❌ Не удалось скачать видео.")
             return

        file_size = os.path.getsize(output_path)
        if file_size > 2 * 1024 * 1024 * 1024:
            await query.edit_message_text("❌ Ошибка: Файл слишком большой для отправки через Telegram (больше 2 ГБ).")
            return

        # Безопасное имя файла (иногда экзотика в заголовках ломает multipart)
        safe_name = Path(output_path).name.encode('utf-8', 'ignore').decode('utf-8')

        logger.info(f"Attempting to send video: {output_path} to chat_id: {query.message.chat_id}")
        await query.edit_message_text("⬆️ Отправляю видео...")

        logger.info("Starting video upload...")

        # ВАЖНО: держим файл открытым на время await,
        # и ставим read_file_handle=False для потоковой передачи
        with open(output_path, "rb") as fh:
            video_if = InputFile(fh, filename=safe_name)
            await context.bot.send_video(
                chat_id=query.message.chat_id,
                video=video_if,
                supports_streaming=True,
                read_timeout=3600,
                write_timeout=3600,
                connect_timeout=3600,
            )
        logger.info("Video sent OK")
        try:
            os.remove(output_path)
        except Exception:
            logger.warning("Temp file remove failed", exc_info=True)
        await query.edit_message_text("✅ Готово!")

    except Exception as e:
        logger.exception(f"Error during download_selection for query data: {query.data}")
        error_message = f"❌ Произошла ошибка: {e}"
        if len(error_message) > 400:
            error_message = error_message[:400] + "..."
        await query.edit_message_text(error_message)
    finally:
        # Clean up user_data
        if 'url_key' in locals() and url_key in context.user_data:
            del context.user_data[url_key]


async def post_init(application: Application) -> None:
    """Post initialization hook for the bot."""
    await application.bot.set_my_commands([
        BotCommand("start", "Запустить бота"),
    ])


def main() -> None:
    """Запускает бота."""
    if not TELEGRAM_BOT_TOKEN:
        logger.error("Ошибка: Токен TELEGRAM_BOT_TOKEN не найден в .env файле.")
        return

    application = Application.builder().token(TELEGRAM_BOT_TOKEN).post_init(post_init).build()

    application.add_handler(CommandHandler("start", start))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    application.add_handler(CallbackQueryHandler(download_selection))

    logger.info("Бот запущен...")
    application.run_polling()


if __name__ == "__main__":
    main()
