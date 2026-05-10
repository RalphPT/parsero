import hashlib
import secrets

API_KEY_PREFIX = "psr"
API_KEY_RAW_BYTES = 32  # secrets.token_urlsafe -> ~43 chars base64url


def hash_api_key(key: str) -> str:
    """SHA-256 hex de la clave en claro. Determinista - el lookup compara hash con hash."""
    return hashlib.sha256(key.encode("utf-8")).hexdigest()


def generate_api_key() -> tuple[str, str, str]:
    """
    Genera una nueva API key.

    Devuelve `(clave_completa, hash, prefijo_publico)`:
      - `clave_completa`: se entrega UNA SOLA VEZ al cliente y nunca se guarda
      - `hash`: lo que persiste en BD (key_hash)
      - `prefijo_publico`: primeros chars para que el cliente reconozca cuál es cuál
    """
    raw = secrets.token_urlsafe(API_KEY_RAW_BYTES)
    full_key = f"{API_KEY_PREFIX}_{raw}"
    return full_key, hash_api_key(full_key), full_key[:12]
