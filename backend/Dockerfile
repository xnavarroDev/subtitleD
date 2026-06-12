# syntax=docker/dockerfile:1.7
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg libgomp1 patchelf \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

ARG INSTALL_WHISPERX=false

COPY requirements.txt requirements-whisperx.txt ./
RUN --mount=type=cache,target=/root/.cache/pip \
    if [ "$INSTALL_WHISPERX" = "true" ]; then \
        pip install -r requirements-whisperx.txt; \
    else \
        pip install -r requirements.txt; \
    fi \
    # Some CTranslate2 wheels request an executable stack, which can fail under
    # Docker Desktop/WSL with "cannot enable executable stack". faster-whisper
    # does not need that flag, so clear it during image build.
    && find /usr/local/lib/python3.12/site-packages -name "libctranslate2*.so*" \
        -exec patchelf --clear-execstack {} \;

COPY . .

EXPOSE 5000

CMD ["flask", "--app", "run", "run", "--host", "0.0.0.0", "--port", "5000"]
