import uvicorn

from .config import HubSettings


def main() -> None:
    s = HubSettings()
    uvicorn.run("ovian_hub.app:create_app", factory=True, host=s.http_host, port=s.http_port, proxy_headers=True,
                forwarded_allow_ips="*")


if __name__ == "__main__":
    main()
