# SignalForge — Frequently Asked Questions

## General

### What is SignalForge?

SignalForge is an AI-powered social media engagement platform that helps teams discover, evaluate, and respond to high-value conversations on Reddit. It uses a multi-agent pipeline to find relevant discussions, classify user intent, prioritize opportunities by business value, and draft authentic responses — all with human approval before posting.

### How does SignalForge work?

SignalForge uses a five-stage pipeline:
1. **Discovery** — Scans Reddit for keyword matches, filtering out spam and noise
2. **Classification** — AI classifies each post's intent (buying, problem, hiring, etc.)
3. **Scoring** — Ranks opportunities by business value using engagement, signals, and urgency
4. **Drafting** — Generates context-aware response drafts using product knowledge (RAG)
5. **Review** — Human-in-the-loop approval via Slack before any response is posted

### Who uses SignalForge?

SignalForge is designed for marketing teams, developer relations, SaaS companies, digital agencies, community managers, and HR teams — anyone who needs to engage authentically at scale on Reddit and social platforms.

### Is SignalForge a spam tool?

Absolutely not. SignalForge is built on the principle of authentic engagement. Every response is designed to genuinely help the community member. Built-in compliance checks enforce Reddit's rules, and no response is posted without human approval. The goal is to add value to conversations, not to spam them.

## Features & Capabilities

### What platforms does SignalForge support?

Currently, SignalForge focuses on Reddit as the primary platform, using PRAW (Python Reddit API Wrapper) for data access. The architecture is designed to support additional platforms in future phases.

### What types of opportunities does SignalForge detect?

SignalForge identifies several types of actionable conversations:
- **Help requests** — Users asking for advice or solutions
- **Recommendation requests** — Users seeking tool or product suggestions
- **Pain point discussions** — Users venting about workflow frustrations
- **Workflow bottlenecks** — Users describing scaling challenges
- **Competitor mentions** — Users discussing or comparing competing products
- **Feature requests** — Users wishing for capabilities that don't exist yet

### How does the scoring system work?

Opportunities are scored on a 0-100 scale across five dimensions:
- Intent weight (how valuable is the intent type)
- Confidence multiplier (how certain is the classification)
- Engagement weight (Reddit upvotes as community validation)
- Signal boost (bonus for high-value signals like help requests)
- Urgency detection (bonus for time-sensitive language)

Scores map to priority labels: Hot (80+), Warm (60-79), Cold (30-59), Ignore (<30).

### Does SignalForge auto-post responses?

No. SignalForge follows a strict human-in-the-loop model. AI drafts response suggestions, but a human team member must review and approve every response before it is posted. This ensures quality, authenticity, and compliance.

### What LLM providers are supported?

SignalForge supports multiple LLM providers through a swappable abstraction layer:
- **Google Gemini** (primary, production-ready)
- **OpenAI GPT** (planned)
- **Anthropic Claude** (planned)

## Technical

### How is product knowledge managed?

SignalForge uses a RAG (Retrieval-Augmented Generation) architecture. Product documentation is chunked, embedded, and stored in a ChromaDB vector database. When drafting responses, the system retrieves the most relevant knowledge chunks to inform the AI's output.

### What about data privacy?

All data processing happens locally or within your configured cloud environment. Reddit data is processed in-memory and only engagement-relevant metadata is cached. No user data is sent to external services beyond the configured LLM API for text generation.

### Can I customize the scoring weights?

Yes. The scoring engine uses a configurable `ScoringConfig` dataclass where you can adjust intent weights, engagement scaling, signal boost values, urgency bonus, and priority label thresholds.

### How does deduplication work?

SignalForge maintains a JSON-backed cache of all previously seen post IDs. Posts that have already been processed are automatically skipped in subsequent scans, preventing duplicate engagement.

## Benefits

### Why use SignalForge instead of manual Reddit engagement?

- **Time savings** — Reduces 4+ hours of daily manual scanning to minutes
- **Consistency** — Ensures no high-value conversation is missed
- **Quality** — AI-assisted drafts maintain brand voice consistency
- **Compliance** — Automated checks prevent guideline violations
- **Scale** — Monitor unlimited subreddits and keywords simultaneously
- **Measurability** — Track engagement ROI with analytics
