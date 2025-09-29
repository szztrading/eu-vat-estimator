from __future__ import annotations
import pandas as pd

def apply_country_rates(df: pd.DataFrame, rates: dict) -> pd.DataFrame:
    """按国家匹配标准税率，追加 'rate'(%) 列（若已有 rate 列则只在缺失处补齐）。"""
    df = df.copy()
    df["country"] = df.get("country", "").astype(str).str.upper()

    rates_map = {k.upper(): v for k, v in rates.items()}
    # 仅在 rate 为空时，用国家标准税率兜底
    if "rate" not in df.columns:
        df["rate"] = df["country"].map(rates_map)
    else:
        df["rate"] = pd.to_numeric(df["rate"], errors="coerce")
        df["rate"] = df["rate"].fillna(df["country"].map(rates_map))

    return df

def derive_net_gross(df: pd.DataFrame) -> pd.DataFrame:
    """
    尽最大努力推导净额/含税额/税额：
    - 若有 net + vat_amount → gross = net + vat_amount
    - 若有 gross + vat_amount → net = gross - vat_amount
    - 若缺 vat_amount 且有 net + rate → vat_amount = net * rate%
    - 若缺 vat_amount 且有 gross + rate → vat_amount = gross - gross/(1+rate%)
    - 若没有 net 且有 gross + rate → 反推 net = gross - vat_amount
    """
    df = df.copy()

    # 数值化
    for col in ["net", "gross", "vat_amount", "rate"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    # 1) 先用已知税额推导
    if "gross" not in df.columns and {"net", "vat_amount"}.issubset(df.columns):
        df["gross"] = df["net"] + df["vat_amount"]

    if "net" not in df.columns and {"gross", "vat_amount"}.issubset(df.columns):
        df["net"] = df["gross"] - df["vat_amount"]

    # 2) 税率可用则推导税额
    if "vat_amount" not in df.columns and "rate" in df.columns:
        # 优先用 net + rate
        if "net" in df.columns:
            df["vat_amount"] = df["net"] * (df["rate"] / 100.0)
        elif "gross" in df.columns:
            df["vat_amount"] = df["gross"] - (df["gross"] / (1.0 + df["rate"] / 100.0))

    # 3) 若此时仍缺 net，但有 gross 与（刚推导的）vat_amount
    if "net" not in df.columns and {"gross", "vat_amount"}.issubset(df.columns):
        df["net"] = df["gross"] - df["vat_amount"]

    return df

def country_summary(df: pd.DataFrame) -> pd.DataFrame:
    """按国家聚合：订单数、净额、应纳VAT、Amazon代扣、需申报VAT。"""
    df = df.copy()

    # —— 基本校验 —— #
    if "country" not in df.columns:
        raise KeyError("Missing required column 'country' after normalization. "
                       "Check your report and the BEST_EFFORT_MAP in parsers/amazon.py")

    # 统一 collector 字段
    if "collector" not in df.columns and "vat_collector" in df.columns:
        df["collector"] = df["vat_collector"]
    df["collector"] = df.get("collector", "").astype(str).str.upper().str.strip()

    # groupby
    g = df.groupby("country", dropna=True)

    # 订单数
    if "order_id" in df.columns:
        orders_df = g["order_id"].nunique().reset_index(name="orders")
    else:
        orders_df = g.size().reset_index(name="orders")

    # 净额/税额的兜底
    if "net" in df.columns:
        net_agg = ("net", "sum")
    else:
        df["__net_fallback__"] = 0.0
        net_agg = ("__net_fallback__", "sum")

    if "vat_amount" not in df.columns:
        # 此时仍没有 vat_amount，说明无法从报表/税率推导
        raise KeyError("Missing required column 'vat_amount'. Ensure your report has VAT fields "
                       "or that derive_net_gross() ran correctly and a 'rate' is available.")

    base = g.agg(
        net=net_agg,
        vat_due=("vat_amount", "sum"),
    ).reset_index()

    # Amazon 代扣
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

    # 整理列顺序
    cols = ["country", "orders", "net", "vat_due", "amazon_collected", "vat_to_declare"]
    out = out[cols]
    out = out.sort_values("vat_to_declare", ascending=False, ignore_index=True)
    return out
