// wikinotes lab: a small, dependency-free front for the local API.

const $ = (selector, root = document) => root.querySelector(selector);
const state = { data: null, pending: [], k: 8, comparisons: [] };

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
  api(path, { method, headers: { "Content-Type": "application/json" }, body: JSON.stringify(data) });

function escape(text) {
  return String(text ?? "").replace(/[&<>"']/g, (c) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  })[c]);
}

const money = (usd) => (usd === null || usd === undefined ? "unknown" : usd === 0 ? "$0" : `$${usd < 0.01 ? usd.toFixed(5) : usd.toFixed(3)}`);
const num = (n) => Number(n ?? 0).toLocaleString("en-US", { maximumFractionDigits: 0 });
const plural = (n, word) => `${n} ${word}${n === 1 ? "" : "s"}`;
const secs = (s) => `${Number(s ?? 0).toFixed(1)} s`;

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
  const blocks = String(markdown ?? "").trim().split(/\n{2,}/);
  return blocks.map((block) => {
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

// --- state and chrome ----------------------------------------------------------------

async function refresh() {
  state.data = await api("/api/state");
  const { vault, config, session, types } = state.data;
  $("#welcome").hidden = Boolean(vault);
  $("#workspace").hidden = !vault;
  $("#folder").value ||= state.data.suggested;
  $("#types").textContent = types.map((t) => `.${t}`).join("  ");
  $("#fileInput").accept = types.map((t) => `.${t}`).join(",");

  const vaultChip = $("#vaultChip");
  vaultChip.textContent = vault ? vault.root : "No vault";
  vaultChip.classList.toggle("on", Boolean(vault));
  const modelChip = $("#modelChip");
  modelChip.textContent = config.model ? config.model : "No model · set up";
  modelChip.classList.toggle("on", Boolean(config.model));
  const spend = $("#spendChip");
  spend.hidden = !session.calls;
  spend.textContent = `${session.calls} calls · ${money(session.usd)}`;

  if (!vault) return;
  $("#vaultPath").innerHTML = `${plural(vault.sources.length, "file")} · ${plural(vault.pages, "wiki page")}<span class="path" title="${escape(vault.root)}">${escape(vault.root)}</span>`;
  $("#countSources").textContent = vault.sources.length || "";
  $("#sourceList").innerHTML = vault.sources.length
    ? vault.sources.map((s) => `<li><b>${escape(s.title)}</b><span class="hint">${escape(s.added)}</span><small>${escape(s.original)} · ${escape(s.id)}</small></li>`).join("")
    : `<li class="empty">Nothing yet. Your files will appear here once the wiki is built.</li>`;
  $("#askBoth").disabled = !vault.sources.length;
  $("#askHint").textContent = vault.sources.length
    ? "The wiki navigates its pages (up to 8 calls); RAG answers in 1 call."
    : "Add files in step 1 first.";
}

const TABS = ["sources", "compare", "results"];

function selectTab(name) {
  if (!TABS.includes(name)) name = "sources";
  try { history.replaceState(null, "", `#${name}`); } catch { /* file previews */ }
  for (const tab of document.querySelectorAll(".steps [role=tab]")) {
    const on = tab.getAttribute("aria-controls") === name;
    tab.setAttribute("aria-selected", on);
    $(`#${tab.getAttribute("aria-controls")}`).hidden = !on;
  }
  if (name === "results") loadResults();
  if (name === "compare") loadComparisons();
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

async function saveSettings(event) {
  if (event.submitter?.value !== "save") return;
  const form = new FormData($("#settingsForm"));
  const data = Object.fromEntries(form.entries());
  for (const key of ["price_input", "price_output", "max_usd"]) data[key] = Number(data[key] || 0);
  data.context_tokens = Number(data.context_tokens || 32000);
  if (!data.api_key) data.api_key = null;
  try {
    await send("/api/config", "PUT", data);
    await refresh();
    toast("Model settings saved");
  } catch (error) {
    toast(error.message, true);
  }
}

// --- jobs ----------------------------------------------------------------------------

async function follow(job, log, describe) {
  log.hidden = false;
  while (true) {
    const current = await api(`/api/jobs/${job.id}`);
    log.innerHTML = describe(current);
    if (current.status !== "running") return current;
    await new Promise((resolve) => setTimeout(resolve, 900));
  }
}

// --- 1 · sources ---------------------------------------------------------------------

async function upload(files) {
  if (!files.length) return;
  const form = new FormData();
  for (const file of files) form.append("files", file);
  try {
    const result = await api("/api/uploads", { method: "POST", body: form });
    state.pending = result.files;
    showEstimate(result);
  } catch (error) {
    toast(error.message, true);
  }
}

function showEstimate({ files, estimate }) {
  const box = $("#estimate");
  box.hidden = false;
  $("#ingestLog").hidden = true;
  if (!estimate.files) {
    box.innerHTML = `<p class="big">These files are already in the vault.</p><p class="hint">Go to step 2 and ask your questions.</p>`;
    return;
  }
  const embeddings = state.data.config.embedding_model;
  box.innerHTML = `
    <div class="files">${files.map((f) => `<span>${escape(f)}</span>`).join("")}</div>
    <p class="big">Building the wiki takes about ${estimate.calls} model calls and costs about ${money(estimate.usd)}.</p>
    <p class="hint">A one-time cost. RAG reads the same extracted paragraphs ${embeddings ? "with embeddings" : "with no model call"}.</p>
    <div class="figures">
      <div class="figure"><b>${estimate.files}</b><small>new files</small></div>
      <div class="figure"><b>${num(estimate.input_tokens)}</b><small>tokens in (estimate)</small></div>
      <div class="figure"><b>${num(estimate.output_tokens)}</b><small>tokens out (estimate)</small></div>
    </div>
    <div class="row">
      <span class="hint">Nothing is written unless a file is ingested completely.</span>
      <button class="btn primary" id="build" type="button">Build the wiki</button>
    </div>`;
  $("#build").addEventListener("click", build);
}

async function build() {
  if (!state.data.config.model) { openSettings(); return; }
  $("#build").disabled = true;
  try {
    const job = await send("/api/ingest", "POST", { files: state.pending });
    const done = await follow(job, $("#ingestLog"), (j) => {
      const last = j.events.at(-1);
      const lines = j.status === "running" && last
        ? [`<div class="now">${escape(last.file)} · ${last.stage} · part ${last.part} of ${last.parts}</div>`]
        : [];
      for (const r of j.result ?? []) {
        lines.push(r.error
          ? `<div class="bad">✗ ${escape(r.file)}: ${escape(r.error)} Nothing changed.</div>`
          : r.skipped
            ? `<div>• ${escape(r.file)} was already in the vault</div>`
            : `<div class="good">✓ ${escape(r.file)}: ${r.created.length} pages created, ${r.updated.length} updated</div>`);
      }
      if (j.error) lines.push(`<div class="bad">✗ ${escape(j.error)}</div>`);
      return lines.join("") || `<div class="now">Starting</div>`;
    });
    $("#estimate").hidden = true;
    if (done.status === "done") toast("Wiki built. Ask your questions in step 2.");
  } catch (error) {
    toast(error.message, true);
    $("#build").disabled = false;
  }
  await refresh();
}

// --- 2 · compare ---------------------------------------------------------------------

function addQuestion(question = "", expected = "") {
  const list = $("#questions");
  const row = document.createElement("div");
  row.className = "q";
  row.innerHTML = `
    <span class="n"></span>
    <input class="question" placeholder="What do you want to know from your files?" aria-label="Question">
    <input class="expected" placeholder="expected: key, terms  (optional)" aria-label="Expected answer, optional">
    <button class="icon" type="button" aria-label="Remove question">×</button>`;
  row.querySelector(".question").value = question;
  row.querySelector(".expected").value = expected;
  row.querySelector("button").addEventListener("click", () => {
    row.remove();
    if (!list.children.length) addQuestion();
    renumber();
  });
  list.append(row);
  renumber();
  return row;
}

function renumber() {
  [...$("#questions").children].forEach((row, i) => { row.querySelector(".n").textContent = i + 1; });
}

function pasteQuestions() {
  const text = prompt("One question per line. Add | and the expected answer if you have one:\n\nWhat produces ATP? | ATP, mitochondria");
  if (!text) return;
  const rows = [...$("#questions").children];
  if (rows.length === 1 && !rows[0].querySelector(".question").value) rows[0].remove();
  for (const line of text.split("\n").map((l) => l.trim()).filter(Boolean)) {
    const [question, expected = ""] = line.split("|").map((part) => part.trim());
    addQuestion(question, expected);
  }
}

async function askBoth() {
  if (!state.data.config.model) { openSettings(); return; }
  const questions = [...$("#questions").children]
    .map((row) => ({
      question: row.querySelector(".question").value.trim(),
      expected: row.querySelector(".expected").value.trim(),
    }))
    .filter((q) => q.question);
  if (!questions.length) { toast("Write at least one question", true); return; }
  const button = $("#askBoth");
  button.disabled = true;
  try {
    const job = await send("/api/compare", "POST", { questions, k: state.k });
    const done = await follow(job, $("#askLog"), (j) => {
      const last = j.events.at(-1);
      if (j.status === "running") {
        return `<div class="now">Question ${last?.number ?? 1} of ${questions.length}: ${escape(last?.question ?? "")}</div>`;
      }
      if (j.error) return `<div class="bad">✗ ${escape(j.error)}</div>`;
      return `<div class="good">✓ ${plural(questions.length, "question")} compared</div>`;
    });
    if (done.status === "done") {
      $("#questions").innerHTML = "";
      addQuestion();
    }
  } catch (error) {
    toast(error.message, true);
  }
  button.disabled = false;
  await Promise.all([refresh(), loadComparisons()]);
}

function armHTML(item, name) {
  const arm = item[name];
  const label = name === "wiki" ? "Wiki" : "RAG";
  const how = name === "wiki"
    ? "reads pages written when the files were added"
    : `reads ${arm.detail.k} paragraphs retrieved now · ${escape(arm.detail.retrieval)}`;
  const correct = item.correct[name];
  const expected = correct === null ? "" : `<div class="expect ${correct ? "hit" : "miss"}">${correct ? "✓ matches" : "✗ does not match"} the expected answer: ${escape(item.expected)}</div>`;
  const saw = name === "wiki"
    ? `Pages read: ${arm.detail.pages_read.map((p) => `<code>${escape(p)}</code>`).join(", ") || "none"} · ${arm.detail.steps} steps`
    : `Retrieved: ${arm.detail.retrieved.map((c) => `<code>${escape(c)}</code>`).join(" ") || "nothing"}`;
  return `
    <div class="arm ${name}">
      <div class="arm-head">
        <span class="tag">${label}</span>
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

function comparisonHTML(item) {
  const options = [["wiki", "Wiki"], ["rag", "RAG"], ["tie", "Tie"], ["neither", "Neither"]];
  return `
    <article class="cmp" data-id="${item.id}">
      <div class="cmp-head">
        <h3>${escape(item.question)}</h3>
        <span class="meta">${escape(item.time.replace("T", " ").slice(0, 16))}${item.shared_citations.length ? ` · ${item.shared_citations.length} shared` : ""}</span>
      </div>
      <div class="cmp-body">${armHTML(item, "wiki")}${armHTML(item, "rag")}</div>
      <div class="verdict">
        <span>Which answer serves you better?</span>
        <div class="seg" role="group" aria-label="Verdict">
          ${options.map(([value, text]) => `<button type="button" data-verdict="${value}" aria-pressed="${item.verdict === value}">${text}</button>`).join("")}
        </div>
        <input class="note" placeholder="Why? (optional)" value="${escape(item.note)}" aria-label="Note">
      </div>
    </article>`;
}

async function loadComparisons() {
  if (!state.data?.vault) return;
  state.comparisons = await api("/api/comparisons");
  $("#countCompare").textContent = state.comparisons.length || "";
  const list = $("#comparisons");
  list.innerHTML = state.comparisons.length
    ? state.comparisons.slice().reverse().map(comparisonHTML).join("")
    : `<p class="empty-state">Your comparisons will appear here, newest first.</p>`;
}

async function saveVerdict(card, verdict) {
  const note = card.querySelector(".note").value;
  try {
    await send(`/api/comparisons/${card.dataset.id}/verdict`, "PUT", { verdict, note });
    for (const b of card.querySelectorAll("[data-verdict]")) b.setAttribute("aria-pressed", b.dataset.verdict === verdict);
    toast("Verdict saved");
  } catch (error) {
    toast(error.message, true);
  }
}

// --- citations: source beside claim --------------------------------------------------

async function showCitation(button) {
  document.querySelectorAll(".cite.sel").forEach((b) => b.classList.remove("sel"));
  button.classList.add("sel");
  try {
    const p = await api(`/api/citation?c=${encodeURIComponent(button.dataset.cite)}`);
    $("#drawerKicker").textContent = `${button.dataset.arm === "wiki" ? "Wiki" : "RAG"} cites ¶${p.anchor}`;
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
  document.querySelectorAll(".cite.sel").forEach((b) => b.classList.remove("sel"));
}

// --- 3 · results ---------------------------------------------------------------------

function statRow(label, value, share) {
  const width = Math.max(0, Math.min(1, share ?? 0)) * 100;
  return `<div class="stat"><span>${label}</span><span class="bar"><i style="width:${width}%"></i></span><b>${value}</b></div>`;
}

async function loadResults() {
  if (!state.data?.vault) return;
  const [{ summary, recommendation }, items] = await Promise.all([
    api(`/api/summary?k=${state.k}`),
    api("/api/comparisons"),
  ]);
  const advice = $("#advice");
  advice.className = `advice ${recommendation.choice}`;
  const label = { wiki: "Recommendation · Wiki", rag: "Recommendation · RAG", undecided: "Recommendation" }[recommendation.choice];
  advice.innerHTML = `<p class="eyebrow">${label}</p><h2>${escape(recommendation.headline)}</h2><ul>${recommendation.reasons.map((r) => `<li>${escape(r)}</li>`).join("")}</ul>`;

  const q = summary.questions || 1;
  const maxTokens = Math.max(summary.arms.wiki.mean_input_tokens, summary.arms.rag.mean_input_tokens) || 1;
  const maxSeconds = Math.max(summary.arms.wiki.mean_seconds, summary.arms.rag.mean_seconds) || 1;
  const maxUsd = Math.max(summary.arms.wiki.total_usd ?? 0, summary.arms.rag.total_usd ?? 0) || 1;
  $("#arms").innerHTML = ["wiki", "rag"].map((name) => {
    const a = summary.arms[name];
    const rows = [
      statRow("Answered", `${a.answered} / ${a.questions}`, a.answered / q),
      a.checked ? statRow("Matches expected", `${a.correct} / ${a.checked}`, a.correct / a.checked) : "",
      statRow("Preferred by you", `${a.preferred} / ${summary.judged}`, summary.judged ? a.preferred / summary.judged : 0),
      statRow("Tokens in / question", num(a.mean_input_tokens), a.mean_input_tokens / maxTokens),
      statRow("Time / question", secs(a.mean_seconds), a.mean_seconds / maxSeconds),
      statRow("Cost of questions", money(a.total_usd), (a.total_usd ?? 0) / maxUsd),
    ].join("");
    const build = name === "wiki"
      ? `<p class="note">Plus building the wiki once: ${summary.ingestion_calls} calls, ${money(summary.ingestion_usd)}.</p>`
      : `<p class="note">No building cost.</p>`;
    return `<div class="armcard ${name}"><h3>${name === "wiki" ? "Wiki" : "RAG"}</h3>${rows}${build}</div>`;
  }).join("");

  const mark = (v) => (v === null ? `<span class="dot" title="no expected answer"></span>` : `<span class="dot ${v ? "yes" : "no"}" title="${v ? "matches" : "does not match"}"></span>`);
  $("#table").innerHTML = items.length
    ? `<thead><tr><th>Question</th><th>Expected</th><th>Wiki</th><th>RAG</th><th>Verdict</th><th class="num">Wiki cost</th><th class="num">RAG cost</th></tr></thead><tbody>${
      items.map((i) => `<tr><td>${escape(i.question)}</td><td class="mono">${escape(i.expected) || "—"}</td><td>${mark(i.correct.wiki)} ${i.wiki.found ? "answered" : "abstained"}</td><td>${mark(i.correct.rag)} ${i.rag.found ? "answered" : "abstained"}</td><td>${escape(i.verdict ?? "—")}</td><td class="num">${money(i.wiki.usd)}</td><td class="num">${money(i.rag.usd)}</td></tr>`).join("")
    }</tbody>`
    : `<tbody><tr><td class="empty-state">No questions yet.</td></tr></tbody>`;
}

// --- wiring --------------------------------------------------------------------------

function wire() {
  $("#vaultForm").addEventListener("submit", async (event) => {
    event.preventDefault();
    try {
      await send("/api/vault", "POST", { folder: $("#folder").value });
      await refresh();
      await loadComparisons();
      if (!state.data.config.model) openSettings();
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

  for (const tab of document.querySelectorAll(".steps [role=tab]")) {
    tab.addEventListener("click", () => selectTab(tab.getAttribute("aria-controls")));
  }

  const drop = $("#drop"), input = $("#fileInput");
  drop.addEventListener("keydown", (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); input.click(); } });
  input.addEventListener("change", () => { upload([...input.files]); input.value = ""; });
  for (const kind of ["dragenter", "dragover"]) {
    drop.addEventListener(kind, (e) => { e.preventDefault(); drop.classList.add("over"); });
  }
  for (const kind of ["dragleave", "drop"]) {
    drop.addEventListener(kind, () => drop.classList.remove("over"));
  }
  drop.addEventListener("drop", (e) => { e.preventDefault(); upload([...e.dataTransfer.files]); });

  $("#k").addEventListener("input", (e) => { state.k = Number(e.target.value); $("#kOut").textContent = state.k; });
  $("#addQuestion").addEventListener("click", () => addQuestion().querySelector(".question").focus());
  $("#pasteQuestions").addEventListener("click", pasteQuestions);
  $("#askBoth").addEventListener("click", askBoth);

  $("#comparisons").addEventListener("click", (e) => {
    const cite = e.target.closest(".cite");
    if (cite) { showCitation(cite); return; }
    const verdict = e.target.closest("[data-verdict]");
    if (verdict) saveVerdict(verdict.closest(".cmp"), verdict.dataset.verdict);
  });
  $("#comparisons").addEventListener("change", (e) => {
    if (!e.target.classList.contains("note")) return;
    const card = e.target.closest(".cmp");
    const pressed = card.querySelector("[data-verdict][aria-pressed=true]");
    saveVerdict(card, pressed?.dataset.verdict ?? null);
  });
  $("#drawerClose").addEventListener("click", closeDrawer);
  addEventListener("keydown", (e) => { if (e.key === "Escape") closeDrawer(); });
}

wire();
addQuestion();
refresh()
  .then(() => selectTab(location.hash.slice(1)))
  .catch((error) => toast(error.message, true));
