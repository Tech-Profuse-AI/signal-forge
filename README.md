# SignalForge

SignalForge is an AI-driven platform for discovering, classifying, and engaging with social media opportunities (primarily Reddit). It leverages LangGraph, LangChain, and advanced LLMs (Gemini, OpenAI, Anthropic) to detect actionable intent (e.g., buying, hiring, churn risk) and formulate brand-aligned responses.

## Project Structure

```
SignalForge/
├── agents/               # Intelligent agents (IntentAgent, OpportunityScanner)
├── config/               # Configuration management & brand guidelines
├── knowledge/            # Persistent knowledge bases (vector stores, context)
├── prompts/              # System prompts for various LLM agents
├── providers/            # External service providers (LLMs, Reddit/PRAW)
├── tests/                # Test suites (pytest)
├── workflows/            # LangGraph workflow orchestration
├── main.py               # Application entry point and phase initialisation runner
├── requirements.txt      # Project dependencies
└── .env.example          # Example environment variables
```

## Features

- **Multi-LLM Support:** Built-in abstraction to swap seamlessly between Google Gemini, OpenAI, and Anthropic (`providers/llm_provider.py`).
- **Reddit Integration:** Configurable PRAW-based integration to scan subreddits for relevant keywords and discussions (`providers/reddit_provider.py`).
- **Brand Guidelines Enforcer:** Validates engagement against configurable rules, voice, and guardrails to ensure brand consistency (`config/brand_guidelines.py`).
- **Opportunity Scanning:** Actively monitors configured data sources to surface potential leads (`agents/opportunity_scanner/`).
- **Intent Classification:** Deterministic JSON-schema parsing to classify user intent into structured, actionable categories (`agents/intent_agent.py`).

## Setup Instructions

1. **Clone the repository:**
   ```bash
   git clone https://github.com/SH-Nihil-Mukkesh-25/signal-forge.git
   cd signal-forge
   ```

2. **Set up a Virtual Environment:**
   ```bash
   python -m venv venv
   # On Windows use:
   venv\Scripts\activate
   # On macOS/Linux use:
   # source venv/bin/activate
   ```

3. **Install Dependencies:**
   ```bash
   pip install -r requirements.txt
   ```

4. **Environment Variables:**
   Copy the example environment file and fill in your keys:
   ```bash
   cp .env.example .env
   ```
   *Required variables include your chosen LLM API keys (`GEMINI_API_KEY`, etc.) and Reddit API credentials (`REDDIT_CLIENT_ID`, `REDDIT_CLIENT_SECRET`).*

5. **Run the Initialization Check:**
   Verify your foundation configuration:
   ```bash
   python main.py
   ```

## Testing

The project uses `pytest` for testing functionality.
```bash
pytest tests/
```

Test coverage includes:
- `test_phase1.py` - Core foundational elements.
- `test_opportunity_scanner.py` - Reddit scanning validation.
- `test_intent_agent.py` - AI intent classification logic using mock Reddit posts.
