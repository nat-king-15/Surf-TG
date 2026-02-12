"""
AES-GCM encryption/decryption for sensitive data like session strings.
Uses PBKDF2 key derivation with MASTER_KEY and IV_KEY — compatible with source bot.
"""
import base64
import os as osy
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from bot.config import Telegram


def _derive_key(pwd=None, slt=None, length=16):
    """Derive AES key using PBKDF2 — matches source bot's dyk()."""
    pw = (pwd or Telegram.MASTER_KEY).encode()
    sl = (slt or Telegram.IV_KEY).encode()
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=length,
        salt=sl,
        iterations=100000,
    )
    return kdf.derive(pw)


def encrypt(data: str) -> str:
    """
    Encrypt a string using AES-GCM with random nonce.
    Output = base64(nonce + tag + ciphertext).
    Compatible with source bot's ecs().
    """
    key = _derive_key()
    nonce = osy.urandom(12)
    cipher = Cipher(algorithms.AES(key), modes.GCM(nonce))
    enc = cipher.encryptor()
    ct = enc.update(data.encode()) + enc.finalize()
    tag = enc.tag
    return base64.b64encode(nonce + tag + ct).decode()


def decrypt(token: str) -> str:
    """
    Decrypt a base64-encoded ciphertext (nonce + tag + ciphertext).
    Compatible with source bot's dcs().
    """
    key = _derive_key()
    raw = base64.b64decode(token.encode())
    nonce = raw[:12]
    tag = raw[12:28]
    ct = raw[28:]
    cipher = Cipher(algorithms.AES(key), modes.GCM(nonce, tag))
    dec = cipher.decryptor()
    result = dec.update(ct) + dec.finalize()
    return result.decode()
