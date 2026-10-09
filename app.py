
import os
import re
import io
import threading
import time
import subprocess

from flask import Flask, request, jsonify, Response
from PIL import Image

app = Flask(__name__)

lock = threading.Lock()
latest_jpeg = None
current_url = ""
status = "Chua co video"
last_error = ""

def extract_video_id(url):
    patterns = [
        r"(?:youtube\.com/watch\?v=|youtu\.be/|youtube\.com/live/)([A-Za-z0-9_-]{11})",
        r"youtube\.com/shorts/([A-Za-z0-9_-]{11})",
        r"youtube\.com/embed/([A-Za-z0-9_-]{11})",
    ]
    for pattern in patterns:
        match = re.search(pattern, url)
        if match:
            return match.group(1)
    return None

def capture_worker(url):
    global latest_jpeg, status, last_error

    video_id = extract_video_id(url)
    if not video_id:
        with lock:
            status = "Link YouTube khong hop le"
        return

    video_url = "https://www.youtube.com/watch?v=" + video_id

    command = [
        "yt-dlp",
        "--no-warnings",
        "--no-playlist",
        "-f", "best[height<=360]/best",
        "-g",
        video_url
    ]

    try:
        result = subprocess.run(
            command, capture_output=True, text=True, timeout=45
        )
        if result.returncode != 0 or not result.stdout.strip():
            raise RuntimeError(result.stderr[-500:])

        stream_url = result.stdout.strip().splitlines()[0]

        # Try reading a single frame every few seconds.
        while True:
            ffmpeg_cmd = [
                "ffmpeg", "-nostdin", "-loglevel", "error",
                "-i", stream_url,
                "-frames:v", "1",
                "-vf", "scale=240:240:force_original_aspect_ratio=decrease,pad=240:240:(ow-iw)/2:(oh-ih)/2",
                "-q:v", "6", "-f", "image2pipe", "-vcodec", "mjpeg", "pipe:1"
            ]

            frame = subprocess.run(
                ffmpeg_cmd, capture_output=True, timeout=25
            )

            if frame.returncode == 0 and frame.stdout:
                with lock:
                    latest_jpeg = frame.stdout
                    status = "OK"
                    last_error = ""
            else:
                with lock:
                    status = "Khong lay duoc frame"
                    last_error = frame.stderr.decode(
                        "utf-8", errors="ignore"
                    )[-500:]

            time.sleep(2)

    except Exception as exc:
        with lock:
            status = "Loi lay video"
            last_error = str(exc)[-500:]


@app.get("/")
def home():
    return """
    <h2>ESP32 YouTube JPEG server</h2>
    <p>Set video: /set?url=YOUTUBE_URL</p>
    <p>Get frame: /frame.jpg</p>
    <p>Status: /status</p>
    """

@app.get("/set")
def set_video():
    global current_url, status, last_error

    url = request.args.get("url", "").strip()
    if not extract_video_id(url):
        return jsonify(error="Link YouTube khong hop le"), 400

    with lock:
        current_url = url
        latest_jpeg = None
        status = "Dang khoi dong"
        last_error = ""

    # Start capture in background. Only one video worker per service.
    threading.Thread(target=capture_worker, args=(url,), daemon=True).start()
    return jsonify(message="Da nhan link video", url=url)

@app.get("/status")
def get_status():
    with lock:
        return jsonify(
            status=status,
            has_frame=latest_jpeg is not None,
            error=last_error
        )

@app.get("/frame.jpg")
def get_frame():
    with lock:
        frame = latest_jpeg

    if frame is None:
        return jsonify(error="Chua co frame; xem /status"), 503

    return Response(frame, mimetype="image/jpeg",
                    headers={"Cache-Control": "no-store"})

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 10000)))
