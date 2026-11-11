# Changelog · Histórico de versões

## Unreleased · Ainda não lançado

- Zoom recordings with one audio file per person: lines the speech model
  invents over silence ("E aí", "Obrigado.", "Tchau.") are removed instead
  of appearing under that person's name. What was removed is kept in the
  meeting file.
- Names that differ only by accents are recognized as the same person
  ("Iolanda Brandao" in Zoom finds "Iolanda Brandão"), in audio tracks and in
  the chat.

- Gravações do Zoom com um arquivo de áudio por pessoa: as falas que o
  modelo inventa sobre o silêncio ("E aí", "Obrigado.", "Tchau.") são
  removidas em vez de aparecer no nome da pessoa. O que foi removido fica
  registrado no arquivo da reunião.
- Nomes que só diferem nos acentos são reconhecidos como a mesma pessoa
  ("Iolanda Brandao" no Zoom encontra "Iolanda Brandão"), nas faixas de
  áudio e no chat.

## 0.1.0

First version, for testing.

- Transcribes Brazilian Portuguese meetings from any audio or video file,
  and from Zoom recordings with one audio file per participant.
- Recognizes people by voice and marks the rest as unknown.
- Review page in the browser: listen to clips, name unknown voices, confirm
  doubtful ones, fix any line of the transcript.
- Learns the voices of a reviewed meeting with one click.
- Installer that needs no administrator rights (except, if missing, the
  Microsoft Visual C++ runtime), downloads the models, and measures the
  computer's speed to estimate how long each meeting will take.

Primeira versão, para testes.

- Transcreve reuniões em português do Brasil a partir de qualquer arquivo
  de áudio ou vídeo, e de gravações do Zoom com um arquivo de áudio por
  participante.
- Reconhece as pessoas pela voz e marca as demais como desconhecidas.
- Página de revisão no navegador: ouvir trechos, dar nome às vozes
  desconhecidas, confirmar as duvidosas, corrigir qualquer linha da
  transcrição.
- Aprende as vozes de uma reunião revisada com um clique.
- Instalador que não precisa de permissão de administrador (exceto, se
  faltar, o Microsoft Visual C++), baixa os modelos e mede a velocidade do
  computador para estimar quanto tempo cada reunião vai levar.
