"""Configuração do pipeline.

Tudo é ajustável por variável de ambiente com prefixo ``CORTES_``, para que a
mesma imagem rode sem alteração na VPS (CPU, backends leves) e na GPU alugada
por segundo (backends pesados) — só mudando o ambiente.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field, fields


def _env_str(name: str, default: str) -> str:
    return os.environ.get(f"CORTES_{name}", default)


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(f"CORTES_{name}")
    return int(raw) if raw not in (None, "") else default


def _env_float(name: str, default: float) -> float:
    raw = os.environ.get(f"CORTES_{name}")
    return float(raw) if raw not in (None, "") else default


def _env_bool(name: str, default: bool) -> bool:
    raw = os.environ.get(f"CORTES_{name}")
    if raw in (None, ""):
        return default
    return raw.strip().lower() in ("1", "true", "yes", "on", "sim")


@dataclass
class TranscribeConfig:
    # faster-whisper (real) | fake (determinístico, para teste sem modelo baixado)
    backend: str = field(default_factory=lambda: _env_str("TRANSCRIBER", "faster-whisper"))
    model: str = field(default_factory=lambda: _env_str("WHISPER_MODEL", "medium"))
    device: str = field(default_factory=lambda: _env_str("WHISPER_DEVICE", "auto"))
    compute_type: str = field(default_factory=lambda: _env_str("WHISPER_COMPUTE", "default"))
    language: str = field(default_factory=lambda: _env_str("LANGUAGE", "pt"))
    beam_size: int = field(default_factory=lambda: _env_int("WHISPER_BEAM", 5))


@dataclass
class SelectorConfig:
    # claude (LLM lê a transcrição) | heuristic (sem rede, sem custo)
    backend: str = field(default_factory=lambda: _env_str("SELECTOR", "claude"))
    model: str = field(default_factory=lambda: _env_str("CLAUDE_MODEL", "claude-opus-5"))
    effort: str = field(default_factory=lambda: _env_str("CLAUDE_EFFORT", "medium"))
    max_output_tokens: int = field(default_factory=lambda: _env_int("CLAUDE_MAX_TOKENS", 16000))
    # Transcrições longas vão em blocos; cada bloco vira uma chamada.
    window_minutes: float = field(default_factory=lambda: _env_float("SELECTOR_WINDOW_MIN", 20.0))
    # Se a chamada ao Claude falhar, cai na heurística em vez de derrubar a rodada.
    fallback_to_heuristic: bool = field(default_factory=lambda: _env_bool("SELECTOR_FALLBACK", True))


@dataclass
class ReframeConfig:
    # auto (rosto se houver modelo, senão movimento) | face | motion | center
    backend: str = field(default_factory=lambda: _env_str("REFRAME", "auto"))
    sample_fps: float = field(default_factory=lambda: _env_float("REFRAME_SAMPLE_FPS", 3.0))
    # Constante de tempo da "câmera", em segundos: quanto ela leva para cobrir
    # ~63% da distância até o alvo. Em segundos, e não por amostra, para que
    # mudar sample_fps não mude o comportamento do pan.
    smoothing_tau: float = field(default_factory=lambda: _env_float("REFRAME_TAU", 0.6))
    # Só move a câmera quando o alvo sai desta fração da largura do recorte.
    deadband: float = field(default_factory=lambda: _env_float("REFRAME_DEADBAND", 0.08))
    # Limite de velocidade do pan, em fração da largura do recorte por segundo.
    max_pan_per_second: float = field(default_factory=lambda: _env_float("REFRAME_MAX_PAN", 0.6))


@dataclass
class CaptionConfig:
    enabled: bool = field(default_factory=lambda: _env_bool("CAPTIONS", True))
    font: str = field(default_factory=lambda: _env_str("CAPTION_FONT", "DejaVu Sans"))
    font_size: int = field(default_factory=lambda: _env_int("CAPTION_FONT_SIZE", 84))
    max_chars: int = field(default_factory=lambda: _env_int("CAPTION_MAX_CHARS", 28))
    max_words: int = field(default_factory=lambda: _env_int("CAPTION_MAX_WORDS", 4))
    max_seconds: float = field(default_factory=lambda: _env_float("CAPTION_MAX_SECONDS", 1.6))
    # Altura da linha de legenda a partir da base, em pixels do vídeo final.
    margin_bottom: int = field(default_factory=lambda: _env_int("CAPTION_MARGIN", 420))
    uppercase: bool = field(default_factory=lambda: _env_bool("CAPTION_UPPERCASE", True))


@dataclass
class RenderConfig:
    width: int = field(default_factory=lambda: _env_int("OUT_WIDTH", 1080))
    height: int = field(default_factory=lambda: _env_int("OUT_HEIGHT", 1920))
    crf: int = field(default_factory=lambda: _env_int("CRF", 21))
    preset: str = field(default_factory=lambda: _env_str("PRESET", "veryfast"))
    audio_bitrate: str = field(default_factory=lambda: _env_str("AUDIO_BITRATE", "128k"))
    fps: int = field(default_factory=lambda: _env_int("OUT_FPS", 30))


@dataclass
class CostConfig:
    """Preços usados para transformar tempo de máquina em R$/minuto processado.

    Os defaults são chutes de partida — o objetivo do ``report.json`` é
    justamente substituí-los por número medido na GPU que for contratada.
    """

    gpu_brl_hour: float = field(default_factory=lambda: _env_float("GPU_BRL_HOUR", 2.20))
    cpu_brl_hour: float = field(default_factory=lambda: _env_float("CPU_BRL_HOUR", 0.30))
    usd_brl: float = field(default_factory=lambda: _env_float("USD_BRL", 5.40))
    # Preço do modelo de seleção, em USD por 1M de tokens (Claude Opus 5).
    llm_input_usd_mtok: float = field(default_factory=lambda: _env_float("LLM_IN_USD", 5.0))
    llm_output_usd_mtok: float = field(default_factory=lambda: _env_float("LLM_OUT_USD", 25.0))
    storage_brl_gb_month: float = field(default_factory=lambda: _env_float("STORAGE_BRL_GB", 0.10))


@dataclass
class Config:
    clips: int = field(default_factory=lambda: _env_int("CLIPS", 8))
    min_clip_seconds: float = field(default_factory=lambda: _env_float("MIN_CLIP", 18.0))
    max_clip_seconds: float = field(default_factory=lambda: _env_float("MAX_CLIP", 75.0))
    # Folga antes/depois do trecho escolhido, para não cortar a fala no talo.
    pad_start: float = field(default_factory=lambda: _env_float("PAD_START", 0.4))
    pad_end: float = field(default_factory=lambda: _env_float("PAD_END", 0.6))
    keep_work_dir: bool = field(default_factory=lambda: _env_bool("KEEP_WORK", True))

    transcribe: TranscribeConfig = field(default_factory=TranscribeConfig)
    selector: SelectorConfig = field(default_factory=SelectorConfig)
    reframe: ReframeConfig = field(default_factory=ReframeConfig)
    captions: CaptionConfig = field(default_factory=CaptionConfig)
    render: RenderConfig = field(default_factory=RenderConfig)
    cost: CostConfig = field(default_factory=CostConfig)

    def describe(self) -> dict:
        out: dict = {}
        for f in fields(self):
            value = getattr(self, f.name)
            if hasattr(value, "__dataclass_fields__"):
                out[f.name] = {sf.name: getattr(value, sf.name) for sf in fields(value)}
            else:
                out[f.name] = value
        return out
