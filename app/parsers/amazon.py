import pandas as pd

BEST_EFFORT_MAP = {
    "order-id": "order_id",
    "order id": "order_id",
    "order_id": "order_id",
    "transaction type": "transaction_type",
    "transaction_type": "transaction_type",
    "transaction-event-date": "date",
    "posting-date": "date",
    "invoice-date": "date",
    "ship-to-country": "country",
    "marketplace-country": "country",
    "marketplace": "marketplace",
    "fulfillment-channel": "channel",
    "fulfilment-channel": "channel",
    "vat-collection-responsible": "vat_collector",
    "product-sales": "product_sales",
    "item-price": "product_sales",
    "tax-exclusive-amount": "net",
    "total-item-price": "gross",
    "vat-amount": "vat_amount",
    "item-tax": "vat_amount",
    "currency": "currency",
}

def normalize_columns(df: pd.DataFrame) -> pd.DataFrame:
    """把不同亚马逊报表列名，尽量映射到统一字段。"""
    df = df.copy()
    lower = {c.lower(): c for c in df.columns}
    mapping = {lower[k]: v for k, v in BEST_EFFORT_MAP.items() if k in lower}
    df = df.rename(columns=mapping)

    if "country" not in df.columns and "marketplace" in df.columns:
        df["country"] = df["marketplace"].astype(str).str[-2:].str.upper()

    if "channel" not in df.columns:
        df["channel"] = "UNKNOWN"
    if "vat_collector" not in df.columns:
        df["vat_collector"] = "SELLER"

    if "date" in df.columns:
        df["date"] = pd.to_datetime(df["date"], errors="coerce")
    return df
