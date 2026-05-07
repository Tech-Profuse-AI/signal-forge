# SignalForge Deployment Guide

This guide outlines how to deploy the SignalForge system (Phase 26) to modern cloud platforms like Railway or Render, utilizing Docker and a unified entrypoint.

## Overview
SignalForge is containerized using `Dockerfile` and orchestrated via `docker-compose.yml`. 
The `start.py` entrypoint allows you to boot the system in three different modes:
- `--mode scheduler` (Default): Runs the continuous background task scheduler for processing pending pipeline workflows.
- `--mode ui`: Boots the internal Streamlit dashboard (exposed on port 8501).
- `--mode cli`: Runs a one-off pipeline execution (requires passing `--query`).

## Environment Variables
Before deploying, ensure you have set up the following environment variables. Do not commit `.env` to version control. Reference `.env.example` for a complete list.

### Required Secrets
- `LLM_PROVIDER`: `gemini` (or `openai`, `anthropic`)
- `GEMINI_API_KEY`: Your Gemini API key
- `SUPABASE_URL`: Your Supabase project REST URL
- `SUPABASE_KEY`: Your Supabase API key (anon/publishable key is sufficient for current RLS setup)
- `SLACK_BOT_TOKEN`: The `xoxb-` token for human-in-the-loop review queues
- `REDDIT_CLIENT_ID` / `REDDIT_CLIENT_SECRET` / `REDDIT_USER_AGENT`: Reddit API credentials

### Optional / Integration Secrets
- `FIRECRAWL_API_KEY`: API key for advanced Quora link scraping (Phase 24)
- `MEDIUM_INTEGRATION_TOKEN` / `MEDIUM_USER_ID`: Required only if publishing to Medium
- `SIGNALFORGE_PUBLISH_MODE`: Usually `dry_run` for testing, or `live` for actual posting

---

## Deploying to Railway

Railway natively supports Dockerfile deployments.

1. **Connect Repository:** Link your GitHub repository to a new Railway project.
2. **Environment Variables:** Navigate to the "Variables" tab and bulk-import your `.env` contents.
3. **Start Command:** Railway will automatically use the `CMD` defined in the `Dockerfile` (`python start.py --mode scheduler`).
   - If you want to deploy the **Streamlit UI** alongside it, create a second service from the same repo and override the Custom Start Command to: `python start.py --mode ui`.
4. **Healthchecks:** Railway automatically monitors the container's health based on the ports exposed, but you can explicitly configure Healthchecks in the service settings to run `python healthcheck.py`.

---

## Deploying to Render

Render supports background workers and web services natively.

1. **New Web Service (For UI):**
   - **Environment:** Docker
   - **Start Command:** `python start.py --mode ui`
   - **Environment Variables:** Add your secrets in the Render dashboard.
2. **New Background Worker (For Scheduler):**
   - **Environment:** Docker
   - **Start Command:** `python start.py --mode scheduler`
   - **Environment Variables:** Add your secrets.

Render handles continuous deployment automatically when you push to your configured branch.

---

## Health Checks

The system ships with a robust `healthcheck.py` script that validates internal configuration and external API connectivity (Supabase ping, Firecrawl reachability, Slack auth). 

**Usage inside container:**
```bash
python healthcheck.py
```
This script returns a `0` exit code if all external services are reachable and configured, or a `1` if the system is unhealthy, making it fully compatible with Docker `HEALTHCHECK` instructions.

## Local Testing

You can simulate the production environment locally using Docker Compose:

```bash
docker-compose up --build
```
This will boot both the scheduler worker and the Streamlit UI, mimicking a full cloud deployment.
