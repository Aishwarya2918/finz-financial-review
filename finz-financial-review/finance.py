"""Deterministic financial logic. No LLM touches any number in this file."""
import re, sqlite3, json
import pandas as pd

DB = "review.db"
# (regex, category, section, confidence, note)
RULES = [
 (r"POS batch deposit - food", "Food Sales", "Revenue", .99, ""),
 (r"POS batch deposit - bev", "Beverage Sales", "Revenue", .99, ""),
 (r"Catering invoice", "Catering Revenue", "Revenue", .97, ""),
 (r"Delivery marketplace payout", "Delivery Revenue", "Revenue", .9, "Payout may be net of platform fees"),
 (r"Refunds and discounts", "Refunds & Discounts", "Revenue", .95, "Contra-revenue: reduces revenue"),
 (r"Delivery platform commission", "Delivery Commissions", "Opex", .9, "Fee: opex vs contra-revenue is a judgment"),
 (r"Large catering event", "Food Purchases", "COGS", .6, "Unusually large; one-off event cost?"),
 (r"Food inventory", "Food Purchases", "COGS", .99, ""),
 (r"Beverage inventory", "Beverage Purchases", "COGS", .99, ""),
 (r"packaging", "Packaging", "COGS", .9, "Packaging: COGS or opex?"),
 (r"Payroll taxes", "Payroll Taxes & Benefits", "Payroll", .98, ""),
 (r"Payroll -|Manager salary", "Wages & Salaries", "Payroll", .98, ""),
 (r"Equipment purchase", "Equipment (Capex)", "Non-P&L", .8, "Capital asset: capitalize and depreciate"),
 (r"Sales tax remittance", "Sales Tax Payable", "Non-P&L", .85, "Liability payment, not an expense"),
 (r"Gift card", "Gift Card Liability", "Non-P&L", .7, "Deferred revenue until redeemed"),
 (r"Loan principal", "Loan Principal", "Non-P&L", .85, "Financing; only interest hits P&L"),
 (r"Owner distribution", "Owner Distribution", "Non-P&L", .95, "Equity"),
 (r"Annual license", "Licenses & Permits", "Opex", .65, "Annual amount: may need spreading over 12 months"),
 (r"Rent", "Rent", "Opex", .99, ""),
 (r"POS/software", "Software", "Opex", .98, ""),
 (r"Insurance", "Insurance", "Opex", .98, ""),
 (r"Accounting", "Professional Fees", "Opex", .98, ""),
 (r"Internet", "Telecom", "Opex", .98, ""),
 (r"Utilities", "Utilities", "Opex", .98, ""),
 (r"Cleaning", "Cleaning & Linen", "Opex", .98, ""),
 (r"Marketing", "Marketing", "Opex", .98, ""),
 (r"Repairs", "Repairs & Maintenance", "Opex", .95, ""),
 (r"Office", "Office Supplies", "Opex", .98, ""),
]
CAT_SECTION = {c: s for _, c, s, _, _ in RULES}
SECTIONS = ["Revenue", "COGS", "Payroll", "Opex", "Non-P&L"]

def _conn():
    c = sqlite3.connect(DB)
    c.execute("CREATE TABLE IF NOT EXISTS overrides(txn_id TEXT PRIMARY KEY, category TEXT)")
    return c

def load(src) -> pd.DataFrame:
    df = pd.read_excel(src)
    df.columns = ["txn_id", "date", "description", "counterparty", "amount", "method"]
    df["date"] = pd.to_datetime(df["date"])
    df["month"] = df["date"].dt.strftime("%Y-%m")
    return df.sort_values(["date", "txn_id"]).reset_index(drop=True)

def categorize(df: pd.DataFrame) -> pd.DataFrame:
    """Rules first; anything unmatched is 'Uncategorized' (LLM fallback lives in ai.py)."""
    out = []
    for d in df["description"]:
        for pat, cat, sec, conf, note in RULES:
            if re.search(pat, d, re.I):
                out.append((cat, sec, conf, note, "rule")); break
        else:
            out.append(("Uncategorized", "Opex", 0.0, "No rule matched", "none"))
    df = df.copy()
    df[["category", "section", "confidence", "reason", "source"]] = pd.DataFrame(out, index=df.index)
    # statistical anomaly: amount far from the typical amount for the same recurring description
    base = df["description"].str.replace(r"week \d+", "week N", regex=True)
    med = df.groupby(base)["amount"].transform(lambda s: s.abs().median())
    cnt = df.groupby(base)["amount"].transform("count")
    odd = (cnt >= 3) & (df["amount"].abs() > 3 * med)
    df.loc[odd, "confidence"] = df.loc[odd, "confidence"].clip(upper=.7)
    df.loc[odd, "reason"] = "Unusual amount vs. similar transactions"
    return apply_overrides(df)

def apply_overrides(df):
    ov = pd.read_sql("SELECT * FROM overrides", _conn()).set_index("txn_id")["category"].to_dict()
    df = df.copy()
    m = df["txn_id"].isin(ov)
    df.loc[m, "category"] = df.loc[m, "txn_id"].map(ov)
    df.loc[m, "section"] = df.loc[m, "category"].map(lambda c: CAT_SECTION.get(c, "Opex"))
    df.loc[m, ["confidence", "source", "reason"]] = [1.0, "user", "Confirmed/corrected by user"]
    df["needs_review"] = (df["confidence"] < 0.9)
    return df

def save_override(txn_id, category):
    with _conn() as c:
        c.execute("INSERT OR REPLACE INTO overrides VALUES(?,?)", (txn_id, category))

def _signed(df):  # revenue positive, costs positive (as costs)
    return df["amount"].where(df["section"] == "Revenue", -df["amount"])

def pnl(df) -> pd.DataFrame:
    p = df[df["section"] != "Non-P&L"].assign(v=lambda d: _signed(d))
    t = p.pivot_table(index="section", columns="month", values="v", aggfunc="sum", fill_value=0)
    t = t.reindex(["Revenue", "COGS", "Payroll", "Opex"]).fillna(0)
    t.loc["Gross Profit"] = t.loc["Revenue"] - t.loc["COGS"]
    t.loc["Operating Profit"] = t.loc["Gross Profit"] - t.loc["Payroll"] - t.loc["Opex"]
    order = ["Revenue", "COGS", "Gross Profit", "Payroll", "Opex", "Operating Profit"]
    return t.loc[order].round(2).rename(index={"Opex": "Operating Expenses"})

def by_category(df) -> pd.DataFrame:
    p = df[df["section"] != "Non-P&L"].assign(v=lambda d: _signed(d))
    return p.pivot_table(index=["section", "category"], columns="month", values="v", aggfunc="sum", fill_value=0).round(2)

def reconciliation(df) -> dict:
    inn = df[df["section"] != "Non-P&L"]["amount"].sum(); out = df[df["section"] == "Non-P&L"]["amount"].sum()
    return {"pnl_net": round(inn, 2), "non_pnl_net": round(out, 2),
            "bank_total": round(df["amount"].sum(), 2), "ok": abs(inn + out - df["amount"].sum()) < .01}

def variances(df, a, b, pct=.10, min_abs=500) -> pd.DataFrame:
    c = by_category(df).reindex(columns=[a, b], fill_value=0).reset_index()
    c["change"] = (c[b] - c[a]).round(2)
    c["change_pct"] = (c["change"] / c[a].abs().replace(0, float("nan")) * 100).round(1)
    c["material"] = (c["change"].abs() >= min_abs) & (c["change_pct"].abs().fillna(999) >= pct * 100)
    return c.sort_values("change", key=abs, ascending=False)

def txns(df, month=None, category=None, section=None, needs_review=None):
    d = df
    if month: d = d[d["month"] == month]
    if category: d = d[d["category"] == category]
    if section: d = d[d["section"] == section]
    if needs_review: d = d[d["needs_review"]]
    return d

# ---- tool layer used by the AI analyst: the LLM can only read numbers from here ----
def run_tool(name, args, df):
    if name == "get_pnl":
        p = pnl(df); m = args.get("month")
        return (p[[m]] if m in p.columns else p).to_dict()
    if name == "get_category_breakdown":
        return by_category(df).reset_index().to_dict("records")
    if name == "compare_months":
        return variances(df, args["month_a"], args["month_b"]).head(10).to_dict("records")
    if name == "get_transactions":
        d = txns(df, args.get("month"), args.get("category"), args.get("section"))
        return d[["txn_id", "date", "description", "amount", "category", "section"]].astype(str).head(40).to_dict("records")
    if name == "get_review_items":
        return txns(df, needs_review=True)[["txn_id", "description", "amount", "category", "reason"]].astype(str).to_dict("records")
    return {"error": f"unknown tool {name}"}
