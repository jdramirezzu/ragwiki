import time

import pytest
from conftest import ScriptedModel
from test_ask import ANSWER, READ, SEARCH
from test_ingest import CELLS, PLAN, WRITE
from test_rag import FakeEmbedder

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from ragwiki.server import Config, Lab, create_app  # noqa: E402

RAG_ANSWER = {"found": True, "text": "Mitochondria [[src-cell-biology#^p2]]."}
MD = ("cells.md", CELLS.encode(), "text/markdown")


@pytest.fixture
def lab(tmp_path):
    model = ScriptedModel()
    config = Config(model="scripted", api_key="secret-key", price_input=1.0, price_output=2.0)
    lab = Lab(
        tmp_path / "vault",
        config,
        make_model=lambda _: model,
        make_embedder=lambda c: None if c.retrieval == "bm25" else FakeEmbedder(),
    )
    lab.scripted = model
    return lab


@pytest.fixture
def client(lab, tmp_path):
    client = TestClient(create_app(lab))
    client.post("/api/vault", json={"folder": str(tmp_path / "vault")})
    return client


def wait(client, job):
    for _ in range(300):
        current = client.get(f"/api/jobs/{job['id']}").json()
        if current["status"] != "running":
            return current
        time.sleep(0.02)
    raise AssertionError("the job did not finish")


def test_the_page_and_its_assets_are_served(client):
    assert "ragwiki lab" in client.get("/").text
    assert client.get("/static/app.js").status_code == 200
    assert client.get("/static/app.css").status_code == 200


def test_state_never_returns_the_api_key(client):
    state = client.get("/api/state").json()

    assert state["config"]["api_key_set"] is True
    assert "secret-key" not in str(state)


def test_saving_settings_without_a_key_keeps_the_previous_one(client, lab):
    response = client.put("/api/config", json={"model": "other", "api_key": None})

    assert response.json()["config"]["model"] == "other"
    assert lab.config.api_key == "secret-key"


def test_actions_before_a_vault_is_open_are_refused(lab):
    fresh = TestClient(create_app(Lab(None, lab.config)))

    response = fresh.post("/api/compare", json={"questions": [{"question": "ATP?"}]})

    assert response.status_code == 409


def test_adding_files_is_free_and_leaves_both_architectures_unbuilt(client, lab):
    added = client.post("/api/sources", files={"files": MD}).json()

    assert added["added"][0]["paragraphs"] == 2
    assert lab.scripted.calls == []
    build = client.get("/api/build").json()
    assert build["wiki"] == build["wiki"] | {"sources": 0, "pending": 1, "ready": False}
    assert build["wiki"]["estimate"]["calls"] == 2
    assert build["rag"] == build["rag"] | {"indexed": 0, "paragraphs": 2, "ready": False}


def test_build_only_the_vector_index_and_ask_with_it(client, lab):
    client.post("/api/sources", files={"files": MD})

    built = wait(client, client.post("/api/build/index").json())
    assert built["status"] == "done", built
    assert client.get("/api/build").json()["rag"]["ready"] is True
    assert client.post("/api/compare", json={"questions": [{"question": "q"}]}).status_code == 400
    refused = client.post("/api/ask", json={"question": "ATP?", "arm": "wiki"})
    assert "Build the WikiLLM first" in refused.json()["detail"]

    lab.scripted.replies = ['{"found": true, "text": "Mitochondria [[src-cell-biology#^p2]]."}']
    job = wait(client, client.post("/api/ask", json={"question": "ATP?", "arm": "rag"}).json())

    assert job["status"] == "done", job
    assert job["result"]["result"]["arm"] == "rag"
    assert job["result"]["result"]["detail"]["retrieval"] == "embeddings:fake/embedder"
    assert client.get("/api/answers").json()[0]["question"] == "ATP?"


def test_build_only_the_wiki_and_ask_with_it(client, lab):
    import json

    client.post("/api/sources", files={"files": MD})
    lab.scripted.replies = [json.dumps(x) for x in (PLAN, WRITE)]

    built = wait(client, client.post("/api/build/wiki").json())
    assert built["status"] == "done", built
    assert built["result"][0]["created"] == ["cell", "mitochondria"]
    build = client.get("/api/build").json()
    assert build["wiki"]["ready"] and build["wiki"]["pending"] == 0
    assert client.get("/api/state").json()["vault"]["sources"][0]["wiki"] is True

    lab.scripted.replies = [json.dumps(x) for x in (SEARCH, READ, ANSWER)]
    job = wait(client, client.post("/api/ask", json={"question": "ATP?", "arm": "wiki"}).json())
    assert job["result"]["result"]["found"] is True
    assert job["result"]["result"]["calls"] == 3


def test_full_experiment_with_both_judge_and_recommend(client, lab):
    import json

    client.post("/api/sources", files={"files": MD})
    wait(client, client.post("/api/build/index").json())
    lab.scripted.replies = [json.dumps(x) for x in (PLAN, WRITE)]
    wait(client, client.post("/api/build/wiki").json())
    lab.scripted.replies = [json.dumps(x) for x in (SEARCH, READ, ANSWER, RAG_ANSWER)]

    question = {"question": "What produces ATP?", "expected": "mitochondria"}
    job = client.post("/api/compare", json={"questions": [question], "k": 3}).json()
    compared = wait(client, job)
    assert compared["status"] == "done", compared
    result = compared["result"][0]
    assert result["correct"] == {"wiki": True, "rag": True}
    assert result["rag"]["detail"]["k"] == 3
    assert result["rag"]["usd"] == pytest.approx(0.002)

    citation = client.get("/api/citation", params={"c": "src-cell-biology#^p2"}).json()
    assert citation["text"] == "Mitochondria produce ATP."
    assert client.put(
        f"/api/comparisons/{result['id']}/verdict", json={"verdict": "tie"}
    ).is_success
    summary = client.get("/api/summary", params={"k": 3}).json()
    assert summary["summary"]["judged"] == 1
    assert summary["recommendation"]["choice"] == "undecided"
    assert "question,verdict" in client.get("/api/export.csv").text.splitlines()[0]
    assert '"tie"' in client.get("/api/export.jsonl").text


def test_keyword_search_needs_no_index(client):
    client.put("/api/config", json={"model": "scripted", "retrieval": "bm25"})
    client.post("/api/sources", files={"files": MD})

    assert client.get("/api/build").json()["rag"]["ready"] is True
    assert client.post("/api/build/index").status_code == 400


def test_a_failed_wiki_build_changes_nothing(client, lab):
    client.post("/api/sources", files={"files": MD})
    lab.scripted.replies = ["not json", "still not json"]

    job = wait(client, client.post("/api/build/wiki").json())

    assert "error" in job["result"][0]
    assert client.get("/api/build").json()["wiki"]["pending"] == 1


def test_unsupported_files_are_reported_not_added(client):
    response = client.post("/api/sources", files={"files": ("data.xlsx", b"PK", "x")}).json()

    assert response["added"] == []
    assert "only pdf" in response["failed"][0]["error"]


def test_the_recommendation_can_be_asked_in_spanish(client):
    advice = client.get("/api/summary", params={"lang": "es"}).json()["recommendation"]

    assert advice["headline"].startswith("Aún no hay evidencia suficiente")


def test_local_embeddings_switch_to_a_multilingual_model_for_spanish_files(client, lab):
    spanish = (
        "# Célula\n\nLa mitocondria produce la energía de la célula.\n\nEl núcleo guarda el ADN."
    )
    seen = []
    lab.make_embedder = lambda config: seen.append(config.embedding_model) or FakeEmbedder()
    client.post("/api/sources", files={"files": ("celula.md", spanish.encode(), "text/markdown")})

    build = client.get("/api/build").json()

    assert "paraphrase-multilingual-MiniLM-L12-v2" in build["rag"]["label"]
    assert seen == ["sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"]


class FirstWins:
    name = "fake/reranker"

    def scores(self, question, texts):
        return [float(-i) for i in range(len(texts))]


def test_compare_kinds_of_rag_for_free_then_answer_with_two(client, lab):
    lab.make_reranker = lambda model: FirstWins()
    client.post("/api/sources", files={"files": MD})
    names = client.get("/api/state").json()["variants"]
    assert names[:3] == ["bm25", "vector", "hybrid"]
    questions = [{"question": "Which organelle produces ATP?", "expected": "mitochondria"}]

    job = client.post(
        "/api/variants/search", json={"questions": questions, "variants": names, "k": 2}
    ).json()
    done = wait(client, job)

    assert done["status"] == "done", done
    assert [s["variant"] for s in done["result"]["scores"]] == names
    assert all(s["checked"] == 1 for s in done["result"]["scores"])
    assert done["result"]["best"] in names
    assert lab.scripted.calls == []
    assert client.get("/api/variants/search").json()["id"] == done["result"]["id"]

    reply = '{"found": true, "text": "Mitochondria [[src-cell-biology#^p2]]."}'
    lab.scripted.replies = [reply, reply]
    job = client.post(
        "/api/variants/answer",
        json={"questions": questions, "variants": ["bm25", "hybrid+rerank"], "k": 2},
    ).json()
    done = wait(client, job)

    assert done["status"] == "done", done
    assert [r["variant"] for r in done["result"]] == ["bm25", "hybrid+rerank"]
    assert [r["correct"] for r in done["result"]] == [True, True]
    assert done["events"][-1] == {
        "number": 2,
        "total": 2,
        "question": questions[0]["question"],
        "variant": "hybrid+rerank",
    }
    assert len(client.get("/api/variants/answers").json()) == 2


def test_unknown_kinds_of_rag_are_refused(client):
    client.post("/api/sources", files={"files": MD})
    response = client.post(
        "/api/variants/search",
        json={"questions": [{"question": "q"}], "variants": ["bm25+magic"]},
    )
    assert response.status_code == 400
