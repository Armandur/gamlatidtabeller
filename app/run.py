"""Kor publika appen och admin-appen i samma process pa tva portar.

Samma process kravs for att admin ska kunna lasa realtidsstatus och
utskriftsjobb ur minnet. PORT (default 8000) ar publika appen,
ADMIN_PORT (default 8001) ar admin - exponera bara den forra publikt.

    uv run python -m app.run
"""

import asyncio
import os

import uvicorn

from app.admin import app as admin_app
from app.main import app as public_app


async def _serve() -> None:
    port = int(os.environ.get("PORT", "8000"))
    admin_port = int(os.environ.get("ADMIN_PORT", "8001"))
    servers = [
        uvicorn.Server(uvicorn.Config(public_app, host="0.0.0.0", port=port)),
        uvicorn.Server(uvicorn.Config(admin_app, host="0.0.0.0", port=admin_port)),
    ]
    # uvicorns signalhantering kraknar med flera servrar i samma loop -
    # lat KeyboardInterrupt/SIGTERM avbryta gather i stallet
    for server in servers:
        server.install_signal_handlers = lambda: None
    await asyncio.gather(*(s.serve() for s in servers))


def main() -> None:
    try:
        asyncio.run(_serve())
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
