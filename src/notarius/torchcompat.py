"""PyTorch 2.6+ compatibility for loading pyannote checkpoints.

PyTorch 2.6 made ``torch.load`` default to ``weights_only=True``, which
rejects the pytorch_lightning objects stored in pyannote checkpoints.  While
those trusted checkpoints load, both ``torch.load`` and
``torch.serialization.load`` (pyannote may reference either) are swapped for
versions that force ``weights_only=False`` — even when the caller passes
``None`` explicitly, as lightning does.
"""

from __future__ import annotations

import contextlib
from collections.abc import Iterator

import torch

_original_torch_load = torch.load
_original_serial_load = torch.serialization.load


def _make_patched(original):
    def _patched(*args, **kwargs):
        if not kwargs.get("weights_only"):
            kwargs["weights_only"] = False
        return original(*args, **kwargs)

    return _patched


@contextlib.contextmanager
def trusted_checkpoints() -> Iterator[None]:
    """Allow full unpickling of checkpoints inside the ``with`` block."""
    torch.load = _make_patched(_original_torch_load)
    torch.serialization.load = _make_patched(_original_serial_load)
    try:
        yield
    finally:
        torch.load = _original_torch_load
        torch.serialization.load = _original_serial_load
