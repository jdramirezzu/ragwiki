import subprocess

import pytest

from wikinotes.domain import Page
from wikinotes.extract import extract
from wikinotes.vault import Vault, VaultError


def make_note(tmp_path, name="cells.md", text="# Cell biology\n\nThe cell is the unit of life.\n"):
    path = tmp_path / name
    path.write_text(text, encoding="utf-8")
    return path


def test_create_builds_the_layout(tmp_path):
    vault = Vault.create(tmp_path / "wiki")

    for name in ("sources", "extracted", "wiki", ".wikinotes"):
        assert (vault.root / name).is_dir()
    for name in ("index.md", "log.md", "SCHEMA.md"):
        assert (vault.root / name).is_file()
    assert vault.sources() == {}
    assert vault.page_slugs() == []


def test_create_refuses_an_existing_vault(tmp_path):
    Vault.create(tmp_path)

    with pytest.raises(VaultError):
        Vault.create(tmp_path)


def test_find_walks_up_to_the_vault_root(tmp_path):
    vault = Vault.create(tmp_path)
    inner = tmp_path / "wiki"

    assert Vault.find(inner).root == vault.root
    with pytest.raises(VaultError):
        Vault.find(tmp_path.parent)


def test_a_source_round_trips_through_the_vault(tmp_path):
    vault = Vault.create(tmp_path / "wiki")
    note = make_note(tmp_path, text="# Cell biology\n\nFirst.\n\n- a\n- b\n\nLast.\n")
    source = extract(note)

    stored = vault.add_source(source, note)
    loaded = vault.load_source(stored.id)

    assert stored.id == "src-cell-biology"
    assert loaded.paragraphs == {"p1": "First.", "p2": "- a\n- b", "p3": "Last."}
    assert loaded.title == "Cell biology"
    assert (vault.root / "sources" / "src-cell-biology.md").read_text(encoding="utf-8") == (
        note.read_text(encoding="utf-8")
    )
    assert vault.has_hash(source.sha256)
    assert vault.sources()["src-cell-biology"]["original"] == "cells.md"


def test_source_ids_never_collide(tmp_path):
    vault = Vault.create(tmp_path / "wiki")
    first = make_note(tmp_path, "a.md", "# Notes\n\nOne.\n")
    second = make_note(tmp_path, "b.md", "# Notes\n\nTwo.\n")

    assert vault.add_source(extract(first), first).id == "src-notes"
    assert vault.add_source(extract(second), second).id == "src-notes-2"


def test_a_page_round_trips_and_appears_in_the_index(tmp_path):
    vault = Vault.create(tmp_path)
    page = Page(
        slug="mitochondria",
        title="Mitochondria",
        type="concept",
        summary="Organelle that produces ATP.",
        sources=["src-cell-biology"],
        body="Mitochondria produce ATP [[src-cell-biology#^p2]]. See [[cell]].",
    )

    vault.write_page(page)
    vault.rebuild_index()

    loaded = vault.read_page("mitochondria")
    assert (loaded.title, loaded.type, loaded.summary) == (page.title, page.type, page.summary)
    assert loaded.sources == ["src-cell-biology"]
    assert loaded.body == page.body
    assert vault.page_slugs() == ["mitochondria"]
    index = (vault.root / "index.md").read_text(encoding="utf-8")
    assert "[[mitochondria]]" in index
    assert "Organelle that produces ATP." in index


def test_commit_records_a_snapshot_in_the_vault_git_history(tmp_path):
    vault = Vault.create(tmp_path)
    vault.append_log("added something")

    vault.commit("add: something")

    log = subprocess.run(
        ["git", "log", "--format=%s"], cwd=vault.root, capture_output=True, text=True, check=True
    )
    assert log.stdout.splitlines()[0] == "add: something"
