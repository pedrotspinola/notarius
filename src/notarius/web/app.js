"use strict";
// Notarius page.  All user-visible text is Portuguese; code is English.
// Every name and transcript line is inserted as text, never as HTML.

const TOKEN = document.querySelector('meta[name="notarius-token"]').content;
const view = document.getElementById("view");

// ---------------------------------------------------------------- helpers

function h(tag, attrs, ...children) {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (v === null || v === undefined || v === false) continue;
    if (k.startsWith("on")) el.addEventListener(k.slice(2), v);
    else if (k === "class") el.className = v;
    else el.setAttribute(k, v === true ? "" : v);
  }
  for (const c of children.flat()) {
    if (c === null || c === undefined || c === false) continue;
    el.append(c instanceof Node ? c : document.createTextNode(String(c)));
  }
  return el;
}

async function api(path, body) {
  const opts = { headers: { "X-Notarius-Token": TOKEN } };
  if (body !== undefined) {
    opts.method = "POST";
    opts.headers["Content-Type"] = "application/json";
    opts.body = JSON.stringify(body);
  }
  const res = await fetch(path, opts);
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.error || "internal");
  return data;
}

const ERRORS = {
  busy: "Já há um trabalho em andamento. Espere terminar ou cancele.",
  not_zoom_folder: "Esta pasta não parece uma gravação do Zoom.",
  not_audio: "Não consegui ler este arquivo como áudio ou vídeo.",
  not_found: "Arquivo ou pasta não encontrado.",
  bad_name: "Este nome não pode ser usado. Use letras, números, espaços, hífen ou ponto.",
  no_audio: "O arquivo de áudio desta reunião não está mais no lugar original.",
  out_of_memory: "Faltou memória no computador. Feche outros programas e tente de novo.",
  no_voice_messages: "Não achei mensagens de voz dessa pessoa (de pelo menos 3 segundos).",
  crashed: "O trabalho parou de repente. Veja o registro na pasta do Notarius.",
};

function toast(message, isError) {
  const t = document.getElementById("toast");
  t.textContent = message;
  t.className = isError ? "error" : "";
  t.hidden = false;
  clearTimeout(toast.timer);
  toast.timer = setTimeout(() => (t.hidden = true), isError ? 8000 : 4000);
}

function fail(err) {
  toast(ERRORS[err.message] || `Algo deu errado (${err.message}).`, true);
}

function duration(seconds) {
  if (seconds === null || seconds === undefined) return "";
  const s = Math.round(seconds);
  const hh = Math.floor(s / 3600), mm = Math.floor((s % 3600) / 60);
  if (hh) return `${hh}h${String(mm).padStart(2, "0")}`;
  if (mm) return `${mm} min`;
  return `${s} s`;
}

function clock(seconds) {
  const s = Math.floor(seconds);
  const p = (n) => String(n).padStart(2, "0");
  return `${p(Math.floor(s / 3600))}:${p(Math.floor((s % 3600) / 60))}:${p(s % 60)}`;
}

function plural(n, one, many) {
  return `${n} ${n === 1 ? one : many}`;
}

function prettyDate(date) {
  // "2026-03-16_11-00-31" -> "16/03/2026 11h00"
  const m = /^(\d{4})-(\d{2})-(\d{2})_(\d{2})-(\d{2})/.exec(date || "");
  return m ? `${m[3]}/${m[2]}/${m[1]} ${m[4]}h${m[5]}` : date || "";
}

// ------------------------------------------------------------------ audio

let current = null;
function play(meetingId, clip, button) {
  if (current) {
    current.audio.pause();
    current.button.classList.remove("playing");
    current.button.textContent = "▶";
    if (current.button === button) { current = null; return; }
  }
  const q = new URLSearchParams({
    meeting: meetingId, start: clip.start.toFixed(2), end: clip.end.toFixed(2),
    track: clip.person || "", t: TOKEN,
  });
  const audio = new Audio(`/api/clip?${q}`);
  current = { audio, button };
  button.classList.add("playing");
  button.textContent = "■";
  const done = () => {
    button.classList.remove("playing");
    button.textContent = "▶";
    if (current && current.audio === audio) current = null;
  };
  audio.addEventListener("ended", done);
  audio.addEventListener("error", () => { done(); toast(ERRORS.no_audio, true); });
  audio.play().catch(done);
}

function playButton(meetingId, clip) {
  const b = h("button", { class: "play small", title: "Ouvir", "aria-label": "Ouvir" }, "▶");
  b.addEventListener("click", () => play(meetingId, clip, b));
  return b;
}

// ------------------------------------------------------------------- jobs

const STAGES = {
  start: "Preparando",
  load: "Lendo o áudio",
  transcribe: "Transcrevendo a fala",
  align: "Alinhando as palavras",
  diarize: "Separando as vozes",
  assign: "Juntando falas e vozes",
  identify: "Reconhecendo as pessoas",
  retry_cpu: "A placa de vídeo ficou sem memória; continuando pelo processador",
  models: "Baixando os modelos",
  tune: "Medindo a velocidade deste computador",
  enroll: "Aprendendo vozes",
  done: "Pronto",
};
const KINDS = {
  transcribe: "Transcrição",
  enroll: "Aprendendo vozes",
  "enroll-files": "Cadastrando uma voz",
  tune: "Teste de velocidade",
  setup: "Preparando o Notarius",
};

let poller = null;
function watchJob(onChange) {
  clearInterval(poller);
  poller = setInterval(async () => {
    try {
      const { job } = await api("/api/job");
      onChange(job);
      if (!job || job.state !== "running") clearInterval(poller);
    } catch { clearInterval(poller); }
  }, 2000);
}

function jobCard(job, onChange) {
  if (!job) return null;
  const name = KINDS[job.kind] || job.kind;
  const elapsed = job.elapsed || 0;
  let bar = null, eta = "";
  if (job.state === "running") {
    if (job.expected_seconds) {
      const pct = Math.min(99, (100 * elapsed) / job.expected_seconds);
      bar = h("div", { class: "progress" }, h("div", { style: `width:${pct}%` }));
      const left = Math.max(0, job.expected_seconds - elapsed);
      eta = left > 30 ? ` · faltam cerca de ${duration(left)}` : " · quase lá";
    } else {
      bar = h("div", { class: "progress indeterminate" }, h("div"));
    }
  }
  const stage = STAGES[job.stage] || job.stage;
  const detail = job.kind === "enroll" && job.state === "running" && job.message ? `: ${job.message}` : "";
  const lines = [h("div", { class: "row spread" },
    h("strong", {}, name),
    h("span", { class: "dim" }, `${duration(elapsed)} decorridos${eta}`))];
  if (job.state === "running") {
    lines.push(h("p", {}, stage + detail + "…"), bar,
      h("p", { class: "dim" }, "Pode deixar o computador trabalhando; ele não vai dormir enquanto isso."),
      h("button", { class: "small", onclick: async () => {
        if (!confirm("Cancelar este trabalho?")) return;
        onChange((await api("/api/job/cancel", {})).job);
      } }, "Cancelar"));
  } else if (job.state === "done") {
    lines.push(h("p", { class: "ok" }, "Terminou."));
    if (job.kind === "transcribe" && job.result) {
      lines.push(h("div", { class: "row" },
        h("button", { class: "primary", onclick: () => { dismiss(); location.hash = `#/reuniao/${encodeURIComponent(job.result.meeting)}`; } }, "Revisar agora"),
        h("button", { onclick: dismiss }, "Fechar")));
    } else {
      lines.push(h("button", { onclick: dismiss }, "Fechar"));
    }
  } else {
    const msg = job.state === "cancelled" ? "Cancelado." : (ERRORS[job.error] || `Falhou: ${job.error}`);
    lines.push(h("p", { class: job.state === "cancelled" ? "dim" : "error" }, msg),
      h("button", { onclick: dismiss }, "Fechar"));
  }
  async function dismiss() { await api("/api/job/dismiss", {}); onChange(null); }
  return h("div", { class: "card", id: "job" }, lines);
}

// ------------------------------------------------------------------ views

async function home() {
  const [state, { meetings }] = await Promise.all([api("/api/state"), api("/api/meetings")]);
  const jobSlot = h("div");
  const render = (job) => {
    jobSlot.replaceChildren(jobCard(job, render) || "");
    if (job && job.state === "running") watchJob(render);
    if (job && job.state === "done") refreshList();
  };
  const list = h("div");
  const refreshList = async () => list.replaceChildren(...meetingList((await api("/api/meetings")).meetings));
  list.replaceChildren(...meetingList(meetings));

  const setupWarning = !state.models_ready
    ? h("div", { class: "card" }, h("p", { class: "error" },
        "O Notarius ainda não está pronto: faltam os modelos de reconhecimento."),
        h("button", { class: "primary", onclick: () => (location.hash = "#/ajustes") }, "Preparar agora"))
    : null;
  view.replaceChildren(
    h("div", { class: "row spread" },
      h("h1", {}, "Reuniões"),
      h("button", { class: "primary big", onclick: () => (location.hash = "#/nova") }, "Nova transcrição")),
    setupWarning, jobSlot, list);
  render(state.job);
}

function meetingList(meetings) {
  if (!meetings.length) {
    return [h("div", { class: "card" },
      h("p", {}, "Nenhuma reunião transcrita ainda."),
      h("p", { class: "dim" }, "Clique em “Nova transcrição” e escolha uma gravação ou uma pasta do Zoom."))];
  }
  return meetings.map((m) => {
    const todo = m.review_status !== "done";
    const unknown = m.unknowns.length;
    const badge = todo
      ? h("span", { class: "badge todo" }, unknown ? `${plural(unknown, "voz", "vozes")} para identificar` : "para revisar")
      : h("span", { class: "badge" }, "revisada");
    return h("div", { class: "card meeting" },
      h("div", { class: "grow" },
        h("div", { class: "title" }, m.title),
        h("div", { class: "dim" }, [prettyDate(m.date), duration(m.duration), plural(m.people.length, "pessoa", "pessoas")].filter(Boolean).join(" · "))),
      badge,
      h("button", { class: todo ? "primary" : "", onclick: () => (location.hash = `#/reuniao/${encodeURIComponent(m.id)}`) },
        todo ? "Revisar" : "Abrir"));
  });
}

async function newTranscription() {
  const state = await api("/api/state");
  const { people } = await api("/api/people");
  let source = null;
  const attendees = [];

  const summary = h("div");
  const chips = h("div", { class: "chips" });
  const nameInput = h("input", { type: "text", list: "known-people", placeholder: "Digite um nome e aperte Enter" });
  const datalist = h("datalist", { id: "known-people" }, people.map((p) => h("option", { value: p.name })));
  const start = h("button", { class: "primary big", disabled: true }, "Começar a transcrição");

  function addAttendee(name) {
    name = name.trim().replace(/\s+/g, " ");
    if (!name || attendees.some((a) => a.toLowerCase() === name.toLowerCase())) return;
    attendees.push(name);
    drawChips();
  }
  function drawChips() {
    chips.replaceChildren(...attendees.map((a, i) => h("span", { class: "chip" }, a,
      h("button", { "aria-label": `Tirar ${a}`, onclick: () => { attendees.splice(i, 1); drawChips(); } }, "×"))));
  }
  nameInput.addEventListener("keydown", (e) => {
    if (e.key === "Enter" || e.key === ",") { e.preventDefault(); addAttendee(nameInput.value); nameInput.value = ""; }
  });
  nameInput.addEventListener("change", () => {
    if (people.some((p) => p.name === nameInput.value)) { addAttendee(nameInput.value); nameInput.value = ""; }
  });

  async function choose(kind) {
    try {
      const { path } = await api("/api/pick", { kind });
      if (!path) return;
      summary.replaceChildren(h("p", { class: "dim" }, "Verificando…"));
      source = await api("/api/inspect", { path });
      drawSummary();
      start.disabled = false;
    } catch (e) { summary.replaceChildren(); fail(e); }
  }
  function drawSummary() {
    const lines = [h("p", {}, h("strong", {}, source.path))];
    if (source.kind === "tracks") {
      lines.push(h("p", {}, `Gravação do Zoom com um áudio por participante (${source.participants.length}): `
        + "cada pessoa já vem separada, o que é mais rápido e mais confiável."),
        h("p", { class: "dim" }, source.participants.join(", ")));
    } else {
      lines.push(h("p", {}, `Gravação de ${duration(source.duration)}. O Notarius vai separar as vozes e reconhecer quem já conhece.`));
    }
    lines.push(h("p", {}, source.estimate
      ? `Tempo estimado neste computador: cerca de ${duration(source.estimate)}.`
      : "Ainda não sei quanto tempo vai levar neste computador."));
    summary.replaceChildren(h("div", { class: "card" }, lines));
  }

  start.addEventListener("click", async () => {
    if (nameInput.value.trim()) { addAttendee(nameInput.value); nameInput.value = ""; }
    start.disabled = true;
    try {
      await api("/api/jobs/transcribe", { path: source.path, attendees });
      location.hash = "#/";
    } catch (e) { start.disabled = false; fail(e); }
  });

  view.replaceChildren(
    h("h1", {}, "Nova transcrição"),
    h("h2", {}, "1. Qual gravação?"),
    h("div", { class: "row" },
      h("button", { class: "big", onclick: () => choose("file") }, "Escolher arquivo de áudio ou vídeo"),
      h("button", { class: "big", onclick: () => choose("folder") }, "Escolher pasta do Zoom")),
    summary,
    h("h2", {}, "2. Quem estava na reunião? (opcional)"),
    h("p", { class: "dim" }, "Ajuda o Notarius a não confundir vozes parecidas. Pode listar só quem você lembra."),
    h("div", { class: "row" }, nameInput, datalist),
    chips,
    h("h2", {}, "3. Começar"),
    state.job && state.job.state === "running"
      ? h("p", { class: "error" }, "Espere o trabalho atual terminar antes de começar outro.")
      : null,
    start);
}

// ---------------------------------------------------------------- meeting

const REASONS = {
  unknown: (it) => `Uma voz que o Notarius não conhece (${duration(it.seconds)} de fala). Quem é?`,
  unproven: (it) => `O Notarius acha que é ${it.current}, mas a semelhança é fraca. Está certo?`,
  low_margin: (it) => `O Notarius acha que é ${it.current}, mas ficou em dúvida com outra pessoa. Está certo?`,
  not_listed: (it) => `O Notarius acha que é ${it.current}, que não estava na lista de presentes. Está certo?`,
  reassigned: (it) => `O Notarius mudou este trecho para ${it.current}. Está certo?`,
  gated: (it) => `Este trecho soa como outra pessoa, que não estava na lista de presentes. Quem disse?`,
  suspect: (it) => `Este trecho está como ${it.current}, mas soa como outra pessoa. Quem disse?`,
  flagged: (it) => `A voz deste trecho não confere bem com ${it.current}. Quem disse?`,
  self_address: (it) => `Aqui ${it.current} chama alguém pelo próprio nome — provavelmente é outra pessoa falando. Quem disse?`,
};
const WHY = {
  voice: "voz parecida",
  intro: "disse o próprio nome",
  called: "foi chamado(a) assim logo antes",
  listed: "estava na lista e ainda não falou",
  current: "como está agora",
  verify: "voz parecida neste trecho",
  before: "como estava antes",
  neighbour: "quem falava logo antes",
};

async function meetingView(id, tab) {
  let data;
  try { data = await api(`/api/meetings/${encodeURIComponent(id)}`); } catch (e) { fail(e); location.hash = "#/"; return; }
  const answers = {};
  const m = data.meeting;
  tab = tab || (m.review_status === "done" && !data.items.length ? "text" : "review");

  const header = h("div", {},
    h("a", { href: "#/", class: "dim" }, "← Reuniões"),
    h("h1", {}, m.title),
    h("p", { class: "dim" }, [prettyDate(m.date), duration(m.duration), m.people.join(", ")].filter(Boolean).join(" · ")),
    h("div", { class: "row" },
      h("button", { class: "small", onclick: () => api("/api/open", { target: "text", id }).catch(fail) }, "Abrir o texto"),
      h("button", { class: "small", onclick: () => api("/api/open", { target: "meetings" }).catch(fail) }, "Abrir a pasta")));
  const tabs = h("div", { class: "tabs" },
    h("button", { class: tab === "review" ? "active" : "", onclick: () => meetingView(id, "review") }, `Revisar (${data.items.length})`),
    h("button", { class: tab === "text" ? "active" : "", onclick: () => meetingView(id, "text") }, "Transcrição"),
    h("button", { class: tab === "learn" ? "active" : "", onclick: () => meetingView(id, "learn") }, "Aprender vozes"));

  let body;
  if (tab === "text") body = transcriptPane(id, data);
  else if (tab === "learn") body = await learnPane(id);
  else body = reviewPane(id, data, answers);
  view.replaceChildren(header, tabs, body);
}

function reviewPane(id, data, answers) {
  if (!data.items.length) {
    return h("div", { class: "card" },
      h("p", {}, "Nada para revisar: todas as vozes foram reconhecidas com segurança."),
      h("p", { class: "dim" }, "Mesmo assim, você pode conferir e corrigir qualquer fala na aba “Transcrição”."),
      h("button", { class: "primary", onclick: () => meetingView(id, "learn") }, "Aprender as vozes desta reunião"));
  }
  const cards = data.items.map((it) => itemCard(id, it, data.known_people, answers));
  const save = h("button", { class: "primary big" }, "Salvar respostas");
  save.addEventListener("click", async () => {
    save.disabled = true;
    try {
      const res = await api(`/api/meetings/${encodeURIComponent(id)}/answers`, { answers });
      const n = Object.values(res.changed).reduce((a, b) => a + b, 0);
      toast(n ? `Transcrição corrigida: ${plural(n, "trecho mudou", "trechos mudaram")}.` : "Nada mudou na transcrição.");
      meetingView(id, "learn");
    } catch (e) { save.disabled = false; fail(e); }
  });
  return h("div", {},
    h("p", {}, "Ouça os trechos e diga quem está falando. O que você deixar sem resposta fica como está."),
    cards, h("div", { class: "row" }, save));
}

function itemCard(id, it, known, answers) {
  const question = (REASONS[it.reason] || REASONS.unknown)(it);
  const clips = h("div", { class: "clips" }, it.clips.map((c) =>
    h("div", { class: "clip" }, playButton(id, c),
      h("span", {}, h("span", { class: "time dim" }, clock(c.start)), " ", h("span", { class: "text" }, `“${c.text}”`)))));
  const context = it.context.length
    ? h("div", { class: "context" }, it.context.map((l) =>
        h("p", { class: l.focus ? "focus" : "dim" }, h("strong", {}, l.speaker), ` [${l.time}]: ${l.text}`)))
    : null;
  const buttons = [];
  const input = h("input", { type: "text", list: "known-people-review", placeholder: "Outro nome" });
  function choose(name, button) {
    for (const b of buttons) b.classList.remove("chosen");
    if (answers[it.id] === name && button) { delete answers[it.id]; return; }
    answers[it.id] = name;
    if (button) { button.classList.add("chosen"); input.value = ""; }
  }
  const suggestions = h("div", { class: "suggestions" }, it.suggestions.map((s) => {
    const why = WHY[s.why] || "";
    const b = h("button", { onclick: () => choose(s.name, b) }, s.name, why ? h("small", {}, why) : null);
    buttons.push(b);
    return b;
  }));
  input.addEventListener("input", () => {
    for (const b of buttons) b.classList.remove("chosen");
    if (input.value.trim()) answers[it.id] = input.value.trim(); else delete answers[it.id];
  });
  return h("div", { class: "card" },
    h("p", {}, h("strong", {}, question)),
    clips, context, suggestions,
    h("div", { class: "answer row" }, input,
      h("datalist", { id: "known-people-review" }, known.map((n) => h("option", { value: n })))));
}

function transcriptPane(id, data) {
  const known = data.known_people;
  const lines = data.lines.map((l) => {
    const who = h("span", { class: "who", title: "Clique para corrigir quem falou" }, l.speaker);
    who.addEventListener("click", async () => {
      const name = prompt(`Quem disse isto?\n\n“${l.text.slice(0, 200)}”`, l.speaker);
      if (!name || name.trim() === l.speaker) return;
      try {
        await api(`/api/meetings/${encodeURIComponent(id)}/rename`, { indices: l.indices, name: name.trim() });
        meetingView(id, "text");
      } catch (e) { fail(e); }
    });
    return h("div", { class: "line" }, playButton(id, { start: l.start, end: Math.min(l.end, l.start + 30), person: l.person }),
      h("div", { class: "grow" }, who, " ", h("span", { class: "time" }, `[${l.time}]`), " ", l.text));
  });
  return h("div", {},
    h("p", { class: "dim" }, "Clique em ▶ para ouvir e no nome para corrigir quem falou."),
    h("div", { class: "lines" }, lines),
    h("datalist", { id: "known-people-text" }, known.map((n) => h("option", { value: n }))));
}

const PLAN_REASONS = {
  new_person: "pessoa nova",
  new_variant: "a voz nesta reunião soou diferente da que o Notarius já conhecia",
  recognized_well: "já é reconhecida bem",
  already_enrolled: "já tem voz cadastrada",
  too_little_speech: "falou pouco nesta reunião",
  too_many: "já tem o máximo de vozes guardadas",
  invalid_name: "nome não pode ser usado",
};

async function learnPane(id) {
  const { plan } = await api(`/api/meetings/${encodeURIComponent(id)}/plan`);
  const chosen = new Set(plan.filter((p) => p.action === "enroll").map((p) => p.person));
  const rows = plan.map((p) => {
    const box = p.action === "enroll"
      ? h("input", { type: "checkbox", checked: true, onchange: (e) => e.target.checked ? chosen.add(p.person) : chosen.delete(p.person) })
      : null;
    let note = PLAN_REASONS[p.code] || p.code;
    if (p.code === "too_little_speech") note += ` (${p.clean_seconds} s de fala limpa; precisa de 45 s)`;
    return h("label", { class: "card row" }, box, h("span", { class: "grow" }, h("strong", {}, p.person)),
      h("span", { class: p.action === "enroll" ? "" : "dim" }, note));
  });
  const go = h("button", { class: "primary big", disabled: !chosen.size }, "Guardar estas vozes");
  const jobSlot = h("div");
  const render = (job) => {
    jobSlot.replaceChildren(jobCard(job, render) || "");
    if (job && job.state === "running") watchJob(render);
    if (job && job.state === "done" && job.kind === "enroll" && job.result) {
      const ok = job.result.outcomes.filter((o) => o.ok).map((o) => o.person);
      toast(ok.length ? `Vozes guardadas: ${ok.join(", ")}.` : "Nenhuma voz foi guardada.");
    }
  };
  go.addEventListener("click", async () => {
    go.disabled = true;
    try { render((await api(`/api/meetings/${encodeURIComponent(id)}/enroll`, { people: [...chosen] })).job); }
    catch (e) { go.disabled = false; fail(e); }
  });
  return h("div", {},
    h("p", {}, "Guardar a voz de quem falou nesta reunião faz o Notarius reconhecer essas pessoas sozinho da próxima vez."),
    h("p", { class: "dim" }, "Faça isso só depois de conferir os nomes: uma voz guardada com o nome errado confunde as próximas reuniões."),
    rows,
    plan.some((p) => p.action === "enroll")
      ? go
      : h("p", {}, "Ninguém desta reunião precisa ser guardado agora (veja o motivo ao lado de cada nome)."),
    jobSlot);
}

// ----------------------------------------------------------------- people

async function peopleView() {
  const { people } = await api("/api/people");
  const jobSlot = h("div");
  const render = (job) => {
    jobSlot.replaceChildren(jobCard(job, render) || "");
    if (job && job.state === "running") watchJob(render);
    if (job && job.state === "done" && job.kind === "enroll-files") peopleView();
  };

  const rows = people.map((p) => {
    const aliasInput = h("input", { type: "text", placeholder: "Outro nome (ex.: nome no Zoom)" });
    aliasInput.addEventListener("keydown", async (e) => {
      if (e.key !== "Enter" || !aliasInput.value.trim()) return;
      try { await api("/api/people/alias", { person: p.name, alias: aliasInput.value }); peopleView(); } catch (err) { fail(err); }
    });
    return h("div", { class: "card" },
      h("div", { class: "row spread" },
        h("strong", {}, p.name),
        h("span", { class: "dim" }, p.profiles > 1 ? `${p.profiles} gravações de voz` : "1 gravação de voz"),
        h("div", { class: "row" },
          h("button", { class: "small", onclick: async () => {
            const name = prompt("Novo nome:", p.name);
            if (!name || name.trim() === p.name) return;
            try { await api("/api/people/rename", { old: p.name, new: name }); peopleView(); } catch (e) { fail(e); }
          } }, "Renomear"),
          h("button", { class: "small danger", onclick: async () => {
            if (!confirm(`Apagar a voz de ${p.name}? O Notarius deixa de reconhecer essa pessoa.`)) return;
            try { await api("/api/people/delete", { name: p.name }); peopleView(); } catch (e) { fail(e); }
          } }, "Apagar"))),
      h("div", { class: "chips" }, p.aliases.map((a) => h("span", { class: "chip" }, a,
        h("button", { "aria-label": `Tirar ${a}`, onclick: async () => {
          await api("/api/people/alias", { person: p.name, alias: a, remove: true }).catch(fail); peopleView();
        } }, "×")))),
      h("div", { class: "row answer" }, aliasInput));
  });

  async function fromWhatsApp() {
    try {
      const { path } = await api("/api/pick", { kind: "folder" });
      if (!path) return;
      const { senders } = await api("/api/whatsapp/senders", { path });
      if (!senders.length) return toast("Não achei mensagens de voz nesta conversa exportada.", true);
      const list = senders.map(([s, n]) => `${s} (${n} áudios)`).join("\n");
      const sender = prompt(`De quem é a voz? Copie o nome exatamente:\n\n${list}`, senders[0][0]);
      if (!sender) return;
      const name = prompt("Com que nome guardar essa pessoa?", sender);
      if (!name) return;
      render((await api("/api/jobs/enroll-files", { name, whatsapp_dir: path, sender })).job);
    } catch (e) { fail(e); }
  }
  async function fromFile() {
    try {
      const { path } = await api("/api/pick", { kind: "file" });
      if (!path) return;
      const name = prompt("De quem é a voz nesta gravação? (só essa pessoa deve falar nela)");
      if (!name) return;
      render((await api("/api/jobs/enroll-files", { name, files: [path] })).job);
    } catch (e) { fail(e); }
  }

  view.replaceChildren(
    h("h1", {}, "Pessoas"),
    h("p", { class: "dim" }, "As vozes que o Notarius conhece. Elas ficam só neste computador."),
    h("div", { class: "row" },
      h("button", { onclick: fromWhatsApp }, "Adicionar voz por conversa do WhatsApp"),
      h("button", { onclick: fromFile }, "Adicionar voz por gravação")),
    h("p", { class: "dim" }, "No WhatsApp: abra a conversa → Mais → Exportar conversa → Incluir mídia; depois extraia o arquivo .zip numa pasta."),
    jobSlot,
    people.length ? rows : h("div", { class: "card" }, h("p", {}, "Nenhuma voz guardada ainda."),
      h("p", { class: "dim" }, "Elas aparecem aqui depois de revisar uma reunião e clicar em “Aprender vozes”.")));
  render((await api("/api/job")).job);
}

// --------------------------------------------------------------- settings

async function settingsView() {
  const state = await api("/api/state");
  const t = state.tuning;
  const jobSlot = h("div");
  const render = (job) => {
    jobSlot.replaceChildren(jobCard(job, render) || "");
    if (job && job.state === "running") watchJob(render);
    if (job && job.state === "done" && (job.kind === "tune" || job.kind === "setup")) settingsView();
  };
  const device = t ? (t.device === "cuda" ? "placa de vídeo" : "processador") : "—";
  const prepare = !state.models_ready
    ? h("div", { class: "card" },
        h("p", {}, h("strong", {}, "Preparar o Notarius")),
        h("p", {}, "Baixa os modelos de reconhecimento (cerca de 5 GB) e mede a velocidade deste computador. "
          + "Pode levar de 15 minutos a uma hora, conforme a internet e o computador."),
        h("button", { class: "primary", onclick: async () => {
          try { render((await api("/api/jobs/setup", {})).job); } catch (e) { fail(e); }
        } }, "Preparar agora"))
    : null;
  view.replaceChildren(
    h("h1", {}, "Ajustes"),
    prepare,
    t ? h("div", { class: "card" },
      h("p", {}, `Este computador: ${t.ram_gb ? `${t.ram_gb} GB de memória, ` : ""}usa o ${device}.`),
      h("p", {}, t.seconds_per_audio_minute
        ? `Velocidade medida: cerca de ${duration(t.seconds_per_audio_minute * 60)} para cada hora de reunião.`
        : "A velocidade ainda não foi medida."),
      h("p", { class: "dim" }, `Modelo de fala: ${t.model}`),
      state.models_ready ? h("button", { onclick: async () => {
        try { render((await api("/api/jobs/tune", {})).job); } catch (e) { fail(e); }
      } }, "Medir a velocidade de novo") : null) : null,
    jobSlot,
    h("div", { class: "card" },
      h("p", {}, "Tudo o que o Notarius guarda fica em:"),
      h("p", {}, h("strong", {}, state.data_dir)),
      h("div", { class: "row" },
        h("button", { onclick: () => api("/api/open", { target: "data" }).catch(fail) }, "Abrir essa pasta"),
        h("button", { onclick: () => api("/api/open", { target: "meetings" }).catch(fail) }, "Abrir as transcrições"))),
    h("p", { class: "dim" }, `Notarius ${state.version}`));
  render(state.job);
}

// ----------------------------------------------------------------- router

async function route() {
  const hash = location.hash || "#/";
  const parts = hash.slice(2).split("/");
  for (const a of document.querySelectorAll("[data-nav]")) {
    const target = { "": "home", nova: "home", reuniao: "home", pessoas: "people", ajustes: "settings" }[parts[0]];
    a.classList.toggle("active", a.dataset.nav === target);
  }
  clearInterval(poller);
  try {
    if (parts[0] === "nova") await newTranscription();
    else if (parts[0] === "reuniao") await meetingView(decodeURIComponent(parts[1] || ""));
    else if (parts[0] === "pessoas") await peopleView();
    else if (parts[0] === "ajustes") await settingsView();
    else await home();
  } catch (e) { fail(e); }
}

window.addEventListener("hashchange", route);
route();
