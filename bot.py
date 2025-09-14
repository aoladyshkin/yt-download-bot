import os
import uuid
from pathlib import Path

from dotenv import load_dotenv
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, CallbackContext

from yt_downloader import process_youtube_url

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
    """Обрабатывает входящие сообщения, скачивает видео и отправляет его."""
    message = update.message
    if not message.text or ("youtube.com/" not in message.text and "youtu.be/" not in message.text):
        await message.reply_text("Пожалуйста, отправьте действительную ссылку на YouTube.")
        return

    url = message.text
    await message.reply_text("Начинаю скачивание... Это может занять некоторое время.")

    try:
        # Вызываем единую функцию для обработки URL
        output_path = process_youtube_url(url, DOWNLOAD_DIR)

        # Отправляем видео
        await message.reply_text("Отправляю видео...")
        await context.bot.send_video(chat_id=message.chat_id, video=open(output_path, "rb"), supports_streaming=True, read_timeout=120, write_timeout=120)

        # Удаляем финальный файл
        os.remove(output_path)

        await message.reply_text("Готово!")

    except Exception as e:
        error_message = f"Произошла ошибка: {e}"
        if hasattr(e, 'stderr') and e.stderr:
            error_message += f"\n---LOG---\n{e.stderr.decode()}"
        await message.reply_text(error_message)


def main() -> None:
    """Запускает бота."""
    if not TELEGRAM_BOT_TOKEN:
        print("Ошибка: Токен TELEGRAM_BOT_TOKEN не найден в .env файле.")
        return

    application = Application.builder().token(TELEGRAM_BOT_TOKEN).build()

    application.add_handler(CommandHandler("start", start))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    print("Бот запущен...")
    application.run_polling()


if __name__ == "__main__":
    main()