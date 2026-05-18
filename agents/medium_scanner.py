"""SignalForge Medium scanner agent."""

from __future__ import annotations

import logging
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Dict, List, Optional

from agents.opportunity_scanner.cache_manager import CacheManager
from agents.opportunity_scanner.filters import FilterConfig, OpportunityFilter
from providers.medium_provider import MediumProvider
from schemas.opportunity import serialize_opportunity
from utils.dedup import cache_keys_for_posts, dedupe_exact_posts
from utils.query_normalizer import is_generic_standalone_query, platform_queries
from utils.semantic_relevance import filter_by_semantic_relevance

logger = logging.getLogger("signalforge.medium_scanner")


_SIGNAL_PATTERNS: Dict[str, List[str]] = {
    "problem_intent": [
        "problem", "challenge", "struggle", "difficulty", "issue",
        "obstacle", "pain", "friction", "blocker", "bottleneck",
        "why i stopped", "what's wrong with", "the problem with",
        "common mistake", "pitfall", "failure", "broken",
        "doesn't work", "failed to",
    ],
    "workflow_pain": [
        "workflow", "process", "pipeline", "manual", "repetitive",
        "time-consuming", "hours every", "days every", "tedious",
        "inefficient", "slow", "wasted time", "taking too long",
        "doing it manually", "copy paste", "copy-paste",
        "context switch", "juggling", "keeping track",
        "spreadsheet", "scattered",
    ],
    "tool_evaluation": [
        "tool", "software", "platform", "app", "solution",
        "compared", "comparison", "review", "tested", "tried",
        "pros and cons", "pros & cons", "worth it", "is it worth",
        "should you use", "best tool", "top tool", "best software",
        "which tool", "which platform", "alternative",
        "switched from", "switched to", "replaced",
    ],
    "competitor_mention": [
        "zapier", "make.com", "integromat", "n8n", "activepieces",
        "hubspot", "salesforce", "marketo", "pardot",
        "notion", "airtable", "clickup", "monday", "asana",
        "hootsuite", "buffer", "sproutsocial", "later",
        "chatgpt", "jasper", "copy.ai", "writesonic",
        "midjourney", "stable diffusion", "dalle",
        "vs ", " versus ", " compared to ",
    ],
    "automation_need": [
        "automat", "autonomous", "automatically",
        "no-code", "low-code", "workflow automation",
        "trigger", "zap", "integration", "api", "webhook",
        "schedule", "recurring", "batch", "bulk",
        "scale", "at scale", "scalable",
        "save time", "time-saving", "productivity",
        "eliminate manual", "reduce manual",
        "ai agent", "ai workflow", "ai automation",
        "llm", "gpt", "generative ai",
    ],
}

_MEDIUM_FALLBACK_TAGS = [
    "workflow-automation",
    "marketing-automation",
    "lead-generation",
    "business-process-automation",
]

_MEDIUM_TAG_KEYWORDS: Dict[str, List[str]] = {
    "ai-automation": [
        "ai", "artificial", "gpt", "llm", "agent", "agents",
        "automation", "automate", "automating",
    ],
    "workflow-automation": [
        "workflow", "workflows", "automation", "automate",
        "automating", "process", "pipeline",
    ],
    "business-process-automation": [
        "business", "process", "operations", "ops", "manual",
        "repetitive", "workflow",
    ],
    "productivity-systems": [
        "productivity", "efficient", "efficiency", "save", "time",
        "schedule", "scheduling", "system", "systems",
    ],
    "social-media-marketing": [
        "social", "media", "reddit", "instagram", "linkedin", "twitter",
    ],
    "community-management": [
        "community", "reddit", "engagement", "reply", "responses",
    ],
    "marketing-automation": ["marketing", "content", "campaign", "brand", "automation"],
    "content-marketing": ["content", "writing", "copywriting", "blog"],
    "saas-growth": ["startup", "startups", "founder", "saas", "scale", "scaling"],
    "sales-automation": ["sales", "crm", "outreach", "pipeline"],
    "lead-generation": ["lead", "leads", "prospect", "prospects", "outreach"],
    "case-study": ["case", "study", "lessons", "learned", "architecture"],
}


def extract_medium_tags(query: str) -> List[str]:
    """Generate 2-5 Medium RSS tags from a natural-language query."""
    text = str(query or "").lower()
    tokens = set(re.findall(r"[a-z0-9]+", text))

    tags: List[str] = []
    for tag, keywords in _MEDIUM_TAG_KEYWORDS.items():
        if any(keyword in tokens or keyword in text for keyword in keywords):
            tags.append(tag)

    if {"ai", "automation"} <= tokens and "ai-automation" not in tags:
        tags.insert(0, "ai-automation")
    if {"workflow", "automation"} & tokens and "workflow-automation" not in tags:
        tags.insert(0, "workflow-automation")
    if "social-media-marketing" in tags and "marketing-automation" not in tags:
        tags.append("marketing-automation")
    if "lead-generation" in tags and "sales-automation" not in tags:
        tags.append("sales-automation")
    if ("case" in tokens or "study" in tokens) and "case-study" not in tags:
        tags.append("case-study")

    if len(tags) < 2:
        for fallback in _MEDIUM_FALLBACK_TAGS:
            if fallback not in tags:
                tags.append(fallback)
            if len(tags) >= 2:
                break

    deduped: List[str] = []
    for tag in tags:
        clean = re.sub(r"[^a-z0-9-]+", "-", tag.lower()).strip("-")
        if clean and clean not in deduped:
            deduped.append(clean)
        if len(deduped) >= 5:
            break

    return deduped or list(_MEDIUM_FALLBACK_TAGS)


class MediumScannerAgent:
    """Discovers and classifies Medium articles as opportunities."""

    def __init__(
        self,
        mode: str = "mock",
        filter_config: Optional[FilterConfig] = None,
        cache_dir: Optional[str] = None,
        default_keywords: Optional[List[str]] = None,
        mock_data_path: Optional[str] = None,
        cache_max_age_days: Optional[int] = None,
        ephemeral_cache: bool = False,
    ) -> None:
        self._provider = MediumProvider(mode=mode, mock_data_path=mock_data_path)
        self._cache = CacheManager(
            cache_dir=cache_dir,
            cache_filename="seen_medium_posts.json",
            max_age_days=cache_max_age_days,
            ephemeral=ephemeral_cache,
        )
        self._filter = OpportunityFilter(
            config=filter_config or self._medium_filter_config()
        )
        self._default_keywords = default_keywords or [
            "AI workflow automation case studies",
            "business process automation lessons learned",
            "marketing automation operational workflows",
            "lead generation automation architecture",
        ]
        self.stats = {"fetched": 0, "deduped": 0, "filtered": 0, "approved": 0}

        logger.info(
            "MediumScannerAgent ready - mode=%s, cache=%d seen",
            self._provider.mode,
            self._cache.size,
        )

    @property
    def mode(self) -> str:
        return self._provider.mode

    @property
    def cache(self) -> CacheManager:
        return self._cache

    @property
    def provider(self) -> MediumProvider:
        return self._provider

    def scan(
        self,
        keywords: Optional[List[str]] = None,
        limit_per_keyword: int = 10,
        original_intent: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Run fetch, exact dedup, balanced filtering, and signal extraction."""
        raw_kw = keywords or self._default_keywords
        normalised_queries = self._prepare_queries(raw_kw, original_intent=original_intent)
        tags: List[str] = []
        for query in normalised_queries:
            for tag in extract_medium_tags(query):
                if tag not in tags:
                    tags.append(tag)

        logger.info(
            "Medium tag generation: raw=%s normalized=%s tags=%s",
            raw_kw,
            normalised_queries,
            tags,
        )

        raw_posts = self._fetch_all(tags, limit_per_keyword)
        if not raw_posts:
            logger.warning(
                "Medium generated tags returned 0 articles; trying fallback tags=%s",
                _MEDIUM_FALLBACK_TAGS,
            )
            raw_posts = self._fetch_all(_MEDIUM_FALLBACK_TAGS, limit_per_keyword)

        self.stats["fetched"] += len(raw_posts)
        logger.info("Medium fetch stage: fetched=%d articles", len(raw_posts))

        deduped = self._deduplicate(raw_posts)
        self.stats["deduped"] += len(deduped)
        logger.info(
            "Medium dedup stage: input=%d kept=%d removed=%d",
            len(raw_posts),
            len(deduped),
            len(raw_posts) - len(deduped),
        )

        filtered = self._filter.filter_opportunities(deduped)
        if isinstance(raw_kw, str):
            raw_intent_text = raw_kw
        else:
            raw_intent_text = " ".join(str(item) for item in raw_kw)
        relevance_intent = original_intent or raw_intent_text
        if relevance_intent.strip():
            before_relevance = len(filtered)
            filtered = filter_by_semantic_relevance(
                filtered,
                relevance_intent,
                threshold=0.2,
            )
            logger.info(
                "Medium semantic relevance stage: input=%d kept=%d rejected=%d",
                before_relevance,
                len(filtered),
                before_relevance - len(filtered),
            )
        self.stats["filtered"] += len(filtered)
        logger.info(
            "Medium filter stage: input=%d kept=%d rejected=%d",
            len(deduped),
            len(filtered),
            len(deduped) - len(filtered),
        )

        opportunities: List[Dict[str, Any]] = []
        for article in filtered:
            signals = self._extract_signals(article)
            if signals:
                enriched = {**article, "opportunity_signals": signals}
                opportunities.append(enriched)
                logger.info(
                    "SIGNAL [%s] %s - %s",
                    article.get("id", "?"),
                    signals,
                    article.get("title", "")[:60],
                )
            else:
                logger.info(
                    "FILTER REJECT: id=%s platform=medium reason=low_relevance_medium_signals title=%s",
                    article.get("id", "?"),
                    article.get("title", "")[:60],
                )

        self._cache.mark_seen_batch(cache_keys_for_posts(opportunities))
        self.stats["approved"] += len(opportunities)
        logger.info("Final Medium opportunities: %d", len(opportunities))
        return [
            serialize_opportunity(
                opportunity,
                status="discovered",
                pipeline_state="discovered",
                can_mutate=False,
            )
            for opportunity in opportunities
        ]

    def _prepare_queries(
        self,
        raw_keywords: List[str] | str,
        *,
        original_intent: Optional[str],
    ) -> List[str]:
        if isinstance(raw_keywords, str):
            raw_list = [raw_keywords]
        else:
            raw_list = [str(item) for item in raw_keywords if str(item).strip()]

        if original_intent:
            candidates = raw_list
        else:
            candidates = platform_queries(raw_list, platform="medium", max_queries=4)

        out: List[str] = []
        for query in candidates:
            clean = str(query).strip()
            if not clean or is_generic_standalone_query(clean):
                continue
            if clean not in out:
                out.append(clean)

        return out or list(self._default_keywords)

    def generate_report(self, opportunities: List[Dict[str, Any]]) -> str:
        """Build a human-readable summary of discovered Medium opportunities."""
        if not opportunities:
            return "No Medium opportunities found in this scan."

        lines = [
            f"# Medium Opportunity Scan Report - {len(opportunities)} found",
            "",
        ]
        for i, opp in enumerate(opportunities, 1):
            signals = ", ".join(opp.get("opportunity_signals", []))
            lines.append(f"## {i}. {opp.get('title', 'Untitled')}")
            lines.append(f"- **Author:** {opp.get('author', '?')}")
            lines.append(f"- **Score:** {opp.get('score', 0)}")
            lines.append(f"- **Signals:** {signals}")
            lines.append(f"- **Tags:** {', '.join(opp.get('tags', []))}")
            lines.append(f"- **Published:** {opp.get('published_at', '?')}")
            lines.append(f"- **URL:** {opp.get('url', '')}")
            preview = opp.get("body", "")[:150]
            if preview:
                lines.append(f"- **Preview:** {preview}...")
            lines.append("")

        return "\n".join(lines)

    def _fetch_all(self, keywords: List[str], limit: int) -> List[Dict[str, Any]]:
        all_posts: List[Dict[str, Any]] = []

        def fetch_tag(tag: str) -> List[Dict[str, Any]]:
            return self._provider.fetch_posts(query=tag, limit=limit)

        with ThreadPoolExecutor(max_workers=3) as pool:
            futures = {pool.submit(fetch_tag, tag): tag for tag in keywords}
            for future in as_completed(futures):
                tag = futures[future]
                try:
                    posts = future.result()
                    all_posts.extend(posts)
                    logger.info("Fetched %d Medium articles for tag '%s'", len(posts), tag)
                    if not posts:
                        logger.info(
                            "Medium tag returned 0 articles: tag=%s reason=empty_rss",
                            tag,
                        )
                except Exception as exc:
                    logger.error("Fetch failed for Medium tag '%s': %s", tag, exc)

        return all_posts

    def _deduplicate(self, posts: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Remove only exact duplicate IDs, exact duplicate URLs, and cache hits."""
        return dedupe_exact_posts(
            posts,
            cache=self._cache,
            logger=logger,
            stage="medium",
            platform="medium",
        )

    def _extract_signals(self, article: Dict[str, Any]) -> List[str]:
        text = " ".join([
            article.get("title", ""),
            article.get("body", ""),
            " ".join(article.get("tags", [])),
        ]).lower()

        signals: List[str] = []
        for signal_name, keywords in _SIGNAL_PATTERNS.items():
            if any(kw.lower() in text for kw in keywords):
                signals.append(signal_name)

        return signals

    @staticmethod
    def _medium_filter_config() -> FilterConfig:
        """Balanced defaults for RSS previews rather than full articles."""
        config = FilterConfig(
            minimum_score=0,
            minimum_body_length=25,
        )
        config.blacklisted_subreddits = []
        config.bot_author_patterns = [
            r"b[o0]t",
            r"auto[-_]?generated",
            r"^test$",
        ]
        config.help_keywords = [
            "how to", "guide", "tutorial", "step by step",
            "tips", "strategies", "best practices", "ways to",
            "how i", "how we", "lessons learned",
        ]
        config.recommendation_keywords = [
            "recommend", "tool", "platform", "software", "review",
            "comparison", "alternative", "best", "top", "worth",
        ]
        config.pain_point_keywords = [
            "problem", "challenge", "struggle", "frustrat", "fail",
            "mistake", "wrong", "broken", "inefficient", "slow",
            "wasted", "pain", "annoying", "tedious",
        ]
        config.bottleneck_keywords = [
            "automat", "workflow", "scale", "bottleneck", "process",
            "time-consuming", "manual", "inefficient", "productivity",
            "pipeline", "integration", "schedule",
        ]
        return config

    def __repr__(self) -> str:
        return (
            f"<MediumScannerAgent mode='{self.mode}' "
            f"cache={self._cache.size}>"
        )
