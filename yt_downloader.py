#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import json
import subprocess
import os
from pathlib import Path
from typing import List, Optional

COOKIES_FILE = Path("cookies.txt")



# --- YouTube загрузка ---
def download_video_only(url, video_path):
    subprocess.run([
        "python3", "-m", "yt_dlp",
        "-f", "bestvideo[height<=720]",
        "--user-agent", "Mozilla/5.0",
        "-o", str(video_path),
        url
    ])
    return video_path

def download_audio_only(url, audio_path):
    """
    Скачивает аудио с YouTube и конвертирует в мини-файл для Whisper-1:
    - формат: .ogg
    - кодек: opus
    - моно
    - частота дискретизации: 24 kHz
    - битрейт: 32 kbps
    """

    audio_path = Path(audio_path).with_suffix(".ogg")
    temp_path = audio_path.with_suffix(".temp.m4a")

    # 1. Скачиваем лучший аудиотрек
    subprocess.run([
        "python3", "-m", "yt_dlp",
        "-f", "bestaudio",
        "--user-agent", "Mozilla/5.0",
        "-o", str(temp_path),
        url
    ], check=True)

    # 2. Конвертируем в мини-файл .ogg для Whisper-1
    subprocess.run([
        "ffmpeg",
        "-i", str(temp_path),
        "-ac", "1",          # моно
        "-ar", "24000",      # частота дискретизации
        "-c:a", "libopus",   # кодек Opus
        "-b:a", "32k",       # битрейт
        "-y",
        str(audio_path)
    ], check=True)

    # 3. Удаляем временный скачанный файл
    temp_path.unlink(missing_ok=True)

    return audio_path


def merge_video_audio(video_path, audio_path, output_path):

    video_path = str(video_path)
    audio_path = str(audio_path)
    output_path = str(output_path)

    # ffmpeg команда: конвертируем аудио в AAC для совместимости с MP4
    cmd = [
        "ffmpeg",
        "-i", video_path,
        "-i", audio_path,
        "-c:v", "copy",        # копируем видео без перекодирования
        "-c:a", "aac",         # конвертируем аудио в AAC
        "-b:a", "128k",        # битрейт аудио
        "-shortest",           # чтобы длительность файла была равна меньшей из видео/аудио
        "-y",                  # перезаписываем если есть
        output_path
    ]

    subprocess.run(cmd, check=True)
    
    # удаляем видео без звука
    if os.path.exists(video_path):
        os.remove(video_path)
    if os.path.exists(audio_path):
        os.remove(audio_path)
        
    return output_path


# ====== твоя точка входа ======
def process_youtube_url(url: str, download_dir: Path = Path("downloads")) -> Path:
    
    print("\nСкачиваю лучшее доступное качество...\n")
    video_only = download_video_only(url, download_dir / "video_only.mp4")
    audio_only = download_audio_only(url, download_dir / "audio_only.ogg")
    video_full = merge_video_audio(video_only, audio_only, download_dir / "video.mp4")
    return video_full


# пример использования из кода:
if __name__ == "__main__":
    out = process_youtube_url("https://www.youtube.com/watch?v=dQw4w9WgXcQ")
    print("Готово:", out)
