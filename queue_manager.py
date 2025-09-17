import asyncio
import logging
import os
from pathlib import Path

from telegram import InputFile
from telegram.ext import Application

from yt_downloader import process_youtube_url

logger = logging.getLogger(__name__)


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

            output_path = await asyncio.to_thread(process_youtube_url, url, Path("downloads"), itag)

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


def add_to_queue(context, chat_id, message_id, url, itag, selected_format_text):
    queue = context.bot_data['download_queue']
    queue.append((chat_id, message_id, url, itag, selected_format_text))
    return len(queue)
