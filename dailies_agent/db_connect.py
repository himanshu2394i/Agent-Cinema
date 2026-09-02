"""ClickHouse client for editorial ranking tools on Cloud Run."""

import os

import clickhouse_connect
from dotenv import load_dotenv


def connect():
    load_dotenv()
    host = os.getenv("CLICKHOUSE_HOST")
    if not host:
        raise RuntimeError("CLICKHOUSE_HOST is not set")
    return clickhouse_connect.get_client(
        host=host,
        port=int(os.getenv("CLICKHOUSE_PORT", "8443")),
        username=os.getenv("CLICKHOUSE_USER", "default"),
        password=os.getenv("CLICKHOUSE_PASSWORD", ""),
        secure=os.getenv("CLICKHOUSE_SECURE", "true").lower() == "true",
    )
