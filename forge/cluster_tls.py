"""LoomCluster TLS / mTLS transport (post-F9, 0.9.1; INFERENCE C-99).

Q6 (0.7.14) made node↔node traffic *authenticated* (HMAC with the fleet secret) but not *encrypted*. This module adds an
optional TLS 1.3 transport with mutual certificate authentication from a private **fleet CA**:

* ``forge cluster tls-keygen --name <node> [--host <dns-or-ip> …]`` creates (once) a self-signed fleet CA
  (``ca.pem`` + ``ca.key.pem``, ECDSA P-256) and a leaf certificate for each named node / operator, signed by that CA,
  with both ``serverAuth`` and ``clientAuth`` usages and the given hosts as SANs (``localhost``, ``127.0.0.1`` and
  ``::1`` are always included). Everything lives under ``.fabric/cluster-tls/`` (gitignored, keys mode 0600).
* A node with TLS enabled serves ``https://`` only, **requires a client certificate signed by the fleet CA** (mTLS) and
  still checks the HMAC fleet signature on every request — defence in depth: a stolen cert without the secret, or the
  secret without a cert, gets nothing. Clients verify the server certificate chain *and* hostname against the fleet CA
  (the public web PKI is not trusted), and refuse plaintext ``http://`` peers while TLS is on (no downgrade).

Enable with ``FORGE_CLUSTER_TLS_DIR=<dir>`` (or ``cluster.protocol.tls.dir`` in forge.yaml); the cert/key used by this
process is ``nodes/<name>.pem`` / ``nodes/<name>.key.pem`` where name = ``FORGE_CLUSTER_TLS_NAME``, else the node id
(``forge cluster node``), else ``operator`` (CLI clients). See docs/cluster-lan-runbook.md.
"""

from __future__ import annotations

import datetime as _dt
import ipaddress
import os
import re
import socket
import ssl
from pathlib import Path
from typing import Any

TLS_REL = ".fabric/cluster-tls"
DIR_ENV = "FORGE_CLUSTER_TLS_DIR"
NAME_ENV = "FORGE_CLUSTER_TLS_NAME"
DEFAULT_HOSTS = ("localhost", "127.0.0.1", "::1")
NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,62}$")
CA_DAYS = 825
LEAF_DAYS = 397


class ClusterTLSError(RuntimeError):
    pass


def _crypto():
    try:
        from cryptography import x509
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import ec
        from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID
    except ImportError as e:  # pragma: no cover - dev/liveops extra installs it
        raise ClusterTLSError("`forge cluster tls-keygen` needs the `cryptography` package (pip install -e .[liveops])") from e
    return x509, hashes, serialization, ec, ExtendedKeyUsageOID, NameOID


def default_dir(root: Path | None = None) -> Path:
    from forge.paths import find_repo_root

    return (root or find_repo_root()) / TLS_REL


def _write_private(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        path.unlink()
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "wb") as f:
        f.write(data)


def _now() -> _dt.datetime:
    return _dt.datetime.now(_dt.timezone.utc)


def ensure_ca(tls_dir: Path) -> tuple[Path, Path]:
    """Create the fleet CA once (never overwritten — re-issuing it would orphan every node certificate)."""
    x509, hashes, serialization, ec, _eku, NameOID = _crypto()
    ca_pem, ca_key = tls_dir / "ca.pem", tls_dir / "ca.key.pem"
    if ca_pem.exists() and ca_key.exists():
        return ca_pem, ca_key
    key = ec.generate_private_key(ec.SECP256R1())
    name = x509.Name([x509.NameAttribute(NameOID.ORGANIZATION_NAME, "AssetFabric LoomCluster"),
                      x509.NameAttribute(NameOID.COMMON_NAME, "LoomCluster fleet CA")])
    now = _now()
    cert = (x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(key.public_key())
            .serial_number(x509.random_serial_number()).not_valid_before(now - _dt.timedelta(minutes=5))
            .not_valid_after(now + _dt.timedelta(days=CA_DAYS))
            .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
            .add_extension(x509.KeyUsage(digital_signature=True, key_cert_sign=True, crl_sign=True, content_commitment=False,
                                         key_encipherment=False, data_encipherment=False, key_agreement=False,
                                         encipher_only=False, decipher_only=False), critical=True)
            .add_extension(x509.SubjectKeyIdentifier.from_public_key(key.public_key()), critical=False)
            .sign(key, hashes.SHA256()))
    _write_private(ca_key, key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                             serialization.NoEncryption()))
    tls_dir.mkdir(parents=True, exist_ok=True)
    ca_pem.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    return ca_pem, ca_key


def _san(hosts: list[str]):
    x509 = _crypto()[0]
    out, seen = [], set()
    for h in [*DEFAULT_HOSTS, *hosts]:
        h = h.strip()
        if not h or h in seen:
            continue
        seen.add(h)
        try:
            out.append(x509.IPAddress(ipaddress.ip_address(h)))
        except ValueError:
            out.append(x509.DNSName(h))
    return out


def issue(tls_dir: Path, name: str, hosts: list[str] | None = None) -> dict[str, Any]:
    """Issue (or re-issue) the leaf certificate for one node/operator, signed by the fleet CA."""
    if not NAME_RE.match(name):
        raise ClusterTLSError(f"bad certificate name {name!r} (letters, digits, . _ - ; ≤ 63 chars)")
    x509, hashes, serialization, ec, EKU, NameOID = _crypto()
    ca_pem, ca_key_p = ensure_ca(tls_dir)
    ca = x509.load_pem_x509_certificate(ca_pem.read_bytes())
    ca_key = serialization.load_pem_private_key(ca_key_p.read_bytes(), password=None)
    key = ec.generate_private_key(ec.SECP256R1())
    now = _now()
    cert = (x509.CertificateBuilder()
            .subject_name(x509.Name([x509.NameAttribute(NameOID.ORGANIZATION_NAME, "AssetFabric LoomCluster"),
                                     x509.NameAttribute(NameOID.COMMON_NAME, name)]))
            .issuer_name(ca.subject).public_key(key.public_key()).serial_number(x509.random_serial_number())
            .not_valid_before(now - _dt.timedelta(minutes=5)).not_valid_after(now + _dt.timedelta(days=LEAF_DAYS))
            .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
            .add_extension(x509.KeyUsage(digital_signature=True, key_encipherment=False, key_cert_sign=False, crl_sign=False,
                                         content_commitment=False, data_encipherment=False, key_agreement=False,
                                         encipher_only=False, decipher_only=False), critical=True)
            .add_extension(x509.ExtendedKeyUsage([EKU.SERVER_AUTH, EKU.CLIENT_AUTH]), critical=False)
            .add_extension(x509.SubjectAlternativeName(_san(list(hosts or []))), critical=False)
            .add_extension(x509.AuthorityKeyIdentifier.from_issuer_public_key(ca_key.public_key()), critical=False)
            .sign(ca_key, hashes.SHA256()))
    nd = tls_dir / "nodes"
    nd.mkdir(parents=True, exist_ok=True)
    _write_private(nd / f"{name}.key.pem", key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                                             serialization.NoEncryption()))
    (nd / f"{name}.pem").write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    sans = [str(getattr(s, "value", s)) for s in _san(list(hosts or []))]
    return {"ca": str(ca_pem), "cert": str(nd / f"{name}.pem"), "key": str(nd / f"{name}.key.pem"), "name": name,
            "hosts": sans, "not_after": cert.not_valid_after_utc.isoformat()}


def keygen(tls_dir: Path, names: list[str], hosts: list[str] | None = None) -> dict[str, Any]:
    ensure_ca(tls_dir)
    return {"dir": str(tls_dir), "ca": str(tls_dir / "ca.pem"), "issued": [issue(tls_dir, n, hosts) for n in names]}


# --------------------------------------------------------------------------- runtime config


def tls_dir_from_env(cfg: dict[str, Any] | None = None) -> Path | None:
    d = os.environ.get(DIR_ENV, "").strip()
    if not d and cfg:
        t = cfg.get("tls") or {}
        if isinstance(t, dict) and t.get("enabled") and t.get("dir"):
            d = str(t["dir"])
            if not os.path.isabs(d):
                from forge.paths import find_repo_root

                d = str(find_repo_root() / d)
    return Path(d) if d else None


def enabled(cfg: dict[str, Any] | None = None) -> bool:
    return tls_dir_from_env(cfg) is not None


def _material(name: str | None, cfg: dict[str, Any] | None = None) -> tuple[Path, Path, Path]:
    d = tls_dir_from_env(cfg)
    if d is None:
        raise ClusterTLSError("cluster TLS is not enabled")
    n = os.environ.get(NAME_ENV, "").strip() or name or "operator"
    ca, cert, key = d / "ca.pem", d / "nodes" / f"{n}.pem", d / "nodes" / f"{n}.key.pem"
    missing = [str(p) for p in (ca, cert, key) if not p.exists()]
    if missing:
        raise ClusterTLSError(f"cluster TLS material missing: {', '.join(missing)} "
                              f"(run `forge cluster tls-keygen --name {n}` on the CA host and copy it here)")
    return ca, cert, key


def server_context(name: str | None, cfg: dict[str, Any] | None = None) -> ssl.SSLContext:
    """TLS ≥ 1.3, own cert chain, client certificate REQUIRED and verified against the fleet CA (mTLS)."""
    ca, cert, key = _material(name, cfg)
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.minimum_version = ssl.TLSVersion.TLSv1_3
    ctx.load_cert_chain(cert, key)
    ctx.load_verify_locations(cafile=str(ca))
    ctx.verify_mode = ssl.CERT_REQUIRED
    return ctx


def client_context(name: str | None, cfg: dict[str, Any] | None = None) -> ssl.SSLContext:
    """Verify the server against the fleet CA only (+ hostname), present our own cert for mTLS."""
    ca, cert, key = _material(name, cfg)
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    ctx.minimum_version = ssl.TLSVersion.TLSv1_3
    ctx.check_hostname = True
    ctx.verify_mode = ssl.CERT_REQUIRED
    ctx.load_verify_locations(cafile=str(ca))
    ctx.load_cert_chain(cert, key)
    return ctx


def peer_name(sock: Any) -> str:
    """Common name of the verified peer certificate (for logs/status)."""
    try:
        cert = sock.getpeercert() or {}
        for rdn in cert.get("subject", ()):
            for k, v in rdn:
                if k == "commonName":
                    return str(v)
    except (AttributeError, ValueError, OSError):
        pass
    return ""


def describe(tls_dir: Path) -> dict[str, Any]:
    """What is in a TLS dir (no key material printed)."""
    x509 = _crypto()[0]
    out: dict[str, Any] = {"dir": str(tls_dir), "ca": None, "nodes": {}}
    if (tls_dir / "ca.pem").exists():
        ca = x509.load_pem_x509_certificate((tls_dir / "ca.pem").read_bytes())
        out["ca"] = {"subject": ca.subject.rfc4514_string(), "not_after": ca.not_valid_after_utc.isoformat(),
                     "key_present": (tls_dir / "ca.key.pem").exists()}
    for p in sorted((tls_dir / "nodes").glob("*.pem")) if (tls_dir / "nodes").exists() else []:
        if p.name.endswith(".key.pem"):
            continue
        c = x509.load_pem_x509_certificate(p.read_bytes())
        try:
            sans = [str(v) for v in c.extensions.get_extension_for_class(x509.SubjectAlternativeName).value
                    .get_values_for_type(x509.DNSName)]
            sans += [str(v) for v in c.extensions.get_extension_for_class(x509.SubjectAlternativeName).value
                     .get_values_for_type(x509.IPAddress)]
        except x509.ExtensionNotFound:
            sans = []
        out["nodes"][p.stem] = {"hosts": sans, "not_after": c.not_valid_after_utc.isoformat(),
                                "key_present": (p.parent / f"{p.stem}.key.pem").exists()}
    return out


def local_hosts() -> list[str]:
    """Hostname (+ FQDN) of this machine — a sensible default SAN set for `tls-keygen --this-host`."""
    hs = {socket.gethostname()}
    try:
        hs.add(socket.getfqdn())
    except OSError:
        pass
    return sorted(h for h in hs if h)
