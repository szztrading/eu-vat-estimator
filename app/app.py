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

# Local imports (this file sits inside app/)
from vat_calculator import apply_country_rates, derive_net_gross, country_summary
from parsers.amazon import normalize_columns

# ---------- Page config ----------
st.set_page_config(page_title="EU VAT Estimator (Multi-file)", layout="wide")
st.title("EU VAT Estimator (Amazon FBA/FBM) — Multi-file")
st.caption("Upload multiple Amazon VAT reports (CSV/XLSX) to combine & analyze. UK excluded by default.")

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
    uploads = st.file_uploader(
        "Upload one or more Amazon reports (CSV/XLSX)",
        type=["csv", "xlsx"],
        accept_multiple_files=True,
    )
with col2:
    period = st.date_input(
        "Period filter",
        value=(datetime(datetime.now().year, 1, 1).date(), datetime.now().date())
    )

# ---------- Helpers ----------
def _read_any(file) -> pd.DataFrame:
    """Read CSV or XLSX with a few encoding fallbacks (for CSV)."""
    name = file.name
    if name.lower().endswith(".csv"):
        for enc in ("utf-8", "utf-8-sig", "cp1252", "latin1"):
            try:
                file.seek(0)
                return pd.read_csv(file, encoding=enc)
            except Exception:
                continue
        # last try default
        file.seek(0)
        return pd.read_csv(file)
    else:
        file.seek(0)
        return pd.read_excel(file)

def _safe_concat(dfs):
    if not dfs:
        return pd.DataFrame()
    # align columns by union
    cols = set()
    for d in dfs:
        cols |= set(d.columns)
    cols = list(cols)
    aligned = []
    for d in dfs:
        missing = [c for c in cols if c not in d.columns]
        for m in missing:
            d[m] = pd.NA
        aligned.append(d[cols])
    return pd.concat(aligned, ignore_index=True)

# ---------- Main ----------
if uploads and len(uploads) > 0:
    raw_tabs = st.tabs([f"Raw: {u.name}" for u in uploads])

    raw_frames = []
    read_errors = []

    # 1) Read each file and preview
    for idx, upl in enumerate(uploads):
        try:
            df_raw = _read_any(upl)
            df_raw["__source_file__"] = upl.name
            raw_frames.append(df_raw)
            with raw_tabs[idx]:
                st.write(f"Shape: {df_raw.shape}, Columns: {len(df_raw.columns)}")
                st.dataframe(df_raw.head(30), width="stretch")
        except Exception as e:
            read_errors.append((upl.name, str(e)))

    if read_errors:
        st.error("Some files failed to read:")
        for name, err in read_errors:
            st.write(f"- {name}: {err}")
        if not raw_frames:
            st.stop()

    # 2) Combine & normalize
    raw_all = _safe_concat(raw_frames)

    st.subheader("Combined — Normalization preview (first 50 rows)")
    df = normalize_columns(raw_all)
    st.dataframe(df.head(50), width="stretch")

    # 3) VAT rates & amounts derivation
    df = apply_country_rates(df, rates)
    df = derive_net_gross(df)

    # 4) Hide UK if configured
    if hide_uk and "country" in df.columns:
        df = df[df["country"] != "UK"]

    # 5) Period filter
    if "date" in df.columns and isinstance(period, tuple) and len(period) == 2:
        start = pd.to_datetime(period[0])
        end = pd.to_datetime(period[1]) + pd.Timedelta(days=1)
        df = df[(df["date"] >= start) & (df["date"] < end)]

    # 6) Country summary (combined)
    st.subheader("Country VAT summary (Combined)")
    try:
        summary = country_summary(df)
    except KeyError as e:
        st.error(f"Missing required column: {e}")
        st.info("Check if 'country' and 'vat_amount' exist (or can be derived).")
        st.write("Normalized data (first 50 rows):")
        st.dataframe(df.head(50), width="stretch")
        st.stop()

    st.dataframe(summary, width="stretch")

    # 7) File × Country pivot (see contribution by file)
    if "__source_file__" in df.columns:
        st.subheader("Breakdown by File × Country")
        # 仅保留必要列，避免 groupby 报错
        mini = df[["__source_file__", "country"]].copy()
        mini["vat_amount"] = pd.to_numeric(df.get("vat_amount", 0), errors="coerce").fillna(0)
        pivot = (
            mini.groupby(["__source_file__", "country"], dropna=False)["vat_amount"]
            .sum()
            .reset_index()
            .sort_values(["__source_file__", "country"])
        )
        st.dataframe(pivot, width="stretch")
    else:
        pivot = pd.DataFrame()

    # 8) Debug: vat_collector distribution (after normalization)
    with st.expander("Debug: vat_collector value counts"):
        if "vat_collector" in df.columns:
            st.write(df["vat_collector"].value_counts(dropna=False))
        else:
            st.write("No 'vat_collector' column after normalization.")

    # 9) Downloads (CSV + Excel)
    st.subheader("Downloads")

    # 9a) Country summary CSV
    st.download_button(
        "Download Country Summary (CSV)",
        data=summary.to_csv(index=False).encode("utf-8"),
        file_name="vat_summary_combined.csv",
        mime="text/csv",
        type="primary",
    )

    # 9b) File × Country CSV
    if not pivot.empty:
        st.download_button(
            "Download File×Country (CSV)",
            data=pivot.to_csv(index=False).encode("utf-8"),
            file_name="vat_by_file_country.csv",
            mime="text/csv",
        )

    # 9c) Excel package (Summary + ByFileCountry + NormalizedSample)
    try:
        bio = BytesIO()
        with pd.ExcelWriter(bio, engine="openpyxl") as writer:
            summary.to_excel(writer, index=False, sheet_name="Summary")
            if not pivot.empty:
                pivot.to_excel(writer, index=False, sheet_name="ByFileCountry")
            df.head(2000).to_excel(writer, index=False, sheet_name="NormalizedSample")
        bio.seek(0)
        st.download_button(
            "Download VAT Report (Excel)",
            data=bio,
            file_name="vat_report_combined.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
    except Exception as e:
        st.warning(f"Excel export failed: {e}")

else:
    st.info("Upload one or more Amazon reports to start.")
