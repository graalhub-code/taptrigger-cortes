"""Transcrição com timestamp por palavra.

É a etapa que justifica GPU: em CPU o modelo ``medium`` roda perto de tempo
real, na GPU alugada roda uma ordem de grandeza mais rápido. O resto do
pipeline só depende do formato de saída (``Transcript``), então trocar o
backend não mexe em mais nada.
"""

from __future__ import annotations

import json
from pathlib import Path

from ..config import TranscribeConfig
from ..models import Segment, Transcript, Word


class Transcriber:
    name = "base"

    def transcribe(self, wav_path: Path) -> Transcript:  # pragma: no cover - interface
        raise NotImplementedError


class FasterWhisperTranscriber(Transcriber):
    name = "faster-whisper"

    def __init__(self, config: TranscribeConfig):
        self.config = config

    def transcribe(self, wav_path: Path) -> Transcript:
        try:
            from faster_whisper import WhisperModel
        except ImportError as exc:  # pragma: no cover - depende do ambiente
            raise RuntimeError(
                "faster-whisper não instalado. `pip install 'cortes[transcribe]'` "
                "ou rode com CORTES_TRANSCRIBER=fake."
            ) from exc

        try:
            model = WhisperModel(
                self.config.model,
                device=self.config.device,
                compute_type=self.config.compute_type,
            )
        except Exception as exc:
            # Falha típica na primeira execução: a máquina não alcança o
            # repositório de onde o modelo é baixado.
            raise RuntimeError(
                f"não consegui carregar o modelo de transcrição "
                f"'{self.config.model}' ({type(exc).__name__}: {exc}). "
                "Na primeira execução ele é baixado da internet — confira se a "
                "máquina tem acesso de saída, ou use um modelo menor com "
                "CORTES_WHISPER_MODEL=tiny."
            ) from exc
        raw_segments, info = model.transcribe(
            str(wav_path),
            language=self.config.language or None,
            beam_size=self.config.beam_size,
            word_timestamps=True,
            vad_filter=True,
        )

        segments: list[Segment] = []
        for seg in raw_segments:
            words = [
                Word(start=float(w.start), end=float(w.end), text=w.word.strip())
                for w in (seg.words or [])
                if w.word and w.word.strip()
            ]
            text = seg.text.strip()
            if not text:
                continue
            segments.append(
                Segment(start=float(seg.start), end=float(seg.end), text=text, words=words)
            )

        return Transcript(
            language=getattr(info, "language", self.config.language) or "pt",
            segments=segments,
            backend=f"faster-whisper:{self.config.model}",
        )


class SidecarTranscriber(Transcriber):
    """Lê um transcript pronto do disco, ou sintetiza um se não houver.

    Serve para dois casos: rodar o resto do pipeline sem pagar transcrição
    (quando já existe transcript de uma rodada anterior ou de outra ferramenta)
    e para os testes automatizados, que não podem depender de modelo baixado.
    """

    name = "fake"

    def __init__(self, config: TranscribeConfig, sidecar: Path | None = None, duration: float = 0.0):
        self.config = config
        self.sidecar = sidecar
        self.duration = duration

    def transcribe(self, wav_path: Path) -> Transcript:
        candidates = [self.sidecar] if self.sidecar else []
        candidates += [
            wav_path.with_suffix(".transcript.json"),
            wav_path.parent / "transcript.json",
        ]
        for candidate in candidates:
            if candidate and candidate.exists():
                data = json.loads(candidate.read_text(encoding="utf-8"))
                transcript = Transcript.from_dict(data)
                transcript.backend = f"sidecar:{candidate.name}"
                return transcript
        return self._synthetic()

    def _synthetic(self) -> Transcript:
        """Fala sintética de 4 s por segmento, só para exercitar o pipeline."""
        duration = self.duration or 60.0
        segments: list[Segment] = []
        step = 4.0
        idx = 0
        t = 0.0
        while t < duration:
            end = min(t + step, duration)
            if end - t < 0.5:
                break
            tokens = [f"palavra{idx * 4 + i}" for i in range(4)]
            width = (end - t) / len(tokens)
            words = [
                Word(start=t + i * width, end=t + (i + 1) * width, text=tok)
                for i, tok in enumerate(tokens)
            ]
            segments.append(Segment(start=t, end=end, text=" ".join(tokens), words=words))
            idx += 1
            t = end
        return Transcript(language=self.config.language or "pt", segments=segments, backend="synthetic")


def build_transcriber(
    config: TranscribeConfig, *, duration: float = 0.0, sidecar: Path | None = None
) -> Transcriber:
    backend = (config.backend or "").strip().lower()
    if backend in ("fake", "sidecar", "none"):
        return SidecarTranscriber(config, sidecar=sidecar, duration=duration)
    return FasterWhisperTranscriber(config)
