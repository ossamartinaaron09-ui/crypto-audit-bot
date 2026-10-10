FROM python:3.10-slim

# Evitar prompts interactivos y buffers en logs
ENV DEBIAN_FRONTEND=noninteractive
ENV PYTHONUNBUFFERED=1

WORKDIR /app

# 1. Instalar dependencias del sistema necesarias para git, solc y compiladores
RUN apt-get update && apt-get install -y --no-install-recommends \
    git \
    wget \
    curl \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# 2. Copiar e instalar dependencias de Python
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 3. Configurar Solidity con solc-select versión 0.8.24 de forma global
RUN solc-select install 0.8.24 && solc-select use 0.8.24

# 4. Copiar los scripts de la aplicación
COPY . .

# 5. Exponer puerto para FastAPI
EXPOSE 8000

# 6. Punto de entrada con el supervisor de procesos
CMD ["python", "supervisor.py"]
