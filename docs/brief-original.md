# Cortes Automáticos de Vídeo — Brief completo (produto novo, separado do TapTrigger por enquanto)

**Data**: 03/09/2026
**Status**: só pesquisa e planejamento até aqui — nada foi implementado, nenhuma linha de código escrita, nada em produção.
**Por que este documento existe**: decisão do JP de tratar essa ideia como um produto/conversa separada da operação do dia a dia do TapTrigger (bugs, deploys, suporte), mesmo sabendo que no futuro os dois devem se conversar na mesma plataforma/conta/site. Este documento é o "pacote completo" pra abrir essa nova conversa/execução already com todo o contexto acumulado, sem precisar repetir nada.

---

## 0. Recomendação sobre separar em conversa/execução própria

Faz sentido separar, por alguns motivos concretos:

- O histórico desta conversa está cheio de contexto operacional do TapTrigger hoje (bug de chat da Kick, deploy na VPS, revert de commits, etc.) que não tem nada a ver com este produto novo — misturar aumenta o risco de uma sessão futura confundir instruções de um assunto com o outro.
- Este produto novo provavelmente vai numa stack/repositório diferente (processamento de vídeo, fila assíncrona, GPU sob demanda) — não faz sentido herdar as restrições e o jeito de trabalhar do repositório atual do TapTrigger (VPS única, SQLite, tudo síncrono).
- Trabalhar separado deixa mais livre pra errar/prototipar rápido sem risco de encostar em produção do TapTrigger sem querer.

**O único cuidado**: como você mesmo disse, os dois produtos devem se conversar no futuro (mesma conta de usuário, talvez mesmo painel/domínio, talvez mesma cobrança). Por isso deixei uma seção (§1) só com os pontos da stack atual do TapTrigger que quem for construir o produto novo deveria ter em mente desde já — não pra travar decisões agora, só pra não fechar portas que tornem a integração futura mais difícil.

---

## 1. Pontos de integração futura a ter em mente (não travam nada agora)

Contexto técnico do TapTrigger hoje, caso ajude a não tomar decisões que dificultem juntar os dois depois:

- Backend em Node.js/Express, banco SQLite (`better-sqlite3`), tudo síncrono/webhook-driven, rodando numa única VPS Oracle (`estopim`, Oracle Cloud, sistema `systemd`).
- Autenticação hoje é por conta própria do streamer (login com Kick/Twitch OAuth), tabela `accounts` no SQLite com campos como `id, platform, username, kick_user_id, twitch_user_id`, etc.
- Planos atuais do TapTrigger: Grátis, Fundador (R$54,90/mês), Pro, Visionário (contribuição única) — cada um com cota de armazenamento (150-500GB) que já é grande pra VPS atual.
- Se o produto novo (cortes de vídeo) crescer separado e depois precisar "conversar" com isso, os pontos mais prováveis de integração são: login único (mesma conta Kick/Twitch), e talvez cobrança/assinatura combinada num plano só no futuro. Nenhum desses precisa ser resolvido agora — só vale desenhar o cadastro do produto novo de um jeito que não impeça, no futuro, vincular pela conta Kick/Twitch do streamer (que já é o identificador único usado hoje).

---

## 2. A ideia original

Streamer usa OBS pra gravar a live. Quer subir essa gravação numa ferramenta e receber de volta vários cortes curtos prontos pra redes sociais (TikTok/Reels/Shorts), automaticamente, sem precisar editar manualmente. Inspiração declarada: **realoficial.com.br**, um SaaS brasileiro que já faz isso. A intenção é oferecer algo parecido dentro do ecossistema GRAAL.hub/TapTrigger, mas **com só 2 planos** (o mais completo e o nível logo abaixo dele), em vez dos 3-4 que a referência tem — e, na virada mais recente da conversa, **construído de forma própria e independente**, sem depender da API de nenhum fornecedor terceiro, priorizando não travar investimento fixo antes de validar.

---

## 3. Como o Real Oficial funciona (referência estudada de ponta a ponta)

### Fluxo do produto
1. **Entrada**: link (YouTube/Twitch/Kick/Drive/MP4), upload de arquivo (até 10h), ou "Live Monitoring" (conecta direto no canal Twitch/Kick e monitora a live ao vivo, sem OBS/upload).
2. **Análise por IA**: Real Vision (expressão facial/emoção/movimento), RHPT — Real HotPeak Tracking (acha o pico de tensão/engajamento pra decidir onde cortar), Prisma (reenquadramento horizontal → vertical 9:16 inteligente), BIA (modelo específico pra podcast/webinar: transcrição + emoção + engajamento).
3. **Saída**: 15-30 cortes por 30 min de vídeo original, já com legenda automática.
4. **Edição**: editor próprio, ajuste em lote (100+ cortes de uma vez), Brand Kit.
5. **Distribuição**: agendamento de publicação com até 60 dias de antecedência.

### Planos e preços
| Plano | Preço/mês | Créditos | Equivalente em vídeo |
|---|---|---|---|
| Grátis | R$0 | — | 3 cortes de até 15s, com marca d'água |
| Lite | R$59,90 | 1.800 | ~30h |
| Creator | R$99,90 | 3.000 | ~50h |
| Viral | R$149,90 | 5.400 | ~90h |
| Business | a partir de R$2.000 | sob consulta | 500h+, 100 contas conectadas, suporte dedicado |

- 1 crédito = 1 minuto de vídeo processado.
- Créditos não expiram, dá pra comprar avulso. Anual com até 25% de desconto.
- **Achado chave pro seu pedido de "só 2 planos"**: Lite, Creator e Viral são o mesmo produto, só mudando volume de crédito — nenhuma feature diferente entre eles. Só o Business tem algo exclusivo de verdade (contas em massa, suporte dedicado). Isso sustenta bem uma estrutura de 2 planos (um "intermediário" + um "completo") sem perder feature nenhuma no meio do caminho — a segmentação real deles é por quantidade, não por recurso.
- Retenção de projeto: 60 dias com assinatura ativa, 3 dias sem.

### A API deles
Existe documentação pública de API em `docs.realoficial.com.br` (bloqueada por robots.txt pras minhas ferramentas — não dá pra ver o conteúdo, só confirmar que existe e está indexada). Achei confirmação real e pública (posts no X de quem parece ser o fundador, @acgfbr) de que **terceiros já usaram essa API pra construir produtos próprios** — ou seja, ela é acessível na prática, mas preço/termos de revenda seguem desconhecidos, e só dá pra descobrir com contato direto com a empresa.

---

## 4. A decisão de caminho: construir de forma própria, sem depender de terceiro

Você foi claro: quer independência (não ficar refém de um fornecedor que pode fechar ou mudar preço) e prioriza o caminho que **não exija investimento fixo antecipado**, mesmo que demore mais pra ficar pronto.

### A evidência que isso é viável: um caso real documentado publicamente

Achei um post no TabNews da mesma pessoa por trás do Real Oficial (@acgfbr) contando como ele **lançou seu próprio SaaS de cortes virais, construído 100% do zero**, sem depender de API de terceiro nenhuma:

- **Stack**: Next.js/Node no front, Laravel (PHP) no back, 5 microsserviços em Python usando **4 tipos de modelos de IA 100% open-source**.
- **Infra**: tudo dockerizado, rodando na Railway.
- **GPU**: em vez de comprar/manter servidor com GPU, ele **aluga GPU por segundo sob demanda** em plataformas como Vast.ai, RunPod e Beam — pede uma GPU nova a cada leva da fila e libera depois. Só paga pela GPU no momento exato em que processa vídeo.
- **Números reais publicados**: cobra R$6,00/hora processada do cliente, com custo operacional de R$0,60/hora (margem ~10x). Primeira receita: R$313 em MRR já no primeiro dia.

Isso é a prova de conceito mais direta possível: dá pra ser independente, e o jeito de fazer isso sem travar investimento fixo é pagar só pela GPU quando ela processa vídeo de verdade — não manter servidor de IA parado gerando custo.

### O blueprint técnico — peça por peça, tudo com opção open-source pronta

Achei 3 projetos open-source no GitHub que fazem exatamente esse tipo de produto (`AI-Youtube-Shorts-Generator`, `openshorts`, `autoclip`) — dá pra usar como referência de arquitetura ou até como ponto de partida:

| Etapa | Componente open-source | Roda em CPU? | Custo |
|---|---|---|---|
| Baixar/receber vídeo | `yt-dlp` (se link) ou upload direto | — | Grátis |
| Transcrição com timestamp | `faster-whisper` / `whisper.cpp` (baseados no Whisper da OpenAI, mas open-source) | Sim (mais lento sem GPU) | Grátis |
| Achar o melhor momento (highlight) | Um LLM analisa a transcrição e pontua trechos por gancho/emoção/clímax (os projetos usam GPT-4o-mini ou Gemini Flash) | — | Baixo custo por chamada, tem camada grátis em alguns provedores |
| Reenquadrar horizontal → vertical seguindo o rosto | `MediaPipe` + `YOLOv8` + `OpenCV`, ou `PyAutoFlip` (baseado no AutoFlip que o próprio Google abriu como open-source em 2020 especificamente pra isso) | **Sim** — o PyAutoFlip é otimizado pra CPU (usa ONNX Runtime) | Grátis |
| Legenda automática queimada | `faster-whisper` (mesma transcrição) + `ffmpeg` | Sim | Grátis |
| Renderização final | `ffmpeg` | Sim | Grátis |

A única etapa que realmente pede poder de processamento pesado é a inferência de IA em volume (transcrição de vídeos longos, análise de highlight em escala) — e essa é a parte que dá pra terceirizar por segundo em GPU alugada, do jeito que o acgfbr fez.

### Nota de infraestrutura própria (VPS atual do TapTrigger)

A VPS Oracle atual do TapTrigger (`E2.1.Micro`, ~500MB RAM) é fraca demais pra qualquer etapa de vídeo, mesmo as leves. A Oracle tem um tier "Always Free" mais forte (Ampere A1, ARM) que **foi cortado pela metade em junho de 2026** (de 4 OCPU/24GB pra 2 OCPU/12GB, sem aviso público) — ainda assim, continua grátis e é uma melhora grande sobre o que o TapTrigger usa hoje. Dá pra rodar nele o backend, a fila de processamento, e as etapas leves (ffmpeg, PyAutoFlip em CPU) — mas não a transcrição em volume nem inferência pesada, pra isso GPU alugada por segundo continua sendo o caminho de menor investimento fixo.

---

## 5. Rascunho de 2 planos (conceitual, pendente de custo real medido)

- **Plano intermediário**: volume de minutos processados que cobre a maioria dos streamers menores/médios.
- **Plano completo**: volume maior, talvez com algo a mais (retenção de projeto mais longa, prioridade na fila).

Isso é só um rascunho — não dá pra precificar de verdade sem medir o custo real por minuto processado no seu próprio pipeline (que depende da GPU alugada, do modelo de LLM escolhido pra highlight, etc.).

---

## 6. Próximos passos propostos (pra quem for executar isso)

1. **Protótipo isolado, fora de qualquer produção**: pegar 1 vídeo real de teste (gravação de OBS) e rodar manualmente o pipeline mínimo — transcrição → LLM aponta 3-5 trechos de destaque → recorte vertical (PyAutoFlip ou OpenCV) → legenda queimada. Objetivo: validar se a qualidade chega perto do Real Oficial antes de investir mais tempo.
2. **Medir custo real** numa GPU alugada por segundo (Vast.ai ou RunPod), processando um vídeo de 30-60 min, e comparar com os R$0,60/hora que o acgfbr relatou (pode variar pro seu caso).
3. **Decidir a arquitetura de fila/orquestração** — processamento é assíncrono por natureza, não cabe no fluxo síncrono do TapTrigger atual, então precisa de fila (mesmo que simples no início).
4. **Resolver upload/armazenamento temporário** de arquivo de vídeo grande — infraestrutura nova de qualquer forma.
5. **Só depois de validar qualidade e custo real**: desenhar a integração de painel (upload → fila → exibição dos cortes) e os 2 planos de preço com número real, não estimado.

## 7. Perguntas em aberto (levar pra nova conversa/execução)

1. Qual dos 3 projetos open-source (`AI-Youtube-Shorts-Generator`, `openshorts`, `autoclip`) usar como base/referência, ou construir mais enxuto do zero olhando pra eles só como inspiração?
2. Qual provedor de GPU sob demanda usar pra medir custo real (Vast.ai, RunPod, Beam, outro)?
3. Tem algum vídeo real de streamer (com autorização) pra usar como teste de qualidade?
4. Esse produto novo vai ter marca/nome próprio desde já, separado do TapTrigger, ou fica sem nome público até decidir se integra?
5. Orçamento que você toparia pra esse teste inicial de GPU (mesmo pequeno, tipo R$20-50 pra rodar os primeiros testes)?

---

## Fontes consultadas

- [Real Oficial — página inicial](https://realoficial.com.br)
- [Real Oficial — planos](https://realoficial.com.br/pt/pricing)
- [Real Oficial — Live Monitoring](https://realoficial.com.br/pt/features/live-monitoring)
- [Real Oficial — documentação (índice)](https://realoficial.com.br/pt/docs)
- [Post no X sobre terceiro usando a API do Real Oficial](https://x.com/acgfbr/status/2024182082923094434)
- [TabNews — "Lancei meu SaaS de cortes virais e fiz 300R$ em um dia"](https://www.tabnews.com.br/acgfbr/lancei-meu-saas-de-cortes-virais-e-fiz-300r-em-um-dia)
- [GitHub — AI-Youtube-Shorts-Generator](https://github.com/SamurAIGPT/AI-Youtube-Shorts-Generator)
- [GitHub — openshorts](https://github.com/mutonby/openshorts)
- [GitHub — autoclip](https://github.com/artbyjazi/autoclip)
- [GitHub — pyautoflip](https://github.com/AhmedHisham1/pyautoflip)
- [Google Open Source Blog — AutoFlip](https://opensource.googleblog.com/2020/02/autoflip-open-source-framework-for.html)
- [InfoQ — Oracle corta free tier Ampere A1 pela metade (2026)](https://www.infoq.com/news/2026/07/oracle-cloud-free-tier-limits/)
