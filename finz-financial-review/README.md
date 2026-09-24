# AI-Native Financial Review
Ingests bank transactions, categorizes them, builds a monthly P&L, explains variances, and lets you investigate via an AI analyst.

## Run
    pip install -r requirements.txt
    export ANTHROPIC_API_KEY=...   # only needed for the AI analyst
    streamlit run app.py

Set `MODEL` env var to override the default Claude model (`claude-sonnet-4-6`).
On Streamlit Cloud add `ANTHROPIC_API_KEY = "..."` under Settings > Secrets.

## Key decisions
- **Deterministic:** categorization rules, P&L, variances, reconciliation (`finance.py`). All financial totals come from code.
- **AI:** ambiguous-item classification fallback and the analyst (`ai.py`). The analyst has no numbers of its own: it can only call typed tools (`get_pnl`, `compare_months`, `get_transactions`, ...) and must cite transaction IDs.
- **Non-P&L treatment:** capex, sales-tax payments, loan principal, owner distributions, gift-card deposits are excluded from profit and flagged for review.
- **Review:** items with confidence < 0.9 or unusual amounts are queued; user corrections persist in SQLite and override rules.
- **Verification:** the sidebar reconciliation (P&L + Non-P&L = bank total) must always pass.

## Limitations / next steps
Free hosts may reset SQLite (use hosted Postgres); prepaid/annual items are flagged, not amortized; unit tests to add.

## Tests
    python test_finance.py
