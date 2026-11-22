import os
from pathlib import Path
import secrets
from urllib.parse import urlparse
from enum import Enum


def _flag(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in ("1", "true", "yes", "on")


class Env(Enum):
    LOCAL = 1
    PROD = 2
    DEV = 3


try:
    env = os.getenv("OPENUI_ENVIRONMENT", "local")
    if env == "production":
        env = "prod"
    elif env == "development":
        env = "dev"
    ENV = Env[env.upper()]
except KeyError:
    print("Invalid environment, defaulting to running locally")
    ENV = Env.LOCAL

# True when running as a serverless function (Vercel sets VERCEL=1). In this mode
# there is no writable home directory, no Ollama / LiteLLM sidecar and the
# database must be an external Postgres (DATABASE_URL).
SERVERLESS = _flag("OPENUI_SERVERLESS", bool(os.getenv("VERCEL")))

# Postgres (e.g. a Supabase pooler connection string). When set, it replaces the
# default local SQLite database. peewee/psycopg2 uses the simple query protocol,
# so this is safe behind a transaction-mode pooler (pgbouncer / Supavisor).
DATABASE_URL = os.getenv("DATABASE_URL") or os.getenv("OPENUI_DATABASE_URL")
DB_CONNECT_TIMEOUT = int(os.getenv("OPENUI_DB_CONNECT_TIMEOUT", "10"))

# Single-owner mode: skip GitHub OAuth and give every browser session the same
# owner account. ONLY enable this when the deployment is protected by something
# else (e.g. Vercel Authentication set to "All Deployments").
SINGLE_USER = _flag("OPENUI_SINGLE_USER")
SINGLE_USER_NAME = os.getenv("OPENUI_SINGLE_USER_NAME", "owner")

# Only touch the home directory for the local (non serverless) defaults.
default_db = Path.home() / ".openui" / "db.sqlite"
if DATABASE_URL is None and not SERVERLESS:
    default_db.parent.mkdir(exist_ok=True)
DB = os.getenv("DATABASE", default_db)
if isinstance(DB, str):
    DB = Path(DB)

if SERVERLESS and DATABASE_URL is None:
    raise RuntimeError(
        "DATABASE_URL is required when running serverless (e.g. on Vercel). "
        "Set it to your Supabase *pooler* connection string."
    )

HOST = os.getenv(
    "OPENUI_HOST",
    "https://localhost:5173" if ENV == Env.DEV else "http://localhost:7878",
)
RP_ID = urlparse(HOST).hostname

SESSION_KEY = os.getenv("OPENUI_SESSION_KEY")
if SESSION_KEY is None:
    if SERVERLESS or DATABASE_URL is not None or SINGLE_USER:
        # A random per-process key would silently log everyone out on every cold
        # start / across function instances, so refuse to start without one.
        raise RuntimeError(
            "OPENUI_SESSION_KEY is required in serverless / Postgres / single-user "
            "mode. "
            'Generate one with: python -c "import secrets; print(secrets.token_hex(32))"'
        )
    env_path = Path.home() / ".openui" / ".env"
    if env_path.exists():
        SESSION_KEY = env_path.read_text().splitlines()[0].split("=")[1]
    else:
        SESSION_KEY = secrets.token_hex(32)
        with env_path.open("w") as f:
            f.write(f"OPENUI_SESSION_KEY={SESSION_KEY}")
# Set the LITELLM_MASTER_KEY to a random value if it's not already set
if os.getenv("LITELLM_MASTER_KEY") is None:
    os.environ["LITELLM_MASTER_KEY"] = "sk-{SESSION_KEY}"
# GPT 3.5 is 0.0005 per 1k tokens input and 0.0015 output
# 700k puts us at a max of $1.00 spent per user over a 48 hour period
MAX_TOKENS = int(os.getenv("OPENUI_MAX_TOKENS", "700000"))
GITHUB_CLIENT_ID = os.getenv("GITHUB_CLIENT_ID")
GITHUB_CLIENT_SECRET = os.getenv("GITHUB_CLIENT_SECRET")

# Optional S3 storage for shared components. When none of these are set, shares
# are stored in the database instead (see openui/util/storage.py).
AWS_ENDPOINT_URL_S3 = os.getenv("AWS_ENDPOINT_URL_S3")
AWS_ACCESS_KEY_ID = os.getenv("AWS_ACCESS_KEY_ID")
AWS_SECRET_ACCESS_KEY = os.getenv("AWS_SECRET_ACCESS_KEY")
BUCKET_NAME = os.getenv("BUCKET_NAME", "openui")
USE_S3 = bool(AWS_ACCESS_KEY_ID and AWS_SECRET_ACCESS_KEY)

# Cors, if you're hosting the annotator iframe elsewhere, add it here
CORS_ORIGINS = os.getenv(
    "OPENUI_CORS_ORIGINS", "https://wandb.github.io,https://localhost:5173"
).split(",")

# Model providers
OLLAMA_HOST = os.getenv("OLLAMA_HOST", "http://127.0.0.1:11434")
# Ollama and the LiteLLM proxy only make sense on a machine you run yourself.
OLLAMA_ENABLED = _flag("OPENUI_ENABLE_OLLAMA", not SERVERLESS)
LITELLM_ENABLED = _flag("OPENUI_ENABLE_LITELLM", not SERVERLESS)
OPENAI_BASE_URL = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "xxx")
# Optional comma separated override of the OpenAI models offered in the UI,
# e.g. OPENUI_OPENAI_MODELS=gpt-4o-mini,gpt-4o
OPENAI_MODELS = [
    m.strip() for m in os.getenv("OPENUI_OPENAI_MODELS", "").split(",") if m.strip()
]
GROQ_BASE_URL = os.getenv("GROQ_BASE_URL", "https://api.groq.com/openai/v1")
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
# Generic OpenAI compatible provider (DeepSeek by default). With the LiteLLM proxy
# these two variables feed LiteLLM's config; when LiteLLM is disabled (serverless)
# OpenUI calls the endpoint directly and lists COMPATIBLE_MODELS in the UI.
OPENAI_COMPATIBLE_API_KEY = os.getenv("OPENAI_COMPATIBLE_API_KEY")
OPENAI_COMPATIBLE_ENDPOINT = os.getenv(
    "OPENAI_COMPATIBLE_ENDPOINT", "https://api.deepseek.com"
)
COMPATIBLE_MODELS = [
    m.strip()
    for m in os.getenv("OPENUI_COMPATIBLE_MODELS", "deepseek-flash,deepseek-v4-pro").split(
        ","
    )
    if m.strip()
]
# DeepSeek models think by default, which delays the first streamed token. Off
# unless OPENUI_COMPATIBLE_THINKING=true.
COMPATIBLE_THINKING = _flag("OPENUI_COMPATIBLE_THINKING")
# The {"thinking": ...} request field is DeepSeek specific; other endpoints may
# reject unknown fields, so only send it to DeepSeek unless forced.
COMPATIBLE_SEND_THINKING = _flag(
    "OPENUI_COMPATIBLE_SEND_THINKING", "deepseek" in OPENAI_COMPATIBLE_ENDPOINT
)
COMPATIBLE_DIRECT = bool(OPENAI_COMPATIBLE_API_KEY) and not LITELLM_ENABLED
LITELLM_API_KEY = os.getenv("LITELLM_API_KEY", os.getenv("LITELLM_MASTER_KEY"))
LITELLM_BASE_URL = os.getenv("LITELLM_BASE_URL", "http://0.0.0.0:4000")
PORT = int(os.getenv("PORT", 7878))
