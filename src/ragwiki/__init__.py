"""ragwiki: an interlinked, LLM-maintained Markdown wiki built from your own material.

Everything an application needs is importable from here. The command line in
`ragwiki.cli` is one such application and uses nothing else.
"""

__version__ = "0.1.0"

from ragwiki.ask import Answer, CitedParagraph, ask, cited_paragraph
from ragwiki.compare import Comparison, Recommendation, compare, recommend, summarize
from ragwiki.domain import Block, Page, Source
from ragwiki.estimate import Estimate, estimate_ingest
from ragwiki.extract import UnreadableSource, UnsupportedFormat
from ragwiki.ingest import IngestError, IngestResult, Progress, ingest
from ragwiki.models import (
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
from ragwiki.rag import RagAnswer, ask_rag
from ragwiki.vault import Vault, VaultError

__all__ = [
    "summarize",
    "recommend",
    "compare",
    "ask_rag",
    "Recommendation",
    "RagAnswer",
    "Comparison",
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
