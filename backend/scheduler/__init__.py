"""Background scheduling loops: the retry sweep (this milestone) and,
eventually, the cron-schedule trigger loop. These run inside the backend
FastAPI process via app.main's lifespan, not as a separate container --
matching the container list decided back in Step 1, which never included a
standalone "scheduler" service.
"""