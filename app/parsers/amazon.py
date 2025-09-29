# app/parsers/amazon.py
# -*- coding: utf-8 -*-
"""
Robust Amazon report normalizer:
- Safe base renames (excluding country-related names to avoid duplicate 'country').
- Build a single 'country' column by priority from multiple raw columns.
- Standardize 'vat_collector' to AMAZON/SELLER (MARKETPLACE/MPF/PLATFORM -> AMAZON).
- Parse dates with dayfirst=True, coerce rates to percentages, and amounts to numeric.
- Infer 'channel' from 'sales_channel' (AFN->FBA, MFN->FBM) when possible.
- Fallbacks for order_id and country (from marketplace suffix) included.
"""

from typing import List
import pandas as pd

# Safe base rename map (do NOT put country-related names here)
BASE_MAP = {
    # identity / dates
    "order-id": "order_id",
    "order id": "order_id",
    "amazon-order-id": "order_id",
    "order_id": "order_id",
    "transaction type": "transaction_type",
    "transaction_type": "transaction_type",
    "transaction-event-date": "date",
    "posting-date": "date",
    "invoice-date": "date",
    "purchase-date": "date",
    "shipment-date": "date",
    "tax_calculation_date": "date",

    # fulfillment
    "fulfillment-channel": "channel",
    "fulfilment-channel": "channel",

    # vat collector
    "vat-collection-responsible": "vat_collector",
    "vat collection responsibility": "vat_collector",
    "tax_collection_responsibility": "vat_collector",
    "tax_collection_role": "vat_collector",

    # totals (preferred in VAT calc reports)
    "total_activity_value_amt_vat_excl": "net",
    "total_activity_value_amt_vat_incl": "gross",
    "total_activity_value_vat_amt": "vat_amount",

    # other VAT components (optional)
    "price_of_items_vat_amt": "vat_amount_items",
    "total_price_of_items_vat_amt": "vat_amount_items_total",
    "ship_charge_vat_amt": "vat_amount_shipping",
    "total_ship_charge_vat_amt": "vat_amount_shipping_total",
    "gift_wrap_vat_amt": "vat_amount_giftwrap",
    "total_gift_wrap_vat_amt": "vat_amount_giftwrap_total",

    # rates (will be coerced to percentages)
    "tax-rate": "rate",
    "tax rate": "rate",
    "vat rate": "rate",
    "vat-rate": "rate",
    "vat_rate": "rate",
    "price_of_items_vat_rate_percent": "rate",

    # currency
    "currency": "currency",

    # sales channel (AFN/MFN)
    "sales_channel": "sales_channel",
}

# Country source priority (raw column names as in Amazon exports)
COUNTRY_PRIORITY: List[str] = [
    "VAT_CALCULATION_IMPUTATION_COUNTRY",
    "ARRIVAL_COUNTRY",
    "SALE_ARRIVAL_COUNTRY",
    "SHIP_TO_COUNTRY",
    "MARKETPLACE_COUNTRY",
]

def _coerce_rate_col(series: pd.Series) -> pd.Series:
    """Normalize rate to percentage (e.g., 19 -> 19.0, 0.19 -> 19.0, '19%' -> 19.0)."""
    s = series.astype(str).str.strip()
    pct = s.str.extract(r"([0-9]*\.?[0-9]+)\s*%?")[0]
    s_num = pd.to_numeric(pct, errors="coerce")
    # 0-1 as fraction -> percentage
    s_num = s_num.where(~((s_num >= 0) & (s_num <= 1)), s_num * 100.0)
    return s_num

def _first_nonempty_rowwise(df_sub: pd.DataFrame) -> pd.Series:
    """Return first non-empty value per row across given columns."""
    if df_sub.empty:
        return pd.Series([None] * len(df_sub), index=df_sub.index)
    return df_sub.apply(
        lambda row: next((x for x in row if pd.notna(x) and str(x).strip() != ""), None),
        axis=1
    )

def normalize_columns(df: pd.DataFrame) -> pd.DataFrame:
    """
    Best-effort normalization:
    - Safe base renames (no country renames here).
    - Create a single 'country' column from priority sources.
    - Standardize vat_collector to AMAZON/SELLER.
    - Coerce dates (dayfirst=True), rates, numeric amounts.
    - Infer channel from sales_channel.
    - Fallbacks for order_id and country.
    """
    df = df.copy()
    original_cols = list(df.columns)
    lower_map = {c.lower(): c for c in original_cols}

    # 1) Safe base renames
    mapping = {lower_map[k]: v for k, v in BASE_MAP.items() if k in lower_map}
    df = df.rename(columns=mapping)

    # 2) Build a single 'country' by priority from original columns
    country_candidates = []
    for raw_name in COUNTRY_PRIORITY:
        if raw_name in original_cols:
            country_candidates.append(raw_name)
        elif raw_name.lower() in lower_map:
            country_candidates.append(lower_map[raw_name.lower()])

    if country_candidates:
        country_series = _first_nonempty_rowwise(df[country_candidates])
        df["country"] = country_series
    else:
        # Fallback: derive from 'marketplace' suffix if available (e.g., 'Amazon.de' -> 'DE')
        if "marketplace" in df.columns:
            df["country"] = df["marketplace"].astype(str).str[-2:].str.upper()

    # Normalize 'country'
    if "country" in df.columns:
        df["country"] = df["country"].astype(str).str.strip().str.upper()
        df["country"] = df["country"].replace({"NAN": None, "NONE": None, "": None})
        df["country"] = df["country"].fillna("UNKNOWN")
    else:
        df["country"] = "UNKNOWN"

    # 3) Standardize vat_collector to AMAZON / SELLER
    if "vat_collector" in df.columns:
        vc_raw = df["vat_collector"].astype(str).str.upper().str.strip()

        # Direct replacements for common variants
        vc = vc_raw.replace({
            "AMAZON EU S.A R.L.": "AMAZON",
            "AMAZON EU SARL": "AMAZON",
            "AMAZON SERVICES EUROPE SARL": "AMAZON",
            "MARKETPLACE": "AMAZON",
            "MARKETPLACE FACILITATOR": "AMAZON",
            "AMAZON - MARKETPLACE FACILITATOR": "AMAZON",
            "MPF": "AMAZON",        # Marketplace Facilitator
            "PLATFORM": "AMAZON",
        })

        # Any value containing these keywords -> AMAZON
        platform_kw = r"(AMAZON|MARKETPLACE|FACILITATOR|MPF|PLATFORM)"
        is_platform = vc.astype(str).str.contains(platform_kw, na=False, regex=True)
        vc = vc.where(~is_platform, "AMAZON")

        # Empty -> SELLER
        vc = vc.replace({"NAN": None, "": None}).fillna("SELLER")

        df["vat_collector"] = vc
    else:
        df["vat_collector"] = "SELLER"

    # 4) Infer channel from sales_channel (AFN -> FBA, MFN -> FBM)
    if "sales_channel" in df.columns and "channel" not in df.columns:
        df["channel"] = df["sales_channel"].astype(str).str.upper().map({
            "AFN": "FBA",
            "MFN": "FBM",
        }).fillna("UNKNOWN")
    elif "channel" not in df.columns:
        df["channel"] = "UNKNOWN"

    # 5) Dates (explicit dayfirst=True to match dd-mm-YYYY formats)
    if "date" in df.columns:
        df["date"] = pd.to_datetime(df["date"], errors="coerce", dayfirst=True)

    # 6) Coerce rate to percentages
    if "rate" in df.columns:
        df["rate"] = _coerce_rate_col(df["rate"])

    # 7) Numeric amounts
    for col in [
        "net", "gross", "vat_amount",
        "vat_amount_items", "vat_amount_items_total",
        "vat_amount_shipping", "vat_amount_shipping_total",
        "vat_amount_giftwrap", "vat_amount_giftwrap_total",
    ]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    # 8) order_id fallback (try a few common IDs if not present)
    if "order_id" not in df.columns:
        for fallback in ["TRANSACTION_EVENT_ID", "ACTIVITY_TRANSACTION_ID", "ORDER_ID"]:
            if fallback in original_cols:
                df["order_id"] = df[fallback]
                break

    return df
