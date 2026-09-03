"""Testes do servidor: envio, fila, resultado e as recusas que importam."""

import time

import pytest
from fastapi.testclient import TestClient

from cortes.web.app import criar_app, montar_config
from cortes.web.jobs import FALHOU, PRONTO


@pytest.fixture
def cliente(tmp_path, monkeypatch):
    # Sem modelo de transcrição no teste: o pipeline sintetiza a fala.
    monkeypatch.setenv("CORTES_TRANSCRIBER", "fake")
    monkeypatch.setenv("CORTES_MAX_UPLOAD_MB", "5")
    monkeypatch.delenv("CORTES_WEB_TOKEN", raising=False)
    with TestClient(criar_app(tmp_path / "jobs")) as cliente:
        yield cliente


def esperar_fim(cliente, job_id, timeout=180):
    limite = time.time() + timeout
    while time.time() < limite:
        estado = cliente.get(f"/api/jobs/{job_id}").json()
        if estado["estado"] in (PRONTO, FALHOU):
            return estado
        time.sleep(1)
    raise AssertionError(f"job {job_id} não terminou em {timeout}s")


def enviar(cliente, video_path, **campos):
    dados = {"clips": "2", "selector": "heuristic", "reframe": "motion", **campos}
    with open(video_path, "rb") as arquivo:
        return cliente.post(
            "/jobs",
            files={"video": (video_path.name, arquivo, "video/mp4")},
            data=dados,
            follow_redirects=False,
        )


def test_pagina_de_envio_abre(cliente):
    resposta = cliente.get("/")
    assert resposta.status_code == 200
    assert "Enviar e processar" in resposta.text


def test_saude_responde_sem_token(cliente):
    assert cliente.get("/saude").json()["ok"] is True


def test_envio_processa_e_mostra_os_cortes(cliente, sample_video):
    resposta = enviar(cliente, sample_video)
    assert resposta.status_code == 303
    destino = resposta.headers["location"]
    job_id = destino.strip("/").split("/")[-1]

    estado = esperar_fim(cliente, job_id)
    assert estado["estado"] == PRONTO, estado.get("erro")
    assert estado["cortes"] >= 1

    pagina = cliente.get(destino)
    assert pagina.status_code == 200
    assert pagina.text.count("<article") == estado["cortes"]


def test_serve_o_mp4_e_a_miniatura(cliente, sample_video):
    resposta = enviar(cliente, sample_video)
    job_id = resposta.headers["location"].strip("/").split("/")[-1]
    esperar_fim(cliente, job_id)

    pagina = cliente.get(f"/jobs/{job_id}/").text
    nome = pagina.split('src="clips/')[1].split('"')[0].split("#")[0]
    video = cliente.get(f"/jobs/{job_id}/clips/{nome}")
    assert video.status_code == 200
    assert video.headers["content-type"] == "video/mp4"
    assert len(video.content) > 10_000

    thumb = pagina.split('poster="thumbs/')[1].split('"')[0]
    assert cliente.get(f"/jobs/{job_id}/thumbs/{thumb}").status_code == 200
    assert cliente.get(f"/jobs/{job_id}/report.json").status_code == 200


def test_progresso_enquanto_processa(cliente, sample_video):
    resposta = enviar(cliente, sample_video)
    job_id = resposta.headers["location"].strip("/").split("/")[-1]
    pagina = cliente.get(f"/jobs/{job_id}/")
    assert pagina.status_code == 200
    # Ainda processando ou já pronto — nos dois casos a página tem de abrir.
    assert "Processando" in pagina.text or "<article" in pagina.text
    esperar_fim(cliente, job_id)


def test_recusa_extensao_que_nao_e_video(cliente, tmp_path):
    falso = tmp_path / "planilha.xlsx"
    falso.write_bytes(b"nao sou video")
    with open(falso, "rb") as arquivo:
        resposta = cliente.post(
            "/jobs",
            files={"video": (falso.name, arquivo, "application/octet-stream")},
            data={"clips": "2"},
        )
    assert resposta.status_code == 400
    assert "não é aceito" in resposta.text


def test_recusa_arquivo_acima_do_limite(cliente, tmp_path):
    grande = tmp_path / "grande.mp4"
    grande.write_bytes(b"0" * (6 * 1024 * 1024))  # limite do fixture é 5 MB
    with open(grande, "rb") as arquivo:
        resposta = cliente.post(
            "/jobs", files={"video": (grande.name, arquivo, "video/mp4")}, data={"clips": "2"}
        )
    assert resposta.status_code == 413
    assert "limite" in resposta.text


def test_job_inexistente_devolve_404(cliente):
    assert cliente.get("/jobs/naoexiste/").status_code == 404
    assert cliente.get("/api/jobs/naoexiste").status_code == 404


def test_nao_serve_arquivo_fora_do_job(cliente, sample_video):
    resposta = enviar(cliente, sample_video)
    job_id = resposta.headers["location"].strip("/").split("/")[-1]
    esperar_fim(cliente, job_id)
    fuga = cliente.get(f"/jobs/{job_id}/clips/..%2f..%2fjob.json")
    assert fuga.status_code == 404


def test_sem_barra_final_redireciona(cliente, sample_video):
    resposta = enviar(cliente, sample_video)
    job_id = resposta.headers["location"].strip("/").split("/")[-1]
    redirecionamento = cliente.get(f"/jobs/{job_id}", follow_redirects=False)
    assert redirecionamento.status_code == 308
    assert redirecionamento.headers["location"].endswith("/")


def test_token_bloqueia_quando_configurado(tmp_path, monkeypatch):
    monkeypatch.setenv("CORTES_WEB_TOKEN", "segredo")
    with TestClient(criar_app(tmp_path / "jobs")) as cliente:
        assert cliente.get("/").status_code == 401
        assert cliente.get("/?token=segredo").status_code == 200
        assert cliente.get("/saude").status_code == 200


def test_valor_absurdo_de_cortes_e_limitado(cliente, sample_video):
    resposta = enviar(cliente, sample_video, clips="999")
    job_id = resposta.headers["location"].strip("/").split("/")[-1]
    estado = cliente.get(f"/api/jobs/{job_id}").json()
    assert estado["estado"] in ("pendente", "processando", "pronto")
    esperar_fim(cliente, job_id)
    # 999 cortes não pode virar 999 renderizações: a rota corta em 30.
    assert cliente.get(f"/api/jobs/{job_id}").json()["cortes"] <= 30


def test_montar_config_traduz_as_opcoes_do_formulario():
    config = montar_config({"clips": "5", "selector": "heuristic", "reframe": "center"})
    assert config.clips == 5
    assert config.selector.backend == "heuristic"
    assert config.reframe.backend == "center"
