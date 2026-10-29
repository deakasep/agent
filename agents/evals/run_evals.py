#!/usr/bin/env python3
"""Deterministic eval runner for CLAU agent outputs (stdlib only).

Two modes:

  python agents/evals/run_evals.py --check
      Validate every case file, require a persona card + case file for every agent in
      registry.json, and prove each case's checks are meaningful: the reference "good"
      output must PASS and the reference "bad" output must FAIL.

  python agents/evals/run_evals.py --agent review-responder --outputs outputs.json
      Score real agent outputs. outputs.json = {"<case-id>": "<output text>", ...}.

Deterministic checks catch rule violations (banned phrases, missing CTA, no escalation,
too many "!" or emoji). Human-likeness itself (empathy, natural tone, voice match) is
scored with the rubric in agents/evals/README.md by a human (or an LLM judge reviewed by
a human). A case passes only when the deterministic checks pass AND the rubric passes.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
AGENTS_DIR = HERE.parent
CASES_DIR = HERE / "cases"
PERSONAS_DIR = AGENTS_DIR / "personas"
REGISTRY = AGENTS_DIR / "registry.json"

# One match per visible emoji: a base symbol plus any skin-tone modifier, variation selector,
# or ZWJ-joined parts ("👍🏽" and "👨‍👩‍👧" each count as one).
EMOJI_RE = re.compile("[\U0001F300-\U0001FAFF\u2600-\u27BF](?:[\U0001F3FB-\U0001F3FF]|\uFE0F|\u200D[\U0001F300-\U0001FAFF\u2600-\u27BF])*")
ESCALATION_MARKER = "eskalasi"
KNOWN_CHECKS = {"max_chars", "must_include_any", "must_not_include", "max_exclamations", "max_emoji", "escalate"}
MIN_CASES = {"active": 2, "planned": 2}
# Agents whose work regularly hits hard limits must prove they escalate instead of answering.
REQUIRES_ESCALATION_CASE = {
    "reel-scripter", "review-responder", "campaign-planner", "sales-assistant", "guest-messenger", "sop-writer",
    "image-creator", "video-creator", "data-analyst",
}


def run_checks(text: str, checks: dict) -> list[str]:
    """Return a list of failed-check messages (empty = pass)."""
    problems = []
    lower = text.lower()
    if "max_chars" in checks and len(text) > checks["max_chars"]:
        problems.append(f"{len(text)} chars > {checks['max_chars']}")
    if checks.get("must_include_any") and not any(s.lower() in lower for s in checks["must_include_any"]):
        problems.append("missing any of: " + ", ".join(checks["must_include_any"]))
    hits = [s for s in checks.get("must_not_include", []) if s.lower() in lower]
    if hits:
        problems.append("contains forbidden: " + ", ".join(hits))
    if "max_exclamations" in checks and text.count("!") > checks["max_exclamations"]:
        problems.append(f"{text.count('!')} '!' > {checks['max_exclamations']}")
    if "max_emoji" in checks and len(EMOJI_RE.findall(text)) > checks["max_emoji"]:
        problems.append(f"{len(EMOJI_RE.findall(text))} emoji > {checks['max_emoji']}")
    if checks.get("escalate") and not lower.lstrip().startswith(ESCALATION_MARKER):
        problems.append("expected escalation (output must start with 'ESKALASI')")
    return problems


def load_cases(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def check_all() -> list[str]:
    errors: list[str] = []
    registry = json.loads(REGISTRY.read_text(encoding="utf-8"))
    seen_ids: set[str] = set()
    for agent in registry["agents"]:
        aid = agent["id"]
        persona = PERSONAS_DIR / f"{aid}.md"
        cases_path = CASES_DIR / f"{aid}.json"
        if agent.get("persona") != f"agents/personas/{aid}.md":
            errors.append(f"{aid}: registry.persona must be agents/personas/{aid}.md")
        if agent.get("evals") != f"agents/evals/cases/{aid}.json":
            errors.append(f"{aid}: registry.evals must be agents/evals/cases/{aid}.json")
        if not persona.is_file():
            errors.append(f"{aid}: missing persona card {persona.relative_to(AGENTS_DIR.parent)}")
        if not cases_path.is_file():
            errors.append(f"{aid}: missing eval cases {cases_path.relative_to(AGENTS_DIR.parent)}")
            continue
        data = load_cases(cases_path)
        if data.get("agent") != aid:
            errors.append(f"{cases_path.name}: agent field must be '{aid}'")
        cases = data.get("cases", [])
        if len(cases) < MIN_CASES[agent["status"]]:
            errors.append(f"{aid}: needs >= {MIN_CASES[agent['status']]} cases, has {len(cases)}")
        if aid in REQUIRES_ESCALATION_CASE and not any(c["checks"].get("escalate") for c in cases):
            errors.append(f"{aid}: needs at least one escalation case")
        for case in cases:
            cid = case.get("id", "?")
            for key in ("id", "scenario", "input", "checks", "reference"):
                if key not in case:
                    errors.append(f"{aid}/{cid}: missing '{key}'")
            if cid in seen_ids:
                errors.append(f"{aid}/{cid}: duplicate case id")
            seen_ids.add(cid)
            unknown = set(case.get("checks", {})) - KNOWN_CHECKS
            if unknown:
                errors.append(f"{aid}/{cid}: unknown checks {sorted(unknown)}")
            ref = case.get("reference", {})
            good_problems = run_checks(ref.get("good", ""), case.get("checks", {}))
            if good_problems:
                errors.append(f"{aid}/{cid}: reference GOOD fails: {'; '.join(good_problems)}")
            if not run_checks(ref.get("bad", ""), case.get("checks", {})):
                errors.append(f"{aid}/{cid}: reference BAD passes (checks do not catch it)")
    for path in CASES_DIR.glob("*.json"):
        if not any(a["id"] == path.stem for a in registry["agents"]):
            errors.append(f"{path.name}: no agent with this id in registry.json")
    return errors


def score(agent: str, outputs_path: Path) -> int:
    data = load_cases(CASES_DIR / f"{agent}.json")
    outputs = json.loads(outputs_path.read_text(encoding="utf-8"))
    failed = 0
    for case in data["cases"]:
        text = outputs.get(case["id"])
        if text is None:
            print(f"SKIP  {case['id']}  (no output)")
            continue
        problems = run_checks(text, case["checks"])
        if problems:
            failed += 1
            print(f"FAIL  {case['id']}  {case['scenario']}")
            for p in problems:
                print(f"      - {p}")
        else:
            print(f"PASS (deterministik)  {case['id']}  {case['scenario']}")
    print("note: lanjutkan dengan rubrik manusia di agents/evals/README.md (empati, natural, voice, akurasi, langkah lanjut, budaya).")
    return 1 if failed else 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--check", action="store_true", help="validate cases, personas, registry links, references")
    parser.add_argument("--agent", help="agent id to score")
    parser.add_argument("--outputs", type=Path, help="JSON file {case_id: output_text}")
    args = parser.parse_args()
    if args.check:
        errors = check_all()
        if errors:
            print("FAIL")
            for e in errors:
                print(f"  - {e}")
            return 1
        n = sum(len(load_cases(p)["cases"]) for p in CASES_DIR.glob("*.json"))
        print(f"PASS — {len(list(CASES_DIR.glob('*.json')))} agents, {n} cases; every GOOD reference passes and every BAD reference is caught")
        return 0
    if args.agent and args.outputs:
        return score(args.agent, args.outputs)
    parser.error("use --check, or --agent with --outputs")
    return 2


if __name__ == "__main__":
    sys.exit(main())
