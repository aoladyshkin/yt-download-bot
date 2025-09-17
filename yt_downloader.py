#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import subprocess
import logging
from pathlib import Path
from pytubefix import YouTube
from pytubefix.exceptions import (
    RegexMatchError, VideoUnavailable, AgeRestrictedError, PytubeFixError
)

logger = logging.getLogger(__name__)

def on_progress(stream, chunk, bytes_remaining):
    total = stream.filesize or 0
    downloaded = total - bytes_remaining
    if total > 0:
        pct = downloaded * 100 / total
        bar_len = 30
        filled = int(bar_len * pct / 100)
        bar = "█" * filled + "·" * (bar_len - filled)
        # Using logger.info for progress, but it might be too verbose for console
        # For a cleaner console, this could be removed or handled differently
        logger.info(f"\r[{bar}] {pct:5.1f}%  {downloaded/1_048_576:.2f}/{total/1_048_176:.2f} MiB", extra={'end': ''})

def safe_filename(title: str) -> str:
    bad = '<>:\"/\\|?*'
    cleaned = "".join(c for c in title if c not in bad)
    return cleaned.strip()[:120] or "video"

def get_video_streams(url: str):
    """Gets available H.264 video streams for a YouTube video."""
    logger.info(f"Getting H.264 streams for: {url}")
    yt = YouTube(url)
    stream_options = []
    
    audio_streams = yt.streams.filter(file_extension="mp4", only_audio=True).order_by("abr").desc()
    best_audio = audio_streams.first() if audio_streams else None
    
    # Get all MP4 video streams and filter for H.264 codec
    all_video_streams = yt.streams.filter(file_extension="mp4", type="video").order_by("resolution").desc()
    compatible_streams = [s for s in all_video_streams if s.video_codec and s.video_codec.startswith('avc')]

    added_resolutions = set()
    for stream in compatible_streams:
        if stream.resolution and stream.resolution not in added_resolutions:
            filesize = stream.filesize or 0
            # Add audio filesize for adaptive streams to show a more realistic total size
            if not stream.is_progressive and best_audio:
                filesize += best_audio.filesize or 0

            stream_options.append({
                "itag": stream.itag,
                "type": "video",
                "resolution": stream.resolution,
                "filesize": filesize,
            })
            added_resolutions.add(stream.resolution)

    if best_audio:
        stream_options.append({
            "itag": best_audio.itag,
            "type": "audio",
            "abr": best_audio.abr,
            "filesize": best_audio.filesize or 0,
        })
        
    return stream_options, yt.title

def download_video(url: str, out_dir: Path, itag: int):
    """Downloads a stream by itag, merging with ffmpeg if necessary."""
    logger.info(f"Processing: {url} with itag: {itag}")
    yt = YouTube(url, on_progress_callback=on_progress)
    stream = yt.streams.get_by_itag(itag)

    if not stream:
        raise ValueError(f"Stream with itag={itag} not found.")

    out_dir.mkdir(parents=True, exist_ok=True)
    target_name = safe_filename(yt.title)
    
    # Case 1: The selected stream is audio-only
    if stream.type == "audio":
        logger.info("Downloading audio stream...")
        filepath = stream.download(output_path=str(out_dir), filename=f"{target_name}.m4a")
        logger.info(f"Готово: {filepath}")
        return filepath

    # Case 2: The selected stream is progressive (video+audio)
    if stream.is_progressive:
        logger.info("Downloading progressive video stream...")
        filepath = stream.download(output_path=str(out_dir), filename=f"{target_name}.mp4")
        logger.info(f"Готово: {filepath}")
        return filepath

    # Case 3: The selected stream is adaptive (video-only), requires merging
    logger.info("Downloading adaptive video stream (merging required)...")
    
    # 1. Download video-only stream
    video_temp_path = stream.download(output_path=str(out_dir), filename_prefix="video_")
    logger.info("Video part downloaded. Now downloading audio part.")

    # 2. Download best audio stream
    audio_stream = yt.streams.filter(file_extension="mp4", type="audio").order_by("abr").desc().first()
    if not audio_stream:
        os.remove(video_temp_path)
        raise RuntimeError("No audio stream found to merge.")
    
    audio_temp_path = audio_stream.download(output_path=str(out_dir), filename_prefix="audio_")
    logger.info("Audio part downloaded. Now merging...")

    # 3. Merge using ffmpeg
    final_path = out_dir / f"{target_name}.mp4"
    
    command = [
        'ffmpeg',
        '-y',  # Overwrite output file if it exists
        '-i', video_temp_path,
        '-i', audio_temp_path,
        '-c:v', 'copy',
        '-c:a', 'copy',
        str(final_path)
    ]
    
    try:
        result = subprocess.run(command, capture_output=True, text=True, check=True)
    except FileNotFoundError:
        raise RuntimeError("ffmpeg not found. Please install ffmpeg and ensure it's in your PATH.")
    except subprocess.CalledProcessError as e:
        os.remove(video_temp_path)
        os.remove(audio_temp_path)
        raise RuntimeError(f"ffmpeg failed to merge files. STDERR: {e.stderr} STDOUT: {e.stdout}")

    # 4. Clean up temporary files
    os.remove(video_temp_path)
    os.remove(audio_temp_path)

    logger.info(f"Готово: {final_path}")
    return str(final_path)

def process_youtube_url(url: str, out_dir: str = "downloads", itag: int = None):
    """Wrapper to download a video by itag."""
    out_dir = Path(out_dir)
    if itag is None:
        raise ValueError("An 'itag' must be provided to select a stream.")

    try:
        return download_video(url, out_dir, itag=itag)
    except (AgeRestrictedError, VideoUnavailable, RegexMatchError, PytubeFixError) as e:
        # Handle specific pytube errors
        error_message = f"A YouTube-related error occurred: {e}"
        logger.info(f"YouTube-related error: {e}")
        raise RuntimeError(error_message) from e
    except Exception as e:
        # Handle other errors like ffmpeg issues or file errors
        logger.info(f"An unexpected error occurred: {e}")
        raise e

if __name__ == "__main__":
    # Example usage (for testing)
    test_url = "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
    logger.info(f"Getting streams for {test_url}")
    streams, title = get_video_streams(test_url)
    logger.info(f"Title: {title}")
    for s in streams:
        logger.info(s)
    
    # To test download, uncomment below and set an itag from the list printed above
    if streams:
        test_itag = streams[0]['itag'] # e.g., download the first option
        logger.info(f"Testing download with itag {test_itag}...")
        process_youtube_url(test_url, itag=test_itag)
