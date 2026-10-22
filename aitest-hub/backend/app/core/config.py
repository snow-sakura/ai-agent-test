import os
from pathlib import Path

# 先加载 backend/.env（若存在），让下面所有 os.getenv 都能吃到本地配置。
# python-dotenv 缺失时静默跳过，不影响只用系统环境变量的部署方式。
try:  # pragma: no cover - 环境相关
    from dotenv import load_dotenv

    load_dotenv(Path(__file__).resolve().parent.parent.parent / ".env")
except Exception:  # noqa: BLE001
    pass

# Base directory
BASE_DIR = Path(__file__).resolve().parent.parent

# Database
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite+aiosqlite:///./aitest_hub.db")

# JWT
SECRET_KEY = os.getenv("SECRET_KEY", "your-secret-key-change-in-production")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60 * 24  # 24 hours

# AI Configuration
DEFAULT_AI_MODEL = "gpt-3.5-turbo"
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
OPENAI_BASE_URL = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1")

# Redis (for Celery)
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")

# File Storage
UPLOAD_DIR = BASE_DIR / "uploads"
UPLOAD_DIR.mkdir(exist_ok=True)

# CORS
CORS_ORIGINS = [
    "http://localhost:5173",
    "http://localhost:3000",
    "http://localhost:8080",
]

# App Info
APP_NAME = "AI Test Hub"
APP_VERSION = "1.0.0"
APP_DESCRIPTION = "AI驱动的智能测试平台"

# 种子账号（仅本地开发/演示用）
# 真实个人信息一律放 backend/.env，不要写进源码：
#   DEMO_ACCOUNT / DEMO_PASSWORD / ADMIN_PASSWORD
DEMO_ACCOUNT = os.getenv("DEMO_ACCOUNT", "13800000000")
DEMO_PASSWORD = os.getenv("DEMO_PASSWORD", "Demo@2026")
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "admin123")
# 演示账号是否对外暴露给登录页（一键填充）。生产部署建议置 false。
DEMO_ACCOUNT_PUBLIC = os.getenv("DEMO_ACCOUNT_PUBLIC", "1") not in ("0", "false", "no")
