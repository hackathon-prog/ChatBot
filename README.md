# LMS Analytics Chatbot

FastAPI + OpenRouter (tool calling). Answers analytics questions only, via validated read-only SQL.
Used by the JDK Learning System admin page (Analytics). Administrators only.

## API (backend only, no web page)

| Method | Path | Purpose |
| --- | --- | --- |
| POST | `/api/chat` | Ask an analytics question |
| GET | `/api/health` | Liveness check |

```
POST /api/chat
Authorization: Bearer <Supabase access token>     (not needed when REQUIRE_AUTH=false)
{"messages": [{"role": "user", "content": "Completion rate by course"}]}

200 {"reply": "..."}
401 not signed in | 403 not an admin | 429 rate limit | 502 AI service problem
```

Send the full conversation in `messages` (max 30, last one from the user). The service keeps no state.
Set `CORS_ORIGINS` to the origins of your frontend.

## Run locally with the sample data

```
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt
copy .env.example .env             # set OPENROUTER_API_KEY, keep REQUIRE_AUTH=false
.venv\Scripts\python -m app.seed   # sample SQLite data
.venv\Scripts\python run.py        # http://127.0.0.1:8000
.venv\Scripts\python -m pytest
```

## Connect it to the real JDK Learning System (Supabase)

1. In the Supabase SQL Editor run `LearningManagementSystem/supabase_analytics.sql`.
   It creates a schema `analytics` with anonymous, read-only views and a role `analytics_ro`.
   No email, display name or notes are exposed. Learners appear only as an 8 character `learner_ref`.
2. Set a password for the role (in the SQL Editor, not in a file):
   `alter role analytics_ro with login password '<long random password>';`
3. In Supabase press **Connect**, copy the **Session pooler** connection string, and use the user
   `analytics_ro.<project-ref>`. In `.env`:
   ```
   DATABASE_URL=postgresql+psycopg://analytics_ro.<project-ref>:<password>@<pooler-host>:5432/postgres
   DB_SCHEMA=analytics
   REQUIRE_AUTH=true
   SUPABASE_URL=https://<project-ref>.supabase.co
   SUPABASE_ANON_KEY=<public anon key only>
   CORS_ORIGINS=http://localhost:5173,https://<your-app>.vercel.app
   ```
4. Start the service. In the app's `.env` set `VITE_CHATBOT_URL=<where the service runs>` and rebuild.
5. Log in as an administrator and open **Analytics** in the sidebar.

To make someone an administrator, run in the SQL Editor (the app cannot do this):
`update public.profiles set role = 'admin' where id = (select id from auth.users where email = '<their email>');`

## Who can use it

Every request must carry the caller's Supabase access token. The service asks Supabase who the caller is and
reads their own profile row with that token. Only `role = 'admin'` is let in. Learners get 403, missing or
bad tokens get 401. Only the public anon key is used. Never give this service the `service_role` key.
There is also a per-user limit (`REQUESTS_PER_MINUTE`, default 12) to keep model costs predictable.

## Safety layers

- System prompt limits scope to LMS analytics and tells the model never to identify learners.
- Database: dedicated role with `SELECT` on the analytics views only, read-only session, 5 second statement limit.
- `app/sql_guard.py`: single SELECT/WITH only, no comments, no write keywords, no Postgres internals
  (`pg_*`, `information_schema`, `set_config`, `current_setting`), blocked columns.
- Row cap on every query (`MAX_ROWS`).
- The app shows replies as plain text (no HTML injection).

## Limits

- Results come from small samples: a module quiz has 3 questions per competency.
- Not tested against a live Supabase database or the live OpenRouter API from here: the tests use a scripted
  model, a mocked Supabase, SQLite, and an in-memory Postgres for the SQL views.
- The service needs hosting that runs Python (not Vercel static hosting).
