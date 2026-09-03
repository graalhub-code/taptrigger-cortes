"""Escolha dos trechos que viram corte.

Dois backends com a mesma saída:

``claude``     — um LLM lê a transcrição com timestamps e aponta os trechos.
``heuristic``  — pontuação local (densidade de fala, ganchos, pausa antes),
                 sem rede e sem custo; é o fallback e a linha de base para
                 comparar se o LLM está valendo o que custa.
"""

from __future__ import annotations

import json
import logging
import re

from ..config import Config, SelectorConfig
from ..models import Highlight, Transcript

logger = logging.getLogger(__name__)

# Marcadores de reação/gancho em pt-BR. Lista curta de propósito: serve como
# linha de base barata, não como classificador.
HOOK_PATTERNS = [
    r"\bkk+\b",
    r"\bhaha+\b",
    r"\bcaramba\b",
    r"\bmano\b",
    r"\bcara\b",
    r"\bgente\b",
    r"\bs[ée]rio\b",
    r"\bmeu deus\b",
    r"\bn[ãa]o acredito\b",
    r"\bque isso\b",
    r"\bolha (s[óo]|isso)\b",
    r"\bpelo amor\b",
    r"\bnunca\b",
    r"\bmelhor\b",
    r"\bpior\b",
    r"\bsegredo\b",
    r"\bningu[ée]m (fala|conta|sabe)\b",
]
_HOOK_RE = re.compile("|".join(HOOK_PATTERNS), re.IGNORECASE)

# Sobreposição tolerada entre dois cortes escolhidos, em segundos.
MAX_OVERLAP_SECONDS = 1.5

SYSTEM_PROMPT = """Você seleciona trechos de uma live/gravação longa que funcionam como \
vídeo curto vertical (TikTok/Reels/Shorts).

Um bom trecho:
- abre com um gancho nos primeiros 3 segundos (pergunta, afirmação forte, reação);
- se sustenta sozinho, sem precisar do que veio antes;
- tem um fecho — remate, punchline ou conclusão — em vez de cortar no meio da frase.

Descarte: conversa administrativa, leitura de chat sem contexto, silêncio, \
repetição do mesmo assunto já escolhido em outro trecho."""


def _mmss(seconds: float) -> str:
    total = int(seconds)
    return f"{total // 60:02d}:{total % 60:02d}"


def format_transcript(transcript: Transcript, start: float, end: float) -> str:
    lines = []
    for seg in transcript.segments_between(start, end):
        lines.append(f"[{_mmss(seg.start)}-{_mmss(seg.end)}] {seg.text.strip()}")
    return "\n".join(lines)


class Selector:
    name = "base"

    def select(self, transcript: Transcript, duration: float) -> list[Highlight]:  # pragma: no cover
        raise NotImplementedError


class HeuristicSelector(Selector):
    """Varre janelas deslizantes e pontua cada uma sem chamar modelo nenhum."""

    name = "heuristic"

    def __init__(self, config: Config):
        self.config = config

    def select(self, transcript: Transcript, duration: float) -> list[Highlight]:
        if not transcript.words:
            return []

        target = min(
            self.config.max_clip_seconds,
            max(self.config.min_clip_seconds, 32.0),
        )

        # Passe 1: mede cada janela. Cada segmento é uma entrada possível —
        # começar onde a fala começa evita abrir o corte no meio de uma palavra.
        windows: list[dict] = []
        for seg in transcript.segments:
            start = seg.start
            end = min(start + target, duration)
            if end - start < self.config.min_clip_seconds:
                continue
            window_words = transcript.words_between(start, end)
            if not window_words:
                continue
            minutes = (end - start) / 60.0
            text = " ".join(w.text for w in window_words)
            windows.append(
                {
                    "start": start,
                    "end": end,
                    "text": text,
                    "density": len(window_words) / (end - start),
                    "hooks_per_min": len(_HOOK_RE.findall(text)) / minutes,
                    "punct_per_min": (text.count("?") + text.count("!")) / minutes,
                    "pause_before": self._pause_before(transcript, start),
                }
            )

        if not windows:
            return []

        # Passe 2: pontua. A densidade entra relativa à mediana do próprio
        # vídeo — o que interessa é falar mais que o normal daquele streamer,
        # não falar rápido em termos absolutos.
        densities = sorted(w["density"] for w in windows)
        median_density = densities[len(densities) // 2] or 1.0

        candidates: list[Highlight] = []
        for w in windows:
            density_ratio = w["density"] / median_density
            score = (
                1.0 * min(density_ratio, 2.0)
                + 0.8 * min(w["hooks_per_min"] / 2.0, 2.0)
                + 0.4 * min(w["punct_per_min"], 2.0)
                + 0.5 * min(w["pause_before"], 1.5)
            )
            candidates.append(
                Highlight(
                    start=w["start"],
                    end=w["end"],
                    title=self._title(w["text"]),
                    score=score,
                    reason=(
                        f"densidade={density_ratio:.2f}x da mediana "
                        f"ganchos={w['hooks_per_min']:.1f}/min "
                        f"pausa={w['pause_before']:.1f}s"
                    ),
                    source="heuristic",
                )
            )
        return candidates

    @staticmethod
    def _pause_before(transcript: Transcript, start: float) -> float:
        previous_end = 0.0
        for seg in transcript.segments:
            if seg.start >= start:
                break
            previous_end = seg.end
        return max(0.0, start - previous_end)

    @staticmethod
    def _title(text: str) -> str:
        clean = " ".join(text.split())
        return (clean[:60] + "...") if len(clean) > 60 else clean


class ClaudeSelector(Selector):
    """Manda a transcrição com timestamps para o Claude e recebe os trechos."""

    name = "claude"

    OUTPUT_SCHEMA = {
        "type": "object",
        "properties": {
            "clips": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "start_seconds": {"type": "number"},
                        "end_seconds": {"type": "number"},
                        "title": {"type": "string"},
                        "score": {"type": "number"},
                        "reason": {"type": "string"},
                    },
                    "required": ["start_seconds", "end_seconds", "title", "score", "reason"],
                    "additionalProperties": False,
                },
            }
        },
        "required": ["clips"],
        "additionalProperties": False,
    }

    def __init__(self, config: Config, usage_sink: dict | None = None):
        self.config = config
        self.selector_config: SelectorConfig = config.selector
        self.usage = usage_sink if usage_sink is not None else {}

    def select(self, transcript: Transcript, duration: float) -> list[Highlight]:
        import anthropic

        client = anthropic.Anthropic()
        window = max(60.0, self.selector_config.window_minutes * 60.0)
        highlights: list[Highlight] = []

        start = 0.0
        while start < duration:
            end = min(start + window, duration)
            block = format_transcript(transcript, start, end)
            if block.strip():
                highlights.extend(self._select_block(client, block, start, end))
            start = end

        return highlights

    def _select_block(self, client, block: str, start: float, end: float) -> list[Highlight]:
        wanted = max(3, self.config.clips)
        user_prompt = (
            f"Transcrição do trecho {_mmss(start)} a {_mmss(end)} de uma gravação, "
            f"com os tempos em MM:SS medidos a partir do início do vídeo inteiro:\n\n"
            f"{block}\n\n"
            f"Escolha até {wanted} trechos para virar corte vertical. "
            f"Cada trecho deve durar entre {self.config.min_clip_seconds:.0f} e "
            f"{self.config.max_clip_seconds:.0f} segundos. "
            "Devolva start_seconds e end_seconds em segundos absolutos do vídeo inteiro, "
            "score de 0 a 10 (quanto mais alto, mais promissor), title curto em pt-BR "
            "que sirva de legenda da publicação, e reason explicando o gancho em uma frase."
        )

        response = client.messages.create(
            model=self.selector_config.model,
            max_tokens=self.selector_config.max_output_tokens,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_prompt}],
            output_config={
                "format": {"type": "json_schema", "schema": self.OUTPUT_SCHEMA},
                "effort": self.selector_config.effort,
            },
        )

        usage = getattr(response, "usage", None)
        if usage is not None:
            self.usage["input_tokens"] = self.usage.get("input_tokens", 0) + (
                usage.input_tokens or 0
            )
            self.usage["output_tokens"] = self.usage.get("output_tokens", 0) + (
                usage.output_tokens or 0
            )
            self.usage["model"] = self.selector_config.model

        if response.stop_reason == "refusal":
            details = getattr(response, "stop_details", None)
            raise RuntimeError(
                f"seleção recusada pelo modelo: {getattr(details, 'category', 'desconhecido')}"
            )

        text = next((b.text for b in response.content if b.type == "text"), "")
        if not text.strip():
            return []
        data = json.loads(text)

        out: list[Highlight] = []
        for item in data.get("clips", []):
            out.append(
                Highlight(
                    start=float(item["start_seconds"]),
                    end=float(item["end_seconds"]),
                    title=str(item["title"]).strip(),
                    # score do modelo vem de 0 a 10; normaliza para 0..1.
                    score=float(item["score"]) / 10.0,
                    reason=str(item.get("reason", "")).strip(),
                    source="claude",
                )
            )
        return out


def build_selector(config: Config, usage_sink: dict | None = None) -> Selector:
    backend = (config.selector.backend or "").strip().lower()
    if backend in ("heuristic", "none", "offline"):
        return HeuristicSelector(config)
    return ClaudeSelector(config, usage_sink=usage_sink)


def select_highlights(config: Config, transcript: Transcript, duration: float, usage_sink: dict) -> list[Highlight]:
    selector = build_selector(config, usage_sink)
    try:
        raw = selector.select(transcript, duration)
    except Exception as exc:  # rede fora, sem credencial, recusa, JSON inválido
        if selector.name == "heuristic" or not config.selector.fallback_to_heuristic:
            raise
        logger.warning("seletor %s falhou (%s); caindo na heurística", selector.name, exc)
        raw = HeuristicSelector(config).select(transcript, duration)
    return postprocess(raw, config, transcript, duration)


def postprocess(
    highlights: list[Highlight], config: Config, transcript: Transcript, duration: float
) -> list[Highlight]:
    """Ajusta limites, corta sobreposição e devolve os melhores em ordem de tempo."""
    cleaned: list[Highlight] = []
    for h in highlights:
        start, end = snap_to_speech(transcript, h.start, h.end, config)
        start = max(0.0, start - config.pad_start)
        end = min(duration, end + config.pad_end)
        if end - start < config.min_clip_seconds:
            continue
        if end - start > config.max_clip_seconds:
            end = start + config.max_clip_seconds
        cleaned.append(
            Highlight(
                start=round(start, 3),
                end=round(end, 3),
                title=h.title or "corte",
                score=h.score,
                reason=h.reason,
                source=h.source,
            )
        )

    cleaned.sort(key=lambda h: h.score, reverse=True)
    kept: list[Highlight] = []
    for cand in cleaned:
        # Conteúdo repetido entre dois cortes é defeito visível para quem
        # assiste os dois; a tolerância cobre só o padding que somamos acima.
        if any(_overlap_seconds(cand, other) > MAX_OVERLAP_SECONDS for other in kept):
            continue
        kept.append(cand)
        if len(kept) >= config.clips:
            break

    kept.sort(key=lambda h: h.start)
    return kept


def snap_to_speech(
    transcript: Transcript, start: float, end: float, config: Config
) -> tuple[float, float]:
    """Encosta os limites do corte na palavra mais próxima, sem estourar o máximo."""
    words = transcript.words
    if not words:
        return start, end

    tolerance = 1.5
    starts = [w.start for w in words if abs(w.start - start) <= tolerance]
    if starts:
        start = min(starts, key=lambda s: abs(s - start))

    ends = [w.end for w in words if abs(w.end - end) <= tolerance]
    if ends:
        end = min(ends, key=lambda e: abs(e - end))

    if end - start > config.max_clip_seconds:
        end = start + config.max_clip_seconds
    return start, end


def _overlap_seconds(a: Highlight, b: Highlight) -> float:
    return max(0.0, min(a.end, b.end) - max(a.start, b.start))
