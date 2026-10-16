"""The app: a small web server on this computer and the page it serves.

Only reachable from this computer (127.0.0.1).  Every API request must
carry a token that is embedded in the page, so other websites open in the
same browser cannot drive the app, and the Host header is checked so a
DNS-rebinding page cannot pose as it either.
"""

from __future__ import annotations

import json
import logging
import mimetypes
import os
import secrets
import subprocess
import sys
import threading
import time
import urllib.parse
import webbrowser
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib import resources
from pathlib import Path

from notarius import __version__
from notarius.aliases import add_alias, load_aliases, remove_alias, save_aliases
from notarius.config import (
    DATA_DIR,
    MEETINGS_DIR,
    PROFILES_DIR,
    UNKNOWN_PREFIX,
    VARIANT_SEPARATOR,
    validate_base_name,
)
from notarius.jobs import JobRunner
from notarius.meeting import Meeting

log = logging.getLogger(__name__)

DEFAULT_PORT = 47830
WEB = resources.files("notarius") / "web"


class ApiError(Exception):
    def __init__(self, code: str, status: int = 400):
        super().__init__(code)
        self.code, self.status = code, status


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _meeting_path(meeting_id: str) -> Path:
    if not meeting_id or any(c in meeting_id for c in "/\\") or ".." in meeting_id:
        raise ApiError("bad_meeting")
    path = MEETINGS_DIR / f"{meeting_id}.json"
    if not path.is_file():
        raise ApiError("no_meeting", 404)
    return path


def _open_in_system(path: Path) -> None:
    if sys.platform == "win32":
        os.startfile(path)  # noqa: S606 - opening the user's own file
    else:
        subprocess.Popen(["xdg-open", str(path)], stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL)


_dialog_lock = threading.Lock()


def _pick(kind: str) -> str | None:
    """Native file/folder chooser (the browser cannot reveal real paths)."""
    import tkinter
    from tkinter import filedialog

    with _dialog_lock:
        root = tkinter.Tk()
        root.withdraw()
        root.attributes("-topmost", True)
        try:
            if kind == "folder":
                path = filedialog.askdirectory(parent=root, title="Escolha a pasta")
            else:
                path = filedialog.askopenfilename(
                    parent=root, title="Escolha a gravação",
                    filetypes=[("Áudio e vídeo", "*.mp3 *.m4a *.wav *.ogg *.opus *.flac "
                                "*.aac *.wma *.mp4 *.mkv *.mov *.avi *.webm *.3gp"),
                               ("Todos os arquivos", "*.*")],
                )
        finally:
            root.destroy()
    return path or None


def _people() -> list[dict]:
    from notarius.profiles import list_profiles

    aliases = load_aliases()
    groups = list_profiles(PROFILES_DIR)
    return [
        {"name": person, "profiles": len(names), "aliases": aliases.get(person, [])}
        for person, names in sorted(groups.items(), key=lambda kv: kv[0].lower())
    ]


def _meeting_summary(path: Path) -> dict:
    m = Meeting.load(path)
    names = {s.speaker_name for s in m.segments}
    return {
        "id": path.stem,
        "title": m.title,
        "date": m.date,
        "duration": m.duration_seconds,
        "kind": m.source_kind,
        "review_status": m.review_status,
        "people": sorted(n for n in names if not n.startswith(UNKNOWN_PREFIX)),
        "unknowns": sorted(n for n in names if n.startswith(UNKNOWN_PREFIX)),
        "updated": m.updated or m.created,
    }


def _inspect(source: Path) -> dict:
    from notarius.pipeline import probe_duration
    from notarius.tuning import load_tuning
    from notarius.zoom import is_zoom_folder, parse_zoom_folder

    if source.is_dir():
        if not is_zoom_folder(source):
            raise ApiError("not_zoom_folder")
        rec = parse_zoom_folder(source)
        kind = "tracks" if rec.has_per_participant else "file"
        duration = probe_duration(rec.mixed_audio) if rec.mixed_audio else None
        participants = [p.display_name for p in rec.participant_audio]
        if kind == "tracks" and duration is None:
            duration = max(filter(None, (probe_duration(p.path) for p in rec.participant_audio)),
                           default=None)
    elif source.is_file():
        kind, participants = "file", []
        duration = probe_duration(source)
        if duration is None:
            raise ApiError("not_audio")
    else:
        raise ApiError("not_found", 404)
    tuning = load_tuning()
    estimate = tuning.estimate_seconds(duration, kind) if tuning and duration else None
    if estimate is not None and kind == "tracks":
        # Every track is transcribed; silence is skipped, speech is not.
        estimate *= max(1, len(participants)) ** 0.5
    return {"path": str(source), "kind": kind, "duration": duration,
            "participants": participants, "estimate": estimate}


# ---------------------------------------------------------------------------
# The application
# ---------------------------------------------------------------------------


class App:
    def __init__(self, port: int) -> None:
        self.port = port
        self.token = secrets.token_urlsafe(24)
        self.jobs = JobRunner()
        self.allowed_hosts = {f"127.0.0.1:{port}", f"localhost:{port}"}

    # -- dispatch ----------------------------------------------------------

    def get(self, path: str, query: dict) -> tuple[object, str]:
        if path == "/api/state":
            from notarius.env import MODELS_READY
            from notarius.tuning import load_tuning

            tuning = load_tuning()
            return {
                "version": __version__,
                "data_dir": str(DATA_DIR),
                "models_ready": MODELS_READY.is_file(),
                "tuning": None if tuning is None else {
                    "device": tuning.device, "model": tuning.whisper_model,
                    "seconds_per_audio_minute": tuning.seconds_per_audio_minute,
                    "ram_gb": tuning.ram_gb,
                },
                "job": self._job(),
            }, "json"
        if path == "/api/job":
            return {"job": self._job()}, "json"
        if path == "/api/meetings":
            MEETINGS_DIR.mkdir(parents=True, exist_ok=True)
            out = []
            for p in sorted(MEETINGS_DIR.glob("*.json"), reverse=True):
                try:
                    out.append(_meeting_summary(p))
                except Exception:
                    log.warning("Unreadable meeting %s", p, exc_info=True)
            return {"meetings": out}, "json"
        if path.startswith("/api/meetings/") and path.endswith("/plan"):
            return self._plan(path.split("/")[3]), "json"
        if path.startswith("/api/meetings/"):
            return self._meeting(path.split("/")[3]), "json"
        if path == "/api/people":
            return {"people": _people()}, "json"
        if path == "/api/clip":
            return self._clip(query), "wav"
        raise ApiError("not_found", 404)

    def post(self, path: str, body: dict) -> object:
        if path == "/api/pick":
            return {"path": _pick(body.get("kind", "file"))}
        if path == "/api/inspect":
            return _inspect(Path(body["path"]))
        if path == "/api/jobs/transcribe":
            info = _inspect(Path(body["path"]))
            attendees = [a.strip() for a in body.get("attendees", []) if a.strip()]
            return self._start("transcribe", {
                "source": info["path"], "attendees": attendees,
                "kind": info["kind"], "duration": info["duration"],
            }, info["estimate"])
        if path == "/api/jobs/tune":
            return self._start("tune", {}, None)
        if path == "/api/jobs/setup":
            return self._start("setup", {}, None)
        if path == "/api/job/cancel":
            self.jobs.cancel()
            return {"job": self._job()}
        if path == "/api/job/dismiss":
            self.jobs.dismiss()
            return {"job": None}
        if path.startswith("/api/meetings/") and path.endswith("/answers"):
            return self._answers(path.split("/")[3], body.get("answers", {}))
        if path.startswith("/api/meetings/") and path.endswith("/rename"):
            return self._rename_lines(path.split("/")[3], body["indices"], body["name"])
        if path.startswith("/api/meetings/") and path.endswith("/enroll"):
            meeting_path = _meeting_path(path.split("/")[3])
            return self._start("enroll", {"meeting_path": str(meeting_path),
                                          "people": body.get("people", [])}, None)
        if path == "/api/open":
            return self._open(body)
        if path == "/api/people/rename":
            return self._rename_person(body["old"], body["new"])
        if path == "/api/people/delete":
            from notarius.profiles import delete_person

            n = delete_person(body["name"], PROFILES_DIR)
            aliases = load_aliases()
            aliases.pop(body["name"], None)
            save_aliases(aliases)
            return {"deleted": n}
        if path == "/api/people/alias":
            if body.get("remove"):
                remove_alias(body["person"], body["alias"])
            else:
                add_alias(body["person"], body["alias"].strip())
            return {"people": _people()}
        if path == "/api/whatsapp/senders":
            from notarius.whatsapp import senders

            return {"senders": senders(Path(body["path"]))}
        if path == "/api/jobs/enroll-files":
            name = " ".join(body["name"].split())
            validate_base_name(name)
            from notarius.profiles import list_profiles

            existing = list_profiles(PROFILES_DIR).get(name, [])
            profile = name if not existing else f"{name}{VARIANT_SEPARATOR}{time.strftime('%Y-%m-%d')}"
            params = {"name": name, "profile": profile}
            if body.get("whatsapp_dir"):
                params.update(whatsapp_dir=body["whatsapp_dir"], sender=body["sender"])
            else:
                params["files"] = body["files"]
            return self._start("enroll-files", params, None)
        raise ApiError("not_found", 404)

    # -- pieces ------------------------------------------------------------

    def _job(self) -> dict | None:
        from dataclasses import asdict

        status = self.jobs.current()
        if status is None:
            return None
        data = asdict(status)
        data["elapsed"] = (status.updated if status.state != "running" else time.time()) - status.started
        return data

    def _start(self, kind: str, params: dict, expected: float | None) -> dict:
        try:
            self.jobs.start(kind, params, expected)
        except RuntimeError:
            raise ApiError("busy", 409)
        return {"job": self._job()}

    def _meeting(self, meeting_id: str) -> dict:
        from notarius.review import build_review, items_as_dicts, merged_lines

        path = _meeting_path(meeting_id)
        m = Meeting.load(path)
        return {
            "meeting": _meeting_summary(path),
            "items": items_as_dicts(build_review(m, PROFILES_DIR)),
            "lines": merged_lines(m),
            "known_people": [p["name"] for p in _people()],
            "listed": m.listed_attendees,
            "chat": len(m.chat),
        }

    def _plan(self, meeting_id: str) -> dict:
        from notarius.enroll import plan_enrollment

        m = Meeting.load(_meeting_path(meeting_id))
        return {"plan": [
            {"person": p.person, "action": p.action, "code": p.code,
             "profile": p.target_profile, "clean_seconds": round(p.clean_seconds),
             "selected_seconds": round(p.selected_seconds), "best_raw": p.best_raw}
            for p in plan_enrollment(m, PROFILES_DIR)
        ]}

    def _answers(self, meeting_id: str, answers: dict) -> dict:
        from notarius.review import apply_answers

        path = _meeting_path(meeting_id)
        m = Meeting.load(path)
        try:
            changed = apply_answers(m, answers)
        except ValueError:
            raise ApiError("bad_name")
        m.review_status = "done"
        m.save(path)
        return {"changed": changed, **self._meeting(meeting_id)}

    def _rename_lines(self, meeting_id: str, indices: list[int], name: str) -> dict:
        from notarius.review import rename_segments

        path = _meeting_path(meeting_id)
        m = Meeting.load(path)
        try:
            rename_segments(m, [int(i) for i in indices], name)
        except ValueError:
            raise ApiError("bad_name")
        m.save(path)
        return self._meeting(meeting_id)

    def _rename_person(self, old: str, new: str) -> dict:
        from notarius.profiles import rename_person

        new = " ".join(new.split())
        try:
            rename_person(old, new, PROFILES_DIR)
        except ValueError:
            raise ApiError("bad_name")
        aliases = load_aliases()
        names = aliases.pop(old, [])
        if old not in names:
            names.append(old)  # the old name keeps resolving to the person
        aliases[new] = names
        save_aliases(aliases)
        return {"people": _people()}

    def _open(self, body: dict) -> dict:
        target = body.get("target")
        if target == "meetings":
            MEETINGS_DIR.mkdir(parents=True, exist_ok=True)
            _open_in_system(MEETINGS_DIR)
        elif target == "data":
            DATA_DIR.mkdir(parents=True, exist_ok=True)
            _open_in_system(DATA_DIR)
        elif target == "text":
            _open_in_system(_meeting_path(body["id"]).with_suffix(".txt"))
        else:
            raise ApiError("bad_target")
        return {"ok": True}

    def _clip(self, query: dict) -> bytes:
        m = Meeting.load(_meeting_path(query["meeting"]))
        start, end = float(query["start"]), float(query["end"])
        if not 0 <= start < end or end - start > 60:
            raise ApiError("bad_clip")
        track = query.get("track", "")
        source = m.tracks.get(track) if track else m.source_path
        if not source or not Path(source).is_file():
            raise ApiError("no_audio", 404)
        result = subprocess.run(
            ["ffmpeg", "-hide_banner", "-loglevel", "error", "-ss", f"{start:.2f}",
             "-t", f"{end - start:.2f}", "-i", source, "-vn", "-ac", "1", "-ar", "16000",
             "-f", "wav", "-"],
            capture_output=True, timeout=60,
        )
        if result.returncode != 0:
            raise ApiError("clip_failed", 500)
        return result.stdout


def _make_handler(app: App):
    class Handler(BaseHTTPRequestHandler):
        server_version = "Notarius"

        def log_message(self, fmt, *args):  # keep the console quiet
            log.debug("%s - %s", self.address_string(), fmt % args)

        def _send(self, status: int, body: bytes, ctype: str, extra: dict | None = None):
            self.send_response(status)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            for k, v in (extra or {}).items():
                self.send_header(k, v)
            self.end_headers()
            self.wfile.write(body)

        def _json(self, status: int, data: object):
            self._send(status, json.dumps(data, ensure_ascii=False).encode("utf-8"),
                       "application/json; charset=utf-8")

        def _guard(self, query: dict) -> bool:
            if self.headers.get("Host") not in app.allowed_hosts:
                self._send(HTTPStatus.FORBIDDEN, b"forbidden", "text/plain")
                return False
            token = self.headers.get("X-Notarius-Token") or query.get("t")
            if self.path.startswith("/api/") and not secrets.compare_digest(
                str(token or ""), app.token
            ):
                self._send(HTTPStatus.FORBIDDEN, b"forbidden", "text/plain")
                return False
            return True

        def do_GET(self):
            url = urllib.parse.urlsplit(self.path)
            query = dict(urllib.parse.parse_qsl(url.query))
            path = urllib.parse.unquote(url.path)
            if path == "/api/ping":  # lets a second launch find this one
                return self._json(200, {"app": "notarius"})
            if not self._guard(query):
                return
            if not path.startswith("/api/"):
                return self._static(path)
            try:
                data, kind = app.get(path, query)
                if kind == "wav":
                    self._send(200, data, "audio/wav")
                else:
                    self._json(200, data)
            except ApiError as e:
                self._json(e.status, {"error": e.code})
            except Exception as e:
                log.exception("GET %s failed", path)
                self._json(500, {"error": "internal", "detail": str(e)[:300]})

        def do_POST(self):
            url = urllib.parse.urlsplit(self.path)
            path = urllib.parse.unquote(url.path)
            if not self._guard({}):
                return
            try:
                length = int(self.headers.get("Content-Length") or 0)
                body = json.loads(self.rfile.read(length) or b"{}")
                self._json(200, app.post(path, body))
            except ApiError as e:
                self._json(e.status, {"error": e.code})
            except Exception as e:
                log.exception("POST %s failed", path)
                self._json(500, {"error": "internal", "detail": str(e)[:300]})

        def _static(self, path: str):
            name = "index.html" if path in ("/", "/index.html") else path.lstrip("/")
            if "/" in name or "\\" in name or ".." in name:
                return self._send(404, b"not found", "text/plain")
            res = WEB / name
            if not res.is_file():
                return self._send(404, b"not found", "text/plain")
            body = res.read_bytes()
            if name == "index.html":
                body = body.replace(b"__NOTARIUS_TOKEN__", app.token.encode())
            ctype = mimetypes.guess_type(name)[0] or "application/octet-stream"
            if ctype.startswith("text/") or ctype.endswith("javascript"):
                ctype += "; charset=utf-8"
            self._send(200, body, ctype)

    return Handler


def _already_running(port: int) -> bool:
    import urllib.request

    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/ping", timeout=1) as r:
            return json.loads(r.read()).get("app") == "notarius"
    except Exception:
        return False


def _disable_quick_edit() -> None:
    """A click inside a Windows console pauses the program (QuickEdit)."""
    if sys.platform != "win32":
        return
    import ctypes

    kernel32 = ctypes.windll.kernel32
    handle = kernel32.GetStdHandle(-10)  # STD_INPUT_HANDLE
    mode = ctypes.c_uint32()
    if kernel32.GetConsoleMode(handle, ctypes.byref(mode)):
        kernel32.SetConsoleMode(handle, (mode.value & ~0x0040) | 0x0080)


def serve(port: int = DEFAULT_PORT, open_browser: bool = True) -> None:
    if _already_running(port):
        print("O Notarius já está aberto; abrindo o navegador.")
        webbrowser.open(f"http://127.0.0.1:{port}/")
        return
    from notarius.datafolder import ensure_data_folder

    ensure_data_folder()
    app = App(port)
    httpd = ThreadingHTTPServer(("127.0.0.1", port), _make_handler(app))
    url = f"http://127.0.0.1:{port}/"
    _disable_quick_edit()
    if sys.platform == "win32":
        import ctypes

        ctypes.windll.kernel32.SetConsoleTitleW("Notarius — não feche esta janela")
    print(f"Notarius {__version__} — aberto em {url}")
    print("Pode minimizar esta janela, mas não a feche: fechar encerra o Notarius.")
    if open_browser:
        threading.Timer(0.5, lambda: webbrowser.open(url)).start()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        app.jobs.cancel()
        httpd.server_close()
