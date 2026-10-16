"""WhatsApp exports from iPhone and Android."""

from notarius.whatsapp import _attachment, find_chat_file, parse_messages, senders

IOS = (
    "﻿[01/02/2026, 10:00:00] Odete Prado: Bom dia\n"
    "[01/02/2026, 10:01:00] Odete Prado: ‎<anexado: 00000012-AUDIO-2026-02-01.opus>\n"
    "[01/02/2026, 10:02:00] Vicente: ‎<anexado: 00000013-PHOTO-2026-02-01.jpg>\n"
)
ANDROID = (
    "01/02/2026 10:00 - Vicente: Oi\n"
    "01/02/2026 10:01 - Vicente: PTT-20260201-WA0001.opus (arquivo anexado)\n"
    "01/02/2026 10:02 - Vicente: PTT-20260201-WA0002.opus (arquivo anexado)\n"
)


def test_attachments():
    assert _attachment("<anexado: a.opus>") == "a.opus"
    assert _attachment("PTT-1.opus (arquivo anexado)") == "PTT-1.opus"
    assert _attachment("IMG-1.jpg (arquivo anexado)") is None
    assert _attachment("texto qualquer") is None


def test_both_formats(tmp_path):
    ios = tmp_path / "ios"
    ios.mkdir()
    (ios / "_chat.txt").write_text(IOS, encoding="utf-8")
    assert senders(ios) == [("Odete Prado", 1)]

    android = tmp_path / "android"
    android.mkdir()
    chat = android / "Conversa do WhatsApp com Vicente.txt"
    chat.write_text(ANDROID, encoding="utf-8")
    assert find_chat_file(android) == chat
    assert len(parse_messages(chat)) == 3
    assert senders(android) == [("Vicente", 2)]
