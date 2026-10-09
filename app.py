import os
import re
import time
import threading
import subprocess

from flask import Flask, request, jsonify, Response

app = Flask(__name__)

# Trang thai dung chung
lock = threading.Lock()
latest_jpeg = None
current_url = ""
status = "Chua co video"
last_error = ""

# Quan ly worker
worker_lock = threading.Lock()
worker_running = False


def extract_video_id(url):
    patterns = [
        r"(?:youtube\.com/watch\?(?:.*&)?v=|youtu\.be/)([A-Za-z0-9_-]{11})",
        r"youtube\.com/shorts/([A-Za-z0-9_-]{11})",
        r"youtube\.com/live/([A-Za-z0-9_-]{11})",
        r"youtube\.com/embed/([A-Za-z0-9_-]{11})",
    ]

    for pattern in patterns:
        match = re.search(pattern, url)
        if match:
            return match.group(1)

    return None


def capture_worker(url):
    global latest_jpeg, status, last_error, worker_running

    try:
        video_id = extract_video_id(url)

        if not video_id:
            with lock:
                status = "Link YouTube khong hop le"
                last_error = "Khong tim thay video ID"
            return

        video_url = "https://www.youtube.com/watch?v=" + video_id

        command = [
            "yt-dlp",
            "--verbose",
            "--no-warnings",
            "--no-playlist",
            "--js-runtimes", "deno",
            "-f", "best[height<=360]/best",
            "-g",
            video_url,
        ]

        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=90,
        )

        if result.returncode != 0 or not result.stdout.strip():
            error_text = (
                result.stderr or "yt-dlp khong tra ve URL"
            )[-3000:]

            with lock:
                status = "Loi lay video"
                last_error = error_text

            return

        stream_url = result.stdout.strip().splitlines()[0]

        with lock:
            status = "Dang lay hinh"
            last_error = ""

        # Lay khung hinh JPEG
        while True:
            ffmpeg_cmd = [
                "ffmpeg",
                "-nostdin",
                "-loglevel", "error",
                "-i", stream_url,
                "-frames:v", "1",
                "-vf",
                "scale=240:240:force_original_aspect_ratio=decrease,"
                "pad=240:240:(ow-iw)/2:(oh-ih)/2",
                "-q:v", "6",
                "-f", "image2pipe",
                "-vcodec", "mjpeg",
                "pipe:1",
            ]

            try:
                frame = subprocess.run(
                    ffmpeg_cmd,
                    capture_output=True,
                    timeout=25,
                )

                if frame.returncode == 0 and frame.stdout:
                    with lock:
                        latest_jpeg = frame.stdout
                        status = "OK"
                        last_error = ""
                else:
                    error_text = frame.stderr.decode(
                        "utf-8", errors="ignore"
                    )[-1500:]

                    with lock:
                        status = "Loi lay frame"
                        last_error = (
                            error_text or "FFmpeg khong tao duoc JPEG"
                        )

                    break

            except subprocess.TimeoutExpired:
                with lock:
                    status = "Loi timeout FFmpeg"
                    last_error = "Doc frame qua 25 giay"
                break

            time.sleep(2)

    except subprocess.TimeoutExpired:
        with lock:
            status = "Timeout yt-dlp"
            last_error = "yt-dlp qua 90 giay ma chua tra ket qua"

    except Exception as exc:
        with lock:
            status = "Loi lay video"
            last_error = str(exc)[-3000:]

    finally:
        with worker_lock:
            worker_running = False


@app.get("/")
def home():
    return """
    <!doctype html>
    <html>
    <head>
        <meta charset="utf-8">
        <title>ESP32 YouTube Server</title>
    </head>
    <body>
        <h2>ESP32 YouTube JPEG Server</h2>
        <p>Set video: /set?url=YOUTUBE_URL</p>
        <p>Get frame: /frame.jpg</p>
        <p>Status: /status</p>
        <p>Health: /health</p>
    </body>
    </html>
    """


@app.get("/set")
def set_video():
    global current_url, latest_jpeg, status, last_error
    global worker_running

    url = request.args.get("url", "").strip()
    video_id = extract_video_id(url)

    if not video_id:
        return jsonify(error="Link YouTube khong hop le"), 400

    with worker_lock:
        if worker_running:
            with lock:
                current_status = status

            return jsonify(
                message="Server dang xu ly video",
                status=current_status,
            ), 409

        worker_running = True

    with lock:
        current_url = url
        latest_jpeg = None
        status = "Dang khoi dong"
        last_error = ""

    thread = threading.Thread(
        target=capture_worker,
        args=(url,),
        daemon=True,
    )
    thread.start()

    return jsonify(
        message="Da nhan link video",
        url=url,
        video_id=video_id,
    )


@app.get("/status")
def get_status():
    with lock:
        return jsonify(
            status=status,
            has_frame=latest_jpeg is not None,
            error=last_error,
            url=current_url,
        )


@app.get("/frame.jpg")
def get_frame():
    with lock:
        frame = latest_jpeg

    if frame is None:
        return jsonify(
            error="Chua co frame; xem /status"
        ), 503

    return Response(
        frame,
        mimetype="image/jpeg",
        headers={
            "Cache-Control": "no-store, no-cache, must-revalidate"
        },
    )


@app.get("/health")
def health():
    return jsonify(ok=True)


if __name__ == "__main__":
    app.run(
        host="0.0.0.0",
        port=int(os.environ.get("PORT", "10000")),
    )


# ===== ROBOT AI API: GOOGLE GEMINI =====
import os
from google import genai
from google.genai import types

@app.post("/chat")
def robot_chat():
    data = request.get_json(silent=True) or {}
    question = data.get("message", "")

    if not isinstance(question, str) or not question.strip():
        return jsonify(error="message khong duoc de trong"), 400

    if len(question) > 1000:
        return jsonify(error="Cau hoi qua dai"), 400

    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        return jsonify(
            ok=False,
            error="Server chua cau hinh GEMINI_API_KEY"
        ), 503

    try:
        client = genai.Client(api_key=api_key)

        response = client.models.generate_content(
            model=os.environ.get(
                "GEMINI_MODEL",
                "gemini-2.5-flash-lite"
            ),
            contents=question,
            config=types.GenerateContentConfig(
                system_instruction=(
                    "Ban la robot AI than thien. "
                    "Tra loi bang tieng Viet, ngan gon, de hieu. "
                    "Uu tien cau tra loi phu hop voi man hinh nho."
                ),
                max_output_tokens=180,
            ),
        )

        answer = (response.text or "").strip()

        if not answer:
            return jsonify(
                ok=False,
                error="AI khong tra ve noi dung"
            ), 502

        return jsonify(
            ok=True,
            question=question,
            answer=answer
        )

    except Exception:
        app.logger.exception("Gemini robot request failed")
        return jsonify(
            ok=False,
            error="Khong goi duoc dich vu AI"
        ), 502
        
import io
import wave
import tempfile
import os

# Dung lai thu vien google-genai da cai cho endpoint /chat
from google import genai


@app.post("/transcribe")
def transcribe_audio():
    # Nhan PCM mono 16-bit, 16 kHz tu ESP32
    pcm_data = request.get_data(cache=False)

    max_bytes = 16000 * 2 * 10  # toi da 10 giay

    if not pcm_data:
        return jsonify(ok=False, error="Khong co audio"), 400

    if len(pcm_data) > max_bytes:
        return jsonify(ok=False, error="Audio qua dai"), 413

    if len(pcm_data) % 2 != 0:
        return jsonify(ok=False, error="PCM khong hop le"), 400

    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        return jsonify(ok=False, error="Thieu GEMINI_API_KEY"), 503

    try:
        # Dong goi PCM thanh WAV
        wav_buffer = io.BytesIO()

        with wave.open(wav_buffer, "wb") as wav_file:
            wav_file.setnchannels(1)
            wav_file.setsampwidth(2)
            wav_file.setframerate(16000)
            wav_file.writeframes(pcm_data)

        with tempfile.NamedTemporaryFile(
            suffix=".wav", delete=True
        ) as temp_file:
            temp_file.write(wav_buffer.getvalue())
            temp_file.flush()

            client = genai.Client(api_key=api_key)

            audio_file = client.files.upload(
                file=temp_file.name
            )

            result = client.interactions.create(
                model="gemini-3.5-transcribe",
                input=[
                    {
                        "type": "audio",
                        "uri": audio_file.uri,
                        "mime_type": "audio/wav",
                    }
                ],
            )

        transcript = (result.output_text or "").strip()

        return jsonify(
            ok=True,
            transcript=transcript
        )

    except Exception:
        app.logger.exception("Transcription failed")
        return jsonify(
            ok=False,
            error="Khong nhan dien duoc audio"
        ), 502
