# Notarius — instructions for AI agents

You are helping someone who uses **Notarius**, a Windows program that
transcribes Brazilian Portuguese meetings and recognizes speakers by voice.
This folder is their Notarius folder. **Talk to them in Brazilian
Portuguese, in plain words: they are not computer experts.**

Notarius writes this file and refreshes it on updates — do not edit it.
Keep everything you learn about *their* people and meetings in `Notas\`.

## What is here

- `Transcrições\` — one meeting = `<date> <title>.json` (the record) +
  `.txt` (readable transcript, generated from the JSON).
- `Vozes\` — voice profiles (`Name.npy`, `Name__tag.npy` = same person,
  other recording condition) and `apelidos.json` (other names a person
  appears under, e.g. their Zoom name).
- `Notas\` — the user's knowledge base, kept by you: `pessoas.md`,
  `grupos.md`, `aprendizados.md`. **Read them at the start of every task;
  update them when you learn something durable.**

## Rules

1. **Never start a transcription yourself.** It takes hours on a laptop and
   your sandbox would get in its way. Ask the user to open the **Notarius**
   app (desktop shortcut) → *Nova transcrição*.
2. The **app's review page** is the main way to name voices. Use the
   commands below for what the page does not cover or when the user asks.
3. **Never edit `.npy` files, and never delete or rename voices without the
   user's explicit yes.** A voice saved under the wrong name makes every
   future meeting worse.
4. Never edit a meeting's `.txt` by hand: it is regenerated from the JSON.
   Change speakers with `rename-speaker` (below).
5. Before naming someone, check `Notas\pessoas.md` and `apelidos.json`:
   first names are ambiguous (several people may share one). Never merge
   two names unless the user confirms they are the same person.

## Commands

In PowerShell (the program's own Python; nothing else is installed):

```powershell
$n = "$env:LOCALAPPDATA\Notarius\env\Scripts\python.exe"
& $n -m notarius profiles                                  # who has a voice
& $n -m notarius aliases                                   # other names
& $n -m notarius aliases add "Odete Prado" "Odete P."          # Zoom name -> person
& $n -m notarius rename-speaker "<meeting>.json" "Odete Prado" --label SPEAKER_03
& $n -m notarius rename-speaker "<meeting>.json" "Odete Prado" --from "Desconhecido 2"
& $n -m notarius rename-speaker "<meeting>.json" "Odete Prado" --segments 41,42
& $n -m notarius enroll-meeting "<meeting>.json" --dry-run   # who would be learned
```

Short commands only. If one says the models are missing, send the user to
the app → *Ajustes → Preparar agora*.

## Reading a meeting's JSON

- `segments[i]`: `start`, `end` (seconds), `text`, `speaker`, `label`
  (diarization label; for Zoom one-track-per-person recordings, the track),
  `origin` (`label` automatic, `verified` moved by the second check,
  `track` from a person's own Zoom track, `review` set by the user).
- `labels[]`: per diarization label, `name`, `matched`, `candidates`
  (`person`, `raw` cosine, `norm` AS-Norm score, `excess` over the accept
  threshold).
- `events[]`: per-segment checks (`reassigned`, `gated`, `suspect`,
  `flagged`, `possible`) with the segment `index`.
- `listed_attendees`: who the user said was present.

## How to find out who is speaking — in this order

1. **Read the beginning of the transcript first.** Introductions ("meu nome
   é…", "aqui é a…") and the chair calling people ("pode falar, Fulano" →
   the next turn is Fulano) settle most unknown voices for free, and they
   also expose wrong automatic matches. Many meetings have more than one
   round of introductions (late joiners).
2. **Someone addressed by their own name in their own turn** ("…, Odete?"
   inside a turn credited to Odete) means the turn is someone else's. The
   person who runs the meeting collects other people's short replies this
   way; when you fix one, check the next turn too (a question and its
   answer often swap together). Two legitimate exceptions: quoting
   someone ("ela falou: Odete, …") and naming oneself for the record.
3. **Scores:** an accepted match with `raw` below 0.50 is *unproven*, not
   necessarily wrong — a bad microphone lowers the real speaker too. A
   small gap between the top two candidates is a warning, but a large gap
   does **not** mean safe: false matches of unknown voices often have big
   gaps. When the text and the scores disagree, trust a clear textual clue.
4. Only then ask the user to listen — and be specific: which phrase, at
   what time. Their ear is the final word.

## Things that look like errors and are not (and the reverse)

- **A speaker not on the attendee list** is most often a late joiner, not a
  wrong match. Check the text before concluding.
- **A voice nobody knows that talks for a long stretch addressed to one
  person** ("Oi, Odete, tudo bem? Eu abri o e-mail…") may be a voice message
  played on someone's computer during the meeting. Ask the user what to do.
- **Text over silence or noise** (a greeting during a join sound) may be
  invented by the speech model. "There is no speech in this clip" is a
  valid answer: suggest removing the line.
- **Turns shorter than 3 seconds are never checked by voice**: they keep
  whatever their label says. Short replies ("sim", "isso") are the most
  likely to be wrong.
- **A recording that ends early** in the transcript is often just silence
  at the end (people leaving, recording left on), not a failure.
- **One person split into two "Desconhecido"** labels is normal: one voice
  can be split by the speaker separation. Two labels trading lines
  mid-argument on one topic are usually one person.

## Voices: when to learn, when not to

- After a meeting is reviewed, the app's *Aprender vozes* tab learns the
  people who spoke enough (45 s of clean speech). Prefer it.
- A **thin profile** (from little speech) attracts false matches. If the
  user insists on learning someone with little audio, warn them.
- A person recognized in one kind of meeting (Zoom) may be missed in
  another (phone, in person). The fix is an extra profile from the new
  condition — the app adds it automatically when recognition was weak.
- **In-person recordings** (one phone in the room) match poorly against
  profiles from online calls. Lean on the text there.
- Always encourage listing attendees when starting a transcription: it
  blocks renames to people who were not there.

## Keeping notes

`Notas\pessoas.md`: one heading per person — the name used in
transcripts, nicknames, the names they appear under in Zoom/WhatsApp,
groups, voice notes ("speaks softly", "usually on the phone"). `grupos.md`:
per group — who runs it, platform, whether there is a round of
introductions. `aprendizados.md`: anything that will matter next time.
Write in Portuguese, short, dated (DD/MM/AAAA).
