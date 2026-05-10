#!/usr/bin/env python3
"""One-time script to generate VAPID key pair for Web Push notifications.

Run with: python scripts/generate_vapid_keys.py

Then upload each value to GCP Secret Manager as instructed in the output.
The 'cryptography' package is already a project dependency.
"""
import base64
from cryptography.hazmat.primitives.asymmetric.ec import generate_private_key, SECP256R1
from cryptography.hazmat.primitives.serialization import (
    Encoding,
    PublicFormat,
    PrivateFormat,
    NoEncryption,
)


def b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


key = generate_private_key(SECP256R1())
private_key = b64url(key.private_numbers().private_value.to_bytes(32, "big"))
public_key = b64url(key.public_key().public_bytes(Encoding.X962, PublicFormat.UncompressedPoint))

print("=" * 60)
print("VAPID keys generated. Store these in GCP Secret Manager.")
print("=" * 60)
print()
print("Private key (secret name: vapid-private-key):")
print(private_key)
print()
print("Public key (secret name: vapid-public-key):")
print(public_key)
print()
print("Upload commands:")
print(f'  printf "%s" "{private_key}" | gcloud secrets versions add vapid-private-key --data-file=- --project=bartenders-464918')
print(f'  printf "%s" "{public_key}" | gcloud secrets versions add vapid-public-key --data-file=- --project=bartenders-464918')
