# KPSTerra on a Hugging Face Docker Space: FastAPI backend + static frontend on one port (7860).
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 \
    LANDCOVER_ROOT=/app/data/landcover MODIS_LC_YEAR=2025 \
    ALLOWED_ORIGINS=*

# Hugging Face runs containers as user 1000
RUN useradd -m -u 1000 user
WORKDIR /app

COPY --chown=user backend/requirements-server.txt backend/requirements-server.txt
RUN pip install --no-cache-dir -r backend/requirements-server.txt

COPY --chown=user backend backend
COPY --chown=user frontend frontend
COPY --chown=user data data

USER user
WORKDIR /app/backend
EXPOSE 7860
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "7860"]
