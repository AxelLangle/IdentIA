from datetime import datetime, timedelta, timezone
import hashlib
import hmac
import secrets

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
import jwt
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import get_db
from app.models import User

bearer_scheme = HTTPBearer(auto_error=False)


def hash_secret(plain: str) -> str:
    """Genera un hash scrypt con salt aleatorio de 16 bytes."""
    salt = secrets.token_bytes(16)
    derived = hashlib.scrypt(
        plain.encode("utf-8"),
        salt=salt,
        n=16384,
        r=8,
        p=1,
        dklen=32,
    )
    return f"scrypt$16384$8$1${salt.hex()}${derived.hex()}"


def verify_secret(plain: str, encoded: str) -> bool:
    """Verifica un secreto en tiempo constante contra su hash scrypt."""
    try:
        scheme, n_s, r_s, p_s, salt_hex, hash_hex = encoded.split("$")
        if scheme != "scrypt":
            return False
        salt = bytes.fromhex(salt_hex)
        expected = bytes.fromhex(hash_hex)
        derived = hashlib.scrypt(
            plain.encode("utf-8"),
            salt=salt,
            n=int(n_s),
            r=int(r_s),
            p=int(p_s),
            dklen=len(expected),
        )
        return hmac.compare_digest(derived, expected)
    except (ValueError, TypeError):
        return False


def generate_delegated_secret() -> tuple[str, str]:
    """Genera una contraseña delegada legible y su prefijo de identificación."""
    alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
    parts = ["".join(secrets.choice(alphabet) for _ in range(4)) for _ in range(3)]
    plain_secret = f"IDN-{'-'.join(parts)}"
    prefix = f"IDN-{parts[0]}"
    return plain_secret, prefix


def create_access_token(user: User) -> str:
    """Firma un token JWT HS256 para la sesión del usuario."""
    settings = get_settings()
    now_utc = datetime.now(timezone.utc)
    payload = {
        "sub": str(user.id),
        "email": user.email,
        "role": user.role,
        "org_id": user.organization_id,
        "iat": now_utc,
        "exp": now_utc + timedelta(minutes=settings.jwt_expire_minutes),
    }
    return jwt.encode(payload, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)


def decode_access_token(token: str) -> dict:
    """Decodifica y valida un token JWT HS256."""
    settings = get_settings()
    return jwt.decode(
        token,
        settings.jwt_secret_key,
        algorithms=[settings.jwt_algorithm],
    )


def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    db: Session = Depends(get_db),
) -> User:
    """Obtiene el usuario autenticado activo desde el header Bearer JWT."""
    auth_error = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Sesión no autenticada o token expirado.",
        headers={"WWW-Authenticate": "Bearer"},
    )
    if credentials is None or not credentials.credentials:
        raise auth_error

    try:
        payload = decode_access_token(credentials.credentials)
        user_id = int(payload["sub"])
    except (jwt.PyJWTError, KeyError, ValueError, TypeError) as exc:
        raise auth_error from exc

    user = db.get(User, user_id)
    if user is None or not user.is_active:
        raise auth_error
    return user


def require_roles(*roles: str):
    """Dependencia que restringe el acceso a los roles indicados."""

    def _checker(current_user: User = Depends(get_current_user)) -> User:
        if current_user.role not in roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="No cuentas con permisos suficientes para esta operación.",
            )
        return current_user

    return _checker


def resolve_org_scope(current_user: User, requested_org_id: int | None) -> int:
    """Resuelve y valida el aislamiento multi-organización para consultas y comandos."""
    if current_user.role == "superadmin":
        if requested_org_id is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Debes indicar organization_id.",
            )
        return requested_org_id

    if current_user.organization_id is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Usuario sin organización asignada.",
        )

    if requested_org_id is not None and requested_org_id != current_user.organization_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Acceso denegado a recursos de otra organización.",
        )
    return current_user.organization_id


def assert_org_access(current_user: User, target_org_id: int) -> None:
    """Verifica que el usuario pueda operar sobre target_org_id."""
    if current_user.role == "superadmin":
        return
    if current_user.organization_id != target_org_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Acceso denegado a recursos de otra organización.",
        )
