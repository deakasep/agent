"""Provider Claude (Tahap 2 PR 4c, TASK-004): memanggil Claude Messages API dengan antarmuka yang sama dengan
FakeProvider (app/ai/provider.py).

Aktif hanya bila owner mengisi di .env server: `CLAU_AI_PROVIDER=claude`, `ANTHROPIC_API_KEY`, dan tarif model
(`CLAU_AI_PRICE_*`, mikro-USD per juta token). Kunci API hanya di container `worker`. Tarif tidak pernah ditulis di kode: biaya setiap panggilan dihitung dari
tarif owner supaya batas biaya (budget) tetap bekerja. Salah satu kosong = AI mati (fail closed, app/ai/config.py).

Data yang dikirim: aturan + agent (system, di-cache), fakta yang DISETUJUI klien, teks request yang sudah disamarkan
(AI-BOUNDARY § Data ke Provider AI). Jawaban wajib JSON terstruktur: isi draft + klaim; label bukti klaim tetap
ditentukan fact-check di worker, bukan model.
"""

from __future__ import annotations

import json
import os
import socket
import urllib.error
import urllib.request
from dataclasses import dataclass

from app.ai.provider import ClaimOut, Generation, Prompt, ProviderFailure, Usage
from app.db.models import CLAIM_CATEGORIES

API_URL = "https://api.anthropic.com/v1/messages"
API_VERSION = "2023-06-01"
# Model per Mode AI (clau-market pricing.md §3a). Nilai bawaan = nama model publik terbaru saat ditulis (2026-11);
# owner bisa menggantinya lewat .env tanpa mengubah kode. Pemilihan mode per job menyusul (UI /requests + catalog).
DEFAULT_MODELS = {"standar": "claude-sonnet-5-5", "ringan": "claude-haiku-5-5", "pro": "claude-fable-5-1"}
RETRYABLE_HTTP = (408, 409, 429, 500, 502, 503, 504, 529)
MAX_RESPONSE_BYTES = 1_048_576

OUTPUT_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["content", "claims"],
    "properties": {
        "content": {"type": "string", "description": "Isi draft siap direview manusia."},
        "claims": {
            "type": "array",
            "description": "Setiap klaim di draft. Klaim fakta tentang bisnis wajib menyebut fact_key dari daftar fakta.",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["text", "category", "fact_key", "implied"],
                "properties": {
                    "text": {"type": "string"},
                    "category": {"type": "string", "enum": list(CLAIM_CATEGORIES)},
                    "fact_key": {"type": ["string", "null"]},
                    "implied": {"type": "boolean"},
                },
            },
        },
    },
}


@dataclass(frozen=True)
class Rates:
    """Tarif owner, mikro-USD per juta token. Cache baca/tulis mengikuti aturan harga provider (0,1× dan 1,25× input)."""

    input: int
    output: int

    def cost(self, input_tokens: int, output_tokens: int, cache_read: int, cache_write: int) -> int:
        micro = (input_tokens * self.input + output_tokens * self.output
                 + cache_read * self.input // 10 + cache_write * self.input * 5 // 4)
        return -(-micro // 1_000_000)  # dibulatkan ke atas: tidak pernah mencatat biaya lebih kecil


def _positive_int(name: str) -> int | None:
    try:
        value = int((os.environ.get(name) or "").strip())
    except ValueError:
        return None
    return value if value > 0 else None


def claude_ready() -> bool:
    """True bila tarif model terisi (dicek backend & worker; fail closed). Kunci API hanya ada di container worker:
    worker tanpa kunci gagal membuat provider, mencatatnya di log, dan job tetap antre sampai kunci diisi."""
    return rates_from_env() is not None


def rates_from_env() -> Rates | None:
    inp, out = _positive_int("CLAU_AI_PRICE_INPUT_MICRO_USD"), _positive_int("CLAU_AI_PRICE_OUTPUT_MICRO_USD")
    return Rates(inp, out) if inp and out else None


def model_for(mode: str = "standar") -> str:
    env = {"standar": "CLAU_AI_MODEL", "ringan": "CLAU_AI_MODEL_RINGAN", "pro": "CLAU_AI_MODEL_PRO"}[mode]
    return (os.environ.get(env) or "").strip() or DEFAULT_MODELS[mode]


def user_message(prompt: Prompt) -> str:
    facts = [{"fact_key": f.fact_key, "category": f.category, "label": f.label, "value": f.value} for f in prompt.facts]
    return (
        "<fakta_disetujui_klien>\n" + json.dumps(facts, ensure_ascii=False, indent=1) + "\n</fakta_disetujui_klien>\n\n"
        "<request>\n" + prompt.request_text + "\n</request>\n\n"
        "Tulis draft sesuai request. Isi `claims` dengan setiap klaim di draft; klaim fakta tentang bisnis wajib memakai "
        "fact_key dari daftar di atas dan teks persis `label: value`. Bila fakta yang dibutuhkan tidak ada, jangan "
        "mengarang: tulis tanpa klaim itu."
    )


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):  # noqa: ANN002, ANN003
        raise ProviderFailure("provider_error", detail="redirect ditolak")


class ClaudeProvider:
    name = "claude"

    def __init__(self, key: str | None = None, rates: Rates | None = None, model: str | None = None,
                 max_output_tokens: int | None = None, timeout_s: int | None = None, opener=None) -> None:
        self.key = key if key is not None else (os.environ.get("ANTHROPIC_API_KEY") or "").strip()
        self.rates = rates or rates_from_env()
        if not self.key or self.rates is None:
            raise ValueError("provider claude belum dikonfigurasi (ANTHROPIC_API_KEY & CLAU_AI_PRICE_*)")
        self.model = model or model_for("standar")
        self.max_output_tokens = max_output_tokens or min(_positive_int("CLAU_AI_MAX_OUTPUT_TOKENS") or 4000, 32000)
        self.timeout_s = timeout_s or min(_positive_int("CLAU_AI_CALL_TIMEOUT_S") or 300, 900)
        self.opener = opener or urllib.request.build_opener(NoRedirect())

    def body(self, prompt: Prompt) -> dict:
        return {
            "model": self.model,
            "max_tokens": self.max_output_tokens,
            # Bagian stabil (aturan + agent) di-cache provider: hemat biaya untuk semua klien.
            "system": [{"type": "text", "text": prompt.system, "cache_control": {"type": "ephemeral"}}],
            "messages": [{"role": "user", "content": user_message(prompt)}],
            "output_config": {"format": {"type": "json_schema", "schema": OUTPUT_SCHEMA}},
        }

    def usage(self, response: dict, stop_reason: str | None) -> Usage:
        u = response.get("usage") or {}
        tok = {k: int(u.get(k) or 0) for k in
               ("input_tokens", "output_tokens", "cache_read_input_tokens", "cache_creation_input_tokens")}
        return Usage(
            model=str(response.get("model") or self.model)[:100],
            input_tokens=tok["input_tokens"], output_tokens=tok["output_tokens"],
            cache_read_tokens=tok["cache_read_input_tokens"], cache_write_tokens=tok["cache_creation_input_tokens"],
            cost_micro_usd=self.rates.cost(tok["input_tokens"], tok["output_tokens"],
                                           tok["cache_read_input_tokens"], tok["cache_creation_input_tokens"]),
            stop_reason=stop_reason, provider_request_id=(str(response.get("id") or "") or None),
        )

    def call(self, body: dict) -> dict:
        request = urllib.request.Request(
            API_URL, method="POST", data=json.dumps(body, ensure_ascii=False).encode(),
            headers={"x-api-key": self.key, "anthropic-version": API_VERSION, "content-type": "application/json"},
        )
        try:
            with self.opener.open(request, timeout=self.timeout_s) as resp:
                raw = resp.read(MAX_RESPONSE_BYTES + 1)
        except urllib.error.HTTPError as e:
            retry = e.code in RETRYABLE_HTTP
            raise ProviderFailure("provider_unavailable" if retry else "provider_error", retryable=retry,
                                  detail=f"http {e.code}") from None
        except (urllib.error.URLError, socket.timeout, TimeoutError, ConnectionError) as e:
            # Batas waktu bisa sudah ditagih provider; worker mencoba ulang dengan jeda dan batas percobaan.
            raise ProviderFailure("provider_unavailable", retryable=True, detail=type(e).__name__) from None
        if len(raw) > MAX_RESPONSE_BYTES:
            raise ProviderFailure("invalid_output", detail="jawaban terlalu besar")
        try:
            data = json.loads(raw)
        except ValueError:
            raise ProviderFailure("invalid_output", detail="bukan JSON") from None
        if not isinstance(data, dict):
            raise ProviderFailure("invalid_output", detail="bukan objek")
        return data

    def generate(self, prompt: Prompt) -> Generation:
        response = self.call(self.body(prompt))
        stop = response.get("stop_reason")
        usage = self.usage(response, stop if isinstance(stop, str) else None)
        if stop == "refusal":
            raise ProviderFailure("refused", usage=usage, detail="model menolak")
        if stop != "end_turn":  # max_tokens dsb.: draft terpotong tidak pernah disimpan
            raise ProviderFailure("invalid_output", usage=usage, detail=f"stop_reason {stop}")
        texts = [b.get("text") for b in response.get("content") or [] if isinstance(b, dict) and b.get("type") == "text"]
        try:
            out = json.loads("".join(t for t in texts if isinstance(t, str)))
            content = out["content"]
            claims = tuple(
                ClaimOut(text=c["text"], category=c["category"], fact_key=c.get("fact_key") or None,
                         implied=bool(c.get("implied")))
                for c in out["claims"]
            )
        except (ValueError, KeyError, TypeError):
            raise ProviderFailure("invalid_output", usage=usage, detail="format jawaban tidak sesuai") from None
        if not isinstance(content, str) or not content.strip() or any(
            not isinstance(c.text, str) or c.category not in CLAIM_CATEGORIES
            or (c.fact_key is not None and not isinstance(c.fact_key, str)) for c in claims
        ):
            raise ProviderFailure("invalid_output", usage=usage, detail="isi jawaban tidak valid")
        return Generation(content=content, claims=claims, usage=usage)
