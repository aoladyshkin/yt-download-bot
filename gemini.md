# Telegram YouTube Download Bot

This is a Telegram bot that allows users to download YouTube videos.

## Features

- Download YouTube videos by sending a link.
- Choose from available video resolutions (up to 720p).
- The bot downloads the video and sends it back to the user.

## How to Run

1.  **Prerequisites:**
    - Python 3
    - ffmpeg

2.  **Clone the repository (or download the files).**

3.  **Create a virtual environment:**
    ```bash
    python3 -m venv venv
    source venv/bin/activate
    ```

4.  **Install the dependencies:**
    ```bash
    pip install -r requirements.txt
    ```

5.  **Create a `.env` file** in the root directory and add your Telegram bot token:
    ```
    TELEGRAM_BOT_TOKEN="YOUR_TELEGRAM_BOT_TOKEN"
    ```

6.  **Run the bot:**
    ```bash
    python3 yt_downloader.py
    ```
