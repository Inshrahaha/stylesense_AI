"""
Crypto utilities — envelope encryption for body measurements.

Body media is the most sensitive data. Measurements are encrypted
at rest using AES-256-GCM with a per-user data key, wrapped by
a master key from the environment.
"""

import base64
import os

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from app.config import get_settings


def _get_master_key() -> bytes:
    """Load the master encryption key from settings."""
    settings = get_settings()
    key_str = settings.master_encryption_key
    # Support both base64 and hex encoded keys
    try:
        key = base64.b64decode(key_str)
    except Exception:
        key = bytes.fromhex(key_str)
    if len(key) != 32:
        raise ValueError("Master encryption key must be 32 bytes (256 bits)")
    return key


def generate_data_key() -> bytes:
    """Generate a random 256-bit data key."""
    return os.urandom(32)


def wrap_key(data_key: bytes, master_key: bytes | None = None) -> bytes:
    """
    Wrap (encrypt) a data key with the master key using AES-256-GCM.
    Returns: nonce (12 bytes) + ciphertext+tag
    """
    if master_key is None:
        master_key = _get_master_key()
    nonce = os.urandom(12)
    aesgcm = AESGCM(master_key)
    ct = aesgcm.encrypt(nonce, data_key, None)
    return nonce + ct


def unwrap_key(wrapped: bytes, master_key: bytes | None = None) -> bytes:
    """Unwrap (decrypt) a data key with the master key."""
    if master_key is None:
        master_key = _get_master_key()
    nonce = wrapped[:12]
    ct = wrapped[12:]
    aesgcm = AESGCM(master_key)
    return aesgcm.decrypt(nonce, ct, None)


def encrypt_data(plaintext: bytes, data_key: bytes) -> bytes:
    """
    Encrypt data using AES-256-GCM.
    Returns: nonce (12 bytes) + ciphertext+tag
    """
    nonce = os.urandom(12)
    aesgcm = AESGCM(data_key)
    ct = aesgcm.encrypt(nonce, plaintext, None)
    return nonce + ct


def decrypt_data(ciphertext: bytes, data_key: bytes) -> bytes:
    """Decrypt data using AES-256-GCM."""
    nonce = ciphertext[:12]
    ct = ciphertext[12:]
    aesgcm = AESGCM(data_key)
    return aesgcm.decrypt(nonce, ct, None)


def encrypt_field(plaintext: str) -> bytes:
    """
    Encrypt a string field using envelope encryption.
    Returns: wrapped_key (44 bytes) + encrypted_data
    The data key is generated fresh each time and wrapped with the master key.
    """
    data_key = generate_data_key()
    wrapped = wrap_key(data_key)
    encrypted = encrypt_data(plaintext.encode("utf-8"), data_key)
    # Store as: len(wrapped) as 2 bytes + wrapped_key + encrypted_data
    wlen = len(wrapped).to_bytes(2, "big")
    return wlen + wrapped + encrypted


def decrypt_field(blob: bytes) -> str:
    """Decrypt a field encrypted with encrypt_field."""
    wlen = int.from_bytes(blob[:2], "big")
    wrapped = blob[2:2 + wlen]
    encrypted = blob[2 + wlen:]
    data_key = unwrap_key(wrapped)
    return decrypt_data(encrypted, data_key).decode("utf-8")
