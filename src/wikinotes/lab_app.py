"""wikinotes lab: compare a wiki and a retrieval baseline on your own files.

Started by `wikinotes lab [FOLDER]`. Same model, same files, same questions; the only
difference is the architecture. Run with `streamlit run` only through that command.
"""

import os
import sys
from pathlib import Path

import streamlit as st

from wikinotes.ask import cited_paragraph
from wikinotes.compare import (
    VERDICTS,
    Ingestion,
    Tally,
    compare,
    load_comparisons,
    load_ingestions,
    recommend,
    record_ingestion,
    save_comparison,
    set_verdict,
    summarize,
)
from wikinotes.estimate import estimate_ingest
from wikinotes.extract import UnreadableSource, UnsupportedFormat
from wikinotes.ingest import IngestError, Progress, ingest
from wikinotes.lab import LAB_TYPES, money, readable, rows, save_upload, to_csv
from wikinotes.models import (
    DEFAULT_CONTEXT_TOKENS,
    BudgetExceeded,
    ConfigError,
    MeteredModel,
    ModelError,
    OpenAICompatibleModel,
)
from wikinotes.rag import DEFAULT_K, OpenAICompatibleEmbedder
from wikinotes.vault import STATE_DIR, Vault, VaultError

ERRORS = (
    BudgetExceeded,
    ConfigError,
    IngestError,
    ModelError,
    UnreadableSource,
    UnsupportedFormat,
    VaultError,
)
ARM_TITLES = {
    "wiki": ("Wiki", "pages the model wrote when the files were added"),
    "rag": ("RAG", "source paragraphs retrieved for this question"),
}

st.set_page_config(page_title="wikinotes lab", layout="wide")


def _default_folder() -> str:
    if len(sys.argv) > 1:
        return sys.argv[1]
    return os.environ.get("WIKINOTES_VAULT") or str(Path.home() / "wikinotes-lab")


def _number(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name) or default)
    except ValueError:
        return default


# --- sidebar: where and with which model -------------------------------------------

with st.sidebar:
    st.header("Setup")
    folder = st.text_input("Vault folder", value=_default_folder())
    st.caption("A folder of plain Markdown. Open it in Obsidian or any editor at any time.")

    st.subheader("Model")
    st.caption("Both arms use this same model. Any OpenAI-compatible endpoint works.")
    model_name = st.text_input("Model", value=os.environ.get("WIKINOTES_MODEL", ""))
    base_url = st.text_input("Base URL", value=os.environ.get("WIKINOTES_BASE_URL", ""))
    api_key = st.text_input(
        "API key",
        value=os.environ.get("WIKINOTES_API_KEY", ""),
        type="password",
        help="Not needed for a local model. It is only kept in memory.",
    )
    price_in = st.number_input(
        "Input price (USD per million tokens)",
        min_value=0.0,
        value=_number("WIKINOTES_PRICE_INPUT", 0.0),
    )
    price_out = st.number_input(
        "Output price (USD per million tokens)",
        min_value=0.0,
        value=_number("WIKINOTES_PRICE_OUTPUT", 0.0),
    )
    max_usd = st.number_input(
        "Spending cap for this session (USD, 0 = none)",
        min_value=0.0,
        value=_number("WIKINOTES_MAX_USD", 1.0),
    )
    context_tokens = int(
        st.number_input(
            "Context window (tokens)",
            min_value=1000,
            value=int(_number("WIKINOTES_CONTEXT_TOKENS", DEFAULT_CONTEXT_TOKENS)),
            step=1000,
        )
    )
    embedding_name = st.text_input(
        "Embedding model for RAG (optional)",
        value=os.environ.get("WIKINOTES_EMBEDDING_MODEL", ""),
        help="Empty: lexical retrieval (BM25), offline and free.",
    )

try:
    root = Path(folder).expanduser()
    vault = Vault.find(root) if (root / STATE_DIR).exists() else None
except VaultError:
    vault = None

if vault is None:
    st.title("wikinotes lab")
    st.write(f"There is no vault in `{folder}` yet.")
    if st.button("Create the vault here", type="primary"):
        try:
            Vault.create(Path(folder).expanduser())
            st.rerun()
        except (VaultError, OSError) as error:
            st.error(str(error))
    st.stop()


def _model() -> MeteredModel | None:
    if not model_name:
        return None
    key = (model_name, base_url, api_key, price_in, price_out, max_usd, str(vault.root))
    if st.session_state.get("model_key") != key:
        inner = OpenAICompatibleModel(model_name, base_url or None, api_key or None)
        st.session_state.model = MeteredModel(
            inner,
            vault.root / STATE_DIR / "calls.jsonl",
            price_input=price_in,
            price_output=price_out,
            max_usd=max_usd or None,
        )
        st.session_state.model_key = key
    return st.session_state.model


model = _model()
embedder = (
    OpenAICompatibleEmbedder(embedding_name, base_url or None, api_key or None)
    if embedding_name
    else None
)
priced = price_in > 0 or price_out > 0

st.title("wikinotes lab")
st.write(
    "Should your documents become a **wiki** the model writes once, or should the model "
    "**retrieve** paragraphs for every question (RAG)? Add your files, ask the questions "
    "you care about, and compare answers, citations, cost and time side by side."
)
if model is None:
    st.warning("No model configured. Fill in **Model** in the sidebar to add files or ask.")
elif model.calls:
    st.caption(f"This session: {model.calls} model calls, {money(model.spent_usd)} spent.")

sources_tab, compare_tab, results_tab = st.tabs(["1 · Sources", "2 · Compare", "3 · Results"])

# --- 1. sources ----------------------------------------------------------------------

with sources_tab:
    st.subheader("Source files")
    st.caption(
        "PDF (with a text layer), Word (.docx), PowerPoint (.pptx) and plain text "
        "(.txt, .md). Both arms read the same paragraphs extracted from these files."
    )
    uploads = st.file_uploader("Choose files", type=list(LAB_TYPES), accept_multiple_files=True)
    paths = []
    for upload in uploads or []:
        try:
            paths.append(save_upload(vault, upload.name, upload.getvalue()))
        except ValueError as error:
            st.error(str(error))

    if paths:
        try:
            estimate = estimate_ingest(
                vault,
                paths,
                context_tokens=context_tokens,
                price_input=price_in,
                price_output=price_out,
            )
        except ERRORS as error:
            st.error(str(error))
            estimate = None
        if estimate is not None and estimate.files == 0:
            st.info("These files are already in the vault.")
        elif estimate is not None:
            st.markdown("**Before spending anything**")
            cols = st.columns(4)
            cols[0].metric("New files", estimate.files)
            cols[1].metric("Model calls", estimate.calls)
            cols[2].metric(
                "Tokens (in / out)", f"{estimate.input_tokens:,} / {estimate.output_tokens:,}"
            )
            cols[3].metric("Estimated cost", money(estimate.usd))
            st.caption(
                "This one-time cost builds the wiki. The RAG arm only indexes the extracted "
                "paragraphs" + (" with embeddings." if embedder else ", with no model call.")
            )
            if st.button("Build the wiki", type="primary", disabled=model is None):
                for path in paths:
                    tally = Tally(model)
                    spent = model.spent_usd
                    with st.status(f"Adding {path.name}", expanded=True) as status:

                        def show(progress: Progress, status=status) -> None:
                            status.write(
                                f"{progress.stage} part {progress.part} of {progress.parts}"
                            )

                        try:
                            result = ingest(
                                vault,
                                tally,
                                path,
                                context_tokens=context_tokens,
                                on_progress=show,
                            )
                        except ERRORS as error:
                            status.update(label=f"{path.name}: nothing changed", state="error")
                            st.error(str(error))
                            continue
                        if result.skipped:
                            status.update(label=f"{path.name} was already added", state="complete")
                            continue
                        record_ingestion(
                            vault,
                            Ingestion(
                                path.name,
                                tally.calls,
                                tally.input_tokens,
                                tally.output_tokens,
                                round(tally.seconds, 3),
                                (model.spent_usd - spent) if priced else None,
                            ),
                        )
                        status.update(
                            label=(
                                f"{path.name}: {len(result.created)} pages created, "
                                f"{len(result.updated)} updated"
                            ),
                            state="complete",
                        )

    sources = vault.sources()
    st.subheader(f"In the vault ({len(sources)})")
    if sources:
        st.dataframe(
            [{"id": key, **entry} for key, entry in sources.items()],
            hide_index=True,
            use_container_width=True,
        )
        st.caption(f"Wiki pages: {len(vault.page_slugs())}. Folder: `{vault.root}`")
    else:
        st.info("No files yet. Add some above to start.")

# --- 2. compare ----------------------------------------------------------------------


def _show_arm(item, name: str) -> None:
    arm = item.arm(name)
    title, subtitle = ARM_TITLES[name]
    st.markdown(f"#### {title}")
    st.caption(subtitle)
    if arm.found:
        st.success("Answered with citations")
    else:
        st.info("Not in your sources")
    correct = item.correct(name)
    if correct is not None:
        st.caption(
            ("✓ matches" if correct else "✗ does not match")
            + f" the expected answer: {item.expected}"
        )
    st.markdown(readable(arm.text))
    cols = st.columns(4)
    cols[0].metric("Calls", arm.calls)
    cols[1].metric("Tokens in", f"{arm.input_tokens:,}")
    cols[2].metric("Seconds", f"{arm.seconds:.1f}")
    cols[3].metric("Cost", money(arm.usd))
    if arm.citations:
        with st.expander(f"Cited paragraphs ({len(arm.citations)})"):
            for citation in arm.citations:
                try:
                    paragraph = cited_paragraph(vault, citation)
                except (VaultError, KeyError, ValueError):
                    continue
                st.markdown(f"**{paragraph.source_title}** ¶{paragraph.anchor}")
                st.write(paragraph.text)
    with st.expander("What the model saw"):
        if name == "wiki":
            st.write("Pages read:", ", ".join(arm.detail.get("pages_read", [])) or "none")
            st.write("Steps:", arm.detail.get("steps"))
        else:
            st.write("Retrieval:", arm.detail.get("retrieval"), "· k =", arm.detail.get("k"))
            st.write("Retrieved:", ", ".join(arm.detail.get("retrieved", [])) or "nothing")


def _show_comparison(item) -> None:
    st.markdown(f"### {item.question}")
    left, right = st.columns(2)
    with left:
        _show_arm(item, "wiki")
    with right:
        _show_arm(item, "rag")
    if item.shared_citations:
        st.caption(f"Both cite: {', '.join(item.shared_citations)}")
    with st.form(f"verdict-{item.id}"):
        options = ["not judged", *VERDICTS]
        verdict = st.radio(
            "Which answer is better for you?",
            options,
            index=options.index(item.verdict) if item.verdict else 0,
            horizontal=True,
        )
        note = st.text_input("Why (optional)", value=item.note)
        if st.form_submit_button("Save verdict"):
            set_verdict(vault, item.id, None if verdict == "not judged" else verdict, note)
            st.toast("Verdict saved")
    st.divider()


with compare_tab:
    st.subheader("Ask both")
    st.caption(
        "One question per line, optionally followed by `|` and the expected answer as key "
        "terms separated by commas (write `none` when your files do not answer it). "
        "Each one goes to both arms with the same model: the wiki "
        "navigates its pages (up to 8 calls), RAG answers from the retrieved paragraphs "
        "(1 call). Nothing is added to the wiki."
    )
    questions_text = st.text_area(
        "Questions",
        height=140,
        placeholder="What produces ATP in the cell? | ATP, mitochondria\n"
        "Which sources disagree about the dose? | none",
    )
    k = st.slider("Paragraphs retrieved by RAG (k)", 1, 20, DEFAULT_K)
    st.session_state.last_k = k
    asked = st.button(
        "Ask both",
        type="primary",
        disabled=model is None or not vault.sources(),
    )
    if not vault.sources():
        st.info("Add files in **1 · Sources** first.")
    if asked:
        lines = [line.strip() for line in questions_text.splitlines() if line.strip()]
        for line in lines:
            question, _, expected = (part.strip() for part in line.partition("|"))
            with st.spinner(f"Asking: {question}"):
                try:
                    result = compare(
                        vault, model, question, k=k, embedder=embedder, expected=expected
                    )
                except ERRORS as error:
                    st.error(str(error))
                    break
            save_comparison(vault, result)

    saved = load_comparisons(vault)
    for item in reversed(saved[-10:]):
        _show_comparison(item)
    if len(saved) > 10:
        st.caption(f"The last 10 of {len(saved)} comparisons. All of them are in **3 · Results**.")

# --- 3. results ----------------------------------------------------------------------

with results_tab:
    saved = load_comparisons(vault)
    summary = summarize(saved, load_ingestions(vault))
    st.subheader(f"Your experiment: {summary.questions} questions, {summary.judged} judged")
    advice = recommend(summary, k=st.session_state.get("last_k"))
    box = {"wiki": st.success, "rag": st.success, "undecided": st.info}[advice.choice]
    box(f"**Recommendation: {advice.headline}**")
    for reason in advice.reasons:
        st.markdown(f"- {reason}")
    if not saved:
        st.info("Ask some questions in **2 · Compare** to see the results here.")
    else:
        left, right = st.columns(2)
        for column, name in ((left, "wiki"), (right, "rag")):
            arm = summary.arms[name]
            with column:
                st.markdown(f"#### {ARM_TITLES[name][0]}")
                if arm.checked:
                    st.metric("Matches the expected answer", f"{arm.correct} / {arm.checked}")
                cols = st.columns(3)
                cols[0].metric("Answered", f"{arm.answered} / {arm.questions}")
                cols[1].metric("Preferred", arm.preferred)
                cols[2].metric("Cost of questions", money(arm.total_usd))
                cols = st.columns(3)
                cols[0].metric("Mean tokens in", f"{arm.mean_input_tokens:,.0f}")
                cols[1].metric("Mean tokens out", f"{arm.mean_output_tokens:,.0f}")
                cols[2].metric("Mean seconds", f"{arm.mean_seconds:.1f}")
                if name == "wiki":
                    st.caption(
                        f"Plus building the wiki once: {summary.ingestion_calls} calls, "
                        f"{money(summary.ingestion_usd)}."
                    )
        st.caption(f"Ties: {summary.ties} · Neither was right: {summary.neither}")
        st.dataframe(rows(saved), hide_index=True, use_container_width=True)
        st.download_button("Download CSV", to_csv(saved), "comparisons.csv", "text/csv")
        jsonl = (vault.root / STATE_DIR / "comparisons.jsonl").read_text(encoding="utf-8")
        st.download_button("Download JSONL", jsonl, "comparisons.jsonl", "application/json")

    with st.expander("How to read these results"):
        st.markdown(
            "- **Answered** counts answers with at least one valid citation; it is not "
            "correctness. Expected answers and your verdicts measure quality.\n"
            "- The wiki pays once to write pages and then spends more per question, because "
            "it reads pages. RAG has no building cost and one call per question.\n"
            "- In the study behind wikinotes (100 arXiv papers, 100 questions, the same model "
            "for both arms), the wiki answered 0.70 of the answerable questions and RAG 0.48 "
            "with k = 5, at 7.2× the cost per question. With k = 20 the gap fell to +0.06 and "
            "was no longer significant. Your files may behave differently: that is why the "
            "lab exists."
        )
