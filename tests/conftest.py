import os

# Required Settings fields — set before any src.config import happens.
os.environ.setdefault("ANTHROPIC_API_KEY", "sk-ant-test-key")
os.environ.setdefault("DATABASE_URL", "postgresql://postgres:password@localhost:5432/hedgefund_test")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/15")
