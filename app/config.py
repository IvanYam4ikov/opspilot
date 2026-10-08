import os


class Settings:
    database_url = os.getenv(
        "DATABASE_URL", "postgresql+psycopg://opspilot:opspilot@localhost:5432/opspilot"
    )
    cors_origins = [
        origin.strip()
        for origin in os.getenv("CORS_ORIGINS", "http://localhost:3000").split(",")
        if origin.strip()
    ]
    investigation_mode = os.getenv("INVESTIGATION_MODE", "demo")
    openai_api_key = os.getenv("OPENAI_API_KEY")
    openai_model = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
    auth_secret = os.getenv("AUTH_SECRET", "local-development-secret-change-me")
    auth_token_minutes = int(os.getenv("AUTH_TOKEN_MINUTES", "480"))
    auto_create_schema = os.getenv("AUTO_CREATE_SCHEMA", "true").lower() == "true"
    worker_poll_seconds = float(os.getenv("WORKER_POLL_SECONDS", "1"))


settings = Settings()
