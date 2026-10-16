# Notarius

*[Leia em português](README.pt-BR.md)*

Notarius turns meeting recordings into transcripts that say **who said
what**. It recognizes people by their voice, so after a few meetings the
transcript names them on its own.

It is made for Windows and for people who are not computer experts:
one installer, one shortcut, and a page in your browser where you listen
to short clips and name the voices it does not know yet.

- **Brazilian Portuguese** meetings.
- **Everything stays on your computer.** No account, no upload, no
  subscription. Recordings and voices never leave your machine.
- Works with **Zoom** recordings (including one audio file per
  participant), and with any audio or video file from Google Meet, Teams,
  a phone or a recorder.
- Runs on an ordinary laptop, no graphics card needed. It is slow there —
  a one-hour meeting can take a few hours — so it keeps the computer awake
  and you can leave it running.

> **Status:** early version, being tested. Expect rough edges.

## Install

1. Download the latest `Notarius-<version>.zip` from
   [Releases](../../releases).
2. Right-click the zip → **Extract All**.
3. Open the extracted folder and double-click **Instalar Notarius**.
   Windows may warn that it "protected your PC", because the installer is
   not signed: click **More info** → **Run anyway**.
4. The installer downloads what it needs (about 5 GB), measures how fast
   your computer is, and creates a **Notarius** shortcut on the desktop.

Nothing needs administrator rights, except that Windows may ask once to
install the Microsoft Visual C++ runtime if your computer does not have it.

## Use

Open **Notarius**. Your browser shows the app.

1. **New transcription:** choose a recording or a Zoom folder and tell
   it who was there (optional, but it helps).
2. Wait. Notarius shows the time it expects to take.
3. **Review:** for each voice it is not sure about, listen to a few clips
   and pick or type the name. Notarius fixes the transcript.
4. **Learn the voices:** with one click, the people you named are saved,
   and next time they are recognized automatically.

Transcripts are saved in `Notarius\Transcrições` inside your user folder,
as a `.txt` you can open in any editor.

## How it works

Speech recognition with [Whisper](https://github.com/openai/whisper)
(large-v3, via [faster-whisper](https://github.com/SYSTRAN/faster-whisper)
and [WhisperX](https://github.com/m-bain/whisperX)), word alignment with
a Portuguese wav2vec2 model, speaker separation with
[pyannote](https://github.com/pyannote/pyannote-audio), and voice
recognition with WeSpeaker embeddings scored by adaptive score
normalization (AS-Norm), plus a second check of every segment to catch
labels that mix two people.

## Licence

Notarius is released under the [MIT licence](LICENSE)
([tradução](LICENSE.pt-BR.md)). It builds on other projects with their own
licences — see [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).
