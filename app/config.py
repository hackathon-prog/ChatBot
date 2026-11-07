from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    anthropic_api_key: str = Field(min_length=1)
    anthropic_model: str = "claude-sonnet-5-5"
    database_url: str = "sqlite:///lms.db"
    db_schema: str = ""
    blocked_columns: str = "email,password,password_hash,phone,address,user_id,display_name,body"
    max_rows: int = Field(default=200, ge=1, le=2000)

    # Admin-only access through Supabase sign-in. Turn off only for the local SQLite sample.
    require_auth: bool = True
    supabase_url: str = ""
    supabase_anon_key: str = ""
    cors_origins: str = ""
    requests_per_minute: int = Field(default=12, ge=1, le=600)

    @model_validator(mode="after")
    def _auth_needs_supabase(self) -> "Settings":
        if self.require_auth and not (self.supabase_url and self.supabase_anon_key):
            raise ValueError("REQUIRE_AUTH=true needs SUPABASE_URL and SUPABASE_ANON_KEY (anon key only).")
        return self

    @property
    def blocked_set(self) -> frozenset[str]:
        return frozenset(c.strip().lower() for c in self.blocked_columns.split(",") if c.strip())

    @property
    def origins(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]
