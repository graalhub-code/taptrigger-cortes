"""Legenda queimada no estilo dos cortes verticais.

Gera ASS (não SRT) porque o corte precisa de fonte grande, contorno grosso e
posição fixa no terço inferior — coisas que o SRT não carrega. O ffmpeg queima
o arquivo com o filtro ``ass``.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..config import CaptionConfig
from ..models import Word

# Fala nova depois desta pausa começa outro bloco de legenda.
GAP_SECONDS = 0.65


@dataclass
class CaptionChunk:
    start: float
    end: float
    text: str


def chunk_words(words: list[Word], config: CaptionConfig) -> list[CaptionChunk]:
    """Agrupa palavras em blocos curtos o suficiente para caber na tela."""
    chunks: list[CaptionChunk] = []
    current: list[Word] = []

    def flush() -> None:
        if not current:
            return
        text = " ".join(w.text for w in current).strip()
        if text:
            chunks.append(CaptionChunk(start=current[0].start, end=current[-1].end, text=text))
        current.clear()

    for word in words:
        if not word.text.strip():
            continue
        if current:
            gap = word.start - current[-1].end
            candidate = " ".join(w.text for w in current + [word])
            too_long = len(candidate) > config.max_chars
            too_many = len(current) >= config.max_words
            too_slow = (word.end - current[0].start) > config.max_seconds
            if gap > GAP_SECONDS or too_long or too_many or too_slow:
                flush()
        current.append(word)
    flush()
    return chunks


def _timestamp(seconds: float) -> str:
    seconds = max(0.0, seconds)
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = seconds % 60
    return f"{hours:d}:{minutes:02d}:{secs:05.2f}"


def _escape(text: str) -> str:
    return (
        text.replace("\\", "\\\\")
        .replace("{", "(")
        .replace("}", ")")
        .replace("\n", " ")
        .strip()
    )


def build_ass(
    words: list[Word],
    clip_start: float,
    clip_end: float,
    config: CaptionConfig,
    play_res: tuple[int, int],
) -> str:
    """Monta o arquivo ASS de um corte, com tempos relativos ao corte."""
    width, height = play_res
    relevant = [
        Word(start=w.start - clip_start, end=w.end - clip_start, text=w.text)
        for w in words
        if w.end > clip_start and w.start < clip_end
    ]
    for word in relevant:
        word.start = max(0.0, word.start)
        word.end = min(clip_end - clip_start, word.end)

    chunks = chunk_words(relevant, config)

    header = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {width}
PlayResY: {height}
WrapStyle: 2
ScaledBorderAndShadow: yes
YCbCr Matrix: TV.709

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Corte,{config.font},{config.font_size},&H00FFFFFF,&H000000FF,&H00000000,&H64000000,-1,0,0,0,100,100,0,0,1,6,3,2,60,60,{config.margin_bottom},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""

    lines = []
    for chunk in chunks:
        text = _escape(chunk.text)
        if config.uppercase:
            text = text.upper()
        lines.append(
            f"Dialogue: 0,{_timestamp(chunk.start)},{_timestamp(chunk.end)},Corte,,0,0,0,,{text}"
        )

    return header + "\n".join(lines) + "\n"
