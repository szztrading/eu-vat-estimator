from __future__ import annotations
import pandas as pd

def _dedupe_country(df: pd.DataFrame) -> pd.DataFrame:
    """若意外产生多个名为 'country' 的列，按行取第一个非空，并收敛为单列。"""
    cols = [c for c in df.columns if c == "country"]
    if len(cols) <= 1:
        return df
    cdf = df[cols]
    # 逐行取第一个非空
    country = cdf.bfill(axis=1).iloc[:, 0]
    df = df.drop(columns=cols)
    df["country"] = country
    return df

def apply_country_rates(df: pd.DataFrame, rates: dict) -> pd.DataFrame:
    """按国家匹配标准税率，追加 'rate'(%) 列"""
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
    df = df.copy()
    for col in ["net", "gross", "vat_amount", "rate"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    if "gross" not in df.columns and {"net", "vat_amount"}.issubset(df.columns):
        df["gross"] = df["net"] + df["vat_amount"]

    if "net" not in df.columns and {"gross", "vat_amount"}.issubset(df.columns):
        df["net"] = df["gross"] - df["vat_amount"]

    if "vat_amount" not in df.columns and "rate" in df.columns:
        if "net" in df.columns:
            df["vat_amount"] = df["net"] * (df["rate"] / 100.0)
        elif "gross" in df.columns:
            df["vat_amount"] = df["gross"] - (df["gross"] / (1.0 + df["rate"] / 100.0))

    if "net" not in df.columns and {"gross", "vat_amount"}.issubset(df.columns):
        df["net"] = df["gross"] - df["vat_amount"]

    return df

def country_summary(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df = _dedupe_country(df)

    if "country" not in df.columns:
        raise KeyError("Missing required column 'country'. Please check normalization mapping.")

    if "collector" not in df.columns and "vat_collector" in df.columns:
        df["collector"] = df["vat_collector"]
    df["collector"] = df.get("collector", "").astype(str).str.upper().str.strip()

    g = df.groupby("country", dropna=True)

    if "order_id" in df.columns:
        orders_df = g["order_id"].nunique().reset_index(name="orders")
    else:
        orders_df = g.size().reset_index(name="orders")

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

    amazon_col = (
        df[df["collector"].str.contains("AMAZON", na=False)]
        .groupby("country")["vat_amount"]
        .sum()
        .rename("amazon_collected")
        .reset_index()
    )

    out = base.merge(orders_df, on="country", how="left")
    out = out.merge(amazon_col, on="country", how="left")
    out["amazon_collected"] = out["amazon_collected"].fillna(0.0)
    out["vat_to_declare"] = out["vat_due"] - out["amazon_collected"]

    cols = ["country", "orders", "net", "vat_due", "amazon_collected", "vat_to_declare"]
    out = out[cols]
    return out.sort_values("vat_to_declare", ascending=False, ignore_index=True)
