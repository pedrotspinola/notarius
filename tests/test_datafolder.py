"""The user's folder: managed files refresh, notes are never overwritten."""

import importlib


def test_agent_files_refresh_but_notes_are_kept(tmp_path, monkeypatch):
    monkeypatch.setenv("NOTARIUS_HOME", str(tmp_path))
    import notarius.config
    import notarius.datafolder

    importlib.reload(notarius.config)
    datafolder = importlib.reload(notarius.datafolder)
    try:
        datafolder.ensure_data_folder(tmp_path)
        agents = tmp_path / "AGENTS.md"
        notes = tmp_path / "Notas" / "pessoas.md"
        assert agents.is_file() and notes.is_file()
        assert (tmp_path / "CLAUDE.md").read_text(encoding="utf-8").strip() == "@AGENTS.md"
        assert (tmp_path / "Transcrições").is_dir() and (tmp_path / "Vozes").is_dir()
        assert len(agents.read_bytes()) < 32 * 1024  # Codex reads at most 32 KiB

        agents.write_text("old version", encoding="utf-8")
        notes.write_text("my own notes", encoding="utf-8")
        datafolder.ensure_data_folder(tmp_path)
        assert agents.read_text(encoding="utf-8") != "old version"
        assert notes.read_text(encoding="utf-8") == "my own notes"
    finally:
        monkeypatch.delenv("NOTARIUS_HOME")
        importlib.reload(notarius.config)
        importlib.reload(notarius.datafolder)
