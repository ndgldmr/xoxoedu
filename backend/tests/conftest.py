import os

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

# Generate a single RSA keypair for the entire test session before any app imports
_test_rsa_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
_TEST_PRIVATE_KEY = _test_rsa_key.private_bytes(
    encoding=serialization.Encoding.PEM,
    format=serialization.PrivateFormat.TraditionalOpenSSL,
    encryption_algorithm=serialization.NoEncryption(),
).decode()
_TEST_PUBLIC_KEY = _test_rsa_key.public_key().public_bytes(
    encoding=serialization.Encoding.PEM,
    format=serialization.PublicFormat.SubjectPublicKeyInfo,
).decode()

os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://postgres:postgres@localhost:5432/xoxoedu_test")
os.environ.setdefault("DATABASE_URL_SYNC", "postgresql://postgres:postgres@localhost:5432/xoxoedu_test")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/1")
os.environ["JWT_PRIVATE_KEY"] = _TEST_PRIVATE_KEY
os.environ["JWT_PUBLIC_KEY"] = _TEST_PUBLIC_KEY
os.environ.setdefault("SECRET_KEY", "a" * 64)
os.environ.setdefault("GOOGLE_CLIENT_ID", "test-client-id")
os.environ.setdefault("GOOGLE_CLIENT_SECRET", "test-client-secret")
os.environ.setdefault("GOOGLE_REDIRECT_URI", "http://localhost:8000/api/v1/auth/google/callback")
os.environ.setdefault("RESEND_API_KEY", "re_test_key")
os.environ.setdefault("ENVIRONMENT", "test")
