# app/vat_calculator.py
# -*- coding: utf-8 -*-
from __future__ import annotations
import pandas as pd

def _dedupe_country(df: pd.DataFrame) -> pd.DataFrame:
    """If multiple 'country' columns accidentally exist, collapse into a single column."""
    cols = [c for c in df.columns if c == "country"]
    if len(cols) <= 1:
        return df
    cdf = df[cols]
    # take first non-null horizontally
    country = cdf.bfill(axis=1).iloc[:, 0]
    df = df.drop(columns=cols)
    df["country"] = country
    return df

def apply_country_rates(df: pd.DataFrame, rates: dict) -> pd.DataFrame:
    """Map standard VAT rate by 2-letter country code, add/complete column 'rate' (percent)."""
    df = df.copy()
    df = _dedupe_country(df)

    if "country" not in df.columns:
        df["country"] = "UNKNOWN"

    df["country"] = df["country"].astype(str).str.upper()
    rates_map = {k.upper(): v for k, v in rates.items()}

    if "rate" not in df.columns:
        df["rate"] = df["country"].map(rates_map)
    else:
        df["rate"] = pd.to_numeric(df["rate"], errors="coerce")
        df["rate"] = df["rate"].fillna(df["country"].map(rates_map))

    return df

def derive_net_gross(df: pd.DataFrame) -> pd.DataFrame:
    """
    Infer net/gross/vat_amount wherever possible:
    - If net + vat_amount => gross = net + vat_amount
    - If gross + vat_amount => net = gross - vat_amount
    - If missing vat_amount and net + rate => vat_amount = net * rate%
    - If missing vat_amount and gross + rate => vat_amount = gross - gross/(1+rate%)
    - If missing net but have gross + vat_amount => net = gross - vat_amount
    """
    df = df.copy()
    for col in ["net", "gross", "vat_amount", "rate"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    # Use existing vat_amount to compute others
    if "gross" not in df.columns and {"net", "vat_amount"}.issubset(df.columns):
        df["gross"] = df["net"] + df["vat_amount"]

    if "net" not in df.columns and {"gross", "vat_amount"}.issubset(df.columns):
        df["net"] = df["gross"] - df["vat_amount"]

    # Fill vat_amount from rate if needed
    if "vat_amount" not in df.columns and "rate" in df.columns:
        if "net" in df.columns:
            df["vat_amount"] = df["net"] * (df["rate"] / 100.0)
        elif "gross" in df.columns:
            df["vat_amount"] = df["gross"] - (df["gross"] / (1.0 + df["rate"] / 100.0))

    # Backfill net from gross and (new) vat_amount
    if "net" not in df.columns and {"gross", "vat_amount"}.issubset(df.columns):
        df["net"] = df["gross"] - df["vat_amount"]

    return df

def country_summary(df: pd.DataFrame) -> pd.DataFrame:
    """Aggregate by country: orders, net, vat_due, amazon_collected, vat_to_declare."""
    df = df.copy()
    df = _dedupe_country(df)

    if "country" not in df.columns:
        raise KeyError("Missing required column 'country'. Please check normalization mapping.")

    # normalize collector field
    if "collector" not in df.columns and "vat_collector" in df.columns:
        df["collector"] = df["vat_collector"]
    df["collector"] = df.get("collector", "").astype(str).str.upper().str.strip()

    g = df.groupby("country", dropna=True)

    # orders count
    if "order_id" in df.columns:
        orders_df = g["order_id"].nunique().reset_index(name="orders")
    else:
        orders_df = g.size().reset_index(name="orders")

    # net fallback
    if "net" in df.columns:
        net_agg = ("net", "sum")
    else:
        df["__net_fallback__"] = 0.0
        net_agg = ("__net_fallback__", "sum")

    if "vat_amount" not in df.columns:
        raise KeyError("Missing required column 'vat_amount'. Ensure normalization mapped correctly or derive_net_gross() worked.")

    base = g.agg(
        net=net_agg,
        vat_due=("vat_amount", "sum"),
    ).reset_index()

    # Platform-collected VAT (broad matching to catch various wordings)
    platform_kw = r"(AMAZON|MARKETPLACE|FACILITATOR|MPF|PLATFORM)"
    collector_upper = df["collector"].astype(str).str.upper().str.strip()
    platform_mask = collector_upper.str.contains(platform_kw, na=False, regex=True)

    amazon = (
        df[platform_mask]
        .groupby("country")["vat_amount"]
        .sum()
        .rename("amazon_collected")
        .reset_index()
    )

    out = base.merge(orders_df, on="country", how="left")
    out = out.merge(amazon, on="country", how="left")
    out["amazon_collected"] = out["amazon_collected"].fillna(0.0)
    out["vat_to_declare"] = out["vat_due"] - out["amazon_collected"]

    cols = ["country", "orders", "net", "vat_due", "amazon_collected", "vat_to_declare"]
    out = out[cols]
    return out.sort_values("vat_to_declare", ascending=False, ignore_index=True)
