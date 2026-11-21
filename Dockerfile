# Production image for the Django dashboard (gunicorn). docker-compose.yml overrides the
# command with runserver for local development.
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# Dependencies first: this layer is rebuilt only when requirements.txt changes,
# not on every source edit (Docker layer caching).
COPY requirements.txt .
RUN pip install -r requirements.txt

# Sentiment word list (Loughran-McDonald), checksum-verified, kept out of git. Its own layer,
# so it is downloaded once and reused until the fetch script changes.
COPY scripts/fetch_sentiment_data.py /app/scripts/
RUN python /app/scripts/fetch_sentiment_data.py lexicon --lexicon-out /app/data/sentiment/lm_words.json
ENV SENTIMENT_LEXICON_PATH=/app/data/sentiment/lm_words.json

# Optional FinBERT build (measured: 2.91 GB image vs 569 MB default):  docker build --build-arg SENTIMENT_MODEL=finbert ...
# Installs CPU-only PyTorch and bakes the pinned model revision into the image, so the running
# container never downloads anything (HF_HUB_OFFLINE=1).
ARG SENTIMENT_MODEL=lexicon
ENV SENTIMENT_MODEL=${SENTIMENT_MODEL} \
    HF_HOME=/app/hf-cache
COPY requirements-finbert.txt .
COPY myproject/market/sentiment/finbert.py /tmp/finbert_pin.py
RUN if [ "$SENTIMENT_MODEL" = "finbert" ]; then \
        pip install -r requirements-finbert.txt && \
        python -c "import re, pathlib; from huggingface_hub import snapshot_download; \
src = pathlib.Path('/tmp/finbert_pin.py').read_text(); \
rev = re.search(r'REVISION = \"([0-9a-f]{40})\"', src).group(1); \
snapshot_download('ProsusAI/finbert', revision=rev, allow_patterns=['*.json', '*.txt', 'model.safetensors'])"; \
    fi && rm /tmp/finbert_pin.py
ENV HF_HUB_OFFLINE=1

COPY myproject/ ./myproject/
WORKDIR /app/myproject

# Bake hashed, compressed static files into the image. SECRET_KEY is required by
# settings when DEBUG=False; this throwaway value exists only during the build step.
RUN SECRET_KEY=collectstatic-only python manage.py collectstatic --noinput

# Don't run as root inside the container.
RUN useradd --create-home --uid 10001 app
USER app

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=3s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request,sys; sys.exit(urllib.request.urlopen('http://127.0.0.1:8000/healthz', timeout=2).status != 200)"

CMD ["gunicorn", "myproject.wsgi:application", "--bind", "0.0.0.0:8000", "--workers", "2", "--timeout", "120", "--access-logfile", "-", "--error-logfile", "-"]
