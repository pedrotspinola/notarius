"""Where downloaded models live, set before any model library is imported.

Hugging Face and pyannote default to caches in the user's home folder.
Notarius keeps them inside its program folder instead, so uninstalling
removes them, and once setup has downloaded everything it switches the
libraries to offline mode: a run never stalls on the network.
"""

from __future__ import annotations

import os

from notarius.config import APP_DIR

MODELS_DIR = APP_DIR / "models"
MODELS_READY = MODELS_DIR / "ready"  # written by setup when every model is present


def configure(offline: bool | None = None) -> None:
    """Point model caches at the program folder (existing settings win).

    Also puts the ffmpeg the installer downloaded on PATH for this process
    and its children, so nothing outside the program folder is changed.
    """
    ffmpeg_dir = APP_DIR / "ffmpeg"
    if (ffmpeg_dir / "ffmpeg.exe").is_file() or (ffmpeg_dir / "ffmpeg").is_file():
        path = os.environ.get("PATH", "")
        if str(ffmpeg_dir) not in path.split(os.pathsep):
            os.environ["PATH"] = str(ffmpeg_dir) + os.pathsep + path
    os.environ.setdefault("HF_HOME", str(MODELS_DIR / "huggingface"))
    os.environ.setdefault("PYANNOTE_CACHE", str(MODELS_DIR / "pyannote"))
    os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")
    os.environ.setdefault("HF_HUB_DISABLE_TELEMETRY", "1")
    # Everything Notarius downloads is public: never send a stored token.
    os.environ.setdefault("HF_HUB_DISABLE_IMPLICIT_TOKEN", "1")
    if offline is None:
        offline = MODELS_READY.is_file()
    if offline:
        os.environ.setdefault("HF_HUB_OFFLINE", "1")
