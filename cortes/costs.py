"""Contabilidade de custo por minuto de vídeo processado.

Este módulo existe por causa do passo 2 do brief: sem número medido não dá
para precificar plano nenhum. Cada estágio declara em que hardware roda, o
cronômetro registra o tempo, e no fim isso vira R$/minuto processado usando os
preços configurados em ``CostConfig``.
"""

from __future__ import annotations

import time
from contextlib import contextmanager

from .config import CostConfig
from .models import StageTiming


class CostTracker:
    def __init__(self) -> None:
        self.timings: list[StageTiming] = []
        self.llm_usage: dict = {}

    @contextmanager
    def stage(self, name: str, hardware: str = "cpu"):
        started = time.perf_counter()
        try:
            yield
        finally:
            elapsed = time.perf_counter() - started
            self.timings.append(StageTiming(name=name, seconds=round(elapsed, 3), hardware=hardware))

    def seconds_on(self, hardware: str) -> float:
        return sum(t.seconds for t in self.timings if t.hardware == hardware)

    @property
    def total_seconds(self) -> float:
        return sum(t.seconds for t in self.timings)

    def summarize(self, config: CostConfig, source_duration: float, clip_count: int) -> dict:
        gpu_seconds = self.seconds_on("gpu")
        cpu_seconds = self.total_seconds - gpu_seconds

        gpu_brl = gpu_seconds / 3600.0 * config.gpu_brl_hour
        cpu_brl = cpu_seconds / 3600.0 * config.cpu_brl_hour

        input_tokens = int(self.llm_usage.get("input_tokens", 0))
        output_tokens = int(self.llm_usage.get("output_tokens", 0))
        llm_usd = (
            input_tokens / 1_000_000 * config.llm_input_usd_mtok
            + output_tokens / 1_000_000 * config.llm_output_usd_mtok
        )
        llm_brl = llm_usd * config.usd_brl

        total_brl = gpu_brl + cpu_brl + llm_brl
        source_minutes = max(source_duration / 60.0, 1e-6)

        return {
            "tempo": {
                "processamento_s": round(self.total_seconds, 2),
                "gpu_s": round(gpu_seconds, 2),
                "cpu_s": round(cpu_seconds, 2),
                "video_fonte_s": round(source_duration, 2),
                # <1 significa que processa mais rápido que o tempo real.
                "fator_tempo_real": round(self.total_seconds / max(source_duration, 1e-6), 3),
            },
            "tokens": {
                "entrada": input_tokens,
                "saida": output_tokens,
                "modelo": self.llm_usage.get("model", ""),
            },
            "custo_brl": {
                "gpu": round(gpu_brl, 4),
                "cpu": round(cpu_brl, 4),
                "llm": round(llm_brl, 4),
                "total": round(total_brl, 4),
                "por_minuto_de_video": round(total_brl / source_minutes, 4),
                "por_hora_de_video": round(total_brl / source_minutes * 60.0, 2),
                "por_corte": round(total_brl / max(clip_count, 1), 4),
            },
            "precos_usados": {
                "gpu_brl_hora": config.gpu_brl_hour,
                "cpu_brl_hora": config.cpu_brl_hour,
                "usd_brl": config.usd_brl,
                "llm_entrada_usd_mtok": config.llm_input_usd_mtok,
                "llm_saida_usd_mtok": config.llm_output_usd_mtok,
            },
        }
