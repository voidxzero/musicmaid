import os
import shutil
import subprocess
from pathlib import Path

import pytest

HAVE_FFMPEG = shutil.which("ffmpeg") is not None


def make_audio(path: Path, seed: int = 1, seconds: int = 30, args: tuple[str, ...] = ()) -> Path:
    """Synthesize distinct, fingerprintable audio with ffmpeg."""
    path.parent.mkdir(parents=True, exist_ok=True)
    expr = (f"0.3*sin(2*PI*(220+{seed}*37)*t*(1+0.1*sin(2*PI*0.{seed}*t)))"
            f"+0.2*sin(2*PI*(330+{seed}*13)*t)*gt(sin(2*PI*({seed}+1)*0.7*t),0)"
            f"+0.1*sin(2*PI*(110*mod(floor(t*{seed}/2+3),5)+200)*t)")
    subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-f", "lavfi", "-i",
                    f"aevalsrc='{expr}':s=22050:d={seconds}", *args, str(path)], check=True)
    return path


@pytest.fixture
def home(tmp_path, monkeypatch):
    """Isolated settings/database directory."""
    h = tmp_path / "home"
    monkeypatch.setenv("MUSICMAID_HOME", str(h))
    import musicmaid.config as config
    monkeypatch.setattr(config, "_settings", None)
    return h


@pytest.fixture
def cover_jpg(tmp_path) -> bytes:
    from PIL import Image
    import io
    buf = io.BytesIO()
    Image.new("RGB", (600, 600), (200, 30, 30)).save(buf, "JPEG")
    return buf.getvalue()


requires_ffmpeg = pytest.mark.skipif(not HAVE_FFMPEG, reason="ffmpeg not installed")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
