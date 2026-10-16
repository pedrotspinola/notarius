"""Entry point of a job process: ``python -m notarius.worker <status.json>``."""

from __future__ import annotations

import logging
import sys
import traceback
from pathlib import Path

from notarius.jobs import read_status, write_status


def main() -> None:
    from notarius import env

    env.configure()
    status_path = Path(sys.argv[1])
    status = read_status(status_path)
    if status is None:
        sys.exit("unreadable job file")
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(name)s %(levelname)s: %(message)s")

    def progress(stage: str, message: str) -> None:
        status.stage, status.message = stage, message
        write_status(status_path, status)

    from notarius.power import keep_awake

    try:
        with keep_awake():
            status.result = _run(status.kind, status.params, progress)
        status.state, status.stage = "done", "done"
    except Exception as exc:  # reported to the user, full trace in the log
        traceback.print_exc()
        status.state = "failed"
        status.error = _friendly_error(exc)
    write_status(status_path, status)


def _friendly_error(exc: Exception) -> str:
    text = str(exc)
    if "out of memory" in text.lower():
        return "out_of_memory"
    return f"{type(exc).__name__}: {text}"[:500]


def _run(kind: str, params: dict, progress) -> dict:
    if kind == "transcribe":
        import time

        from notarius.pipeline import run
        from notarius.settings import run_settings
        from notarius.tuning import load_tuning, save_tuning

        settings = run_settings()
        source = Path(params["source"])
        attendees = params.get("attendees") or []
        start = time.monotonic()
        try:
            path = run(source, settings, attendees, progress=progress)
        except Exception as exc:
            if settings.device != "cuda" or "out of memory" not in str(exc).lower():
                raise
            # The graphics card is shared with other programs; the
            # processor is slower but always has room.
            progress("retry_cpu", "Not enough video memory; continuing on the processor...")
            settings = run_settings(device="cpu")
            start = time.monotonic()
            path = run(source, settings, attendees, progress=progress)
        tuning = load_tuning()
        if tuning is not None and params.get("duration") and settings.device == tuning.device:
            tuning.record_run(params.get("kind", "file"), params["duration"],
                              time.monotonic() - start)
            save_tuning(tuning)
        return {"meeting": path.stem}

    if kind == "enroll":
        from notarius.config import PROFILES_DIR
        from notarius.enroll import execute, plan_enrollment
        from notarius.meeting import Meeting
        from notarius.settings import run_settings

        meeting = Meeting.load(Path(params["meeting_path"]))
        wanted = set(params["people"])
        plans = [p for p in plan_enrollment(meeting, PROFILES_DIR) if p.person in wanted]
        outcomes = execute(plans, PROFILES_DIR, run_settings().device,
                           progress=lambda person: progress("enroll", person))
        from notarius.enroll import record_learned

        record_learned(Path(params["meeting_path"]), outcomes)
        return {"outcomes": [
            {"person": o.plan.person, "profile": o.plan.target_profile,
             "ok": o.profile_path is not None, "reason": o.reason,
             "closest_other": o.closest_other, "conflicts": o.conflicts}
            for o in outcomes
        ]}

    if kind == "enroll-files":
        from notarius.config import PROFILES_DIR
        from notarius.profiles import enroll_from_files
        from notarius.settings import run_settings

        progress("enroll", params["name"])
        files = params.get("files")
        if params.get("whatsapp_dir"):
            from notarius.whatsapp import find_audio_by_sender, select_enrollment_files

            files = select_enrollment_files(
                find_audio_by_sender(Path(params["whatsapp_dir"]), params["sender"]))
            if not files:
                raise ValueError("no_voice_messages")
        enroll_from_files(params["profile"], files, PROFILES_DIR, run_settings().device)
        return {"profile": params["profile"], "files": len(files)}

    if kind == "setup":
        from notarius.setup import run_setup

        return run_setup(progress)

    if kind == "tune":
        from notarius.tuning import run_speed_test

        tuning = run_speed_test(progress)
        return {"seconds_per_audio_minute": tuning.seconds_per_audio_minute,
                "whisper_model": tuning.whisper_model}

    raise ValueError(f"unknown job kind {kind!r}")


if __name__ == "__main__":
    main()
