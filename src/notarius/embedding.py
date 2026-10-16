"""Speaker embeddings: voice profiles and voice comparison.

Wraps pyannote's speaker embedding model (the same model the diarization
pipeline uses internally) and provides cosine similarity between
embeddings.  The model is loaded through a context manager so memory is
released as soon as a stage is done.
"""

from __future__ import annotations

import gc
import logging
from pathlib import Path
from types import TracebackType

import numpy as np
import torch
from pyannote.audio import Inference, Model

from notarius.config import EMBEDDING_MODEL
from notarius.torchcompat import trusted_checkpoints

logger = logging.getLogger(__name__)


class EmbeddingModel:
    """Loads the embedding model for the duration of a ``with`` block::

        with EmbeddingModel("cpu") as emb:
            vector = emb.extract("clip.wav")
    """

    def __init__(self, device: str = "cpu", model_id: str = EMBEDDING_MODEL) -> None:
        self._device = device
        self._model_id = model_id
        self._inference: Inference | None = None

    def __enter__(self) -> EmbeddingModel:
        self.load()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        self.unload()

    def load(self) -> None:
        if self._inference is not None:
            return
        logger.info("Loading speaker embedding model (%s)...", self._model_id)
        with trusted_checkpoints():
            # The model is not gated, so no token is needed.
            model = Model.from_pretrained(self._model_id)
        if model is None:
            raise RuntimeError(
                f"Could not load the speaker embedding model '{self._model_id}'."
            )
        self._inference = Inference(model, window="whole")
        self._inference.to(torch.device(self._device))

    def unload(self) -> None:
        if self._inference is None:
            return
        del self._inference
        self._inference = None
        gc.collect()
        if torch.cuda.is_available():
            torch.cuda.empty_cache()

    def _require_loaded(self) -> Inference:
        if self._inference is None:
            raise RuntimeError(
                "Embedding model is not loaded. Use it as a context manager."
            )
        return self._inference

    def extract(self, audio_path: str | Path) -> np.ndarray:
        """Embedding (1-D vector) of a whole audio file."""
        inference = self._require_loaded()
        return inference(str(audio_path))

    def extract_waveform(self, waveform: np.ndarray, sample_rate: int) -> np.ndarray:
        """Embedding of an in-memory mono waveform (samples in [-1, 1]).

        pyannote requires a float32 2-D ``(channel, time)`` tensor on the
        CPU; it moves it to the device itself.
        """
        inference = self._require_loaded()
        tensor = torch.from_numpy(np.ascontiguousarray(waveform, dtype=np.float32))[None, :]
        return inference({"waveform": tensor, "sample_rate": sample_rate})


def cosine_similarity(a: np.ndarray, b: np.ndarray) -> float:
    """Cosine similarity in [-1, 1]; 0.0 when either vector is all zeros."""
    if a.shape != b.shape:
        raise ValueError(
            f"Embedding size mismatch: {a.shape} vs {b.shape} — a profile "
            "from a different embedding model?"
        )
    norm_a = np.linalg.norm(a)
    norm_b = np.linalg.norm(b)
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    return float(np.dot(a, b) / (norm_a * norm_b))
