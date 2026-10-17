"""Email address normalization helpers."""


def normalize_email(value: str) -> str:
    """Produce the stable lookup key used by contacts, jobs, and suppressions."""

    return value.strip().casefold()
