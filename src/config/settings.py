from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}

    # Feishu
    feishu_app_id: str = ""
    feishu_app_secret: str = ""
    feishu_verification_token: str = ""
    feishu_encrypt_key: str = ""
    feishu_memory_folder_name: str = "PineClaw"

    # LLM
    llm_provider: str = "openai"
    llm_api_key: str = ""
    llm_base_url: str = "https://api.deepseek.com/v1"
    llm_model: str = "deepseek-chat"

    # Chat history
    chat_history_dir: str = "./data/chat_history"
    chat_max_token_estimate: int = 60000  # ~80% of typical 128k context window
    chat_compress_keep_ratio: float = 0.3  # keep recent 30%, compress older 70%

    # App
    log_level: str = "INFO"
    sqlite_db_path: str = "./data/pineclaw.db"


settings = Settings()
