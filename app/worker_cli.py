"""Module entry point for running the worker from a local virtual environment."""

from app.cli import run_worker


def main() -> None:
    """Start the command-line worker interface."""

    run_worker()


if __name__ == "__main__":
    main()
