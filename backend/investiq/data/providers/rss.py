"""RSS/Atom feed ingestion for official and permitted public sources.

Only the title, link, publication time and a short plain-text excerpt (<= 400 chars) are kept.
Full articles are never stored. XML is parsed with defusedxml (no external entities).
"""

from __future__ import annotations

import html
import re
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime

from defusedxml import ElementTree as ET

from investiq.data.providers.base import NewsDTO, ProviderError
from investiq.data.providers.http import HttpClient

_TAG = re.compile(r"<[^>]+>")
ATOM = "{http://www.w3.org/2005/Atom}"
MAX_SUMMARY = 400


def _text(el) -> str | None:
    if el is None or el.text is None:
        return None
    return el.text.strip()


def _clean(raw: str | None) -> str | None:
    if not raw:
        return None
    text = html.unescape(_TAG.sub(" ", raw))
    text = " ".join(text.split())
    if len(text) > MAX_SUMMARY:
        text = text[: MAX_SUMMARY - 1].rsplit(" ", 1)[0] + "…"
    return text or None


def _date(raw: str | None) -> datetime | None:
    if not raw:
        return None
    try:
        dt = parsedate_to_datetime(raw)
    except (TypeError, ValueError):
        try:
            dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        except ValueError:
            return None
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)


def parse_feed(xml_text: str, source_key: str, category: str | None, official: bool) -> list[NewsDTO]:
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as exc:
        raise ProviderError(f"feed {source_key} is not valid XML") from exc
    items: list[NewsDTO] = []
    for item in root.iter("item"):
        link, title = _text(item.find("link")), _text(item.find("title"))
        if not link or not title:
            continue
        items.append(NewsDTO(url=link, title=html.unescape(title), summary=_clean(_text(item.find("description"))),
                             published_at=_date(_text(item.find("pubDate")) or _text(item.find("{http://purl.org/dc/elements/1.1/}date"))),
                             source_key=source_key, category=category, official=official))
    for entry in root.iter(f"{ATOM}entry"):
        link_el = entry.find(f"{ATOM}link")
        link = link_el.get("href") if link_el is not None else None
        title = _text(entry.find(f"{ATOM}title"))
        if not link or not title:
            continue
        items.append(NewsDTO(url=link, title=html.unescape(title),
                             summary=_clean(_text(entry.find(f"{ATOM}summary")) or _text(entry.find(f"{ATOM}content"))),
                             published_at=_date(_text(entry.find(f"{ATOM}updated")) or _text(entry.find(f"{ATOM}published"))),
                             source_key=source_key, category=category, official=official))
    return items


class RssProvider:
    name = "rss"

    def __init__(self, http: HttpClient | None = None) -> None:
        self._http = http or HttpClient(min_interval_s=1.0)

    def fetch_feed(self, url: str, source_key: str, category: str | None, official: bool) -> list[NewsDTO]:
        resp = self._http.get(url)
        return parse_feed(resp.text, source_key, category, official)
