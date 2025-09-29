# ====== 顶部：路径注入，确保导入模块正常 ======
import sys, os
HERE = os.path.dirname(__file__)
ROOT = os.path.dirname(HERE)
if HERE not in sys.path:
    sys.path.insert(0, HERE)
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)
# ============================================

import streamlit as st
import pandas as pd
import yaml
from datetime import datetime

# 导入计算函数和解析函数（本地导入）
from vat_calculator import apply_country_rates, derive_net_gross, country_summary
from parsers.amazon import normalize_columns

# Streamlit 页面配置
st.set_page_config(page_title="EU VAT Estimator", layout="wide")
st.title("🇪🇺 EU VAT Estimator (Amazon FBA/FBM)")
st.caption("v0.2 • 自动识别 Amazon 已代缴 VAT • 上传 CSV/XLSX 报表自动计算 EU VAT")

# 读取配置文件
@st.cache_data
def load_config():
    with open("config.yaml", "r", encoding="utf-8") as f:
        return yaml.safe_load(f)

config = load_config()
rates = {k: v.get("standard_rate", 0) for k, v in config.get("countries", {}).items()}
hide_uk = config.get("ui", {}).get("hide_uk", True)

# 上传报表 + 选择时间范围
c1, c2 = st.columns([2, 1])
with c1:
    uploaded = st.file_uploader("📤 上传 Amazon 报表 (CSV 或 XLSX)", type=["csv", "xlsx"])
with c2:
    period = st.date_input(
        "📅 选择时间范围",
        value=(datetime(datetime.now().year, 1, 1).date(), datetime.now().date())
    )

# 主逻辑
if uploaded:
    # ① 读取文件
    df = pd.read_csv(uploaded) if uploaded.name.lower().endswith(".csv") else pd.read_excel(uploaded)
    st.subheader("📊 原始数据预览")
    st.dataframe(df.head(50), use_container_width=True)

    # ② 标准化列名 + 税率匹配 + 金额推导
    df = normalize_columns(df)
    df = apply_country_rates(df, rates)
    df = derive_net_gross(df)

    # ③ 按配置隐藏 UK
    if hide_uk and "country" in df.columns:
        df = df[df["country"] != "UK"]

    # ④ 按日期过滤
    if "date" in df.columns and isinstance(period, tuple) and len(period) == 2:
        start, end = pd.to_datetime(period[0]), pd.to_datetime(period[1]) + pd.Timedelta(days=1)
        df = df[(df["date"] >= start) & (df["date"] < end)]

    # ⑤ 聚合汇总（带容错）
    st.subheader("📈 各国 VAT 汇总")
    try:
        summary = country_summary(df)
    except KeyError as e:
        st.error(f"❌ 数据缺少关键字段：{e}")
        st.info("请检查：是否存在 'country'、'vat_amount' 字段（或能推导出），以及是否已正确解析报表。")
        st.write("👇 标准化处理后的数据（前 50 行）：")
        st.dataframe(df.head(50), use_container_width=True)
        st.stop()

    # ⑥ 显示汇总结果
    st.dataframe(summary, use_container_width=True)

    # ⑦ 下载按钮
    csv_data = summary.to_csv(index=False).encode("utf-8")
    st.download_button(
        "⬇️ 下载 VAT 汇总 (CSV)",
        csv_data,
        file_name="vat_summary.csv",
        mime="text/csv"
    )

    # ⑧ 可选：查看标准化后数据
    with st.expander("📄 查看标准化数据（前 200 行）"):
        st.dataframe(df.head(200), use_container_width=True)

else:
    st.info("📥 请先上传 Amazon 报表文件 (CSV 或 XLSX) 开始计算。")
