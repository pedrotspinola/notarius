# Notarius — instruções para agentes de IA (tradução)

> Tradução para leitura. O agente lê a versão em inglês (`AGENTS.md`).

Você está ajudando alguém que usa o **Notarius**, um programa para Windows
que transcreve reuniões em português do Brasil e reconhece quem fala pela
voz. Esta pasta é a pasta do Notarius dessa pessoa. **Fale com ela em
português do Brasil, com palavras simples: ela não é especialista em
computador.**

O Notarius escreve este arquivo e o atualiza a cada versão — não o edite.
Guarde tudo o que aprender sobre as pessoas e reuniões *dela* em `Notas\`.

## O que há aqui

- `Transcrições\` — uma reunião = `<data> <título>.json` (o registro) +
  `.txt` (transcrição legível, gerada a partir do JSON).
- `Vozes\` — perfis de voz (`Nome.npy`; `Nome__marca.npy` = mesma pessoa
  em outra condição de gravação) e `apelidos.json` (outros nomes com que
  a pessoa aparece, por exemplo o nome no Zoom).
- `Notas\` — a base de conhecimento do usuário, mantida por você:
  `pessoas.md`, `grupos.md`, `aprendizados.md`. **Leia no começo de toda
  tarefa; atualize quando aprender algo que vale guardar.**

## Regras

1. **Nunca comece uma transcrição você mesmo.** Leva horas num notebook e
   o seu ambiente protegido atrapalharia. Peça para a pessoa abrir o
   aplicativo **Notarius** (atalho na área de trabalho) → *Nova
   transcrição*.
2. A **página de revisão do aplicativo** é o caminho principal para dar
   nome às vozes. Use os comandos abaixo para o que a página não cobre, ou
   quando a pessoa pedir.
3. **Nunca edite arquivos `.npy`, e nunca apague ou renomeie vozes sem um
   "sim" explícito da pessoa.** Uma voz guardada com o nome errado piora
   todas as reuniões seguintes.
4. Nunca edite à mão o `.txt` de uma reunião: ele é gerado a partir do
   JSON. Troque falantes com `rename-speaker` (abaixo).
5. Antes de dar nome a alguém, confira `Notas\pessoas.md` e
   `apelidos.json`: primeiros nomes são ambíguos (várias pessoas podem ter
   o mesmo). Nunca junte dois nomes sem a pessoa confirmar que são a mesma.

## Comandos

No PowerShell (o Python do próprio programa):

```powershell
$n = "$env:LOCALAPPDATA\Notarius\env\Scripts\python.exe"
& $n -m notarius profiles                                  # quem tem voz guardada
& $n -m notarius aliases                                   # outros nomes
& $n -m notarius aliases add "Odete Prado" "Odete P."          # nome no Zoom -> pessoa
& $n -m notarius rename-speaker "<reunião>.json" "Odete Prado" --label SPEAKER_03
& $n -m notarius rename-speaker "<reunião>.json" "Odete Prado" --from "Desconhecido 2"
& $n -m notarius rename-speaker "<reunião>.json" "Odete Prado" --segments 41,42
& $n -m notarius enroll-meeting "<reunião>.json" --dry-run   # quem seria aprendido
```

Só comandos curtos. Se algum disser que faltam os modelos, mande a pessoa
ao aplicativo → *Ajustes → Preparar agora*.

## Como ler o JSON de uma reunião

- `segments[i]`: `start`, `end` (segundos), `text`, `speaker`, `label`
  (rótulo da separação de vozes; em gravações do Zoom com uma faixa por
  pessoa, a faixa), `origin` (`label` automático, `verified` movido pela
  segunda verificação, `track` da faixa própria no Zoom, `review` definido
  pela pessoa).
- `labels[]`: por rótulo, `name`, `matched`, `candidates` (`person`,
  cosseno `raw`, pontuação AS-Norm `norm`, `excess` acima do limite).
- `events[]`: verificações por trecho (`reassigned`, `gated`, `suspect`,
  `flagged`, `possible`) com o `index` do trecho.
- `listed_attendees`: quem a pessoa disse que estava presente.

## Como descobrir quem está falando — nesta ordem

1. **Leia primeiro o começo da transcrição.** Apresentações ("meu nome
   é…", "aqui é a…") e quem coordena chamando as pessoas ("pode falar,
   Fulano" → a fala seguinte é do Fulano) resolvem a maioria das vozes
   desconhecidas sem custo, e também revelam reconhecimentos automáticos
   errados. Muitas reuniões têm mais de uma rodada de apresentações
   (quem chega atrasado).
2. **Alguém chamado pelo próprio nome dentro da própria fala** ("…, Odete?"
   numa fala atribuída à Odete) indica que a fala é de outra pessoa. Quem
   coordena a reunião acumula respostas curtas dos outros assim; ao
   corrigir uma, confira a fala seguinte também (pergunta e resposta
   costumam trocar juntas). Duas exceções legítimas: citar alguém ("ela
   falou: Odete, …") e dizer o próprio nome para registro.
3. **Pontuações:** um reconhecimento aceito com `raw` abaixo de 0,50 está
   *não comprovado*, não necessariamente errado — um microfone ruim também
   rebaixa a pessoa certa. Diferença pequena entre os dois primeiros
   candidatos é um aviso, mas diferença grande **não** é garantia:
   reconhecimentos errados de vozes desconhecidas costumam ter diferença
   grande. Quando o texto e as pontuações discordam, confie numa pista
   clara do texto.
4. Só então peça para a pessoa ouvir — e seja específico: qual frase, em
   que momento. O ouvido dela é a palavra final.

## Coisas que parecem erro e não são (e o contrário)

- **Alguém fora da lista de presentes** costuma ser quem chegou atrasado,
  não um reconhecimento errado. Confira o texto antes de concluir.
- **Uma voz desconhecida que fala muito tempo dirigida a uma pessoa**
  ("Oi, Odete, tudo bem? Eu abri o e-mail…") pode ser um áudio de WhatsApp
  tocado no computador de alguém durante a reunião. Pergunte o que fazer.
- **Texto sobre silêncio ou ruído** (um cumprimento durante o som de
  entrada) pode ter sido inventado pelo modelo de fala. "Não há fala neste
  trecho" é uma resposta válida: sugira apagar a linha.
- **Falas com menos de 3 segundos nunca são conferidas pela voz**: ficam
  com o nome do rótulo. Respostas curtas ("sim", "isso") são as mais
  sujeitas a erro.
- **Uma gravação cuja transcrição termina cedo** muitas vezes só tem
  silêncio no fim (pessoas saindo, gravação esquecida ligada), não falha.
- **Uma pessoa dividida em dois "Desconhecido"** é normal: a separação de
  vozes pode dividir uma voz. Dois rótulos alternando falas no meio de uma
  mesma discussão costumam ser uma pessoa só.

## Vozes: quando aprender e quando não

- Depois de revisar uma reunião, a aba *Aprender vozes* do aplicativo
  guarda quem falou o bastante (45 s de fala limpa). Prefira ela.
- Um **perfil magro** (feito com pouca fala) atrai reconhecimentos
  errados. Se a pessoa insistir em guardar alguém com pouco áudio, avise.
- Alguém reconhecido num tipo de reunião (Zoom) pode não ser em outro
  (telefone, presencial). A solução é um perfil a mais da nova condição —
  o aplicativo acrescenta sozinho quando o reconhecimento foi fraco.
- **Gravações presenciais** (um celular na sala) casam mal com perfis de
  chamadas online. Nelas, apoie-se no texto.
- Sempre incentive listar os presentes ao começar uma transcrição: isso
  impede trocar trechos para quem não estava lá.

## Anotações

`Notas\pessoas.md`: um título por pessoa — o nome usado nas transcrições,
apelidos, os nomes com que aparece no Zoom/WhatsApp, grupos, observações
sobre a voz ("fala baixo", "costuma entrar pelo celular"). `grupos.md`:
por grupo — quem coordena, plataforma, se há rodada de apresentações.
`aprendizados.md`: o que vai importar da próxima vez. Escreva em
português, curto, com data (DD/MM/AAAA).
