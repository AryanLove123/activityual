import json
import sys
import uuid

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
kid = sys.argv[1] if len(sys.argv) > 1 else f"k-{uuid.uuid4().hex[:8]}"
priv = key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()).decode()
pub = key.public_key().public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo).decode()
print("JWT_PRIVATE_KEY=" + json.dumps(priv))
print("JWT_PUBLIC_KEYS=" + json.dumps(json.dumps({kid: pub})))
print("JWT_KID=" + kid)