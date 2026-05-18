"""
SignalForge Settings — centralized environment-driven configuration.

Loads all required environment variables from a .env file using python-dotenv.
Raises clear errors at startup if critical keys are missing, so failures
surface immediately rather than deep inside a pipeline run.
"""

import os
import logging
from pathlib import Path
from typing import Optional
from dotenv import load_dotenv

logger = logging.getLogger("signalforge.config")


class Settings:
    """
    Singleton-style settings loader.

    Usage:
        settings = Settings()          # loads .env from project root
        key = settings.gemini_api_key   # access individual keys
    """

    _instance: Optional["Settings"] = None

    def __new__(cls, env_path: Optional[str] = None) -> "Settings":
        """Return the existing instance if already initialised."""
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self, env_path: Optional[str] = None) -> None:
        if self._initialized:
            return

        # Resolve .env path — default: project root
        if env_path is None:
            env_path = str(Path(__file__).resolve().parent.parent / ".env")

        if not Path(env_path).exists():
            logger.warning(
                ".env file not found at %s — falling back to system env vars",
                env_path,
            )
        else:
            load_dotenv(dotenv_path=env_path, override=False)
            logger.info("Loaded environment from %s", env_path)

        # ── LLM Provider ──────────────────────────────────────────────
        self.llm_provider: str = os.getenv("LLM_PROVIDER", "gemini").lower()
        self.gemini_api_key: str = os.getenv("GEMINI_API_KEY", "")
        self.openai_api_key: str = os.getenv("OPENAI_API_KEY", "")
        self.anthropic_api_key: str = os.getenv("ANTHROPIC_API_KEY", "")

        # ── Reddit (PRAW) ─────────────────────────────────────────────
        self.reddit_client_id: str = os.getenv("REDDIT_CLIENT_ID", "")
        self.reddit_client_secret: str = os.getenv("REDDIT_CLIENT_SECRET", "")
        self.reddit_user_agent: str = os.getenv(
            "REDDIT_USER_AGENT", "SignalForge/1.0"
        )

        # ── Slack ─────────────────────────────────────────────────────
        self.slack_bot_token: str = os.getenv("SLACK_BOT_TOKEN", "")

        # ── Medium (Integration API) ─────────────────────────────────
        self.medium_integration_token: str = os.getenv(
            "MEDIUM_INTEGRATION_TOKEN", ""
        )
        self.medium_user_id: str = os.getenv("MEDIUM_USER_ID", "")
        self.medium_publish_status: str = os.getenv(
            "MEDIUM_PUBLISH_STATUS", "draft"
        ).lower()
        self.medium_content_format: str = os.getenv(
            "MEDIUM_CONTENT_FORMAT", "markdown"
        ).lower()

        # ── Supabase (Phase 25 Persistence) ──────────────────────────
        self.supabase_url: str = os.getenv("SUPABASE_URL", "")
        self.supabase_key: str = os.getenv("SUPABASE_KEY", "")

        # Scanner data-quality controls
        self.cache_max_age_days: int = int(os.getenv("CACHE_MAX_AGE_DAYS", "7"))
        self.clear_cache_on_boot: bool = (
            os.getenv("CLEAR_CACHE_ON_BOOT", "false").lower()
            in {"1", "true", "yes", "on"}
        )
        self.test_mode: bool = (
            os.getenv("TEST_MODE", "false").lower()
            in {"1", "true", "yes", "on"}
        )

        self._initialized = True
        logger.info(
            "Settings initialised — LLM provider: %s", self.llm_provider
        )

    # ── Validation helpers ────────────────────────────────────────────

    def validate_llm(self) -> None:
        """Raise if the selected LLM provider key is missing."""
        key_map = {
            "gemini": self.gemini_api_key,
            "openai": self.openai_api_key,
            "anthropic": self.anthropic_api_key,
        }
        key = key_map.get(self.llm_provider)
        if not key:
            raise EnvironmentError(
                f"API key for LLM provider '{self.llm_provider}' is not set. "
                "Check your .env file."
            )

    def validate_reddit(self) -> None:
        """Raise if Reddit credentials are missing."""
        missing = []
        if not self.reddit_client_id:
            missing.append("REDDIT_CLIENT_ID")
        if not self.reddit_client_secret:
            missing.append("REDDIT_CLIENT_SECRET")
        if missing:
            raise EnvironmentError(
                f"Missing Reddit credentials: {', '.join(missing)}. "
                "Check your .env file."
            )

    def validate_slack(self) -> None:
        """Raise if Slack bot token is missing."""
        if not self.slack_bot_token:
            raise EnvironmentError(
                "SLACK_BOT_TOKEN is not set. Check your .env file."
            )

    def validate_all(self) -> None:
        """Run every validation check."""
        self.validate_llm()
        self.validate_reddit()
        self.validate_slack()

    @classmethod
    def reset(cls) -> None:
        """Reset the singleton (useful for testing)."""
        cls._instance = None

    def __repr__(self) -> str:
        return (
            f"<Settings llm_provider='{self.llm_provider}' "
            f"reddit_configured={bool(self.reddit_client_id)} "
            f"slack_configured={bool(self.slack_bot_token)}>"
        )
