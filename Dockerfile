FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    OLLAMA_HOST=http://host.docker.internal:11434 \
    OLLAMA_MODEL=granite3.2:2b \
    JOB_FINDER_DB=/app/data/job_finder.db

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -r requirements.txt

COPY CV ./CV
COPY Database ./Database
COPY Ingestion ./Ingestion
COPY Interface ./Interface
COPY Search ./Search
COPY run.py pyproject.toml .env.example ./

RUN mkdir -p /app/data \
    && useradd --create-home --shell /usr/sbin/nologin appuser \
    && chown -R appuser:appuser /app

USER appuser

EXPOSE 8000

CMD ["uvicorn", "Interface.main:app", "--host", "0.0.0.0", "--port", "8000"]
