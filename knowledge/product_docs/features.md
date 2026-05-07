# SignalForge — Features

## Opportunity Discovery

SignalForge's OpportunityScannerAgent continuously monitors Reddit for high-value engagement opportunities.

**Capabilities:**
- Keyword-based scanning across multiple subreddits simultaneously
- Smart filtering that rejects deleted posts, memes, bot spam, and low-effort content
- Signal detection for help requests, recommendation asks, pain-point discussions, and workflow bottleneck posts
- Deduplication cache to prevent re-surfacing previously seen opportunities
- Configurable thresholds for minimum score and body length
- Support for both live Reddit API (PRAW) and mock data modes

## Intent Classification

The IntentAgent uses LLM-powered analysis to classify each discovered opportunity into actionable categories.

**Supported intent types:**
- **Buying Intent** — User actively seeking tools or products to purchase
- **Problem Intent** — User experiencing workflow pain or operational challenges
- **Hiring Intent** — User looking for people, agencies, or service providers
- **Competitor Mention** — User discussing or comparing competitor tools and platforms
- **Feature Request** — User expressing desire for missing functionality
- **Churn Risk** — User frustrated with current tools and considering alternatives
- **Ignore** — Not actionable for engagement

**Technical details:**
- Deterministic prompt design for consistent JSON output
- Confidence scoring between 0.0 and 1.0
- Business relevance assessment for each classification
- Recommended action suggestions (respond, monitor, escalate, skip)

## Priority Scoring

The OpportunityScoringAgent ranks classified opportunities by business value.

**Scoring dimensions (0-100 scale):**
- Intent weight — Higher scores for buying intent and churn risk
- Confidence multiplier — Scales by LLM classification certainty
- Engagement weight — Reddit upvotes indicate community validation
- Signal boost — Bonus for help requests, pain points, recommendations, bottlenecks
- Urgency detection — Bonus for time-sensitive language (urgent, ASAP, stuck)

**Priority labels:**
- **Hot (80+)** — Respond immediately, high business value
- **Warm (60-79)** — Respond soon, strong potential
- **Cold (30-59)** — Monitor, may become actionable
- **Ignore (<30)** — Skip, not worth pursuing

## Draft Generation (Coming Soon)

AI-powered response drafting that matches subreddit culture and brand voice.

**Planned capabilities:**
- RAG-powered context retrieval from product knowledge base
- Subreddit tone matching
- Brand guideline enforcement
- Multiple draft variations for human selection

## Compliance Checks (Coming Soon)

Automated review of all drafted responses against brand and platform rules.

**Planned checks:**
- Reddit self-promotion ratio compliance
- Subreddit-specific rule adherence
- Brand voice consistency
- Prohibited content filtering
- Link and disclosure requirements

## Slack Human-in-the-Loop (Coming Soon)

Interactive approval workflow via Slack for draft review.

**Planned capabilities:**
- Opportunity notification cards with context
- One-click approve/reject/edit workflow
- Feedback loop for improving future drafts
- Team assignment and escalation rules
