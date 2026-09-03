"""Fila de processamento em memória, com estado no disco.

Processar vídeo leva minutos: a requisição HTTP não pode esperar. O envio só
grava o arquivo, cria o job e devolve a página de acompanhamento; um worker
em segundo plano roda o pipeline e vai anotando o progresso.

Um worker por vez de propósito — dois ffmpeg simultâneos numa máquina pequena
deixam os dois lentos e ainda arriscam estourar a memória.
"""

from __future__ import annotations

import json
import logging
import queue
import threading
import time
import traceback
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from ..config import Config
from ..pipeline import run_pipeline

logger = logging.getLogger(__name__)

PENDENTE = "pendente"
PROCESSANDO = "processando"
PRONTO = "pronto"
FALHOU = "falhou"


@dataclass
class Job:
    id: str
    nome_original: str
    criado_em: str
    estado: str = PENDENTE
    etapa: str = ""
    descricao: str = "na fila"
    erro: str = ""
    cortes: int = 0
    duracao_fonte: float = 0.0
    segundos_processando: float = 0.0
    opcoes: dict = field(default_factory=dict)

    @property
    def terminado(self) -> bool:
        return self.estado in (PRONTO, FALHOU)


class JobStore:
    """Guarda os jobs em memória e espelha cada um num ``job.json``."""

    def __init__(self, raiz: Path):
        self.raiz = raiz
        self.raiz.mkdir(parents=True, exist_ok=True)
        self._jobs: dict[str, Job] = {}
        self._lock = threading.Lock()
        self._carregar_do_disco()

    def dir_do_job(self, job_id: str) -> Path:
        return self.raiz / job_id

    def criar(self, nome_original: str, opcoes: dict) -> Job:
        job = Job(
            id=uuid.uuid4().hex[:12],
            nome_original=nome_original,
            criado_em=datetime.now(timezone.utc).isoformat(timespec="seconds"),
            opcoes=opcoes,
        )
        with self._lock:
            self._jobs[job.id] = job
        self.dir_do_job(job.id).mkdir(parents=True, exist_ok=True)
        self._salvar(job)
        return job

    def obter(self, job_id: str) -> Job | None:
        with self._lock:
            return self._jobs.get(job_id)

    def listar(self) -> list[Job]:
        with self._lock:
            jobs = list(self._jobs.values())
        return sorted(jobs, key=lambda j: j.criado_em, reverse=True)

    def atualizar(self, job_id: str, **campos) -> Job | None:
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                return None
            for chave, valor in campos.items():
                setattr(job, chave, valor)
        self._salvar(job)
        return job

    def _salvar(self, job: Job) -> None:
        destino = self.dir_do_job(job.id) / "job.json"
        destino.parent.mkdir(parents=True, exist_ok=True)
        destino.write_text(
            json.dumps(asdict(job), ensure_ascii=False, indent=2), encoding="utf-8"
        )

    def _carregar_do_disco(self) -> None:
        for arquivo in sorted(self.raiz.glob("*/job.json")):
            try:
                dados = json.loads(arquivo.read_text(encoding="utf-8"))
                job = Job(**dados)
            except Exception:
                logger.warning("job ilegível em %s, ignorando", arquivo)
                continue
            # Job que estava rodando quando o processo caiu não volta sozinho.
            if job.estado in (PENDENTE, PROCESSANDO):
                job.estado = FALHOU
                job.descricao = "interrompido por reinício do servidor"
                job.erro = "o servidor reiniciou no meio do processamento"
                self._salvar(job)
            self._jobs[job.id] = job


class Worker:
    """Consome a fila em uma thread, um job por vez."""

    def __init__(self, store: JobStore, montar_config):
        self.store = store
        self.montar_config = montar_config
        self.fila: queue.Queue[str] = queue.Queue()
        self._thread: threading.Thread | None = None
        self._parar = threading.Event()

    def iniciar(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._parar.clear()
        self._thread = threading.Thread(target=self._loop, name="cortes-worker", daemon=True)
        self._thread.start()

    def parar(self, timeout: float = 5.0) -> None:
        self._parar.set()
        self.fila.put("")
        if self._thread:
            self._thread.join(timeout=timeout)

    def enfileirar(self, job_id: str) -> None:
        self.fila.put(job_id)

    @property
    def tamanho_da_fila(self) -> int:
        return self.fila.qsize()

    def _loop(self) -> None:
        while not self._parar.is_set():
            job_id = self.fila.get()
            if not job_id or self._parar.is_set():
                continue
            try:
                self._processar(job_id)
            except Exception:
                logger.exception("worker quebrou no job %s", job_id)
                self.store.atualizar(
                    job_id, estado=FALHOU, descricao="erro inesperado", erro=traceback.format_exc(limit=3)
                )

    def _processar(self, job_id: str) -> None:
        job = self.store.obter(job_id)
        if job is None:
            return

        dir_job = self.store.dir_do_job(job_id)
        entradas = list((dir_job / "entrada").glob("*"))
        if not entradas:
            self.store.atualizar(
                job_id, estado=FALHOU, descricao="arquivo enviado sumiu", erro="entrada vazia"
            )
            return

        inicio = time.perf_counter()
        self.store.atualizar(job_id, estado=PROCESSANDO, etapa="analisando", descricao="começando")

        def progresso(etapa: str, descricao: str) -> None:
            self.store.atualizar(job_id, etapa=etapa, descricao=descricao)

        try:
            report = run_pipeline(
                entradas[0],
                dir_job / "saida",
                self.montar_config(job.opcoes),
                reuse=False,
                on_progress=progresso,
            )
        except Exception as exc:
            logger.exception("pipeline falhou no job %s", job_id)
            self.store.atualizar(
                job_id,
                estado=FALHOU,
                descricao="o processamento falhou",
                erro=f"{type(exc).__name__}: {exc}",
                segundos_processando=round(time.perf_counter() - inicio, 1),
            )
            return

        self.store.atualizar(
            job_id,
            estado=PRONTO,
            etapa="pronto",
            descricao=f"{len(report.clips)} cortes prontos",
            cortes=len(report.clips),
            duracao_fonte=report.source_duration,
            segundos_processando=round(time.perf_counter() - inicio, 1),
        )
