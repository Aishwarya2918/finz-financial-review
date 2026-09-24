"""AI layer: (1) LLM fallback for unmatched transactions, (2) tool-calling analyst.
The LLM never computes totals: every number comes from finance.run_tool()."""
import os, json
import anthropic
import finance as f

MODEL = os.getenv("MODEL", "claude-sonnet-4-6")
client = lambda: anthropic.Anthropic()  # reads ANTHROPIC_API_KEY

def llm_categorize(rows):
    """rows: list of {txn_id, description, counterparty, amount}. Returns {txn_id: category}."""
    cats = list(f.CAT_SECTION)
    r = client().messages.create(model=MODEL, max_tokens=1000,
        system=f"Classify restaurant bank transactions. Choose ONLY from: {cats}. Reply with JSON only: {{txn_id: category}}.",
        messages=[{"role": "user", "content": json.dumps(rows)}])
    txt = r.content[0].text.replace("```json", "").replace("```", "").strip()
    return {k: v for k, v in json.loads(txt).items() if v in f.CAT_SECTION}

TOOLS = [
 {"name": "get_pnl", "description": "Monthly P&L (Revenue, COGS, Gross Profit, Payroll, Operating Expenses, Operating Profit). Optional month 'YYYY-MM'.",
  "input_schema": {"type": "object", "properties": {"month": {"type": "string"}}}},
 {"name": "get_category_breakdown", "description": "P&L amounts by category and month.", "input_schema": {"type": "object", "properties": {}}},
 {"name": "compare_months", "description": "Category-level variances between two months, largest first.",
  "input_schema": {"type": "object", "properties": {"month_a": {"type": "string"}, "month_b": {"type": "string"}}, "required": ["month_a", "month_b"]}},
 {"name": "get_transactions", "description": "Transactions filtered by month, category, section (Revenue/COGS/Payroll/Opex/Non-P&L).",
  "input_schema": {"type": "object", "properties": {"month": {"type": "string"}, "category": {"type": "string"}, "section": {"type": "string"}}}},
 {"name": "get_review_items", "description": "Transactions needing human review, with reasons.", "input_schema": {"type": "object", "properties": {}}},
]
SYSTEM = ("You are a financial analyst for a restaurant (data: Jan-Mar 2026). Answer ONLY using tool results; never compute or guess totals. "
          "Cite evidence: quote transaction IDs (e.g. T1031) and category names behind each claim. For 'why' questions, call compare_months then "
          "get_transactions on the top drivers. If data is missing, say so. Non-P&L items (capex, tax, loans, owner draws, gift cards) are excluded from profit.")

def ask(question, df, history=None):
    msgs = (history or []) + [{"role": "user", "content": question}]
    used = []
    for _ in range(8):
        r = client().messages.create(model=MODEL, max_tokens=1500, system=SYSTEM, tools=TOOLS, messages=msgs)
        msgs.append({"role": "assistant", "content": r.content})
        calls = [b for b in r.content if b.type == "tool_use"]
        if not calls:
            return "".join(b.text for b in r.content if b.type == "text"), used, msgs
        res = []
        for c in calls:
            used.append((c.name, c.input))
            res.append({"type": "tool_result", "tool_use_id": c.id, "content": json.dumps(f.run_tool(c.name, c.input, df), default=str)})
        msgs.append({"role": "user", "content": res})
    return "I couldn't complete that analysis.", used, msgs
