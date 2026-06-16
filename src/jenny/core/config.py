"""Configuration centralisée via Pydantic Settings.

Toute la configuration de l'application est centralisée ici.
Les valeurs sont lues depuis les variables d'environnement (préfixe JENNY_).
"""

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

    # ── Application ──
    env: Literal["dev", "test", "prod"] = "dev"
    debug: bool = True
    log_level: str = "INFO"
    app_name: str = "Jenny"
    require_auth: bool = False
    # Seed (idempotent) du compte démo au démarrage de l'API si activé.
    auto_seed: bool = False

    # ── API ──
    api_host: str = "0.0.0.0"
    api_port: int = 8000

    # ── Database ──
    database_url: str = "postgresql+asyncpg://jenny:jenny_secret@localhost:5432/jenny"

    # ── Redis ──
    redis_url: str = "redis://localhost:6379/0"

    # ── Rate limiting (webhooks / ingest) ──
    rate_limit_enabled: bool = True
    # Nombre de requêtes autorisées par fenêtre glissante et par IP.
    rate_limit_max_requests: int = 120
    rate_limit_window_seconds: int = 60

    # ── LLM ──
    openai_api_key: str = ""
    groq_api_key: str = ""
    mistral_api_key: str = ""
    llama_base_url: str = "http://localhost:11434"  # Ollama / vLLM local
    llm_provider: str = "groq"  # groq, openai, mistral, llama, nanogpt
    llm_model: str = "llama-3.3-70b-versatile"  # modèle par défaut Groq
    llm_temperature: float = 0.4  # ton du LLM : assez bas = stable/posé (évite l'effet « fébrile »)
    # Durée pendant laquelle Ollama garde le modèle chargé en mémoire entre deux
    # requêtes. "30m"/"-1" (illimité) évitent le cold-start → réponses « au tac au
    # tac ». Mettre "0" pour libérer la RAM immédiatement après chaque requête.
    llama_keep_alive: str = "30m"

    # ── ML supervisé (intent / NER) ──
    enable_ml_models: bool = True
    intent_model_path: str = "checkpoints/intent/best_model.pt"
    ner_model_path: str = "checkpoints/ner/best_model.pt"

    # ── Embeddings RAG ──
    embeddings_backend: str = "ollama"  # ollama, sentence-transformer, openai
    embeddings_model: str = "nomic-embed-text"

    # ── MLflow ──
    mlflow_tracking_uri: str = "http://localhost:5000"

    # ── WhatsApp Business API (Meta Cloud API) ──
    whatsapp_phone_number_id: str = ""
    whatsapp_access_token: str = ""
    whatsapp_verify_token: str = "jenny-whatsapp-verify"
    whatsapp_api_version: str = "v21.0"

    # ── Instagram Messaging API (Meta) ──
    instagram_page_id: str = ""
    instagram_access_token: str = ""
    instagram_verify_token: str = "jenny-instagram-verify"

    # ── Twitter/X API ──
    twitter_api_key: str = ""
    twitter_api_secret: str = ""
    twitter_access_token: str = ""
    twitter_access_token_secret: str = ""
    twitter_bearer_token: str = ""
    twitter_webhook_env: str = "production"

    # ── Snapchat for Business ──
    snapchat_client_id: str = ""
    snapchat_client_secret: str = ""
    snapchat_access_token: str = ""

    # ── Email SMTP (envoi de mails) ──
    smtp_host: str = "smtp.gmail.com"
    smtp_port: int = 587
    smtp_username: str = ""
    smtp_password: str = ""
    smtp_from_email: str = ""
    smtp_from_name: str = "Jenny"
    smtp_use_tls: bool = True

    # ── Backend d'envoi d'email ──
    # "auto" : SMTP si identifiants présents, sinon écriture du HTML sur disque
    # (dev, consultable dans un navigateur) ou console (tests).
    email_backend: Literal["auto", "smtp", "file", "console"] = "auto"
    email_preview_dir: str = "var/emails"
    # URL publique du front (liens dans les emails, ex. confirmation).
    app_base_url: str = "http://localhost:3000"
    # Origines CORS autorisées : "*" en dev ; en prod, l'URL du frontend
    # (plusieurs séparées par des virgules), ce qui active aussi les credentials.
    cors_origins: str = "*"
    # Durée de validité du code de confirmation email (minutes).
    email_verification_ttl_minutes: int = 15

    # ── SMS Twilio ──
    twilio_account_sid: str = ""
    twilio_auth_token: str = ""
    twilio_phone_number: str = ""

    # ── Google Calendar ──
    google_calendar_id: str = "primary"
    google_service_account_json: str = ""  # Chemin vers le fichier JSON service account

    # ── Meta webhooks (signature HMAC) ──
    facebook_app_secret: str = ""
    skip_meta_signature: bool = False

    # ── Origine PUBLIQUE de l'API (pour les URLs de webhook données à Meta) ──
    # Vide ⇒ on dérive l'origine de la requête entrante. À définir derrière un
    # proxy / en prod (ex. https://api.jenny.app).
    public_api_base_url: str = ""

    # ── Chiffrement au repos des identifiants de canal (Fernet) ──
    # Vide ⇒ identifiants stockés en clair (dev / mono-tenant, HTTPS). En prod,
    # définir une clé Fernet (base64 urlsafe 32 octets) pour chiffrer les tokens.
    master_key: str = ""

    # ── Dev : business par défaut si aucun channel_accounts (WhatsApp / IG) ──
    default_business_id: str = ""

    # ── OAuth Google (dashboard) ──
    google_oauth_client_id: str = ""
    google_oauth_client_secret: str = ""
    google_oauth_redirect_uri: str = "http://localhost:8000/api/v1/auth/google/callback"
    jwt_secret: str = "change-me-in-production"
    jwt_algorithm: str = "HS256"
    jwt_exp_minutes: int = 60 * 24

    # ── Email inbound ──
    email_inbound_secret: str = ""
    imap_host: str = ""
    imap_user: str = ""
    imap_password: str = ""
    imap_mailbox: str = "INBOX"
    imap_poll_seconds: int = 120
    imap_use_ssl: bool = True
    imap_business_id: str = ""

    # ── Stripe / PayPal ──
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
    """Retourne l'instance unique des settings (singleton via cache)."""
    return Settings()
