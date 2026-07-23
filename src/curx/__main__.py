import uvicorn

from curx.core.config import get_settings


def main() -> None:
    settings = get_settings()
    uvicorn.run(
        "curx.main:app",
        host=settings.app_host,
        port=settings.app_port,
        reload=settings.app_env == "local",
    )


if __name__ == "__main__":
    main()
