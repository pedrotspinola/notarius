"""Unit tests for power.keep_awake, with a fake Windows kernel32.

Plain asserts, no test framework:  uv run python tests/test_keep_awake.py

Runs anywhere: it pretends to be Windows and records the calls instead of
making them.  What matters is that sleep is blocked during the block and
released afterwards, including when the job fails.
"""
import ctypes
import sys
from pathlib import Path



from notarius.power import ES_CONTINUOUS, ES_SYSTEM_REQUIRED, keep_awake


class FakeKernel32:
    def __init__(self):
        self.calls = []

    def SetThreadExecutionState(self, flags):
        self.calls.append(flags)
        return 1


class FakeWindll:
    def __init__(self):
        self.kernel32 = FakeKernel32()


real_platform = sys.platform
had_windll = hasattr(ctypes, "windll")
try:
    sys.platform = "win32"

    # Normal run: block sleep on entry, release on exit
    ctypes.windll = FakeWindll()
    calls = ctypes.windll.kernel32.calls
    with keep_awake():
        assert calls == [ES_CONTINUOUS | ES_SYSTEM_REQUIRED], calls
    assert calls == [ES_CONTINUOUS | ES_SYSTEM_REQUIRED, ES_CONTINUOUS], calls

    # A failing job must still release the block
    ctypes.windll = FakeWindll()
    calls = ctypes.windll.kernel32.calls
    try:
        with keep_awake():
            raise RuntimeError("job failed")
    except RuntimeError:
        pass
    assert calls[-1] == ES_CONTINUOUS, calls

    # Not Windows: no calls at all
    sys.platform = "linux"
    ctypes.windll = FakeWindll()
    with keep_awake():
        pass
    assert ctypes.windll.kernel32.calls == []
finally:
    sys.platform = real_platform
    if not had_windll:
        del ctypes.windll


