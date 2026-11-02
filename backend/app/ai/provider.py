"""Antarmuka provider model AI + provider tiruan (uji tanpa biaya, tanpa data keluar).

Provider menerima `Prompt` (sudah disamarkan, hanya fakta yang dikonfirmasi klien) dan mengembalikan `Generation`:
isi draft + klaim terstruktur. Label bukti klaim TIDAK ditentukan provider: worker menentukannya lewat AI fact-check
(app/ai/factcheck.py). Provider Claude (Tahap 2 PR 4c, app/ai/claude.py) mengikuti antarmuka yang sama.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class FactForPrompt:
    fact_key: str
    category: str
    label: str
    value: str


@dataclass(frozen=True)
class Prompt:
    agent_id: str
    intent: str
    system: str  # bagian stabil (aturan + agent): dasar prompt_version & prompt caching
    facts: tuple[FactForPrompt, ...]
    request_text: str  # sudah disamarkan (app/ai/prompt.redact)
    prompt_version: str


@dataclass(frozen=True)
class ClaimOut:
    text: str
    category: str
    fact_key: str | None = None
    implied: bool = False


@dataclass(frozen=True)
class Usage:
    model: str
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0
    cost_micro_usd: int = 0
    stop_reason: str | None = None
    provider_request_id: str | None = None


@dataclass(frozen=True)
class Generation:
    content: str
    claims: tuple[ClaimOut, ...]
    usage: Usage


@dataclass
class ProviderFailure(Exception):
    """Gagal memanggil provider. `code` = kode error job (database-schema § Keputusan Implementasi)."""

    code: str
    retryable: bool = False
    usage: Usage | None = None  # panggilan yang tetap ditagih (mis. ditolak di tengah jawaban) tetap dicatat
    detail: str = field(default="", repr=False)  # untuk log server saja, tidak pernah ke API/audit

    def __post_init__(self) -> None:
        super().__init__(self.code)


class FakeProvider:
    """Provider tiruan deterministik untuk uji alur tanpa biaya. Hanya untuk klien SIMULASI (endpoint menegakkan).

    Penanda di teks request (hanya berlaku di provider tiruan) untuk menguji jalur tertentu:
    `[uji:klaim-tanpa-fakta]` menambah klaim "pantai pribadi" yang tidak ada di fact sheet (fact-check harus menandai),
    `[uji:gagal-sementara]` = provider tidak tersedia (retry), `[uji:tolak]` = model menolak.
    """

    name = "fake"
    model = "fake-0"

    def generate(self, prompt: Prompt) -> Generation:
        usage = Usage(model=self.model, stop_reason="end_turn", provider_request_id="fake")
        if "[uji:gagal-sementara]" in prompt.request_text:
            raise ProviderFailure("provider_unavailable", retryable=True, detail="fake: unavailable")
        if "[uji:tolak]" in prompt.request_text:
            raise ProviderFailure("refused", usage=Usage(model=self.model, stop_reason="refusal"), detail="fake: refusal")
        used = prompt.facts[:3]
        claims = [ClaimOut(text=f"{f.label}: {f.value}", category=f.category, fact_key=f.fact_key) for f in used]
        lines = [f"- {c.text}" for c in claims]
        if "[uji:klaim-tanpa-fakta]" in prompt.request_text:
            claims.append(ClaimOut(text="Nikmati pantai pribadi kami", category="facility", fact_key="facility.pantai-pribadi"))
            lines.append("- Nikmati pantai pribadi kami")
        content = "\n".join([
            "[DRAF UJI — dibuat provider tiruan, bukan AI; jangan dipublikasikan]",
            f"Agent: {prompt.agent_id} · intent: {prompt.intent}",
            "",
            "Fakta yang dipakai:",
            *(lines or ["- (tidak ada)"]),
        ])
        return Generation(content=content, claims=tuple(claims), usage=usage)


def get_provider(name: str):
    if name == "fake":
        return FakeProvider()
    if name == "claude":
        from app.ai.claude import ClaudeProvider  # impor tunda: provider.py dipakai claude.py

        return ClaudeProvider()
    raise ValueError(f"provider AI tidak dikenal: {name}")
