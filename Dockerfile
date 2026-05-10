# Usamos a 3.11-slim, que é a "golden version" para gRPC e Redes
FROM python:3.11-slim

# Diretório de trabalho
WORKDIR /app

# Instalar dependências do sistema num único passo para poupar espaço
RUN apt-get update && apt-get install -y \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Copiar os requisitos
COPY requirements.txt .

# Atualizar o pip e instalar TUDO o que é preciso para compilar protos
RUN pip install --no-cache-dir --upgrade pip setuptools wheel grpcio-tools
RUN pip install --no-cache-dir -r requirements.txt

# Copiar o resto do código
COPY . .

# Limpar versões antigas dos protos e compilar as novas
RUN rm -f proto/game_pb2.py proto/game_pb2_grpc.py
RUN python -m grpc_tools.protoc -I. --python_out=. --grpc_python_out=. proto/game.proto

# Comando de entrada
ENTRYPOINT ["python", "main.py"]