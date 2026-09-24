"""Run: python test_finance.py   (or pytest)"""
import os, finance as f
f.DB = "test_review.db"
if os.path.exists(f.DB): os.remove(f.DB)
df = f.categorize(f.load("data/transactions.xlsx"))

def test_all_rows_categorized():
    assert len(df) == 181 and (df.category != "Uncategorized").all()

def test_pnl_reconciles_to_bank_total():
    assert f.reconciliation(df)["ok"]

def test_non_pnl_excluded_from_profit():
    for d in ["Equipment purchase - new oven", "Sales tax remittance", "Loan principal repayment", "Owner distribution", "Gift card sales deposit"]:
        assert (df[df.description == d].section == "Non-P&L").all(), d

def test_profit_arithmetic():
    p = f.pnl(df)
    for m in p.columns:
        assert abs(p.loc["Gross Profit", m] - (p.loc["Revenue", m] - p.loc["COGS", m])) < .01
        assert abs(p.loc["Operating Profit", m] - (p.loc["Gross Profit", m] - p.loc["Payroll", m] - p.loc["Operating Expenses", m])) < .01

def test_correction_persists_and_changes_pnl():
    before = f.pnl(df).loc["Operating Profit"].sum()
    f.save_override("T1061", "Repairs & Maintenance")
    d2 = f.categorize(f.load("data/transactions.xlsx"))
    row = d2[d2.txn_id == "T1061"].iloc[0]
    assert row.section == "Opex" and not row.needs_review
    assert f.pnl(d2).loc["Operating Profit"].sum() < before

def test_review_queue_contains_judgment_items():
    r = set(df[df.needs_review].description)
    assert "Large catering event food purchase" in r and "Annual license renewal" in r

if __name__ == "__main__":
    for n, fn in list(globals().items()):
        if n.startswith("test_"): fn(); print("PASS", n)
    os.remove(f.DB)
