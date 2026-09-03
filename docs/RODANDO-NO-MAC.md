# Rodando o teste no Mac

Antes de tudo, um esclarecimento que evita frustração: **não há nada online
para abrir ainda**. Não existe endereço, login nem site. O `revisao.html` é um
arquivo que só passa a existir depois que o pipeline roda na sua máquina —
abrir o Chrome antes disso não mostra nada.

A sequência é: Terminal roda o pipeline → sai uma pasta com os cortes →
você abre o `revisao.html` dessa pasta no Chrome.

## 1. Instalar o que falta (uma vez só)

Abra o **Terminal** (Spotlight com `⌘ + espaço`, digite "Terminal").

Se você ainda não tem o Homebrew:

```bash
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
```

Depois:

```bash
brew install ffmpeg python git
```

O `ffmpeg` é o que corta e renderiza vídeo; sem ele nada funciona.

## 2. Baixar o projeto e instalar

```bash
cd ~/Documents
git clone https://github.com/graalhub-code/taptrigger-cortes.git
cd taptrigger-cortes
git checkout claude/new-session-16ussk

python3 -m venv .venv
source .venv/bin/activate
pip install -e '.[all,dev]'
cortes fetch-models
```

O `source .venv/bin/activate` precisa ser repetido toda vez que você abrir um
Terminal novo — é o que faz o comando `cortes` existir naquela janela. Você
sabe que funcionou quando aparece `(.venv)` no começo da linha.

Para confirmar que está tudo de pé:

```bash
pytest
```

Devem passar 73 testes, em menos de um minuto.

## 3. Preparar a gravação

Comece por um pedaço curto, não pela live inteira. A transcrição roda na CPU
do Mac e é a etapa lenta: dez minutos de vídeo servem para julgar qualidade e
levam poucos minutos, enquanto três horas levariam a tarde toda.

```bash
# Corta os primeiros 10 minutos sem reencodar (é instantâneo)
ffmpeg -ss 0 -t 600 -i ~/Desktop/live.mp4 -c copy ~/Desktop/trecho.mp4
```

## 4. Rodar

```bash
cortes run ~/Desktop/trecho.mp4 -o ~/Desktop/cortes-teste --selector heuristic --whisper-model small
```

O que cada parte faz:

- `--selector heuristic` escolhe os trechos sem chamar a API, então esta
  primeira rodada não gasta nada. Para usar o Claude na seleção, exporte
  `ANTHROPIC_API_KEY` e troque para `--selector claude`.
- `--whisper-model small` é o modelo de transcrição mais rápido que ainda
  presta em português. Depois vale repetir com `medium` e comparar a legenda.
- Na primeira vez o modelo de transcrição é baixado (algumas centenas de MB) —
  isso acontece uma vez só.

## 5. Ver o resultado

```bash
open ~/Desktop/cortes-teste/revisao.html
```

Abre no Chrome com os cortes lado a lado: player, o trecho de onde cada um
veio, a nota e o custo da rodada. Os MP4 estão em
`~/Desktop/cortes-teste/clips/` e tocam em qualquer player.

## 6. Iterar barato

Rodar de novo na **mesma pasta de saída** reaproveita a transcrição, que é a
parte cara. Então dá para mexer em enquadramento e legenda quantas vezes
quiser sem esperar tudo de novo:

```bash
cortes run ~/Desktop/trecho.mp4 -o ~/Desktop/cortes-teste --selector heuristic -n 12
cortes run ~/Desktop/trecho.mp4 -o ~/Desktop/cortes-teste --selector heuristic --reframe center
CORTES_CAPTION_FONT_SIZE=110 cortes run ~/Desktop/trecho.mp4 -o ~/Desktop/cortes-teste --selector heuristic
```

Para forçar tudo do zero, use `--no-reuse`.

## O que observar durante o teste

Este é o objetivo da rodada — não é só ver se roda:

1. **Os trechos escolhidos prestam?** Abriria com esse gancho? O corte termina
   num remate ou no meio de uma frase?
2. **O enquadramento acompanha você?** O card mostra qual detector foi usado
   (`face`, `motion` ou `center`). Se aparecer `center` numa cena com o seu
   rosto na tela, a detecção falhou e vale investigar.
3. **A legenda erra palavra?** É o que decide entre `small` e `medium`.
4. **Quanto custou?** O topo da página mostra R$/minuto. Esse é o número que
   entra na conta dos planos — mas atenção: no Mac ele reflete o custo da sua
   CPU, não o da GPU alugada. A medição que vale para preço está em
   [CUSTOS.md](CUSTOS.md).

## Se der errado

| Sintoma | Causa provável |
|---|---|
| `command not found: cortes` | faltou `source .venv/bin/activate` nesta janela |
| `ffmpeg não encontrado no PATH` | faltou `brew install ffmpeg` |
| `nenhum trecho passou nos critérios` | vídeo curto demais para o mínimo de duração; use `-n 3 --min-clip 10` ou um trecho maior |
| players pretos no Chrome | miniatura não gerou; os MP4 em `clips/` continuam bons |
| transcrição demorando muito | use `--whisper-model small` e um trecho de 10 min |
