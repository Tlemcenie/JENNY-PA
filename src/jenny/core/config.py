"""Configuration via Pydantic Settings."""

from functools import lru_cache
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict

# secret jwt par défaut
DEFAULT_JWT_SECRET = "change-me-in-production"


class Settings(BaseSettings):
    """Configuration principale de Jenny."""

    model_config = SettingsConfigDict(
        env_prefix="JENNY_",
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
        # erreurs sans secrets
        hide_input_in_errors=True,
    )

    # application
    env: Literal["dev", "test", "prod"] = "dev"
    debug: bool = True
    log_level: str = "INFO"
    app_name: str = "Jenny"
    # forcé à True en prod
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
    # POST /auth/* par IP
    rate_limit_auth_max_requests: int = 20
    # login par IP, échecs à part
    rate_limit_login_max_requests: int = 60
    # chat par IP
    rate_limit_chat_max_requests: int = 30
    # chat par salon
    rate_limit_chat_business_max_requests: int = 300
    # proxys devant l'API (XFF)
    rate_limit_proxy_hops: int = 1

    # LLM
    openai_api_key: str = ""
    groq_api_key: str = ""
    llm_provider: str = "groq"  # groq ou openai
    llm_model: str = "openai/gpt-oss-120b"  # modèle par défaut Groq
    llm_temperature: float = 0.4  # bas = stable/posé

    # intention : tête mpnet
    enable_ml_models: bool = True
    intent_head_path: str = "checkpoints/intent_head/head.npz"

    # embeddings RAG
    # multilingue, 100 % en-process
    embeddings_backend: str = "sentence-transformer"  # ou openai
    embeddings_model: str = "paraphrase-multilingual-mpnet-base-v2"
    # re-ranking lexical
    rag_rerank: bool = True
    rag_rerank_candidates: int = 12  # candidats avant re-ranking

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
    # secret partagé du webhook
    snapchat_webhook_secret: str = ""

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
    # ignoré en prod
    skip_meta_signature: bool = False

    # origine publique de l'API
    # vide = dérivée de la requête
    public_api_base_url: str = ""

    # chiffrement des identifiants (Fernet)
    # obligatoire en prod
    master_key: str = ""
    # clair permis hors prod
    allow_plaintext_credentials: bool = False

    # business par défaut (dev)
    default_business_id: str = ""

    # OAuth Google
    google_oauth_client_id: str = ""
    google_oauth_client_secret: str = ""
    google_oauth_redirect_uri: str = "http://localhost:8000/api/v1/auth/google/callback"
    jwt_secret: str = DEFAULT_JWT_SECRET
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

    @property
    def auth_required(self) -> bool:
        """Auth exigée (toujours en prod)."""
        return self.require_auth or self.is_prod

    @property
    def meta_signature_skipped(self) -> bool:
        """Saut du HMAC Meta, jamais en prod."""
        return self.skip_meta_signature and not self.is_prod


class InsecureConfigError(RuntimeError):
    """Config prod pas sûre."""


def check_prod_secrets(settings: Settings) -> None:
    """Refuse une prod mal configurée."""
    if not settings.is_prod:
        return
    errors: list[str] = []
    secret = settings.jwt_secret.strip()
    # valeur d'exemple du .env
    if not secret or secret == DEFAULT_JWT_SECRET or secret.upper().startswith("CHANGE_ME"):
        errors.append("JENNY_JWT_SECRET doit être défini (valeur par défaut interdite)")
    key = settings.master_key.strip()
    if not key:
        errors.append("JENNY_MASTER_KEY doit être définie (clé Fernet)")
    else:
        try:
            from cryptography.fernet import Fernet

            Fernet(key.encode())
        except Exception:
            errors.append("JENNY_MASTER_KEY invalide (clé Fernet attendue)")
    if errors:
        raise InsecureConfigError("Démarrage refusé en prod : " + " ; ".join(errors))


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Settings en singleton."""
    settings = Settings()
    check_prod_secrets(settings)
    return settings
