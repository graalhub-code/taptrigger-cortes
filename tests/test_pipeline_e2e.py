"""Smoke test de ponta a ponta: gera um vídeo, roda o pipeline, confere a saída.

Não avalia qualidade de seleção (a transcrição aqui é sintética) — confere que
recorte, escala, legenda queimada e relatório de custo saem coerentes.
"""

import shutil
import subprocess
from pathlib import Path

import pytest

from cortes.config import Config
from cortes.pipeline import run_pipeline, slugify

pytestmark = pytest.mark.skipif(
    shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None,
    reason="ffmpeg/ffprobe não estão no PATH",
)


# A fixture sample_video vive em conftest.py, compartilhada com os testes web.


def offline_config() -> Config:
    config = Config()
    config.transcribe.backend = "fake"
    config.selector.backend = "heuristic"
    config.reframe.backend = "motion"
    config.clips = 2
    config.min_clip_seconds = 10.0
    config.max_clip_seconds = 20.0
    return config


def probe(path: Path, entries: str) -> str:
    out = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-select_streams",
            "v:0",
            "-show_entries",
            f"stream={entries}",
            "-of",
            "csv=p=0",
            str(path),
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    return out.stdout.strip()


@pytest.fixture(scope="module")
def run_result(sample_video, tmp_path_factory):
    out_dir = tmp_path_factory.mktemp("saida")
    report = run_pipeline(sample_video, out_dir, offline_config(), reuse=False)
    return report, out_dir


def test_gera_os_cortes_pedidos(run_result):
    report, _ = run_result
    assert 1 <= len(report.clips) <= 2
    for clip in report.clips:
        assert Path(clip.path).exists()
        assert Path(clip.path).stat().st_size > 10_000


def test_cortes_saem_em_9_16(run_result):
    report, _ = run_result
    for clip in report.clips:
        assert probe(Path(clip.path), "width,height") == "1080,1920"


def test_duracao_do_corte_bate_com_o_trecho_escolhido(run_result):
    report, _ = run_result
    for clip in report.clips:
        duration = float(probe(Path(clip.path), "duration"))
        assert duration == pytest.approx(clip.highlight.duration, abs=0.5)


def test_respeita_os_limites_de_duracao(run_result):
    report, _ = run_result
    for clip in report.clips:
        assert 10.0 <= clip.highlight.duration <= 20.0


def test_cortes_nao_se_sobrepoem(run_result):
    report, _ = run_result
    janelas = sorted((c.highlight.start, c.highlight.end) for c in report.clips)
    for (_, first_end), (second_start, _) in zip(janelas, janelas[1:]):
        assert second_start >= first_end - 1.5


def test_escreve_relatorio_com_custo_por_minuto(run_result):
    report, out_dir = run_result
    assert (out_dir / "report.json").exists()
    assert (out_dir / "config-usado.json").exists()
    assert report.cost["custo_brl"]["por_minuto_de_video"] >= 0
    assert report.cost["tempo"]["video_fonte_s"] == pytest.approx(45.0, abs=1.0)


def test_gera_pagina_de_revisao_com_miniaturas(run_result):
    report, out_dir = run_result
    pagina = out_dir / "revisao.html"
    assert pagina.exists()
    html = pagina.read_text(encoding="utf-8")
    assert html.count("<article") == len(report.clips)
    for clip in report.clips:
        assert Path(clip.poster).exists(), "toda miniatura citada tem de existir no disco"
        assert Path(clip.poster).stat().st_size > 1000


def test_guarda_intermediarios_para_reaproveitar(run_result):
    _, out_dir = run_result
    work = out_dir / "work"
    assert (work / "transcript.json").exists()
    assert (work / "audio.wav").exists()
    assert list(work.glob("*.crop.json"))
    assert list(work.glob("*.ass"))


def test_segunda_rodada_reaproveita_transcricao(sample_video, tmp_path):
    config = offline_config()
    config.clips = 1
    run_pipeline(sample_video, tmp_path, config, reuse=True)
    marker = tmp_path / "work" / "transcript.json"
    marker_mtime = marker.stat().st_mtime

    report = run_pipeline(sample_video, tmp_path, config, reuse=True)
    assert marker.stat().st_mtime == marker_mtime, "não deveria transcrever de novo"
    assert not any(t.name == "transcricao" for t in report.timings)


def test_recorte_central_quando_pedido(sample_video, tmp_path):
    config = offline_config()
    config.clips = 1
    config.reframe.backend = "center"
    report = run_pipeline(sample_video, tmp_path, config, reuse=False)
    assert all(clip.crop_backend == "center" for clip in report.clips)


def test_sem_legenda_quando_desligada(sample_video, tmp_path):
    config = offline_config()
    config.clips = 1
    config.captions.enabled = False
    report = run_pipeline(sample_video, tmp_path, config, reuse=False)
    assert not list((tmp_path / "work").glob("*.ass"))
    assert all(clip.caption_count == 0 for clip in report.clips)


def test_slug_do_arquivo_e_seguro():
    assert slugify("Olha só isso aí, gente!") == "olha-so-isso-ai-gente"
    assert slugify("///") == "corte"
    assert len(slugify("a" * 200)) <= 40
