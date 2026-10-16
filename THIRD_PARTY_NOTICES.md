# Third-party notices · Avisos de terceiros

Notarius uses the following models and programs. The installer downloads
them from their publishers, except the pyannote segmentation model, which
is bundled.

O Notarius usa os modelos e programas abaixo. O instalador os baixa de
quem os publica, exceto o modelo de segmentação do pyannote, que vem
incluído.

## Models · Modelos

- **pyannote/segmentation-3.0** — © 2023 CNRS, MIT licence. Bundled in
  `src/notarius/models/` with its licence (`LICENSE-segmentation-3.0.txt`).
  https://huggingface.co/pyannote/segmentation-3.0
- **pyannote/speaker-diarization-3.1** pipeline configuration — CNRS, MIT
  licence. Reproduced in `src/notarius/transcribe.py`.
  https://huggingface.co/pyannote/speaker-diarization-3.1
- **pyannote/wespeaker-voxceleb-resnet34-LM** — WeSpeaker ResNet34 trained
  on VoxCeleb, packaged by pyannote, **CC BY 4.0**.
  https://huggingface.co/pyannote/wespeaker-voxceleb-resnet34-LM —
  WeSpeaker: https://github.com/wenet-e2e/wespeaker
- **Whisper large-v3** (OpenAI, MIT licence), CTranslate2 conversion by
  SYSTRAN (`Systran/faster-whisper-large-v3`, MIT licence).
- **Whisper large-v3-turbo** (OpenAI, MIT licence), CTranslate2 conversion
  `dropbox-dash/faster-whisper-large-v3-turbo` (MIT licence) — used on
  computers with little memory.
- **jonatasgrosman/wav2vec2-large-xlsr-53-portuguese** — Jonatas
  Grosman, Apache 2.0 licence.

## Software

- **WhisperX** (BSD 2-Clause), **faster-whisper** (MIT), **CTranslate2**
  (MIT), **pyannote.audio** (MIT), **PyTorch** (BSD-style), and their
  dependencies, installed from PyPI by `uv`.
- **uv** by Astral (MIT / Apache 2.0), downloaded by the installer.
- **FFmpeg** (GPL build by gyan.dev), downloaded by the installer from
  its publisher and run as a separate program. Notarius does not
  redistribute it. https://www.gyan.dev/ffmpeg/builds/

## Test recordings · Gravações de teste

The voices in `tests/fixtures/` are excerpts of public-domain LibriVox
recordings (https://librivox.org), read by LibriVox volunteers.

As vozes em `tests/fixtures/` são trechos de gravações em domínio público
do LibriVox (https://librivox.org), lidas por voluntários do LibriVox.
