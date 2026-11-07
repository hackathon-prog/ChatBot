# LMS Analytics Chatbot

FastAPI + Claude tool use. Answers analytics questions only, via validated read-only SQL.

## Run

```
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt
copy .env.example .env        # set ANTHROPIC_API_KEY
.venv\Scripts\python -m app.seed   # sample data (skip if using your own DB)
.venv\Scripts\python run.py        # http://127.0.0.1:8000
.venv\Scripts\python -m pytest
```

## Use your real LMS

1. Set `DATABASE_URL` to a **read-only** DB user (SQLite is opened read-only automatically).
2. Add sensitive column names to `BLOCKED_COLUMNS`. They are hidden from the model and rejected in queries.
3. Schema is introspected at startup, so no code change is needed.

## Safety layers

- System prompt limits scope to LMS analytics.
- `app/sql_guard.py`: single SELECT/WITH only, no comments, no write keywords, blocked columns.
- Row cap on every query (`MAX_ROWS`), read-only connection.
- UI renders replies with `textContent` (no HTML injection).
