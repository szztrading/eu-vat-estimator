import pandas as pd
import re

# 尽可能覆盖亚马逊报表/市场常见列名
BEST_EFFORT_MAP = {
    # 订单/基础
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

    # 国家/站点
    "ship-to-country": "country",
    "ship_country": "country",
    "marketplace-country": "country",
    "marketplace": "marketplace",

    # 履约渠道
    "fulfillment-channel": "channel",
    "fulfilment-channel": "channel",

    # VAT 代扣方
    "vat-collection-responsible": "vat_collector",
    "vat collection responsibility": "vat_collector",

    # 金额（不含税/含税）
    "tax-exclusive-amount": "net",
    "tax-exclusive-price": "net",
    "item-price": "product_sales",       # 先作为产品价（不一定净额）
    "product-sales": "product_sales",
    "total-item-price": "gross",
    "total price": "gross",
    "total-price": "gross",
    "total-amount": "gross",
    "total charged": "gross",

    # 税额（各种写法映射为 vat_amount）
    "vat-amount": "vat_amount",
    "item-tax": "vat_amount",
    "product tax": "vat_amount",
    "total-tax": "vat_amount",
    "tax-amount": "vat_amount",
    "vat": "vat_amount",
    "tax": "vat_amount",

    # 税率（各种写法映射为 rate，百分比或小数都兼容）
    "tax-rate": "rate",
    "tax rate": "rate",
    "vat rate": "rate",
    "vat-rate": "rate",
    "vat_rate": "rate",

    # 货币
    "currency": "currency",
}

def _coerce_rate_col(series: pd.Series) -> pd.Series:
    """把税率列统一为百分数（例如 19 -> 19.0；0.19 -> 19.0；'19%' -> 19.0）。"""
    s = series.astype(str).str.strip()
    # 提取数字(含小数)和可选百分号
    pct = s.str.extract(r"([0-9]*\.?[0-9]+)\s*%?")[0]
    s_num = pd.to_numeric(pct, errors="coerce")
    # 判断是否像 0-1 之间的小数，如果是则乘以100转成百分比
    s_num = s_num.where(~((s_num >= 0) & (s_num <= 1)), s_num * 100.0)
    return s_num

def normalize_columns(df: pd.DataFrame) -> pd.DataFrame:
    """把不同亚马逊报表列名，尽量映射到统一字段，并做必要推导。"""
    df = df.copy()
    lower = {c.lower(): c for c in df.columns}
    mapping = {lower[k]: v for k, v in BEST_EFFORT_MAP.items() if k in lower}
    df = df.rename(columns=mapping)

    # 兜底：从 marketplace 推导国家，如 'Amazon.de' -> 'DE'（不总是可靠，但比空好）
    if "country" not in df.columns and "marketplace" in df.columns:
        df["country"] = df["marketplace"].astype(str).str[-2:].str.upper()

    # 默认值兜底
    if "channel" not in df.columns:
        df["channel"] = "UNKNOWN"
    if "vat_collector" not in df.columns:
        df["vat_collector"] = "SELLER"

    # 时间字段转时间
    if "date" in df.columns:
        df["date"] = pd.to_datetime(df["date"], errors="coerce")

    # 标准化税率列（如果存在）
    if "rate" in df.columns:
        df["rate"] = _coerce_rate_col(df["rate"])

    # 金额列尽量转数值
    for col in ["net", "gross", "vat_amount", "product_sales"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    return df
