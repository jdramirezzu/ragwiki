import time

import pytest
from conftest import ScriptedModel
from test_ask import ANSWER, READ, SEARCH
from test_ingest import CELLS, PLAN, WRITE

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from wikinotes.server import Config, Lab, create_app  # noqa: E402

RAG_ANSWER = {"found": True, "text": "Mitochondria [[src-cell-biology#^p2]]."}


@pytest.fixture
def lab(tmp_path):
    model = ScriptedModel(PLAN, WRITE, SEARCH, READ, ANSWER, RAG_ANSWER)
    config = Config(model="scripted", api_key="secret-key", price_input=1.0, price_output=2.0)
    lab = Lab(tmp_path / "vault", config, make_model=lambda _: model)
    lab.scripted = model
    return lab


@pytest.fixture
def client(lab):
    return TestClient(create_app(lab))


def wait(client, job):
    for _ in range(200):
        current = client.get(f"/api/jobs/{job['id']}").json()
        if current["status"] != "running":
            return current
        time.sleep(0.02)
    raise AssertionError("the job did not finish")


def test_the_page_and_its_assets_are_served(client):
    assert "wikinotes lab" in client.get("/").text
    assert client.get("/static/app.js").status_code == 200
    assert client.get("/static/app.css").status_code == 200


def test_state_never_returns_the_api_key(client):
    state = client.get("/api/state").json()

    assert state["vault"] is None
    assert state["config"]["api_key_set"] is True
    assert "secret-key" not in str(state)


def test_saving_settings_without_a_key_keeps_the_previous_one(client, lab):
    response = client.put("/api/config", json={"model": "other", "api_key": None})

    assert response.json()["config"]["model"] == "other"
    assert lab.config.api_key == "secret-key"


def test_actions_before_a_vault_is_open_are_refused(client):
    response = client.post("/api/compare", json={"questions": [{"question": "ATP?"}]})

    assert response.status_code == 409
    assert "Open or create a vault" in response.json()["detail"]


def test_full_flow_upload_estimate_build_compare_judge_and_recommend(client, lab, tmp_path):
    folder = str(tmp_path / "vault")
    assert client.post("/api/vault", json={"folder": folder}).json()["vault"]["sources"] == []

    upload = client.post(
        "/api/uploads", files={"files": ("cells.md", CELLS.encode(), "text/markdown")}
    ).json()
    assert upload["files"] == ["cells.md"]
    assert upload["estimate"]["files"] == 1 and upload["estimate"]["usd"] > 0

    built = wait(client, client.post("/api/ingest", json={"files": ["cells.md"]}).json())
    assert built["status"] == "done", built
    assert built["result"][0]["created"] == ["cell", "mitochondria"]
    assert [event["stage"] for event in built["events"]] == ["planning", "writing"]
    assert client.get("/api/state").json()["vault"]["pages"] == 2

    question = {"question": "What produces ATP?", "expected": "mitochondria"}
    compared = wait(
        client, client.post("/api/compare", json={"questions": [question], "k": 3}).json()
    )
    assert compared["status"] == "done", compared
    result = compared["result"][0]
    assert result["wiki"]["found"] and result["rag"]["found"]
    assert result["correct"] == {"wiki": True, "rag": True}
    assert result["rag"]["detail"]["k"] == 3
    assert result["rag"]["usd"] == pytest.approx(0.002)

    citation = client.get("/api/citation", params={"c": "src-cell-biology#^p2"}).json()
    assert citation["text"] == "Mitochondria produce ATP."

    verdict = client.put(f"/api/comparisons/{result['id']}/verdict", json={"verdict": "tie"})
    assert verdict.status_code == 200
    summary = client.get("/api/summary", params={"k": 3}).json()
    assert summary["summary"]["judged"] == 1
    assert summary["recommendation"]["choice"] == "undecided"
    assert "question,verdict" in client.get("/api/export.csv").text.splitlines()[0]
    assert '"tie"' in client.get("/api/export.jsonl").text


def test_a_failed_model_call_is_reported_by_the_job(client, lab, tmp_path):
    client.post("/api/vault", json={"folder": str(tmp_path / "vault")})
    client.post("/api/uploads", files={"files": ("cells.md", CELLS.encode(), "text/markdown")})
    lab.scripted.replies = ["not json", "still not json"]

    job = wait(client, client.post("/api/ingest", json={"files": ["cells.md"]}).json())

    assert job["status"] == "done"
    assert "error" in job["result"][0]
    assert client.get("/api/state").json()["vault"]["sources"] == []


def test_uploads_outside_the_supported_types_are_refused(client, tmp_path):
    client.post("/api/vault", json={"folder": str(tmp_path / "vault")})

    response = client.post("/api/uploads", files={"files": ("data.xlsx", b"PK", "x")})

    assert response.status_code == 400
