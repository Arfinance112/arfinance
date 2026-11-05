# Backend de ARFinance Gestión: API FastAPI + worker de la cola + OCR (Tesseract en español).
# Lo construye Fly.io en sus servidores (`fly deploy`); no hace falta Docker en la PC.
FROM python:3.12-slim

# Tesseract con español para los PDF escaneados
RUN apt-get update \
    && apt-get install -y --no-install-recommends tesseract-ocr tesseract-ocr-spa \
    && rm -rf /var/lib/apt/lists/*

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
WORKDIR /app

COPY backend/requirements.txt backend/requirements.txt
RUN pip install -r backend/requirements.txt

# Código y maestros (db/seeds) y migraciones (db/migraciones): misma estructura que en la PC
COPY backend/app backend/app
COPY db db

# Usuario sin privilegios
RUN useradd --create-home app && chown -R app /app
USER app
WORKDIR /app/backend

EXPOSE 8080
# --proxy-headers: Fly termina HTTPS adelante; la API ve la IP real del cliente
CMD ["python", "-m", "uvicorn", "app.api.main:app", "--host", "0.0.0.0", "--port", "8080", "--proxy-headers", "--forwarded-allow-ips", "*"]
