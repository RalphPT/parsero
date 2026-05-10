"""
Hashing y verificación de passwords con bcrypt.

Usamos `bcrypt` directamente (no passlib) porque passlib 1.7.4 tiene un bug
de detección con bcrypt >=4.0 que falla en módulos con __version__ no parseable.
Bcrypt limita los passwords a 72 bytes - truncamos por seguridad para evitar
errores en contraseñas con muchos chars unicode.
"""
import bcrypt


_BCRYPT_MAX_BYTES = 72


def _truncate(password: str) -> bytes:
    return password.encode("utf-8")[:_BCRYPT_MAX_BYTES]


def hash_password(plain: str) -> str:
    return bcrypt.hashpw(_truncate(plain), bcrypt.gensalt()).decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(_truncate(plain), hashed.encode("utf-8"))
    except ValueError:
        return False
