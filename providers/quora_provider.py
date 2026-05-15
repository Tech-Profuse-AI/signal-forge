"""
SignalForge Quora Provider.

Quora has no official public API, so we discover content via
search-engine queries (site:quora.com <query>), then fetch and
parse the result pages for question metadata.

Modes:
  - mock  — loads data/mock_quora_posts.json (no network calls)
  - live  — uses a SERP API or DuckDuckGo scraping to find Quora URLs,
             then fetches page metadata from each question page

Normalised output schema:
    {
        "id":       str,   # derived from URL slug
        "platform": "quora",
        "title":    str,
        "body":     str,   # first answer snippet or question detail
        "url":      str,
        "score":    int,   # follower / upvote count (best-effort)
        "author":   str,
        "topic":    str,
    }
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import time
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import quote_plus, urlparse
from urllib.request import Request, urlopen
from urllib.error import URLError, HTTPError

from utils.url_validator import validate_and_clean

logger = logging.getLogger("signalforge.quora")

_DEFAULT_MOCK_PATH = (
    Path(__file__).resolve().parent.parent / "tests" / "mock_quora_posts.json"
)
# ── User-Agent for page fetching ─────────────────────────────────────
_USER_AGENT = (
    "Mozilla/5.0 (compatible; SignalForge/1.0; +https://signalforge.io)"
)


def _url_to_id(url: str) -> str:
    """Derive a stable short ID from a Quora URL."""
    # Ensure uniqueness by hashing the full URL to prevent slug collisions
    hash_str = hashlib.sha1(url.encode()).hexdigest()[:8]
    slug = urlparse(url).path.rstrip("/").split("/")[-1]
    if slug:
        return f"qra_{slug[:30]}_{hash_str}"
    return f"qra_{hash_str}"


class QuoraProvider:
    """
    Discovers Quora questions via search and parses their metadata.

    Args:
        mock_mode:      If True, load from mock_quora_posts.json only.
        mock_data_path: Override path to mock JSON.
        serp_api_key:   Optional SerpAPI key for live search.
                        If absent, falls back to DuckDuckGo HTML scraping.
        request_delay:  Seconds to wait between HTTP requests (live mode).
    """

    def __init__(
        self,
        mock_mode: bool = False,
        mock_data_path: Optional[str] = None,
        serp_api_key: Optional[str] = None,
        request_delay: float = 1.5,
    ) -> None:
        self._mock_mode = mock_mode
        self._mock_path = Path(mock_data_path) if mock_data_path else _DEFAULT_MOCK_PATH
        self._serp_api_key = serp_api_key
        self._request_delay = request_delay

        mode = "MOCK" if mock_mode else "LIVE"
        logger.info("QuoraProvider initialised — mode=%s", mode)

    # ── Public API ────────────────────────────────────────────────────

    def fetch_posts(
        self, query: str, limit: int = 10
    ) -> List[Dict[str, Any]]:
        """
        Fetch and normalise Quora posts for the given query.

        Args:
            query: Search term (e.g. "best CRM for small business").
            limit: Maximum number of posts to return.

        Returns:
            List of normalised post dicts.
        """
        if self._mock_mode:
            return self._fetch_mock(query, limit)
        return self._fetch_live(query, limit)

    def normalize(self, raw: Dict[str, Any]) -> Dict[str, Any]:
        """
        Normalise a raw Quora result dict into the SignalForge schema.

        Accepts either a raw scraped dict or an already-normalised dict
        and always returns the canonical Quora schema.
        """
        raw_url = raw.get("url", "")
        cleaned_url, is_valid = validate_and_clean(raw_url, "quora")

        if not is_valid:
            logger.debug("Skipping invalid Quora URL: %s", raw_url)

        return {
            "id": raw.get("id") or _url_to_id(cleaned_url or raw_url),
            "platform": "quora",
            "title": raw.get("title", "").strip(),
            "body": raw.get("body", "").strip(),
            "url": cleaned_url,
            "url_valid": is_valid,
            "score": int(raw.get("score", 0)),
            "author": raw.get("author", "").strip(),
            "topic": raw.get("topic", "").strip(),
        }

    # ── Mock mode ─────────────────────────────────────────────────────

    def _fetch_mock(self, query: str, limit: int) -> List[Dict[str, Any]]:
        """Load mock data and filter/truncate to simulate a real query."""
        if not self._mock_path.exists():
            logger.warning("Mock file not found: %s", self._mock_path)
            return []

        try:
            with open(self._mock_path, "r", encoding="utf-8") as fh:
                raw_posts: List[Dict[str, Any]] = json.load(fh)
        except (json.JSONDecodeError, OSError) as exc:
            logger.error("Failed to load mock data: %s", exc)
            return []

        # Simple relevance filter: keyword match in title + body
        q_lower = query.lower()
        matched = [
            p for p in raw_posts
            if q_lower in (p.get("title", "") + " " + p.get("body", "")).lower()
        ]
        # Fall back to all posts if nothing matches — useful for broad tests
        pool = matched if matched else raw_posts

        posts = [self.normalize(p) for p in pool[:limit]]
        logger.info(
            "Mock fetch: query='%s' -> %d/%d posts returned",
            query, len(posts), len(raw_posts),
        )
        return posts

    # ── Live mode ─────────────────────────────────────────────────────

    def _fetch_live(self, query: str, limit: int) -> List[Dict[str, Any]]:
        """
        1. Discover Quora URLs via search (SerpAPI or DuckDuckGo).
        2. Filter URLs: only crawl valid www.quora.com question pages.
        3. Crawl each question page (Firecrawl when configured) and extract structured content.
           Falls back to lightweight HTML meta parsing when crawling is unavailable.
        4. Normalise and return.

        Crawl targets are capped at 5 to stay under 90s total runtime.
        """
        raw_urls = self._search_quora_urls(query, limit)

        # --- Pre-crawl URL filtering ---
        urls: List[str] = []
        for raw_url in raw_urls:
            cleaned, valid = validate_and_clean(raw_url, "quora")
            if valid:
                urls.append(cleaned)
            else:
                logger.debug("Skipping Quora URL before crawl: %s", raw_url)

        # Cap crawl targets to avoid >90s runtime with Firecrawl
        max_crawl = min(5, limit)
        crawl_urls = urls[:max_crawl]
        logger.info(
            "Discovered %d Quora URLs for '%s' — valid %d — crawling %d",
            len(raw_urls), query, len(urls), len(crawl_urls),
        )

        posts: List[Dict[str, Any]] = []
        for idx, url in enumerate(crawl_urls, 1):
            try:
                logger.info("Crawling %d/%d: %s", idx, len(crawl_urls), url)
                raw = self._crawl_quora_page(url) or self._parse_quora_page(url)
                if raw:
                    body = raw.get("body", "")
                    if len(body.strip()) < 25:
                        logger.info(
                            "Quora page has short body; passing to scanner filter: body_len=%d url=%s",
                            len(body.strip()), url,
                        )
                    normalised = self.normalize(raw)
                    if normalised.get("url_valid", True):
                        posts.append(normalised)
                time.sleep(self._request_delay)
            except Exception as exc:
                logger.warning("Failed to parse %s: %s", url, exc)

        # If live discovery is blocked/unavailable, fall back to mock data to keep
        # downstream agents functioning in offline/test-like environments.
        if not posts and _DEFAULT_MOCK_PATH.exists():
            logger.warning("Live fetch returned 0 posts — falling back to mock data")
            return self._fetch_mock(query, limit)

        logger.info(
            "Live fetch: query='%s' -> %d posts", query, len(posts)
        )
        return posts

    def _search_quora_urls(self, query: str, limit: int) -> List[str]:
        """
        Return a list of quora.com question URLs for the given query.

        Tries SerpAPI first; falls back to Firecrawl Search, then DuckDuckGo HTML scraping.
        """
        if self._serp_api_key:
            return self._serp_api_search(query, limit)
            
        api_key = str(os.environ.get("FIRECRAWL_API_KEY", "") or "").strip()
        if api_key:
            try:
                urls = self._firecrawl_search(query, limit, api_key)
                if urls:
                    return urls
            except Exception as exc:
                logger.warning("Firecrawl search failed, falling back to DuckDuckGo: %s", exc)

        return self._duckduckgo_search(query, limit)

    def _serp_api_search(self, query: str, limit: int) -> List[str]:
        """Use SerpAPI to run a site:quora.com search."""
        try:
            import requests  # noqa: PLC0415

            search_query = f"site:quora.com {query}"
            resp = requests.get(
                "https://serpapi.com/search",
                params={
                    "q": search_query,
                    "api_key": self._serp_api_key,
                    "engine": "google",
                    "num": limit,
                },
                timeout=10,
                headers={"User-Agent": _USER_AGENT},
            )
            resp.raise_for_status()
            data = resp.json()

            urls: List[str] = []
            for result in data.get("organic_results", []):
                url = result.get("link", "")
                if "quora.com/q/" in url or "/What-" in url or "/How-" in url:
                    urls.append(url)
            return urls[:limit]

        except Exception as exc:
            logger.error("SerpAPI search failed: %s", exc)
            return []

    def _firecrawl_search(self, query: str, limit: int, api_key: str) -> List[str]:
        """Use Firecrawl's /v1/search endpoint to find Quora URLs."""
        try:
            import json  # noqa: PLC0415
            from urllib.request import Request, urlopen  # noqa: PLC0415

            search_query = f"site:quora.com {query}"
            endpoint = "https://api.firecrawl.dev/v1/search"
            body = json.dumps({"query": search_query, "limit": limit * 2}).encode("utf-8")

            req = Request(
                endpoint,
                method="POST",
                data=body,
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                    "User-Agent": _USER_AGENT,
                },
            )
            with urlopen(req, timeout=15) as resp:
                raw = resp.read().decode("utf-8", errors="replace")

            data = json.loads(raw)
            if not data.get("success"):
                raise RuntimeError(f"Firecrawl search unsuccessful: {str(data)[:300]}")

            urls: List[str] = []
            for item in data.get("data", []):
                url = item.get("url", "")
                if re.search(r"/[A-Z][^/]*[-][^/]+", urlparse(url).path):
                    if url not in urls:
                        urls.append(url)
                if len(urls) >= limit:
                    break
                    
            logger.info("Firecrawl search for '%s': found %d Quora URLs", query, len(urls))
            return urls

        except Exception as exc:
            logger.error("Firecrawl search failed: %s", exc)
            return []

    def _duckduckgo_search(self, query: str, limit: int) -> List[str]:
        """
        Scrape DuckDuckGo HTML results for site:quora.com links.
        No API key needed. Rate-limit friendly — uses a single request.
        """
        try:
            import requests  # noqa: PLC0415
            from html.parser import HTMLParser  # noqa: PLC0415

            search_query = f"site:quora.com {query}"
            encoded = quote_plus(search_query)

            resp = requests.get(
                f"https://html.duckduckgo.com/html/?q={encoded}",
                headers={
                    "User-Agent": _USER_AGENT,
                    "Accept-Language": "en-US,en;q=0.9",
                },
                timeout=12,
            )
            resp.raise_for_status()

            # Extract href values pointing to quora.com
            urls: List[str] = []
            href_pattern = re.compile(
                r'href="(https?://(?:www\.)?quora\.com/[^"]+)"',
                re.IGNORECASE,
            )
            for match in href_pattern.finditer(resp.text):
                url = match.group(1)
                # Keep only question pages, skip profile/topic pages
                if re.search(r"/[A-Z][^/]*[-][^/]+", urlparse(url).path):
                    if url not in urls:
                        urls.append(url)
                if len(urls) >= limit:
                    break

            logger.info(
                "DuckDuckGo search for '%s': found %d Quora URLs",
                query, len(urls),
            )
            return urls

        except Exception as exc:
            logger.error("DuckDuckGo search failed: %s", exc)
            return []

    def _parse_quora_page(self, url: str) -> Optional[Dict[str, Any]]:
        """
        Fetch a Quora question page and extract:
          - title (from <title> or og:title)
          - body snippet (from og:description or first answer)
          - author (from structured data if present)
          - topic (from URL or breadcrumb)
          - score (follower count if parseable)
        """
        try:
            import requests  # noqa: PLC0415

            resp = requests.get(
                url,
                headers={
                    "User-Agent": _USER_AGENT,
                    "Accept": "text/html,application/xhtml+xml",
                    "Accept-Language": "en-US,en;q=0.9",
                },
                timeout=12,
            )
            resp.raise_for_status()
            html = resp.text

        except Exception as exc:
            logger.warning("HTTP fetch failed for %s: %s", url, exc)
            return None

        # ── Extract via Open Graph / meta tags ────────────────────────
        title = _extract_meta(html, "og:title") or _extract_title_tag(html)
        body = _extract_meta(html, "og:description") or ""
        author = _extract_meta(html, "author") or ""

        # ── Topic from URL path ───────────────────────────────────────
        path_parts = urlparse(url).path.strip("/").split("/")
        topic = path_parts[0] if path_parts else ""

        # ── Score: try to find follower count ─────────────────────────
        score = _extract_score(html)

        if not title:
            logger.debug("No title found for %s — skipping", url)
            return None

        return {
            "id": _url_to_id(url),
            "platform": "quora",
            "title": title,
            "body": body[:500],
            "url": url,
            "score": score,
            "author": author,
            "topic": topic,
        }

    def _crawl_quora_page(self, url: str) -> Optional[Dict[str, Any]]:
        """
        Crawl a Quora question page and extract structured content.

        Primary integration: Firecrawl API (if FIRECRAWL_API_KEY is set).
        If Firecrawl is not configured or crawling fails, returns None so the
        caller can fall back to lightweight HTML parsing.

        Extracts (best-effort):
          - question title
          - question body
          - answer count
          - top answer snippet
          - author/topic (if present)

        Output is still normalized to the canonical Quora schema via normalize().
        """
        api_key = str(os.environ.get("FIRECRAWL_API_KEY", "") or "").strip()
        if not api_key:
            return None

        try:
            payload = self._firecrawl_scrape(url=url, api_key=api_key)
        except Exception as exc:  # noqa: BLE001
            logger.info("Firecrawl crawl failed for %s: %s", url, exc)
            return None

        extracted = _extract_quora_from_firecrawl(payload, url)
        return extracted or None

    def _firecrawl_scrape(self, *, url: str, api_key: str, timeout: int = 25) -> Dict[str, Any]:
        """
        Firecrawl scrape call (mock in tests).

        Uses the Firecrawl REST API to retrieve cleaned page content and metadata.
        """
        endpoint = "https://api.firecrawl.dev/v1/scrape"
        body = json.dumps({
            "url": url,
            "formats": ["markdown", "html"],
            "onlyMainContent": True,
        }).encode("utf-8")
        req = Request(
            endpoint,
            method="POST",
            data=body,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
                "User-Agent": _USER_AGENT,
                "Accept": "application/json",
            },
        )
        try:
            with urlopen(req, timeout=timeout) as resp:
                raw = resp.read().decode("utf-8", errors="replace")
        except HTTPError as exc:
            raw = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"Firecrawl HTTP {exc.code}: {raw[:300]}") from exc
        except URLError as exc:
            raise RuntimeError(f"Firecrawl network error: {exc}") from exc

        try:
            data = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise RuntimeError("Firecrawl returned non-JSON response") from exc

        if not isinstance(data, dict) or data.get("success") is not True:
            raise RuntimeError(f"Firecrawl scrape unsuccessful: {str(data)[:300]}")
        return data

    def __repr__(self) -> str:
        mode = "mock" if self._mock_mode else "live"
        return f"<QuoraProvider mode='{mode}'>"


# ── HTML parsing helpers ─────────────────────────────────────────────

def _extract_meta(html: str, property_name: str) -> str:
    """Extract a meta tag value by og: property or name attribute."""
    # og:* pattern
    pattern_og = re.compile(
        rf'<meta[^>]+property=["\']?{re.escape(property_name)}["\']?[^>]+content=["\']([^"\']+)["\']',
        re.IGNORECASE | re.DOTALL,
    )
    m = pattern_og.search(html)
    if m:
        return m.group(1).strip()

    # name=* pattern
    pattern_name = re.compile(
        rf'<meta[^>]+name=["\']?{re.escape(property_name)}["\']?[^>]+content=["\']([^"\']+)["\']',
        re.IGNORECASE | re.DOTALL,
    )
    m = pattern_name.search(html)
    if m:
        return m.group(1).strip()

    return ""


def _extract_title_tag(html: str) -> str:
    """Fall back to <title> tag."""
    m = re.search(r"<title[^>]*>([^<]+)</title>", html, re.IGNORECASE)
    if m:
        raw = m.group(1).strip()
        # Quora appends " - Quora" — strip it
        return re.sub(r"\s*[-|]\s*Quora\s*$", "", raw).strip()
    return ""


def _extract_score(html: str) -> int:
    """
    Try to parse a follower / upvote count from the page.
    Returns 0 if not found (Quora hides counts behind JS in many cases).
    """
    # Look for follower patterns like "1.2K followers" or "847 followers"
    m = re.search(
        r"([\d,\.]+)\s*[Kk]?\s*follower",
        html,
        re.IGNORECASE,
    )
    if m:
        raw = m.group(1).replace(",", "")
        try:
            val = float(raw)
            # Handle "1.2K" stored as "1.2" — but K was caught in suffix
            if "K" in m.group(0) or "k" in m.group(0):
                val *= 1000
            return int(val)
        except ValueError:
            pass
    return 0


def _extract_quora_from_firecrawl(payload: Dict[str, Any], url: str) -> Optional[Dict[str, Any]]:
    """
    Convert Firecrawl response into a Quora raw dict compatible with normalize().

    Firecrawl payload shape varies by version; we support:
      - payload["data"]["markdown"] or payload["data"]["content"]
      - payload["data"]["metadata"] with title/description/author
    """
    if not isinstance(payload, dict):
        return None
    data = payload.get("data", {})
    if not isinstance(data, dict):
        return None

    meta = data.get("metadata", {})
    if not isinstance(meta, dict):
        meta = {}

    markdown = data.get("markdown") or data.get("content") or ""
    if not isinstance(markdown, str):
        markdown = ""

    title = str(meta.get("title") or "").strip()
    if not title:
        # Try first markdown heading as question title
        m = re.search(r"^\s*#\s+(.+?)\s*$", markdown, flags=re.MULTILINE)
        if m:
            title = m.group(1).strip()

    if not title:
        return None

    # Remove obvious navigation/login noise if present.
    cleaned = re.sub(r"(?i)sign up|log in|cookie|accept all", " ", markdown)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned).strip()

    # Best-effort: find question body and top answer snippet.
    # If we can't reliably split, fall back to the first ~500 chars after title.
    body = ""
    top_answer = ""
    answer_count = 0

    # Answer count heuristic: "Answers (123)" or "123 Answers"
    m_cnt = re.search(r"(?i)\b(\d{1,5})\s+answers?\b", cleaned)
    if m_cnt:
        try:
            answer_count = int(m_cnt.group(1))
        except ValueError:
            answer_count = 0

    # Try to isolate body between title and an "Answers" section marker.
    parts = cleaned.splitlines()
    # Drop the first heading line if it matches title
    if parts and title.lower() in parts[0].lower():
        parts = parts[1:]
    text_after_title = "\n".join(parts).strip()
    split = re.split(r"(?i)\n\s*answers?\s*\n", text_after_title, maxsplit=1)
    if split:
        body = split[0].strip()
        if len(split) > 1:
            remainder = split[1].strip()
            top_answer = remainder.split("\n\n", 1)[0].strip()

    body = body[:1200].strip()
    if top_answer:
        # Append top answer snippet to body to improve signal extraction.
        snippet = top_answer[:600].strip()
        if snippet and snippet.lower() not in body.lower():
            body = (body + "\n\nTop answer:\n" + snippet).strip()

    if not body:
        body = cleaned[:500]

    author = str(meta.get("author") or meta.get("siteName") or "").strip()
    # Topic can be derived from URL path prefix in QuoraScannerAgent; we keep best-effort here too.
    path_parts = urlparse(url).path.strip("/").split("/")
    topic = path_parts[0] if path_parts else ""

    # Score is best-effort; Firecrawl won't give engagement; keep 0.
    return {
        "id": _url_to_id(url),
        "platform": "quora",
        "title": title,
        "body": body,
        "url": url,
        "score": int(answer_count) if answer_count else 0,
        "author": author,
        "topic": topic,
    }
