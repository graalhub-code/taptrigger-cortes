"""Camada fina sobre ffmpeg/ffprobe.

Todo o pipeline chama ffmpeg por aqui para que haja um único lugar onde
verificar disponibilidade, montar comando e capturar erro legível.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

from .models import MediaInfo


class FFmpegError(RuntimeError):
    pass


def ensure_available() -> None:
    for tool in ("ffmpeg", "ffprobe"):
        if shutil.which(tool) is None:
            raise FFmpegError(
                f"{tool} não encontrado no PATH. Instale com `apt-get install ffmpeg`."
            )


def run(args: list[str], *, timeout: float | None = None) -> str:
    """Executa um comando e devolve o stderr (onde o ffmpeg escreve o log)."""
    proc = subprocess.run(
        args,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        timeout=timeout,
    )
    if proc.returncode != 0:
        tail = "\n".join((proc.stderr or "").strip().splitlines()[-15:])
        raise FFmpegError(f"comando falhou ({proc.returncode}): {' '.join(args[:6])}...\n{tail}")
    return proc.stderr


def probe(path: Path) -> MediaInfo:
    ensure_available()
    proc = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-print_format",
            "json",
            "-show_format",
            "-show_streams",
            str(path),
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    if proc.returncode != 0:
        raise FFmpegError(f"ffprobe falhou em {path}: {proc.stderr.strip()}")

    data = json.loads(proc.stdout)
    streams = data.get("streams", [])
    video = next((s for s in streams if s.get("codec_type") == "video"), None)
    if video is None:
        raise FFmpegError(f"{path} não tem stream de vídeo")

    has_audio = any(s.get("codec_type") == "audio" for s in streams)
    duration = float(data.get("format", {}).get("duration") or video.get("duration") or 0.0)

    fps = 30.0
    raw_fps = video.get("avg_frame_rate") or video.get("r_frame_rate") or "30/1"
    try:
        num, _, den = raw_fps.partition("/")
        if den and float(den) != 0:
            fps = float(num) / float(den)
    except (ValueError, ZeroDivisionError):
        pass

    return MediaInfo(
        path=str(path),
        duration=duration,
        width=int(video.get("width") or 0),
        height=int(video.get("height") or 0),
        fps=fps or 30.0,
        has_audio=has_audio,
    )


def extract_audio(source: Path, destination: Path, *, sample_rate: int = 16000) -> Path:
    """Extrai áudio mono 16 kHz — o formato que o Whisper consome direto."""
    ensure_available()
    destination.parent.mkdir(parents=True, exist_ok=True)
    run(
        [
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-i",
            str(source),
            "-vn",
            "-ac",
            "1",
            "-ar",
            str(sample_rate),
            "-c:a",
            "pcm_s16le",
            str(destination),
        ]
    )
    return destination


def extract_poster(source: Path, destination: Path, at_seconds: float = 1.0) -> Path:
    """Tira um quadro do corte para servir de miniatura na página de revisão."""
    ensure_available()
    destination.parent.mkdir(parents=True, exist_ok=True)
    run(
        [
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-ss",
            f"{max(0.0, at_seconds):.2f}",
            "-i",
            str(source),
            "-frames:v",
            "1",
            "-q:v",
            "4",
            str(destination),
        ]
    )
    return destination


def escape_filter_path(path: Path | str) -> str:
    """Escapa um caminho para uso dentro de um filtergraph do ffmpeg."""
    text = str(path)
    for char in ("\\", ":", "'", "[", "]", ",", ";"):
        text = text.replace(char, "\\" + char)
    return text
