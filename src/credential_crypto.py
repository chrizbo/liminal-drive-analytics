"""KMS-backed encryption helpers for hosted credentials."""

import base64
import os


KMS_KEY_ENV = "DRIVE_ANALYTICS_KMS_KEY_NAME"


def kms_key_name():
    return os.environ.get(KMS_KEY_ENV, "").strip()


def encrypt_text(plaintext, *, aad=None):
    key_name = kms_key_name()
    if not key_name:
        raise RuntimeError(f"{KMS_KEY_ENV} is required to encrypt hosted credentials")
    try:
        from google.cloud import kms_v1
    except ImportError as exc:
        raise RuntimeError(
            "KMS encryption requires google-cloud-kms. Install dependencies with "
            "`pip3 install -r requirements.txt`."
        ) from exc
    client = kms_v1.KeyManagementServiceClient()
    response = client.encrypt(
        request={
            "name": key_name,
            "plaintext": plaintext.encode("utf-8"),
            "additional_authenticated_data": (aad or "").encode("utf-8"),
        }
    )
    return base64.b64encode(response.ciphertext).decode("ascii")


def decrypt_text(ciphertext, *, aad=None):
    key_name = kms_key_name()
    if not key_name:
        raise RuntimeError(f"{KMS_KEY_ENV} is required to decrypt hosted credentials")
    try:
        from google.cloud import kms_v1
    except ImportError as exc:
        raise RuntimeError(
            "KMS decryption requires google-cloud-kms. Install dependencies with "
            "`pip3 install -r requirements.txt`."
        ) from exc
    client = kms_v1.KeyManagementServiceClient()
    response = client.decrypt(
        request={
            "name": key_name,
            "ciphertext": base64.b64decode(ciphertext.encode("ascii")),
            "additional_authenticated_data": (aad or "").encode("utf-8"),
        }
    )
    return response.plaintext.decode("utf-8")
