#!/usr/bin/env python3
"""Gera um vídeo horizontal sintético para testar o pipeline sem material real.

Um retângulo atravessa o quadro de um lado para o outro: é o "assunto" que o
reenquadramento tem de seguir. Serve para validar recorte, pan, legenda e
render — não serve para avaliar qualidade de seleção de trecho, que só faz
sentido com gravação de verdade.

Uso: python scripts/make_sample_video.py saida.mp4 [--duration 60]
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path


def build_command(destination: Path, duration: float, width: int, height: int) -> list[str]:
    box_width, box_height = 240, 340
    amplitude = (width - box_width) / 2 - 40
    center = (width - box_width) / 2
    # Vai e volta suavemente, com período de 20s. `eval=frame` é obrigatório:
    # sem isso o overlay calcula a posição uma vez só e o objeto fica parado.
    x_expr = f"{center:.0f}+{amplitude:.0f}*sin(2*PI*t/20)"
    # O cronômetro no canto é de propósito: é um HUD que pisca sozinho e serve
    # para conferir que o rastreio por movimento não persegue overlay estático.
    filtergraph = (
        f"[0:v][1:v]overlay=x='{x_expr}':y={height // 4}:eval=frame[bg];"
        f"[bg]drawtext=text='%{{eif\\:t\\:d}}s':x=40:y=40:fontsize=48:fontcolor=white[v]"
    )
    return [
        "ffmpeg",
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        "-f",
        "lavfi",
        "-i",
        f"color=c=0x11161F:s={width}x{height}:r=30:d={duration}",
        "-f",
        "lavfi",
        "-i",
        f"color=c=0xE8973A:s={box_width}x{box_height}:r=30:d={duration}",
        "-f",
        "lavfi",
        "-i",
        f"sine=frequency=220:duration={duration}",
        "-filter_complex",
        filtergraph,
        "-map",
        "[v]",
        "-map",
        "2:a",
        "-c:v",
        "libx264",
        "-preset",
        "veryfast",
        "-crf",
        "23",
        "-pix_fmt",
        "yuv420p",
        "-c:a",
        "aac",
        "-b:a",
        "96k",
        str(destination),
    ]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("destination", type=Path)
    parser.add_argument("--duration", type=float, default=60.0)
    parser.add_argument("--width", type=int, default=1280)
    parser.add_argument("--height", type=int, default=720)
    args = parser.parse_args()

    args.destination.parent.mkdir(parents=True, exist_ok=True)
    proc = subprocess.run(build_command(args.destination, args.duration, args.width, args.height))
    if proc.returncode != 0:
        return proc.returncode
    print(f"vídeo de teste em {args.destination}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
