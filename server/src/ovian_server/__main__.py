import uvicorn

from .config import Settings


def main() -> None:
    settings = Settings()
    uvicorn.run(
        "ovian_server.app:create_app",
        factory=True,
        host=settings.http_host,
        port=settings.http_port,
        proxy_headers=True,
    )


if __name__ == "__main__":
    main()
