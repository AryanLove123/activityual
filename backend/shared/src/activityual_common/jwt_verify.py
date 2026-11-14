import json
from dataclasses import dataclass

import jwt


@dataclass(frozen=True)
class Claims:
    user_id: str
    token_id: str

def parse_keys(keys_json: str) -> dict[str, str]:
    keys = json.loads(keys_json or "{}")
    if not isinstance(keys, dict):
        raise ValueError("JWT_PUBLIC_KEYS must be a JSON object {kid: PEM}")  # noqa: TRY004
    return keys

def verify_token(token: str, keys: dict[str, str], issuer: str, audience: str) -> Claims:
    try: 
        header = jwt.get_unverified_header(token)
        if header.get("alg") != "RS256":
            raise TokenError("unexpected algorithm")

        key = keys.get(header.get("kid", ""))
        if key is None: 
            raise TokenError("unknow key id")

        data = jwt.decode(token, key, algorithms=["RS256"], issuer=issuer, audience=audience, options={"require": ["exp", "iat", "sub", "iss", "aud"]})

        return Claims(user_id=str(data["sub"]), token_id=str(data.get("jti", "")))
    except TokenError:
        raise
    except jwt.PyJWTError as exc:
        raise TokenError(type(exc).__name__) from exc


class TokenError(Exception):
    """Token missing, malformed, expired, wrongly signed or for another audience."""
