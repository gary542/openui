# Deploying OpenUI on Vercel (Hobby) with Supabase

This fork adds a serverless mode: FastAPI as one Vercel Function, Postgres
(Supabase) instead of SQLite, a single-owner session instead of GitHub OAuth, and
no Ollama / LiteLLM sidecar. The default local / Docker behaviour is unchanged.

## Vercel project

| Setting | Value |
| --- | --- |
| Git repo / branch | `gary542/openui`, branch `feat/vercel-supabase` |
| Root Directory | `backend` |
| Framework preset | FastAPI (entrypoint `backend/app.py`, `vercel.json` sets `maxDuration` 300 and region `lhr1`) |
| Deployment Protection | **Vercel Authentication → All Deployments** (this is what keeps the app private) |

The frontend is served from the committed `backend/openui/dist` (as upstream does).
Set `OPENUI_BUILD_FRONTEND=1` to rebuild it from `frontend/` during the Vercel build
instead (`backend/build.py`).

## Environment variables

Required:

| Name | Notes |
| --- | --- |
| `DATABASE_URL` | Supabase **transaction pooler** URI (port 6543), e.g. `postgresql://postgres.<ref>:<password>@aws-0-<region>.pooler.supabase.com:6543/postgres?sslmode=require`. Percent-encode special characters in the password. |
| `OPENUI_SESSION_KEY` | Random secret that signs the session cookie (`python -c "import secrets; print(secrets.token_hex(32))"`). The app refuses to start without it. |
| `OPENAI_COMPATIBLE_API_KEY` | DeepSeek API key (the default provider on Vercel). `OPENAI_API_KEY` is **not** needed. |
| `OPENAI_COMPATIBLE_ENDPOINT` | Defaults to `https://api.deepseek.com`; set it for any other OpenAI-compatible provider. |
| `OPENUI_ENVIRONMENT` | `production` (Secure cookies, usage quota enforced) |
| `OPENUI_SINGLE_USER` | `true` – every browser session is the owner account; GitHub login is disabled. **Only use behind Vercel Authentication.** |
| `OPENUI_HOST` | `https://<project>.vercel.app` (or your custom domain) |

Models: with `OPENAI_COMPATIBLE_API_KEY` set and LiteLLM off (serverless), OpenUI calls
the endpoint directly and lists `OPENUI_COMPATIBLE_MODELS` (default
`deepseek-flash,deepseek-v4-pro`, per the current DeepSeek docs) in the model picker
(under the "LiteLLM" heading). With no OpenAI key the UI defaults to the first of them.
DeepSeek thinking mode is off by default for faster streaming
(`OPENUI_COMPATIBLE_THINKING=true` turns it on; `OPENUI_COMPATIBLE_SEND_THINKING`
forces/disables sending the DeepSeek-only `thinking` field). `OPENAI_API_KEY` still works
for OpenAI models if you add it.

Optional: `OPENUI_SINGLE_USER_NAME` (default `owner`), `OPENUI_MAX_TOKENS` (24h
token quota, default 700000 – note upstream counts `gpt-4*` models 20x, so raise it
for real use), `OPENUI_OPENAI_MODELS` (comma separated model list shown in the UI),
`GROQ_API_KEY`, `OPENUI_DB_CONNECT_TIMEOUT`.

`VERCEL=1` is set by Vercel and switches on serverless mode automatically
(`OPENUI_SERVERLESS=1` does the same elsewhere).

## Database

`backend/migrations/001_init.sql` is the schema (also applied by the app with
`CREATE TABLE IF NOT EXISTS` on first use). RLS is enabled with no policies so the
Supabase REST API (anon key) cannot read the tables; OpenUI connects directly as
the `postgres` role. Shared components are stored in the `shares` table (S3 is only
used if `AWS_ACCESS_KEY_ID`/`AWS_SECRET_ACCESS_KEY` are set and `pip install openui[s3]`).

Free-tier note: Supabase pauses free projects after a week of inactivity.

## Notes

* DB connections are opened lazily and closed after every request (including the
  end of a streamed response), and psycopg2 uses the simple query protocol, so the
  transaction pooler is safe.
* Chat streaming uses SSE inside the 300s Hobby function limit.
* Generated-HTML previews are rendered in an iframe hosted by upstream at
  `wandb.github.io` (the HTML stays in the browser, passed via `postMessage`).
* Tests: `backend/tests/test_postgres_single_user.py` (needs a throw-away Postgres,
  see its docstring).
