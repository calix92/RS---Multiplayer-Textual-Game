# --- Estágio de Build ---
FROM python:3.11-slim AS builder

WORKDIR /app

# Instalar dependências de compilação
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Configurar virtualenv para isolar dependências
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip setuptools wheel
RUN pip install --no-cache-dir -r requirements.txt

# Compilação dos Protos (precisamos do código proto agora)
COPY proto/ ./proto/
RUN python -m grpc_tools.protoc -I. --python_out=. --grpc_python_out=. proto/game.proto

# --- Estágio Final ---
FROM python:3.11-slim

WORKDIR /app

# Variáveis de ambiente para Python em Docker
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/opt/venv/bin:$PATH"

# Copiar o virtualenv e o código
COPY --from=builder /opt/venv /opt/venv
COPY . .
COPY --from=builder /app/proto/*_pb2*.py ./proto/

# Remover ficheiros desnecessários que possam ter sido copiados
RUN rm -rf proto/*.proto requirements.txt Dockerfile compose.yaml notasParaCorrer.txt .dockerignore

# O entrypoint mantém-se
ENTRYPOINT ["python", "main.py"]
