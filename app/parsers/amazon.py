import pandas as pd
import re

# 仅做“安全”的基础映射；国家(country)相关不在这里直接重命名，避免重复列
BASE_MAP = {
    # 标识/时间
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

    # 履约渠道
    "fulfillment-channel": "channel",
    "fulfilment-channel": "channel",

    # VAT 代扣方（统一为 vat_collector）
    "vat-collection-responsible": "vat_collector",
    "vat collection responsibility": "vat_collector",
    "tax_collection_responsibility": "vat_collector",

    # 金额（总额三件套）
    "total_activity_value_amt_vat_excl": "net",
    "total_activity_value_amt_vat_incl": "gross",
    "total_activity_value_vat_amt": "vat_amount",

    # 其它分项（保留为参考，不参与核心计算）
    "price_of_items_vat_amt": "vat_amount_items",
    "total_price_of_items_vat_amt": "vat_amount_items_total",
    "ship_charge_vat_amt": "vat_amount_shipping",
    "total_ship_charge_vat_amt": "vat_amount_shipping_total",
    "gift_wrap_vat_amt": "vat_amount_giftwrap",
    "total_gift_wrap_vat_amt": "vat_amount_giftwrap_total",

    # 税率
    "tax-rate": "rate",
    "tax rate": "rate",
    "vat rate": "rate",
    "vat-rate": "rate",
    "vat_rate": "rate",
    "price_of_items_vat_rate_percent": "rate",

    # 货币
    "currency": "currency",

    # 销售渠道（AFN=FBA, MFN=FBM）
    "sales_channel": "sales_channel"
}

# 国家来源列的优先级（出现就用，不出现就找下一个）
COUNTRY_PRIORITY = [
    "VAT_CALCULATION_IMPUTATION_COUNTRY",
    "ARRIVAL_COUNTRY",
    "SALE_ARRIVAL_COUNTRY",
    "SHIP_TO_COUNTRY",
    "MARKETPLACE_COUNTRY",
]

def _coerce_rate_col(series: pd.Series) -> pd.Series:
    """把税率统一为百分数：19 -> 19.0, 0.19 -> 19.0, '19%' -> 19.0"""
    s = series.astype(str).str.strip()
    pct = s.str.extract(r"([0-9]*\.?[0-9]+)\s*%?")[0]
    s_num = pd.to_numeric(pct, errors="coerce")
    s_num = s_num.where(~((s_num >= 0) & (s_num <= 1)), s_num * 100.0)
    return s_num

def _first_nonempty_rowwise(df_sub: pd.DataFrame) -> pd.Series:
    """按行取第一个非空/非空字符串的值。"""
    if df_sub.empty:
        return pd.Series([None] * len(df_sub), index=df_sub.index)
    s = df_sub.apply(
        lambda row: next((x for x in row if pd.notna(x) and str(x).strip() != ""), None),
        axis=1
    )
    return s

def normalize_columns(df: pd.DataFrame) -> pd.DataFrame:
    """标准化列名 + 生成唯一 country 列 + 补全必要字段"""
    df = df.copy()
    original_cols = list(df.columns)
    lower_map = {c.lower(): c for c in original_cols}

    # 1) 先做基础映射（不含 country 相关）
    mapping = {lower_map[k]: v for k, v in BASE_MAP.items() if k in lower_map}
    df = df.rename(columns=mapping)

    # 2) 生成唯一的 country 列（按优先级从原始列里抽取）
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
        # 兜底：尝试从 marketplace 推断（最后两位）
        if "marketplace" in df.columns:
            df["country"] = df["marketplace"].astype(str).str[-2:].str.upper()

    # 统一国家格式
    if "country" in df.columns:
        df["country"] = df["country"].astype(str).str.strip().str.upper()
        df["country"] = df["country"].replace({"NAN": None, "NONE": None, "": None})
        df["country"] = df["country"].fillna("UNKNOWN")
    else:
        df["country"] = "UNKNOWN"

    # 3) 补充/清洗其他字段
    # vat_collector 规范化为 AMAZON / SELLER
    if "vat_collector" in df.columns:
        vc = df["vat_collector"].astype(str).str.upper().str.strip()
        vc = vc.replace({"AMAZON EU S.A R.L.": "AMAZON", "AMAZON EU SARL": "AMAZON"})
        df["vat_collector"] = vc
    else:
        df["vat_collector"] = "SELLER"

    # 从 sales_channel 推断 channel（AFN=FBA, MFN=FBM）
    if "sales_channel" in df.columns and "channel" not in df.columns:
        df["channel"] = df["sales_channel"].astype(str).str.upper().map({
            "AFN": "FBA",  # Amazon Fulfillment Network
            "MFN": "FBM"
        }).fillna("UNKNOWN")
    elif "channel" not in df.columns:
        df["channel"] = "UNKNOWN"

    # 时间列
    if "date" in df.columns:
        df["date"] = pd.to_datetime(df["date"], errors="coerce")

    # 税率转为百分数
    if "rate" in df.columns:
        df["rate"] = _coerce_rate_col(df["rate"])

    # 金额列转数值
    for col in ["net", "gross", "vat_amount",
                "vat_amount_items", "vat_amount_items_total",
                "vat_amount_shipping", "vat_amount_shipping_total",
                "vat_amount_giftwrap", "vat_amount_giftwrap_total"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    # 订单号兜底
    if "order_id" not in df.columns:
        for fallback in ["TRANSACTION_EVENT_ID", "ACTIVITY_TRANSACTION_ID"]:
            if fallback in original_cols:
                df["order_id"] = df[fallback]
                break

    return df
