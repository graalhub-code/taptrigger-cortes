from pathlib import Path

from cortes.models import Clip, Highlight, RunReport, StageTiming
from cortes.review import build_review


def make_report(out_dir: Path, clips=None) -> RunReport:
    return RunReport(
        source="/videos/live.mp4",
        source_duration=1800.0,
        clips=clips if clips is not None else [],
        timings=[StageTiming("render", 12.0, "cpu")],
        llm_model="claude-opus-5",
        llm_input_tokens=1000,
        llm_output_tokens=200,
        cost={
            "tempo": {"processamento_s": 12.0, "fator_tempo_real": 0.4},
            "custo_brl": {"total": 0.5, "por_minuto_de_video": 0.017, "por_hora_de_video": 1.02},
        },
    )


def make_clip(out_dir: Path, index=1, title="O plot twist", score=0.9, poster=True) -> Clip:
    return Clip(
        index=index,
        highlight=Highlight(start=65.0, end=95.0, title=title, score=score, reason="abre com pergunta"),
        path=str(out_dir / "clips" / f"{index:02d}-corte.mp4"),
        crop_backend="face",
        caption_count=12,
        poster=str(out_dir / "thumbs" / f"{index:02d}-corte.jpg") if poster else "",
    )


def test_gera_um_cartao_por_corte(tmp_path):
    report = make_report(tmp_path, [make_clip(tmp_path, i) for i in (1, 2, 3)])
    html = build_review(report, tmp_path).read_text(encoding="utf-8")
    assert html.count("<article") == 3
    assert html.count("<video") == 3


def test_usa_caminho_relativo_para_abrir_offline(tmp_path):
    report = make_report(tmp_path, [make_clip(tmp_path)])
    html = build_review(report, tmp_path).read_text(encoding="utf-8")
    assert 'src="clips/01-corte.mp4' in html
    assert 'poster="thumbs/01-corte.jpg"' in html
    assert str(tmp_path) not in html, "caminho absoluto quebra se a pasta for movida"


def test_sem_miniatura_nao_emite_atributo_poster(tmp_path):
    report = make_report(tmp_path, [make_clip(tmp_path, poster=False)])
    html = build_review(report, tmp_path).read_text(encoding="utf-8")
    assert "poster=" not in html


def test_mostra_trecho_de_origem_em_minutos(tmp_path):
    report = make_report(tmp_path, [make_clip(tmp_path)])
    html = build_review(report, tmp_path).read_text(encoding="utf-8")
    assert "01:05" in html and "01:35" in html


def test_escapa_titulo_com_html(tmp_path):
    report = make_report(tmp_path, [make_clip(tmp_path, title='<script>alert("x")</script>')])
    html = build_review(report, tmp_path).read_text(encoding="utf-8")
    assert "<script>alert" not in html
    assert "&lt;script&gt;" in html


def test_traz_o_custo_da_rodada(tmp_path):
    report = make_report(tmp_path, [make_clip(tmp_path)])
    html = build_review(report, tmp_path).read_text(encoding="utf-8")
    assert "R$ 0.0170" in html
    assert "0.40x tempo real" in html


def test_rodada_sem_corte_avisa_em_vez_de_pagina_vazia(tmp_path):
    html = build_review(make_report(tmp_path), tmp_path).read_text(encoding="utf-8")
    assert "Nenhum trecho" in html
    assert "<article" not in html


def test_barra_de_nota_nao_estoura_com_nota_zero(tmp_path):
    report = make_report(tmp_path, [make_clip(tmp_path, score=0.0)])
    html = build_review(report, tmp_path).read_text(encoding="utf-8")
    assert "width:0%" in html
