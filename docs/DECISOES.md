# Decisões

Respostas às perguntas em aberto do brief (§7) e registro do que foi decidido
ao construir o protótipo. Onde a decisão não é minha, está marcado como
pendente e com o que falta para resolver.

## 1. Usar um dos projetos open-source como base, ou construir enxuto?

**Decidido: construir enxuto, olhando os três só como referência.**

`AI-Youtube-Shorts-Generator`, `openshorts` e `autoclip` fazem a mesma
sequência que este repositório faz — Whisper para transcrever, um LLM para
escolher, ffmpeg para cortar. A diferença entre eles e este pipeline não está
na arquitetura, está no ajuste: o que conta como bom trecho, como a câmera se
move, como a legenda quebra. Adotar a base de um deles traria dependências,
licença e decisões de outra pessoa sem economizar a parte que dá trabalho.

O pipeline inteiro tem cerca de mil linhas. O que vale copiar dos três é
comparar resultado com o mesmo vídeo, não herdar código.

## 2. Qual provedor de GPU sob demanda?

**Pendente — depende de abrir conta e colocar cartão, decisão do JP.**

Recomendação: começar pela **RunPod**. Cobra por segundo, tem imagem pronta
com CUDA e a instância sobe em menos de um minuto, o que importa porque o
tempo de provisionamento é custo que não aparece no processamento. A
**Vast.ai** costuma sair mais barata por hora, mas é marketplace de máquina de
terceiro: disponibilidade e desempenho variam, e isso atrapalha justamente uma
primeira medição, que precisa ser comparável.

Sugestão concreta: medir na RunPod primeiro para ter um número confiável, e só
depois comparar o mesmo vídeo na Vast.ai para ver quanto de margem a diferença
de preço traz. O procedimento está em [CUSTOS.md](CUSTOS.md).

## 3. Tem vídeo real de streamer, com autorização, para testar?

**Pendente — é a pergunta que mais trava a validação de qualidade.**

Todo o pipeline foi verificado com material sintético, o que basta para
mecânica (dimensão, corte, pan, legenda, custo) e não basta para nada de
qualidade: se o trecho escolhido é bom, se a câmera acompanha o rosto de
verdade, se a legenda erra palavra. Enquanto não houver gravação real, esses
três pontos seguem sem resposta.

O que já existe para não ficar parado: `scripts/make_sample_video.py` (objeto
em movimento, para o rastreio) e `scripts/make_speech_sample.py` (fala em
português sintetizada com espeak-ng, com transcrição alinhada, para a seleção
e a legenda).

O ideal seria uma gravação de OBS de 30 a 60 minutos, com o streamer visível
em parte dela — porque é o pior caso do reenquadramento.

## 4. Marca própria desde já?

**Recomendação: não agora.**

Nome público é decisão de posicionamento, e posicionamento depende do preço,
que depende do custo medido. Enquanto não há esse número, batizar o produto só
antecipa trabalho (domínio, identidade) sobre uma coisa que pode não sair.

O que precisa ser decidido já, e não é o nome, é o **identificador de conta**:
se este produto ganhar cadastro, a chave tem de ser o par
`(plataforma, id_na_plataforma)` do Kick/Twitch, o mesmo que o TapTrigger usa
hoje. Com isso, juntar os dois depois é migração de tabela; com e-mail próprio,
vira reconciliação de identidade. Detalhes em
[ARQUITETURA.md](ARQUITETURA.md#integração-futura-com-o-taptrigger).

## 5. Orçamento para o primeiro teste de GPU?

**R$ 20 a R$ 50 é o suficiente**, e sobra.

Ordem de grandeza: uma GPU de gama média em provedor por segundo custa algo
entre US$ 0,20 e US$ 0,50 por hora. A medição descrita em CUSTOS.md — três
tamanhos de modelo sobre uma gravação de uma hora, mais as repetições que
sempre são necessárias — cabe em poucas horas de máquina. O risco de estourar
não está no preço da hora, está em esquecer a instância ligada; vale conferir
que ela foi derrubada ao fim de cada teste.

---

## Decisões tomadas ao construir

Registradas porque mudam o comportamento do produto e alguém vai querer saber
por quê.

**Claude escolhe os trechos, com heurística como linha de base.** O LLM lê a
transcrição com timestamps e devolve JSON validado por schema. A heurística
local (densidade de fala relativa à mediana do vídeo, ganchos, pausa) existe
por três motivos: é o fallback quando a API falha, é o modo sem custo para
iterar no resto do pipeline, e é a régua para responder se o LLM está valendo
o que custa. Sem essa régua não dá para saber.

**YuNet em vez de Haar ou MediaPipe.** O Haar saiu do OpenCV 5 e sempre foi
ruim de falso positivo. O MediaPipe traria uma dependência grande para uma
etapa que precisa ser leve. O YuNet tem 230 KB, roda em CPU e é o detector que
o próprio OpenCV entrega hoje. Fica fora do repositório e é baixado por
`cortes fetch-models`.

**Rastreio por movimento como segunda opção, não só centro.** Boa parte do
material de streamer é gameplay sem rosto na tela. Travar no centro nesse caso
é desperdiçar a única decisão interessante do reenquadramento. Os dois
detectores rodam no mesmo passe de decodificação e a escolha é feita depois,
olhando quem realmente achou alvo.

**Sobreposição entre cortes limitada a 1,5 s.** Dois cortes que dividem trinta
segundos de conteúdo são um defeito visível para quem assiste os dois. A
tolerância cobre só o padding aplicado nas bordas.

**Legenda em ASS, não SRT.** Fonte grande, contorno grosso e posição fixa no
terço inferior não cabem em SRT.

**Preços de custo vêm do ambiente, e ficam gravados no relatório.** Um número
de custo sem a tabela de preços que o gerou não dá para comparar entre
rodadas.

## O que segue sem decisão, e por quê

- **Os dois planos e seus preços.** Dependem do custo medido. O rascunho do
  brief (um plano intermediário e um completo, separados por volume de minutos)
  continua de pé, e o achado de que a referência separa os planos por volume e
  não por recurso sustenta essa forma.
- **Política de retenção de arquivo.** Muda o custo mais do que o
  processamento. Precisa ser decidida antes de fechar preço.
- **Monitoramento de live ao vivo**, como o "Live Monitoring" da referência.
  É outro produto em cima deste; não faz sentido discutir antes de o caminho
  do upload funcionar.
