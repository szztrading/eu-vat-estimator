# ===== Path setup to ensure local imports work =====
import sys, os
HERE = os.path.dirname(__file__)
ROOT = os.path.dirname(HERE)
if HERE not in sys.path:
    sys.path.insert(0, HERE)
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)
# ===================================================

import streamlit as st
import pandas as pd
import yaml
from datetime import datetime
from io import BytesIO

# Local imports (do NOT use "app." prefix when this file sits inside app/)
from vat_calculator import apply_country_rates, derive_net_gross, country_summary
from parsers.amazon import normalize_columns

# ---------- Page config ----------
st.set_page_config(page_title="EU VAT Estimator", layout="wide")
st.title("EU VAT Estimator (Amazon FBA/FBM)")
st.caption("v0.3 - Upload Amazon CSV/XLSX, auto-calc EU VAT; UK excluded by default")

# ---------- Config loader ----------
@st.cache_data
def load_config():
    with open(os.path.join(ROOT, "config.yaml"), "r", encoding="utf-8") as f:
        return yaml.safe_load(f)

config = load_config()
rates = {k: v.get("standard_rate", 0) for k, v in config.get("countries", {}).items()}
hide_uk = config.get("ui", {}).get("hide_uk", True)

# ---------- Inputs ----------
col1, col2 = st.columns([2, 1])
with col1:
    uploaded = st.file_uploader("Upload Amazon report (CSV or XLSX)", type=["csv", "xlsx"])
with col2:
    period = st.date_input(
        "Period",
        value=(datetime(datetime.now().year, 1, 1).date(), datetime.now().date())
    )

# ---------- Main ----------
if uploaded:
    # 1) Read file
    try:
        if uploaded.name.lower().endswith(".csv"):
            df = pd.read_csv(uploaded)
        else:
            df = pd.read_excel(uploaded)
    except Exception as e:
        st.error(f"Failed to read file: {e}")
        st.stop()

    st.subheader("Raw preview")
    st.dataframe(df.head(50), width="stretch")

    # 2) Normalize + rates + net/gross/vat derivation
    df = normalize_columns(df)
    df = apply_country_rates(df, rates)
    df = derive_net_gross(df)

    # 3) Filter out UK if configured
    if hide_uk and "country" in df.columns:
        df = df[df["country"] != "UK"]

    # 4) Date filter
    if "date" in df.columns and isinstance(period, tuple) and len(period) == 2:
        start = pd.to_datetime(period[0])
        end = pd.to_datetime(period[1]) + pd.Timedelta(days=1)
        df = df[(df["date"] >= start) & (df["date"] < end)]

    # 5) Summary with guard-rails
    st.subheader("Country VAT summary")
    try:
        summary = country_summary(df)
    except KeyError as e:
        st.error(f"Missing required column: {e}")
        st.info("Check if 'country' and 'vat_amount' exist (or can be derived).")
        st.write("Normalized data (first 50 rows):")
        st.dataframe(df.head(50), width="stretch")
        st.stop()

    st.dataframe(summary, width="stretch")

    # 6) Download buttons (CSV + Excel)
    # 6a) CSV
    csv_bytes = summary.to_csv(index=False).encode("utf-8")
    st.download_button(
        "Download VAT summary (CSV)",
        data=csv_bytes,
        file_name="vat_summary.csv",
        mime="text/csv",
        type="primary",
    )

    # 6b) Excel with two sheets: Summary + NormalizedDataSample
    try:
        bio = BytesIO()
        with pd.ExcelWriter(bio, engine="openpyxl") as writer:
            summary.to_excel(writer, index=False, sheet_name="Summary")
            df.head(1000).to_excel(writer, index=False, sheet_name="NormalizedDataSample")
        bio.seek(0)
        st.download_button(
            "Download VAT report (Excel)",
            data=bio,
            file_name="vat_report.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
    except Exception as e:
        st.warning(f"Excel export failed: {e}")

    # 7) Debug/inspection
    with st.expander("Normalized data (first 200 rows)"):
        st.dataframe(df.head(200), width="stretch")

else:
    st.info("Upload an Amazon report to start.")
