// The lab's page: a small, dependency-free front for the local API.

const $ = (selector, root = document) => root.querySelector(selector);
const $$ = (selector, root = document) => [...root.querySelectorAll(selector)];
const state = { data: null, build: null, k: 8, mode: "both" };
const TABS = ["sources", "build", "ask", "results"];

// --- helpers -------------------------------------------------------------------------

async function api(path, options = {}) {
  const response = await fetch(path, options);
  const body = response.headers.get("content-type")?.includes("json")
    ? await response.json()
    : await response.text();
  if (!response.ok) throw new Error(body?.detail ?? body ?? response.statusText);
  return body;
}
const send = (path, method, data) =>
  api(path, { method, headers: { "Content-Type": "application/json" }, body: JSON.stringify(data ?? {}) });

function escape(text) {
  return String(text ?? "").replace(/[&<>"']/g, (c) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  })[c]);
}
const money = (usd) => (usd === null || usd === undefined ? "unknown" : usd === 0 ? "$0" : `$${usd < 0.01 ? usd.toFixed(5) : usd.toFixed(3)}`);
const num = (n) => Number(n ?? 0).toLocaleString("en-US", { maximumFractionDigits: 0 });
const plural = (n, word) => `${n} ${word}${n === 1 ? "" : "s"}`;
const secs = (s) => `${Number(s ?? 0).toFixed(1)} s`;
const NAMES = { wiki: "WikiLLM", rag: "Vector search" };

let toastTimer;
function toast(message, bad = false) {
  const el = $("#toast");
  el.textContent = message;
  el.className = `toast show${bad ? " bad" : ""}`;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => { el.className = "toast"; }, bad ? 6000 : 2600);
}

// Answers come as Markdown with [[source#^p3]] citations and [[page]] links. Everything is
// escaped first, so model output can never inject markup.
function render(markdown, arm) {
  const inline = (text) => escape(text)
    .replace(/ ?\[\[([^\[\]|#]+)#\^(p\d+)\]\]/g, (_, src, p) =>
      ` <button class="cite" type="button" data-cite="${src}#^${p}" data-arm="${arm}" title="Show the cited paragraph">${p}</button>`)
    .replace(/\[\[([^\[\]|#]+)(?:\|([^\[\]]*))?\]\]/g, (_, page, alias) => `<em>${alias || page}</em>`)
    .replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>")
    .replace(/(^|[^*])\*([^*]+)\*/g, "$1<em>$2</em>")
    .replace(/`([^`]+)`/g, "<code>$1</code>");
  return String(markdown ?? "").trim().split(/\n{2,}/).map((block) => {
    const lines = block.split("\n");
    if (lines.every((l) => /^\s*[-*] /.test(l))) {
      return `<ul>${lines.map((l) => `<li>${inline(l.replace(/^\s*[-*] /, ""))}</li>`).join("")}</ul>`;
    }
    if (lines.every((l) => /^\s*\d+[.)] /.test(l))) {
      return `<ol>${lines.map((l) => `<li>${inline(l.replace(/^\s*\d+[.)] /, ""))}</li>`).join("")}</ol>`;
    }
    return `<p>${lines.map(inline).join("<br>")}</p>`;
  }).join("");
}

async function follow(job, log, describe) {
  log.hidden = false;
  while (true) {
    const current = await api(`/api/jobs/${job.id}`);
    log.innerHTML = describe(current);
    if (current.status !== "running") return current;
    await new Promise((resolve) => setTimeout(resolve, 700));
  }
}

// --- state and chrome ----------------------------------------------------------------

async function refresh() {
  state.data = await api("/api/state");
  const { vault, config, session, types } = state.data;
  $("#welcome").hidden = Boolean(vault);
  $("#workspace").hidden = !vault;
  $("#folder").value ||= state.data.suggested;
  $("#types").textContent = types.map((t) => `.${t}`).join("  ");
  $("#fileInput").accept = types.map((t) => `.${t}`).join(",");

  $("#vaultChip").textContent = vault ? vault.root : "No folder";
  $("#vaultChip").classList.toggle("on", Boolean(vault));
  $("#modelChip").textContent = config.model ? config.model : "No model · set up";
  $("#modelChip").classList.toggle("on", Boolean(config.model));
  $("#spendChip").hidden = !session.calls;
  $("#spendChip").textContent = `${plural(session.calls, "call")} · ${money(session.usd)}`;
  if (!vault) return;

  $("#vaultPath").innerHTML = `${plural(vault.sources.length, "file")} · ${plural(vault.pages, "wiki page")}<span class="path" title="${escape(vault.root)}">${escape(vault.root)}</span>`;
  $("#countSources").textContent = vault.sources.length || "";
  $("#sourceList").innerHTML = vault.sources.length
    ? vault.sources.map((s) => `<li><b>${escape(s.title)}</b><span class="marks"><span class="mini wiki ${s.wiki ? "on" : ""}">${s.wiki ? "in WikiLLM" : "not in WikiLLM"}</span></span><small>${escape(s.original)} · ${escape(s.id)}</small></li>`).join("")
    : `<li class="empty">Nothing yet. Added files appear here.</li>`;
  $("#toBuild").hidden = !vault.sources.length;
  await refreshBuild();
}

async function refreshBuild() {
  if (!state.data?.vault) return;
  state.build = await api("/api/build");
  const { rag, wiki } = state.build;
  const config = state.data.config;

  $("#retrieval").value = config.retrieval;
  const local = config.retrieval === "local";
  const input = $("#embeddingModel");
  input.hidden = config.retrieval === "bm25";
  input.value = config.embedding_model;
  input.placeholder = local ? state.data.local_model : "text-embedding-3-small";
  $("#retrievalNote").textContent = {
    local: state.data.local_embeddings
      ? "Runs on your computer, free. The study's model; for non-English files try sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2. Downloaded once."
      : "Install the lab extra to compute embeddings locally: uv sync --extra lab.",
    provider: "Your provider's embedding endpoint, at its price.",
    bm25: "Matches words, not meaning. No index to build: useful as a baseline.",
  }[config.retrieval];

  const ragShare = rag.paragraphs ? rag.indexed / rag.paragraphs : 0;
  $("#ragBar").style.width = `${ragShare * 100}%`;
  $("#ragStatus").innerHTML = rag.error
    ? `<span class="rag-t">${escape(rag.error)}</span>`
    : rag.ready
      ? `<b>Ready</b> · ${num(rag.paragraphs)} paragraphs searchable with ${escape(rag.label)}`
      : rag.paragraphs
        ? `${num(rag.indexed)} of ${num(rag.paragraphs)} paragraphs indexed`
        : "Add files first";
  $("#ragBuildCost").textContent = config.retrieval === "local"
    ? "No model calls: embeddings run on your computer"
    : config.retrieval === "bm25" ? "Nothing to build" : "Embedding calls at your provider's price";
  const indexButton = $("#buildIndex");
  indexButton.hidden = config.retrieval === "bm25";
  indexButton.disabled = !rag.paragraphs || rag.ready;
  indexButton.textContent = rag.ready ? "Vector index built" : rag.indexed ? "Update vector index" : "Build vector index";

  const total = wiki.sources + wiki.pending;
  $("#wikiBar").style.width = `${total ? (wiki.sources / total) * 100 : 0}%`;
  $("#wikiStatus").innerHTML = !total
    ? "Add files first"
    : wiki.pending
      ? `${wiki.sources} of ${total} files written into the wiki · ${plural(wiki.pages, "page")}`
      : `<b>Ready</b> · ${plural(wiki.pages, "page")} from ${plural(total, "file")}`;
  const estimate = wiki.estimate;
  $("#wikiBuildCost").textContent = estimate
    ? `About ${estimate.calls} model calls and ${money(estimate.usd)} for ${plural(estimate.files, "new file")}, once`
    : wiki.spent_usd !== null ? `Spent ${money(wiki.spent_usd)} so far, once` : "2 model calls per file, once";
  const wikiButton = $("#buildWiki");
  wikiButton.disabled = !wiki.pending;
  wikiButton.textContent = !total || wiki.pending ? (wiki.sources ? "Update WikiLLM" : "Build WikiLLM") : "WikiLLM built";

  updateModes();
}

function selectTab(name) {
  if (!TABS.includes(name)) name = "sources";
  try { history.replaceState(null, "", `#${name}`); } catch { /* file previews */ }
  scrollTo(0, 0);
  for (const tab of $$(".steps [role=tab]")) {
    const on = tab.getAttribute("aria-controls") === name;
    tab.setAttribute("aria-selected", on);
    $(`#${tab.getAttribute("aria-controls")}`).hidden = !on;
  }
  if (name === "build") refreshBuild();
  if (name === "ask") loadAnswers();
  if (name === "results") loadResults();
}

// --- settings ------------------------------------------------------------------------

function openSettings() {
  const form = $("#settingsForm");
  const config = state.data.config;
  for (const [key, value] of Object.entries(config)) {
    if (form.elements[key]) form.elements[key].value = value ?? "";
  }
  form.elements.api_key.value = "";
  $("#keyNote").textContent = config.api_key_set
    ? "A key is set. Leave empty to keep it."
    : "Kept in memory only, never written to disk.";
  $("#settings").showModal();
}

async function saveConfig(changes) {
  const data = { ...state.data.config, api_key: null, ...changes };
  delete data.api_key_set;
  await send("/api/config", "PUT", data);
  await refresh();
}

async function saveSettings(event) {
  if (event.submitter?.value !== "save") return;
  const data = Object.fromEntries(new FormData($("#settingsForm")).entries());
  for (const key of ["price_input", "price_output", "max_usd"]) data[key] = Number(data[key] || 0);
  data.context_tokens = Number(data.context_tokens || 32000);
  if (!data.api_key) data.api_key = null;
  try {
    await saveConfig(data);
    toast("Model settings saved");
  } catch (error) {
    toast(error.message, true);
  }
}

// --- 1 · files -----------------------------------------------------------------------

async function addFiles(files) {
  if (!files.length) return;
  const form = new FormData();
  for (const file of files) form.append("files", file);
  const log = $("#addLog");
  log.hidden = false;
  log.innerHTML = `<div class="now">Extracting ${plural(files.length, "file")}</div>`;
  try {
    const result = await api("/api/sources", { method: "POST", body: form });
    log.innerHTML = [
      ...result.added.map((a) => a.skipped
        ? `<div>• ${escape(a.title)} was already added</div>`
        : `<div class="good">✓ ${escape(a.title)} · ${plural(a.paragraphs, "paragraph")}</div>`),
      ...result.failed.map((f) => `<div class="bad">✗ ${escape(f.file)}: ${escape(f.error)}</div>`),
    ].join("");
  } catch (error) {
    log.innerHTML = `<div class="bad">✗ ${escape(error.message)}</div>`;
  }
  await refresh();
}

// --- 2 · build -----------------------------------------------------------------------

async function buildIndex() {
  $("#buildIndex").disabled = true;
  try {
    const job = await send("/api/build/index", "POST");
    const done = await follow(job, $("#indexLog"), (j) => {
      const last = j.events.at(-1);
      if (j.error) return `<div class="bad">✗ ${escape(j.error)}</div>`;
      if (j.status === "done") return `<div class="good">✓ ${num(j.result.indexed)} paragraphs indexed</div>`;
      if (!last || !last.total) return `<div class="now">Loading the embedding model (the first time it is downloaded)</div>`;
      return `<div class="now">Embedding ${num(last.done)} of ${num(last.total)} paragraphs</div>`;
    });
    if (done.status === "done") toast("Vector search is ready. Ask in step 3.");
  } catch (error) {
    toast(error.message, true);
  }
  await refreshBuild();
}

async function buildWiki() {
  if (!state.data.config.model) { openSettings(); return; }
  $("#buildWiki").disabled = true;
  try {
    const job = await send("/api/build/wiki", "POST");
    const done = await follow(job, $("#wikiLog"), (j) => {
      const last = j.events.at(-1);
      const lines = j.status === "running" && last
        ? [`<div class="now">${escape(last.file)} · ${last.stage} · part ${last.part} of ${last.parts}</div>`]
        : [];
      for (const r of j.result ?? []) {
        lines.push(r.error
          ? `<div class="bad">✗ ${escape(r.file)}: ${escape(r.error)} Nothing changed.</div>`
          : `<div class="good">✓ ${escape(r.file)}: ${r.created.length} pages created, ${r.updated.length} updated</div>`);
      }
      if (j.error) lines.push(`<div class="bad">✗ ${escape(j.error)}</div>`);
      return lines.join("") || `<div class="now">Starting</div>`;
    });
    if (done.status === "done") toast("WikiLLM built. Ask in step 3.");
  } catch (error) {
    toast(error.message, true);
  }
  await refresh();
}

// --- 3 · ask -------------------------------------------------------------------------

function updateModes() {
  const ready = { rag: state.build?.rag.ready, wiki: state.build?.wiki.ready };
  ready.both = ready.rag && ready.wiki;
  for (const button of $$(".seg.mode button")) button.disabled = !ready[button.dataset.mode];
  if (!ready[state.mode]) state.mode = ready.both ? "both" : ready.rag ? "rag" : ready.wiki ? "wiki" : "both";
  setMode(state.mode, false);
}

function setMode(mode, reload = true) {
  state.mode = mode;
  for (const button of $$(".seg.mode button")) button.setAttribute("aria-checked", button.dataset.mode === mode);
  const ready = state.build && (mode === "both" ? state.build.rag.ready && state.build.wiki.ready : state.build[mode].ready);
  $("#modeNote").textContent = {
    both: "Each question goes to both with the same model. Add an expected answer (key terms, or none) to score them; the comparisons feed the recommendation in step 4.",
    rag: "Answers from the paragraphs closest to the question, in one model call.",
    wiki: "An agent searches and reads the wiki's pages, up to 8 model calls.",
  }[mode];
  $("#kbox").hidden = mode === "wiki";
  $$(".q .expected").forEach((input) => { input.hidden = mode !== "both"; });
  $("#askButton").disabled = !ready;
  $("#askButton").textContent = mode === "both" ? "Ask both" : `Ask ${NAMES[mode]}`;
  $("#askHint").textContent = ready ? "" : "Build it first in step 2.";
  if (reload) loadAnswers();
}

function addQuestion(question = "", expected = "") {
  const row = document.createElement("div");
  row.className = "q";
  row.innerHTML = `
    <span class="n"></span>
    <input class="question" placeholder="What do you want to know from your files?" aria-label="Question">
    <input class="expected" placeholder="expected: key, terms  (optional)" aria-label="Expected answer, optional">
    <button class="icon" type="button" aria-label="Remove question">×</button>`;
  row.querySelector(".question").value = question;
  row.querySelector(".expected").value = expected;
  row.querySelector(".expected").hidden = state.mode !== "both";
  row.querySelector("button").addEventListener("click", () => {
    row.remove();
    if (!$("#questions").children.length) addQuestion();
    renumber();
  });
  $("#questions").append(row);
  renumber();
  return row;
}

function renumber() {
  $$("#questions .q").forEach((row, i) => { row.querySelector(".n").textContent = i + 1; });
}

function pasteQuestions() {
  const text = prompt("One question per line. Add | and the expected answer if you have one:\n\nWhat produces ATP? | ATP, mitochondria");
  if (!text) return;
  const rows = $$("#questions .q");
  if (rows.length === 1 && !rows[0].querySelector(".question").value) rows[0].remove();
  for (const line of text.split("\n").map((l) => l.trim()).filter(Boolean)) {
    const [question, expected = ""] = line.split("|").map((part) => part.trim());
    addQuestion(question, expected);
  }
}

async function ask() {
  if (!state.data.config.model) { openSettings(); return; }
  const questions = $$("#questions .q")
    .map((row) => ({ question: row.querySelector(".question").value.trim(), expected: row.querySelector(".expected").value.trim() }))
    .filter((q) => q.question);
  if (!questions.length) { toast("Write at least one question", true); return; }
  const button = $("#askButton");
  button.disabled = true;
  const log = $("#askLog");
  try {
    if (state.mode === "both") {
      const job = await send("/api/compare", "POST", { questions, k: state.k });
      await follow(job, log, (j) => {
        const last = j.events.at(-1);
        if (j.error) return `<div class="bad">✗ ${escape(j.error)}</div>`;
        if (j.status === "running") return `<div class="now">Question ${last?.number ?? 1} of ${questions.length}: ${escape(last?.question ?? "")}</div>`;
        return `<div class="good">✓ ${plural(questions.length, "question")} compared</div>`;
      });
    } else {
      for (const [index, q] of questions.entries()) {
        const job = await send("/api/ask", "POST", { question: q.question, arm: state.mode, k: state.k });
        const done = await follow(job, log, (j) => j.error
          ? `<div class="bad">✗ ${escape(j.error)}</div>`
          : `<div class="${j.status === "running" ? "now" : "good"}">${NAMES[state.mode]} · question ${index + 1} of ${questions.length}</div>`);
        if (done.status !== "done") break;
      }
    }
    $("#questions").innerHTML = "";
    addQuestion();
  } catch (error) {
    toast(error.message, true);
  }
  button.disabled = false;
  await refresh();
  await loadAnswers();
}

function armHTML(arm, name, item = null) {
  const how = name === "wiki"
    ? "reads pages written when the files were added"
    : `reads ${arm.detail.k} paragraphs retrieved now · ${escape(arm.detail.retrieval)}`;
  const correct = item?.correct?.[name] ?? null;
  const expected = correct === null ? "" : `<div class="expect ${correct ? "hit" : "miss"}">${correct ? "✓ matches" : "✗ does not match"} the expected answer: ${escape(item.expected)}</div>`;
  const saw = name === "wiki"
    ? `Pages read: ${arm.detail.pages_read.map((p) => `<code>${escape(p)}</code>`).join(", ") || "none"} · ${arm.detail.steps} steps`
    : `Retrieved: ${arm.detail.retrieved.map((c) => `<code>${escape(c)}</code>`).join(" ") || "nothing"}`;
  return `
    <div class="arm ${name}">
      <div class="arm-head">
        <span class="tag">${NAMES[name]}</span>
        <span class="badge ${arm.found ? "yes" : "abst"}">${arm.found ? `Answered · ${plural(arm.citations.length, "citation")}` : "Not in your files"}</span>
      </div>
      <div class="how">${how}</div>
      <div class="answer ${arm.found ? "" : "abst"}">${render(arm.text, name)}</div>
      ${expected}
      <details class="saw"><summary>What the model saw</summary>${saw}</details>
      <div class="metrics">
        <div><b>${arm.calls}</b><small>calls</small></div>
        <div><b>${num(arm.input_tokens)}</b><small>tokens in</small></div>
        <div><b>${secs(arm.seconds)}</b><small>time</small></div>
        <div><b>${money(arm.usd)}</b><small>cost</small></div>
      </div>
    </div>`;
}

const when = (time) => escape(time.replace("T", " ").slice(0, 16));

function comparisonHTML(item) {
  const options = [["wiki", "WikiLLM"], ["rag", "Vector search"], ["tie", "Tie"], ["neither", "Neither"]];
  return `
    <article class="cmp" data-id="${item.id}">
      <div class="cmp-head"><h3>${escape(item.question)}</h3><span class="meta">${when(item.time)}${item.shared_citations.length ? ` · ${item.shared_citations.length} shared` : ""}</span></div>
      <div class="cmp-body">${armHTML(item.rag, "rag", item)}${armHTML(item.wiki, "wiki", item)}</div>
      <div class="verdict">
        <span>Which answer serves you better?</span>
        <div class="seg" role="group" aria-label="Verdict">
          ${options.map(([value, text]) => `<button type="button" data-verdict="${value}" aria-pressed="${item.verdict === value}">${text}</button>`).join("")}
        </div>
        <input class="note" placeholder="Why? (optional)" value="${escape(item.note)}" aria-label="Note">
      </div>
    </article>`;
}

function singleHTML(item) {
  return `
    <article class="cmp single">
      <div class="cmp-head"><h3>${escape(item.question)}</h3><span class="meta">${when(item.time)}</span></div>
      <div class="cmp-body">${armHTML(item.result, item.result.arm)}</div>
    </article>`;
}

async function loadAnswers() {
  if (!state.data?.vault) return;
  const list = $("#answers");
  if (state.mode === "both") {
    const items = await api("/api/comparisons");
    list.innerHTML = items.length
      ? items.slice().reverse().map(comparisonHTML).join("")
      : `<p class="empty-state">Comparisons will appear here, newest first.</p>`;
  } else {
    const items = (await api("/api/answers")).filter((a) => a.result.arm === state.mode);
    list.innerHTML = items.length
      ? items.slice().reverse().map(singleHTML).join("")
      : `<p class="empty-state">Answers from ${NAMES[state.mode]} will appear here.</p>`;
  }
}

async function saveVerdict(card, verdict) {
  try {
    await send(`/api/comparisons/${card.dataset.id}/verdict`, "PUT", { verdict, note: card.querySelector(".note").value });
    for (const b of card.querySelectorAll("[data-verdict]")) b.setAttribute("aria-pressed", b.dataset.verdict === verdict);
    toast("Verdict saved");
  } catch (error) {
    toast(error.message, true);
  }
}

// --- citations: source beside claim --------------------------------------------------

async function showCitation(button) {
  $$(".cite.sel").forEach((b) => b.classList.remove("sel"));
  button.classList.add("sel");
  try {
    const p = await api(`/api/citation?c=${encodeURIComponent(button.dataset.cite)}`);
    $("#drawerKicker").textContent = `${NAMES[button.dataset.arm]} cites ¶${p.anchor}`;
    $("#drawerTitle").textContent = p.source_title;
    $("#drawerText").textContent = p.text;
    $("#drawer").classList.add("open");
    $("#drawer").setAttribute("aria-hidden", "false");
    $("#drawerClose").focus();
  } catch (error) {
    toast(error.message, true);
  }
}
function closeDrawer() {
  $("#drawer").classList.remove("open");
  $("#drawer").setAttribute("aria-hidden", "true");
  $$(".cite.sel").forEach((b) => b.classList.remove("sel"));
}

// --- 4 · results ---------------------------------------------------------------------

function statRow(label, value, share) {
  const width = Math.max(0, Math.min(1, share ?? 0)) * 100;
  return `<div class="stat"><span>${label}</span><span class="bar"><i style="width:${width}%"></i></span><b>${value}</b></div>`;
}

async function loadResults() {
  if (!state.data?.vault) return;
  const [{ summary, recommendation }, items] = await Promise.all([api(`/api/summary?k=${state.k}`), api("/api/comparisons")]);
  const advice = $("#advice");
  advice.className = `advice ${recommendation.choice}`;
  const label = { wiki: "Recommendation · WikiLLM", rag: "Recommendation · Vector search", undecided: "Recommendation" }[recommendation.choice];
  advice.innerHTML = `<p class="eyebrow">${label}</p><h2>${escape(recommendation.headline)}</h2><ul>${recommendation.reasons.map((r) => `<li>${escape(r)}</li>`).join("")}</ul>`;

  const q = summary.questions || 1;
  const arms = summary.arms;
  const maxTokens = Math.max(arms.wiki.mean_input_tokens, arms.rag.mean_input_tokens) || 1;
  const maxSeconds = Math.max(arms.wiki.mean_seconds, arms.rag.mean_seconds) || 1;
  const maxUsd = Math.max(arms.wiki.total_usd ?? 0, arms.rag.total_usd ?? 0) || 1;
  $("#arms").innerHTML = ["rag", "wiki"].map((name) => {
    const a = arms[name];
    const rows = [
      statRow("Answered", `${a.answered} / ${a.questions}`, a.answered / q),
      a.checked ? statRow("Matches expected", `${a.correct} / ${a.checked}`, a.correct / a.checked) : "",
      statRow("Preferred by you", `${a.preferred} / ${summary.judged}`, summary.judged ? a.preferred / summary.judged : 0),
      statRow("Tokens in / question", num(a.mean_input_tokens), a.mean_input_tokens / maxTokens),
      statRow("Time / question", secs(a.mean_seconds), a.mean_seconds / maxSeconds),
      statRow("Cost of questions", money(a.total_usd), (a.total_usd ?? 0) / maxUsd),
    ].join("");
    const build = name === "wiki"
      ? `<p class="note">Plus building the wiki once: ${plural(summary.ingestion_calls, "call")}, ${money(summary.ingestion_usd)}.</p>`
      : `<p class="note">No model cost to build.</p>`;
    return `<div class="armcard ${name}"><h3>${NAMES[name]}</h3>${rows}${build}</div>`;
  }).join("");

  const mark = (v) => (v === null ? `<span class="dot" title="no expected answer"></span>` : `<span class="dot ${v ? "yes" : "no"}" title="${v ? "matches" : "does not match"}"></span>`);
  $("#table").innerHTML = items.length
    ? `<thead><tr><th>Question</th><th>Expected</th><th>Vector search</th><th>WikiLLM</th><th>Verdict</th><th class="num">Search cost</th><th class="num">Wiki cost</th></tr></thead><tbody>${
      items.map((i) => `<tr><td>${escape(i.question)}</td><td class="mono">${escape(i.expected) || "—"}</td><td>${mark(i.correct.rag)} ${i.rag.found ? "answered" : "abstained"}</td><td>${mark(i.correct.wiki)} ${i.wiki.found ? "answered" : "abstained"}</td><td>${escape(i.verdict ?? "—")}</td><td class="num">${money(i.rag.usd)}</td><td class="num">${money(i.wiki.usd)}</td></tr>`).join("")
    }</tbody>`
    : `<tbody><tr><td class="empty-state">Compare both in step 3 to see results here.</td></tr></tbody>`;
}

// --- wiring --------------------------------------------------------------------------

function wire() {
  $("#vaultForm").addEventListener("submit", async (event) => {
    event.preventDefault();
    try {
      await send("/api/vault", "POST", { folder: $("#folder").value });
      await refresh();
      selectTab("sources");
    } catch (error) {
      toast(error.message, true);
    }
  });
  $("#vaultChip").addEventListener("click", () => {
    $("#folder").value = state.data.vault?.root ?? state.data.suggested;
    $("#welcome").hidden = false;
    $("#workspace").hidden = true;
  });
  $("#modelChip").addEventListener("click", openSettings);
  $("#settingsForm").addEventListener("submit", saveSettings);
  for (const tab of $$(".steps [role=tab]")) tab.addEventListener("click", () => selectTab(tab.getAttribute("aria-controls")));
  for (const button of $$("[data-goto]")) button.addEventListener("click", () => selectTab(button.dataset.goto));

  const drop = $("#drop"), input = $("#fileInput");
  drop.addEventListener("keydown", (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); input.click(); } });
  input.addEventListener("change", () => { addFiles([...input.files]); input.value = ""; });
  for (const kind of ["dragenter", "dragover"]) drop.addEventListener(kind, (e) => { e.preventDefault(); drop.classList.add("over"); });
  for (const kind of ["dragleave", "drop"]) drop.addEventListener(kind, () => drop.classList.remove("over"));
  drop.addEventListener("drop", (e) => { e.preventDefault(); addFiles([...e.dataTransfer.files]); });

  $("#retrieval").addEventListener("change", (e) => saveConfig({ retrieval: e.target.value, embedding_model: "" }).catch((err) => toast(err.message, true)));
  $("#embeddingModel").addEventListener("change", (e) => saveConfig({ embedding_model: e.target.value.trim() }).catch((err) => toast(err.message, true)));
  $("#buildIndex").addEventListener("click", buildIndex);
  $("#buildWiki").addEventListener("click", buildWiki);

  for (const button of $$(".seg.mode button")) button.addEventListener("click", () => setMode(button.dataset.mode));
  $("#k").addEventListener("input", (e) => { state.k = Number(e.target.value); $("#kOut").textContent = state.k; });
  $("#addQuestion").addEventListener("click", () => addQuestion().querySelector(".question").focus());
  $("#pasteQuestions").addEventListener("click", pasteQuestions);
  $("#askButton").addEventListener("click", ask);

  $("#answers").addEventListener("click", (e) => {
    const cite = e.target.closest(".cite");
    if (cite) { showCitation(cite); return; }
    const verdict = e.target.closest("[data-verdict]");
    if (verdict) saveVerdict(verdict.closest(".cmp"), verdict.dataset.verdict);
  });
  $("#answers").addEventListener("change", (e) => {
    if (!e.target.classList.contains("note")) return;
    const card = e.target.closest(".cmp");
    saveVerdict(card, card.querySelector("[data-verdict][aria-pressed=true]")?.dataset.verdict ?? null);
  });
  $("#drawerClose").addEventListener("click", closeDrawer);
  addEventListener("keydown", (e) => { if (e.key === "Escape") closeDrawer(); });
  addEventListener("hashchange", () => selectTab(location.hash.slice(1)));
}

wire();
addQuestion();
refresh()
  .then(() => selectTab(location.hash.slice(1)))
  .catch((error) => toast(error.message, true));
