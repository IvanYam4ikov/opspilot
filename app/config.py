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


settings = Settings()

