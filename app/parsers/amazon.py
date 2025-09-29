import pandas as pd
import re

# 尽可能覆盖亚马逊常见列名（统一映射到标准字段）
BEST_EFFORT_MAP = {
    # ---- 标识/时间 ----
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
    "tax_calculation_date": "date",   # 本表常见时间列

    # ---- 国家/站点 ----
    "ship-to-country": "country",
    "ship_country": "country",
    "marketplace-country": "country",
    "marketplace": "marketplace",

    # 本表更准确的国家列（按优先级从高到低）
    "vat_calculation_imputation_country": "country",
    "arrival_country": "country",
    "sale_arrival_country": "country",

    # ---- 履约渠道 ----
    "fulfillment-channel": "channel",
    "fulfilment-channel": "channel",

    # ---- VAT 代扣方 ----
    "vat-collection-responsible": "vat_collector",
    "vat collection responsibility": "vat_collector",
    "tax_collection_responsibility": "vat_collector",   # 本表字段

    # ---- 金额（不含税/含税/税额）----
    # 你的报表里最重要的三列（直接能产出净额/含税额/税额）
    "total_activity_value_amt_vat_excl": "net",
    "total_activity_value_amt_vat_incl": "gross",
    "total_activity_value_vat_amt": "vat_amount",

    # 其它可能存在的分项（供将来扩展用，不影响当前逻辑）
    "price_of_items_vat_amt": "vat_amount_items",
    "total_price_of_items_vat_amt": "vat_amount_items_total",
    "ship_charge_vat_amt": "vat_amount_shipping",
    "total_ship_charge_vat_amt": "vat_amount_shipping_total",
    "gift_wrap_vat_amt": "vat_amount_giftwrap",
    "total_gift_wrap_vat_amt": "vat_amount_giftwrap_total",

    # 税率（统一映射为 rate，后面会做标准化：0.19→19.0）
    "tax-rate": "rate",
    "tax rate": "rate",
    "vat rate": "rate",
    "vat-rate": "rate",
    "vat_rate": "rate",
    "price_of_items_vat_rate_percent": "rate",

    # 货币
    "currency": "currency",
}

def _coerce_rate_col(series: pd.Series) -> pd.Series:
    """把税率列统一为百分数：19→19.0，0.19→19.0，'19%'→19.0。"""
    s = series.astype(str).str.strip()
    pct = s.str.extract(r"([0-9]*\.?[0-9]+)\s*%?")[0]
    s_num = pd.to_numeric(pct, errors="coerce")
    s_num = s_num.where(~((s_num >= 0) & (s_num <= 1)), s_num * 100.0)
    return s_num

def normalize_columns(df: pd.DataFrame) -> pd.DataFrame:
    """尽最大努力把不同报表列名映射到统一字段，并做必要推导。"""
    df = df.copy()
    lower = {c.lower(): c for c in df.columns}
    mapping = {lower[k]: v for k, v in BEST_EFFORT_MAP.items() if k in lower}
    df = df.rename(columns=mapping)

    # 如果 country 仍不存在，最后再尝试从 marketplace 推导（末两位）
    if "country" not in df.columns and "marketplace" in df.columns:
        df["country"] = df["marketplace"].astype(str).str[-2:].str.upper()

    # 默认值兜底
    if "channel" not in df.columns:
        df["channel"] = "UNKNOWN"
    if "vat_collector" not in df.columns:
        df["vat_collector"] = "SELLER"

    # 时间字段
    if "date" in df.columns:
        df["date"] = pd.to_datetime(df["date"], errors="coerce")

    # 税率标准化
    if "rate" in df.columns:
        df["rate"] = _coerce_rate_col(df["rate"])

    # 金额列尽量转数值
    for col in ["net", "gross", "vat_amount", "vat_amount_items",
                "vat_amount_items_total", "vat_amount_shipping", "vat_amount_shipping_total",
                "vat_amount_giftwrap", "vat_amount_giftwrap_total"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    return df
