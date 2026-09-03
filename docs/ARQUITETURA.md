# Arquitetura

## Princípio que organiza tudo

Só uma etapa do pipeline precisa de GPU: a transcrição. Todo o resto —
extração de áudio, rastreio do assunto, legenda, corte e reencode — roda em
CPU comum. Separar as duas coisas é o que permite não ter investimento fixo:
a máquina barata fica ligada o tempo todo segurando fila e render, e a GPU é
alugada por segundo só enquanto transcreve.

Por isso cada estágio declara em que hardware roda (`CostTracker.stage(nome,
"gpu"|"cpu")`) e cada backend é trocável por variável de ambiente. A mesma
imagem sobe nos dois lugares.

## Estágios

| Estágio | Módulo | Hardware | Backends |
|---|---|---|---|
| Metadados | `cortes/ffmpeg.py` | CPU | ffprobe |
| Extração de áudio | `cortes/ffmpeg.py` | CPU | ffmpeg (16 kHz mono PCM) |
| Transcrição | `stages/transcribe.py` | **GPU** | `faster-whisper`, `fake` (sidecar) |
| Seleção de trechos | `stages/highlights.py` | rede | `claude`, `heuristic` |
| Rastreio / recorte | `stages/reframe.py` | CPU | `face` (YuNet), `motion`, `center` |
| Legenda | `stages/subtitles.py` | CPU | ASS |
| Render | `stages/render.py` | CPU | ffmpeg + libx264 |

### Transcrição

`faster-whisper` com `word_timestamps=True` e `vad_filter=True`. O timestamp
por palavra não é luxo: é ele que permite encostar o corte no início de uma
palavra (em vez de decepar a fala) e sincronizar a legenda.

O resultado vira `work/transcript.json` e é reaproveitado entre rodadas. Como
é a etapa cara, tudo que vem depois pode ser iterado de graça.

### Seleção de trechos

Dois backends com a mesma saída, o que permite comparar um contra o outro:

- **`claude`** — manda blocos de 20 minutos de transcrição com timestamps e
  pede de volta JSON validado por schema (`output_config.format`), com início,
  fim, título, nota e justificativa. Modelo em `CORTES_CLAUDE_MODEL`
  (padrão `claude-opus-5`), esforço em `CORTES_CLAUDE_EFFORT`.
- **`heuristic`** — pontua janelas por densidade de fala **relativa à mediana
  do próprio vídeo**, ganchos por minuto, pontuação e pausa antes do trecho.
  Sem rede e sem custo. É o fallback quando a API falha e a linha de base para
  responder se o LLM está valendo o que custa.

Depois vem um pós-processamento comum aos dois: encosta os limites na palavra
mais próxima, aplica o padding, respeita mínimo e máximo de duração, rejeita
trechos que se sobrepõem por mais de 1,5 s (conteúdo repetido entre dois
cortes é defeito visível) e corta no número de cortes pedido.

### Rastreio e recorte vertical

De um 16:9 cabe um 9:16 de `altura × 9/16` de largura — sobra uma faixa
horizontal para escolher. O rastreio decide onde essa janela fica a cada
instante.

Amostra 3 quadros por segundo (`CORTES_REFRAME_SAMPLE_FPS`), em versão
reduzida para 480 px de largura. Dois detectores rodam no mesmo passe de
decodificação:

- **rosto**: YuNet (DNN do OpenCV, ~230 KB, roda em CPU), maior rosto do quadro;
- **movimento**: maior componente conectado da diferença entre quadros
  consecutivos. Usa a maior região, e não o centroide de tudo que se mexeu,
  porque cronômetro, alerta e chat na tela piscam sozinhos e puxariam a câmera
  para o canto.

Escolhe-se o rosto se ele apareceu em pelo menos 20% das amostras; senão o
movimento; senão centro fixo.

O caminho cru vira caminho de câmera com três freios, nesta ordem:

1. **zona morta** (8% da largura do recorte) — ignora tremida pequena;
2. **suavização exponencial** com constante de tempo em segundos
   (`CORTES_REFRAME_TAU`, padrão 0,6 s) — em segundos, e não por amostra, para
   que mudar a taxa de amostragem não mude o comportamento do pan;
3. **limite de velocidade** (60% da largura do recorte por segundo) — impede
   chicote quando a detecção pula de um alvo para outro.

O caminho vira keyframes aplicados pelo `sendcmd` do ffmpeg no filtro `crop`.

> Armadilha achada aqui, que vale registrar: amostrar com
> `VideoCapture.set(CAP_PROP_POS_MSEC)` parece o jeito barato, mas o OpenCV
> encosta a busca no keyframe anterior — com GOP de vários segundos, amostras
> seguidas caem no mesmo quadro e a diferença entre elas dá zero. O código lê
> em sequência e descarta com `grab()`.

### Legenda

ASS, não SRT: o corte precisa de fonte grande, contorno grosso e posição fixa
no terço inferior, e o SRT não carrega nada disso. As palavras viram blocos de
até 4 palavras / 28 caracteres / 1,6 s, quebrando também em pausa acima de
0,65 s. Os tempos são relativos ao corte.

### Render

Um passe de ffmpeg por corte:

```
setpts=PTS-STARTPTS, sendcmd=f=cmds, crop=W:H:x:y, scale=1080:1920, setsar=1, ass=legenda.ass
```

libx264 `veryfast` CRF 21, áudio AAC 128k, `+faststart`.

## O que falta para virar produto

Nada disto está escrito ainda — é o desenho proposto, não código existente.

### Fila

Processar vídeo é assíncrono por natureza e não cabe no fluxo síncrono do
TapTrigger. O mínimo que funciona: tabela `jobs` (id, conta, arquivo, estado,
tentativas, resultado) e um worker que pega um job por vez. Estados:
`recebido → transcrevendo → selecionando → renderizando → pronto | falhou`.

Vale um detalhe de custo: os jobs devem ser agrupados por leva antes de subir
GPU. Alugar GPU por segundo só compensa se ela transcrever várias gravações
seguidas e for liberada — subir e descer máquina para um vídeo só paga mais em
provisionamento do que em processamento.

### GPU sob demanda

O worker de transcrição é o único que precisa da GPU. Fluxo: acumula jobs →
sobe instância (Vast.ai/RunPod) → roda `cortes` com
`CORTES_TRANSCRIBER=faster-whisper` em cada um → devolve os `transcript.json`
→ derruba a instância. As demais etapas seguem na máquina barata.

### Armazenamento

Gravação de live é arquivo grande. O plano de retenção precisa ser decidido
antes do produto existir, porque muda o custo: guardar o vídeo original por 60
dias é caro, guardar só os cortes é barato. Sugestão de partida: original
apagado assim que os cortes saem, cortes retidos conforme o plano.

## Integração futura com o TapTrigger

O brief pede para não fechar portas. Duas portas, e o que basta fazer para
mantê-las abertas:

- **Login único.** O TapTrigger identifica o streamer pela conta Kick/Twitch
  (tabela `accounts`, campos `kick_user_id` / `twitch_user_id`). Quando este
  produto ganhar cadastro, a chave da conta deve ser esse mesmo par
  `(plataforma, id_na_plataforma)` — não um e-mail próprio. Assim juntar os
  dois depois é uma migração de tabela, não uma reconciliação de identidades.
- **Cobrança combinada.** Nada a fazer agora além de manter a contagem de uso
  em minutos processados por conta, que é a unidade em que qualquer plano
  futuro vai ser expresso.

O que **não** deve ser herdado: SQLite com escrita síncrona na VPS única não
aguenta fila de vídeo, e a VPS atual (`E2.1.Micro`, ~500 MB de RAM) não roda
nem as etapas leves. Este produto precisa de infraestrutura própria desde o
começo.
