"""sentence-transformers wrapper.

The model (~90 MB) is lazy-loaded on first use and cached process-wide so we
don't pay the load cost more than once. The first-ever load downloads the model
from the Hugging Face hub; we expose byte-level progress + ETA so the UI can
show a progress bar instead of appearing frozen. Embedding is CPU-only.
"""

from __future__ import annotations

import threading
import time
from typing import Dict, List, Sequence

MODEL_NAME = "all-MiniLM-L6-v2"
MODEL_REPO = "sentence-transformers/all-MiniLM-L6-v2"

_model = None
_model_lock = threading.Lock()

# --- Download / load progress -------------------------------------------------
# state: idle | downloading | loading | ready | error
_progress: Dict[str, object] = {
    "state": "idle",
    "percent": 0.0,
    "downloaded_mb": 0.0,
    "total_mb": 0.0,
    "eta_seconds": None,
    "message": "",
}
_progress_lock = threading.Lock()
_prepare_thread: threading.Thread | None = None
# Per-tqdm-bar byte counters: id -> {"n": int, "total": int}
_bars: Dict[int, Dict[str, int]] = {}
_dl_start: float | None = None


def _set_progress(**kwargs) -> None:
    with _progress_lock:
        _progress.update(kwargs)


def get_progress() -> Dict[str, object]:
    """Return a snapshot of the current download/load progress."""
    with _progress_lock:
        return dict(_progress)


def _recompute_progress() -> None:
    """Aggregate all active download bars into overall percent + ETA."""
    total = sum(b["total"] for b in _bars.values() if b["total"])
    done = sum(min(b["n"], b["total"]) for b in _bars.values() if b["total"])
    if total <= 0:
        return
    percent = 100.0 * done / total
    eta = None
    if _dl_start is not None and done > 0:
        elapsed = time.time() - _dl_start
        speed = done / elapsed if elapsed > 0 else 0
        if speed > 0:
            eta = max(0.0, (total - done) / speed)
    _set_progress(
        state="downloading",
        percent=round(percent, 1),
        downloaded_mb=round(done / 1_048_576, 1),
        total_mb=round(total / 1_048_576, 1),
        eta_seconds=round(eta, 1) if eta is not None else None,
        message="Downloading language model…",
    )


def _make_tqdm_class():
    """A tqdm subclass that reports byte progress into the shared state."""
    from tqdm.auto import tqdm as _base

    class _ProgressTqdm(_base):  # type: ignore[misc]
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self._key = id(self)
            if self.total:
                with _progress_lock:
                    _bars[self._key] = {"n": int(self.n or 0), "total": int(self.total)}
                _recompute_progress()

        def update(self, n=1):
            ret = super().update(n)
            if self.total:
                with _progress_lock:
                    _bars[self._key] = {"n": int(self.n or 0), "total": int(self.total)}
                _recompute_progress()
            return ret

        def close(self):
            if self.total:
                with _progress_lock:
                    _bars[self._key] = {"n": int(self.total), "total": int(self.total)}
                _recompute_progress()
            return super().close()

    return _ProgressTqdm


def _download_model() -> None:
    """Download the model files to the local HF cache, tracking progress.

    We restrict to the PyTorch + tokenizer files SentenceTransformer actually
    loads, skipping the heavy ONNX/OpenVINO variants in the repo (which would
    otherwise balloon the download to hundreds of MB).
    """
    global _dl_start
    from huggingface_hub import snapshot_download

    with _progress_lock:
        _bars.clear()
    _dl_start = time.time()
    _set_progress(state="downloading", percent=0.0, message="Downloading language model…")
    snapshot_download(
        repo_id=MODEL_REPO,
        tqdm_class=_make_tqdm_class(),
        allow_patterns=[
            "*.json",
            "*.txt",
            "vocab.txt",
            "model.safetensors",
            "modules.json",
            "sentence_bert_config.json",
            "tokenizer.json",
            "1_Pooling/*",
        ],
        ignore_patterns=["onnx/*", "openvino/*", "*.onnx", "*.bin", "tf_*", "rust_*"],
    )


def _is_cached() -> bool:
    """True if the model is already fully present in the local HF cache."""
    try:
        from huggingface_hub import snapshot_download

        snapshot_download(
            repo_id=MODEL_REPO,
            local_files_only=True,
            allow_patterns=[
                "*.json",
                "*.txt",
                "vocab.txt",
                "model.safetensors",
                "modules.json",
                "sentence_bert_config.json",
                "tokenizer.json",
                "1_Pooling/*",
            ],
            ignore_patterns=["onnx/*", "openvino/*", "*.onnx", "*.bin", "tf_*", "rust_*"],
        )
        return True
    except Exception:
        return False


def _load_model_blocking():
    """Download (if needed) + construct the SentenceTransformer model."""
    global _model
    from sentence_transformers import SentenceTransformer

    if _is_cached():
        # Already on disk — no network download, just load it.
        _set_progress(
            state="loading",
            percent=100.0,
            message="Model already downloaded — loading into memory…",
        )
    else:
        try:
            _download_model()
        except Exception as exc:  # network/cache issues — fall through to direct load
            _set_progress(message=f"Download note: {exc}")
        _set_progress(state="loading", message="Loading model into memory…")

    _model = SentenceTransformer(MODEL_NAME)
    _set_progress(
        state="ready", percent=100.0, eta_seconds=0.0, message="Model ready."
    )
    return _model


def prepare_model() -> Dict[str, object]:
    """Start preparing the model in a background thread (idempotent).

    Returns the current progress immediately so the UI can begin polling.
    """
    global _prepare_thread
    with _model_lock:
        if _model is not None:
            _set_progress(state="ready", percent=100.0, message="Model ready.")
            return get_progress()
        if _prepare_thread is not None and _prepare_thread.is_alive():
            return get_progress()

        def _worker():
            try:
                with _model_lock:
                    if _model is None:
                        _load_model_blocking()
            except Exception as exc:  # pragma: no cover - surfaced to UI
                _set_progress(state="error", message=f"Model preparation failed: {exc}")

        _prepare_thread = threading.Thread(target=_worker, daemon=True)
        _prepare_thread.start()
    return get_progress()


def get_model():
    """Return the shared SentenceTransformer model, loading it once (blocking)."""
    global _model
    if _model is None:
        with _model_lock:
            if _model is None:
                _load_model_blocking()
    return _model



def embed_texts(texts: Sequence[str]) -> List[List[float]]:
    """Embed a batch of strings into vectors."""
    if not texts:
        return []
    model = get_model()
    vectors = model.encode(
        list(texts),
        show_progress_bar=False,
        convert_to_numpy=True,
        normalize_embeddings=True,
    )
    return [v.tolist() for v in vectors]


def embed_text(text: str) -> List[float]:
    """Embed a single string."""
    return embed_texts([text])[0]
