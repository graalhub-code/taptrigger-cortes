# Imagem única com o pipeline e o servidor web.
#
# Roda em qualquer lugar que aceite um contêiner: VPS com Docker, Railway,
# Render, Fly. A transcrição roda em CPU aqui — para GPU, ver docs/CUSTOS.md.
FROM python:3.11-slim

# ffmpeg faz todo o corte, recorte e render; libgl/libglib são do OpenCV.
RUN apt-get update && apt-get install -y --no-install-recommends \
        ffmpeg \
        libgl1 \
        libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Dependências primeiro: mudar código não invalida esta camada.
COPY pyproject.toml README.md ./
COPY cortes ./cortes
RUN pip install --no-cache-dir -e '.[all,web]'

# Detector de rosto (~230 KB) embutido, para o primeiro job não esperar download.
RUN cortes fetch-models || echo "modelo de rosto não baixou; segue com movimento/centro"

ENV CORTES_DATA_DIR=/data/jobs \
    CORTES_MAX_UPLOAD_MB=2048 \
    CORTES_WHISPER_MODEL=small \
    CORTES_WHISPER_DEVICE=cpu \
    CORTES_WHISPER_COMPUTE=int8 \
    PORT=8000

# Os vídeos e cortes vivem aqui. Monte um volume para não perder no redeploy.
VOLUME ["/data"]
EXPOSE 8000

# Um worker só: o processamento é pesado e serializado na fila interna.
CMD ["sh", "-c", "uvicorn cortes.web.app:servidor --factory --host 0.0.0.0 --port ${PORT:-8000} --workers 1 --timeout-keep-alive 120"]
