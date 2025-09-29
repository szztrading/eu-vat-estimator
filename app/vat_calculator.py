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

    # 统一 collector 字段
    if "collector" not in df.columns and "vat_collector" in df.columns:
        df["collector"] = df["vat_collector"]
    df["collector"] = df.get("collector", "").astype(str).str.upper().str.strip()

    # 订单计数字段
    orders = ("order_id", "nunique") if "order_id" in df.columns else ("country", "count")

    grp = df.groupby("country").agg(
        orders=orders,
        net=("net", "sum"),
        vat_due=("vat_amount", "sum"),
    ).reset_index()

    # Amazon 代扣
    amazon = df[df["collector"].str.contains("AMAZON", na=False)].groupby("country")["vat_amount"].sum()
    grp = grp.merge(amazon.rename("amazon_collected"), on="country", how="left")

    grp["amazon_collected"] = grp["amazon_collected"].fillna(0.0)
    grp["vat_to_declare"] = grp["vat_due"] - grp["amazon_collected"]

    # 按需申报倒序
    grp = grp.sort_values("vat_to_declare", ascending=False, ignore_index=True)
    return grp
