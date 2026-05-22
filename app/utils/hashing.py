import hashlib


def sha256_text(content: str) -> str:
    """Return SHA-256 hash for a text string."""
    return hashlib.sha256(content.encode("utf-8")).hexdigest()