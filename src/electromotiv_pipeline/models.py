from __future__ import annotations

from dataclasses import asdict, dataclass, field


@dataclass(frozen=True)
class Article:
    index: int
    title: str
    url: str
    source: str
    published_at: str
    snippet: str
    source_name: str = "google_news"
    domain: str = ""


@dataclass(frozen=True)
class RankedLink:
    query: str
    run_id: str
    rank: int
    article_index: int
    title: str
    url: str
    source: str
    source_name: str
    domain: str
    published_at: str
    llm_score: float
    reason: str
    created_at: str
    model: str = ""
    keywords: tuple[str, ...] = field(default_factory=tuple)
    llm_raw_response: str = ""

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class SavedRecord:
    url: str
    rid: str
