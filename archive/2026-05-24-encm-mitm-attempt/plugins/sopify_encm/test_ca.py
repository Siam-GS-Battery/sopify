"""CA cert generation tests."""
from __future__ import annotations

import datetime

from cryptography import x509

from plugins.sopify_encm.ca import (
    ca_cert_pem,
    cert_expiry,
    cert_subject,
    generate_ca,
)


def test_generate_creates_key_and_cert(tmp_path):
    key_path, cert_path = generate_ca(tmp_path)
    assert key_path.exists()
    assert cert_path.exists()
    # Bundle file is concatenation used by mitmproxy --certs
    assert (tmp_path / "ca-bundle.pem").exists()


def test_generate_is_idempotent(tmp_path):
    """Default behaviour: don't regenerate if files exist (overwrite=False)."""
    k1, c1 = generate_ca(tmp_path)
    mtime1 = c1.stat().st_mtime
    k2, c2 = generate_ca(tmp_path)
    mtime2 = c2.stat().st_mtime
    assert mtime1 == mtime2
    assert k1 == k2 and c1 == c2


def test_generate_overwrite_replaces(tmp_path):
    k1, c1 = generate_ca(tmp_path)
    serial1 = x509.load_pem_x509_certificate(c1.read_bytes()).serial_number
    k2, c2 = generate_ca(tmp_path, overwrite=True)
    serial2 = x509.load_pem_x509_certificate(c2.read_bytes()).serial_number
    assert serial1 != serial2  # new random serial → fresh cert


def test_cert_has_ca_basic_constraint(tmp_path):
    """The CA cert MUST be marked as CA=True or browsers/curl reject it for
    leaf-cert signing."""
    _, cert_path = generate_ca(tmp_path)
    cert = x509.load_pem_x509_certificate(cert_path.read_bytes())
    bc = cert.extensions.get_extension_for_class(x509.BasicConstraints).value
    assert bc.ca is True
    assert bc.path_length == 0  # may only sign leaf certs, not sub-CAs


def test_cert_valid_for_5_years(tmp_path):
    """Issuance window — 5 years matches Mozilla policy for ops CAs."""
    _, cert_path = generate_ca(tmp_path)
    cert = x509.load_pem_x509_certificate(cert_path.read_bytes())
    delta = cert.not_valid_after_utc - cert.not_valid_before_utc
    # Allow ±2 days slack so a leap year doesn't break the assertion.
    assert datetime.timedelta(days=365 * 5 - 2) <= delta <= datetime.timedelta(days=365 * 5 + 2)


def test_cert_subject_is_sopify_branded(tmp_path):
    generate_ca(tmp_path)
    subject = cert_subject(tmp_path)
    assert "Sopify" in subject
    assert "GS Battery" in subject


def test_key_file_is_mode_600(tmp_path):
    """Private key must not be world- or group-readable."""
    import os
    import stat
    import sys
    if sys.platform.startswith("win"):
        # Windows ACLs don't map to POSIX mode bits — skip
        return
    key_path, _ = generate_ca(tmp_path)
    mode = stat.S_IMODE(os.stat(key_path).st_mode)
    assert mode == 0o600


def test_cert_file_readable_by_group(tmp_path):
    """Cert needs to be world-readable so sandbox `update-ca-certificates`
    can copy it without sudo gymnastics."""
    import os
    import stat
    import sys
    if sys.platform.startswith("win"):
        return
    _, cert_path = generate_ca(tmp_path)
    mode = stat.S_IMODE(os.stat(cert_path).st_mode)
    assert mode == 0o644


def test_ca_cert_pem_returns_bytes(tmp_path):
    generate_ca(tmp_path)
    pem = ca_cert_pem(tmp_path)
    assert pem.startswith(b"-----BEGIN CERTIFICATE-----")
    assert b"-----END CERTIFICATE-----" in pem


def test_cert_expiry_returns_future_datetime(tmp_path):
    generate_ca(tmp_path)
    exp = cert_expiry(tmp_path)
    now = datetime.datetime.now(datetime.timezone.utc)
    assert exp > now + datetime.timedelta(days=365 * 4)  # at least 4 years remaining
