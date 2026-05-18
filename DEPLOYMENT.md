# SignalForge Deployment Guide

This guide outlines how to deploy the SignalForge system (Phase 26) to modern cloud platforms like Railway or Render, utilizing Docker and a unified entrypoint.

## Overview
SignalForge is containerized using `Dockerfile` and orchestrated via `docker-compose.yml`. 
The `start.py` entrypoint allows you to boot the legacy system components, but with the introduction of the modern React frontend, the architecture now typically consists of two main services:
- **API Backend**: FastAPI application exposing the pipeline and queue (`uvicorn api.main:app`).
- **Static Frontend**: A compiled Vite + React application.
- **Background Scheduler**: Continuous background task scheduler (`python start.py --mode scheduler`).

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

Railway natively supports Dockerfile deployments as well as static site builds.

1. **API Backend**:
   - Create a service from the GitHub repository.
   - Set the Custom Start Command to: `uvicorn api.main:app --host 0.0.0.0 --port $PORT`
   - Bulk-import your `.env` contents in the Variables tab.

2. **Frontend Dashboard**:
   - Create another service pointing to the `frontend/` directory of the repo.
   - Build Command: `npm run build`
   - Start Command: `npm run preview` (or host it as a static site).
   - Ensure the frontend can communicate with the backend by setting API base URL variables.

3. **Background Scheduler**:
   - Create a third service from the repo.
   - Start Command: `python start.py --mode scheduler`
   - Supply the same environment variables as the backend.

---

## Deploying to Render

Render supports background workers, web services, and static sites natively.

1. **API Web Service (Backend):**
   - **Environment:** Docker or Python
   - **Start Command:** `uvicorn api.main:app --host 0.0.0.0 --port $PORT`
   - **Environment Variables:** Add your secrets in the Render dashboard.

2. **Static Site (Frontend):**
   - **Environment:** Static Site
   - **Build Command:** `cd frontend && npm install && npm run build`
   - **Publish Directory:** `frontend/dist`

3. **Background Worker (Scheduler):**
   - **Environment:** Docker or Python
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

You can simulate the production environment locally using the CLI:

```bash
# Start the API
uvicorn api.main:app --reload --port 8000

# Start the Frontend
cd frontend
npm run dev
```

Alternatively, use the existing Docker setup for the backend services.
