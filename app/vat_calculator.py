from __future__ import annotations
import pandas as pd

def apply_country_rates(df: pd.DataFrame, rates: dict) -> pd.DataFrame:
    """按国家匹配标准税率，追加 'rate'(%) 列（若已有 rate 列则只在缺失处补齐）"""
    df = df.copy()

    # ✅ 修复：如果没有 'country' 列，先创建一列 UNKNOWN，避免 .get 返回 str
    if "country" not in df.columns:
        df["country"] = "UNKNOWN"

    # 统一大写
    df["country"] = df["country"].astype(str).str.upper()

    # 匹配税率（优先用已有 rate，其次用国家映射）
    rates_map = {k.upper(): v for k, v in rates.items()}

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
    - 若没有 net 且有 gross + vat_amount → 反推 net
    """
    df = df.copy()

    # 转数值
    for col in ["net", "gross", "vat_amount", "rate"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    # 1️⃣ 税额推导
    if "gross" not in df.columns and {"net", "vat_amount"}.issubset(df.columns):
        df["gross"] = df["net"] + df["vat_amount"]

    if "net" not in df.columns and {"gross", "vat_amount"}.issubset(df.columns):
        df["net"] = df["gross"] - df["vat_amount"]

    # 2️⃣ 税率推导
    if "vat_amount" not in df.columns and "rate" in df.columns:
        if "net" in df.columns:
            df["vat_amount"] = df["net"] * (df["rate"] / 100.0)
        elif "gross" in df.columns:
            df["vat_amount"] = df["gross"] - (df["gross"] / (1.0 + df["rate"] / 100.0))

    # 3️⃣ 再反推净额
    if "net" not in df.columns and {"gross", "vat_amount"}.issubset(df.columns):
        df["net"] = df["gross"] - df["vat_amount"]

    return df


def country_summary(df: pd.DataFrame) -> pd.DataFrame:
    """按国家聚合：订单数、净额、应纳VAT、Amazon代扣、需申报VAT"""
    df = df.copy()

    # 校验
    if "country" not in df.columns:
        raise KeyError("Missing required column 'country'. Please check normalization mapping.")

    if "collector" not in df.columns and "vat_collector" in df.columns:
        df["collector"] = df["vat_collector"]
    df["collector"] = df.get("collector", "").astype(str).str.upper().str.strip()

    g = df.groupby("country", dropna=True)

    # 订单数
    if "order_id" in df.columns:
        orders_df = g["order_id"].nunique().reset_index(name="orders")
    else:
        orders_df = g.size().reset_index(name="orders")

    # 净额兜底
    if "net" in df.columns:
        net_agg = ("net", "sum")
    else:
        df["__net_fallback__"] = 0.0
        net_agg = ("__net_fallback__", "sum")

    # 检查 VAT 字段
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
