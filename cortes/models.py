"""Estruturas de dados que atravessam o pipeline.

Tudo aqui é serializável em JSON: cada estágio grava seu resultado no diretório
de trabalho, então uma rodada interrompida pode ser retomada sem refazer a
transcrição (que é a etapa cara).
"""

from __future__ import annotations

import dataclasses
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


def _to_jsonable(value: Any) -> Any:
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return {k: _to_jsonable(v) for k, v in dataclasses.asdict(value).items()}
    if isinstance(value, dict):
        return {k: _to_jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_to_jsonable(v) for v in value]
    if isinstance(value, Path):
        return str(value)
    return value


def dump_json(obj: Any, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(_to_jsonable(obj), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


@dataclass
class MediaInfo:
    path: str
    duration: float
    width: int
    height: int
    fps: float
    has_audio: bool

    @property
    def is_landscape(self) -> bool:
        return self.width >= self.height


@dataclass
class Word:
    start: float
    end: float
    text: str


@dataclass
class Segment:
    """Trecho contíguo de fala, do jeito que o Whisper devolve."""

    start: float
    end: float
    text: str
    words: list[Word] = field(default_factory=list)

    @property
    def duration(self) -> float:
        return max(0.0, self.end - self.start)


@dataclass
class Transcript:
    language: str
    segments: list[Segment]
    backend: str = "unknown"

    @property
    def words(self) -> list[Word]:
        out: list[Word] = []
        for seg in self.segments:
            out.extend(seg.words)
        return out

    @property
    def text(self) -> str:
        return " ".join(seg.text.strip() for seg in self.segments if seg.text.strip())

    def words_between(self, start: float, end: float) -> list[Word]:
        """Palavras cujo centro cai dentro da janela."""
        return [w for w in self.words if start <= (w.start + w.end) / 2 <= end]

    def segments_between(self, start: float, end: float) -> list[Segment]:
        return [s for s in self.segments if s.end > start and s.start < end]

    @classmethod
    def from_dict(cls, data: dict) -> "Transcript":
        segments = [
            Segment(
                start=float(s["start"]),
                end=float(s["end"]),
                text=s["text"],
                words=[
                    Word(start=float(w["start"]), end=float(w["end"]), text=w["text"])
                    for w in s.get("words", [])
                ],
            )
            for s in data.get("segments", [])
        ]
        return cls(
            language=data.get("language", "pt"),
            segments=segments,
            backend=data.get("backend", "unknown"),
        )


@dataclass
class Highlight:
    """Um trecho candidato a virar corte, antes de ser renderizado."""

    start: float
    end: float
    title: str
    score: float
    reason: str = ""
    source: str = "unknown"

    @property
    def duration(self) -> float:
        return max(0.0, self.end - self.start)


@dataclass
class CropKeyframe:
    """Posição do recorte vertical num instante (relativo ao início do corte)."""

    t: float
    x: int
    y: int


@dataclass
class CropPlan:
    width: int
    height: int
    keyframes: list[CropKeyframe]
    backend: str = "center"
    faces_found: int = 0

    @property
    def is_static(self) -> bool:
        return len({k.x for k in self.keyframes}) <= 1


@dataclass
class Clip:
    index: int
    highlight: Highlight
    path: str
    crop_backend: str
    caption_count: int


@dataclass
class StageTiming:
    name: str
    seconds: float
    hardware: str = "cpu"


@dataclass
class RunReport:
    source: str
    source_duration: float
    clips: list[Clip]
    timings: list[StageTiming]
    llm_input_tokens: int = 0
    llm_output_tokens: int = 0
    llm_model: str = ""
    cost: dict[str, Any] = field(default_factory=dict)

    @property
    def total_seconds(self) -> float:
        return sum(t.seconds for t in self.timings)
