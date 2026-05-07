#!/usr/bin/env python3
"""
SignalForge Production Entrypoint.

Supports multiple boot modes:
  --mode scheduler  : Runs the continuous background task scheduler
  --mode ui         : Boots the Streamlit web interface
  --mode cli        : Runs a one-off pipeline execution (requires --query)
"""

import argparse
import logging
import subprocess
import sys
import time

from config.settings import Settings

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(name)-32s | %(levelname)-7s | %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger("signalforge.startup")


def boot_scheduler():
    """Boot the background task scheduler in a continuous loop."""
    logger.info("Booting SignalForge Scheduler...")
    from scheduler.task_scheduler import TaskScheduler
    scheduler = TaskScheduler()
    
    logger.info("Scheduler running. Polling for tasks...")
    try:
        while True:
            results = scheduler.run_all_pending()
            for res in results:
                logger.info(
                    "Scheduler executed task %s - success=%s, status=%s",
                    res.get("task_id"), res.get("success"), res.get("status")
                )
            # Sleep before next poll
            time.sleep(60)
    except KeyboardInterrupt:
        logger.info("Scheduler gracefully shutting down.")


def boot_ui():
    """Boot the Streamlit UI."""
    logger.info("Booting SignalForge Streamlit UI...")
    cmd = ["streamlit", "run", "ui/app.py", "--server.port", "8501", "--server.address", "0.0.0.0"]
    try:
        subprocess.run(cmd, check=True)
    except KeyboardInterrupt:
        logger.info("UI gracefully shutting down.")


def boot_cli(query):
    """Run a one-off CLI execution."""
    if not query:
        logger.error("--query is required for cli mode.")
        sys.exit(1)
    
    logger.info("Booting SignalForge CLI mode...")
    from run_signalforge import run_pipeline
    run_pipeline(query)


def main():
    parser = argparse.ArgumentParser(description="SignalForge Entrypoint")
    parser.add_argument("--mode", choices=["scheduler", "ui", "cli"], default="scheduler", help="Boot mode")
    parser.add_argument("--query", "-q", help="Query string (for cli mode)")
    args = parser.parse_args()

    # Validate essential environment variables before starting
    try:
        settings = Settings()
        settings.validate_all()
        logger.info("Environment configuration validated successfully.")
    except EnvironmentError as e:
        logger.error("Configuration Error: %s", e)
        sys.exit(1)

    if args.mode == "scheduler":
        boot_scheduler()
    elif args.mode == "ui":
        boot_ui()
    elif args.mode == "cli":
        boot_cli(args.query)


if __name__ == "__main__":
    main()
