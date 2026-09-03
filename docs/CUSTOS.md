# Como medir o custo real

O passo 2 do brief é medir custo por minuto processado numa GPU alugada e
comparar com os R$ 0,60/hora relatados publicamente. Sem esse número não dá
para precificar plano nenhum. Este documento é o procedimento.

## O que o pipeline já mede sozinho

Toda rodada escreve `report.json`:

```json
{
  "tempo": {
    "processamento_s": 51.8,
    "gpu_s": 0.0,
    "cpu_s": 51.8,
    "video_fonte_s": 90.0,
    "fator_tempo_real": 0.58
  },
  "tokens": { "entrada": 0, "saida": 0, "modelo": "" },
  "custo_brl": {
    "gpu": 0.0, "cpu": 0.0043, "llm": 0.0,
    "total": 0.0043,
    "por_minuto_de_video": 0.0029,
    "por_hora_de_video": 0.17,
    "por_corte": 0.0014
  },
  "precos_usados": { "gpu_brl_hora": 2.2, "usd_brl": 5.4, "...": "..." }
}
```

`fator_tempo_real` abaixo de 1 significa que processa mais rápido que o tempo
real do vídeo. `precos_usados` fica gravado junto de propósito: um número de
custo sem a tabela de preços que o gerou não serve para comparar rodadas.

Os preços vêm do ambiente:

| Variável | Padrão | O que é |
|---|---|---|
| `CORTES_GPU_BRL_HOUR` | 2.20 | preço da hora da GPU alugada |
| `CORTES_CPU_BRL_HOUR` | 0.30 | rateio da máquina que fica ligada |
| `CORTES_USD_BRL` | 5.40 | câmbio para converter o custo do LLM |
| `CORTES_LLM_IN_USD` | 5.0 | USD por 1M de tokens de entrada |
| `CORTES_LLM_OUT_USD` | 25.0 | USD por 1M de tokens de saída |

Os padrões são chute de partida. **Trocar pelos preços da máquina contratada é
a primeira coisa a fazer** — o resto do relatório só vale depois disso.

## Procedimento de medição

Precisa de uma gravação real de 30 a 60 minutos. Vídeo curto não serve: o
tempo de subir a instância e carregar o modelo domina a conta e mascara o
custo marginal, que é o que interessa.

**1. Linha de base em CPU**, na máquina que já existe:

```bash
CORTES_GPU_BRL_HOUR=0 CORTES_CPU_BRL_HOUR=<sua_hora> \
  cortes run gravacao.mp4 -o ./medicao-cpu --selector heuristic
```

Isso dá o custo das etapas que nunca vão para a GPU (áudio, rastreio, legenda,
render) e o `fator_tempo_real` delas. Guarde o `report.json`.

**2. Transcrição na GPU alugada.** Suba a instância, instale ffmpeg e o
pacote, e rode com os preços reais:

```bash
CORTES_GPU_BRL_HOUR=<preço/hora da instância> \
CORTES_WHISPER_MODEL=medium CORTES_WHISPER_DEVICE=cuda CORTES_WHISPER_COMPUTE=float16 \
  cortes run gravacao.mp4 -o ./medicao-gpu --selector heuristic
```

O estágio `transcricao` só é rotulado como GPU quando há CUDA de verdade
disponível — se o relatório mostrar `gpu_s: 0`, a GPU não foi usada e a medição
não vale.

Vale medir dois ou três tamanhos de modelo (`small`, `medium`, `large-v3`): a
diferença de custo é grande e a de qualidade de legenda pode não ser, e essa é
uma das decisões de margem do produto.

**3. Custo do seletor.** Rode a mesma gravação com `--selector claude` e olhe
`tokens` e `custo_brl.llm`. Como o custo é por token de transcrição, ele
cresce com a duração do vídeo, não com o número de cortes.

**4. Junte.** O custo total por hora de vídeo é a soma dos três, e é o número
que entra na conta do plano. Compare com R$ 6,00/hora cobrados do cliente na
referência pública para ver que margem sobra.

## O que a conta ainda não cobre

Deliberadamente fora do `report.json`, porque não são medíveis numa rodada:

- **Provisionamento da GPU.** O tempo entre pedir a instância e ela estar
  pronta é pago e não aparece aqui. É o argumento para agrupar jobs em levas
  em vez de subir máquina por vídeo.
- **Armazenamento.** Gravação de live é arquivo grande, e a política de
  retenção muda o custo mais do que o processamento. `CORTES_STORAGE_BRL_GB`
  existe na configuração mas ainda não entra no relatório porque depende de
  uma política de retenção que não foi decidida.
- **Egresso.** Download dos cortes pelo cliente.
- **Reprocessamento.** Cliente insatisfeito que manda rodar de novo.

## Números observados aqui (não servem de referência)

Rodadas de validação, em CPU de container, com vídeo sintético e transcrição
já pronta — ou seja, **sem a etapa cara**:

| Rodada | Fonte | Etapas | Fator tempo real |
|---|---|---|---|
| 3 cortes, rastreio por movimento | 90 s | áudio + rastreio + legenda + render | 0,40x |
| 1 corte, rastreio por movimento | 58 s | idem | 0,28x |

Servem só para dizer que as etapas de CPU são baratas perto da transcrição.
Qualquer número de custo real depende da medição acima com gravação de
verdade.
