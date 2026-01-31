import re
import pandas as pd
import streamlit as st

st.set_page_config(page_title="Hermi vs OCT Stock Tool", layout="wide")

st.title("📊 Hermi vs OCT Stock Comparison (Advanced Zero‑Error Check)")
st.write("Hermi real qty vs Odoo OCT qty ko MODEL level pe pivot + smart checks ke saath compare karo.")

ABS_TOL = 0.01
PCT_TOL_MINOR = 1.0
PCT_TOL_MEDIUM = 5.0

def clean_model(m: str) -> str:
    if pd.isna(m):
        return ""
    m = str(m).strip()
    m = m.replace(" ", "").upper()
    return m

col1, col2 = st.columns(2)
with col1:
    hermi_file = st.file_uploader("Hermi File (Real Quantity)", type=["xlsx", "xls"], key="hermi")
with col2:
    oct_file = st.file_uploader("Odoo OCT File (System Quantity)", type=["xlsx", "xls"], key="oct")

@st.cache_data
def parse_hermi_file(uploaded):
    df = pd.read_excel(uploaded, header=None)
    df = df.iloc[1:, :].reset_index(drop=True)

    sku_col_idx = 1
    color_col_idx = 9
    status_col_idx = 10
    qty_col_idx = 11

    if df.shape[1] <= qty_col_idx:
        raise ValueError("Hermi file ka structure change ho gaya, expected kam se kam 12 columns (NO..QTY).")

    raw_sku = df[sku_col_idx].astype(str).str.strip()
    df["MODEL_RAW_H"] = raw_sku.str.split("/").str[0].str.strip()
    df["MODEL"] = df["MODEL_RAW_H"].apply(clean_model)

    df["COLOR"] = df[color_col_idx].astype(str).fillna("").str.strip().str.upper()
    df["STATUS"] = df[status_col_idx].astype(str).fillna("").str.strip()
    df["HERMI_QTY"] = pd.to_numeric(df[qty_col_idx], errors="coerce").fillna(0)

    df = df[df["MODEL"] != ""].copy()

    grouped = (
        df.groupby("MODEL", as_index=False)
        .agg(
            {
                "MODEL_RAW_H": "first",
                "COLOR": lambda x: ", ".join(sorted(set([c for c in x if c]))),
                "STATUS": "first",
                "HERMI_QTY": "sum",
            }
        )
    )
    grouped["KEY"] = grouped["MODEL"]
    return grouped

@st.cache_data
def parse_oct_file(uploaded):
    df = pd.read_excel(uploaded, header=0)

    cols = {str(c).lower().strip(): c for c in df.columns}
    name_col = cols.get("display name") or list(df.columns)[0]
    qty_col = cols.get("quantity on hand") or list(df.columns)[1]

    df[name_col] = df[name_col].astype(str).str.strip()
    df["QTY_RAW"] = pd.to_numeric(df[qty_col], errors="coerce").fillna(0)

    def extract_model(s):
        m = re.search(r"\[([^\]]+)\]", s)
        if not m:
            txt = str(s).strip()
            if txt and "[" not in txt and "]" not in txt and "/" not in txt and " " not in txt:
                return txt
            return None
        inside = m.group(1)
        base = inside.split("/")[0]
        return base.strip()

    df["MODEL_RAW_O"] = df[name_col].apply(extract_model)
    df = df.dropna(subset=["MODEL_RAW_O"]).copy()
    df["MODEL"] = df["MODEL_RAW_O"].apply(clean_model)

    grouped = (
        df.groupby("MODEL", as_index=False)["QTY_RAW"].sum()
        .rename(columns={"QTY_RAW": "OCT_QTY"})
    )
    raw_example = df.groupby("MODEL", as_index=False)["MODEL_RAW_O"].first()
    grouped = grouped.merge(raw_example, on="MODEL", how="left")

    grouped["KEY"] = grouped["MODEL"]
    return grouped

if hermi_file and oct_file:
    try:
        hermi_df = parse_hermi_file(hermi_file)
        oct_df = parse_oct_file(oct_file)

        merged = hermi_df.merge(oct_df, on="KEY", how="outer", suffixes=("", "_OCT"))

        merged["MODEL"] = merged["MODEL"].fillna(merged["MODEL"])
        merged["MODEL_RAW_H"] = merged["MODEL_RAW_H"].fillna("")
        merged["MODEL_RAW_O"] = merged["MODEL_RAW_O"].fillna("")

        merged["COLOR"] = merged["COLOR"].fillna("")
        merged["STATUS"] = merged["STATUS"].fillna("")

        merged["HERMI_QTY"] = merged["HERMI_QTY"].fillna(0)
        merged["OCT_QTY"] = merged["OCT_QTY"].fillna(0)

        merged["HERMI_QTY_R"] = merged["HERMI_QTY"].round(2)
        merged["OCT_QTY_R"] = merged["OCT_QTY"].round(2)

        merged["ABS_DIFF"] = (merged["OCT_QTY_R"] - merged["HERMI_QTY_R"]).round(2)

        def pct_diff(row):
            h = row["HERMI_QTY_R"]
            o = row["OCT_QTY_R"]
            if h == 0 and o == 0:
                return 0.0
            if h == 0 and o != 0:
                return 999.9
            return ((o - h) / h) * 100.0

        merged["PCT_DIFF"] = merged.apply(pct_diff, axis=1).round(1)

        def logical_match(row):
            if abs(row["HERMI_QTY_R"]) <= ABS_TOL and abs(row["OCT_QTY_R"]) <= ABS_TOL:
                return True
            if abs(row["ABS_DIFF"]) <= ABS_TOL:
                return True
            if abs(row["PCT_DIFF"]) <= PCT_TOL_MINOR:
                return True
            return False

        merged["LOGICAL_MATCH"] = merged.apply(logical_match, axis=1)

        merged["ONLY_IN_HERMI"] = (merged["HERMI_QTY_R"] > ABS_TOL) & (merged["OCT_QTY_R"] <= ABS_TOL)
        merged["ONLY_IN_OCT"] = (merged["OCT_QTY_R"] > ABS_TOL) & (merged["HERMI_QTY_R"] <= ABS_TOL)

        def severity(row):
            if row["ONLY_IN_HERMI"]:
                return "Only in Hermi"
            if row["ONLY_IN_OCT"]:
                return "Only in OCT"
            if row["LOGICAL_MATCH"]:
                return "Perfect/Minor"
            if abs(row["PCT_DIFF"]) <= PCT_TOL_MEDIUM:
                return "Medium"
            return "Major"

        merged["SEVERITY"] = merged.apply(severity, axis=1)

        def risk_score(row):
            if row["LOGICAL_MATCH"]:
                return 0
            score = min(100, abs(row["PCT_DIFF"]))
            if row["ONLY_IN_HERMI"] or row["ONLY_IN_OCT"]:
                score = max(score, 80)
            if abs(row["ABS_DIFF"]) >= 50:
                score = max(score, 90)
            return round(score, 1)

        merged["RISK_SCORE"] = merged.apply(risk_score, axis=1)

        merged["IS_PUBLISHED"] = merged["STATUS"].str.upper().str.contains("PUBLISHED")

        def suspicious(row):
            if row["RISK_SCORE"] >= 90:
                return True
            if row["ONLY_IN_OCT"] or row["ONLY_IN_HERMI"]:
                return True
            return False

        merged["SUSPICIOUS"] = merged.apply(suspicious, axis=1)

        total_models = len(merged)
        zero_error = int(merged["LOGICAL_MATCH"].sum())
        suspicious_cnt = int(merged["SUSPICIOUS"].sum())
        avg_risk = merged["RISK_SCORE"].mean().round(1) if total_models else 0.0

        st.subheader("📈 Advanced Summary")
        k1, k2, k3, k4 = st.columns(4)
        k1.metric("Total Models", total_models)
        k2.metric("Zero‑Error / Acceptable", zero_error)
        k3.metric("Suspicious Models", suspicious_cnt)
        k4.metric("Avg Risk Score", avg_risk)

        st.subheader("🔎 Smart Filters")
        f1, f2, f3, f4, f5 = st.columns([1, 1, 1, 1, 2])
        with f1:
            err_filter = st.selectbox("Error Level", ["All", "Zero/OK", "Medium", "Major"])
        with f2:
            side_filter = st.selectbox("Side", ["All", "Only in Hermi", "Only in OCT"])
        with f3:
            susp_filter = st.selectbox("Suspicious", ["All", "Only Suspicious"])
        with f4:
            pub_filter = st.selectbox("Publish", ["All", "Published", "Not Published"])
        with f5:
            search_text = st.text_input("Search MODEL / Raw / Color")

        df_view = merged.copy()

        if err_filter == "Zero/OK":
            df_view = df_view[df_view["LOGICAL_MATCH"]]
        elif err_filter == "Medium":
            df_view = df_view[df_view["SEVERITY"] == "Medium"]
        elif err_filter == "Major":
            df_view = df_view[df_view["SEVERITY"] == "Major"]

        if side_filter == "Only in Hermi":
            df_view = df_view[df_view["ONLY_IN_HERMI"]]
        elif side_filter == "Only in OCT":
            df_view = df_view[df_view["ONLY_IN_OCT"]]

        if susp_filter == "Only Suspicious":
            df_view = df_view[df_view["SUSPICIOUS"]]

        if pub_filter == "Published":
            df_view = df_view[df_view["IS_PUBLISHED"]]
        elif pub_filter == "Not Published":
            df_view = df_view[~df_view["IS_PUBLISHED"]]

        if search_text:
            s = search_text.lower()
            df_view = df_view[
                df_view["MODEL_RAW_H"].astype(str).str.lower().str.contains(s)
                | df_view["MODEL_RAW_O"].astype(str).str.lower().str.contains(s)
                | df_view["MODEL"].astype(str).str.lower().str.contains(s)
                | df_view["COLOR"].astype(str).str.lower().str.contains(s)
            ]

        df_view = df_view[
            [
                "MODEL_RAW_H",
                "MODEL_RAW_O",
                "MODEL",
                "COLOR",
                "STATUS",
                "HERMI_QTY_R",
                "OCT_QTY_R",
                "ABS_DIFF",
                "PCT_DIFF",
                "SEVERITY",
                "RISK_SCORE",
                "ONLY_IN_HERMI",
                "ONLY_IN_OCT",
                "SUSPICIOUS",
            ]
        ].rename(
            columns={
                "MODEL_RAW_H": "Hermi Model",
                "MODEL_RAW_O": "Odoo Model",
                "MODEL": "Clean Model",
                "HERMI_QTY_R": "Hermi Qty",
                "OCT_QTY_R": "OCT Qty",
                "ABS_DIFF": "Abs Diff",
                "PCT_DIFF": "% Diff",
                "SEVERITY": "Severity",
                "RISK_SCORE": "Risk Score",
                "ONLY_IN_HERMI": "Only in Hermi",
                "ONLY_IN_OCT": "Only in OCT",
                "SUSPICIOUS": "Suspicious",
            }
        )

        st.subheader("📋 Zero‑Error Detector (MODEL Pivot)")

        def highlight_row(row):
            if row["Suspicious"]:
                return ["background-color: #f8d7da"] * len(row)
            if row["Only in Hermi"]:
                return ["background-color: #fff3cd"] * len(row)
            if row["Only in OCT"]:
                return ["background-color: #cce5ff"] * len(row)
            if row["Severity"] == "Perfect/Minor":
                return ["background-color: #d4edda"] * len(row)
            if row["Severity"] == "Medium":
                return ["background-color: #ffe8a1"] * len(row)
            return [""] * len(row)

        st.dataframe(df_view.style.apply(highlight_row, axis=1), use_container_width=True)

    except Exception as e:
        st.error(f"Error: {e}")
else:
    st.info("Dono files upload karo: Hermi + Odoo OCT.")
