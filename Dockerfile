FROM python:3.11-slim

RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg curl unzip && rm -rf /var/lib/apt/lists/*

RUN curl -fsSL https://deno.land/install.sh | sh

ENV DENO_INSTALL=/root/.deno
ENV PATH="/root/.deno/bin:${PATH}"

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt && python -m pip install --no-cache-dir --pre --upgrade "yt-dlp[default]"

COPY app.py .

CMD ["sh", "-c", "gunicorn --bind 0.0.0.0:${PORT:-10000} --workers 1 --threads 2 --timeout 120 app:app"]
