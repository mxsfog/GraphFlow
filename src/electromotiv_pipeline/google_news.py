from __future__ import annotations

import html
import urllib.parse
import xml.etree.ElementTree as ET
from dataclasses import dataclass, replace

from electromotiv_pipeline.http_client import get_url
from electromotiv_pipeline.models import Article


@dataclass(frozen=True)
class NewsSource:
    name: str
    url: str


def build_google_news_rss_url(query: str) -> str:
    params = {
        "q": query,
        "hl": "en-US",
        "gl": "US",
        "ceid": "US:en",
    }
    return "https://news.google.com/rss/search?" + urllib.parse.urlencode(params)


def fetch_news(query: str, max_records: int, timeout_seconds: int = 30) -> list[Article]:
    articles: list[Article] = []
    errors: list[str] = []
    successful_sources = 0
    for source in build_news_sources(query):
        try:
            payload = get_url(
                source.url,
                headers={"User-Agent": "electromotiv-practice/0.1"},
                timeout_seconds=timeout_seconds,
            )
            parsed_articles = parse_google_news_rss(
                payload,
                max_records=max_records,
                source_name=source.name,
                source_url=source.url,
            )
        except (RuntimeError, ET.ParseError) as exc:
            errors.append(f"{source.name}: {exc}")
            continue
        successful_sources += 1
        articles.extend(parsed_articles)
    if successful_sources == 0:
        raise RuntimeError("Не удалось получить RSS: " + "; ".join(errors))
    return deduplicate_articles(articles)


def build_news_sources(query: str) -> list[NewsSource]:
    return [NewsSource("google_news_general", build_google_news_rss_url(query))]


def parse_google_news_rss(
    payload: bytes,
    max_records: int,
    *,
    source_name: str = "google_news",
    source_url: str = "",
) -> list[Article]:
    root = ET.fromstring(payload)
    items = root.findall("./channel/item")[:max_records]
    articles: list[Article] = []
    for index, item in enumerate(items, start=1):
        title = clean_text(item.findtext("title", default=""))
        link = clean_text(item.findtext("link", default=""))
        source = clean_text(item.findtext("source", default=""))
        published_at = clean_text(item.findtext("pubDate", default=""))
        snippet = clean_text(item.findtext("description", default=""))
        if not link:
            continue
        articles.append(
            Article(
                index=index,
                title=title,
                url=link,
                source=source,
                published_at=published_at,
                snippet=snippet,
                source_name=source_name,
                domain=extract_domain(link or source_url),
            )
        )
    return articles


def clean_text(value: str) -> str:
    return " ".join(html.unescape(value).split())


def deduplicate_articles(articles: list[Article]) -> list[Article]:
    seen_urls: set[str] = set()
    seen_titles: set[str] = set()
    deduplicated: list[Article] = []
    for article in articles:
        normalized_url = normalize_url(article.url)
        normalized_title = normalize_title(article.title)
        if normalized_url in seen_urls or normalized_title in seen_titles:
            continue
        seen_urls.add(normalized_url)
        seen_titles.add(normalized_title)
        deduplicated.append(replace(article, index=len(deduplicated) + 1))
    return deduplicated


def normalize_url(url: str) -> str:
    parsed = urllib.parse.urlsplit(url)
    query = urllib.parse.parse_qsl(parsed.query, keep_blank_values=False)
    filtered_query = [
        (key, value)
        for key, value in query
        if key.lower() not in {"utm_source", "utm_medium", "utm_campaign", "utm_term", "oc"}
    ]
    return urllib.parse.urlunsplit(
        (
            parsed.scheme.lower(),
            parsed.netloc.lower(),
            parsed.path.rstrip("/"),
            urllib.parse.urlencode(filtered_query),
            "",
        )
    )


def normalize_title(title: str) -> str:
    return " ".join(title.casefold().split())


def extract_domain(url: str) -> str:
    parsed = urllib.parse.urlsplit(url)
    return parsed.netloc.lower()
