# Colocar online

O objetivo aqui é um endereço público onde se envia um vídeo pelo navegador e
se recebe os cortes, sem instalar nada e sem cadastro.

O código para isso está pronto: `cortes/web/` tem o servidor, o `Dockerfile`
empacota tudo, e há testes cobrindo envio, fila, resultado e as recusas. O que
falta é **uma máquina**, e isso depende de uma conta sua — não existe caminho
que dispense esse passo.

## O que a aplicação exige da máquina

Estes quatro requisitos são o que elimina a maior parte das opções:

| Exigência | Por quê |
|---|---|
| Executar por minutos | Uma rodada de 10 min de vídeo leva vários minutos; não é uma requisição rápida |
| ~2 GB de RAM | O modelo de transcrição sozinho ocupa perto de 1 GB |
| Disco que persiste | Os cortes e o vídeo enviado ficam em `/data` |
| `ffmpeg` no sistema | É ele que corta, recorta e renderiza |

## Por que não dá para usar a Vercel

Você já tem conta Vercel (time `graalhub`, plano hobby), então vale explicar por
que não serve para **esta** parte. Não é limitação de plano, é de formato:
funções serverless aceitam corpo de requisição de poucos MB (um vídeo não
passa), têm teto de duração em segundos, o pacote da função não comporta o
ffmpeg mais o modelo de transcrição, e não há disco que sobreviva entre
chamadas.

A Vercel continua fazendo sentido mais para frente, para o site e o painel do
produto — que conversariam com este serviço por HTTP. Só não é onde o vídeo é
processado.

## Opções, da mais rápida de subir à mais barata

### 1. Railway — recomendada para o teste

Sobe direto do GitHub, detecta o `Dockerfile` sozinho e devolve uma URL HTTPS.
Sem administrar servidor. Custa a partir de US$ 5/mês.

1. Entre em railway.app com o GitHub.
2. **New Project → Deploy from GitHub repo** → `graalhub-code/taptrigger-cortes`.
3. Em **Settings → Branch**, escolha `claude/new-session-16ussk`.
4. Em **Variables**, adicione `ANTHROPIC_API_KEY` (sem ela o seletor cai na
   heurística, que funciona mas escolhe pior).
5. Em **Volumes**, crie um volume montado em `/data`.
6. Em **Settings → Networking**, clique em **Generate Domain**.

O endereço gerado é o seu teste.

### 2. Render — configuração já versionada

O repositório traz um `render.yaml`, então o Render monta o serviço sozinho.
Precisa de plano pago (o gratuito não tem disco persistente e hiberna, o que
mata job em andamento).

1. Em render.com: **New → Blueprint** e aponte para o repositório.
2. Ele lê o `render.yaml` e cria o serviço com disco de 20 GB em `/data`.
3. Preencha `ANTHROPIC_API_KEY` no painel.

### 3. VPS com Docker — mais barato e sem limite de tempo

Um servidor de 2 vCPU e 4 GB custa cerca de €4/mês (Hetzner) ou sai de graça
no *Always Free* Ampere da Oracle, que você já usa para o TapTrigger. Depois de
criar a máquina, com Docker instalado:

```bash
git clone https://github.com/graalhub-code/taptrigger-cortes.git
cd taptrigger-cortes && git checkout claude/new-session-16ussk
docker build -t cortes .
docker run -d --name cortes -p 80:8000 \
  -v /srv/cortes-dados:/data \
  -e ANTHROPIC_API_KEY=sua-chave \
  --restart unless-stopped cortes
```

Fica em `http://IP-DA-MAQUINA`. Para HTTPS num subdomínio seu (por exemplo
`cortes.graalhub.com`), aponte o DNS para o IP e ponha um Caddy na frente — ele
resolve o certificado sozinho.

### 4. Fly.io

Também roda o `Dockerfile`, cobra por uso e tem volume persistente. Exige o
CLI `flyctl` instalado na sua máquina, o que anula parte da vantagem de não
mexer no Mac.

## Variáveis de ambiente

| Variável | Padrão | Para que serve |
|---|---|---|
| `ANTHROPIC_API_KEY` | — | Liga a seleção de trechos pelo Claude |
| `CORTES_WHISPER_MODEL` | `small` | `tiny` é mais rápido, `medium` transcreve melhor |
| `CORTES_MAX_UPLOAD_MB` | `2048` | Teto do arquivo enviado |
| `CORTES_DATA_DIR` | `/data/jobs` | Onde ficam vídeos e cortes |
| `CORTES_WEB_TOKEN` | vazio | Se preenchido, exige `?token=...` para abrir |
| `CORTES_SELECTOR` | `claude` | `heuristic` roda sem chamar a API |

## Quanto tempo leva cada rodada

Medido aqui, só das etapas leves (áudio, enquadramento, legenda, render):
**0,2 a 0,4 vez a duração do vídeo**. Ou seja, um vídeo de 10 minutos gasta
uns 2 a 4 minutos nessas etapas.

A transcrição não foi medida — o ambiente de desenvolvimento não conseguia
baixar o modelo. Ela é a etapa mais pesada e vai dominar o total em CPU. Conte
com algo entre uma e três vezes a duração do vídeo, e comece por um trecho de
10 minutos antes de mandar uma live inteira.

## Sobre não ter login

O serviço sobe sem cadastro, como pedido: a proteção é a URL não ser
divulgada. Vale saber o que isso implica: quem tiver o endereço envia vídeo e
consome a CPU da máquina, e vê os cortes de todo mundo em `/jobs`. Para um
teste seu, tudo bem. Quando o endereço deixar de ser secreto, definir
`CORTES_WEB_TOKEN` já resolve o caso simples, sem precisar de tela de login.
