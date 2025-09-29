from __future__ import annotations
import pandas as pd

def apply_country_rates(df: pd.DataFrame, rates: dict) -> pd.DataFrame:
    """按国家匹配标准税率，追加 'rate'(%) 列。"""
    df = df.copy()
    df["country"] = df.get("country", "").astype(str).str.upper()
    df["rate"] = df["country"].map({k.upper(): v for k, v in rates.items()}).fillna(0.0)
    return df

def derive_net_gross(df: pd.DataFrame) -> pd.DataFrame:
    """在有缺失时，根据已有字段反推 net/gross/vat_amount。"""
    df = df.copy()
    for col in ["net", "gross", "vat_amount", "rate"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    # 优先用已知税额反推
    if "gross" not in df.columns and "net" in df.columns and "vat_amount" in df.columns:
        df["gross"] = df["net"] + df["vat_amount"]
    if "net" not in df.columns and "gross" in df.columns and "vat_amount" in df.columns:
        df["net"] = df["gross"] - df["vat_amount"]

    # 若缺 vat_amount，用税率推导
    if "vat_amount" not in df.columns and "net" in df.columns and "rate" in df.columns:
        df["vat_amount"] = df["net"] * (df["rate"] / 100.0)
    if "vat_amount" not in df.columns and "gross" in df.columns and "rate" in df.columns:
        df["vat_amount"] = df["gross"] - (df["gross"] / (1.0 + df["rate"] / 100.0))
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

    # 订单数：优先用 order_id.nunique，否则用 size（不依赖具体列名）
    g = df.groupby("country", dropna=True)

    if "order_id" in df.columns:
        orders_df = g["order_id"].nunique().reset_index(name="orders")
    else:
        orders_df = g.size().reset_index(name="orders")

    # 净额 / VAT 汇总（如果缺 net，则用 0 占位；如果缺 vat_amount，先确保 derive_net_gross 已填充）
    if "net" in df.columns:
        net_agg = ("net", "sum")
    else:
        # 没有 net 时给个兜底列，避免 KeyError
        df["__net_fallback__"] = 0.0
        net_agg = ("__net_fallback__", "sum")

    if "vat_amount" not in df.columns:
        raise KeyError("Missing required column 'vat_amount'. "
                       "Ensure your report has VAT fields or that derive_net_gross() ran correctly.")

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


    # Amazon 代扣
    amazon = df[df["collector"].str.contains("AMAZON", na=False)].groupby("country")["vat_amount"].sum()
    grp = grp.merge(amazon.rename("amazon_collected"), on="country", how="left")

    grp["amazon_collected"] = grp["amazon_collected"].fillna(0.0)
    grp["vat_to_declare"] = grp["vat_due"] - grp["amazon_collected"]

    # 按需申报倒序
    grp = grp.sort_values("vat_to_declare", ascending=False, ignore_index=True)
    return grp
