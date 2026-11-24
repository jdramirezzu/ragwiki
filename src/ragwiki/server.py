"""The lab's local web server: a thin HTTP layer over the library and a browser front.

Started by `ragwiki lab`. It listens on localhost only. Model calls run in a background
thread, one job at a time, and the page polls `/api/jobs/<id>` for progress. The API key is
kept in memory and never sent back to the browser.

The person adds files once (free: text extraction only), then builds the vector search
index, the WikiLLM or both, and asks with one architecture or compares the two.
"""

import importlib.util
import os
import threading
import uuid
from collections.abc import Callable
from dataclasses import asdict
from pathlib import Path
from typing import Annotated, Literal

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse, PlainTextResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from ragwiki.ask import cited_paragraph
from ragwiki.compare import (
    Ingestion,
    Tally,
    answer_with,
    compare,
    load_answers,
    load_comparisons,
    load_ingestions,
    recommend,
    record_answer,
    record_ingestion,
    save_comparison,
    set_verdict,
    summarize,
)
from ragwiki.estimate import estimate_ingest
from ragwiki.extract import UnreadableSource, UnsupportedFormat
from ragwiki.ingest import IngestError, Progress, add_source_only, ingest
from ragwiki.lab import LAB_TYPES, save_upload, to_csv
from ragwiki.models import (
    DEFAULT_CONTEXT_TOKENS,
    BudgetExceeded,
    ConfigError,
    MeteredModel,
    Model,
    ModelError,
    OpenAICompatibleModel,
)
from ragwiki.rag import (
    DEFAULT_K,
    LOCAL_MODEL,
    Embedder,
    LocalEmbedder,
    OpenAICompatibleEmbedder,
    build_index,
    default_local_model,
    index_status,
)
from ragwiki.vault import STATE_DIR, Vault, VaultError

WEB = Path(__file__).with_name("web")
ERRORS = (
    BudgetExceeded,
    ConfigError,
    IngestError,
    ModelError,
    UnreadableSource,
    UnsupportedFormat,
    VaultError,
)
Retrieval = Literal["local", "provider", "bm25"]


def _local_available() -> bool:
    return importlib.util.find_spec("fastembed") is not None


class Config(BaseModel):
    model: str = ""
    base_url: str = ""
    api_key: str | None = None
    """None keeps the key already set; an empty string clears it."""
    price_input: float = Field(0.0, ge=0)
    price_output: float = Field(0.0, ge=0)
    max_usd: float = Field(1.0, ge=0)
    context_tokens: int = Field(DEFAULT_CONTEXT_TOKENS, ge=1000)
    retrieval: Retrieval = "local"
    """local: embeddings on this computer; provider: the provider's embeddings; bm25: words."""
    embedding_model: str = ""


class VaultRequest(BaseModel):
    folder: str


class Question(BaseModel):
    question: str = Field(min_length=1)
    expected: str = ""


class CompareRequest(BaseModel):
    questions: list[Question] = Field(min_length=1)
    k: int = Field(DEFAULT_K, ge=1, le=50)


class AskRequest(BaseModel):
    question: str = Field(min_length=1)
    arm: Literal["wiki", "rag"]
    k: int = Field(DEFAULT_K, ge=1, le=50)


class VerdictRequest(BaseModel):
    verdict: str | None = None
    note: str = ""


def _env_number(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name) or default)
    except ValueError:
        return default


def config_from_env() -> Config:
    embedding = os.environ.get("RAGWIKI_EMBEDDING_MODEL", "")
    retrieval = "provider" if embedding else ("local" if _local_available() else "bm25")
    return Config(
        model=os.environ.get("RAGWIKI_MODEL", ""),
        base_url=os.environ.get("RAGWIKI_BASE_URL", ""),
        api_key=os.environ.get("RAGWIKI_API_KEY", ""),
        price_input=_env_number("RAGWIKI_PRICE_INPUT", 0.0),
        price_output=_env_number("RAGWIKI_PRICE_OUTPUT", 0.0),
        max_usd=_env_number("RAGWIKI_MAX_USD", 1.0),
        context_tokens=int(_env_number("RAGWIKI_CONTEXT_TOKENS", DEFAULT_CONTEXT_TOKENS)),
        retrieval=retrieval,
        embedding_model=embedding,
    )


def default_embedder(config: Config) -> Embedder | None:
    if config.retrieval == "local":
        return LocalEmbedder(config.embedding_model or LOCAL_MODEL)
    if config.retrieval == "provider":
        if not config.embedding_model:
            raise ConfigError("Name the provider's embedding model, or choose local embeddings.")
        return OpenAICompatibleEmbedder(
            config.embedding_model, config.base_url or None, config.api_key or None
        )
    return None


class Lab:
    """Server state: the open vault, the model settings and the running jobs."""

    def __init__(
        self,
        folder: Path | None,
        config: Config,
        make_model: Callable[[Config], Model] | None = None,
        make_embedder: Callable[[Config], Embedder | None] | None = None,
    ) -> None:
        self.vault: Vault | None = None
        self.config = config
        self.make_model = make_model or (
            lambda c: OpenAICompatibleModel(c.model, c.base_url or None, c.api_key or None)
        )
        self.make_embedder = make_embedder or default_embedder
        self.metered: MeteredModel | None = None
        self._embedder: tuple[tuple, Embedder | None] | None = None
        self.jobs: dict[str, dict] = {}
        self.estimates: dict[tuple, dict] = {}
        self.busy = threading.Lock()
        if folder is not None and (Path(folder) / STATE_DIR / "state.json").is_file():
            self.vault = Vault(Path(folder))
        self.suggested = str(folder or Path.home() / "ragwiki-lab")

    def model(self) -> MeteredModel:
        if not self.config.model:
            raise HTTPException(400, "No model configured. Fill in the model settings first.")
        if self.metered is None:
            self.metered = MeteredModel(
                self.make_model(self.config),
                self.need_vault().root / STATE_DIR / "calls.jsonl",
                price_input=self.config.price_input,
                price_output=self.config.price_output,
                max_usd=self.config.max_usd or None,
            )
        return self.metered

    def embedding_model(self) -> str:
        """The model in use: the one chosen, or for local embeddings one fit for the files."""
        if self.config.embedding_model or self.config.retrieval != "local" or not self.vault:
            return self.config.embedding_model
        return default_local_model(self.vault)

    def embedder(self) -> Embedder | None:
        """Kept between requests: a local model takes a few seconds to load."""
        model = self.embedding_model()
        key = (self.config.retrieval, model, self.config.base_url)
        if self._embedder is None or self._embedder[0] != key:
            config = self.config.model_copy(update={"embedding_model": model})
            self._embedder = (key, self.make_embedder(config))
        return self._embedder[1]

    def priced(self) -> bool:
        return self.config.price_input > 0 or self.config.price_output > 0

    def need_vault(self) -> Vault:
        if self.vault is None:
            raise HTTPException(409, "Open or create a vault first.")
        return self.vault

    def start(self, kind: str, work: Callable[[dict], object]) -> dict:
        if not self.busy.acquire(blocking=False):
            raise HTTPException(409, "Another task is running. Wait for it to finish.")
        job = {"id": uuid.uuid4().hex[:12], "kind": kind, "status": "running", "events": []}
        job |= {"result": None, "error": None}
        self.jobs[job["id"]] = job

        def run() -> None:
            try:
                job["result"] = work(job)
                job["status"] = "done"
            except ERRORS as error:
                job["error"], job["status"] = str(error), "failed"
            except Exception as error:  # noqa: BLE001 - the page must learn about any failure
                job["error"], job["status"] = f"Unexpected error: {error}", "failed"
            finally:
                self.busy.release()

        threading.Thread(target=run, daemon=True).start()
        return job


# --- views ------------------------------------------------------------------------------


def _state(lab: Lab) -> dict:
    vault = lab.vault
    config = lab.config.model_dump(exclude={"api_key"})
    config["api_key_set"] = bool(lab.config.api_key)
    state: dict = {
        "config": config,
        "types": list(LAB_TYPES),
        "suggested": lab.suggested,
        "local_embeddings": _local_available(),
        "local_model": lab.embedding_model() or LOCAL_MODEL,
    }
    state["session"] = {
        "calls": lab.metered.calls if lab.metered else 0,
        "usd": round(lab.metered.spent_usd, 6) if lab.metered and lab.priced() else None,
    }
    if vault is None:
        return state | {"vault": None}
    sources = [
        {"id": key, **entry, "wiki": vault.in_wiki(key)}
        for key, entry in sorted(vault.sources().items())
    ]
    return state | {
        "vault": {"root": str(vault.root), "sources": sources, "pages": len(vault.page_slugs())}
    }


def _retrieval_label(lab: Lab) -> str:
    model = lab.embedding_model()
    if lab.config.retrieval == "local":
        return f"local embeddings ({model or LOCAL_MODEL})"
    if lab.config.retrieval == "provider":
        return f"provider embeddings ({model or 'not set'})"
    return "keyword search (BM25)"


def _build_state(lab: Lab) -> dict:
    vault = lab.need_vault()
    sources = vault.sources()
    pending = [key for key in sources if not vault.in_wiki(key)]
    wiki = {"sources": len(sources) - len(pending), "pending": len(pending)}
    wiki |= {"pages": len(vault.page_slugs()), "estimate": None}
    if pending:
        # Extracting PDFs is slow, so an estimate is reused until the inputs change.
        key = (
            tuple(sorted(pending)),
            tuple(vault.page_slugs()),
            lab.config.context_tokens,
            lab.config.price_input,
            lab.config.price_output,
        )
        if key not in lab.estimates:
            estimate = estimate_ingest(
                vault,
                [vault.original_path(source) for source in pending],
                context_tokens=lab.config.context_tokens,
                price_input=lab.config.price_input,
                price_output=lab.config.price_output,
            )
            lab.estimates[key] = asdict(estimate)
        wiki["estimate"] = lab.estimates[key]
    rag = {"retrieval": lab.config.retrieval, "label": _retrieval_label(lab)}
    if lab.config.retrieval == "bm25":
        paragraphs = sum(len(vault.load_source(key).paragraphs) for key in sources)
        rag |= {"indexed": paragraphs, "paragraphs": paragraphs, "ready": bool(paragraphs)}
    else:
        try:
            status = index_status(vault, lab.embedder())
        except ConfigError as error:
            rag |= {"indexed": 0, "paragraphs": 0, "ready": False, "error": str(error)}
        else:
            rag |= {
                "indexed": status.indexed,
                "paragraphs": status.paragraphs,
                "ready": status.ready,
            }
    ingestions = load_ingestions(vault)
    wiki["spent_usd"] = (
        sum(item.usd for item in ingestions if item.usd is not None) if ingestions else None
    )
    wiki["ready"] = wiki["pages"] > 0
    return {"wiki": wiki, "rag": rag}


def _comparison(item) -> dict:
    data = asdict(item)
    data["correct"] = {name: item.correct(name) for name in ("wiki", "rag")}
    data["shared_citations"] = item.shared_citations
    return data


def create_app(lab: Lab) -> FastAPI:
    app = FastAPI(title="ragwiki lab", docs_url=None, redoc_url=None)

    @app.get("/api/state")
    def state() -> dict:
        return _state(lab)

    @app.post("/api/vault")
    def open_vault(request: VaultRequest) -> dict:
        folder = Path(request.folder).expanduser()
        try:
            lab.vault = Vault.find(folder) if (folder / STATE_DIR).exists() else None
            if lab.vault is None:
                lab.vault = Vault.create(folder)
        except (VaultError, OSError) as error:
            raise HTTPException(400, str(error)) from error
        lab.metered = None
        return _state(lab)

    @app.put("/api/config")
    def set_config(config: Config) -> dict:
        if config.api_key is None:
            config.api_key = lab.config.api_key
        lab.config = config
        lab.metered = None
        return _state(lab)

    # --- 1 · sources: extraction only, no model call ---------------------------------

    @app.post("/api/sources")
    async def add_sources(files: Annotated[list[UploadFile], File()]) -> dict:
        vault = lab.need_vault()
        added, failed = [], []
        for upload in files:
            try:
                path = save_upload(vault, upload.filename or "", await upload.read())
                added.append(asdict(add_source_only(vault, path)) | {"file": path.name})
            except (ValueError, *ERRORS) as error:
                failed.append({"file": upload.filename, "error": str(error)})
        return {"added": added, "failed": failed, "state": _state(lab)}

    # --- 2 · build -------------------------------------------------------------------

    @app.get("/api/build")
    def build_state() -> dict:
        return _build_state(lab)

    @app.post("/api/build/wiki")
    def build_wiki() -> dict:
        vault = lab.need_vault()
        pending = [key for key in vault.sources() if not vault.in_wiki(key)]
        if not pending:
            raise HTTPException(400, "The WikiLLM already includes every file.")
        model = lab.model()

        def work(job: dict) -> list[dict]:
            results = []
            for key in pending:
                path = vault.original_path(key)
                title = vault.sources()[key]["title"]
                tally, spent = Tally(model), model.spent_usd

                def report(progress: Progress, name: str = title) -> None:
                    job["events"].append(asdict(progress) | {"file": name})

                try:
                    result = ingest(
                        vault,
                        tally,
                        path,
                        context_tokens=lab.config.context_tokens,
                        on_progress=report,
                    )
                except (IngestError, UnreadableSource, UnsupportedFormat) as error:
                    results.append({"file": title, "error": str(error)})
                    continue
                usd = (model.spent_usd - spent) if lab.priced() else None
                record_ingestion(
                    vault,
                    Ingestion(
                        title,
                        tally.calls,
                        tally.input_tokens,
                        tally.output_tokens,
                        round(tally.seconds, 3),
                        usd,
                    ),
                )
                results.append({"file": title, **asdict(result)})
            return results

        return lab.start("wiki", work)

    @app.post("/api/build/index")
    def build_vector_index() -> dict:
        vault = lab.need_vault()
        if not vault.sources():
            raise HTTPException(400, "Add files first.")
        if lab.config.retrieval == "bm25":
            raise HTTPException(
                400, "Keyword search needs no index. Choose embeddings to build one."
            )

        def work(job: dict) -> dict:
            job["events"].append({"stage": "loading the embedding model"})
            embedder = lab.embedder()

            def report(done: int, total: int) -> None:
                job["events"].append({"stage": "embedding", "done": done, "total": total})

            return asdict(build_index(vault, embedder, report))

        return lab.start("index", work)

    # --- 3 · ask: one architecture, or both as an experiment -------------------------

    @app.post("/api/ask")
    def ask_one(request: AskRequest) -> dict:
        vault = lab.need_vault()
        built = _build_state(lab)
        if not built[request.arm]["ready"]:
            name = "WikiLLM" if request.arm == "wiki" else "vector search index"
            raise HTTPException(400, f"Build the {name} first.")
        model = lab.model()
        prices = (lab.config.price_input, lab.config.price_output)

        def work(job: dict) -> dict:
            embedder = lab.embedder() if request.arm == "rag" else None
            result = answer_with(
                vault,
                model,
                request.question.strip(),
                request.arm,
                k=request.k,
                embedder=embedder,
                prices=prices,
            )
            return asdict(record_answer(vault, request.question.strip(), result))

        return lab.start("ask", work)

    @app.get("/api/answers")
    def answers() -> list[dict]:
        return [asdict(item) for item in load_answers(lab.need_vault())]

    @app.post("/api/compare")
    def start_compare(request: CompareRequest) -> dict:
        vault = lab.need_vault()
        built = _build_state(lab)
        if not (built["wiki"]["ready"] and built["rag"]["ready"]):
            raise HTTPException(400, "Build both the WikiLLM and the vector search to compare.")
        model = lab.model()
        prices = (lab.config.price_input, lab.config.price_output)

        def work(job: dict) -> list[dict]:
            embedder = lab.embedder()
            done = []
            for number, item in enumerate(request.questions, start=1):
                job["events"].append({"question": item.question, "number": number})
                result = compare(
                    vault,
                    model,
                    item.question.strip(),
                    k=request.k,
                    embedder=embedder,
                    prices=prices,
                    expected=item.expected,
                )
                save_comparison(vault, result)
                done.append(_comparison(result))
            return done

        return lab.start("compare", work)

    @app.get("/api/jobs/{job_id}")
    def job(job_id: str) -> dict:
        if job_id not in lab.jobs:
            raise HTTPException(404, "Unknown task")
        return lab.jobs[job_id]

    # --- 4 · results -----------------------------------------------------------------

    @app.get("/api/comparisons")
    def comparisons() -> list[dict]:
        return [_comparison(item) for item in load_comparisons(lab.need_vault())]

    @app.put("/api/comparisons/{comparison_id}/verdict")
    def verdict(comparison_id: str, request: VerdictRequest) -> dict:
        try:
            set_verdict(lab.need_vault(), comparison_id, request.verdict, request.note)
        except KeyError as error:
            raise HTTPException(404, str(error)) from error
        except ValueError as error:
            raise HTTPException(400, str(error)) from error
        return {"ok": True}

    @app.get("/api/summary")
    def summary(k: int | None = None, lang: str = "en") -> dict:
        vault = lab.need_vault()
        result = summarize(load_comparisons(vault), load_ingestions(vault))
        advice = recommend(result, k=k, lang=lang)
        return {"summary": asdict(result), "recommendation": asdict(advice)}

    @app.get("/api/citation")
    def citation(c: str) -> dict:
        try:
            return asdict(cited_paragraph(lab.need_vault(), c))
        except (VaultError, KeyError, ValueError) as error:
            raise HTTPException(404, f"Citation not found: {c}") from error

    @app.get("/api/export.csv")
    def export_csv() -> PlainTextResponse:
        text = to_csv(load_comparisons(lab.need_vault()))
        headers = {"Content-Disposition": 'attachment; filename="comparisons.csv"'}
        return PlainTextResponse(text, media_type="text/csv", headers=headers)

    @app.get("/api/export.jsonl")
    def export_jsonl() -> Response:
        path = lab.need_vault().root / STATE_DIR / "comparisons.jsonl"
        text = path.read_text(encoding="utf-8") if path.is_file() else ""
        headers = {"Content-Disposition": 'attachment; filename="comparisons.jsonl"'}
        return Response(text, media_type="application/x-ndjson", headers=headers)

    @app.get("/")
    def index() -> FileResponse:
        return FileResponse(WEB / "index.html")

    app.mount("/static", StaticFiles(directory=WEB), name="static")
    return app


def run(folder: Path | None, port: int, open_browser: bool = True) -> None:
    import webbrowser

    import uvicorn

    app = create_app(Lab(folder, config_from_env()))
    url = f"http://127.0.0.1:{port}"
    if open_browser:
        threading.Timer(1.0, webbrowser.open, args=(url,)).start()
    print(f"ragwiki lab running at {url} (Ctrl+C to stop)")
    uvicorn.run(app, host="127.0.0.1", port=port, log_level="warning")
