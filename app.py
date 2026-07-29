from __future__ import annotations

import hmac
import html
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "src"))

try:
    from dotenv import load_dotenv
except ImportError:
    pass
else:
    load_dotenv(ROOT / ".env")

import streamlit as st

from text2sql.database import SQLiteAnalyticsDatabase
from text2sql.generator import RuleBasedGenerator
from text2sql.providers import LangChainGenerator, OpenAIGenerator, OpenAIQueryOptimizer
from text2sql.service import TextToSQLService
from text2sql.warehouse import databricks_database, snowflake_database

st.set_page_config(page_title="QueryCraft · Ask Your Data", page_icon="⌁", layout="wide")
st.markdown("""<style>
@keyframes drift{50%{background-position:100% 50%}}.stApp{background:#071018;color:#eff8ff}.hero{padding:2.5rem;border:1px solid #ffffff1c;border-radius:26px;background:linear-gradient(120deg,#102c3b,#171b3d,#102c3b);background-size:200% 200%;animation:drift 10s ease infinite}.mark{color:#67e8f9;letter-spacing:.18em;font-weight:800}.sqlbox{border-left:3px solid #67e8f9;padding:.8rem 1rem;background:#071018;border-radius:4px}.hint{padding:.8rem 1rem;border:1px solid #ffffff18;border-radius:12px;color:#a8bfce}
[data-testid="stSidebar"]{background:#09151f}div.stButton>button{background:#67e8f9;color:#061018;border:0;border-radius:99px;font-weight:800}
@media (prefers-reduced-motion:reduce){*,*::before,*::after{animation:none!important;transition:none!important;scroll-behavior:auto!important}}
</style><div class="hero"><div class="mark">QUERYCRAFT</div><h1>Ask the business question.<br>Inspect the SQL. Trust the boundary.</h1><p>Schema-aware analytics with a deterministic offline engine and an opt-in OpenAI generator.</p></div>""", unsafe_allow_html=True)

backend = os.getenv("DATABASE_BACKEND", "sqlite").strip().lower()
timeout_ms = int(os.getenv("QUERY_TIMEOUT_MS", "1500"))
max_rows = int(os.getenv("MAX_RESULT_ROWS", "200"))
try:
    if backend == "sqlite":
        database_path = Path(os.getenv("DATABASE_PATH", ROOT / ".local" / "food_delivery.db"))
        db = SQLiteAnalyticsDatabase(database_path, timeout_ms=timeout_ms, max_rows=max_rows)
        db.initialize(ROOT / "data" / "food_delivery.sql")
    elif backend == "databricks":
        db = databricks_database(timeout_ms, max_rows)
    elif backend == "snowflake":
        db = snowflake_database(timeout_ms, max_rows)
    else:
        raise ValueError("DATABASE_BACKEND must be sqlite, databricks, or snowflake")
except Exception as exc:
    st.error(f"Database configuration failed: {exc}")
    st.stop()

if "history" not in st.session_state:
    st.session_state.history = []
required_password = os.getenv("APP_PASSWORD", "")
if required_password and not st.session_state.get("authenticated"):
    st.subheader("Private analytics workspace")
    password = st.text_input("Workspace password", type="password")
    if st.button("Sign in"):
        st.session_state.authenticated = hmac.compare_digest(password, required_password)
        if st.session_state.authenticated:
            st.rerun()
        st.error("Incorrect password")
    st.stop()

with st.sidebar:
    st.header("Workspace")
    provider_name = st.selectbox("SQL generator", ["Local rules", "OpenAI structured", "LangChain LCEL"])
    api_key = ""
    optimize = False
    if not provider_name.startswith("Local"):
        api_key = st.text_input("OpenAI API key", type="password", help="Leave blank to use OPENAI_API_KEY from the server environment.")
        model = st.text_input("Model", os.getenv("OPENAI_MODEL", "gpt-4.1-mini"))
        optimize = st.checkbox("Run one plan-aware optimization pass", value=os.getenv("OPTIMIZE_QUERIES", "0") == "1")
    st.metric("Tables", len(db.schema().tables))
    st.caption(f"Read-only {backend.title()} · ≤ {db.max_rows} rows · {db.timeout_ms} ms budget")
    with st.expander("Schema"):
        st.code(db.schema().prompt_text(), language="sql")
    if st.button("Clear session history"):
        st.session_state.history = []
        st.rerun()

st.markdown("### What would you like to know?")
examples = ["Top 5 restaurants by revenue", "Average rating by restaurant", "Recent 10 orders", "Order count by status"]
example_cols = st.columns(4)
for column, text in zip(example_cols, examples):
    if column.button(text, use_container_width=True):
        st.session_state.question = text
question = st.text_area("Question", value=st.session_state.get("question", ""), placeholder="e.g. Which restaurants earned the most completed revenue?", height=95, label_visibility="collapsed")
run = st.button("Generate and run safe query", type="primary")

if run:
    try:
        optimizer = None
        if not provider_name.startswith("Local"):
            resolved_key = api_key or os.getenv("OPENAI_API_KEY", "")
            if not resolved_key:
                raise ValueError("Enter an API key for the opt-in OpenAI provider, or choose Local rules.")
            if provider_name.startswith("LangChain"):
                generator = LangChainGenerator(api_key=resolved_key, model=model, dialect=backend)
            else:
                generator = OpenAIGenerator(api_key=resolved_key, model=model, dialect=backend)
            if optimize:
                optimizer = OpenAIQueryOptimizer(api_key=resolved_key, model=model, dialect=backend)
        else:
            generator = RuleBasedGenerator()
        with st.spinner("Inspecting schema and validating SQL…"):
            result = TextToSQLService(db, generator, optimizer).ask(question)
        st.session_state.history.insert(0, result)
        st.session_state.history = st.session_state.history[:20]
    except Exception as exc:
        st.error(str(exc))

if st.session_state.history:
    result = st.session_state.history[0]
    a, b, c = st.columns(3)
    a.metric("Rows", len(result.rows))
    b.metric("Latency", f"{result.elapsed_ms:.1f} ms")
    c.metric("Provider", result.provider)
    st.markdown("#### Result")
    st.dataframe([dict(zip(result.columns, row)) for row in result.rows], use_container_width=True, hide_index=True)
    with st.expander("SQL and reasoning", expanded=True):
        st.code(result.sql, language="sql")
        st.write(result.explanation)
        for assumption in result.assumptions:
            st.warning(assumption)
        st.caption("Query plan: " + " · ".join(result.query_plan))
    st.download_button("Download result JSON", json.dumps(result.to_dict(), indent=2), "query-result.json", "application/json")
    if len(st.session_state.history) > 1:
        st.markdown("#### Session history")
        for older in st.session_state.history[1:]:
            safe_question = html.escape(older.question)
            safe_sql = html.escape(older.sql.splitlines()[0])
            st.markdown(f"<div class='hint'><b>{safe_question}</b><br><code>{safe_sql}…</code> · {len(older.rows)} rows</div>", unsafe_allow_html=True)
else:
    st.info("The included database is seeded automatically. Try one of the example questions—no key required.")
