"""HTML das telas do serviço: envio, acompanhamento e erro.

Página de resultado não está aqui: quando o job termina, quem responde é o
próprio ``revisao.html`` que o pipeline já gera, servido do diretório do job.
Os caminhos relativos dele (``clips/...``, ``thumbs/...``) casam com as rotas
do servidor, então não há duplicação de tela.
"""

from __future__ import annotations

import html

ESTILO = """
:root { color-scheme: dark; }
* { box-sizing: border-box; }
body {
  margin: 0; padding: 40px 24px 64px; background: #0f1216; color: #e7e9ee;
  font: 15px/1.6 system-ui, -apple-system, "Segoe UI", Roboto, sans-serif;
}
.wrap { max-width: 640px; margin: 0 auto; }
h1 { font-size: 24px; margin: 0 0 6px; letter-spacing: -0.01em; }
.sub { color: #8b93a7; margin: 0 0 28px; }
form, .cartao {
  background: #151a21; border: 1px solid #232833; border-radius: 12px; padding: 22px;
}
label { display: block; font-size: 13px; color: #9aa4b8; margin: 16px 0 6px; }
label:first-of-type { margin-top: 0; }
input[type=file], select, input[type=number] {
  width: 100%; padding: 10px 12px; border-radius: 8px;
  border: 1px solid #2b323f; background: #0f1216; color: #e7e9ee; font: inherit;
}
input[type=file] { padding: 10px; }
.linha { display: grid; grid-template-columns: 1fr 1fr; gap: 14px; }
button {
  margin-top: 22px; width: 100%; padding: 13px; border: 0; border-radius: 8px;
  background: #e8973a; color: #14181e; font: 600 15px system-ui; cursor: pointer;
}
button:hover { background: #f2a651; }
button:disabled { opacity: 0.6; cursor: progress; }
.dica { color: #6b7385; font-size: 12px; margin-top: 10px; }
.estado { font-size: 19px; margin: 0 0 6px; }
.barra { height: 6px; background: #232833; border-radius: 3px; overflow: hidden; margin: 18px 0 10px; }
.barra i { display: block; height: 100%; background: #e8973a; transition: width .4s; }
.passos { list-style: none; padding: 0; margin: 18px 0 0; }
.passos li { padding: 7px 0; color: #6b7385; border-top: 1px solid #1c222c; }
.passos li.feito { color: #9aa4b8; }
.passos li.atual { color: #e8973a; font-weight: 600; }
.erro { color: #f0857d; background: #2a1a1c; border: 1px solid #452327;
  border-radius: 8px; padding: 14px; margin-top: 16px; font-size: 13px;
  white-space: pre-wrap; word-break: break-word; }
a { color: #8ec7f0; }
footer { margin-top: 28px; color: #6b7385; font-size: 12px; }
"""

PASSOS = [
    ("analisando", "Lendo o vídeo"),
    ("audio", "Extraindo o áudio"),
    ("transcricao", "Transcrevendo a fala"),
    ("selecao", "Escolhendo os trechos"),
    ("render", "Montando os cortes"),
    ("pronto", "Pronto"),
]


def _documento(titulo: str, corpo: str, refresh: int | None = None) -> str:
    meta_refresh = f"<meta http-equiv='refresh' content='{refresh}'>" if refresh else ""
    return (
        "<!doctype html><html lang='pt-BR'><head><meta charset='utf-8'>"
        "<meta name='viewport' content='width=device-width, initial-scale=1'>"
        f"{meta_refresh}<title>{html.escape(titulo)}</title>"
        f"<style>{ESTILO}</style></head><body><div class='wrap'>{corpo}</div></body></html>"
    )


def pagina_envio(limite_mb: int, aviso: str = "") -> str:
    bloco_aviso = f"<div class='erro'>{html.escape(aviso)}</div>" if aviso else ""
    corpo = f"""
<h1>Cortes automáticos</h1>
<p class="sub">Envie uma gravação e receba cortes verticais com legenda.</p>
<form method="post" action="/jobs" enctype="multipart/form-data"
      onsubmit="this.querySelector('button').disabled=true;
                this.querySelector('button').textContent='Enviando o arquivo...';">
  {bloco_aviso}
  <label for="video">Arquivo de vídeo (até {limite_mb} MB)</label>
  <input id="video" type="file" name="video" accept="video/*" required>

  <div class="linha">
    <div>
      <label for="clips">Quantos cortes</label>
      <input id="clips" type="number" name="clips" value="6" min="1" max="30">
    </div>
    <div>
      <label for="whisper_model">Qualidade da transcrição</label>
      <select id="whisper_model" name="whisper_model">
        <option value="small" selected>Rápida (small)</option>
        <option value="medium">Melhor (medium, mais lento)</option>
        <option value="tiny">Só para testar (tiny)</option>
      </select>
    </div>
  </div>

  <div class="linha">
    <div>
      <label for="selector">Quem escolhe os trechos</label>
      <select id="selector" name="selector">
        <option value="claude" selected>Claude lê a transcrição</option>
        <option value="heuristic">Heurística local (sem custo)</option>
      </select>
    </div>
    <div>
      <label for="reframe">Enquadramento</label>
      <select id="reframe" name="reframe">
        <option value="auto" selected>Automático</option>
        <option value="face">Seguir rosto</option>
        <option value="motion">Seguir movimento</option>
        <option value="center">Centro fixo</option>
      </select>
    </div>
  </div>

  <button type="submit">Enviar e processar</button>
  <p class="dica">Comece com 5 a 10 minutos de vídeo. O processamento roda em
  CPU e leva mais tempo do que a duração do vídeo.</p>
</form>
<footer><a href="/jobs">Ver processamentos anteriores</a></footer>
"""
    return _documento("Cortes automáticos", corpo)


def pagina_progresso(job, posicao_na_fila: int) -> str:
    indice = next((i for i, (chave, _) in enumerate(PASSOS) if chave == job.etapa), 0)
    percentual = int(100 * indice / (len(PASSOS) - 1)) if job.etapa else 4

    itens = []
    for i, (_, rotulo) in enumerate(PASSOS[:-1]):
        classe = "feito" if i < indice else ("atual" if i == indice else "")
        itens.append(f"<li class='{classe}'>{html.escape(rotulo)}</li>")

    espera = ""
    if posicao_na_fila > 0:
        espera = f"<p class='dica'>{posicao_na_fila} job(s) na sua frente na fila.</p>"

    corpo = f"""
<h1>Processando</h1>
<p class="sub">{html.escape(job.nome_original)}</p>
<div class="cartao">
  <p class="estado">{html.escape(job.descricao)}</p>
  <div class="barra"><i style="width:{percentual}%"></i></div>
  <ul class="passos">{''.join(itens)}</ul>
  {espera}
  <p class="dica">Esta página se atualiza sozinha. Pode fechar e voltar depois —
  o endereço continua valendo.</p>
</div>
<footer><a href="/">Enviar outro vídeo</a></footer>
"""
    return _documento("Processando", corpo, refresh=5)


def pagina_erro(job) -> str:
    corpo = f"""
<h1>Não deu certo</h1>
<p class="sub">{html.escape(job.nome_original)}</p>
<div class="cartao">
  <p class="estado">{html.escape(job.descricao)}</p>
  <div class="erro">{html.escape(job.erro or 'sem detalhe')}</div>
</div>
<footer><a href="/">Tentar de novo</a></footer>
"""
    return _documento("Falhou", corpo)


def pagina_lista(jobs) -> str:
    if not jobs:
        linhas = "<p class='sub'>Nenhum processamento ainda.</p>"
    else:
        itens = []
        for job in jobs:
            rotulo = {"pronto": "✓", "falhou": "✕", "processando": "•", "pendente": "•"}.get(
                job.estado, "•"
            )
            itens.append(
                f"<li class='feito'><a href='/jobs/{html.escape(job.id)}/'>{rotulo} "
                f"{html.escape(job.nome_original)}</a> — {html.escape(job.descricao)}</li>"
            )
        linhas = f"<ul class='passos'>{''.join(itens)}</ul>"
    corpo = f"""
<h1>Processamentos</h1>
<div class="cartao">{linhas}</div>
<footer><a href="/">Enviar um vídeo</a></footer>
"""
    return _documento("Processamentos", corpo)
