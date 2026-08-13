from __future__ import annotations

import os
from pathlib import Path

try:
    from dotenv import load_dotenv
except ImportError:
    load_dotenv = None

REPO_ROOT = Path(__file__).resolve().parents[2]

if load_dotenv is not None:
    load_dotenv(REPO_ROOT / ".env")

# Local paths
EXPORT_DIR = Path(os.getenv("CSBAOYAN_EXPORT_DIR", "chat_exports"))
PAGES_DIR = Path(os.getenv("CSBAOYAN_PAGES_DIR", "pages"))
XHS_EXPORT = os.getenv("CSBAOYAN_XHS_EXPORT", "").strip().lower() in {"1", "true", "yes", "on"}

# NTQQ 本地数据库直读（路线 B：不封号的数据源）
NTQQ_DB_PATH = Path(os.getenv("CSBAOYAN_NTQQ_DB_PATH") or "")
GROUP_CODE = os.getenv("CSBAOYAN_GROUP_CODE")
NTQQ_QQ = os.getenv("CSBAOYAN_NTQQ_QQ")  # 仅用于 qq_dump_db 解密步骤的 --qq 参数
DUMP_DB_DIR = Path(os.getenv("CSBAOYAN_DUMP_DB_DIR") or "")  # qq_dump_db 输出的明文库目录

# Model provider config
OPENAI_BASE_URL = os.getenv("OPENAI_BASE_URL")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
OPENAI_MODEL = os.getenv("OPENAI_MODEL")

# Telegram broadcast config
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHANNEL_ID = os.getenv("TELEGRAM_CHANNEL_ID")
SITE_BASE_URL = os.getenv("SITE_BASE_URL")


def resolve_path(path: Path, base: Path | None = None) -> Path:
    if path.is_absolute():
        return path
    return (base or REPO_ROOT) / path
