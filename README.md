# Nuvo Retention Guild — an agentic organisation

Final project for **H9CEAI — Customer Engagement and Artificial Intelligence**
(National College of Ireland). Five specialised Claude agents run as a
pipeline against a fictional Irish digital bank, **Nuvo**, to turn live
customer data into a reviewed, ready-to-ship retention intervention.

Live prototype: `docs/` is served via GitHub Pages —
`https://<your-username>.github.io/<your-repo>/`

## The five agents (`agents.py`)

| # | Agent | Name | Produces |
|---|-------|------|----------|
| 1 | Researcher | Mara Vance, Head of Retention Analytics | `opportunity_brief` |
| 2 | Designer | Theo Lindqvist, Principal Service Designer | `solution_concept` |
| 3 | Maker | Devika Rao, Staff Engineer | `build_spec` |
| 4 | Communicator | Jonah Okafor, Lifecycle Marketing Lead | `messaging_pack` |
| 5 | Manager | Isabel Ferreira, Director of Customer Value | `executive_review` |

Each agent has its own system prompt, personality, hard rules, and a strict
JSON output contract. Every downstream agent must cite a specific field from
its upstream agent's output (e.g. the Designer must quote the Researcher's
`cohort_id`) — this is what `orchestrator.py`'s `check_handoff()` verifies
after every run.

## Live data (`nuvo_data.py`)

Customer, transaction and event data lives in a public Google Sheet
(`customers` / `transactions` / `events` tabs), not in this repo. Every call
to `fetch_all()` issues a fresh HTTP request to the sheet's CSV export
endpoint — nothing is cached, hardcoded, or copy-pasted into the code. The
CSVs at the repo root (`customers.csv`, `transactions.csv`, `events.csv`)
are kept only as the original seed data and a human-readable reference; the
pipeline never reads them directly.

`nuvo_data.py` also computes the aggregated, sample-size-labelled cuts
(`build_agent_payload`) that Mara Vance's hard rules require, and a
lightweight `retention_snapshot` used for the Manager's review and the
console log.

## Running the pipeline

```bash
export GEMINI_API_KEY=...   # never commit this
python orchestrator.py
```

Each run fetches live data, runs all five agents in order, lets the Manager
issue an APPROVE/REVISE verdict (with one automatic revision loop if she
sends work back), and writes the full transcript to
`runs/run_<timestamp>.json` plus a stable `runs/latest_run.json` that the
GitHub Pages site reads. Timestamped run files are never deleted — they are
the evidence of iteration the brief asks for.

## GitHub Pages site (`docs/`)

Two independent live things, no backend required:

1. **Live data panel** — loads the `customers` and `events` tabs straight
   from Google Sheets in the browser (via the sheet's JSONP-style gviz
   endpoint, so no server or API key is needed) and computes churn stats
   on the spot. Hit "Refresh now" to prove it's a live request, not a
   screenshot.
2. **Latest pipeline run** — fetches `runs/latest_run.json` from this repo
   via `raw.githubusercontent.com` and renders each agent's actual output
   plus the chain-of-custody audit.

Before publishing, edit `docs/config.js` with your GitHub username and repo
name.

## Setup checklist

- [ ] Set `docs/config.js` → `githubUser` / `githubRepo`
- [ ] `git init`, commit, push to a **public** GitHub repo
- [ ] Enable GitHub Pages → serve from `/docs` on `main`
- [ ] Run `python orchestrator.py` at least once locally with a real
      `GEMINI_API_KEY`, then commit the resulting `runs/` files
- [ ] Confirm the Pages URL loads without login and both panels populate
