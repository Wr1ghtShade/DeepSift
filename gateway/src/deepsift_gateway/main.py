"""``deepsift-gateway``: start the API server."""

from __future__ import annotations

import argparse
import logging
import os


def main() -> None:
    parser = argparse.ArgumentParser(prog="deepsift-gateway", description=__doc__)
    parser.add_argument("--host", default=os.environ.get("DEEPSIFT_HOST", "127.0.0.1"))
    parser.add_argument("--port", type=int, default=int(os.environ.get("DEEPSIFT_PORT", "47800")))
    parser.add_argument(
        "--forwarded-allow-ips",
        default=os.environ.get("DEEPSIFT_FORWARDED_ALLOW_IPS"),
        help="trust X-Forwarded-* from these proxies (comma-separated); off by default",
    )
    args = parser.parse_args()
    logging.basicConfig(level=os.environ.get("DEEPSIFT_LOG_LEVEL", "INFO"))

    import uvicorn

    from .api import create_app

    uvicorn.run(
        create_app(),
        host=args.host,
        port=args.port,
        proxy_headers=bool(args.forwarded_allow_ips),
        forwarded_allow_ips=args.forwarded_allow_ips,
        server_header=False,
        ws_max_size=1 << 16,
    )


if __name__ == "__main__":
    main()
