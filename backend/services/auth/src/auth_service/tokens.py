"""Password hashing (Argon2id) and RS256 access tokens."""

import base64
import uuid
from datetime import UTC, datetime, timedelta

import jwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from pwdlib import PasswordHash
from pwdlib.hashers.argon2 import Argon2Hasher

_hasher = PasswordHash((Argon2Hasher(),))
DUMMY_HASH = _hasher.hash(uuid.uuid4().hex)


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password: str, hashed: str) -> bool:
    return _hasher.verify(password, hashed)


def _b64(n: int) -> str:
    raw = n.to_bytes((n.bit_length() + 7) // 8, "big")
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


class TokenIssuer:
    def __init__(
        self, private_pem: str, kid: str, issuer: str, audience: str, minutes: int
    ) -> None:
        self._private_pem, self.kid, self.issuer, self.audience = (
            private_pem,
            kid,
            issuer,
            audience,
        )
        self.lifetime = timedelta(minutes=minutes)
        key = serialization.load_pem_private_key(private_pem.encode(), password=None)
        if not isinstance(key, rsa.RSAPrivateKey):
            raise TypeError("RS256 requires an RSA private key")
        nums = key.public_key().public_numbers()
        self.public_pem = (
            key.public_key()
            .public_bytes(
                serialization.Encoding.PEM,
                serialization.PublicFormat.SubjectPublicKeyInfo,
            )
            .decode()
        )
        self.jwk = {
            "kty": "RSA",
            "kid": kid,
            "use": "sig",
            "alg": "RS256",
            "n": _b64(nums.n),
            "e": _b64(nums.e),
        }

    @property
    def expires_in(self) -> int:
        return int(self.lifetime.total_seconds())

    def issue(self, user_id: str) -> str:
        now = datetime.now(UTC)
        claims = {
            "iss": self.issuer,
            "aud": self.audience,
            "sub": user_id,
            "iat": now,
            "exp": now + self.lifetime,
            "jti": str(uuid.uuid4()),
        }
        return jwt.encode(
            claims, self._private_pem, algorithm="RS256", headers={"kid": self.kid}
        )
