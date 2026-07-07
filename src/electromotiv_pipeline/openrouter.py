from __future__ import annotations

import json
import re
from datetime import UTC, datetime

from electromotiv_pipeline.http_client import post_url
from electromotiv_pipeline.models import Article, RankedLink

OPENROUTER_CHAT_COMPLETIONS_URL = "https://openrouter.ai/api/v1/chat/completions"


def rank_articles_with_openrouter(
    *,
    api_key: str,
    model: str,
    query: str,
    run_id: str,
    articles: list[Article],
    timeout_seconds: int = 90,
) -> list[RankedLink]:
    if not articles:
        return []

    last_error: RuntimeError | None = None
    for strict_json in (True, False):
        body = build_openrouter_request_body(
            model=model,
            query=query,
            articles=articles,
            strict_json=strict_json,
        )
        try:
            payload = request_openrouter(
                api_key=api_key,
                body=body,
                timeout_seconds=timeout_seconds,
            )
            content = extract_message_content(payload)
            return parse_ranked_links(
                content=content,
                query=query,
                run_id=run_id,
                model=model,
                articles=articles,
            )
        except RuntimeError as exc:
            last_error = exc
            if strict_json and should_retry_without_response_format(exc):
                continue
            raise

    raise RuntimeError(f"OpenRouter request failed: {last_error}")


def should_retry_without_response_format(exc: RuntimeError) -> bool:
    message = str(exc)
    return "пустой message.content" in message or "LLM вернула невалидный JSON" in message


def request_openrouter(
    *,
    api_key: str,
    body: dict[str, object],
    timeout_seconds: int,
) -> dict[str, object]:
    try:
        return json.loads(
            post_url(
                OPENROUTER_CHAT_COMPLETIONS_URL,
                body=json.dumps(body, ensure_ascii=False).encode("utf-8"),
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                    "HTTP-Referer": "http://localhost/electromotiv-practice",
                    "X-Title": "ElectroMotiv Practice Pipeline",
                },
                timeout_seconds=timeout_seconds,
            ).decode("utf-8")
        )
    except RuntimeError as exc:
        raise RuntimeError(f"OpenRouter request failed: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise RuntimeError("OpenRouter вернул невалидный JSON-ответ API.") from exc


def extract_message_content(payload: dict[str, object]) -> str:
    choices = payload.get("choices", [])
    if not isinstance(choices, list) or not choices:
        raise RuntimeError("OpenRouter не вернул choices.")
    first_choice = choices[0]
    if not isinstance(first_choice, dict):
        raise RuntimeError("OpenRouter вернул некорректный элемент choices.")
    message = first_choice.get("message", {})
    if not isinstance(message, dict):
        raise RuntimeError("OpenRouter вернул некорректное поле message.")
    content = message.get("content")
    if isinstance(content, str) and content.strip():
        return content
    if isinstance(content, list):
        parts = [
            str(part.get("text", "")).strip()
            for part in content
            if isinstance(part, dict) and part.get("type") == "text"
        ]
        joined = "\n".join(part for part in parts if part)
        if joined:
            return joined
    finish_reason = str(first_choice.get("finish_reason") or "")
    raise RuntimeError(f"OpenRouter вернул пустой message.content. finish_reason={finish_reason}")


def build_openrouter_request_body(
    *,
    model: str,
    query: str,
    articles: list[Article],
    strict_json: bool,
) -> dict[str, object]:
    body = build_openrouter_messages(model=model, query=query, articles=articles)
    if strict_json:
        body["response_format"] = {"type": "json_object"}
    return body


def build_openrouter_messages(
    *,
    model: str,
    query: str,
    articles: list[Article],
) -> dict[str, object]:
    candidates = "\n\n".join(
        [
            "\n".join(
                [
                    f"article_index: {article.index}",
                    f"title: {article.title}",
                    f"source: {article.source or article.source_name}",
                    f"source_stream: {article.source_name}",
                    f"published_at: {article.published_at}",
                    f"snippet: {article.snippet[:600]}",
                ]
            )
            for article in articles
        ]
    )
    return {
        "model": model,
        "temperature": 0.1,
        "max_tokens": 15000,
        "messages": [
            {
                "role": "system",
                "content": (
                    "Ты аналитик новостных ссылок. Верни только валидный JSON без markdown. "
                    "Строгий формат: "
                    '{"results":[{"rank":1,"article_index":1,"llm_score":0.0,'
                    '"keywords":[""],"reason":""}]}. '
                    "Не возвращай URL, title, source и published_at: верни только article_index "
                    "из списка кандидатов, llm_score, keywords и reason. "
                    "llm_score должен быть числом от 0 до 1. "
                    "keywords составь сам: это 3-8 коротких ключевых слов, сущностей или "
                    "фраз, по которым видно, почему материал связан с текущим запросом. "
                    "Оцени соответствие строго текущему поисковому запросу, а не заранее "
                    "заданной теме. Шкала: 0.90-1.00 — материал прямо отвечает на запрос; "
                    "0.70-0.89 — сильная тематическая связь и есть ключевые факты по запросу; "
                    "0.40-0.69 — частичная или косвенная связь; 0.10-0.39 — слабая связь; "
                    "0.00-0.09 — нерелевантно. reason пиши по-русски, до 140 символов, "
                    "с конкретным основанием оценки."
                ),
            },
            {
                "role": "user",
                "content": (
                    f"Запрос: {query}\n\n"
                    "Нужно выбрать новости, которые лучше всего отвечают именно этому запросу. "
                    "Учитывай совпадение темы, фактическую близость заголовка и snippet, "
                    "наличие ключевых сущностей из запроса и отсутствие подмены темы. "
                    "Отсортируй максимум 10 кандидатов по релевантности. "
                    "Для каждого выбранного кандидата самостоятельно сформируй keywords. "
                    "В ответе используй только номера кандидатов из поля article_index. "
                    "Не выдумывай кандидатов, не меняй номера и не добавляй текст вне JSON.\n\n"
                    f"Кандидаты:\n{candidates}"
                ),
            },
        ],
    }


def parse_ranked_links(
    *,
    content: str,
    query: str,
    run_id: str = "",
    model: str = "",
    articles: list[Article] | None = None,
) -> list[RankedLink]:
    cleaned = strip_markdown_code_fence(content)
    try:
        payload = json.loads(cleaned)
    except json.JSONDecodeError as exc:
        raise RuntimeError(
            f"LLM вернула невалидный JSON: {exc.msg}. Ответ: {content[:500]}"
        ) from exc

    raw_results = payload if isinstance(payload, list) else payload.get("results", [])
    if not isinstance(raw_results, list):
        raise RuntimeError("LLM JSON не содержит массива results.")

    created_at = datetime.now(UTC).isoformat(timespec="seconds")
    article_by_index = {article.index: article for article in articles or []}
    ranked: list[RankedLink] = []
    for index, item in enumerate(raw_results, start=1):
        if not isinstance(item, dict):
            continue
        article_index = int_or_default(
            item.get("article_index") or item.get("index") or item.get("candidate_index"),
            0,
        )
        article = article_by_index.get(article_index)
        url = str(item.get("url") or "").strip()
        if article is not None:
            url = article.url
        if not url:
            continue
        llm_score = clamp_score(item.get("llm_score"))
        ranked.append(
            RankedLink(
                query=query,
                run_id=run_id,
                rank=int_or_default(item.get("rank"), index),
                article_index=article_index,
                title=(
                    article.title if article is not None else str(item.get("title") or "").strip()
                ),
                url=url,
                source=(
                    article.source if article is not None else str(item.get("source") or "").strip()
                ),
                source_name=article.source_name if article is not None else "",
                domain=article.domain if article is not None else "",
                published_at=(
                    article.published_at
                    if article is not None
                    else str(item.get("published_at") or "").strip()
                ),
                llm_score=llm_score,
                reason=str(item.get("reason") or "").strip(),
                created_at=created_at,
                model=model,
                keywords=parse_keywords(item.get("keywords")),
                llm_raw_response=content,
            )
        )
    return ranked


def strip_markdown_code_fence(content: str) -> str:
    stripped = content.strip()
    match = re.fullmatch(r"```(?:json)?\s*(.*?)\s*```", stripped, flags=re.DOTALL)
    if match:
        return match.group(1).strip()
    return stripped


def int_or_default(value: object, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def clamp_score(value: object) -> float:
    try:
        score = float(value)
    except (TypeError, ValueError):
        return 0.0
    return round(max(0.0, min(1.0, score)), 4)


def parse_keywords(value: object) -> tuple[str, ...]:
    if isinstance(value, list):
        keywords = [str(item).strip() for item in value]
    elif isinstance(value, str):
        keywords = [item.strip() for item in value.split(",")]
    else:
        keywords = []
    return tuple(keyword for keyword in keywords if keyword)
