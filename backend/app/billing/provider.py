"""Payment gateway (AI-BOUNDARY 2.0.0 § Token Kanal & Pembayaran).

`fake` = mode uji (development/CI): tanpa uang sungguhan, tagihan dilunasi owner lewat endpoint simulasi (bukan di
produksi). `midtrans` = Snap API; status lunas HANYA dari webhook bertanda tangan valid. Server key hanya di `.env`
server; tidak pernah dicatat di log atau dikirim ke browser. Platform tidak pernah menerima data kartu/rekening.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import urllib.error
import urllib.request
from dataclasses import dataclass

PROVIDERS = ("fake", "midtrans")
SANDBOX_SNAP = "https://app.sandbox.midtrans.com/snap/v1/transactions"
PRODUCTION_SNAP = "https://app.midtrans.com/snap/v1/transactions"


@dataclass(frozen=True)
class BillingSettings:
    enabled: bool
    provider: str
    midtrans_server_key: str
    midtrans_production: bool
    environment: str


def billing_settings() -> BillingSettings:
    provider = (os.environ.get("CLAU_PAYMENT_PROVIDER") or "fake").strip()
    return BillingSettings(
        # Fail closed: provider tak dikenal = pembayaran mati (checkout ditolak); kredit yang ada tetap bisa dipakai.
        enabled=provider in PROVIDERS and (provider != "midtrans" or bool(os.environ.get("CLAU_MIDTRANS_SERVER_KEY"))),
        provider=provider,
        midtrans_server_key=os.environ.get("CLAU_MIDTRANS_SERVER_KEY") or "",
        midtrans_production=os.environ.get("CLAU_MIDTRANS_PRODUCTION") == "1",
        environment=os.environ.get("CLAU_ENV") or "development",
    )


class GatewayError(Exception):
    """Gateway menolak / tidak bisa dihubungi. Pesan aman (tanpa key, tanpa body mentah)."""


def create_payment_url(settings: BillingSettings, order_id: str, amount_idr: int, item_name: str) -> str | None:
    if settings.provider == "fake":
        return None
    body = json.dumps({
        "transaction_details": {"order_id": order_id, "gross_amount": amount_idr},
        "item_details": [{"id": order_id, "price": amount_idr, "quantity": 1, "name": item_name[:50]}],
        "credit_card": {"secure": True},
    }).encode()
    auth = base64.b64encode(f"{settings.midtrans_server_key}:".encode()).decode()
    req = urllib.request.Request(
        PRODUCTION_SNAP if settings.midtrans_production else SANDBOX_SNAP, data=body, method="POST",
        headers={"Content-Type": "application/json", "Accept": "application/json", "Authorization": f"Basic {auth}"},
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as res:  # noqa: S310 (URL tetap, bukan dari input)
            url = json.loads(res.read().decode()).get("redirect_url")
    except (urllib.error.URLError, TimeoutError, ValueError) as exc:
        raise GatewayError("payment_gateway_unavailable") from exc
    if not isinstance(url, str) or not url.startswith("https://"):
        raise GatewayError("payment_gateway_unavailable")
    return url


def midtrans_signature(order_id: str, status_code: str, gross_amount: str, server_key: str) -> str:
    return hashlib.sha512(f"{order_id}{status_code}{gross_amount}{server_key}".encode()).hexdigest()


def midtrans_signature_valid(payload: dict, server_key: str) -> bool:
    if not server_key:
        return False
    parts = [payload.get(k) for k in ("order_id", "status_code", "gross_amount", "signature_key")]
    if not all(isinstance(p, str) and p for p in parts):
        return False
    expected = midtrans_signature(parts[0], parts[1], parts[2], server_key)
    return hmac.compare_digest(expected, parts[3])


def midtrans_outcome(payload: dict) -> str | None:
    """Status Midtrans → status tagihan. None = belum final (abaikan)."""
    status = payload.get("transaction_status")
    if status == "settlement" or (status == "capture" and payload.get("fraud_status") in (None, "accept")):
        return "paid"
    if status == "expire":
        return "expired"
    if status in ("cancel", "deny", "failure"):
        return "failed"
    return None
