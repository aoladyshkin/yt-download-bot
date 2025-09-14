import os
import uuid
from pathlib import Path

from dotenv import load_dotenv
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, filters, CallbackContext, CallbackQueryHandler

from yt_downloader import process_youtube_url, get_video_streams

# Загружаем переменные окружения
load_dotenv()
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")

# Директория для скачивания
DOWNLOAD_DIR = Path("downloads")
DOWNLOAD_DIR.mkdir(exist_ok=True)


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

        await query.edit_message_text("⏳ Начинаю скачивание... Это может занять некоторое время.")

        output_path = process_youtube_url(url, DOWNLOAD_DIR, itag=itag)

        if not output_path or not Path(output_path).exists():
             await query.edit_message_text("❌ Не удалось скачать видео.")
             return

        await query.edit_message_text("⬆️ Отправляю видео...")
        
        with open(output_path, "rb") as video_file:
            await context.bot.send_video(
                chat_id=query.message.chat_id, 
                video=video_file, 
                supports_streaming=True,
                read_timeout=120, 
                write_timeout=120,
                connect_timeout=120,
            )

        os.remove(output_path)
        await query.edit_message_text("✅ Готово!")

    except Exception as e:
        error_message = f"❌ Произошла ошибка: {e}"
        if hasattr(e, 'stderr') and e.stderr:
            error_message += f"\n---LOG---\n{e.stderr.decode()}"
        await query.edit_message_text(error_message)
    finally:
        # Clean up user_data
        if 'url_key' in locals() and url_key in context.user_data:
            del context.user_data[url_key]


def main() -> None:
    """Запускает бота."""
    if not TELEGRAM_BOT_TOKEN:
        print("Ошибка: Токен TELEGRAM_BOT_TOKEN не найден в .env файле.")
        return

    application = Application.builder().token(TELEGRAM_BOT_TOKEN).build()

    application.add_handler(CommandHandler("start", start))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    application.add_handler(CallbackQueryHandler(download_selection))

    print("Бот запущен...")
    application.run_polling()


if __name__ == "__main__":
    main()
