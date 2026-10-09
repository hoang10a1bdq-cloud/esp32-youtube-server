import os
import io
import wave
import tempfile
import json

from flask import Flask, request, jsonify
from google import genai
from google.genai import types

app = Flask(__name__)

# ==========================================
# ENDPOINT: KIỂM TRA TRẠNG THÁI SERVER
# ==========================================
@app.get("/")
def home():
    return "<h2>ESP32 AI Voice Chat Server is Running!</h2>"

# ==========================================
# ENDPOINT: AI VOICE CHAT (NGHE & TRẢ LỜI CÙNG LÚC)
# ==========================================
@app.post("/voice_chat")
def voice_chat():
    # Nhận âm thanh PCM 16-bit 8000Hz từ ESP32
    pcm_data = request.get_data(cache=False)
    
    if not pcm_data or len(pcm_data) % 2 != 0:
        return jsonify(ok=False, error="Audio khong hop le"), 400

    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        return jsonify(ok=False, error="Thieu GEMINI_API_KEY"), 503

    try:
        # 1. Đóng gói Raw PCM thành file WAV 8000Hz
        wav_buffer = io.BytesIO()
        with wave.open(wav_buffer, "wb") as wav_file:
            wav_file.setnchannels(1)
            wav_file.setsampwidth(2)
            wav_file.setframerate(8000) 
            wav_file.writeframes(pcm_data)

        # 2. Tạo file tạm để gửi cho Gemini
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as temp_file:
            temp_file.write(wav_buffer.getvalue())
            temp_file.flush()
            temp_file_name = temp_file.name

        # 3. Gọi Gemini phân tích âm thanh và tạo câu trả lời
        client = genai.Client(api_key=api_key)
        audio_file = client.files.upload(file=temp_file_name)

        # Yêu cầu Gemini trả về JSON cứng
        prompt = """
        Bạn là một trợ lý AI thông minh tích hợp trên vi điều khiển.
        Hãy nghe đoạn âm thanh tiếng Việt này và thực hiện 2 việc:
        1. Chép lại chính xác lời người dùng nói.
        2. Trả lời câu hỏi/yêu cầu đó một cách ngắn gọn, súc tích (dưới 40 từ) vì màn hình hiển thị rất nhỏ.
        
        TRẢ VỀ KẾT QUẢ THEO ĐÚNG ĐỊNH DẠNG JSON SAU (không dùng markdown block):
        {
            "transcript": "nội dung người dùng nói",
            "answer": "câu trả lời của bạn"
        }
        
        Nếu đoạn âm thanh chỉ là tiếng ồn, tạp âm, tiếng quạt máy, không có giọng người rõ ràng, hãy trả về:
        {
            "transcript": "[NOISE]",
            "answer": ""
        }
        """

        response = client.models.generate_content(
            model="gemini-3.5-flash-lite",
            contents=[audio_file, prompt]
        )
        
        # 4. Dọn dẹp bộ nhớ
        try:
            client.files.delete(name=audio_file.name)
        except:
            pass
        os.remove(temp_file_name)

        # 5. Xử lý chuỗi JSON Gemini trả về (Bỏ các thẻ markdown nếu có)
        raw_text = (response.text or "").strip()
        if raw_text.startswith("```json"):
            raw_text = raw_text[7:-3].strip()
        elif raw_text.startswith("```"):
            raw_text = raw_text[3:-3].strip()

        data = json.loads(raw_text)

        # Xử lý trường hợp tiếng ồn
        if "[NOISE]" in data.get("transcript", "").upper():
            return jsonify(ok=True, transcript="(Khong nghe ro)", answer="...")

        return jsonify(
            ok=True, 
            transcript=data.get("transcript", ""),
            answer=data.get("answer", "")
        )

    except Exception as e:
        app.logger.exception("Voice Chat failed")
        return jsonify(ok=False, error=str(e)), 502

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
