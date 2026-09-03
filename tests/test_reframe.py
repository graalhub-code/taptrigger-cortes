import math

import pytest

from cortes.config import ReframeConfig, RenderConfig
from cortes.models import MediaInfo
from cortes.stages import reframe


def media(width=1920, height=1080):
    return MediaInfo(
        path="/dev/null", duration=60.0, width=width, height=height, fps=30.0, has_audio=True
    )


def test_crop_size_de_16_9_para_9_16():
    width, height = reframe.crop_size(media(), RenderConfig())
    assert height == 1080
    assert width == 608  # 1080 * 9/16 = 607.5, arredondado para par
    assert width % 2 == 0 and height % 2 == 0


def test_crop_size_em_fonte_vertical_nao_estoura_a_largura():
    width, height = reframe.crop_size(media(width=720, height=1280), RenderConfig())
    assert width <= 720
    assert math.isclose(width / height, 9 / 16, rel_tol=0.02)


def test_plan_center_fica_no_meio():
    plan = reframe.plan_center(media(), RenderConfig())
    assert plan.is_static
    assert plan.keyframes[0].x == (1920 - plan.width) // 2 - ((1920 - plan.width) // 2) % 2


def test_pan_segue_o_alvo_ate_alcancar():
    deadband = 0.05
    config = ReframeConfig(smoothing_tau=0.4, deadband=deadband, max_pan_per_second=1.0)
    crop_width, max_x = 600, 1000
    # Alvo parado na direita; a câmera parte da esquerda.
    samples = [(i * 0.2, 1200.0) for i in range(60)]
    samples[0] = (0.0, 300.0)
    path = reframe.smooth_path(samples, crop_width, max_x, config)
    assert path[0][1] == 0
    # Alvo em 1200 pede recorte em 1200 - 600/2 = 900; a zona morta deixa a
    # câmera parar essa margem antes, que é o que evita a vibração.
    assert path[-1][1] == pytest.approx(900 - deadband * crop_width, abs=2)


def test_pan_nunca_passa_dos_limites_do_quadro():
    config = ReframeConfig(smoothing_tau=0.1, deadband=0.0, max_pan_per_second=50.0)
    crop_width, max_x = 600, 1000
    samples = [(i * 0.2, 5000.0 if i % 2 else -5000.0) for i in range(20)]
    path = reframe.smooth_path(samples, crop_width, max_x, config)
    assert all(0 <= x <= max_x for _, x in path)


def test_zona_morta_ignora_tremida_pequena():
    config = ReframeConfig(smoothing_tau=0.3, deadband=0.2, max_pan_per_second=1.0)
    crop_width, max_x = 600, 1000
    center = 800.0
    # Oscilação de +-30px, bem abaixo da zona morta de 0.2*600 = 120px.
    samples = [(i * 0.2, center + (30 if i % 2 else -30)) for i in range(40)]
    path = reframe.smooth_path(samples, crop_width, max_x, config)
    assert len(path) == 1, "a câmera não deveria se mexer dentro da zona morta"


def test_limite_de_velocidade_segura_o_chicote():
    slow = ReframeConfig(smoothing_tau=0.01, deadband=0.0, max_pan_per_second=0.1)
    crop_width, max_x = 600, 1000
    samples = [(0.0, 300.0), (0.2, 1500.0)]
    path = reframe.smooth_path(samples, crop_width, max_x, slow)
    # Em 0.2s o teto é 0.1 * 600 * 0.2 = 12px.
    assert path[-1][1] <= path[0][1] + 12


def test_suavizacao_independe_da_taxa_de_amostragem():
    """Dobrar sample_fps não pode dobrar a velocidade do pan."""
    config = ReframeConfig(smoothing_tau=0.5, deadband=0.0, max_pan_per_second=10.0)
    crop_width, max_x = 600, 2000
    target = 1400.0

    def final_x(step: float) -> int:
        count = int(4.0 / step)
        samples = [(0.0, 300.0)] + [(i * step, target) for i in range(1, count)]
        return reframe.smooth_path(samples, crop_width, max_x, config)[-1][1]

    assert abs(final_x(0.5) - final_x(0.1)) <= 4


def test_buraco_sem_alvo_mantem_ultima_posicao():
    config = ReframeConfig(smoothing_tau=0.3, deadband=0.0, max_pan_per_second=10.0)
    samples = [(0.0, 900.0), (0.3, None), (0.6, None), (0.9, 900.0)]
    path = reframe.smooth_path(samples, 600, 1000, config)
    assert all(x == path[0][1] for _, x in path)


def test_sem_amostra_nenhuma_cai_no_centro():
    path = reframe.smooth_path([(0.0, None)], 600, 1000, ReframeConfig())
    assert path == [(0.0, 500)]


def test_escolhe_rosto_quando_ele_aparece_o_bastante():
    tracks = {
        "face": [(i * 0.3, 500.0 if i % 2 else None) for i in range(10)],
        "motion": [(i * 0.3, 900.0) for i in range(10)],
    }
    name, _, hits = reframe.pick_track(tracks, ["face", "motion"])
    assert name == "face" and hits == 5


def test_cai_para_movimento_quando_quase_nao_ha_rosto():
    # Gameplay: um falso positivo solto de rosto não pode mandar no recorte.
    tracks = {
        "face": [(i * 0.3, 500.0 if i == 3 else None) for i in range(20)],
        "motion": [(i * 0.3, 900.0) for i in range(20)],
    }
    name, _, _ = reframe.pick_track(tracks, ["face", "motion"])
    assert name == "motion"


def test_sem_alvo_em_detector_nenhum_devolve_none():
    tracks = {"face": [(0.0, None)], "motion": [(0.0, None)]}
    assert reframe.pick_track(tracks, ["face", "motion"]) is None


def test_backend_motion_nao_carrega_detector_de_rosto():
    detectors = reframe.build_detectors(ReframeConfig(backend="motion"), (480, 270))
    assert [d.name for d in detectors] == ["motion"]


def test_backend_center_nao_usa_detector():
    assert reframe.build_detectors(ReframeConfig(backend="center"), (480, 270)) == []


def test_backend_face_sem_modelo_reclama(monkeypatch, tmp_path):
    monkeypatch.setenv("CORTES_YUNET_MODEL", str(tmp_path / "nao-existe.onnx"))
    with pytest.raises(FileNotFoundError, match="fetch-models"):
        reframe.build_detectors(ReframeConfig(backend="face"), (480, 270))


def test_auto_sem_modelo_usa_movimento(monkeypatch, tmp_path):
    monkeypatch.setenv("CORTES_YUNET_MODEL", str(tmp_path / "nao-existe.onnx"))
    detectors = reframe.build_detectors(ReframeConfig(backend="auto"), (480, 270))
    assert [d.name for d in detectors] == ["motion"]


def test_sendcmd_gera_um_par_por_keyframe():
    plan = reframe.plan_center(media(), RenderConfig())
    plan.keyframes.append(reframe.CropKeyframe(t=1.5, x=100, y=0))
    script = reframe.sendcmd_script(plan)
    lines = [line for line in script.splitlines() if line.strip()]
    assert len(lines) == 4
    assert lines[2] == "1.50 crop x 100;"


cv2 = pytest.importorskip("cv2")
np = pytest.importorskip("numpy")


def _frame(subject_x: int, hud_on: bool, size=(270, 480), hud=(10, 20)):
    frame = np.full((size[0], size[1], 3), 20, np.uint8)
    frame[80:200, subject_x : subject_x + 90] = 200
    if hud_on:
        frame[10 : 10 + hud[0], 5 : 5 + hud[1]] = 255
    return frame


def test_movimento_prefere_o_maior_bloco_ao_hud():
    detector = reframe.MotionDetector()
    # HUD grande piscando no canto esquerdo enquanto o assunto anda no meio.
    assert detector.center_x(_frame(50, True, hud=(40, 60)), 1.0) is None  # 1º quadro: sem referência
    center = detector.center_x(_frame(150, False, hud=(40, 60)), 1.0)
    assert center is not None
    # O assunto se move entre x=50 e x=240; o HUD apagou em x<65.
    assert 100 < center < 260


def test_movimento_descarta_bloco_pequeno_demais():
    detector = reframe.MotionDetector()
    detector.center_x(_frame(200, True), 1.0)
    # Entre os dois quadros só o HUD de 10x20 mudou: abaixo do limiar de área.
    assert detector.center_x(_frame(200, False), 1.0) is None


def test_movimento_devolve_none_no_primeiro_quadro():
    assert reframe.MotionDetector().center_x(_frame(100, False), 1.0) is None
