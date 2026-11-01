"""agents/capabilities.json: setiap agent punya tugas terstruktur (pola Sintra.ai) yang sinkron dengan kartu persona."""

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CAPS = json.loads((ROOT / "agents" / "capabilities.json").read_text(encoding="utf-8"))["agents"]
REGISTRY = json.loads((ROOT / "agents" / "registry.json").read_text(encoding="utf-8"))["agents"]

# Kata yang membuat klaim berlebihan atau bertentangan dengan aturan "AI tidak publish/kirim".
FORBIDDEN = re.compile(r"(otomatis (posting|memposting|mengirim|terkirim|tayang)|langsung (tayang|terkirim|diposting))", re.I)


def test_every_registry_agent_has_capabilities_and_no_extras():
    assert set(CAPS) == {a["id"] for a in REGISTRY}


def test_structure_is_complete():
    for aid, c in CAPS.items():
        assert len(c["summary"]) >= 80, aid
        assert len(c["abilities"]) == 3, aid
        assert all(0 < len(x) <= 30 for x in c["abilities"]), aid
        assert len(c["features"]) == 6, aid
        for f in c["features"]:
            assert f["title"] and len(f["description"]) >= 40, (aid, f["title"])
        assert len({f["title"] for f in c["features"]}) == 6, aid
        assert len(c["workflow"]) >= 4, aid
        assert len(c["quality"]) >= 3, aid


def test_work_always_ends_as_draft_for_human_approval():
    for aid, c in CAPS.items():
        last = c["workflow"][-1].lower()
        assert "menyerahkan" in last, aid
        assert any(w in last for w in ("setuju", "periksa", "mengirim", "dibaca")), aid


def test_no_overclaiming_language():
    for aid, c in CAPS.items():
        texts = [c["summary"], *c["abilities"], *c["workflow"], *c["quality"]]
        texts += [f"{f['title']} {f['description']}" for f in c["features"]]
        for t in texts:
            assert not FORBIDDEN.search(t), (aid, t)


def test_persona_card_mirrors_workflow_and_checklist():
    for aid, c in CAPS.items():
        card = (ROOT / "agents" / "personas" / f"{aid}.md").read_text(encoding="utf-8")
        assert "## 4a. Cara Kerja" in card, aid
        for i, step in enumerate(c["workflow"], 1):
            assert f"{i}. {step}" in card, (aid, step)
        for q in c["quality"]:
            assert f"- [ ] {q}" in card, (aid, q)
