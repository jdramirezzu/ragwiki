// The lab's page: a small, dependency-free front for the local API.

import { language, pickLanguage, setLanguage, t } from "./i18n.js";

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
const decimal = (text) => (language() === "es" ? String(text).replace(".", ",") : String(text));
const money = (usd) => (usd === null || usd === undefined ? t("unknown") : usd === 0 ? "$0" : `$${decimal(usd < 0.01 ? usd.toFixed(5) : usd.toFixed(3))}`);
const num = (n) => Number(n ?? 0).toLocaleString(language() === "es" ? "es-CO" : "en-US", { maximumFractionDigits: 0 });
const secs = (s) => `${decimal(Number(s ?? 0).toFixed(1))} s`;
// "files" / "file" style pairs: the singular key is the plural key without its final "s".
const count = (n, key) => t(n === 1 ? key.replace(/s$/, "") : key, { n });
const name = (arm) => t(`names_${arm}`);

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
      ` <button class="cite" type="button" data-cite="${src}#^${p}" data-arm="${arm}">${p}</button>`)
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
  $("#types").textContent = types.map((x) => `.${x}`).join("  ");
  $("#fileInput").accept = types.map((x) => `.${x}`).join(",");

  $("#vaultChip").textContent = vault ? vault.root : t("noFolder");
  $("#vaultChip").classList.toggle("on", Boolean(vault));
  $("#modelChip").textContent = config.model ? config.model : t("noModel");
  $("#modelChip").classList.toggle("on", Boolean(config.model));
  $("#spendChip").hidden = !session.calls;
  $("#spendChip").textContent = `${t(session.calls === 1 ? "calls1" : "callsN", { n: session.calls })} · ${money(session.usd)}`;
  if (!vault) return;

  $("#vaultPath").innerHTML = `${count(vault.sources.length, "files")} · ${count(vault.pages, "pages")}<span class="path" title="${escape(vault.root)}">${escape(vault.root)}</span>`;
  $("#countSources").textContent = vault.sources.length || "";
  $("#sourceList").innerHTML = vault.sources.length
    ? vault.sources.map((s) => `<li><b>${escape(s.title)}</b><span class="marks"><span class="mini wiki ${s.wiki ? "on" : ""}">${t(s.wiki ? "inWiki" : "notInWiki")}</span></span><small>${escape(s.original)} · ${escape(s.id)}</small></li>`).join("")
    : `<li class="empty">${t("nothingYet")}</li>`;
  $("#toBuild").hidden = !vault.sources.length;
  await refreshBuild();
}

async function refreshBuild() {
  if (!state.data?.vault) return;
  state.build = await api("/api/build");
  const { rag, wiki } = state.build;
  const config = state.data.config;

  $("#retrieval").value = config.retrieval;
  const input = $("#embeddingModel");
  input.hidden = config.retrieval === "bm25";
  input.value = config.embedding_model;
  input.placeholder = config.retrieval === "local" ? state.data.local_model : "text-embedding-3-small";
  $("#retrievalNote").textContent = {
    local: state.data.local_embeddings ? t("noteLocal", { model: state.data.local_model }) : t("noteLocalMissing"),
    provider: t("noteProvider"),
    bm25: t("noteBm25"),
  }[config.retrieval];

  $("#ragBar").style.width = `${rag.paragraphs ? (rag.indexed / rag.paragraphs) * 100 : 0}%`;
  $("#ragStatus").innerHTML = rag.error
    ? `<span class="rag-t">${escape(rag.error)}</span>`
    : rag.ready
      ? t("ragReady", { n: num(rag.paragraphs), label: escape(t({ local: "lblLocal", provider: "lblProvider", bm25: "lblBm25" }[config.retrieval], { model: config.embedding_model || state.data.local_model })) })
      : rag.paragraphs
        ? t("ragProgress", { done: num(rag.indexed), total: num(rag.paragraphs) })
        : t("addFirst");
  $("#ragBuildCost").textContent = config.retrieval === "local"
    ? t("ragCostLocal")
    : config.retrieval === "bm25" ? t("ragCostNone") : t("ragCostProvider");
  const indexButton = $("#buildIndex");
  indexButton.hidden = config.retrieval === "bm25";
  indexButton.disabled = !rag.paragraphs || rag.ready;
  indexButton.textContent = t(rag.ready ? "indexBuilt" : rag.indexed ? "updateIndex" : "buildIndex");

  const total = wiki.sources + wiki.pending;
  $("#wikiBar").style.width = `${total ? (wiki.sources / total) * 100 : 0}%`;
  $("#wikiStatus").innerHTML = !total
    ? t("addFirst")
    : wiki.pending
      ? t("wikiProgress", { done: wiki.sources, total, pages: count(wiki.pages, "pages") })
      : t("wikiReady", { pages: count(wiki.pages, "pages"), files: count(total, "files") });
  const estimate = wiki.estimate;
  $("#wikiBuildCost").textContent = estimate
    ? t("wikiEstimate", { calls: estimate.calls, usd: money(estimate.usd), files: count(estimate.files, "newFiles") })
    : wiki.spent_usd !== null ? t("wikiSpent", { usd: money(wiki.spent_usd) }) : t("wikiCostDefault");
  const wikiButton = $("#buildWiki");
  wikiButton.disabled = !wiki.pending;
  wikiButton.textContent = t(!total || wiki.pending ? (wiki.sources ? "updateWiki" : "buildWiki") : "wikiBuilt");

  updateModes();
}

function selectTab(tab) {
  if (!TABS.includes(tab)) tab = "sources";
  try { history.replaceState(null, "", `#${tab}`); } catch { /* file previews */ }
  scrollTo(0, 0);
  for (const el of $$(".steps [role=tab]")) {
    const on = el.getAttribute("aria-controls") === tab;
    el.setAttribute("aria-selected", on);
    $(`#${el.getAttribute("aria-controls")}`).hidden = !on;
  }
  if (tab === "build") refreshBuild();
  if (tab === "ask") loadAnswers();
  if (tab === "results") loadResults();
}

// --- settings ------------------------------------------------------------------------

function openSettings() {
  const form = $("#settingsForm");
  const config = state.data.config;
  for (const [key, value] of Object.entries(config)) {
    if (form.elements[key]) form.elements[key].value = value ?? "";
  }
  form.elements.api_key.value = "";
  $("#keyNote").textContent = t(config.api_key_set ? "keySet" : "keyMemory");
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
    toast(t("saved"));
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
  log.innerHTML = `<div class="now">${t("extracting", { n: files.length })}</div>`;
  try {
    const result = await api("/api/sources", { method: "POST", body: form });
    log.innerHTML = [
      ...result.added.map((a) => a.skipped
        ? `<div>• ${t("alreadyAdded", { title: escape(a.title) })}</div>`
        : `<div class="good">✓ ${escape(a.title)} · ${t("paragraphs", { n: a.paragraphs })}</div>`),
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
      if (j.status === "done") return `<div class="good">✓ ${t("indexed", { n: num(j.result.indexed) })}</div>`;
      if (!last || !last.total) return `<div class="now">${t("loadingModel")}</div>`;
      return `<div class="now">${t("embedding", { done: num(last.done), total: num(last.total) })}</div>`;
    });
    if (done.status === "done") toast(t("indexToast"));
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
        ? [`<div class="now">${t("partOf", { file: escape(last.file), stage: t(`stage_${last.stage}`), part: last.part, parts: last.parts })}</div>`]
        : [];
      for (const r of j.result ?? []) {
        lines.push(r.error
          ? `<div class="bad">✗ ${escape(r.file)}: ${escape(r.error)} ${t("nothingChanged")}</div>`
          : `<div class="good">✓ ${escape(r.file)}: ${t("pagesCreated", { created: r.created.length, updated: r.updated.length })}</div>`);
      }
      if (j.error) lines.push(`<div class="bad">✗ ${escape(j.error)}</div>`);
      return lines.join("") || `<div class="now">${t("starting")}</div>`;
    });
    if (done.status === "done") toast(t("wikiToast"));
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
  $("#modeNote").textContent = t({ both: "modeNoteBoth", rag: "modeNoteRag", wiki: "modeNoteWiki" }[mode]);
  $("#kbox").hidden = mode === "wiki";
  $$(".q .expected").forEach((input) => { input.hidden = mode !== "both"; });
  $("#askButton").disabled = !ready;
  $("#askButton").textContent = mode === "both" ? t("askBoth") : t("askOne", { name: name(mode) });
  $("#askHint").textContent = ready ? "" : t("buildFirst");
  if (reload) loadAnswers();
}

function addQuestion(question = "", expected = "") {
  const row = document.createElement("div");
  row.className = "q";
  row.innerHTML = `
    <span class="n"></span>
    <input class="question" data-i18n-ph="questionPh" placeholder="${escape(t("questionPh"))}">
    <input class="expected" data-i18n-ph="expectedPh" placeholder="${escape(t("expectedPh"))}">
    <button class="icon" type="button" aria-label="×">×</button>`;
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
  const text = prompt(t("pastePrompt"));
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
  if (!questions.length) { toast(t("writeOne"), true); return; }
  const button = $("#askButton");
  button.disabled = true;
  const log = $("#askLog");
  try {
    if (state.mode === "both") {
      const job = await send("/api/compare", "POST", { questions, k: state.k });
      await follow(job, log, (j) => {
        const last = j.events.at(-1);
        if (j.error) return `<div class="bad">✗ ${escape(j.error)}</div>`;
        if (j.status === "running") return `<div class="now">${t("questionOf", { n: last?.number ?? 1, total: questions.length, q: escape(last?.question ?? "") })}</div>`;
        return `<div class="good">✓ ${t("compared", { n: questions.length })}</div>`;
      });
    } else {
      for (const [index, q] of questions.entries()) {
        const job = await send("/api/ask", "POST", { question: q.question, arm: state.mode, k: state.k });
        const done = await follow(job, log, (j) => j.error
          ? `<div class="bad">✗ ${escape(j.error)}</div>`
          : `<div class="${j.status === "running" ? "now" : "good"}">${t("armQuestion", { name: name(state.mode), n: index + 1, total: questions.length })}</div>`);
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

function armHTML(arm, which, item = null) {
  const how = which === "wiki" ? t("howWiki") : t("howRag", { k: arm.detail.k, retrieval: escape(arm.detail.retrieval) });
  const correct = item?.correct?.[which] ?? null;
  const expected = correct === null ? "" : `<div class="expect ${correct ? "hit" : "miss"}">${t(correct ? "matches" : "noMatch")} ${t("theExpected", { e: escape(item.expected) })}</div>`;
  const saw = which === "wiki"
    ? t("pagesRead", { pages: arm.detail.pages_read.map((p) => `<code>${escape(p)}</code>`).join(", ") || t("none"), steps: arm.detail.steps })
    : t("retrieved", { list: arm.detail.retrieved.map((c) => `<code>${escape(c)}</code>`).join(" ") || t("nothing") });
  const badge = arm.found
    ? (arm.citations.length === 1 ? t("answered1") : t("answered", { n: arm.citations.length }))
    : t("notInFiles");
  return `
    <div class="arm ${which}">
      <div class="arm-head">
        <span class="tag">${name(which)}</span>
        <span class="badge ${arm.found ? "yes" : "abst"}">${badge}</span>
      </div>
      <div class="how">${how}</div>
      <div class="answer ${arm.found ? "" : "abst"}">${render(arm.text, which)}</div>
      ${expected}
      <details class="saw"><summary>${t("sawTitle")}</summary>${saw}</details>
      <div class="metrics">
        <div><b>${arm.calls}</b><small>${t("calls")}</small></div>
        <div><b>${num(arm.input_tokens)}</b><small>${t("tokensIn")}</small></div>
        <div><b>${secs(arm.seconds)}</b><small>${t("time")}</small></div>
        <div><b>${money(arm.usd)}</b><small>${t("cost")}</small></div>
      </div>
    </div>`;
}

const when = (time) => escape(time.replace("T", " ").slice(0, 16));

function comparisonHTML(item) {
  const options = [["wiki", name("wiki")], ["rag", name("rag")], ["tie", t("tie")], ["neither", t("neither")]];
  return `
    <article class="cmp" data-id="${item.id}">
      <div class="cmp-head"><h3>${escape(item.question)}</h3><span class="meta">${when(item.time)}${item.shared_citations.length ? ` · ${t("shared", { n: item.shared_citations.length })}` : ""}</span></div>
      <div class="cmp-body">${armHTML(item.rag, "rag", item)}${armHTML(item.wiki, "wiki", item)}</div>
      <div class="verdict">
        <span>${t("which")}</span>
        <div class="seg" role="group">
          ${options.map(([value, text]) => `<button type="button" data-verdict="${value}" aria-pressed="${item.verdict === value}">${text}</button>`).join("")}
        </div>
        <input class="note" placeholder="${escape(t("why"))}" value="${escape(item.note)}">
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
      : `<p class="empty-state">${t("emptyBoth")}</p>`;
  } else {
    const items = (await api("/api/answers")).filter((a) => a.result.arm === state.mode);
    list.innerHTML = items.length
      ? items.slice().reverse().map(singleHTML).join("")
      : `<p class="empty-state">${t("emptyOne", { name: name(state.mode) })}</p>`;
  }
}

async function saveVerdict(card, verdict) {
  try {
    await send(`/api/comparisons/${card.dataset.id}/verdict`, "PUT", { verdict, note: card.querySelector(".note").value });
    for (const b of card.querySelectorAll("[data-verdict]")) b.setAttribute("aria-pressed", b.dataset.verdict === verdict);
    toast(t("verdictSaved"));
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
    $("#drawerKicker").textContent = t("cites", { name: name(button.dataset.arm), p: p.anchor });
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
  const [{ summary, recommendation }, items] = await Promise.all([
    api(`/api/summary?k=${state.k}&lang=${language()}`),
    api("/api/comparisons"),
  ]);
  const advice = $("#advice");
  advice.className = `advice ${recommendation.choice}`;
  const label = recommendation.choice === "undecided" ? t("recommendation") : t("recFor", { name: name(recommendation.choice) });
  advice.innerHTML = `<p class="eyebrow">${label}</p><h2>${escape(recommendation.headline)}</h2><ul>${recommendation.reasons.map((r) => `<li>${escape(r)}</li>`).join("")}</ul>`;

  const q = summary.questions || 1;
  const arms = summary.arms;
  const maxTokens = Math.max(arms.wiki.mean_input_tokens, arms.rag.mean_input_tokens) || 1;
  const maxSeconds = Math.max(arms.wiki.mean_seconds, arms.rag.mean_seconds) || 1;
  const maxUsd = Math.max(arms.wiki.total_usd ?? 0, arms.rag.total_usd ?? 0) || 1;
  $("#arms").innerHTML = ["rag", "wiki"].map((which) => {
    const a = arms[which];
    const rows = [
      statRow(t("rAnswered"), `${a.answered} / ${a.questions}`, a.answered / q),
      a.checked ? statRow(t("rMatches"), `${a.correct} / ${a.checked}`, a.correct / a.checked) : "",
      statRow(t("rPreferred"), `${a.preferred} / ${summary.judged}`, summary.judged ? a.preferred / summary.judged : 0),
      statRow(t("rTokens"), num(a.mean_input_tokens), a.mean_input_tokens / maxTokens),
      statRow(t("rTime"), secs(a.mean_seconds), a.mean_seconds / maxSeconds),
      statRow(t("rCost"), money(a.total_usd), (a.total_usd ?? 0) / maxUsd),
    ].join("");
    const build = which === "wiki"
      ? `<p class="note">${t("plusBuild", { calls: t(summary.ingestion_calls === 1 ? "calls1" : "callsN", { n: summary.ingestion_calls }), usd: money(summary.ingestion_usd) })}</p>`
      : `<p class="note">${t("noBuild")}</p>`;
    return `<div class="armcard ${which}"><h3>${name(which)}</h3>${rows}${build}</div>`;
  }).join("");

  const mark = (v) => (v === null ? `<span class="dot"></span>` : `<span class="dot ${v ? "yes" : "no"}"></span>`);
  const verdictName = (v) => ({ wiki: name("wiki"), rag: name("rag"), tie: t("tie"), neither: t("neither") })[v] ?? "—";
  $("#table").innerHTML = items.length
    ? `<thead><tr><th>${t("thQuestion")}</th><th>${t("thExpected")}</th><th>${name("rag")}</th><th>WikiLLM</th><th>${t("thVerdict")}</th><th class="num">${t("thSearchCost")}</th><th class="num">${t("thWikiCost")}</th></tr></thead><tbody>${
      items.map((i) => `<tr><td>${escape(i.question)}</td><td class="mono">${escape(i.expected) || "—"}</td><td>${mark(i.correct.rag)} ${t(i.rag.found ? "answeredShort" : "abstained")}</td><td>${mark(i.correct.wiki)} ${t(i.wiki.found ? "answeredShort" : "abstained")}</td><td>${verdictName(i.verdict)}</td><td class="num">${money(i.rag.usd)}</td><td class="num">${money(i.wiki.usd)}</td></tr>`).join("")
    }</tbody>`
    : `<tbody><tr><td class="empty-state">${t("noResults")}</td></tr></tbody>`;
}

// --- language ------------------------------------------------------------------------

function applyLanguage(lang) {
  setLanguage(lang);
  for (const b of $$(".seg.lang button")) b.setAttribute("aria-pressed", b.dataset.lang === language());
  $("#kLabel").innerHTML = t("kLabel", { k: state.k });
  for (const el of $$(".dec")) el.innerHTML = decimal(el.innerHTML);
  if (language() === "en") for (const el of $$(".dec")) el.innerHTML = el.innerHTML.replace(",", ".");
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
  for (const button of $$(".seg.lang button")) {
    button.addEventListener("click", async () => {
      applyLanguage(button.dataset.lang);
      await refresh();
      selectTab(location.hash.slice(1));
    });
  }

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

applyLanguage(pickLanguage());
wire();
addQuestion();
refresh()
  .then(() => selectTab(location.hash.slice(1)))
  .catch((error) => toast(error.message, true));
