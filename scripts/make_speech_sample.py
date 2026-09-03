#!/usr/bin/env python3
"""Gera um vídeo de teste com fala em português e a transcrição correspondente.

Usa o espeak-ng para sintetizar frase por frase, mede a duração real de cada
uma e monta um ``transcript.json`` alinhado ao áudio. Serve para exercitar
seleção de trecho e legenda com texto de verdade (acento, pontuação, ganchos)
sem precisar de gravação real nem de baixar modelo de transcrição.

Uso:
    python scripts/make_speech_sample.py saida.mp4 [--texto arquivo.txt]

Sai um ``saida.mp4`` e um ``saida.transcript.json`` para passar em
``cortes run saida.mp4 --transcript saida.transcript.json``.
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

FALAS_PADRAO = [
    "Bom, gente, hoje eu quero contar uma coisa que aconteceu ontem na live.",
    "Eu tava jogando normal, tranquilo, sem nada demais acontecendo.",
    "Aí do nada apareceu um cara no chat falando que sabia onde eu morava.",
    "Caramba, eu não acredito que isso aconteceu de novo, sério mesmo!",
    "Eu parei tudo, respirei fundo, e resolvi encarar a situação de frente.",
    "E foi aí que eu descobri o segredo que ninguém conta pra quem começa a fazer live.",
    "O segredo é que a maior parte do que você vê no chat não importa nada.",
    "Pior que eu levei três anos pra entender uma coisa tão simples quanto essa.",
    "Então fica a dica: não deixa ninguém estragar o seu dia por causa de uma mensagem.",
    "Melhor coisa que eu fiz foi aprender a desligar o computador e ir dormir.",
]

PAUSA_ENTRE_FALAS = 0.45


def duracao(path: Path) -> float:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)],
        capture_output=True,
        text=True,
        check=True,
    )
    return float(out.stdout.strip())


def sintetiza(falas: list[str], work: Path) -> tuple[Path, list[dict]]:
    """Sintetiza cada frase, concatena e devolve os segmentos com tempo real."""
    partes: list[Path] = []
    segmentos: list[dict] = []
    silencio = work / "silencio.wav"
    subprocess.run(
        [
            "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
            "-f", "lavfi", "-i", f"anullsrc=r=22050:cl=mono:d={PAUSA_ENTRE_FALAS}",
            "-c:a", "pcm_s16le", str(silencio),
        ],
        check=True,
    )

    cursor = 0.0
    for index, fala in enumerate(falas):
        parte = work / f"fala-{index:02d}.wav"
        subprocess.run(
            ["espeak-ng", "-v", "pt-br", "-s", "150", "-w", str(parte), fala],
            check=True,
        )
        span = duracao(parte)
        segmentos.append(
            {
                "start": round(cursor, 3),
                "end": round(cursor + span, 3),
                "text": fala,
                "words": distribui_palavras(fala, cursor, cursor + span),
            }
        )
        partes.append(parte)
        partes.append(silencio)
        cursor += span + PAUSA_ENTRE_FALAS

    lista = work / "lista.txt"
    lista.write_text(
        "\n".join(f"file '{p.resolve()}'" for p in partes) + "\n", encoding="utf-8"
    )
    audio = work / "fala.wav"
    subprocess.run(
        [
            "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
            "-f", "concat", "-safe", "0", "-i", str(lista),
            "-c:a", "pcm_s16le", str(audio),
        ],
        check=True,
    )
    return audio, segmentos


def distribui_palavras(fala: str, start: float, end: float) -> list[dict]:
    """Reparte a frase entre suas palavras proporcionalmente ao tamanho delas.

    Não é alinhamento de verdade — é aproximação boa o bastante para conferir
    quebra de legenda e corte na palavra. O alinhamento real vem do Whisper.
    """
    palavras = fala.split()
    if not palavras:
        return []
    pesos = [len(p) + 1 for p in palavras]
    total = sum(pesos)
    span = end - start
    saida = []
    cursor = start
    for palavra, peso in zip(palavras, pesos):
        largura = span * peso / total
        saida.append(
            {"start": round(cursor, 3), "end": round(cursor + largura, 3), "text": palavra}
        )
        cursor += largura
    return saida


def monta_video(audio: Path, destination: Path, width: int, height: int, duration: float) -> None:
    box_width, box_height = 240, 340
    amplitude = (width - box_width) / 2 - 40
    center = (width - box_width) / 2
    x_expr = f"{center:.0f}+{amplitude:.0f}*sin(2*PI*t/20)"
    filtergraph = (
        f"[0:v][1:v]overlay=x='{x_expr}':y={height // 4}:eval=frame[bg];"
        f"[bg]drawtext=text='%{{eif\\:t\\:d}}s':x=40:y=40:fontsize=48:fontcolor=white[v]"
    )
    subprocess.run(
        [
            "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
            "-f", "lavfi", "-i", f"color=c=0x11161F:s={width}x{height}:r=30:d={duration:.2f}",
            "-f", "lavfi", "-i", f"color=c=0xE8973A:s={box_width}x{box_height}:r=30:d={duration:.2f}",
            "-i", str(audio),
            "-filter_complex", filtergraph,
            "-map", "[v]", "-map", "2:a", "-shortest",
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "23", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-b:a", "96k",
            str(destination),
        ],
        check=True,
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("destination", type=Path)
    parser.add_argument("--texto", type=Path, default=None, help="uma fala por linha")
    parser.add_argument("--width", type=int, default=1280)
    parser.add_argument("--height", type=int, default=720)
    args = parser.parse_args()

    for tool in ("espeak-ng", "ffmpeg", "ffprobe"):
        if shutil.which(tool) is None:
            print(f"{tool} não encontrado no PATH", file=sys.stderr)
            return 2

    falas = FALAS_PADRAO
    if args.texto:
        falas = [linha.strip() for linha in args.texto.read_text(encoding="utf-8").splitlines() if linha.strip()]

    args.destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        work = Path(tmp)
        audio, segmentos = sintetiza(falas, work)
        monta_video(audio, args.destination, args.width, args.height, duracao(audio))

    transcript_path = args.destination.with_suffix(".transcript.json")
    transcript_path.write_text(
        json.dumps(
            {"language": "pt", "backend": "espeak-ng", "segments": segmentos},
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    print(f"vídeo em {args.destination}")
    print(f"transcrição em {transcript_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
