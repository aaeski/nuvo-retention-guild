"""
orchestrator.py — beş agent'ı sırayla çalıştırır ve handoff'u zorlar.

Çalıştırma:
    export GEMINI_API_KEY=...           # repoya ASLA girmez
    python orchestrator.py

Model çağrısı Google Gemini API'sine gidiyor (generativelanguage.googleapis.com).
Agent kişilikleri ve JSON sözleşmeleri agents.py'de tanımlı, modelden bağımsız;
ödev şartnamesi "Claude, ChatGPT, Gemini, or other LLMs" seçimini serbest
bırakıyor, biz ücretsiz katmanı olan Gemini'yi seçtik.

Her çalıştırma runs/run_<zaman>.json dosyası üretir: canlı veri damgası, her
agent'ın ham çıktısı, zincir denetimi ve Manager'ın kararı. Bu dosyalar
"evidence of iteration" demek; silme, biriktir.

TASARIM NOTU — neden düz bir zincir değil
Manager APPROVE veya REVISE döndürebilir. REVISE gelirse orchestrator ilgili
agent'ı Manager'ın talimatıyla BİR KEZ yeniden çalıştırır ve ondan sonraki tüm
adımları da yeniden üretir. Yani zincir tek yönlü değil, bir geri besleme
döngüsü var. Bu, rubriğin "sophisticated handoffs" dediği şeyin somut hali.
"""

from __future__ import annotations

import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

import agents
import nuvo_data

API_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
MAX_TOKENS = 8000
RUNS_DIR = Path("runs")


# ---------------------------------------------------------------------------
# Model çağrısı
# ---------------------------------------------------------------------------

def call_model(system: str, user: str, model: str = agents.MODEL,
               retries: int = 3) -> str:
    key = os.environ.get("GEMINI_API_KEY")
    if not key:
        sys.exit("GEMINI_API_KEY tanımlı değil. Anahtarı ortam değişkeninde "
                 "tut, koda yazma.")

    body = json.dumps({
        "systemInstruction": {"parts": [{"text": system}]},
        "contents": [{"role": "user", "parts": [{"text": user}]}],
        "generationConfig": {"maxOutputTokens": MAX_TOKENS, "temperature": 0.7},
    }).encode("utf-8")

    req = urllib.request.Request(API_URL.format(model=model), data=body, headers={
        "content-type": "application/json",
        "x-goog-api-key": key,
    })

    last = None
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(req, timeout=180) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            candidates = data.get("candidates") or []
            if not candidates:
                block_reason = data.get("promptFeedback", {}).get("blockReason")
                raise RuntimeError(f"Gemini boş yanıt döndürdü (blockReason={block_reason})")
            finish_reason = candidates[0].get("finishReason")
            parts = candidates[0].get("content", {}).get("parts", [])
            text = "".join(p.get("text", "") for p in parts)
            if finish_reason == "MAX_TOKENS":
                raise RuntimeError(
                    f"Gemini yaniti MAX_TOKENS'ta kesildi (limit={MAX_TOKENS}). "
                    f"Alinan {len(text)} karakter, JSON tamamlanmamis olabilir."
                )
            return text
        except urllib.error.HTTPError as e:
            last = f"HTTP {e.code}: {e.read().decode('utf-8', 'replace')[:300]}"
            if e.code in (429, 500, 503) and attempt < retries - 1:
                time.sleep(2 ** attempt * 3)
                continue
            raise RuntimeError(last)
        except urllib.error.URLError as e:
            last = str(e)
            if attempt < retries - 1:
                time.sleep(2 ** attempt * 3)
                continue
            raise RuntimeError(last)
    raise RuntimeError(last or "bilinmeyen hata")


def parse_json(text: str, who: str) -> dict:
    """Agent çıktısını JSON'a çevirir; model markdown fence koyarsa temizler."""
    cleaned = re.sub(r"^```(?:json)?|```$", "", text.strip(),
                     flags=re.MULTILINE).strip()
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        start, end = cleaned.find("{"), cleaned.rfind("}")
        if start != -1 and end > start:
            try:
                return json.loads(cleaned[start:end + 1])
            except json.JSONDecodeError:
                pass
    raise ValueError(f"{who} geçerli JSON döndürmedi. İlk 400 karakter:\n"
                     f"{cleaned[:400]}")


# ---------------------------------------------------------------------------
# Handoff denetimi
# ---------------------------------------------------------------------------

def check_handoff(upstream: dict, downstream: dict, key_up: str,
                  key_down: str) -> dict:
    """Downstream artefaktın upstream'e gerçekten atıf yapıp yapmadığını ölçer.

    Bu bir güvenlik ağı değil, kanıt üretici. Rapora "handoff gerçek" yazmak
    yerine, hangi alanın hangi değeri taşıdığını gösterebilirsin.
    """
    want = str(upstream.get(key_up, "")).strip()
    got = str(downstream.get(key_down, "")).strip()
    return {
        "expected": want,
        "found": got,
        "carried": bool(want) and want.lower() == got.lower(),
        "via": f"{key_up} -> {key_down}",
    }


# ---------------------------------------------------------------------------
# Adımlar
# ---------------------------------------------------------------------------

def run_researcher(payload: str, note: str = "") -> dict:
    user = ("Here is the live retention data payload for Nuvo, fetched from the "
            "operational data source at the moment of this call.\n\n"
            f"{payload}\n\n"
            "Produce your opportunity brief.")
    if note:
        user += f"\n\nREVISION REQUESTED BY Isabel Ferreira: {note}"
    return parse_json(call_model(agents.RESEARCHER["system"], user), "Researcher")


def run_designer(brief: dict, note: str = "") -> dict:
    user = ("Mara Vance has completed her opportunity brief. Design the "
            "intervention.\n\n=== OPPORTUNITY BRIEF ===\n"
            f"{json.dumps(brief, ensure_ascii=False, indent=2)}")
    if note:
        user += f"\n\nREVISION REQUESTED BY Isabel Ferreira: {note}"
    return parse_json(call_model(agents.DESIGNER["system"], user), "Designer")


def run_maker(concept: dict, brief: dict, note: str = "") -> dict:
    schema = ("customers: customer_id, signup_date, segment, city, "
              "product_holdings, monthly_income_band, status, churn_date "
              "(full_name and email exist in the sheet but are stripped before "
              "any model sees them)\n"
              "transactions: txn_id, customer_id, date, amount, category, channel\n"
              "events: customer_id, date, event_type "
              "(salary_deposit_stopped | card_dormant | support_ticket | "
              "app_login_gap | account_closed), detail")
    user = ("Theo Lindqvist has produced a solution concept. Build it.\n\n"
            "=== SOLUTION CONCEPT ===\n"
            f"{json.dumps(concept, ensure_ascii=False, indent=2)}\n\n"
            "=== TARGET COHORT (from Mara Vance) ===\n"
            f"{json.dumps(brief.get('target_cohort', {}), ensure_ascii=False, indent=2)}\n\n"
            f"=== LIVE DATA SCHEMA ===\n{schema}")
    if note:
        user += f"\n\nREVISION REQUESTED BY Isabel Ferreira: {note}"
    return parse_json(call_model(agents.MAKER["system"], user), "Maker")


def run_communicator(spec: dict, concept: dict, note: str = "") -> dict:
    user = ("Devika Rao has produced the build spec and needs its copy slots "
            "filled.\n\n=== BUILD SPEC ===\n"
            f"{json.dumps(spec, ensure_ascii=False, indent=2)}\n\n"
            "=== SOLUTION CONCEPT (for tone and intent) ===\n"
            f"{json.dumps(concept, ensure_ascii=False, indent=2)}")
    if note:
        user += f"\n\nREVISION REQUESTED BY Isabel Ferreira: {note}"
    return parse_json(call_model(agents.COMMUNICATOR["system"], user),
                      "Communicator")


def run_manager(brief, concept, spec, pack, snapshot) -> dict:
    user = ("Review the full pipeline. All four artefacts follow, in order, "
            "plus the live data snapshot the Researcher was given.\n\n"
            f"=== 1. OPPORTUNITY BRIEF (Mara Vance) ===\n"
            f"{json.dumps(brief, ensure_ascii=False, indent=2)}\n\n"
            f"=== 2. SOLUTION CONCEPT (Theo Lindqvist) ===\n"
            f"{json.dumps(concept, ensure_ascii=False, indent=2)}\n\n"
            f"=== 3. BUILD SPEC (Devika Rao) ===\n"
            f"{json.dumps(spec, ensure_ascii=False, indent=2)}\n\n"
            f"=== 4. MESSAGING PACK (Jonah Okafor) ===\n"
            f"{json.dumps(pack, ensure_ascii=False, indent=2)}\n\n"
            f"=== LIVE DATA SNAPSHOT ===\n"
            f"{json.dumps(snapshot, ensure_ascii=False, indent=2)}")
    return parse_json(call_model(agents.MANAGER["system"], user), "Manager")


# ---------------------------------------------------------------------------
# Ana akış
# ---------------------------------------------------------------------------

def main(allow_revision: bool = True) -> dict:
    print("· canlı veri çekiliyor (Google Sheets)...")
    data = nuvo_data.fetch_all()
    snapshot = nuvo_data.retention_snapshot(data)
    payload = nuvo_data.build_agent_payload(data)
    print(f"  çekim: {data['fetched_at']} · {snapshot['total_customers']} müşteri")

    print("· Researcher (Mara Vance)...")
    brief = run_researcher(payload)
    print(f"  → {brief.get('headline_finding', '')[:110]}")

    print("· Designer (Theo Lindqvist)...")
    concept = run_designer(brief)
    print(f"  → {concept.get('concept_name', '')}")

    print("· Maker (Devika Rao)...")
    spec = run_maker(concept, brief)
    print(f"  → {spec.get('what_it_is', '')[:110]}")

    print("· Communicator (Jonah Okafor)...")
    pack = run_communicator(spec, concept)
    print(f"  → {len(pack.get('copy_slots', []))} copy slot dolduruldu")

    print("· Manager (Isabel Ferreira)...")
    review = run_manager(brief, concept, spec, pack, snapshot)
    print(f"  → karar: {review.get('verdict')}")

    revision = None
    if allow_revision and review.get("verdict") == "REVISE":
        target = review.get("revise_target", "none")
        note = review.get("revise_instruction", "")
        print(f"· REVISE → {target}: {note[:100]}")
        revision = {"target": target, "instruction": note,
                    "before": {"brief": brief, "concept": concept,
                               "spec": spec, "pack": pack}}

        if target == "Researcher":
            brief = run_researcher(payload, note)
            concept = run_designer(brief)
            spec = run_maker(concept, brief)
            pack = run_communicator(spec, concept)
        elif target == "Designer":
            concept = run_designer(brief, note)
            spec = run_maker(concept, brief)
            pack = run_communicator(spec, concept)
        elif target == "Maker":
            spec = run_maker(concept, brief, note)
            pack = run_communicator(spec, concept)
        elif target == "Communicator":
            pack = run_communicator(spec, concept, note)

        print("· Manager yeniden inceliyor...")
        review = run_manager(brief, concept, spec, pack, snapshot)
        print(f"  → karar: {review.get('verdict')}")

    chain = [
        {"handoff": "Researcher → Designer",
         **check_handoff(brief.get("target_cohort", {}), concept,
                         "cohort_id", "responds_to_cohort_id")},
        {"handoff": "Designer → Maker",
         **check_handoff(concept, spec, "concept_name", "implements_concept")},
        {"handoff": "Maker → Communicator",
         **check_handoff(spec, pack, "implements_concept", "implements_concept")},
    ]
    slots_wanted = set(spec.get("ui_copy_slots", []))
    slots_filled = {s.get("slot") for s in pack.get("copy_slots", [])}
    chain.append({"handoff": "Maker → Communicator (copy slots)",
                  "expected": sorted(slots_wanted),
                  "found": sorted(slots_filled),
                  "carried": slots_wanted.issubset(slots_filled) if slots_wanted else False,
                  "via": "ui_copy_slots -> copy_slots"})

    print("\nzincir denetimi")
    for c in chain:
        print(f"  {'✓' if c['carried'] else '✗'} {c['handoff']}  ({c['via']})")

    run = {
        "run_id": datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ"),
        "model": agents.MODEL,
        "data_fetched_at": data["fetched_at"],
        "data_source": data["source"],
        "snapshot": snapshot,
        "artefacts": {"opportunity_brief": brief, "solution_concept": concept,
                      "build_spec": spec, "messaging_pack": pack,
                      "executive_review": review},
        "chain_audit": chain,
        "revision": revision,
    }

    RUNS_DIR.mkdir(exist_ok=True)
    payload = json.dumps(run, ensure_ascii=False, indent=2)
    path = RUNS_DIR / f"run_{run['run_id']}.json"
    path.write_text(payload, encoding="utf-8")
    # docs/ sitesi hep bu sabit isimden okur; zaman damgali dosya silinmez,
    # sadece "en son run hangisi" isaretcisi guncellenir.
    (RUNS_DIR / "latest_run.json").write_text(payload, encoding="utf-8")
    print(f"\nkaydedildi: {path}")
    return run


if __name__ == "__main__":
    main()
