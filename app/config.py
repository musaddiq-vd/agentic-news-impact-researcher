"""Settings loaded from .env. Keys live only in .env, never in code."""

import os
from dataclasses import dataclass
from datetime import timedelta, timezone

from dotenv import load_dotenv

# Fixed UTC+5:30 (India has no DST); avoids needing the tzdata package on Windows.
IST = timezone(timedelta(hours=5, minutes=30))


@dataclass(frozen=True)
class Settings:
    aws_region: str
    tavily_api_key: str
    model_query: str
    model_impact: str
    model_summary: str
    max_articles: int
    days: int
    db_path: str
    impact_concurrency: int = 3
    # Daily email brief (app/brief.py)
    smtp_host: str = "smtp.gmail.com"
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    brief_to: tuple[str, ...] = ()
    app_url: str = "http://localhost:8501"


def get_settings() -> Settings:
    load_dotenv()
    return Settings(
        aws_region=os.getenv("AWS_REGION", "ap-south-1"),
        tavily_api_key=os.getenv("TAVILY_API_KEY", ""),
        model_query=os.getenv("MODEL_QUERY", ""),
        model_impact=os.getenv("MODEL_IMPACT", ""),
        model_summary=os.getenv("MODEL_SUMMARY", ""),
        max_articles=int(os.getenv("MAX_ARTICLES", "8")),
        days=int(os.getenv("DAYS", "30")),
        db_path=os.getenv("DB_PATH", "news_impact.db"),
        impact_concurrency=int(os.getenv("IMPACT_CONCURRENCY", "3")),
        smtp_host=os.getenv("SMTP_HOST", "smtp.gmail.com"),
        smtp_port=int(os.getenv("SMTP_PORT", "587")),
        smtp_user=os.getenv("SMTP_USER", ""),
        smtp_password=os.getenv("SMTP_PASSWORD", ""),
        brief_to=tuple(a.strip() for a in os.getenv("BRIEF_TO", "").split(",") if a.strip()),
        app_url=os.getenv("APP_URL", "http://localhost:8501"),
    )
