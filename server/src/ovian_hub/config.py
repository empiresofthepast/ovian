from pydantic_settings import BaseSettings, SettingsConfigDict


class HubSettings(BaseSettings):
    """All settings come from OVIAN_HUB_* environment variables."""

    model_config = SettingsConfigDict(env_prefix="OVIAN_HUB_", env_file=".env", extra="ignore")

    http_host: str = "0.0.0.0"
    http_port: int = 8000
    database_url: str = "postgresql://ovian:ovian@localhost:5432/ovian_hub"

    # Signs the hub's own login tokens.
    jwt_secret: str = "dev-hub-secret-change-me-please-0123456789"
    jwt_ttl_hours: int = 72
    # Shared with every world (their OVIAN_HUB_SECRET): signs the tickets that let an account into a world,
    # and authenticates the hub's badge pushes and the worlds' join notices.
    world_secret: str = "dev-world-secret-change-me-please-0123456789"
    ticket_ttl_seconds: int = 300

    # Comma separated usernames that are hub administrators (founders, badges, worlds).
    admin_users: str = ""
    cors_origins: str = "*"
    # Public address of the site, where Patreon sends players back: https://empires.ofthepast.org
    public_url: str = "http://localhost:47174"
    # Public path or URL of the hub API as seen from the browser, for the Patreon redirect URI.
    public_api_url: str = "http://localhost:47174/hub"

    # Patreon (docs/patreon.md). Empty client id disables it.
    patreon_client_id: str = ""
    patreon_client_secret: str = ""
    patreon_webhook_secret: str = ""
    # Only pledges to this campaign count (the id from the creator's campaign); empty: any campaign of the client.
    patreon_campaign_id: str = ""

    # Worlds declared at startup, created or updated: "id|name|api_url|internal_url;..." (handy with Docker).
    worlds: str = ""
    # The world spawner (docs/worlds.md): where the hub reaches it, and the key it expects. Empty: no spawning from the hub.
    spawner_url: str = ""
    spawner_key: str = ""

    @staticmethod
    def split(value: str) -> list[str]:
        return [v.strip() for v in value.split(",") if v.strip()]
