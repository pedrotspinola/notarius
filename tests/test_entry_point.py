"""The shortcuts and the installer start Notarius as ``python -m notarius``."""

import subprocess
import sys

from notarius import __version__


def test_python_dash_m_notarius_runs():
    result = subprocess.run([sys.executable, "-m", "notarius", "--version"],
                            capture_output=True, text=True, timeout=120)
    assert result.returncode == 0, result.stderr
    assert __version__ in result.stdout
