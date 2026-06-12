# Deploying the demo (Fly.io)

The image is portable — nothing below is Fly-specific beyond the `flyctl`
commands. Any container host (Railway, Render, a VM) runs the same
`Dockerfile`; `railway.json` and `Procfile` are kept for those hosts.

## 1. What ships

- `Dockerfile` — `python:3.12-slim`, installs `requirements.txt`, serves
  `uvicorn src.server.app:app` on `$PORT` (defaults to 8000; Fly talks to it
  on 8000 directly).
- `fly.toml` — app config: Dockerfile build, `/health` check, a volume at
  `/data`, scale-to-zero machines (`min_machines_running = 0`).
- `railway.json` / `Procfile` — equivalent config for Railway / buildpack
  hosts, unused on Fly.

## 2. Required environment variables

Set secrets with `fly secrets set` (step 4 below). See `.env.example` for the
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
`ADAPTIVE_LEARNING_STORE_DIR` (default `/data/store` in the image).
`fly.toml` mounts a Fly **volume** named `data` at `/data` so learner progress
and the day's spend survive restarts and deploys. Without the volume the demo
still runs, but state resets on every deploy.

## 4. Deploy steps

```bash
fly auth login                                   # one-time
fly apps create adaptive-learning-2
fly volumes create data --region ord --size 1 --app adaptive-learning-2
fly secrets set --app adaptive-learning-2 \
  ANTHROPIC_API_KEY=sk-ant-... \
  DEMO_TOKEN=<generate one: openssl rand -hex 16>
fly deploy
```

Smoke-test:

```bash
curl https://adaptive-learning-2.fly.dev/health       # {"status":"ok"}, open
curl -X POST https://adaptive-learning-2.fly.dev/sessions/start \
  -H "Content-Type: application/json" \
  -H "X-Demo-Token: <DEMO_TOKEN>" \
  -d '{"user_id":"demo","domain_id":"cognitive_biases"}'
```

Visit `/visual` for the live walkthrough page (open, no token).

Machines scale to zero when idle (`auto_stop_machines = 'stop'`), so the first
request after a quiet period takes a few seconds while a machine boots.

## 5. Guard behaviour at a glance

- **No token** on a protected endpoint when `DEMO_TOKEN` is set → `401` with a
  friendly message. `/health` and `/visual` are always open.
- **Daily cap reached** → session endpoints return `429 demo_budget_exhausted`
  until 00:00 UTC.
- **Per-IP limit reached** → `429 rate_limited`.
- **Per-session cap reached** → the next `respond` returns
  `status: session_budget_reached` instead of generating another artifact.
