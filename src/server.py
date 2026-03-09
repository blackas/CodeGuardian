"""Entry point for the webhook server: python -m src.server"""

import uvicorn

from src.webhook_server import app


def main() -> None:
    uvicorn.run(app, host="0.0.0.0", port=8000)


if __name__ == "__main__":
    main()
