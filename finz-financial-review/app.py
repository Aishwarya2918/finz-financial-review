import os
import streamlit as st
import finance as f

st.set_page_config(page_title="AI Financial Review", layout="wide")
try:  # Streamlit Cloud secrets -> env var for the Anthropic SDK
    if "ANTHROPIC_API_KEY" in st.secrets: os.environ["ANTHROPIC_API_KEY"] = st.secrets["ANTHROPIC_API_KEY"]
except Exception:
    pass
st.session_state.setdefault("v", 0)  # bumped after each save so stale editor state is discarded

st.title("AI-Native Financial Review")
up = st.sidebar.file_uploader("Bank transactions (.xlsx)", type="xlsx")
try:
    df = f.categorize(f.load(up or "data/transactions.xlsx"))
except Exception as e:
    st.error(f"Could not read the transaction file: {e}"); st.stop()
months = sorted(df["month"].unique())
rec = f.reconciliation(df)
st.sidebar.metric("Transactions", len(df)); st.sidebar.metric("Need review", int(df["needs_review"].sum()))
if rec["ok"]: st.sidebar.success("Reconciles to bank total")
else: st.sidebar.error("Reconciliation FAILED")
st.sidebar.caption(f"P&L net {rec['pnl_net']:,.2f} + Non-P&L {rec['non_pnl_net']:,.2f} = bank {rec['bank_total']:,.2f}")

def editor(d, key, review=False):
    """Editable category. Saved corrections persist in SQLite and flow into the P&L.
    In the review queue, tick 'resolve' to confirm the current category without changing it."""
    view = d[["txn_id", "date", "description", "amount", "category", "section", "confidence", "reason"]].copy()
    view["date"] = view["date"].dt.date
    if review: view["resolve"] = False
    fixed = [c for c in view.columns if c not in ("category", "resolve")]
    out = st.data_editor(view, key=f"{key}_{st.session_state.v}", hide_index=True, disabled=fixed,
        column_config={"category": st.column_config.SelectboxColumn(options=sorted(f.CAT_SECTION)),
                       "confidence": st.column_config.ProgressColumn(min_value=0.0, max_value=1.0)})
    if st.button("Save", key=f"{key}_save"):
        for (_, a), (_, b) in zip(view.iterrows(), out.iterrows()):
            if a["category"] != b["category"] or (review and b["resolve"]):
                f.save_override(b["txn_id"], b["category"])
        st.session_state.v += 1
        st.rerun()

t1, t2, t3, t4, t5 = st.tabs(["Transactions", "Review queue", "P&L", "Variances", "AI analyst"])
with t1:
    sec = st.multiselect("Section", f.SECTIONS, default=f.SECTIONS)
    st.caption("Non-P&L rows (capex, tax, loans, owner draws, gift cards) are excluded from profit.")
    editor(df[df["section"].isin(sec)], "all")
with t2:
    q = df[df["needs_review"]]
    if len(q):
        st.write(f"**{len(q)} items** need judgment. Change the category and/or tick *resolve*, then Save.")
        editor(q, "review", review=True)
    else:
        st.success("Nothing left to review.")
with t3:
    st.dataframe(f.pnl(df).style.format("{:,.2f}"))
    with st.expander("By category"): st.dataframe(f.by_category(df))
with t4:
    c1, c2 = st.columns(2)
    a = c1.selectbox("From", months, 0); b = c2.selectbox("To", months, len(months) - 1)
    if a == b:
        st.info("Pick two different months.")
    else:
        v = f.variances(df, a, b); m = v[v["material"]]
        st.caption("Material = change of at least 10% and $500.")
        st.dataframe(m, hide_index=True)
        if len(m):
            pick = st.selectbox("Drill into category", list(m["category"]))
            st.write("Transactions behind this variance:")
            d = f.txns(df, category=pick); d = d[d["month"].isin([a, b])]
            st.dataframe(d[["txn_id", "date", "description", "amount", "month"]], hide_index=True)
with t5:
    import ai
    if not os.getenv("ANTHROPIC_API_KEY"): st.warning("Set ANTHROPIC_API_KEY to enable the analyst.")
    st.session_state.setdefault("hist", []); st.session_state.setdefault("log", [])
    for who, txt in st.session_state.log: st.chat_message(who).write(txt)
    if p := st.chat_input("e.g. Why did operating profit change between February and March?"):
        st.chat_message("user").write(p)
        try:
            with st.spinner("Querying the data..."):
                ans, used, st.session_state.hist = ai.ask(p, df, st.session_state.hist)
            ans += "\n\n*Data used: " + "; ".join(f"`{n}({k})`" for n, k in used) + "*"
        except Exception as e:
            ans = f"Analyst error: {e}"
        st.session_state.log += [("user", p), ("assistant", ans)]; st.chat_message("assistant").write(ans)
