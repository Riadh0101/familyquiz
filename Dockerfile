FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    DATABASE_PATH=/app/data/quiz.db \
    PORT=5000

WORKDIR /app

RUN useradd --create-home --uid 1000 quiz \
    && mkdir -p /app/data \
    && chown quiz:quiz /app/data

COPY requirements.txt .
RUN pip install -r requirements.txt

COPY --chown=quiz:quiz app.py ./
COPY --chown=quiz:quiz templates ./templates
COPY --chown=quiz:quiz static ./static

USER quiz
VOLUME ["/app/data"]
EXPOSE 5000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import os, urllib.request; urllib.request.urlopen('http://127.0.0.1:%s/healthz' % os.environ.get('PORT', '5000'), timeout=4)"

# --preload runs create_app() (DB init, admin setup) once before forking workers.
CMD ["sh", "-c", "exec gunicorn --preload --workers 2 --threads 4 --bind 0.0.0.0:${PORT} --access-logfile - 'app:create_app()'"]
