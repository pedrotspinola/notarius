"""Build the test recordings from public-domain LibriVox audio.

Reads tests/fixtures/sources.json (which clips, cut where) and writes:

  tests/fixtures/voices/Voz NN.opus   enrollment sample, Voz 01-11 (~45 s)
  tests/fixtures/meeting.opus         a synthetic meeting: turns of
                                      Voz 01-04 (enrolled) and Voz 12
                                      (never enrolled), 0.6 s apart
  tests/fixtures/meeting.truth.json   who speaks when in meeting.opus

Needs ffmpeg and network access to archive.org.  The output is committed,
so tests never download anything.

    uv run python tools/build_test_fixtures.py
"""

from __future__ import annotations

import json
import subprocess
import tempfile
import time
from pathlib import Path

FIXTURES = Path(__file__).resolve().parents[1] / "tests" / "fixtures"
GAP = 0.6  # seconds of silence between meeting turns
MEETING_VOICES = ["Voz 01", "Voz 02", "Voz 03", "Voz 04", "Voz 12"]
UNENROLLED = "Voz 12"
# Speaking order, never the same voice twice in a row.  The unenrolled
# voice speaks five times, so that after it is named in review it has
# enough clean speech (well over the 45 s minimum) to be enrolled.
ORDER = [0, 1, 4, 2, 3, 4, 0, 2, 4, 1, 3, 4, 1, 0, 4, 3, 2]
ENCODE = ["-ac", "1", "-ar", "16000", "-c:a", "libopus", "-b:a", "32k"]


def cut(url: str, start: float, end: float, out: Path) -> None:
    """Cut a clip straight from the remote MP3.

    archive.org mirrors sometimes answer 500; retry, then try the same
    chapter's full-bitrate file (same recording, same timing).
    """
    candidates = [url, url.replace("_64kb.mp3", ".mp3")]
    for attempt in range(6):
        source = candidates[attempt % 2]
        result = subprocess.run(
            ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
             "-ss", f"{start:.2f}", "-t", f"{end - start:.2f}", "-i", source,
             "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le", str(out)],
            capture_output=True, text=True,
        )
        if result.returncode == 0:
            return
        print(f"  retry {attempt + 1}: {source} ({result.stderr.strip()[:80]})")
        time.sleep(5)
    raise RuntimeError(f"could not download {url}")


def concat(parts: list[Path], out: Path, gap: float = 0.0) -> None:
    """Join WAV parts with *gap* seconds of silence between them."""
    inputs, filters = [], []
    for i, p in enumerate(parts):
        inputs += ["-i", str(p)]
        filters.append(f"[{i}:a]apad=pad_dur={gap}[a{i}]" if gap else f"[{i}:a]anull[a{i}]")
    joined = "".join(f"[a{i}]" for i in range(len(parts)))
    graph = ";".join(filters) + f";{joined}concat=n={len(parts)}:v=0:a=1[out]"
    subprocess.run(
        ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", *inputs,
         "-filter_complex", graph, "-map", "[out]", *ENCODE, str(out)],
        check=True,
    )


def main() -> None:
    sources = json.loads((FIXTURES / "sources.json").read_text(encoding="utf-8"))
    voices = {v["name"]: v for v in sources["voices"]}
    (FIXTURES / "voices").mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        tmp_dir = Path(tmp)
        for name, v in voices.items():
            if name == UNENROLLED or (FIXTURES / "voices" / f"{name}.opus").is_file():
                continue  # already built (re-runs resume)
            parts = []
            for i, c in enumerate(v["enroll"]):
                part = tmp_dir / f"{name}-e{i}.wav"
                cut(c["url"], c["start"], c["end"], part)
                parts.append(part)
            concat(parts, FIXTURES / "voices" / f"{name}.opus")
            print("voice", name)

        turns, parts, t = [], [], 0.0
        used = {name: 0 for name in MEETING_VOICES}
        for idx in ORDER:
            name = MEETING_VOICES[idx]
            pool = voices[name]["meeting"]
            if name == UNENROLLED:
                pool = pool + voices[name]["enroll"]
            c = pool[used[name]]
            used[name] += 1
            part = tmp_dir / f"m{len(parts):02d}.wav"
            cut(c["url"], c["start"], c["end"], part)
            parts.append(part)
            dur = c["end"] - c["start"]
            turns.append({"speaker": name, "start": round(t, 2), "end": round(t + dur, 2)})
            t += dur + GAP
        concat(parts, FIXTURES / "meeting.opus", gap=GAP)
        (FIXTURES / "meeting.truth.json").write_text(
            json.dumps({"enrolled": [n for n in voices if n != UNENROLLED],
                        "unenrolled": [UNENROLLED], "turns": turns}, indent=1) + "\n",
            encoding="utf-8",
        )
        print(f"meeting: {len(turns)} turns, {t:.0f} s")


if __name__ == "__main__":
    main()
