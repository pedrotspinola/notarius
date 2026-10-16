# Notarius

*[Read in English](README.md)*

O Notarius transforma gravações de reuniões em transcrições que dizem
**quem falou o quê**. Ele reconhece as pessoas pela voz, então depois de
algumas reuniões a transcrição já sai com os nomes.

Foi feito para Windows e para quem não é especialista em computador:
um instalador, um atalho e uma página no navegador onde você ouve trechos
curtos e dá nome às vozes que ele ainda não conhece.

- Reuniões em **português do Brasil**.
- **Tudo fica no seu computador.** Sem conta, sem envio para a internet,
  sem assinatura. Gravações e vozes nunca saem da sua máquina.
- Funciona com gravações do **Zoom** (inclusive com um arquivo de áudio
  por participante) e com qualquer arquivo de áudio ou vídeo do Google
  Meet, do Teams, do celular ou de um gravador.
- Roda num notebook comum, sem placa de vídeo. Nesse caso é lento — uma
  reunião de uma hora pode levar algumas horas — por isso ele impede o
  computador de dormir e você pode deixá-lo trabalhando.

> **Situação:** versão inicial, em testes. Pode ter arestas.

## Instalação

1. Baixe o `Notarius-<versão>.zip` mais recente em
   [Releases](../../releases).
2. Clique com o botão direito no zip → **Extrair tudo**.
3. Abra a pasta extraída e dê dois cliques em **Instalar Notarius**.
   O Windows pode avisar que "protegeu o computador", porque o instalador
   não é assinado: clique em **Mais informações** → **Executar assim
   mesmo**.
4. O instalador baixa o que precisa (cerca de 5 GB), mede a velocidade do
   seu computador e cria um atalho **Notarius** na área de trabalho.

Nada exige permissão de administrador, exceto que o Windows pode pedir
uma vez para instalar o "Microsoft Visual C++ Redistributable", se o seu
computador ainda não tiver.

## Uso

Abra o **Notarius**. O navegador mostra o programa.

1. **Nova transcrição:** escolha uma gravação ou uma pasta do Zoom e
   diga quem estava presente (opcional, mas ajuda).
2. Aguarde. O Notarius mostra quanto tempo deve levar.
3. **Revisão:** para cada voz de que ele não tem certeza, ouça alguns
   trechos e escolha ou digite o nome. O Notarius corrige a transcrição.
4. **Aprender as vozes:** com um clique, as pessoas que você nomeou ficam
   guardadas e, da próxima vez, são reconhecidas sozinhas.

As transcrições ficam em `Notarius\Transcrições`, dentro da sua pasta de
usuário, como um `.txt` que abre em qualquer editor.

## Com um agente de IA (opcional)

Se você usa o Codex, o Claude Code ou um agente parecido, abra-o na sua
pasta `Notarius`. O Notarius mantém ali um `AGENTS.md` com tudo o que o
agente precisa para ajudar a revisar reuniões — e uma pasta `Notas` onde
ele anota o que aprende sobre as suas pessoas e grupos. O agente nunca
começa transcrições; elas rodam no aplicativo.

## Como funciona

Reconhecimento de fala com o [Whisper](https://github.com/openai/whisper)
(large-v3, via [faster-whisper](https://github.com/SYSTRAN/faster-whisper)
e [WhisperX](https://github.com/m-bain/whisperX)), alinhamento das
palavras com um modelo wav2vec2 de português, separação de falantes com o
[pyannote](https://github.com/pyannote/pyannote-audio) e reconhecimento de
voz com embeddings WeSpeaker pontuados por normalização adaptativa de
pontuação (AS-Norm), mais uma segunda verificação de cada trecho para
pegar rótulos que misturam duas pessoas.

## Licença

O Notarius é distribuído sob a [licença MIT](LICENSE)
([tradução](LICENSE.pt-BR.md)). Ele se apoia em outros projetos, com
licenças próprias — veja [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).
