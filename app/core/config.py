from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):

    # 환경변수 > .env
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # ── App ──────────────────────────────────────
    APP_ENV: str = "development"
    APP_PORT: int = 8000

    # ── MariaDB ──────────────────────────────────
    DB_HOST: str = "localhost"
    DB_PORT: int = 3306
    DB_NAME: str = "logfixer"
    DB_USER: str = "logfixer"
    DB_PASSWORD: str = "logfixer1234"

    # ── Qdrant ───────────────────────────────────
    QDRANT_HOST: str = "localhost"
    QDRANT_PORT: int = 6333

    # ── Elasticsearch ────────────────────────────
    ES_HOST: str = "http://localhost:9200"

    # ── OpenAI ───────────────────────────────────
    OPENAI_API_KEY: str = ""

    # ── Slack ────────────────────────────────────
    SLACK_BOT_TOKEN: str = ""
    SLACK_CHANNEL_ID: str = ""

    # ── LC 연동 ───────────────────────────────────
    LC_BASE_URL: str = "http://localhost:8080"
    LC_API_KEY: str = ""

    # ── SSH ───────────────────────────────────────
    SSH_DEFAULT_USER: str = "ubuntu"
    SSH_DEFAULT_KEY_PATH: str = "/home/ubuntu/.ssh/id_rsa"

    @property
    def db_url(self) -> str:
        """SQLAlchemy 비동기 접속 URL"""
        return (
            f"mysql+aiomysql://{self.DB_USER}:{self.DB_PASSWORD}"
            f"@{self.DB_HOST}:{self.DB_PORT}/{self.DB_NAME}"
        )


settings = Settings()