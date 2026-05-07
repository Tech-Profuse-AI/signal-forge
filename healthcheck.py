#!/usr/bin/env python3
"""
SignalForge Healthcheck.

Validates:
- Supabase connectivity
- Firecrawl availability
- Medium token presence
- Slack connectivity

Returns 0 if healthy, 1 otherwise. Suitable for Docker HEALTHCHECK.
"""

import json
import logging
import sys
import urllib.request
from typing import Dict, Any

from config.settings import Settings
from storage.supabase_store import get_supabase_client_from_settings

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger("healthcheck")


def test_supabase(settings: Settings) -> bool:
    """Test Supabase connectivity via ping()."""
    try:
        client = get_supabase_client_from_settings(settings)
        if not client.is_configured():
            logger.warning("Supabase is not configured.")
            return True # Best effort pipeline allows missing Supabase
        
        if client.ping():
            logger.info("Supabase: OK")
            return True
        else:
            logger.error("Supabase: FAILED (ping returned False)")
            return False
    except Exception as e:
        logger.error("Supabase: FAILED (%s)", e)
        return False


def test_firecrawl(settings: Settings) -> bool:
    """Test Firecrawl API availability."""
    if not settings.supabase_url: # Firecrawl is phase 24, fallback exists.
        pass
    api_key = getattr(settings, "firecrawl_api_key", None)
    if not api_key:
        from os import getenv
        api_key = getenv("FIRECRAWL_API_KEY")
        
    if not api_key:
        logger.info("Firecrawl: Skipped (Not configured, fallback mode active)")
        return True

    body = json.dumps({"query": "healthcheck", "limit": 1}).encode("utf-8")
    req = urllib.request.Request(
        "https://api.firecrawl.dev/v1/search",
        method="POST",
        data=body,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }
    )
    
    try:
        urllib.request.urlopen(req, timeout=5)
        logger.info("Firecrawl: OK")
        return True
    except urllib.error.HTTPError as e:
        # 401/400/405/422 still means the API is available and responding
        if e.code in (401, 400, 405, 422):
            logger.info("Firecrawl: OK (API reachable)")
            return True
        logger.error("Firecrawl: FAILED (HTTP %s)", e.code)
        return False
    except Exception as e:
        logger.error("Firecrawl: FAILED (%s)", e)
        return False


def test_medium(settings: Settings) -> bool:
    """Validate Medium configuration presence."""
    token = settings.medium_integration_token
    if not token:
        logger.warning("Medium: Skipped (Not configured)")
        return True
        
    logger.info("Medium: OK (Token present)")
    return True


def test_slack(settings: Settings) -> bool:
    """Test Slack connectivity."""
    token = settings.slack_bot_token
    if not token:
        logger.warning("Slack: Skipped (Not configured)")
        return True
        
    req = urllib.request.Request(
        "https://slack.com/api/auth.test",
        headers={"Authorization": f"Bearer {token}"},
        method="POST"
    )
    try:
        with urllib.request.urlopen(req, timeout=5) as response:
            data = json.loads(response.read().decode())
            if data.get("ok"):
                logger.info("Slack: OK")
                return True
            else:
                logger.error("Slack: FAILED (auth.test returned %s)", data.get("error"))
                return False
    except Exception as e:
        logger.error("Slack: FAILED (%s)", e)
        return False


def main():
    logger.info("Running SignalForge Healthcheck...")
    settings = Settings()
    
    checks = [
        test_supabase(settings),
        test_firecrawl(settings),
        test_medium(settings),
        test_slack(settings),
    ]
    
    if all(checks):
        logger.info("Healthcheck PASSED.")
        sys.exit(0)
    else:
        logger.error("Healthcheck FAILED.")
        sys.exit(1)


if __name__ == "__main__":
    main()
