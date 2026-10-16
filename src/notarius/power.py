"""Keep the computer from sleeping while a long job runs (Windows only).

A CPU transcription on a laptop takes hours, and Windows' idle sleep
stops it partway through.  SetThreadExecutionState asks Windows not to
sleep until the request is cleared, and needs no admin rights.  Closing
the lid still does whatever the power settings say.  On other systems
this does nothing.
"""

from __future__ import annotations

import contextlib
import sys
from collections.abc import Iterator

ES_CONTINUOUS = 0x80000000
ES_SYSTEM_REQUIRED = 0x00000001


@contextlib.contextmanager
def keep_awake() -> Iterator[None]:
    """Block idle sleep for the duration of the ``with`` block."""
    if sys.platform != "win32":
        yield
        return

    import ctypes

    kernel32 = ctypes.windll.kernel32
    kernel32.SetThreadExecutionState(ES_CONTINUOUS | ES_SYSTEM_REQUIRED)
    try:
        yield
    finally:
        kernel32.SetThreadExecutionState(ES_CONTINUOUS)
