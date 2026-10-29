import app.config as config


def test_defaults(monkeypatch):
    monkeypatch.setattr(config, "load_dotenv", lambda: None)  # do not read the real .env
    for key in ["AWS_REGION", "MAX_ARTICLES", "DAYS", "DB_PATH", "MODEL_QUERY"]:
        monkeypatch.delenv(key, raising=False)
    s = config.get_settings()
    assert s.aws_region == "ap-south-1"
    assert s.max_articles == 8
    assert s.days == 30
    assert s.db_path == "news_impact.db"
    assert s.model_query == ""


def test_env_override(monkeypatch):
    monkeypatch.setattr(config, "load_dotenv", lambda: None)
    monkeypatch.setenv("MAX_ARTICLES", "5")
    monkeypatch.setenv("MODEL_IMPACT", "test-model")
    s = config.get_settings()
    assert s.max_articles == 5
    assert s.model_impact == "test-model"
