#!/usr/bin/env python3
"""
SignalForge Slack Webhook Server.

Runs the FastAPI app that handles interactive Slack actions
(approve / edit / reject) from review cards.

Usage:
    python main_webhook.py
"""

import sys
from pathlib import Path

# Ensure project root is on sys.path
PROJECT_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(PROJECT_ROOT))

import uvicorn
from integrations.slack_webhook import app

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8080)
