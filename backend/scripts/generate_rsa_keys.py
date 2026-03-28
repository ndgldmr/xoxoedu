#!/usr/bin/env python3
"""
Generate RSA-2048 keypair for JWT signing.
Output is formatted for use in .env (literal \\n, not actual newlines).

Usage:
    uv run scripts/generate_rsa_keys.py
"""
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa


def main() -> None:
    private_key = rsa.generate_private_key(
        public_exponent=65537,
        key_size=2048,
    )

    private_pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.TraditionalOpenSSL,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode()

    public_pem = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    ).decode()

    def to_env(pem: str) -> str:
        return pem.replace("\n", "\\n")

    print("Add these to your .env file:\n")
    print(f'JWT_PRIVATE_KEY="{to_env(private_pem)}"')
    print(f'JWT_PUBLIC_KEY="{to_env(public_pem)}"')


if __name__ == "__main__":
    main()
