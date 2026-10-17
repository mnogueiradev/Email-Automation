"""Command-line entry points."""

import argparse

import uvicorn

from app.config import get_settings
from app.worker import run_worker as start_worker


def run_api() -> None:
    """Run the API with the configured local bind address."""

    settings = get_settings()
    uvicorn.run(
        "app.main:app",
        host=str(settings.api_host),
        port=settings.api_port,
        log_config=None,
        access_log=False,
        reload=False,
    )


def run_worker() -> None:
    """Run the outbound queue worker; one batch is processed with ``--once``."""

    parser = argparse.ArgumentParser(description="Processa a fila de e-mails agendados.")
    parser.add_argument(
        "--once",
        action="store_true",
        help="Processa um único lote e encerra; sem esta opção, monitora a fila.",
    )
    arguments = parser.parse_args()
    start_worker(once=arguments.once)
