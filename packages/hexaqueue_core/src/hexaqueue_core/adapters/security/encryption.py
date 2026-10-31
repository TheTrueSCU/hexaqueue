"""Local envelope encryption adapter using AES-256-GCM.

Notes/Architectural Intent:
    Implements EnvelopeEncryptionPort using cryptographic DEK/KEK key hierarchy.
    Every payload is encrypted under a freshly generated 256-bit ephemeral Data
    Encryption Key (DEK), which is wrapped by a master Key Encryption Key (KEK).
"""

from __future__ import annotations

import json
import os

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from hexaqueue_core.domain.exceptions import HexaqueueError
from hexaqueue_core.domain.security import EncryptedEnvelope
from hexaqueue_core.ports.security import EnvelopeEncryptionPort


class LocalEnvelopeEncryptionAdapter(EnvelopeEncryptionPort):
    """Local AES-256-GCM envelope encryption adapter.

    Args:
        master_key: 32-byte master key (KEK). If None, generates a cryptographically random 256-bit key.
        key_id: Identifier of the master key (defaults to 'kek-primary').
    """

    def __init__(
        self,
        master_key: bytes | None = None,
        key_id: str = "kek-primary",
    ) -> None:
        if master_key is not None:
            if len(master_key) != 32:
                msg = f"Master key must be exactly 32 bytes (256 bits); got {len(master_key)}"
                raise ValueError(msg)
            self._kek = master_key
        else:
            self._kek = os.urandom(32)

        self._key_id = key_id

    def _serialize_aad(self, context: dict[str, str] | None) -> bytes:
        """Deterministically serialize Additional Authenticated Data (AAD) dictionary."""
        if not context:
            return b""
        return json.dumps(context, sort_keys=True).encode("utf-8")

    async def encrypt(
        self,
        data: bytes,
        key_id: str | None = None,
        context: dict[str, str] | None = None,
    ) -> EncryptedEnvelope:
        """Encrypt payload data using a freshly minted ephemeral DEK wrapped by a master KEK.

        Args:
            data: Raw plaintext payload bytes.
            key_id: Optional master key identifier override.
            context: Optional Additional Authenticated Data (AAD) dictionary.

        Returns:
            EncryptedEnvelope holding ciphertext, wrapped DEK, IV, tag, and context.
        """
        active_key_id = key_id or self._key_id

        # 1. Generate ephemeral 256-bit Data Encryption Key (DEK)
        dek = os.urandom(32)
        dek_cipher = AESGCM(dek)

        # 2. Encrypt payload under DEK with 12-byte IV and AAD
        iv = os.urandom(12)
        aad = self._serialize_aad(context)
        ct_with_tag = dek_cipher.encrypt(iv, data, aad)
        ciphertext = ct_with_tag[:-16]
        tag = ct_with_tag[-16:]

        # 3. Wrap (encrypt) the DEK under master KEK
        kek_cipher = AESGCM(self._kek)
        dek_iv = os.urandom(12)
        wrapped_dek_bytes = kek_cipher.encrypt(dek_iv, dek, b"HEXAQUEUE_DEK_WRAP")
        encrypted_dek = dek_iv + wrapped_dek_bytes

        return EncryptedEnvelope(
            algorithm="AES-256-GCM",
            ciphertext=ciphertext,
            context=dict(context or {}),
            encrypted_dek=encrypted_dek,
            iv=iv,
            key_id=active_key_id,
            tag=tag,
        )

    async def decrypt(self, envelope: EncryptedEnvelope) -> bytes:
        """Decrypt an envelope by unwrapping its DEK and deciphering the payload.

        Args:
            envelope: EncryptedEnvelope containing ciphertext and wrapped DEK.

        Returns:
            Decrypted plaintext bytes.

        Raises:
            HexaqueueError: If cipher tag validation fails or envelope is corrupt.
        """
        if envelope.algorithm != "AES-256-GCM":
            msg = f"Unsupported envelope encryption algorithm '{envelope.algorithm}'"
            raise HexaqueueError(msg)

        if len(envelope.encrypted_dek) < 28:
            msg = "Corrupted encrypted DEK payload (insufficient length)"
            raise HexaqueueError(msg)

        # 1. Unwrap DEK using master KEK
        dek_iv = envelope.encrypted_dek[:12]
        wrapped_dek = envelope.encrypted_dek[12:]
        kek_cipher = AESGCM(self._kek)

        try:
            dek = kek_cipher.decrypt(dek_iv, wrapped_dek, b"HEXAQUEUE_DEK_WRAP")
        except InvalidTag as exc:
            msg = "Envelope decryption failed: master KEK could not unwrap DEK (tampered or wrong key)"
            raise HexaqueueError(msg) from exc

        # 2. Decrypt payload using unwrapped DEK and verify tag + AAD
        dek_cipher = AESGCM(dek)
        ct_with_tag = envelope.ciphertext + envelope.tag
        aad = self._serialize_aad(envelope.context)

        try:
            return dek_cipher.decrypt(envelope.iv, ct_with_tag, aad)
        except InvalidTag as exc:
            msg = "Envelope decryption failed: authentication tag verification failed (tampered ciphertext or context)"
            raise HexaqueueError(msg) from exc


__all__ = [
    "LocalEnvelopeEncryptionAdapter",
]
