import re
import pandas as pd
import streamlit as st

st.set_page_config(page_title="Hermi vs OCT Stock Tool", layout="wide")

st.title("📊 Hermi vs OCT Stock Comparison (MODEL Pivot)")
st.write("Hermi real qty vs Odoo OCT qty ko MODEL level pe pivot karke compare karo (sizes/colors auto‑sum).")

# ---------------- FILE UPLOAD ---------------- #

col1, col2 = st.columns(2)
with col1:
    hermi_file = st.file_uploader("Hermi File (Real Quantity)", type=["xlsx", "xls"], key="hermi")
with col2:
    oct_file = st.file_uploader("Odoo OCT File (System Quantity)", type=["xlsx", "xls"], key="oct")


# ---------------- PARSE FUNCTIONS ---------------- #

@st.cache_data
def parse_hermi_file(uploaded):
    df = pd.read_excel(uploaded, header=None)  # raw
    df = df.iloc[1:, :].reset_index(drop=True)  # skip first header row

    # Index mapping (0‑based): 1=MODEL/SKU, 9=COLOR, 10=STATUS, 11=QTY
    sku_col_idx = 1
    color_col_idx = 9
    status_col_idx = 10
    qty_col_idx = 11

    if df.shape[1] <= qty_col_idx:
        raise ValueError("Hermi file ka structure change ho gaya, expected kam se kam 12 columns (NO..QTY).")

    raw_sku = df[sku_col_idx].astype(str).str.strip()
    df["MODEL"] = raw_sku.str.split("/").str[0].str.strip()
    df["COLOR"] = df[color_col_idx].astype(str).fillna("").str.strip().str.upper()
    df["STATUS"] = df[status_col_idx].astype(str).fillna("").str.strip()
    df["HERMI_QTY"] = pd.to_numeric(df[qty_col_idx], errors="coerce").fillna(0)

    df = df[df["MODEL"] != ""].copy()

    grouped = (
        df.groupby("MODEL", as_index=False)
        .agg(
            {
                "COLOR": lambda x: ", ".join(sorted(set([c for c in x if c]))),  # all colors list
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

    # Pivot: MODEL extract from [MODEL/size] or [MODEL] format
    def extract_model(s):
        m = re.search(r"\[([^\]]+)\]", s)
        if not m:
            # kuch rows plain model name ke saath hote hain, jaise "DM836"
            txt = str(s).strip()
            if txt and "[" not in txt and "]" not in txt and "/" not in txt and " " not in txt:
                return txt
            return None
        inside = m.group(1)
        model = inside.split("/")[0]
        return model.strip()

    df["MODEL"] = df[name_col].apply(extract_model)
    df = df.dropna(subset=["MODEL"]).copy()

    grouped = (
        df.groupby("MODEL", as_index=False)["QTY_RAW"].sum()
        .rename(columns={"QTY_RAW": "OCT_QTY"})
    )
    grouped["KEY"] = grouped["MODEL"]
    return grouped


# ---------------- MAIN LOGIC ---------------- #

if hermi_file and oct_file:
    try:
        hermi_df = parse_hermi_file(hermi_file)
        oct_df = parse_oct_file(oct_file)

        merged = hermi_df.merge(oct_df, on="KEY", how="outer", suffixes=("_H", "_O"))

        merged["MODEL"] = merged["MODEL_H"].fillna(merged["MODEL_O"])
        merged["COLOR"] = merged["COLOR"].fillna("")
        merged["STATUS"] = merged["STATUS"].fillna("")

        merged["HERMI_QTY"] = merged["HERMI_QTY"].fillna(0)
        merged["OCT_QTY"] = merged["OCT_QTY"].fillna(0)

        merged["HERMI_QTY_R"] = merged["HERMI_QTY"].round(2)
        merged["OCT_QTY_R"] = merged["OCT_QTY"].round(2)

        merged["DIFF"] = merged["OCT_QTY_R"] - merged["HERMI_QTY_R"]

        # % difference (relative to Hermi)
        merged["PCT_DIFF"] = merged.apply(
            lambda r: 0 if r["HERMI_QTY_R"] == 0 else (r["DIFF"] / r["HERMI_QTY_R"]) * 100, axis=1
        ).round(1)

        # Advanced flags
        merged["MATCH"] = merged["DIFF"] == 0
        merged["ONLY_IN_HERMI"] = (merged["HERMI_QTY_R"] != 0) & (merged["OCT_QTY_R"] == 0)
        merged["ONLY_IN_OCT"] = (merged["OCT_QTY_R"] != 0) & (merged["HERMI_QTY_R"] == 0)

        def severity(row):
            if row["ONLY_IN_HERMI"]:
                return "Only in Hermi"
            if row["ONLY_IN_OCT"]:
                return "Only in OCT"
            if row["MATCH"]:
                return "Perfect"
            if abs(row["PCT_DIFF"]) <= 5:
                return "Minor"
            if abs(row["PCT_DIFF"]) <= 20:
                return "Medium"
            return "Major"

        merged["SEVERITY"] = merged.apply(severity, axis=1)

        merged["IS_PUBLISHED"] = merged["STATUS"].str.upper().str.contains("PUBLISHED")

        # -------- KPIs -------- #
        total_models = len(merged)
        matched = int(merged["MATCH"].sum())
        major_mismatch = int((merged["SEVERITY"] == "Major").sum())
        only_hermi_count = int(merged["ONLY_IN_HERMI"].sum())
        only_oct_count = int(merged["ONLY_IN_OCT"].sum())
        published = int(merged["IS_PUBLISHED"].sum())

        st.subheader("📈 Summary (MODEL Pivot)")
        k1, k2, k3, k4, k5 = st.columns(5)
        k1.metric("Total Models", total_models)
        k2.metric("Perfect Match", matched)
        k3.metric("Major Mismatch", major_mismatch)
        k4.metric("Only in Hermi", only_hermi_count)
        k5.metric("Only in OCT", only_oct_count)

        # -------- Filters -------- #
        st.subheader("🔎 Filter & Search")
        f1, f2, f3, f4 = st.columns([1, 1, 1, 2])
        with f1:
            match_filter = st.selectbox("Match Filter", ["All", "Perfect", "Minor", "Medium", "Major"])
        with f2:
            side_filter = st.selectbox("Side Filter", ["All", "Only in Hermi", "Only in OCT"])
        with f3:
            pub_filter = st.selectbox("Publish", ["All", "Published", "Not Published"])
        with f4:
            search_text = st.text_input("Search MODEL / Color")

        df_view = merged.copy()

        if match_filter != "All":
            if match_filter == "Perfect":
                df_view = df_view[df_view["SEVERITY"] == "Perfect"]
            else:
                df_view = df_view[df_view["SEVERITY"] == match_filter]

        if side_filter == "Only in Hermi":
            df_view = df_view[df_view["ONLY_IN_HERMI"]]
        elif side_filter == "Only in OCT":
            df_view = df_view[df_view["ONLY_IN_OCT"]]

        if pub_filter == "Published":
            df_view = df_view[df_view["IS_PUBLISHED"]]
        elif pub_filter == "Not Published":
            df_view = df_view[~df_view["IS_PUBLISHED"]]

        if search_text:
            s = search_text.lower()
            df_view = df_view[
                df_view["MODEL"].astype(str).str.lower().str.contains(s)
                | df_view["COLOR"].astype(str).str.lower().str.contains(s)
            ]

        df_view = df_view[
            [
                "MODEL",
                "COLOR",
                "STATUS",
                "HERMI_QTY_R",
                "OCT_QTY_R",
                "DIFF",
                "PCT_DIFF",
                "SEVERITY",
                "ONLY_IN_HERMI",
                "ONLY_IN_OCT",
            ]
        ].rename(
            columns={
                "HERMI_QTY_R": "Hermi Qty",
                "OCT_QTY_R": "OCT Qty",
                "DIFF": "Diff",
                "PCT_DIFF": "% Diff",
                "SEVERITY": "Severity",
                "ONLY_IN_HERMI": "Only in Hermi",
                "ONLY_IN_OCT": "Only in OCT",
            }
        )

        st.subheader("📋 Advanced MODEL Level Pivot View")

        def highlight_row(row):
            if row["Only in Hermi"]:
                color = "#fff3cd"   # yellow
            elif row["Only in OCT"]:
                color = "#cce5ff"   # blue
            else:
                if row["Severity"] == "Perfect":
                    color = "#d4edda"
                elif row["Severity"] == "Minor":
                    color = "#e2f0cb"
                elif row["Severity"] == "Medium":
                    color = "#ffe8a1"
                else:
                    color = "#f8d7da"
            return [f"background-color: {color}"] * len(row)

        st.dataframe(df_view.style.apply(highlight_row, axis=1), use_container_width=True)

        # -------- Download Excel -------- #
        from io import BytesIO

        def to_excel_bytes(df):
            output = BytesIO()
            with pd.ExcelWriter(output, engine="xlsxwriter") as writer:
                df.to_excel(writer, index=False, sheet_name="Model Pivot")
            return output.getvalue()

        excel_bytes = to_excel_bytes(df_view)
        st.download_button(
            "⬇️ Download Pivot Report",
            data=excel_bytes,
            file_name="model_pivot_stock_comparison.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )

    except Exception as e:
        st.error(f"Error: {e}")
else:
    st.info("Dono files upload karo: Hermi + Odoo OCT.")
