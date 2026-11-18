from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_name: str = "YAAN"
    environment: str = "development"  # development | production
    database_url: str = "postgresql+psycopg://yaan:yaan_dev_2026@localhost:5432/yaan"

    # Auth
    jwt_secret: str = "dev-only-change-me"
    jwt_algorithm: str = "HS256"
    access_token_minutes: int = 60
    temp_password_days: int = 5  # confirmed business rule (spec 2.1)

    password_min_length: int = 10
    reset_token_minutes: int = 60
    frontend_url: str = "http://localhost:5173"

    # Email (SendGrid chosen). Without an API key, emails are logged to the console (dev only).
    sendgrid_api_key: str | None = None
    # AWS SES (preferred when AWS_SES_REGION is set). Credentials: the two keys below, or the usual AWS ones
    # (IAM role / ~/.aws / AWS_ACCESS_KEY_ID env) when they are left empty. EMAIL_FROM must be a verified SES identity.
    aws_ses_region: str | None = None
    aws_access_key_id: str | None = None
    aws_secret_access_key: str | None = None
    aws_ses_configuration_set: str | None = None  # optional, for delivery/bounce tracking
    # Zoho ZeptoMail (transactional email API). Set the "Send Mail token" as ZEPTOMAIL_API_KEY. EMAIL_FROM must be an address
    # on a domain verified in ZeptoMail (e.g. no-reply@yourdomain.in). URL by data centre: India api.zeptomail.in, global
    # api.zeptomail.com, EU api.zeptomail.eu.
    zeptomail_api_key: str | None = None
    zeptomail_api_url: str = "https://api.zeptomail.in/v1.1/email"
    # SMTP server, used whenever SMTP_HOST is set (takes priority over SendGrid). Zoho Mail:
    #   India data centre: smtp.zoho.in   | Global: smtp.zoho.com | EU: smtp.zoho.eu
    #   port 465 + SMTP_USE_SSL=true  (or port 587 + SMTP_USE_SSL=false for STARTTLS)
    #   SMTP_USERNAME = the full mailbox address; SMTP_PASSWORD = an app-specific password (needed if 2FA is on).
    #   EMAIL_FROM must be that same mailbox (or an alias added to it), otherwise Zoho rejects the message.
    # Gmail also works: smtp.gmail.com:587 + an app password.
    smtp_host: str | None = None
    smtp_port: int = 587
    smtp_username: str | None = None
    smtp_password: str | None = None
    smtp_use_ssl: bool = False  # True for implicit TLS (port 465); otherwise STARTTLS is used
    email_from: str = "no-reply@yaan.local"
    email_from_name: str = "YAAN"

    # SMS (Twilio chosen). Without all three Twilio values, SMS go to the console log (dev only).
    twilio_account_sid: str | None = None
    twilio_auth_token: str | None = None
    twilio_from_number: str | None = None
    # Public URL of this API (e.g. https://api.example.com). Needed for Twilio delivery-status callbacks.
    public_base_url: str | None = None
    default_country_code: str = "+91"  # applied to local numbers stored without a country code
    sms_timeout_seconds: int = 10

    # Expenses: how long the person who entered an expense may still edit/void it (admins: always)
    expense_edit_window_hours: int = 24

    # Drop-off OTP (confirmed: 4 digits; 5 wrong tries per employee, then locked)
    otp_length: int = 4
    otp_max_attempts: int = 5

    # Dashboard thresholds
    on_time_grace_minutes: int = 5  # a trip that starts within this many minutes of schedule counts as on time
    acceptance_warning_minutes: int = 60  # flag trips not yet accepted this close to departure
    assignment_warning_minutes: int = 180  # flag requests still without driver/vehicle this close to departure

    # Login throttling (spec 29)
    login_max_attempts: int = 8
    login_window_seconds: int = 300

    # Timezone used for day boundaries, filters and message text. Instants are stored as UTC.
    business_timezone: str = "Asia/Kolkata"

    # Scheduling (spec 2.6) – centralised, used only by the availability service
    availability_buffer_minutes: int = 30

    cors_origins: list[str] = ["http://localhost:5173"]


@lru_cache
def get_settings() -> Settings:
    return Settings()
