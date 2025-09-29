# —— 放在文件最顶端 —— #
import sys, os
HERE = os.path.dirname(__file__)               # .../app
ROOT = os.path.dirname(HERE)                   # 仓库根目录
if HERE not in sys.path:
    sys.path.insert(0, HERE)
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)
# —— 顶部注入结束 —— #


import streamlit as st
import pandas as pd
import yaml
from datetime import datetime

from vat_calculator import apply_country_rates, derive_net_gross, country_summary
from parsers.amazon import normalize_columns


st.set_page_config(page_title="EU VAT Estimator", layout="wide")
st.title("🇪🇺 EU VAT Estimator (Amazon FBA/FBM)")
st.caption("v0.1 • UK excluded by default • Upload Amazon VAT Transaction report or compatible CSV/XLSX")

@st.cache_data
def load_config():
    with open("config.yaml", "r", encoding="utf-8") as f:
        return yaml.safe_load(f)

config = load_config()
rates = {k: v.get("standard_rate", 0) for k, v in config.get("countries", {}).items()}
hide_uk = config.get("ui", {}).get("hide_uk", True)

c1, c2 = st.columns([2, 1])
with c1:
    uploaded = st.file_uploader("Upload report (CSV/XLSX)", type=["csv", "xlsx"])
with c2:
    period = st.date_input(
        "Period",
        value=(datetime(datetime.now().year, 1, 1).date(), datetime.now().date())
    )

if uploaded:
    df = pd.read_csv(uploaded) if uploaded.name.lower().endswith(".csv") else pd.read_excel(uploaded)

    st.subheader("Raw preview")
    st.dataframe(df.head(50), use_container_width=True)

    df = normalize_columns(df)
    df = apply_country_rates(df, rates)
    df = derive_net_gross(df)

    if hide_uk and "country" in df.columns:
        df = df[df["country"] != "UK"]

    if "date" in df.columns and isinstance(period, tuple) and len(period) == 2:
        start, end = pd.to_datetime(period[0]), pd.to_datetime(period[1]) + pd.Timedelta(days=1)
        df = df[(df["date"] >= start) & (df["date"] < end)]

    st.subheader("Country VAT summary")
    summary = country_summary(df)
    st.dataframe(summary, use_container_width=True)

    st.download_button(
        "⬇️ Download summary (CSV)",
        summary.to_csv(index=False).encode("utf-8"),
        file_name="vat_summary.csv",
        mime="text/csv"
    )

    with st.expander("Normalized data (first 200 rows)"):
        st.dataframe(df.head(200), use_container_width=True)

else:
    st.info("Upload an Amazon report to start.")
