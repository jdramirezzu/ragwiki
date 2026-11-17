import json

import pytest

from wikinotes.models import Reply
from wikinotes.vault import Vault


class ScriptedModel:
    """Stands in for a real model: returns the given replies in order and records the calls.

    Tests must never reach a real API, so every model interaction goes through this class.
    """

    def __init__(self, *replies):
        self.replies = [r if isinstance(r, str) else json.dumps(r) for r in replies]
        self.calls: list[tuple[str, str]] = []

    def complete(self, system: str, user: str) -> Reply:
        self.calls.append((system, user))
        if not self.replies:
            raise AssertionError("The scripted model ran out of replies")
        return Reply(text=self.replies.pop(0), input_tokens=1000, output_tokens=500)


@pytest.fixture
def vault(tmp_path):
    return Vault.create(tmp_path / "vault")


@pytest.fixture
def note(tmp_path):
    def write(name: str, text: str):
        path = tmp_path / name
        path.write_text(text, encoding="utf-8")
        return path

    return write
