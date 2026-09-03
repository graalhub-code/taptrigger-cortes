"""Página de revisão dos cortes de uma rodada.

O pipeline é linha de comando, mas julgar oito cortes abrindo arquivo por
arquivo no gerenciador é ruim. Esta página junta tudo numa tela só: cada corte
com player, o trecho de onde veio, a nota, o motivo da escolha e o custo da
rodada. É folha de revisão, não interface de produto — sai um HTML solto na
pasta de saída, que abre com dois cliques e funciona sem internet.
"""

from __future__ import annotations

import html
import os
from pathlib import Path

from .models import RunReport

ESTILO = """
:root { color-scheme: dark; }
* { box-sizing: border-box; }
body {
  margin: 0; padding: 32px 24px 64px;
  background: #0f1216; color: #e7e9ee;
  font: 15px/1.5 system-ui, -apple-system, "Segoe UI", Roboto, sans-serif;
}
.wrap { max-width: 1200px; margin: 0 auto; }
h1 { font-size: 22px; margin: 0 0 4px; letter-spacing: -0.01em; }
.fonte { color: #8b93a7; font-size: 13px; margin-bottom: 24px; word-break: break-all; }
.resumo {
  display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
  gap: 1px; background: #232833; border: 1px solid #232833;
  border-radius: 10px; overflow: hidden; margin-bottom: 32px;
}
.resumo div { background: #151a21; padding: 14px 16px; }
.resumo dt { color: #8b93a7; font-size: 11px; text-transform: uppercase;
  letter-spacing: 0.06em; margin-bottom: 4px; }
.resumo dd { margin: 0; font-size: 19px; font-variant-numeric: tabular-nums; }
.resumo dd small { font-size: 12px; color: #8b93a7; font-weight: normal; }
.grade { display: grid; grid-template-columns: repeat(auto-fill, minmax(260px, 1fr)); gap: 24px; }
.corte { background: #151a21; border: 1px solid #232833; border-radius: 12px; overflow: hidden; }
.corte video { width: 100%; display: block; background: #000; aspect-ratio: 9 / 16; }
.corpo { padding: 14px 16px 16px; }
.titulo { font-weight: 600; margin: 0 0 8px; font-size: 15px; }
.meta { display: flex; flex-wrap: wrap; gap: 6px; margin-bottom: 10px; }
.chip { font-size: 11px; padding: 3px 8px; border-radius: 999px;
  background: #1e2530; color: #9aa4b8; font-variant-numeric: tabular-nums; }
.chip.tempo { background: #1b2b3a; color: #8ec7f0; }
.barra { height: 4px; background: #232833; border-radius: 2px; overflow: hidden; margin-bottom: 10px; }
.barra i { display: block; height: 100%; background: #e8973a; }
.motivo { color: #9aa4b8; font-size: 13px; margin: 0; }
.vazio { color: #8b93a7; }
footer { margin-top: 40px; color: #6b7385; font-size: 12px; }
"""


def _mmss(segundos: float) -> str:
    total = int(segundos)
    return f"{total // 60:02d}:{total % 60:02d}"


def _cartao(clip, out_dir: Path, melhor_nota: float) -> str:
    # O fragmento #t= faz o navegador buscar esse instante e mostrar o quadro
    # como miniatura; sem ele o player fica preto até alguém clicar.
    destino = os.path.relpath(clip.path, out_dir).replace(os.sep, "/") + "#t=1"
    h = clip.highlight
    largura = int(100 * h.score / melhor_nota) if melhor_nota > 0 else 0
    poster = ""
    if clip.poster:
        caminho = os.path.relpath(clip.poster, out_dir).replace(os.sep, "/")
        poster = f' poster="{html.escape(caminho, quote=True)}"'

    partes = [
        '<article class="corte">',
        f'<video src="{html.escape(destino, quote=True)}"{poster} controls preload="metadata"></video>',
        '<div class="corpo">',
        f'<p class="titulo">{clip.index:02d}. {html.escape(h.title)}</p>',
        '<div class="meta">',
        f'<span class="chip tempo">{_mmss(h.start)} → {_mmss(h.end)}</span>',
        f'<span class="chip">{h.duration:.0f}s</span>',
        f'<span class="chip">nota {h.score:.2f}</span>',
        f'<span class="chip">{html.escape(clip.crop_backend)}</span>',
        f'<span class="chip">{clip.caption_count} legendas</span>',
        "</div>",
        f'<div class="barra"><i style="width:{largura}%"></i></div>',
    ]
    if h.reason:
        partes.append(f'<p class="motivo">{html.escape(h.reason)}</p>')
    partes.append("</div></article>")
    return "".join(partes)


def _celula(rotulo: str, valor: str, nota: str = "") -> str:
    extra = f" <small>{html.escape(nota)}</small>" if nota else ""
    return f"<div><dt>{html.escape(rotulo)}</dt><dd>{html.escape(valor)}{extra}</dd></div>"


def build_review(report: RunReport, out_dir: Path) -> Path:
    tempo = report.cost.get("tempo", {})
    brl = report.cost.get("custo_brl", {})
    melhor_nota = max((c.highlight.score for c in report.clips), default=0.0)

    resumo = "".join(
        [
            _celula("Cortes", str(len(report.clips))),
            _celula("Duração da fonte", _mmss(report.source_duration)),
            _celula(
                "Processamento",
                f"{tempo.get('processamento_s', 0):.0f}s",
                f"{tempo.get('fator_tempo_real', 0):.2f}x tempo real",
            ),
            _celula("Custo da rodada", f"R$ {brl.get('total', 0):.4f}"),
            _celula("Por minuto de vídeo", f"R$ {brl.get('por_minuto_de_video', 0):.4f}"),
            _celula("Por hora de vídeo", f"R$ {brl.get('por_hora_de_video', 0):.2f}"),
        ]
    )

    if report.clips:
        corpo = '<div class="grade">' + "".join(
            _cartao(c, out_dir, melhor_nota) for c in report.clips
        ) + "</div>"
    else:
        corpo = '<p class="vazio">Nenhum trecho passou nos critérios desta rodada.</p>'

    modelo = report.llm_model or "heurística local"
    documento = (
        "<!doctype html><html lang='pt-BR'><head><meta charset='utf-8'>"
        "<meta name='viewport' content='width=device-width, initial-scale=1'>"
        "<title>Revisão dos cortes</title>"
        f"<style>{ESTILO}</style></head><body><div class='wrap'>"
        "<h1>Revisão dos cortes</h1>"
        f"<p class='fonte'>{html.escape(report.source)}</p>"
        f"<dl class='resumo'>{resumo}</dl>"
        f"{corpo}"
        f"<footer>Seleção por {html.escape(modelo)} · "
        f"{report.llm_input_tokens + report.llm_output_tokens} tokens · "
        "números completos em report.json</footer>"
        "</div></body></html>"
    )

    destino = out_dir / "revisao.html"
    destino.write_text(documento, encoding="utf-8")
    return destino
