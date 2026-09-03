import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="session")
def sample_video(tmp_path_factory) -> Path:
    """Vídeo curto de teste, gerado uma vez por sessão."""
    destino = tmp_path_factory.mktemp("fonte-web") / "sample.mp4"
    subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts" / "make_sample_video.py"),
            str(destino),
            "--duration",
            "45",
        ],
        check=True,
        capture_output=True,
    )
    return destino
