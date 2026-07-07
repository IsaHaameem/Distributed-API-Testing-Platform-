# Distributed API Testing & Monitoring Platform

A distributed backend platform for scheduling, executing, and monitoring API test runs
across a pool of stateless workers — a self-built, lightweight combination of Postman,
k6, Locust, and UptimeRobot, focused on the distributed-systems mechanics rather than the UI.

## Stack

- **Backend:** FastAPI, SQLAlchemy 2.0 (async), Alembic, Pydantic v2
- **Execution:** Redis Streams-backed worker pool, HTTPX, asyncio
- **Database:** PostgreSQL
- **Frontend:** Next.js, React, TypeScript, Tailwind, Recharts (added later)
- **Monitoring:** Prometheus, Grafana (added later)
- **Testing:** pytest, Locust

## Status

Built incrementally, milestone by milestone. Current state: **Step 2 — base project
structure and a working health-check skeleton** (FastAPI + PostgreSQL + Redis, wired
end-to-end in Docker Compose).

## Prerequisites

- Docker Desktop (with Compose)
- Python 3.13 (only needed for local editor support, not for running anything)

## Running locally

1. Copy the environment template:

```powershell
   Copy-Item .env.example .env
```

2. Build and start the stack:

```powershell
   docker compose up --build
```

3. Check the health endpoint:

```powershell
   Invoke-RestMethod -Uri "http://localhost:8000/health"
```

   A healthy stack returns `{"status": "ok", "database": "ok", "redis": "ok"}`.

## Running tests

```powershell
docker compose exec backend pytest -v
```

## Project layout

- `backend/app/` — FastAPI application
- `backend/worker/` — distributed worker process (Step 7)
- `backend/scheduler/` — cron and retry-requeue loops (Step 10)
- `frontend/` — Next.js dashboard (Step 12)
- `monitoring/` — Prometheus and Grafana configuration (Step 11)