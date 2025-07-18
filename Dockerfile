# ---------- STAGE 1: builder ---------------------------------------
FROM python:3.11-slim AS builder

# Evitiamo interazione
ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# Copiamo requirements e installiamo in una venv temporanea
COPY requirements.txt .
RUN python -m venv /opt/venv \
 && /opt/venv/bin/pip install --upgrade pip \
 && /opt/venv/bin/pip install --no-cache-dir -r requirements.txt

# ---------- STAGE 2: runtime ---------------------------------------
FROM python:3.11-slim

# Copia la venv dal builder
COPY --from=builder /opt/venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

WORKDIR /app

# Copia sorgenti
COPY . .

# Porta default
EXPOSE 8000

# Comando di avvio
CMD ["python", "main.py"]
