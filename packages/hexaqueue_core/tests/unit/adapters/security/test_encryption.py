"""Unit tests for local envelope encryption adapter."""

import os

import pytest

from hexaqueue_core.adapters.security.encryption import (
    LocalEnvelopeEncryptionAdapter,
)
from hexaqueue_core.domain.exceptions import HexaqueueError


@pytest.mark.asyncio
async def test_envelope_encryption_roundtrip() -> None:
    """Verify encryption and decryption roundtrip produces identical plaintext."""
    adapter = LocalEnvelopeEncryptionAdapter()
    original_data = b"secret hypervisor credentials and test binary"
    context = {"job_id": "job-101", "tenant_id": "acme-corp"}

    envelope = await adapter.encrypt(original_data, context=context)
    algo = envelope.algorithm
    assert algo == "AES-256-GCM"
    ct_len = len(envelope.ciphertext)
    assert ct_len == len(original_data)

    decrypted = await adapter.decrypt(envelope)
    assert decrypted == original_data


@pytest.mark.asyncio
async def test_envelope_tamper_ciphertext_detection() -> None:
    """Verify tampering with ciphertext triggers authentication tag failure."""
    adapter = LocalEnvelopeEncryptionAdapter()
    data = b"confidential cluster workload configuration"

    envelope = await adapter.encrypt(data)

    # Flip one byte in ciphertext
    tampered_bytes = bytearray(envelope.ciphertext)
    tampered_bytes[0] ^= 0xFF
    tampered_env = envelope.model_copy(update={"ciphertext": bytes(tampered_bytes)})

    with pytest.raises(HexaqueueError, match="authentication tag verification failed"):
        await adapter.decrypt(tampered_env)


@pytest.mark.asyncio
async def test_envelope_tamper_context_detection() -> None:
    """Verify modifying AAD context causes authentication tag verification to fail."""
    adapter = LocalEnvelopeEncryptionAdapter()
    data = b"sensitive dataset payload"
    envelope = await adapter.encrypt(data, context={"tenant": "tenant-A"})

    tampered_env = envelope.model_copy(update={"context": {"tenant": "tenant-B"}})

    with pytest.raises(HexaqueueError, match="authentication tag verification failed"):
        await adapter.decrypt(tampered_env)


@pytest.mark.asyncio
async def test_envelope_tamper_wrapped_dek_detection() -> None:
    """Verify tampering with wrapped DEK triggers master key unwrapping failure."""
    adapter = LocalEnvelopeEncryptionAdapter()
    data = b"test payload"
    envelope = await adapter.encrypt(data)

    tampered_dek = bytearray(envelope.encrypted_dek)
    tampered_dek[15] ^= 0xFF
    tampered_env = envelope.model_copy(update={"encrypted_dek": bytes(tampered_dek)})

    with pytest.raises(HexaqueueError, match="master KEK could not unwrap DEK"):
        await adapter.decrypt(tampered_env)


def test_invalid_master_key_length() -> None:
    """Verify invalid master key lengths raise ValueError."""
    with pytest.raises(ValueError, match="Master key must be exactly 32 bytes"):
        LocalEnvelopeEncryptionAdapter(master_key=b"too-short")


@pytest.mark.asyncio
async def test_different_master_key_cannot_decrypt() -> None:
    """Verify an envelope encrypted under one master key cannot be decrypted by another."""
    key1 = os.urandom(32)
    key2 = os.urandom(32)

    adapter1 = LocalEnvelopeEncryptionAdapter(master_key=key1)
    adapter2 = LocalEnvelopeEncryptionAdapter(master_key=key2)

    data = b"cross-cluster confidential payload"
    envelope = await adapter1.encrypt(data)

    with pytest.raises(HexaqueueError, match="master KEK could not unwrap DEK"):
        await adapter2.decrypt(envelope)
