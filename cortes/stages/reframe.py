"""Reenquadramento horizontal -> vertical 9:16.

Amostra alguns quadros por segundo, decide onde está o assunto do quadro e
monta um caminho de "câmera" suavizado. O caminho vira keyframes que o ffmpeg
aplica no filtro ``crop`` via ``sendcmd`` — assim o recorte acompanha quem
está falando em vez de cortar a cabeça do streamer fora do quadro.

Três detectores, do melhor para o mais simples:

``face``    YuNet (DNN do OpenCV). Precisa do arquivo .onnx — baixe com
            ``cortes fetch-models``. É o certo para câmera de streamer.
``motion``  Centroide da diferença entre quadros. Sem modelo nenhum, serve
            para gameplay e para quando não há rosto visível.
``center``  Recorte fixo no centro.

O padrão é ``auto``: usa rosto se o modelo estiver disponível, senão
movimento, senão centro. Tudo roda em CPU — esta etapa fica na VPS, não na
GPU alugada.
"""

from __future__ import annotations

import logging
import math
import os
from pathlib import Path

from ..config import ReframeConfig, RenderConfig
from ..models import CropKeyframe, CropPlan, MediaInfo

logger = logging.getLogger(__name__)

YUNET_FILENAME = "face_detection_yunet_2023mar.onnx"
YUNET_URL = (
    "https://media.githubusercontent.com/media/opencv/opencv_zoo/main/"
    "models/face_detection_yunet/" + YUNET_FILENAME
)


def model_dir() -> Path:
    return Path(os.environ.get("CORTES_MODEL_DIR", Path.home() / ".cache" / "cortes"))


def yunet_model_path() -> Path:
    explicit = os.environ.get("CORTES_YUNET_MODEL")
    return Path(explicit) if explicit else model_dir() / YUNET_FILENAME


def _even(value: float) -> int:
    """h264 exige dimensões pares."""
    out = int(round(value))
    return out - (out % 2)


def crop_size(media: MediaInfo, render: RenderConfig) -> tuple[int, int]:
    """Maior recorte com o aspecto de saída que cabe dentro do vídeo original."""
    target_aspect = render.width / render.height
    width = _even(min(media.width, media.height * target_aspect))
    height = _even(min(media.height, width / target_aspect))
    width = _even(min(media.width, height * target_aspect))
    return max(2, width), max(2, height)


def plan_center(media: MediaInfo, render: RenderConfig, backend: str = "center") -> CropPlan:
    width, height = crop_size(media, render)
    x = _even((media.width - width) / 2)
    y = _even((media.height - height) / 2)
    return CropPlan(
        width=width,
        height=height,
        keyframes=[CropKeyframe(t=0.0, x=x, y=y)],
        backend=backend,
    )


# --------------------------------------------------------------------------
# Detectores: cada um devolve o centro horizontal do assunto, em pixels do
# quadro original, ou None quando não achou nada naquele quadro.
# --------------------------------------------------------------------------


class SubjectDetector:
    name = "base"

    def center_x(self, frame, scale: float) -> float | None:  # pragma: no cover - interface
        raise NotImplementedError


class FaceDetector(SubjectDetector):
    name = "face"

    def __init__(self, model_path: Path, frame_size: tuple[int, int], threshold: float = 0.7):
        import cv2

        self._cv2 = cv2
        self.detector = cv2.FaceDetectorYN_create(
            str(model_path), "", frame_size, threshold, 0.3, 5000
        )

    def center_x(self, frame, scale: float) -> float | None:
        _, faces = self.detector.detect(frame)
        if faces is None or len(faces) == 0:
            return None
        # Rosto maior = quem está em primeiro plano.
        best = max(faces, key=lambda f: float(f[2]) * float(f[3]))
        return (float(best[0]) + float(best[2]) / 2.0) / scale


class MotionDetector(SubjectDetector):
    """Segue o maior bloco de movimento entre quadros consecutivos.

    Usa a maior região conectada em vez do centroide de tudo que se mexeu: um
    cronômetro, um alerta ou o chat na tela piscam sozinhos e puxariam a
    câmera para o canto se cada pixel valesse o mesmo.
    """

    name = "motion"

    # Fração da área do quadro que o bloco precisa ocupar para contar.
    MIN_AREA_RATIO = 0.004

    def __init__(self):
        import cv2

        self._cv2 = cv2
        self.previous = None

    def center_x(self, frame, scale: float) -> float | None:
        cv2 = self._cv2
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        gray = cv2.GaussianBlur(gray, (7, 7), 0)
        previous, self.previous = self.previous, gray
        if previous is None:
            return None

        diff = cv2.absdiff(gray, previous)
        _, mask = cv2.threshold(diff, 18, 255, cv2.THRESH_BINARY)
        # Fecha buracos dentro do assunto e apaga respingo isolado.
        kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (11, 11))
        mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel)
        mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel)

        count, _labels, stats, centroids = cv2.connectedComponentsWithStats(mask, connectivity=8)
        if count <= 1:
            return None

        # índice 0 é o fundo
        areas = stats[1:, cv2.CC_STAT_AREA]
        best = int(areas.argmax()) + 1
        frame_area = mask.shape[0] * mask.shape[1]
        if stats[best, cv2.CC_STAT_AREA] < self.MIN_AREA_RATIO * frame_area:
            return None
        return float(centroids[best][0]) / scale


def build_detectors(
    config: ReframeConfig, frame_size: tuple[int, int]
) -> list[SubjectDetector]:
    """Detectores a rodar, em ordem de preferência.

    Em ``auto`` volta rosto e movimento: os dois rodam no mesmo passe de
    decodificação e a escolha é feita depois, olhando quem realmente achou
    alguma coisa. É o caso comum de gameplay, em que não há rosto na tela e
    perseguir o movimento é melhor do que travar no centro.
    """
    backend = (config.backend or "auto").strip().lower()
    if backend in ("center", "none", "static"):
        return []
    if backend == "motion":
        return [MotionDetector()]

    face: SubjectDetector | None = None
    model_path = yunet_model_path()
    if model_path.exists():
        try:
            face = FaceDetector(model_path, frame_size)
        except Exception as exc:
            logger.warning("YuNet não carregou (%s)", exc)
    elif backend == "face":
        raise FileNotFoundError(
            f"modelo de rosto ausente em {model_path}. Rode `cortes fetch-models`."
        )
    else:
        logger.info(
            "modelo de rosto ausente em %s; usando detecção por movimento "
            "(rode `cortes fetch-models` para habilitar o rastreio de rosto)",
            model_path,
        )

    if backend == "face":
        return [face] if face else []
    return [d for d in (face, MotionDetector()) if d is not None]


# --------------------------------------------------------------------------
# Planejamento do recorte
# --------------------------------------------------------------------------


def plan_for_clip(
    media: MediaInfo,
    start: float,
    end: float,
    config: ReframeConfig,
    render: RenderConfig,
) -> CropPlan:
    backend = (config.backend or "auto").strip().lower()
    if backend in ("center", "none", "static"):
        return plan_center(media, render)
    try:
        return _plan_with_tracking(media, start, end, config, render)
    except Exception as exc:
        logger.warning("rastreio falhou (%s); usando recorte central", exc)
        return plan_center(media, render, backend="center:fallback")


def _plan_with_tracking(
    media: MediaInfo,
    start: float,
    end: float,
    config: ReframeConfig,
    render: RenderConfig,
) -> CropPlan:
    import cv2

    width, height = crop_size(media, render)
    max_x = max(0, media.width - width)
    y = _even((media.height - height) / 2)
    if max_x == 0:
        # Fonte já é vertical ou mais estreita que o alvo: não há para onde pan.
        return plan_center(media, render, backend="center:sem-margem")

    # Trabalha numa versão reduzida: nem rosto nem movimento precisam de 1080p.
    scale = min(1.0, 480.0 / max(1, media.width))
    small_size = (int(media.width * scale), int(media.height * scale))
    detectors = build_detectors(config, small_size)
    if not detectors:
        return plan_center(media, render)

    capture = cv2.VideoCapture(media.path)
    if not capture.isOpened():
        raise RuntimeError(f"não consegui abrir {media.path} no OpenCV")

    step = 1.0 / max(0.5, config.sample_fps)
    tracks: dict[str, list[tuple[float, float | None]]] = {d.name: [] for d in detectors}

    try:
        for timestamp, frame in iter_frames(capture, start, end, step, media.fps):
            small = cv2.resize(frame, small_size) if scale < 1.0 else frame
            for detector in detectors:
                tracks[detector.name].append((timestamp - start, detector.center_x(small, scale)))
    finally:
        capture.release()

    chosen = pick_track(tracks, [d.name for d in detectors])
    if chosen is None:
        tried = "+".join(d.name for d in detectors)
        return plan_center(media, render, backend=f"center:{tried}-sem-alvo")

    name, samples, hits = chosen
    keyframes = smooth_path(samples, width, max_x, config)
    return CropPlan(
        width=width,
        height=height,
        keyframes=[CropKeyframe(t=round(kt, 2), x=kx, y=y) for kt, kx in keyframes],
        backend=name,
        faces_found=hits,
    )


# Um detector só é levado a sério se achou alvo nesta fração das amostras;
# abaixo disso o caminho seria quase todo "última posição conhecida".
MIN_HIT_RATIO = 0.2


def pick_track(
    tracks: dict[str, list[tuple[float, float | None]]], preference: list[str]
) -> tuple[str, list[tuple[float, float | None]], int] | None:
    """Escolhe o primeiro detector, na ordem de preferência, que achou alvo o bastante."""
    for name in preference:
        samples = tracks.get(name) or []
        if not samples:
            continue
        hits = sum(1 for _, center in samples if center is not None)
        if hits and hits >= MIN_HIT_RATIO * len(samples):
            return name, samples, hits
    return None


def iter_frames(capture, start: float, end: float, step: float, fps: float):
    """Percorre o trecho decodificando em sequência e entregando 1 quadro a cada ``step``.

    Buscar por tempo a cada amostra (``set(CAP_PROP_POS_MSEC)``) parece mais
    barato, mas o OpenCV encosta a busca no keyframe anterior — com GOP de
    vários segundos, amostras seguidas caem no mesmo quadro e a diferença
    entre elas dá zero. Ler em sequência e descartar com ``grab()`` custa
    decodificação, mas é o que dá timestamp confiável.
    """
    import cv2

    fps = fps if fps and fps > 0 else 30.0
    # Recua para pegar o keyframe anterior ao início; o descarte alinha o resto.
    capture.set(cv2.CAP_PROP_POS_MSEC, max(0.0, start - 10.0) * 1000.0)

    index = 0
    next_sample = start
    while True:
        if not capture.grab():
            return
        position = capture.get(cv2.CAP_PROP_POS_MSEC) / 1000.0
        if position <= 0:
            # Container sem timestamp confiável: cai para contagem de quadros.
            position = max(0.0, start - 10.0) + index / fps
        index += 1

        if position > end:
            return
        if position + 1e-6 < next_sample:
            continue

        ok, frame = capture.retrieve()
        if not ok or frame is None:
            return
        yield position, frame
        next_sample = max(position, next_sample) + step


def smooth_path(
    samples: list[tuple[float, float | None]],
    crop_width: int,
    max_x: int,
    config: ReframeConfig,
) -> list[tuple[float, int]]:
    """Transforma centros crus num caminho de câmera assistível.

    Três freios, nesta ordem: zona morta (ignora tremida pequena), suavização
    exponencial (tira o solavanco) e limite de velocidade (impede chicote
    quando a detecção pula de um alvo para outro).
    """
    # Preenche buracos (quadros sem alvo) com o último centro conhecido.
    filled: list[tuple[float, float]] = []
    last_known: float | None = None
    for t, center in samples:
        if center is not None:
            last_known = center
        if last_known is not None:
            filled.append((t, last_known))
    if not filled:
        return [(0.0, _even(max_x / 2))]

    deadband_px = config.deadband * crop_width
    max_step_per_second = config.max_pan_per_second * crop_width
    tau = max(0.05, config.smoothing_tau)

    current = _clamp(filled[0][1] - crop_width / 2.0, 0, max_x)
    out: list[tuple[float, int]] = [(0.0, _even(current))]
    previous_t = filled[0][0]

    for t, center in filled[1:]:
        dt = max(1e-3, t - previous_t)
        previous_t = t
        desired = _clamp(center - crop_width / 2.0, 0, max_x)
        delta = desired - current
        if abs(delta) > deadband_px:
            # Só persegue o que passou da zona morta, para a câmera não vibrar.
            target = desired - (deadband_px if delta > 0 else -deadband_px)
            # Suavização exponencial em tempo contínuo: o quanto anda depende
            # do intervalo real entre amostras, não da contagem de amostras.
            alpha = 1.0 - math.exp(-dt / tau)
            move = (target - current) * alpha
            budget = max_step_per_second * dt
            move = _clamp(move, -budget, budget)
            current = _clamp(current + move, 0, max_x)
        x = _even(current)
        if x != out[-1][1]:
            out.append((t, x))

    return out


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def sendcmd_script(plan: CropPlan) -> str:
    """Comandos de ``crop`` para o ffmpeg, um por keyframe."""
    lines = []
    for kf in plan.keyframes:
        lines.append(f"{max(0.0, kf.t):.2f} crop x {kf.x};")
        lines.append(f"{max(0.0, kf.t):.2f} crop y {kf.y};")
    return "\n".join(lines) + "\n"


def fetch_yunet(destination: Path | None = None, *, url: str = YUNET_URL) -> Path:
    """Baixa o modelo de detecção de rosto para o cache local."""
    import urllib.request

    target = destination or yunet_model_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_suffix(".part")
    with urllib.request.urlopen(url, timeout=120) as response, tmp.open("wb") as handle:
        handle.write(response.read())
    if tmp.stat().st_size < 100_000:
        tmp.unlink(missing_ok=True)
        raise RuntimeError(f"download de {url} veio truncado")
    tmp.replace(target)
    return target
