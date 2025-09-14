#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from pathlib import Path
from pytubefix import YouTube, Playlist
from pytubefix.exceptions import (
    RegexMatchError, VideoUnavailable, AgeRestrictedError, PytubeFixError
)

def on_progress(stream, chunk, bytes_remaining):
    total = stream.filesize or 0
    downloaded = total - bytes_remaining
    if total > 0:
        pct = downloaded * 100 / total
        bar_len = 30
        filled = int(bar_len * pct / 100)
        bar = "█" * filled + "·" * (bar_len - filled)
        print(f"\r[{bar}] {pct:5.1f}%  {downloaded/1_048_576:.2f}/{total/1_048_576:.2f} MiB", end="", flush=True)

def safe_filename(title: str) -> str:
    bad = '<>:"/\\|?*'
    cleaned = "".join(c for c in title if c not in bad)
    return cleaned.strip()[:120] or "video"


def get_video_streams(url: str):
    """Gets available streams for a YouTube video."""
    print(f"\n=== Getting streams for: {url}")
    yt = YouTube(url)
    
    stream_options = []
    
    # Video streams (progressive, mp4, <=720p)
    video_streams = yt.streams.filter(progressive=True, file_extension="mp4").order_by("resolution").desc()
    for stream in video_streams:
        if not stream.resolution or int(stream.resolution.replace('p','')) > 720:
            continue
        stream_options.append({
            "itag": stream.itag,
            "type": "video",
            "resolution": stream.resolution,
            "filesize": stream.filesize,
        })
    
    # Audio only streams (mp4)
    audio_streams = yt.streams.filter(only_audio=True, file_extension="mp4").order_by("abr").desc()
    for stream in audio_streams:
        stream_options.append({
            "itag": stream.itag,
            "type": "audio",
            "abr": stream.abr,
            "filesize": stream.filesize,
        })
        
    return stream_options, yt.title


def download_video(
    url: str,
    out_dir: Path,
    audio_only: bool = False,
    filename = None,
    itag = None
):
    print(f"\n=== Обработка: {url}")
    yt = YouTube(url, on_progress_callback=on_progress)
    print(f"Название: {yt.title}")
    print(f"Канал:   {yt.author}")

    if itag is not None:
        stream = yt.streams.get_by_itag(itag)
        if stream is None:
            raise ValueError(f"Не найден поток с itag={itag}.")
    else:
        if audio_only:
            stream = (
                yt.streams.filter(only_audio=True, file_extension="mp4")
                                   .order_by("abr")
                                   .desc()
                                   .first()
            )
            if stream is None:
                stream = yt.streams.filter(only_audio=True).order_by("abr").desc().first()
        else:
            stream = (
                yt.streams.filter(progressive=True, file_extension="mp4")
                                   .order_by("resolution")
                                   .desc()
                                   .first()
            )

    if stream is None:
        raise RuntimeError("Не удалось подобрать поток для загрузки.")

    out_dir.mkdir(parents=True, exist_ok=True)

    # Автоматически добавляем расширение
    if audio_only:
        ext = ".m4a"
    else:
        ext = ".mp4"

    target_name = filename or safe_filename(yt.title)
    if not target_name.lower().endswith(ext):
        target_name += ext

    print(f"Формат:  itag={stream.itag}, mime={stream.mime_type}, res/abr={stream.resolution or stream.abr}")
    print(f"Сохранение в: {out_dir.resolve()}")
    filepath = stream.download(output_path=str(out_dir), filename=target_name)
    print(f"\nГотово: {filepath}")
    return filepath


def process_youtube_url(
    url: str,
    out_dir: str = "downloads",
    audio_only: bool = False,
    filename = None,
    itag = None
):
    """Основная точка входа — скачивание видео/плейлиста"""
    out_dir = Path(out_dir)

    try:
        return download_video(url, out_dir, audio_only=audio_only, filename=filename, itag=itag)
    except AgeRestrictedError:
        print("\nОшибка: ролик с возрастным ограничением.")
    except VideoUnavailable:
        print("\nОшибка: видео недоступно.")
    except RegexMatchError:
        print("\nОшибка парсинга. Обновите pytubefix.")
    except PytubeFixError as e:
        print(f"\nОшибка pytubefix: {e}")
    except Exception as e:
        print(f"\nНеожиданная ошибка: {e}")
        
if __name__ == "__main__":
    process_youtube_url("https://www.youtube.com/watch?v=dQw4w9WgXcQ")  # Пример вызова
