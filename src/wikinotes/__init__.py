"""wikinotes: an interlinked, LLM-maintained Markdown wiki built from your own material.

Everything an application needs is importable from here. The command line in
`wikinotes.cli` is one such application and uses nothing else.
"""

__version__ = "0.1.0"

from wikinotes.ask import Answer, CitedParagraph, ask, cited_paragraph
from wikinotes.domain import Block, Page, Source
from wikinotes.estimate import Estimate, estimate_ingest
from wikinotes.extract import UnreadableSource, UnsupportedFormat
from wikinotes.ingest import IngestError, IngestResult, Progress, ingest
from wikinotes.models import (
    BudgetExceeded,
    ConfigError,
    Image,
    MeteredModel,
    Model,
    ModelError,
    OpenAICompatibleModel,
    Reply,
    metered_from_env,
)
from wikinotes.vault import Vault, VaultError

__all__ = [
    "Answer",
    "Block",
    "BudgetExceeded",
    "CitedParagraph",
    "ConfigError",
    "Estimate",
    "Image",
    "IngestError",
    "IngestResult",
    "MeteredModel",
    "Model",
    "ModelError",
    "OpenAICompatibleModel",
    "Page",
    "Progress",
    "Reply",
    "Source",
    "UnreadableSource",
    "UnsupportedFormat",
    "Vault",
    "VaultError",
    "__version__",
    "ask",
    "cited_paragraph",
    "estimate_ingest",
    "ingest",
    "metered_from_env",
]
