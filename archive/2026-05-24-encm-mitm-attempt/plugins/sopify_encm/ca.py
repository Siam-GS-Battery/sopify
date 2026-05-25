"""CA cert generation for HTTPS interception by the ENCM proxy.

We generate a self-signed CA that mitmproxy uses to sign per-host certs on
the fly. The CA cert itself is installed into the sandbox's trust store so
HTTPS requests through the proxy validate cleanly inside the microVM.

Threat model: the CA is trusted ONLY inside the sandbox — host OS doesn't
import it, so an escaped CA key can only impact sandbox traffic (which is
already proxied). The key still lives at 0600.

Layout:
  ~/.sopify/encm-ca/
    ├── ca.key       (ed25519 private, 0600)
    ├── ca.crt       (X.509 self-signed, valid 5y, 0644)
    └── ca-bundle    (concatenation for mitmproxy's `--set certs` flag)
"""
from __future__ import annotations

import datetime
import os
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID

# RSA chosen over ed25519 because mitmproxy still expects RSA CAs for per-host
# leaf signing in some code paths. 4096 bits matches Mozilla policy for new CAs.
_KEY_SIZE = 4096
_VALID_YEARS = 5

# Default install path — overridable via env so docker installs land in the
# image at build time, while host installs use the user's home dir.
DEFAULT_CA_DIR = Path(os.environ.get("SOPIFY_ENCM_CA_DIR", "~/.sopify/encm-ca")).expanduser()


def _ca_subject() -> x509.Name:
    return x509.Name([
        x509.NameAttribute(NameOID.COUNTRY_NAME, "TH"),
        x509.NameAttribute(NameOID.ORGANIZATION_NAME, "GS Battery"),
        x509.NameAttribute(NameOID.ORGANIZATIONAL_UNIT_NAME, "Sopify ENCM"),
        x509.NameAttribute(NameOID.COMMON_NAME, "Sopify Network Control CA"),
    ])


def generate_ca(out_dir: str | Path | None = None, *, overwrite: bool = False) -> tuple[Path, Path]:
    """Generate a new CA key + cert pair. Returns (key_path, cert_path).

    If files already exist and ``overwrite=False``, returns the existing paths
    without regenerating — this is what ``sopify install`` should call.

    The cert is valid from now to now + 5 years. Backdating start by 1 day so
    clock drift on a fresh laptop doesn't immediately invalidate it.
    """
    out_dir = Path(out_dir or DEFAULT_CA_DIR).expanduser()
    out_dir.mkdir(parents=True, exist_ok=True)
    # Lock down the directory — only owner reads.
    try:
        os.chmod(out_dir, 0o700)
    except (PermissionError, NotImplementedError):
        pass  # Windows / mounted filesystems with restricted chmod

    key_path = out_dir / "ca.key"
    cert_path = out_dir / "ca.crt"
    bundle_path = out_dir / "ca-bundle.pem"

    if not overwrite and key_path.exists() and cert_path.exists():
        return key_path, cert_path

    # ── private key ────────────────────────────────────────────────────
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=_KEY_SIZE)

    # ── cert ───────────────────────────────────────────────────────────
    now = datetime.datetime.now(datetime.timezone.utc)
    subject = issuer = _ca_subject()

    builder = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(issuer)
        .public_key(private_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - datetime.timedelta(days=1))
        .not_valid_after(now + datetime.timedelta(days=365 * _VALID_YEARS))
        # CA constraint — this cert may sign other certs.
        .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
        # Key usage — only the CA-relevant flags. mitmproxy leaf certs will
        # have their own KU.
        .add_extension(
            x509.KeyUsage(
                digital_signature=True, content_commitment=False,
                key_encipherment=False, data_encipherment=False,
                key_agreement=False, key_cert_sign=True, crl_sign=True,
                encipher_only=False, decipher_only=False,
            ),
            critical=True,
        )
        .add_extension(
            x509.SubjectKeyIdentifier.from_public_key(private_key.public_key()),
            critical=False,
        )
    )
    cert = builder.sign(private_key=private_key, algorithm=hashes.SHA256())

    # ── persist ────────────────────────────────────────────────────────
    key_bytes = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.TraditionalOpenSSL,
        encryption_algorithm=serialization.NoEncryption(),
    )
    cert_bytes = cert.public_bytes(serialization.Encoding.PEM)

    key_path.write_bytes(key_bytes)
    cert_path.write_bytes(cert_bytes)
    # mitmproxy expects a single file with key + cert concatenated for `certs`.
    bundle_path.write_bytes(key_bytes + b"\n" + cert_bytes)

    # File modes — key strict 0600, cert + bundle 0644 (cert needs to be readable
    # for trust-store install inside the sandbox).
    try:
        os.chmod(key_path, 0o600)
        os.chmod(bundle_path, 0o600)
        os.chmod(cert_path, 0o644)
    except (PermissionError, NotImplementedError):
        pass

    return key_path, cert_path


def ca_cert_pem(out_dir: str | Path | None = None) -> bytes:
    """Read the public cert. Used by the sandbox installer to drop it into
    /usr/local/share/ca-certificates/."""
    out_dir = Path(out_dir or DEFAULT_CA_DIR).expanduser()
    return (out_dir / "ca.crt").read_bytes()


def cert_subject(out_dir: str | Path | None = None) -> str:
    """Inspect the CA cert subject. Used by ``sopify doctor``."""
    pem = ca_cert_pem(out_dir)
    cert = x509.load_pem_x509_certificate(pem)
    return cert.subject.rfc4514_string()


def cert_expiry(out_dir: str | Path | None = None) -> datetime.datetime:
    """Return the cert's `not_valid_after` (UTC). Used by ``sopify doctor`` to
    warn about expiring CAs."""
    pem = ca_cert_pem(out_dir)
    cert = x509.load_pem_x509_certificate(pem)
    return cert.not_valid_after_utc
