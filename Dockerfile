FROM python:3.14-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 \
    HF_HOME=/app/.cache/huggingface \
    LEGALBOT_DATA_DIR=/data

WORKDIR /app
COPY requirements.txt .
# CPU-only torch keeps the image small; the server only embeds short queries.
RUN pip install --no-cache-dir --extra-index-url https://download.pytorch.org/whl/cpu -r requirements.txt

COPY legalbot ./legalbot
COPY app ./app

# Download the embedding model at build time so the container needs no network access to Hugging Face.
RUN python -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('BAAI/bge-small-en-v1.5')"

RUN useradd --create-home --uid 10001 legalbot && chown -R legalbot /app
USER legalbot

# Mount the database and index (built with legalbot.ingest / legalbot.vectors) at /data.
VOLUME ["/data"]
EXPOSE 8000
CMD ["uvicorn", "app.server:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers"]
