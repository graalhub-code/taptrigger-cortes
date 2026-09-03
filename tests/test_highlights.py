from cortes.config import Config
from cortes.models import Highlight, Segment, Transcript, Word
from cortes.stages import highlights


def make_transcript(duration=300.0, step=5.0, text="uma frase qualquer aqui"):
    segments = []
    t = 0.0
    while t + step <= duration:
        tokens = text.split()
        width = step / len(tokens)
        words = [
            Word(start=t + i * width, end=t + (i + 1) * width, text=tok)
            for i, tok in enumerate(tokens)
        ]
        segments.append(Segment(start=t, end=t + step, text=text, words=words))
        t += step
    return Transcript(language="pt", segments=segments)


def test_postprocess_descarta_curto_demais():
    config = Config()
    config.min_clip_seconds = 20.0
    transcript = make_transcript()
    curto = Highlight(start=10.0, end=15.0, title="curto", score=9.0)
    ok = Highlight(start=60.0, end=100.0, title="bom", score=5.0)
    result = highlights.postprocess([curto, ok], config, transcript, 300.0)
    assert [h.title for h in result] == ["bom"]


def test_postprocess_corta_no_maximo():
    config = Config()
    config.max_clip_seconds = 60.0
    transcript = make_transcript()
    longo = Highlight(start=10.0, end=200.0, title="longo", score=5.0)
    (result,) = highlights.postprocess([longo], config, transcript, 300.0)
    assert result.duration <= 60.0


def test_postprocess_rejeita_sobreposicao():
    config = Config()
    config.clips = 5
    transcript = make_transcript()
    primeiro = Highlight(start=30.0, end=70.0, title="melhor", score=9.0)
    # Sobrepõe 30s do anterior: conteúdo repetido, não pode virar segundo corte.
    segundo = Highlight(start=40.0, end=80.0, title="repetido", score=8.0)
    terceiro = Highlight(start=120.0, end=160.0, title="outro", score=7.0)
    result = highlights.postprocess([primeiro, segundo, terceiro], config, transcript, 300.0)
    assert [h.title for h in result] == ["melhor", "outro"]


def test_postprocess_respeita_o_limite_de_cortes_e_ordena_por_tempo():
    config = Config()
    config.clips = 2
    transcript = make_transcript()
    entrada = [
        Highlight(start=200.0, end=240.0, title="c", score=9.0),
        Highlight(start=100.0, end=140.0, title="b", score=8.0),
        Highlight(start=10.0, end=50.0, title="a", score=1.0),
    ]
    result = highlights.postprocess(entrada, config, transcript, 300.0)
    assert [h.title for h in result] == ["b", "c"]


def test_postprocess_nao_passa_do_fim_do_video():
    config = Config()
    transcript = make_transcript()
    quase_no_fim = Highlight(start=270.0, end=400.0, title="fim", score=5.0)
    (result,) = highlights.postprocess([quase_no_fim], config, transcript, 300.0)
    assert result.end <= 300.0


def test_snap_encosta_na_palavra_mais_proxima():
    config = Config()
    transcript = make_transcript()
    start, end = highlights.snap_to_speech(transcript, 20.3, 60.4, config)
    word_starts = {round(w.start, 3) for w in transcript.words}
    word_ends = {round(w.end, 3) for w in transcript.words}
    assert round(start, 3) in word_starts
    assert round(end, 3) in word_ends


def test_heuristica_pontua_gancho_acima_de_fala_neutra():
    config = Config()
    neutro = make_transcript(duration=120.0, text="entao seguimos o roteiro normal do dia")
    com_gancho = make_transcript(
        duration=120.0, text="caramba nao acredito que isso aconteceu serio mesmo"
    )
    melhor_neutro = max(h.score for h in highlights.HeuristicSelector(config).select(neutro, 120.0))
    melhor_gancho = max(
        h.score for h in highlights.HeuristicSelector(config).select(com_gancho, 120.0)
    )
    assert melhor_gancho > melhor_neutro


def test_heuristica_sem_transcricao_devolve_vazio():
    config = Config()
    vazio = Transcript(language="pt", segments=[])
    assert highlights.HeuristicSelector(config).select(vazio, 60.0) == []


def test_selecao_cai_na_heuristica_quando_o_llm_falha(monkeypatch):
    config = Config()
    config.selector.backend = "claude"
    config.selector.fallback_to_heuristic = True

    def explode(self, transcript, duration):
        raise RuntimeError("sem credencial")

    monkeypatch.setattr(highlights.ClaudeSelector, "select", explode)
    result = highlights.select_highlights(config, make_transcript(), 300.0, {})
    assert result, "deveria ter caído na heurística em vez de derrubar a rodada"
    assert all(h.source == "heuristic" for h in result)


def test_selecao_propaga_erro_quando_fallback_desligado(monkeypatch):
    config = Config()
    config.selector.backend = "claude"
    config.selector.fallback_to_heuristic = False

    def explode(self, transcript, duration):
        raise RuntimeError("sem credencial")

    monkeypatch.setattr(highlights.ClaudeSelector, "select", explode)
    try:
        highlights.select_highlights(config, make_transcript(), 300.0, {})
    except RuntimeError as exc:
        assert "sem credencial" in str(exc)
    else:
        raise AssertionError("deveria ter propagado o erro")


class FakeBlock:
    type = "text"

    def __init__(self, text):
        self.text = text


class FakeUsage:
    def __init__(self, input_tokens, output_tokens):
        self.input_tokens = input_tokens
        self.output_tokens = output_tokens


class FakeResponse:
    def __init__(self, text, stop_reason="end_turn"):
        self.content = [FakeBlock(text)]
        self.usage = FakeUsage(1200, 300)
        self.stop_reason = stop_reason
        self.stop_details = None


class FakeMessages:
    def __init__(self, response):
        self.response = response
        self.last_kwargs = None

    def create(self, **kwargs):
        self.last_kwargs = kwargs
        return self.response


class FakeClient:
    def __init__(self, response):
        self.messages = FakeMessages(response)


CLIPS_JSON = (
    '{"clips": [{"start_seconds": 30.0, "end_seconds": 62.0, "title": "O plot twist",'
    ' "score": 9.0, "reason": "abre com pergunta"}]}'
)


def test_claude_converte_a_resposta_em_highlight():
    config = Config()
    usage = {}
    selector = highlights.ClaudeSelector(config, usage_sink=usage)
    client = FakeClient(FakeResponse(CLIPS_JSON))

    (resultado,) = selector._select_block(client, "[00:30-01:02] alguma fala", 0.0, 600.0)

    assert resultado.start == 30.0 and resultado.end == 62.0
    assert resultado.title == "O plot twist"
    assert resultado.source == "claude"
    # O modelo devolve nota de 0 a 10; internamente trabalhamos em 0 a 1.
    assert resultado.score == 0.9


def test_claude_acumula_tokens_para_o_calculo_de_custo():
    config = Config()
    usage = {}
    selector = highlights.ClaudeSelector(config, usage_sink=usage)
    client = FakeClient(FakeResponse(CLIPS_JSON))

    selector._select_block(client, "bloco", 0.0, 600.0)
    selector._select_block(client, "bloco", 600.0, 1200.0)

    assert usage["input_tokens"] == 2400
    assert usage["output_tokens"] == 600
    assert usage["model"] == config.selector.model


def test_claude_pede_json_com_schema_e_esforco_configurado():
    config = Config()
    config.selector.effort = "low"
    selector = highlights.ClaudeSelector(config, usage_sink={})
    client = FakeClient(FakeResponse(CLIPS_JSON))

    selector._select_block(client, "bloco", 0.0, 600.0)

    kwargs = client.messages.last_kwargs
    assert kwargs["model"] == config.selector.model
    assert kwargs["output_config"]["effort"] == "low"
    assert kwargs["output_config"]["format"]["type"] == "json_schema"
    assert kwargs["output_config"]["format"]["schema"] == highlights.ClaudeSelector.OUTPUT_SCHEMA
    assert "gancho" in kwargs["system"]


def test_claude_levanta_erro_quando_o_modelo_recusa():
    selector = highlights.ClaudeSelector(Config(), usage_sink={})
    client = FakeClient(FakeResponse("", stop_reason="refusal"))
    try:
        selector._select_block(client, "bloco", 0.0, 600.0)
    except RuntimeError as exc:
        assert "recusada" in str(exc)
    else:
        raise AssertionError("recusa deveria virar erro, não lista vazia")


def test_claude_com_resposta_vazia_nao_quebra():
    selector = highlights.ClaudeSelector(Config(), usage_sink={})
    client = FakeClient(FakeResponse("   "))
    assert selector._select_block(client, "bloco", 0.0, 600.0) == []


def test_formata_transcricao_com_timestamp_legivel():
    transcript = make_transcript(duration=130.0, step=65.0, text="alguma coisa")
    texto = highlights.format_transcript(transcript, 0.0, 130.0)
    assert texto.splitlines()[0].startswith("[00:00-01:05]")
