"""Provider Claude (app/ai/claude.py) tanpa jaringan: opener tiruan menggantikan API.

Menguji: fail closed tanpa tarif/kunci, isi permintaan (system di-cache, hanya fakta disetujui + request tersamar,
JSON terstruktur), hitung biaya dari tarif owner, pemetaan error ke kode job tetap, dan penolakan jawaban tidak valid.
"""

import io
import json
import urllib.error

import pytest

from app.ai import claude
from app.ai.claude import ClaudeProvider, Rates
from app.ai.config import ai_settings
from app.ai.prompt import build_prompt
from app.ai.provider import FactForPrompt, ProviderFailure, get_provider

RATES = Rates(input=3_000_000, output=15_000_000)  # $3 / $15 per juta token (contoh uji, bukan harga resmi)


class FakeResponse(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class Opener:
    def __init__(self, reply=None, error=None):
        self.reply, self.error, self.requests = reply, error, []

    def open(self, request, timeout):
        self.requests.append((request, timeout))
        if self.error:
            raise self.error
        return FakeResponse(json.dumps(self.reply).encode())


def prompt(text="Caption promo kamar, hubungi 081234567890"):
    facts = [FactForPrompt("facility.kolam-renang", "facility", "Kolam renang", "Ada, outdoor")]
    return build_prompt("tara", "caption", facts, text)


def answer(out, stop="end_turn", usage=None):
    return {
        "id": "msg_uji", "model": "claude-sonnet-5-5", "stop_reason": stop,
        "content": [{"type": "text", "text": json.dumps(out)}],
        "usage": usage or {"input_tokens": 1000, "output_tokens": 500, "cache_read_input_tokens": 2000,
                           "cache_creation_input_tokens": 0},
    }


GOOD = {"content": "Berenang santai di kolam outdoor kami.",
        "claims": [{"text": "Kolam renang: Ada, outdoor", "category": "facility",
                    "fact_key": "facility.kolam-renang", "implied": False}]}


def provider(opener):
    return ClaudeProvider(key="sk-uji", rates=RATES, model="claude-sonnet-5-5", opener=opener)


def test_success_builds_safe_request_and_counts_cost():
    opener = Opener(answer(GOOD))
    gen = provider(opener).generate(prompt())
    assert gen.content == GOOD["content"]
    assert [(c.fact_key, c.category, c.implied) for c in gen.claims] == [("facility.kolam-renang", "facility", False)]
    # 1000×3 + 500×15 + 2000×0,3 = 3000 + 7500 + 600 mikro-USD (dibulatkan ke atas per panggilan)
    assert (gen.usage.cost_micro_usd, gen.usage.cache_read_tokens, gen.usage.provider_request_id) == (11_100, 2000, "msg_uji")
    request, _ = opener.requests[0]
    body = json.loads(request.data)
    assert request.full_url == claude.API_URL and request.get_header("X-api-key") == "sk-uji"
    assert body["system"][0]["cache_control"] == {"type": "ephemeral"}
    assert body["output_config"]["format"]["type"] == "json_schema"
    user = body["messages"][0]["content"]
    assert "081234567890" not in user and "<KONTAK>" in user  # penyamaran sudah terjadi sebelum keluar
    assert "facility.kolam-renang" in user


def test_cost_rounds_up_and_charges_cache_write():
    assert Rates(input=1, output=1).cost(1, 0, 0, 0) == 1
    assert RATES.cost(0, 0, 0, 1_000_000) == 3_750_000


@pytest.mark.parametrize("code,expected,retry", [(429, "provider_unavailable", True), (529, "provider_unavailable", True),
                                                 (500, "provider_unavailable", True), (400, "provider_error", False),
                                                 (401, "provider_error", False)])
def test_http_errors_map_to_fixed_job_codes(code, expected, retry):
    err = urllib.error.HTTPError(claude.API_URL, code, "x", {}, io.BytesIO(b"{}"))
    with pytest.raises(ProviderFailure) as e:
        provider(Opener(error=err)).generate(prompt())
    assert (e.value.code, e.value.retryable) == (expected, retry)


def test_network_timeout_is_retryable():
    with pytest.raises(ProviderFailure) as e:
        provider(Opener(error=TimeoutError())).generate(prompt())
    assert (e.value.code, e.value.retryable) == ("provider_unavailable", True)


def test_refusal_and_truncated_answers_are_never_saved_but_billed():
    with pytest.raises(ProviderFailure) as e:
        provider(Opener(answer(GOOD, stop="refusal"))).generate(prompt())
    assert e.value.code == "refused" and e.value.usage.cost_micro_usd > 0
    with pytest.raises(ProviderFailure) as e:
        provider(Opener(answer(GOOD, stop="max_tokens"))).generate(prompt())
    assert e.value.code == "invalid_output" and e.value.usage.cost_micro_usd > 0


@pytest.mark.parametrize("out", [
    {"content": "x"},
    {"content": "", "claims": []},
    {"content": "x", "claims": [{"text": "y", "category": "tidak-dikenal", "fact_key": None, "implied": False}]},
    "bukan objek",
])
def test_invalid_structured_output_fails_job(out):
    with pytest.raises(ProviderFailure) as e:
        provider(Opener(answer(out))).generate(prompt())
    assert e.value.code == "invalid_output"


def test_fail_closed_without_rates_or_key(monkeypatch):
    for name in ("CLAU_AI_PRICE_INPUT_MICRO_USD", "CLAU_AI_PRICE_OUTPUT_MICRO_USD", "ANTHROPIC_API_KEY"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("CLAU_AI_ENABLED", "1")
    monkeypatch.setenv("CLAU_AI_PROVIDER", "claude")
    assert ai_settings().enabled is False  # tanpa tarif: biaya tak bisa dihitung = AI mati
    monkeypatch.setenv("CLAU_AI_PRICE_INPUT_MICRO_USD", "3000000")
    monkeypatch.setenv("CLAU_AI_PRICE_OUTPUT_MICRO_USD", "0")
    assert ai_settings().enabled is False
    monkeypatch.setenv("CLAU_AI_PRICE_OUTPUT_MICRO_USD", "15000000")
    assert ai_settings().enabled is True
    with pytest.raises(ValueError):  # container tanpa kunci (mis. backend) tidak bisa membuat provider
        get_provider("claude")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-uji")
    p = get_provider("claude")
    assert (p.name, p.model, p.rates) == ("claude", "claude-sonnet-5-5", RATES)


def test_model_per_mode_can_be_overridden(monkeypatch):
    monkeypatch.delenv("CLAU_AI_MODEL_PRO", raising=False)
    assert claude.model_for("pro") == "claude-fable-5-1"
    monkeypatch.setenv("CLAU_AI_MODEL_PRO", "claude-fable-5-1-uji")
    assert claude.model_for("pro") == "claude-fable-5-1-uji"
