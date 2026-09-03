# Cortes automáticos

Pega uma gravação longa (live, podcast, gameplay) e devolve vários cortes
verticais 9:16 com legenda queimada, prontos para TikTok/Reels/Shorts.

Isto é o protótipo do passo 1 do brief: pipeline mínimo rodando ponta a ponta,
com o custo de cada etapa medido, para decidir com número na mão se vale
seguir. **Não é produto**: não tem painel, não tem fila, não tem cobrança.

## Como funciona

```
vídeo longo
   │
   ├─ ffmpeg extrai áudio 16 kHz mono
   ├─ transcrição com timestamp por palavra      ← única etapa que pede GPU
   ├─ seleção dos trechos (Claude lê a transcrição, ou heurística local)
   ├─ para cada trecho:
   │     ├─ rastreio do assunto → caminho de câmera suavizado
   │     ├─ legenda ASS a partir das palavras do trecho
   │     └─ ffmpeg: corta, recorta seguindo a câmera, escala 1080x1920, queima legenda
   └─ report.json com tempo e custo por minuto de vídeo
```

Detalhes de cada etapa e onde ela roda: [docs/ARQUITETURA.md](docs/ARQUITETURA.md).

## Instalação

```bash
sudo apt-get install -y ffmpeg
python3 -m venv .venv && . .venv/bin/activate
pip install -e '.[all,dev]'
cortes fetch-models          # detector de rosto (~230 KB), opcional mas recomendado
```

## Uso

```bash
# Rodada completa: transcreve, escolhe com o Claude, renderiza 8 cortes
export ANTHROPIC_API_KEY=...
cortes run gravacao.mp4 -o ./saida

# Sem rede e sem custo de API: transcreve local e escolhe pela heurística
cortes run gravacao.mp4 --selector heuristic

# Já tem a transcrição pronta (de outra ferramenta ou de uma rodada anterior)
cortes run gravacao.mp4 --transcript transcript.json

# Só ver o que tem no arquivo
cortes probe gravacao.mp4
```

Saída:

```
saida/
├── clips/01-o-plot-twist-da-live.mp4   ← 1080x1920, legenda queimada
├── report.json                          ← tempo por etapa e custo por minuto
├── config-usado.json
└── work/                                ← transcript, planos de recorte, .ass
```

`work/` existe para não repagar o caro: rodar de novo no mesmo diretório
reaproveita a transcrição, então dá para iterar em legenda e enquadramento de
graça. `--no-reuse` força refazer tudo.

## Opções que importam

| Flag | O que muda |
|---|---|
| `-n, --clips` | quantos cortes gerar (padrão 8) |
| `--selector claude\|heuristic` | quem escolhe os trechos |
| `--transcriber faster-whisper\|fake` | `fake` usa transcrição pronta, não roda modelo |
| `--whisper-model tiny…large-v3` | tamanho do modelo (padrão `medium`) |
| `--reframe auto\|face\|motion\|center` | como o recorte segue o assunto |
| `--transcript ARQUIVO` | usa uma transcrição pronta |
| `--no-captions` | não queima legenda |

Tudo também sai por variável de ambiente com prefixo `CORTES_` — a lista
completa está em [`cortes/config.py`](cortes/config.py). É assim que a mesma
imagem roda na VPS (etapas leves) e na GPU alugada (transcrição), só trocando
o ambiente.

`--reframe auto` roda rosto e movimento no mesmo passe e escolhe depois: se
achou rosto em pelo menos 20% das amostras usa o rosto, senão segue o
movimento (caso do gameplay), senão trava no centro.

## Custo

Cada rodada escreve em `report.json` quanto tempo passou em GPU e em CPU,
quantos tokens o seletor gastou, e converte isso em R$/minuto de vídeo usando
os preços de `CORTES_GPU_BRL_HOUR`, `CORTES_USD_BRL` e afins. Os preços padrão
são chute; o ponto do relatório é justamente substituí-los pelo medido na
máquina que for contratada. Como medir: [docs/CUSTOS.md](docs/CUSTOS.md).

## Testes

```bash
pytest
```

64 testes. Os de ponta a ponta geram um vídeo com o ffmpeg, rodam o pipeline
inteiro e conferem dimensão, duração, sobreposição e relatório — levam ~45 s.

## O que já foi verificado rodando, e o que não

Verificado neste repositório:

- corte, recorte 9:16, escala e reencode saindo em 1080x1920 com a duração certa;
- pan dinâmico do recorte (keyframes via `sendcmd` do ffmpeg) acompanhando um
  assunto em movimento, sem o assunto sair do quadro;
- legenda queimada com acentuação correta, quebrada em blocos de 2 a 4 palavras;
- seleção heurística escolhendo o trecho com mais gancho num texto pt-BR real;
- fallback do seletor quando a chamada ao Claude falha;
- contabilidade de custo e reaproveitamento da transcrição entre rodadas.

**Não** verificado rodando (o ambiente de desenvolvimento não tinha como):

- **transcrição real com faster-whisper** — o download do modelo estava
  bloqueado. O código segue a API da biblioteca, mas ainda não rodou; é a
  primeira coisa a validar na máquina com GPU.
- **detecção de rosto em imagem real** — o modelo YuNet carrega, mas só foi
  exercitado com material sintético, onde ele corretamente não acha rosto.
- **seleção pelo Claude contra a API real** — não havia credencial. O formato
  da requisição e o parsing da resposta estão cobertos por teste com cliente
  falso; falta a chamada de verdade.

Os três dependem só de ambiente, não de código novo.
