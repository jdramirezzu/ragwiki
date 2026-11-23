"""The lab's local web server: a thin HTTP layer over the library and a browser front.

Started by `wikinotes lab`. It listens on localhost only. Model calls run in a background
thread, one job at a time, and the page polls `/api/jobs/<id>` for progress. The API key is
kept in memory and never sent back to the browser.
"""

import os
import threading
import uuid
from collections.abc import Callable
from dataclasses import asdict
from pathlib import Path
from typing import Annotated

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse, PlainTextResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from wikinotes.ask import cited_paragraph
from wikinotes.compare import (
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
from wikinotes.lab import LAB_TYPES, save_upload, to_csv
from wikinotes.models import (
    DEFAULT_CONTEXT_TOKENS,
    BudgetExceeded,
    ConfigError,
    MeteredModel,
    Model,
    ModelError,
    OpenAICompatibleModel,
)
from wikinotes.rag import DEFAULT_K, Embedder, OpenAICompatibleEmbedder
from wikinotes.vault import STATE_DIR, Vault, VaultError

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


class Config(BaseModel):
    model: str = ""
    base_url: str = ""
    api_key: str | None = None
    """None keeps the key already set; an empty string clears it."""
    price_input: float = Field(0.0, ge=0)
    price_output: float = Field(0.0, ge=0)
    max_usd: float = Field(1.0, ge=0)
    context_tokens: int = Field(DEFAULT_CONTEXT_TOKENS, ge=1000)
    embedding_model: str = ""


class VaultRequest(BaseModel):
    folder: str


class FilesRequest(BaseModel):
    files: list[str]


class Question(BaseModel):
    question: str = Field(min_length=1)
    expected: str = ""


class CompareRequest(BaseModel):
    questions: list[Question] = Field(min_length=1)
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
    return Config(
        model=os.environ.get("WIKINOTES_MODEL", ""),
        base_url=os.environ.get("WIKINOTES_BASE_URL", ""),
        api_key=os.environ.get("WIKINOTES_API_KEY", ""),
        price_input=_env_number("WIKINOTES_PRICE_INPUT", 0.0),
        price_output=_env_number("WIKINOTES_PRICE_OUTPUT", 0.0),
        max_usd=_env_number("WIKINOTES_MAX_USD", 1.0),
        context_tokens=int(_env_number("WIKINOTES_CONTEXT_TOKENS", DEFAULT_CONTEXT_TOKENS)),
        embedding_model=os.environ.get("WIKINOTES_EMBEDDING_MODEL", ""),
    )


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
        self.make_embedder = make_embedder or (
            lambda c: (
                OpenAICompatibleEmbedder(c.embedding_model, c.base_url or None, c.api_key or None)
                if c.embedding_model
                else None
            )
        )
        self.metered: MeteredModel | None = None
        self.jobs: dict[str, dict] = {}
        self.busy = threading.Lock()
        if folder is not None and (Path(folder) / STATE_DIR / "state.json").is_file():
            self.vault = Vault(Path(folder))
        self.suggested = str(folder or Path.home() / "wikinotes-lab")

    # --- model -----------------------------------------------------------------------

    def model(self) -> MeteredModel:
        if not self.config.model:
            raise ConfigError("No model configured. Fill in the model settings first.")
        if self.metered is None:
            self.metered = MeteredModel(
                self.make_model(self.config),
                self.need_vault().root / STATE_DIR / "calls.jsonl",
                price_input=self.config.price_input,
                price_output=self.config.price_output,
                max_usd=self.config.max_usd or None,
            )
        return self.metered

    def priced(self) -> bool:
        return self.config.price_input > 0 or self.config.price_output > 0

    def need_vault(self) -> Vault:
        if self.vault is None:
            raise HTTPException(409, "Open or create a vault first.")
        return self.vault

    # --- jobs ------------------------------------------------------------------------

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


def _state(lab: Lab) -> dict:
    vault = lab.vault
    config = lab.config.model_dump(exclude={"api_key"})
    config["api_key_set"] = bool(lab.config.api_key)
    state: dict = {"config": config, "types": list(LAB_TYPES), "suggested": lab.suggested}
    state["session"] = {
        "calls": lab.metered.calls if lab.metered else 0,
        "usd": round(lab.metered.spent_usd, 6) if lab.metered and lab.priced() else None,
    }
    if vault is None:
        return state | {"vault": None}
    sources = [{"id": key, **entry} for key, entry in sorted(vault.sources().items())]
    return state | {
        "vault": {"root": str(vault.root), "sources": sources, "pages": len(vault.page_slugs())}
    }


def _summary(lab: Lab, k: int | None) -> dict:
    vault = lab.need_vault()
    summary = summarize(load_comparisons(vault), load_ingestions(vault))
    return {"summary": asdict(summary), "recommendation": asdict(recommend(summary, k=k))}


def _comparison(item) -> dict:
    data = asdict(item)
    data["correct"] = {name: item.correct(name) for name in ("wiki", "rag")}
    data["shared_citations"] = item.shared_citations
    return data


def create_app(lab: Lab) -> FastAPI:
    app = FastAPI(title="wikinotes lab", docs_url=None, redoc_url=None)

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

    @app.post("/api/uploads")
    async def upload(files: Annotated[list[UploadFile], File()]) -> dict:
        vault = lab.need_vault()
        saved: list[Path] = []
        for upload in files:
            try:
                saved.append(save_upload(vault, upload.filename or "", await upload.read()))
            except ValueError as error:
                raise HTTPException(400, str(error)) from error
        try:
            estimate = estimate_ingest(
                vault,
                saved,
                context_tokens=lab.config.context_tokens,
                price_input=lab.config.price_input,
                price_output=lab.config.price_output,
            )
        except ERRORS as error:
            raise HTTPException(400, str(error)) from error
        return {"files": [path.name for path in saved], "estimate": asdict(estimate)}

    @app.post("/api/ingest")
    def start_ingest(request: FilesRequest) -> dict:
        vault = lab.need_vault()
        folder = vault.root / STATE_DIR / "uploads"
        paths = [folder / Path(name).name for name in request.files]
        missing = [path.name for path in paths if not path.is_file()]
        if missing:
            raise HTTPException(400, f"Upload these files first: {', '.join(missing)}")
        model = lab.model()

        def work(job: dict) -> list[dict]:
            results = []
            for path in paths:
                tally, spent = Tally(model), model.spent_usd

                def report(progress: Progress, name: str = path.name) -> None:
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
                    results.append({"file": path.name, "error": str(error)})
                    continue
                if not result.skipped:
                    usd = (model.spent_usd - spent) if lab.priced() else None
                    record_ingestion(
                        vault,
                        Ingestion(
                            path.name,
                            tally.calls,
                            tally.input_tokens,
                            tally.output_tokens,
                            round(tally.seconds, 3),
                            usd,
                        ),
                    )
                results.append({"file": path.name, **asdict(result)})
            return results

        return lab.start("ingest", work)

    @app.post("/api/compare")
    def start_compare(request: CompareRequest) -> dict:
        vault = lab.need_vault()
        if not vault.sources():
            raise HTTPException(400, "Add files to the vault first.")
        model = lab.model()
        embedder = lab.make_embedder(lab.config)
        prices = (lab.config.price_input, lab.config.price_output)

        def work(job: dict) -> list[dict]:
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
    def summary(k: int | None = None) -> dict:
        return _summary(lab, k)

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
    print(f"wikinotes lab running at {url} (Ctrl+C to stop)")
    uvicorn.run(app, host="127.0.0.1", port=port, log_level="warning")
