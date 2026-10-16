"""Command line for Notarius (agents, tests, advanced users).

Most people use the app (``notarius app``); everything it does is also
available here.
"""

from __future__ import annotations

import argparse
import json
import logging
import shutil
import sys
from pathlib import Path

from notarius import __version__
from notarius.aliases import ALIASES_FILE
from notarius.config import (
    CPU_BATCH_SIZE,
    CPU_COMPUTE_TYPE,
    FFMPEG_MISSING,
    GPU_BATCH_SIZE,
    GPU_COMPUTE_TYPE,
    PROFILES_DIR,
    WHISPER_MODEL,
)

logger = logging.getLogger("notarius")


def _add_device_args(p: argparse.ArgumentParser, whisper: bool) -> None:
    p.add_argument("--device", default=None,
                   help="cuda or cpu (default: cuda if available, else cpu)")
    if whisper:
        p.add_argument("--compute-type", default=None,
                       choices=["float16", "int8", "int8_float32", "float32"],
                       help=f"default: {GPU_COMPUTE_TYPE} on cuda, {CPU_COMPUTE_TYPE} on cpu")
        p.add_argument("--batch-size", type=int, default=None,
                       help=f"default: {GPU_BATCH_SIZE} on cuda, {CPU_BATCH_SIZE} on cpu")
        p.add_argument("--model", default=None,
                       help=f"whisper model (default: tuned setting, else {WHISPER_MODEL})")


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="notarius",
        description="Transcribe meetings and identify who is speaking.",
    )
    parser.add_argument("--version", action="version", version=f"notarius {__version__}")
    parser.add_argument("-v", "--verbose", action="store_true", help="debug logging")
    sub = parser.add_subparsers(dest="command")

    p = sub.add_parser("app", help="open the app in the browser (default)")
    p.add_argument("--port", type=int, default=None)
    p.add_argument("--no-browser", action="store_true")

    p = sub.add_parser("setup", help="download models and measure this computer")
    p.add_argument("--no-speed-test", action="store_true")

    p = sub.add_parser("transcribe", help="transcribe a recording or a Zoom folder")
    p.add_argument("source", type=Path, help="audio/video file or Zoom recording folder")
    p.add_argument("--attendees", default=None, metavar="NAMES",
                   help='comma-separated people present, e.g. "Odete,Vicente"')
    p.add_argument("--out-dir", type=Path, default=None, help="where to save the meeting")
    _add_device_args(p, whisper=True)

    p = sub.add_parser("enroll", help="create a voice profile from audio files")
    p.add_argument("name")
    p.add_argument("audio_files", nargs="+", type=Path)
    p.add_argument("--variant", default=None, metavar="TAG",
                   help="save as an extra profile Name__TAG")
    _add_device_args(p, whisper=False)

    p = sub.add_parser("enroll-whatsapp", help="create a voice profile from a WhatsApp export")
    p.add_argument("name")
    p.add_argument("export_dir", type=Path)
    p.add_argument("--sender", default=None, help="sender name in the chat (default: NAME)")
    p.add_argument("--variant", default=None, metavar="TAG")
    _add_device_args(p, whisper=False)

    p = sub.add_parser("enroll-meeting", help="create voice profiles from a reviewed meeting")
    p.add_argument("meeting", type=Path, help="the meeting's .json file")
    p.add_argument("--dry-run", action="store_true", help="show the plan only")
    _add_device_args(p, whisper=False)

    p = sub.add_parser("profiles", help="list, rename or delete voice profiles")
    ps = p.add_subparsers(dest="profiles_command")
    d = ps.add_parser("delete")
    d.add_argument("name")
    d.add_argument("--all", action="store_true", dest="delete_all",
                   help="delete the person and every variant")
    r = ps.add_parser("rename")
    r.add_argument("old")
    r.add_argument("new")

    p = sub.add_parser("aliases", help="other names people appear under")
    asub = p.add_subparsers(dest="aliases_command")
    a = asub.add_parser("add")
    a.add_argument("person")
    a.add_argument("display_name")
    a = asub.add_parser("remove")
    a.add_argument("person")
    a.add_argument("display_name")

    return parser


def _device(args: argparse.Namespace) -> str:
    if args.device:
        return args.device
    from notarius.config import default_device

    return default_device()


def _run_settings(args: argparse.Namespace):
    from notarius.settings import run_settings

    settings = run_settings(args.device, args.compute_type, args.batch_size, args.model)
    if args.out_dir:
        settings.meetings_dir = args.out_dir
    return settings


def _cmd_transcribe(args: argparse.Namespace) -> None:
    from notarius.pipeline import run

    settings = _run_settings(args)
    print(f"Device: {settings.device}, model {settings.whisper_model}, "
          f"{settings.compute_type}, batch {settings.batch_size}", file=sys.stderr)
    attendees = [n.strip() for n in (args.attendees or "").split(",") if n.strip()]
    path = run(args.source, settings, attendees,
               progress=lambda stage, msg: print(msg, file=sys.stderr))
    print(f"Meeting saved: {path}", file=sys.stderr)
    print(f"Transcript:    {path.with_suffix('.txt')}", file=sys.stderr)


def _profile_name(name: str, variant: str | None) -> str:
    from notarius.config import VARIANT_SEPARATOR, validate_base_name

    validate_base_name(name)
    return f"{name}{VARIANT_SEPARATOR}{variant}" if variant else name


def _cmd_enroll(args: argparse.Namespace) -> None:
    from notarius.profiles import enroll_from_files

    target = _profile_name(args.name, args.variant)
    enroll_from_files(target, args.audio_files, PROFILES_DIR, _device(args))
    print(f"Voice profile saved: {target}", file=sys.stderr)


def _cmd_enroll_whatsapp(args: argparse.Namespace) -> None:
    from notarius.profiles import enroll_from_files
    from notarius.whatsapp import find_audio_by_sender, select_enrollment_files

    sender = args.sender or args.name
    files = select_enrollment_files(find_audio_by_sender(args.export_dir, sender))
    if not files:
        sys.exit(f"Error: no voice messages of at least 3 s from '{sender}'.")
    target = _profile_name(args.name, args.variant)
    print(f"Using {len(files)} voice messages from '{sender}'...", file=sys.stderr)
    enroll_from_files(target, files, PROFILES_DIR, _device(args))
    print(f"Voice profile saved: {target}", file=sys.stderr)


def _cmd_enroll_meeting(args: argparse.Namespace) -> None:
    from notarius.enroll import execute, plan_enrollment
    from notarius.meeting import Meeting

    plans = plan_enrollment(Meeting.load(args.meeting), PROFILES_DIR)
    for p in plans:
        target = f" -> {p.target_profile}" if p.action == "enroll" else ""
        print(f"  {p.action.upper():6} {p.person}{target}: {p.reason}", file=sys.stderr)
    if args.dry_run or not any(p.action == "enroll" for p in plans):
        return
    for o in execute(plans, PROFILES_DIR, _device(args)):
        if o.profile_path is None:
            print(f"  FAILED {o.plan.person}: {o.reason}", file=sys.stderr)
            continue
        note = ""
        if o.closest_other:
            note = f"; closest other profile {o.closest_other[0]} {o.closest_other[1]:.2f}"
        print(f"  OK {o.plan.person}: {o.clips_used} clips, self-similarity "
              f"{o.self_similarity:.2f}{note}", file=sys.stderr)


def _cmd_profiles(args: argparse.Namespace) -> None:
    from notarius.profiles import delete_person, delete_profile, list_profiles, rename_person

    if args.profiles_command == "delete":
        n = (delete_person(args.name, PROFILES_DIR) if args.delete_all
             else int(delete_profile(args.name, PROFILES_DIR)))
        if not n:
            sys.exit(f"Error: no profile named '{args.name}'.")
        print(f"Deleted {n} profile(s).", file=sys.stderr)
        return
    if args.profiles_command == "rename":
        n = rename_person(args.old, args.new, PROFILES_DIR)
        print(f"Renamed {n} profile(s).", file=sys.stderr)
        return
    groups = list_profiles(PROFILES_DIR)
    print(f"Enrolled people ({len(groups)}):", file=sys.stderr)
    for person, names in sorted(groups.items()):
        extra = f" ({len(names)} profiles)" if len(names) > 1 else ""
        print(f"  {person}{extra}", file=sys.stderr)


def _cmd_aliases(args: argparse.Namespace) -> None:
    from notarius.aliases import add_alias, load_aliases, remove_alias

    if args.aliases_command == "add":
        add_alias(args.person, args.display_name)
        return
    if args.aliases_command == "remove":
        if not remove_alias(args.person, args.display_name):
            sys.exit("Error: no such alias.")
        return
    for person, names in sorted(load_aliases(ALIASES_FILE).items()):
        print(f"  {person} <- {', '.join(names)}", file=sys.stderr)


def _cmd_app(args: argparse.Namespace) -> None:
    from notarius.server import DEFAULT_PORT, serve

    serve(args.port or DEFAULT_PORT, open_browser=not args.no_browser)


def _cmd_setup(args: argparse.Namespace) -> None:
    from notarius.setup import run_setup

    result = run_setup(lambda stage, msg: print(msg, file=sys.stderr),
                       speed_test=not args.no_speed_test)
    print(json.dumps(result), file=sys.stderr)


_COMMANDS = {
    "app": _cmd_app,
    "setup": _cmd_setup,
    "transcribe": _cmd_transcribe,
    "enroll": _cmd_enroll,
    "enroll-whatsapp": _cmd_enroll_whatsapp,
    "enroll-meeting": _cmd_enroll_meeting,
    "profiles": _cmd_profiles,
    "aliases": _cmd_aliases,
}
_NEEDS_FFMPEG = {"app", "setup", "transcribe", "enroll", "enroll-whatsapp", "enroll-meeting"}


def main(argv: list[str] | None = None) -> None:
    # Windows encodes piped or redirected output as cp1252, which garbles
    # names for any program reading it as UTF-8.
    for stream in (sys.stdout, sys.stderr):
        stream.reconfigure(encoding="utf-8", errors="replace")
    from notarius import env

    env.configure()
    parser = _build_parser()
    args = parser.parse_args(argv if argv is not None else (sys.argv[1:] or ["app"]))
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s: %(message)s",
        stream=sys.stderr,
    )
    if args.command is None:
        parser.print_help(sys.stderr)
        sys.exit(1)
    if args.command in _NEEDS_FFMPEG:
        missing = [t for t in ("ffmpeg", "ffprobe") if shutil.which(t) is None]
        if missing:
            sys.exit(f"Error: {' and '.join(missing)} not found. {FFMPEG_MISSING}")

    from notarius.power import keep_awake

    try:
        with keep_awake():
            _COMMANDS[args.command](args)
    except KeyboardInterrupt:
        sys.exit("\nInterrupted.")
    except Exception as exc:
        logger.debug("Unhandled exception", exc_info=True)
        sys.exit(f"Error: {exc}")
