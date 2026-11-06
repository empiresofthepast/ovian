from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """All settings come from OVIAN_* environment variables (or a .env file)."""

    model_config = SettingsConfigDict(env_prefix="OVIAN_", env_file=".env", extra="ignore")

    http_host: str = "0.0.0.0"
    http_port: int = 8000
    database_url: str = "postgresql://ovian:ovian@localhost:5432/ovian"

    # Content pack folder containing pack.yaml.
    content_dir: str = "content/classic"
    # World id, used in MQTT topics. One server process runs one world.
    world_id: str = "w1"
    # Overrides the pack's world.speed (handy for development).
    world_speed: float | None = None
    # A YAML file merged onto the pack at load: {world: {...}, extensions: {...}}. How a spawned world differs from
    # its pack (docs/worlds.md). Empty: the pack as it is.
    overrides_file: str = ""

    jwt_secret: str = "dev-secret-change-me"
    jwt_ttl_hours: int = 72

    # Broker the server connects to as a superuser. Empty disables MQTT.
    mqtt_url: str = ""
    mqtt_service_user: str = "ovian-server"
    mqtt_service_password: str = "dev-service-password"
    # Broker URL handed to browsers.
    mqtt_public_url: str = "ws://localhost:47001"
    # Shared with the broker's auth plugin for the /internal/mqtt endpoints.
    internal_key: str = "dev-internal-key"

    # Comma separated list of allowed origins, or *.
    cors_origins: str = "*"

    scheduler_enabled: bool = True
    scheduler_interval: float = 0.5

    # Comma separated usernames that are superusers (granted at startup and on login).
    admin_users: str = ""
    # Comma separated usernames run by the AI rulers service (shown as bots).
    bot_users: str = ""
    # days a player waits between two changes of username (real days, not game time)
    rename_days: float = 7

    # The hub (docs/worlds.md): shared with it (its OVIAN_HUB_WORLD_SECRET); empty means this world has no hub.
    hub_secret: str = ""
    # Where this world reaches the hub to report who joined, e.g. http://hub:8000; empty: it does not report.
    hub_url: str = ""
    # False: new players come only through the hub (POST /auth/register is closed).
    local_registration: bool = True

    # Comma separated extra plugin modules to load, besides installed entry points.
    plugins: str = ""
    # Comma separated entry-point plugin names to skip.
    disabled_plugins: str = ""

    @staticmethod
    def split(value: str) -> list[str]:
        return [v.strip() for v in value.split(",") if v.strip()]
