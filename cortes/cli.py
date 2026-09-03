"""Linha de comando do pipeline."""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

from . import ffmpeg
from .config import Config
from .models import RunReport
from .pipeline import run_pipeline


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="cortes",
        description="Gera cortes verticais com legenda a partir de uma gravação longa.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    run = sub.add_parser("run", help="roda o pipeline inteiro num vídeo")
    run.add_argument("video", type=Path)
    run.add_argument("-o", "--out", type=Path, default=None, help="diretório de saída")
    run.add_argument("-n", "--clips", type=int, default=None, help="quantos cortes gerar")
    run.add_argument(
        "--selector",
        choices=["claude", "heuristic"],
        default=None,
        help="quem escolhe os trechos (padrão: claude, com fallback na heurística)",
    )
    run.add_argument(
        "--transcriber",
        choices=["faster-whisper", "fake"],
        default=None,
        help="fake reaproveita transcript.json existente ou sintetiza (só para teste)",
    )
    run.add_argument(
        "--whisper-model",
        default=None,
        help="tiny/base/small/medium/large-v3 (padrão: medium)",
    )
    run.add_argument(
        "--reframe",
        choices=["auto", "face", "motion", "center"],
        default=None,
        help="como o recorte vertical segue o assunto (padrão: auto)",
    )
    run.add_argument(
        "--min-clip", type=float, default=None, help="duração mínima do corte em segundos"
    )
    run.add_argument(
        "--max-clip", type=float, default=None, help="duração máxima do corte em segundos"
    )
    run.add_argument(
        "--transcript",
        type=Path,
        default=None,
        help="usa uma transcrição pronta (JSON) em vez de transcrever",
    )
    run.add_argument("--no-captions", action="store_true", help="não queima legenda")
    run.add_argument("--no-reuse", action="store_true", help="ignora resultados de rodada anterior")
    run.add_argument("-v", "--verbose", action="store_true")

    probe = sub.add_parser("probe", help="mostra metadados do vídeo")
    probe.add_argument("video", type=Path)

    sub.add_parser(
        "fetch-models",
        help="baixa o modelo de detecção de rosto usado no reenquadramento",
    )

    return parser


def _apply_overrides(config: Config, args: argparse.Namespace) -> Config:
    if args.clips is not None:
        config.clips = args.clips
    if args.min_clip is not None:
        config.min_clip_seconds = args.min_clip
    if args.max_clip is not None:
        config.max_clip_seconds = args.max_clip
    if args.selector is not None:
        config.selector.backend = args.selector
    if args.transcriber is not None:
        config.transcribe.backend = args.transcriber
    if args.whisper_model is not None:
        config.transcribe.model = args.whisper_model
    if args.reframe is not None:
        config.reframe.backend = args.reframe
    if args.no_captions:
        config.captions.enabled = False
    return config


def _print_summary(report: RunReport, out_dir: Path) -> None:
    cost = report.cost
    print()
    print(f"{len(report.clips)} cortes em {out_dir / 'clips'}")
    for clip in report.clips:
        h = clip.highlight
        print(
            f"  {clip.index:02d}  {h.start:7.1f}s -> {h.end:7.1f}s  "
            f"({h.duration:4.1f}s)  [{clip.crop_backend}]  {h.title}"
        )

    tempo = cost.get("tempo", {})
    brl = cost.get("custo_brl", {})
    print()
    print(
        f"tempo de processamento: {tempo.get('processamento_s', 0):.1f}s "
        f"para {tempo.get('video_fonte_s', 0):.1f}s de vídeo "
        f"(fator {tempo.get('fator_tempo_real', 0):.2f}x tempo real)"
    )
    print(
        f"custo estimado: R$ {brl.get('total', 0):.4f} na rodada | "
        f"R$ {brl.get('por_minuto_de_video', 0):.4f}/min | "
        f"R$ {brl.get('por_hora_de_video', 0):.2f}/hora de vídeo"
    )
    print(f"relatório completo: {out_dir / 'report.json'}")


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if getattr(args, "verbose", False) else logging.INFO,
        format="%(levelname)s %(name)s: %(message)s",
    )

    if args.command == "probe":
        info = ffmpeg.probe(args.video)
        print(json.dumps(info.__dict__, indent=2, ensure_ascii=False))
        return 0

    if args.command == "fetch-models":
        from .stages.reframe import fetch_yunet, yunet_model_path

        target = yunet_model_path()
        if target.exists():
            print(f"modelo já está em {target}")
            return 0
        try:
            path = fetch_yunet()
        except Exception as exc:
            print(f"falha ao baixar o modelo: {exc}", file=sys.stderr)
            return 2
        print(f"modelo salvo em {path}")
        return 0

    config = _apply_overrides(Config(), args)
    out_dir = args.out or (args.video.parent / f"{args.video.stem}-cortes")

    try:
        report = run_pipeline(
            args.video,
            out_dir,
            config,
            reuse=not args.no_reuse,
            transcript_file=args.transcript,
        )
    except ffmpeg.FFmpegError as exc:
        print(f"erro de ffmpeg: {exc}", file=sys.stderr)
        return 2
    except FileNotFoundError as exc:
        print(str(exc), file=sys.stderr)
        return 2

    if not report.clips:
        print("nenhum trecho passou nos critérios — nada foi renderizado.", file=sys.stderr)
        return 1

    _print_summary(report, out_dir.expanduser().resolve())
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
