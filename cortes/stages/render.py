"""Renderização final de cada corte com ffmpeg.

Um único passe por corte: recorta (acompanhando o caminho de câmera), escala
para 1080x1920, queima a legenda e reencoda. Roda em CPU.
"""

from __future__ import annotations

from pathlib import Path

from ..config import Config
from ..ffmpeg import escape_filter_path, run
from ..models import CropPlan, Highlight
from .reframe import sendcmd_script


def build_filtergraph(
    plan: CropPlan, config: Config, *, cmd_file: Path | None, ass_file: Path | None
) -> str:
    parts = ["setpts=PTS-STARTPTS"]
    first = plan.keyframes[0] if plan.keyframes else None
    x = first.x if first else 0
    y = first.y if first else 0

    if cmd_file is not None:
        parts.append(f"sendcmd=f='{escape_filter_path(cmd_file)}'")
    parts.append(f"crop={plan.width}:{plan.height}:{x}:{y}")
    parts.append(f"scale={config.render.width}:{config.render.height}:flags=lanczos")
    parts.append("setsar=1")
    if ass_file is not None:
        parts.append(f"ass='{escape_filter_path(ass_file)}'")
    return ",".join(parts)


def render_clip(
    source: Path,
    destination: Path,
    highlight: Highlight,
    plan: CropPlan,
    config: Config,
    work_dir: Path,
    *,
    ass_file: Path | None = None,
) -> Path:
    destination.parent.mkdir(parents=True, exist_ok=True)

    cmd_file: Path | None = None
    if not plan.is_static and len(plan.keyframes) > 1:
        cmd_file = work_dir / f"{destination.stem}.cmds"
        cmd_file.write_text(sendcmd_script(plan), encoding="utf-8")

    filtergraph = build_filtergraph(plan, config, cmd_file=cmd_file, ass_file=ass_file)

    args = [
        "ffmpeg",
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        "-ss",
        f"{highlight.start:.3f}",
        "-t",
        f"{highlight.duration:.3f}",
        "-i",
        str(source),
        "-filter_complex",
        f"[0:v]{filtergraph}[v]",
        "-map",
        "[v]",
        "-map",
        "0:a?",
        "-af",
        "asetpts=PTS-STARTPTS",
        "-r",
        str(config.render.fps),
        "-c:v",
        "libx264",
        "-preset",
        config.render.preset,
        "-crf",
        str(config.render.crf),
        "-pix_fmt",
        "yuv420p",
        "-c:a",
        "aac",
        "-b:a",
        config.render.audio_bitrate,
        "-movflags",
        "+faststart",
        str(destination),
    ]
    run(args)
    return destination
