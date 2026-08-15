"""
nuvo_data.py — Nuvo'nun canli veri katmani.

Musteri, islem ve olay verisi bir Google Sheets dosyasinda tutulur
(customers / transactions / events sekmeleri). Bu modul, her cagrida
sekmelerin genel-erisimli CSV export uclarindan (gviz/tq) HTTP ile
veriyi ceker. Hicbir satir diske veya koda gomulmez; fetch_all() her
calistiginda o anki sayfa icerigini doner.

SHEET_ID public salt-okunur paylasilmis durumda (izinler: "anyone: reader"),
bu yuzden API anahtari veya servis hesabi gerekmiyor.
"""

from __future__ import annotations

import csv
import io
import urllib.error
import urllib.request
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone

SHEET_ID = "1ufEfEqSBBr_sU1_IeTwHy82bC4qUxbwxjYNaaS6MxG4"
CSV_URL = "https://docs.google.com/spreadsheets/d/{sheet_id}/gviz/tq?tqx=out:csv&sheet={name}"

# Musteriyi churn'e goturebilecek sinyal niteligindeki olay tipleri.
RISK_EVENT_TYPES = {"salary_deposit_stopped", "card_dormant", "app_login_gap", "support_ticket"}
RECENT_WINDOW_DAYS = 30
MIN_N = 15  # Researcher'in n<15 kuralinin dayandigi ayni esik; burada sadece bilgi amacli.


def _fetch_csv_rows(sheet_name: str) -> list[dict]:
    url = CSV_URL.format(sheet_id=SHEET_ID, name=sheet_name)
    req = urllib.request.Request(url, headers={"user-agent": "nuvo-retention-guild/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            raw = resp.read().decode("utf-8-sig")
    except urllib.error.URLError as e:
        raise RuntimeError(f"'{sheet_name}' sekmesi canli olarak cekilemedi: {e}") from e
    return list(csv.DictReader(io.StringIO(raw)))


def fetch_all() -> dict:
    """Uc sekmeyi de canli ceker. Her cagrida yeniden HTTP istegi atar."""
    customers = _fetch_csv_rows("customers")
    transactions = _fetch_csv_rows("transactions")
    events = _fetch_csv_rows("events")
    return {
        "customers": customers,
        "transactions": transactions,
        "events": events,
        "fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "source": f"google_sheets:{SHEET_ID}",
    }


def _parse_date(s: str):
    try:
        return datetime.strptime(s.strip(), "%Y-%m-%d")
    except (ValueError, AttributeError):
        return None


def _cut(cut_name: str, ids_in_cut: set, churned_ids: set) -> dict:
    n = len(ids_in_cut)
    churned = len(ids_in_cut & churned_ids)
    rate = round(churned / n, 4) if n else 0.0
    return {"cut": cut_name, "n": n, "churned": churned, "rate": rate}


def _compute(data: dict) -> dict:
    customers = data["customers"]
    events = data["events"]

    all_ids = {c["customer_id"] for c in customers}
    churned_ids = {c["customer_id"] for c in customers if c.get("status") == "churned"}
    active_ids = all_ids - churned_ids

    by_segment = defaultdict(set)
    by_income = defaultdict(set)
    by_product_count = defaultdict(set)
    for c in customers:
        cid = c["customer_id"]
        by_segment[c.get("segment", "unknown")].add(cid)
        by_income[c.get("monthly_income_band", "unknown")].add(cid)
        holdings = [h for h in c.get("product_holdings", "").split("|") if h]
        by_product_count[len(holdings)].add(cid)

    by_event_type = defaultdict(set)
    event_dates = defaultdict(list)
    for e in events:
        cid = e.get("customer_id")
        etype = e.get("event_type")
        if cid and etype:
            by_event_type[etype].add(cid)
            d = _parse_date(e.get("date", ""))
            if d:
                event_dates[cid].append((etype, d))

    cuts = [_cut("all_customers", all_ids, churned_ids)]
    for seg, ids in sorted(by_segment.items()):
        cuts.append(_cut(f"segment:{seg}", ids, churned_ids))
    for band, ids in sorted(by_income.items()):
        cuts.append(_cut(f"income_band:{band}", ids, churned_ids))
    for count, ids in sorted(by_product_count.items()):
        cuts.append(_cut(f"product_count:{count}", ids, churned_ids))
    for etype, ids in sorted(by_event_type.items()):
        cuts.append(_cut(f"had_event:{etype}", ids, churned_ids))

    # "recent" pencereyi verideki en guncel olay tarihine gore ankorluyoruz,
    # cunku sentetik veri sabit bir gecmis donemi simule ediyor.
    all_event_dates = [d for pairs in event_dates.values() for _, d in pairs]
    as_of = max(all_event_dates) if all_event_dates else datetime.now(timezone.utc).replace(tzinfo=None)
    window_start = as_of - timedelta(days=RECENT_WINDOW_DAYS)

    at_risk_ids = sorted(
        cid
        for cid, pairs in event_dates.items()
        if cid in active_ids
        and any(etype in RISK_EVENT_TYPES and d >= window_start for etype, d in pairs)
    )

    return {
        "as_of": as_of.strftime("%Y-%m-%d"),
        "all_ids": all_ids,
        "active_ids": active_ids,
        "churned_ids": churned_ids,
        "cuts": cuts,
        "at_risk_ids": at_risk_ids,
    }


def retention_snapshot(data: dict) -> dict:
    """Manager'a ve konsol ozetine giden ust-duzey goruntu."""
    m = _compute(data)
    return {
        "as_of": m["as_of"],
        "total_customers": len(m["all_ids"]),
        "active_customers": len(m["active_ids"]),
        "churned_customers": len(m["churned_ids"]),
        "overall_churn_rate": round(len(m["churned_ids"]) / len(m["all_ids"]), 4) if m["all_ids"] else 0.0,
        "at_risk_customers_flagged": len(m["at_risk_ids"]),
        "n_transactions": len(data["transactions"]),
        "n_events": len(data["events"]),
    }


def build_agent_payload(data: dict) -> dict:
    """Researcher'a giden JSON payload. Her cut kendi n'ini tasir (HARD RULE 2)."""
    m = _compute(data)
    return {
        "as_of": m["as_of"],
        "min_n_for_finding": MIN_N,
        "cuts": m["cuts"],
        "recently_active_customers_with_signals": m["at_risk_ids"],
        "signal_event_types_considered": sorted(RISK_EVENT_TYPES),
        "signal_window_days": RECENT_WINDOW_DAYS,
    }


if __name__ == "__main__":
    d = fetch_all()
    print(f"cekim: {d['fetched_at']} kaynak: {d['source']}")
    print(retention_snapshot(d))
