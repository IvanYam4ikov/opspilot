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


settings = Settings()
