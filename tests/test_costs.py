from cortes.config import CostConfig
from cortes.costs import CostTracker
from cortes.models import StageTiming


def tracker_with(gpu_seconds=0.0, cpu_seconds=0.0, tokens=(0, 0)):
    tracker = CostTracker()
    if gpu_seconds:
        tracker.timings.append(StageTiming("transcricao", gpu_seconds, "gpu"))
    if cpu_seconds:
        tracker.timings.append(StageTiming("render", cpu_seconds, "cpu"))
    tracker.llm_usage = {"input_tokens": tokens[0], "output_tokens": tokens[1], "model": "teste"}
    return tracker


def test_custo_de_gpu_usa_o_preco_por_hora():
    config = CostConfig(gpu_brl_hour=3.60, cpu_brl_hour=0.0, usd_brl=5.0)
    resumo = tracker_with(gpu_seconds=3600.0).summarize(config, source_duration=600.0, clip_count=5)
    assert resumo["custo_brl"]["gpu"] == 3.60


def test_custo_de_llm_converte_tokens_para_reais():
    config = CostConfig(
        gpu_brl_hour=0.0,
        cpu_brl_hour=0.0,
        usd_brl=5.0,
        llm_input_usd_mtok=5.0,
        llm_output_usd_mtok=25.0,
    )
    resumo = tracker_with(tokens=(1_000_000, 100_000)).summarize(config, 600.0, 5)
    # (1M * $5 + 0.1M * $25) = $7.50 -> R$ 37,50
    assert resumo["custo_brl"]["llm"] == 37.50


def test_custo_por_minuto_divide_pela_duracao_da_fonte():
    config = CostConfig(gpu_brl_hour=3.60, cpu_brl_hour=0.0, usd_brl=5.0)
    resumo = tracker_with(gpu_seconds=600.0).summarize(config, source_duration=1800.0, clip_count=4)
    # 600s de GPU a R$3,60/h = R$0,60 para 30 min de vídeo.
    assert resumo["custo_brl"]["total"] == 0.60
    assert resumo["custo_brl"]["por_minuto_de_video"] == 0.02
    assert resumo["custo_brl"]["por_hora_de_video"] == 1.20
    assert resumo["custo_brl"]["por_corte"] == 0.15


def test_fator_tempo_real_abaixo_de_um_significa_mais_rapido_que_o_video():
    config = CostConfig()
    resumo = tracker_with(cpu_seconds=300.0).summarize(config, source_duration=600.0, clip_count=1)
    assert resumo["tempo"]["fator_tempo_real"] == 0.5


def test_sem_cortes_nao_divide_por_zero():
    resumo = tracker_with(cpu_seconds=10.0).summarize(CostConfig(), 60.0, clip_count=0)
    assert resumo["custo_brl"]["por_corte"] >= 0


def test_cronometro_registra_hardware_do_estagio():
    tracker = CostTracker()
    with tracker.stage("transcricao", "gpu"):
        pass
    with tracker.stage("render", "cpu"):
        pass
    assert [t.hardware for t in tracker.timings] == ["gpu", "cpu"]
    assert tracker.seconds_on("gpu") >= 0.0


def test_cronometro_conta_o_tempo_mesmo_se_o_estagio_falhar():
    tracker = CostTracker()
    try:
        with tracker.stage("render", "cpu"):
            raise RuntimeError("ffmpeg morreu")
    except RuntimeError:
        pass
    assert len(tracker.timings) == 1
