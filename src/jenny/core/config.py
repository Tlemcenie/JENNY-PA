"""Configuration via Pydantic Settings."""

from functools import lru_cache
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Configuration principale de Jenny."""

    model_config = SettingsConfigDict(
        env_prefix="JENNY_",
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # application
    env: Literal["dev", "test", "prod"] = "dev"
    debug: bool = True
    log_level: str = "INFO"
    app_name: str = "Jenny"
    require_auth: bool = False
    # seed du compte démo
    auto_seed: bool = False

    # API
    api_host: str = "0.0.0.0"
    api_port: int = 8000

    # database
    database_url: str = "postgresql+asyncpg://jenny:jenny_secret@localhost:5432/jenny"

    # Redis (optionnel)
    # vide = pas de Redis, tout en mémoire
    redis_url: str = ""

    # rate limiting
    rate_limit_enabled: bool = True
    # requêtes autorisées par IP
    rate_limit_max_requests: int = 120
    rate_limit_window_seconds: int = 60

    # LLM
    openai_api_key: str = ""
    groq_api_key: str = ""
    mistral_api_key: str = ""
    llama_base_url: str = "http://localhost:11434"  # Ollama / vLLM local
    llm_provider: str = "groq"  # groq, openai, mistral, llama…
    llm_model: str = "openai/gpt-oss-120b"  # modèle par défaut Groq
    llm_temperature: float = 0.4  # bas = stable/posé
    # garde le modèle chargé
    llama_keep_alive: str = "30m"

    # ML supervisé (intent/NER)
    enable_ml_models: bool = True
    intent_model_path: str = "checkpoints/intent/best_model.pt"
    ner_model_path: str = "checkpoints/ner/best_model.pt"

    # embeddings RAG
    # multilingue, 100 % en-process
    embeddings_backend: str = "sentence-transformer"  # ollama, sentence-transformer, openai
    embeddings_model: str = "paraphrase-multilingual-mpnet-base-v2"
    # re-ranking lexical
    rag_rerank: bool = True
    rag_rerank_candidates: int = 12  # candidats avant re-ranking

    # MLflow
    mlflow_tracking_uri: str = "http://localhost:5000"

    # WhatsApp (Meta)
    whatsapp_phone_number_id: str = ""
    whatsapp_access_token: str = ""
    whatsapp_verify_token: str = "jenny-whatsapp-verify"
    whatsapp_api_version: str = "v21.0"

    # Instagram (Meta)
    instagram_page_id: str = ""
    instagram_access_token: str = ""
    instagram_verify_token: str = "jenny-instagram-verify"

    # Twitter/X
    twitter_api_key: str = ""
    twitter_api_secret: str = ""
    twitter_access_token: str = ""
    twitter_access_token_secret: str = ""
    twitter_bearer_token: str = ""
    twitter_webhook_env: str = "production"

    # Snapchat
    snapchat_client_id: str = ""
    snapchat_client_secret: str = ""
    snapchat_access_token: str = ""

    # email SMTP
    smtp_host: str = "smtp.gmail.com"
    smtp_port: int = 587
    smtp_username: str = ""
    smtp_password: str = ""
    smtp_from_email: str = ""
    smtp_from_name: str = "Jenny"
    smtp_use_tls: bool = True

    # backend d'envoi email
    # auto : SMTP sinon fichier
    email_backend: Literal["auto", "smtp", "file", "console"] = "auto"
    email_preview_dir: str = "var/emails"
    # URL publique du front
    app_base_url: str = "http://localhost:3000"
    # origines CORS autorisées
    cors_origins: str = "*"
    # validité du code (minutes)
    email_verification_ttl_minutes: int = 15

    # SMS Twilio
    twilio_account_sid: str = ""
    twilio_auth_token: str = ""
    twilio_phone_number: str = ""

    # Google Calendar
    google_calendar_id: str = "primary"
    google_service_account_json: str = ""  # chemin JSON service account

    # webhooks Meta (HMAC)
    facebook_app_secret: str = ""
    skip_meta_signature: bool = False

    # origine publique de l'API
    # vide = dérivée de la requête
    public_api_base_url: str = ""

    # chiffrement des identifiants (Fernet)
    # vide = stockés en clair
    master_key: str = ""

    # business par défaut (dev)
    default_business_id: str = ""

    # OAuth Google
    google_oauth_client_id: str = ""
    google_oauth_client_secret: str = ""
    google_oauth_redirect_uri: str = "http://localhost:8000/api/v1/auth/google/callback"
    jwt_secret: str = "change-me-in-production"
    jwt_algorithm: str = "HS256"
    jwt_exp_minutes: int = 60 * 24

    # email inbound
    email_inbound_secret: str = ""
    imap_host: str = ""
    imap_user: str = ""
    imap_password: str = ""
    imap_mailbox: str = "INBOX"
    imap_poll_seconds: int = 120
    imap_use_ssl: bool = True
    imap_business_id: str = ""

    # Stripe / PayPal
    stripe_secret_key: str = ""
    stripe_webhook_secret: str = ""
    paypal_client_id: str = ""
    paypal_client_secret: str = ""
    paypal_webhook_id: str = ""
    paypal_base_url: str = "https://api-m.sandbox.paypal.com"

    @property
    def is_dev(self) -> bool:
        return self.env == "dev"

    @property
    def is_prod(self) -> bool:
        return self.env == "prod"

    @property
    def is_test(self) -> bool:
        return self.env == "test"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Settings en singleton."""
    return Settings()
