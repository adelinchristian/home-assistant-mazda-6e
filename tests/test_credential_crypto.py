"""Tests for Mazda cloud-control signing."""

import base64

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa

from custom_components.mazda_6e.credential_crypto import sign_control_payload


def test_sign_control_payload_sorts_fields_and_lowercases_booleans():
    """Mazda signs payload fields lexicographically, excluding the signature itself."""
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    private_der = private_key.private_bytes(
        serialization.Encoding.DER,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    )
    signature = sign_control_payload(
        {"vehicleId": "42", "enabled": True, "targetTemp": 210, "sign": "ignored"},
        base64.encodebytes(private_der).decode(),
    )

    private_key.public_key().verify(
        base64.b64decode(signature),
        b"enabled=true&targetTemp=210&vehicleId=42",
        padding.PKCS1v15(),
        hashes.SHA256(),
    )


def test_sign_control_payload_can_omit_unsigned_command_fields():
    """Window and trunk commands omit their command discriminator from the signature."""
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    private_der = private_key.private_bytes(
        serialization.Encoding.DER,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    )
    signature = sign_control_payload(
        {"command": "window", "open": True, "openType": 10, "vehicleId": "42"},
        base64.encodebytes(private_der).decode(),
        omit_keys={"command"},
    )

    private_key.public_key().verify(
        base64.b64decode(signature),
        b"open=true&openType=10&vehicleId=42",
        padding.PKCS1v15(),
        hashes.SHA256(),
    )