"""Orquestração do pipeline: vídeo longo entra, cortes verticais saem.

Cada estágio grava seu resultado no diretório de trabalho. Rodar de novo em
cima do mesmo diretório reaproveita transcrição e seleção, que são as etapas
caras — dá para iterar em legenda e enquadramento sem repagar a transcrição.
"""

from __future__ import annotations

import json
import logging
import re
import unicodedata
from pathlib import Path

from . import ffmpeg
from .config import Config
from .costs import CostTracker
from .models import Clip, RunReport, Transcript, dump_json
from .stages import highlights as highlights_stage
from .stages import reframe as reframe_stage
from .stages import render as render_stage
from .stages import subtitles as subtitles_stage
from .stages.transcribe import build_transcriber

logger = logging.getLogger(__name__)


def slugify(text: str, limit: int = 40) -> str:
    normalized = unicodedata.normalize("NFKD", text)
    ascii_text = normalized.encode("ascii", "ignore").decode("ascii").lower()
    slug = re.sub(r"[^a-z0-9]+", "-", ascii_text).strip("-")
    return (slug[:limit].rstrip("-")) or "corte"


def run_pipeline(
    source: Path,
    out_dir: Path,
    config: Config,
    *,
    reuse: bool = True,
    transcript_file: Path | None = None,
) -> RunReport:
    source = source.expanduser().resolve()
    if not source.exists():
        raise FileNotFoundError(f"vídeo não encontrado: {source}")

    out_dir = out_dir.expanduser().resolve()
    work_dir = out_dir / "work"
    clips_dir = out_dir / "clips"
    work_dir.mkdir(parents=True, exist_ok=True)
    clips_dir.mkdir(parents=True, exist_ok=True)

    tracker = CostTracker()
    media = ffmpeg.probe(source)
    logger.info(
        "fonte: %.1fs, %dx%d, %.2f fps, áudio=%s",
        media.duration,
        media.width,
        media.height,
        media.fps,
        media.has_audio,
    )
    dump_json(media, work_dir / "media.json")

    # --- áudio -----------------------------------------------------------
    wav_path = work_dir / "audio.wav"
    if not (reuse and wav_path.exists()):
        with tracker.stage("audio", "cpu"):
            ffmpeg.extract_audio(source, wav_path)

    # --- transcrição -----------------------------------------------------
    transcript_path = work_dir / "transcript.json"
    if transcript_file is not None:
        # Transcrição pronta vinda de fora: não roda modelo nenhum.
        transcript = Transcript.from_dict(json.loads(transcript_file.read_text(encoding="utf-8")))
        transcript.backend = f"externo:{transcript_file.name}"
        dump_json(transcript, transcript_path)
        logger.info("transcrição externa carregada de %s", transcript_file)
    elif reuse and transcript_path.exists():
        transcript = Transcript.from_dict(json.loads(transcript_path.read_text(encoding="utf-8")))
        logger.info("transcrição reaproveitada de %s", transcript_path)
    else:
        transcriber = build_transcriber(config.transcribe, duration=media.duration)
        with tracker.stage("transcricao", _transcription_hardware(config)):
            transcript = transcriber.transcribe(wav_path)
        dump_json(transcript, transcript_path)
    logger.info("transcrição: %d segmentos, %d palavras", len(transcript.segments), len(transcript.words))

    # --- seleção de trechos ---------------------------------------------
    highlights_path = work_dir / "highlights.json"
    with tracker.stage("selecao", "rede"):
        chosen = highlights_stage.select_highlights(
            config, transcript, media.duration, tracker.llm_usage
        )
    dump_json(chosen, highlights_path)
    logger.info("trechos escolhidos: %d", len(chosen))

    # --- enquadramento, legenda e render --------------------------------
    clips: list[Clip] = []
    for index, highlight in enumerate(chosen, start=1):
        stem = f"{index:02d}-{slugify(highlight.title)}"

        with tracker.stage(f"reframe:{index}", "cpu"):
            plan = reframe_stage.plan_for_clip(
                media, highlight.start, highlight.end, config.reframe, config.render
            )
        dump_json(plan, work_dir / f"{stem}.crop.json")

        ass_file = None
        caption_count = 0
        if config.captions.enabled and transcript.words:
            words = transcript.words_between(highlight.start, highlight.end)
            ass_text = subtitles_stage.build_ass(
                transcript.words,
                highlight.start,
                highlight.end,
                config.captions,
                (config.render.width, config.render.height),
            )
            ass_file = work_dir / f"{stem}.ass"
            ass_file.write_text(ass_text, encoding="utf-8")
            caption_count = len(subtitles_stage.chunk_words(words, config.captions))

        destination = clips_dir / f"{stem}.mp4"
        with tracker.stage(f"render:{index}", "cpu"):
            render_stage.render_clip(
                source, destination, highlight, plan, config, work_dir, ass_file=ass_file
            )

        clips.append(
            Clip(
                index=index,
                highlight=highlight,
                path=str(destination),
                crop_backend=plan.backend,
                caption_count=caption_count,
            )
        )
        logger.info(
            "corte %02d %.1fs-%.1fs (%.1fs) -> %s",
            index,
            highlight.start,
            highlight.end,
            highlight.duration,
            destination.name,
        )

    report = RunReport(
        source=str(source),
        source_duration=media.duration,
        clips=clips,
        timings=tracker.timings,
        llm_input_tokens=int(tracker.llm_usage.get("input_tokens", 0)),
        llm_output_tokens=int(tracker.llm_usage.get("output_tokens", 0)),
        llm_model=str(tracker.llm_usage.get("model", "")),
        cost=tracker.summarize(config.cost, media.duration, len(clips)),
    )
    dump_json(report, out_dir / "report.json")
    dump_json(config.describe(), out_dir / "config-usado.json")
    return report


def _transcription_hardware(config: Config) -> str:
    """Rotula o estágio como GPU só quando há CUDA de verdade disponível."""
    if config.transcribe.backend.lower() not in ("faster-whisper", "whisper"):
        return "cpu"
    if config.transcribe.device.lower() == "cpu":
        return "cpu"
    try:
        import ctranslate2

        if ctranslate2.get_cuda_device_count() > 0:
            return "gpu"
    except Exception:
        pass
    return "cpu"
