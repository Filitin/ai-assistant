# src/voice/stt.py
"""
Speech-to-text via faster-whisper (CTranslate2).

Loads a Whisper model once and transcribes 16 kHz mono float32 audio with
automatic language detection — one multilingual model covers RU/UK/EN, so the
language is never hard-coded. Uses the GPU when available, falls back to CPU
only on a real CUDA error.

Run directly to load the model and report the device (no microphone needed):
    python -m src.voice.stt                                # large-v3
    $env:WHISPER_MODEL="tiny"; python -m src.voice.stt     # quick GPU smoke test
"""

from __future__ import annotations

import importlib.util
import os
import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent

# --- Hugging Face cache: keep models in-repo, avoid the broken C: cache, and
# silence the Windows symlink warning. MUST run before importing faster_whisper.
os.environ.setdefault("HF_HOME", str(_PROJECT_ROOT / "models" / "hf"))
os.environ.setdefault("HF_HUB_DISABLE_XET", "1")
os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")


def _add_nvidia_dll_dirs() -> None:
    """
    On Windows, let CTranslate2 find the cuBLAS/cuDNN DLLs shipped by the
    nvidia-*-cu12 pip packages. Windows doesn't auto-discover them the way Linux
    does. No-op if the packages aren't installed — the model then loads on CPU.
    """
    if not sys.platform.startswith("win"):
        return
    for pkg in ("nvidia.cublas", "nvidia.cudnn"):
        try:
            spec = importlib.util.find_spec(pkg)
        except ModuleNotFoundError:
            spec = None
        if spec and spec.submodule_search_locations:
            bin_dir = Path(spec.submodule_search_locations[0]) / "bin"
            if bin_dir.is_dir():
                os.add_dll_directory(str(bin_dir))


_add_nvidia_dll_dirs()

from faster_whisper import WhisperModel, download_model  # noqa: E402

# --- Configuration ------------------------------------------------------------
MODEL_SIZE   = os.environ.get("WHISPER_MODEL", "large-v3")
_GPU_COMPUTE = "int8_float16"   # ~1.5 GB VRAM, near-fp16 quality on the 4070 Super
_CPU_COMPUTE = "int8"

_model: WhisperModel | None = None
_device = "unloaded"


def _load_model() -> WhisperModel:
    """Load the model once (singleton), preferring GPU with a CPU fallback."""
    global _model, _device
    if _model is not None:
        return _model

    # Resolve the model to a local path FIRST. Downloading separately means a
    # download/filesystem failure surfaces as itself instead of being mistaken
    # for a GPU problem (which silently forced CPU before).
    model_path = download_model(MODEL_SIZE)

    try:
        _model = WhisperModel(model_path, device="cuda", compute_type=_GPU_COMPUTE)
        _device = "cuda"
    except Exception as e:
        print(f"[stt] CUDA load failed ({type(e).__name__}: {e}); falling back to CPU.")
        _model = WhisperModel(model_path, device="cpu", compute_type=_CPU_COMPUTE)
        _device = "cpu"

    print(f"[stt] Whisper '{MODEL_SIZE}' loaded on {_device}.")
    return _model


def transcribe(audio, language: str | None = None) -> tuple[str, str]:
    """
    Transcribe 16 kHz mono float32 audio (a numpy array) to text.

    language: leave None for auto-detection (RU/UK/EN). Only set it to force a
    language — the assistant never hard-codes one.

    Returns (text, detected_language).
    """
    model = _load_model()
    segments, info = model.transcribe(
        audio,
        language=language,
        beam_size=5,
        vad_filter=True,   # trim leading/trailing silence from push-to-talk clips
    )
    text = " ".join(seg.text.strip() for seg in segments).strip()
    return text, info.language


def warm_up() -> None:
    """Load the model now so the first real utterance isn't slowed by a cold load."""
    _load_model()


if __name__ == "__main__":
    warm_up()
    print(f"[stt] Ready on {_device}.")