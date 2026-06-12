# Deploying the demo (Railway)

The image is portable — nothing below is Railway-specific beyond the dashboard
steps. Any container host (Fly, Render, a VM) runs the same `Dockerfile`.

## 1. What ships

- `Dockerfile` — `python:3.12-slim`, installs `requirements.txt`, serves
  `uvicorn src.server.app:app` on `$PORT` (Railway sets it; defaults to 8000).
- `railway.json` — tells Railway to build from the Dockerfile, health-check
  `/health`, and restart on failure.
- `Procfile` — same start command for buildpack-style hosts.

## 2. Required environment variables

Set these in the Railway service (Variables tab). See `.env.example` for the
full annotated list.

| Variable | Required | Purpose |
|---|---|---|
| `ANTHROPIC_API_KEY` | **yes** | Model access. Set a hard spend limit on this key in the Anthropic console. |
| `DEMO_TOKEN` | recommended | If set, session endpoints require `X-Demo-Token`. Leave unset only for a fully open demo. |
| `DEMO_SESSION_USD_CAP` | no (default 1.00) | Per-session cost cap; the session ends gracefully when crossed. |
| `DEMO_DAILY_USD_CAP` | no (default 20.00) | Daily global spend cap; session endpoints return "budget exhausted" when crossed. |
| `DEMO_RATE_LIMIT_PER_HOUR` | no (default 5) | Per-IP new-session limit. |
| `ADAPTIVE_LEARNING_MAX_STEPS` | no (default 10) | Agent-loop iteration cap. |
| `LANGSMITH_TRACING` + `LANGSMITH_API_KEY` | no | Set both to enable LangSmith tracing (config-only; no code change). |

## 3. Persistence

The learner/graph store and the daily-spend counter live under
`ADAPTIVE_LEARNING_STORE_DIR` (default `/data/store` in the image). Attach a
Railway **volume** mounted at `/data` so learner progress and the day's spend
survive restarts. Without a volume the demo still runs, but state resets on
every deploy.

## 4. Deploy steps

1. Create a Railway project from this GitHub repo (Deploy from repo).
2. Railway detects `railway.json` and builds the Dockerfile.
3. Add the environment variables above.
4. (Optional) Add a volume at `/data`.
5. Deploy. Smoke-test:
   ```bash
   curl https://<your-app>.up.railway.app/health         # {"status":"ok"}, open
   curl -X POST https://<your-app>.up.railway.app/sessions/start \
     -H "Content-Type: application/json" \
     -H "X-Demo-Token: <DEMO_TOKEN>" \
     -d '{"user_id":"demo","domain_id":"cognitive_biases"}'
   ```
   Visit `/visual` for the live walkthrough page (open, no token).

## 5. Guard behaviour at a glance

- **No token** on a protected endpoint when `DEMO_TOKEN` is set → `401` with a
  friendly message. `/health` and `/visual` are always open.
- **Daily cap reached** → session endpoints return `429 demo_budget_exhausted`
  until 00:00 UTC.
- **Per-IP limit reached** → `429 rate_limited`.
- **Per-session cap reached** → the next `respond` returns
  `status: session_budget_reached` instead of generating another artifact.
