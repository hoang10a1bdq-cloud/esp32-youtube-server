
import os
import io
import wave
import json
import tempfile
import logging

from flask import Flask, request, jsonify, send_file
from google import genai
from google.genai import types
from gtts import gTTS

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 10 * 1024 * 1024

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


# ==========================================
# 1. KIEM TRA SERVER
# ==========================================
@app.get("/")
def home():
    return """
    <h2>ESP32 AI Voice Chat Server</h2>
    <p>Status: Running</p>
    <p>Endpoints: /health, /voice_chat, /tts</p>
    """


@app.get("/health")
def health():
    return jsonify(
        ok=True,
        service="ESP32 AI Voice Chat Server"
    )


# ==========================================
# 2. NHAN PCM TU ESP32 -> GEMINI -> JSON
# PCM: mono, signed 16-bit, 8000 Hz
# ==========================================
@app.post("/voice_chat")
def voice_chat():
    pcm_data = request.get_data(cache=False)

    if not pcm_data or len(pcm_data) % 2 != 0:
        return jsonify(
            ok=False,
            error="Audio PCM khong hop le"
        ), 400

    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        return jsonify(
            ok=False,
            error="Thieu GEMINI_API_KEY tren server"
        ), 503

    temp_file_name = None
    client = None
    uploaded_file = None

    try:
        # Tao WAV tu PCM
        wav_buffer = io.BytesIO()

        with wave.open(wav_buffer, "wb") as wav_file:
            wav_file.setnchannels(1)
            wav_file.setsampwidth(2)
            wav_file.setframerate(8000)
            wav_file.writeframes(pcm_data)

        # Ghi file WAV tam
        with tempfile.NamedTemporaryFile(
            suffix=".wav",
            delete=False
        ) as temp_file:
            temp_file.write(wav_buffer.getvalue())
            temp_file_name = temp_file.name

        # Upload audio len Gemini
        client = genai.Client(api_key=api_key)
        uploaded_file = client.files.upload(
            file=temp_file_name
        )

        prompt = """
Ban la tro ly AI tieng Viet tren robot ESP32.

Hay nghe doan am thanh va tra ve:
1. transcript: noi dung nguoi dung noi.
2. answer: cau tra loi ngan gon, duoi 40 tu.

Chi tra ve JSON hop le, khong dung Markdown:
{
  "transcript": "noi dung nguoi dung noi",
  "answer": "cau tra loi"
}

Neu chi co tieng on, khong nghe ro giong nguoi:
{
  "transcript": "[NOISE]",
  "answer": ""
}
"""

        response = client.models.generate_content(
            model=os.environ.get(
                "GEMINI_MODEL",
                "gemini-3.5-flash-lite"
            ),
            contents=[uploaded_file, prompt],
            config=types.GenerateContentConfig(
                response_mime_type="application/json"
            )
        )

        raw_text = (response.text or "").strip()
        data = json.loads(raw_text)

        transcript = str(data.get("transcript", "")).strip()
        answer = str(data.get("answer", "")).strip()

        if "[NOISE]" in transcript.upper():
            return jsonify(
                ok=True,
                transcript="(Khong nghe ro)",
                answer=""
            )

        return jsonify(
            ok=True,
            transcript=transcript,
            answer=answer
        )

    except Exception:
        logger.exception("Voice chat failed")
        return jsonify(
            ok=False,
            error="Xu ly am thanh that bai"
        ), 502

    finally:
        # Don dep file tam va file da upload
        if client is not None and uploaded_file is not None:
            try:
                client.files.delete(name=uploaded_file.name)
            except Exception:
                logger.warning("Khong xoa duoc file Gemini")

        if temp_file_name and os.path.exists(temp_file_name):
            try:
                os.remove(temp_file_name)
            except OSError:
                logger.warning("Khong xoa duoc file WAV tam")


# ==========================================
# 3. TEXT -> MP3 TIENG VIET
# GET /tts?text=Xin%20chao
# Tra ve truc tiep audio/mpeg
# ==========================================
@app.get("/tts")
def text_to_speech():
    text = request.args.get("text", "").strip()

    if not text:
        return jsonify(
            ok=False,
            error="Thieu tham so text"
        ), 400

    if len(text) > 500:
        return jsonify(
            ok=False,
            error="Text qua dai, toi da 500 ky tu"
        ), 400

    try:
        audio_buffer = io.BytesIO()

        tts = gTTS(
            text=text,
            lang="vi",
            slow=False
        )
        tts.write_to_fp(audio_buffer)
        audio_buffer.seek(0)

        return send_file(
            audio_buffer,
            mimetype="audio/mpeg",
            as_attachment=False,
            download_name="answer.mp3",
            max_age=0
        )

    except Exception:
        logger.exception("TTS generation failed")
        return jsonify(
            ok=False,
            error="Tao MP3 that bai"
        ), 502


# ==========================================
# 4. CHAY SERVER
# ==========================================
if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(
        host="0.0.0.0",
        port=port,
        debug=False
    )
