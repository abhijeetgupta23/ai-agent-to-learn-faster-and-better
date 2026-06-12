# Minimal, working image for the adaptive-learning-agent server.
# Portable: no hosting-specific assumptions. Railway/Fly/any container host
# can run this as-is (Railway provides $PORT; we default to 8000 locally).
FROM python:3.12-slim

WORKDIR /app

# Install dependencies first so the layer caches across code changes.
COPY pyproject.toml requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# App code.
COPY src ./src
COPY domains ./domains
COPY docs/visual ./docs/visual
COPY run_server.py ./
# /evals endpoint serves the recorded eval-harness results.
COPY evals/results.json ./evals/results.json

# Persisted learner/graph store lives here; mount a volume to keep it.
ENV ADAPTIVE_LEARNING_STORE_DIR=/data/store
EXPOSE 8000

# Honour $PORT when the platform sets one (Railway, Heroku); else 8000.
CMD ["sh", "-c", "uvicorn src.server.app:app --host 0.0.0.0 --port ${PORT:-8000}"]
