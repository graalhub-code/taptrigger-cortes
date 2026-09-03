"""Servidor web do pipeline: envia vídeo, acompanha, vê os cortes.

Camada fina sobre o pipeline — nada de regra de negócio nova aqui. O trabalho
é receber o arquivo sem estourar a memória, colocar na fila, e servir o que o
pipeline já produz.

Sem cadastro de propósito: é ferramenta de teste, protegida por a URL não ser
divulgada. Definir ``CORTES_WEB_TOKEN`` liga uma senha simples, para quando o
endereço deixar de ser secreto.
"""

from __future__ import annotations

import logging
import os
import shutil
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse

from ..config import Config
from . import paginas
from .jobs import FALHOU, PRONTO, JobStore, Worker

logger = logging.getLogger(__name__)

EXTENSOES_ACEITAS = {".mp4", ".mov", ".mkv", ".webm", ".avi", ".m4v", ".ts", ".flv"}


def raiz_de_dados() -> Path:
    return Path(os.environ.get("CORTES_DATA_DIR", "/data/jobs")).expanduser()


def limite_mb() -> int:
    return int(os.environ.get("CORTES_MAX_UPLOAD_MB", "2048"))


def token_de_acesso() -> str:
    return os.environ.get("CORTES_WEB_TOKEN", "").strip()


def montar_config(opcoes: dict) -> Config:
    """Traduz as opções do formulário para a configuração do pipeline."""
    config = Config()
    if opcoes.get("clips"):
        config.clips = int(opcoes["clips"])
    if opcoes.get("selector"):
        config.selector.backend = opcoes["selector"]
    if opcoes.get("whisper_model"):
        config.transcribe.model = opcoes["whisper_model"]
    if opcoes.get("reframe"):
        config.reframe.backend = opcoes["reframe"]
    return config


def criar_app(raiz: Path | None = None) -> FastAPI:
    store = JobStore(raiz or raiz_de_dados())
    worker = Worker(store, montar_config)

    @asynccontextmanager
    async def ciclo_de_vida(app: FastAPI):
        worker.iniciar()
        yield
        worker.parar()

    app = FastAPI(title="Cortes automáticos", lifespan=ciclo_de_vida, docs_url=None, redoc_url=None)
    app.state.store = store
    app.state.worker = worker

    @app.middleware("http")
    async def exigir_token(request: Request, call_next):
        token = token_de_acesso()
        if token and request.url.path not in ("/saude",):
            enviado = request.query_params.get("token") or request.headers.get("x-token", "")
            if enviado != token:
                return JSONResponse({"erro": "token inválido"}, status_code=401)
        return await call_next(request)

    @app.get("/saude")
    def saude():
        return {"ok": True, "fila": worker.tamanho_da_fila}

    @app.get("/", response_class=HTMLResponse)
    def envio():
        return paginas.pagina_envio(limite_mb())

    @app.post("/jobs")
    async def criar_job(
        request: Request,
        video: UploadFile,
        clips: str = Form("6"),
        selector: str = Form("claude"),
        whisper_model: str = Form("small"),
        reframe: str = Form("auto"),
    ):
        nome = Path(video.filename or "video.mp4").name
        extensao = Path(nome).suffix.lower()
        if extensao not in EXTENSOES_ACEITAS:
            return HTMLResponse(
                paginas.pagina_envio(
                    limite_mb(), f"Formato {extensao or 'desconhecido'} não é aceito."
                ),
                status_code=400,
            )

        opcoes = {
            "clips": _inteiro(clips, 6, 1, 30),
            "selector": selector if selector in ("claude", "heuristic") else "claude",
            "whisper_model": whisper_model
            if whisper_model in ("tiny", "small", "medium", "large-v3")
            else "small",
            "reframe": reframe if reframe in ("auto", "face", "motion", "center") else "auto",
        }

        job = store.criar(nome, opcoes)
        destino = store.dir_do_job(job.id) / "entrada" / f"video{extensao}"
        destino.parent.mkdir(parents=True, exist_ok=True)

        try:
            gravados = _gravar_upload(video, destino, limite_mb() * 1024 * 1024)
        except ValueError as exc:
            shutil.rmtree(store.dir_do_job(job.id), ignore_errors=True)
            return HTMLResponse(paginas.pagina_envio(limite_mb(), str(exc)), status_code=413)

        logger.info("job %s recebeu %s (%.1f MB)", job.id, nome, gravados / 1024 / 1024)
        worker.enfileirar(job.id)
        return RedirectResponse(f"/jobs/{job.id}/", status_code=303)

    @app.get("/jobs", response_class=HTMLResponse)
    def listar():
        return paginas.pagina_lista(store.listar())

    @app.get("/jobs/{job_id}")
    def sem_barra(job_id: str):
        # A página de resultado usa caminhos relativos; sem a barra final eles
        # resolveriam para fora do diretório do job.
        return RedirectResponse(f"/jobs/{job_id}/", status_code=308)

    @app.get("/jobs/{job_id}/", response_class=HTMLResponse)
    def ver_job(job_id: str):
        job = _job_ou_404(store, job_id)
        if job.estado == PRONTO:
            revisao = store.dir_do_job(job_id) / "saida" / "revisao.html"
            if revisao.exists():
                return HTMLResponse(revisao.read_text(encoding="utf-8"))
            return HTMLResponse(paginas.pagina_erro(job), status_code=500)
        if job.estado == FALHOU:
            return HTMLResponse(paginas.pagina_erro(job))
        return HTMLResponse(paginas.pagina_progresso(job, worker.tamanho_da_fila))

    @app.get("/api/jobs/{job_id}")
    def estado_do_job(job_id: str):
        job = _job_ou_404(store, job_id)
        return {
            "id": job.id,
            "estado": job.estado,
            "etapa": job.etapa,
            "descricao": job.descricao,
            "cortes": job.cortes,
            "erro": job.erro,
        }

    @app.get("/jobs/{job_id}/report.json")
    def relatorio(job_id: str):
        return _arquivo_da_saida(store, job_id, "report.json", "application/json")

    @app.get("/jobs/{job_id}/clips/{nome}")
    def corte(job_id: str, nome: str):
        return _arquivo_da_saida(store, job_id, f"clips/{nome}", "video/mp4")

    @app.get("/jobs/{job_id}/thumbs/{nome}")
    def miniatura(job_id: str, nome: str):
        return _arquivo_da_saida(store, job_id, f"thumbs/{nome}", "image/jpeg")

    return app


def _inteiro(valor: str, padrao: int, minimo: int, maximo: int) -> int:
    try:
        return max(minimo, min(maximo, int(valor)))
    except (TypeError, ValueError):
        return padrao


def _gravar_upload(video: UploadFile, destino: Path, limite_bytes: int) -> int:
    """Copia em blocos e aborta se passar do limite — nunca carrega tudo na RAM."""
    gravados = 0
    with destino.open("wb") as saida:
        while True:
            bloco = video.file.read(1024 * 1024)
            if not bloco:
                break
            gravados += len(bloco)
            if gravados > limite_bytes:
                saida.close()
                destino.unlink(missing_ok=True)
                raise ValueError(
                    f"Arquivo maior que o limite de {limite_bytes // 1024 // 1024} MB."
                )
            saida.write(bloco)
    if gravados == 0:
        destino.unlink(missing_ok=True)
        raise ValueError("O arquivo chegou vazio.")
    return gravados


def _job_ou_404(store: JobStore, job_id: str):
    job = store.obter(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="job não encontrado")
    return job


def _arquivo_da_saida(store: JobStore, job_id: str, relativo: str, tipo: str) -> FileResponse:
    _job_ou_404(store, job_id)
    base = (store.dir_do_job(job_id) / "saida").resolve()
    alvo = (base / relativo).resolve()
    # Impede que um nome como ../../etc/passwd escape do diretório do job.
    if not alvo.is_relative_to(base) or not alvo.is_file():
        raise HTTPException(status_code=404, detail="arquivo não encontrado")
    return FileResponse(alvo, media_type=tipo)


app = None  # criado sob demanda por servidor()


def servidor() -> FastAPI:
    """Ponto de entrada para o uvicorn: ``cortes.web.app:servidor``."""
    return criar_app()
