import re
import pandas as pd
import streamlit as st

st.set_page_config(page_title="Hermi vs OCT Stock Tool", layout="wide")

st.title("📊 Hermi vs OCT Stock Comparison")
st.write("HERMIE-FILE-FOR-OUTFIT-2.xlsx (real qty) aur Untitled-spreadsheet-5.xlsx (OCT qty) ko compare karo.")

# ---------------- FILE UPLOAD ---------------- #

col1, col2 = st.columns(2)
with col1:
    hermi_file = st.file_uploader("Hermi File (Real Quantity)", type=["xlsx", "xls"], key="hermi")
with col2:
    oct_file = st.file_uploader("OCT File (System Quantity)", type=["xlsx", "xls"], key="oct")


# ---------------- PARSE FUNCTIONS ---------------- #

@st.cache_data
def parse_hermi_file(uploaded):
    # Hermi file: header nahi lena, raw data
    df = pd.read_excel(uploaded, header=None)

    # Row 0 = "OUTFIT ITEMS", actual table row 1 se start
    df = df.iloc[1:, :].reset_index(drop=True)

    # Column indexes (0‑based):
    # 0: NO
    # 1: MODEL/SKU
    # 9: COLOR
    # 10: STATUS IN SALLA
    # 11: QTY
    sku_col_idx = 1
    color_col_idx = 9
    status_col_idx = 10
    qty_col_idx = 11

    if df.shape[1] <= qty_col_idx:
        raise ValueError("Hermi file ka structure change ho gaya, expected kam se kam 12 columns (NO..QTY).")

    df["MODEL"] = df[sku_col_idx].astype(str).str.strip()
    df["COLOR"] = df[color_col_idx].astype(str).fillna("").str.strip().str.upper()
    df["STATUS"] = df[status_col_idx].astype(str).fillna("").str.strip()
    df["HERMI_QTY"] = pd.to_numeric(df[qty_col_idx], errors="coerce").fillna(0)

    # Empty model rows hatao
    df = df[df["MODEL"] != ""].copy()

    # KEY = MODEL + COLOR
    df["KEY"] = df["MODEL"] + "__" + df["COLOR"]

    grouped = (
        df.groupby("KEY", as_index=False)
        .agg(
            {
                "MODEL": "first",
                "COLOR": "first",
                "STATUS": "first",
                "HERMI_QTY": "sum",
            }
        )
    )
    return grouped


@st.cache_data
def parse_oct_file(uploaded):
    df = pd.read_excel(uploaded, header=0)

    # Expect: Display Name | Quantity On Hand
    cols = {str(c).lower().strip(): c for c in df.columns}
    name_col = cols.get("display name") or list(df.columns)[0]
    qty_col = cols.get("quantity on hand") or list(df.columns)[1]

    df[name_col] = df[name_col].astype(str).str.strip()
    df["OCT_QTY_RAW"] = pd.to_numeric(df[qty_col], errors="coerce").fillna(0)

    # [DN50001-1/L GRAY] -> MODEL = DN50001-1, COLOR = GRAY
    def extract_model_color(s):
        m = re.search(r"\[([^\]]+)\]", s)
        if not m:
            return None, None
        inside = m.group(1)          # e.g. "DN50001-1/L GRAY"
        parts = inside.split()
        base = parts[0]              # "DN50001-1/L"
        model = base.split("/")[0]   # "DN50001-1"
        color = " ".join(parts[1:]).upper() if len(parts) > 1 else ""
        return model.strip(), color.strip()

    df[["MODEL", "COLOR"]] = df[name_col].apply(
        lambda x: pd.Series(extract_model_color(x))
    )

    # MODEL missing rows hatao
    df = df.dropna(subset=["MODEL"])
    df["COLOR"] = df["COLOR"].fillna("").str.upper()

    df["KEY"] = df["MODEL"].astype(str).str.strip() + "__" + df["COLOR"]

    grouped = (
        df.groupby("KEY", as_index=False)["OCT_QTY_RAW"].sum()
        .rename(columns={"OCT_QTY_RAW": "OCT_QTY"})
    )
    return grouped


# ---------------- MAIN LOGIC ---------------- #

if hermi_file and oct_file:
    try:
        hermi_df = parse_hermi_file(hermi_file)
        oct_df = parse_oct_file(oct_file)

        # Outer join taaki dono side ka missing data bhi dikhe
        merged = hermi_df.merge(oct_df, on="KEY", how="outer", suffixes=("_H", "_O"))

        # MODEL / COLOR fill
        merged["MODEL"] = merged["MODEL"].fillna(merged["MODEL"])
        merged["COLOR"] = merged["COLOR"].fillna(merged["COLOR"])

        merged["HERMI_QTY"] = merged["HERMI_QTY"].fillna(0)
        merged["OCT_QTY"] = merged["OCT_QTY"].fillna(0)

        # Strict 2‑decimal rounding
        merged["HERMI_QTY_R"] = merged["HERMI_QTY"].round(2)
        merged["OCT_QTY_R"] = merged["OCT_QTY"].round(2)

        merged["DIFF"] = merged["OCT_QTY_R"] - merged["HERMI_QTY_R"]
        merged["MATCH"] = merged["DIFF"] == 0

        # Missing flags
        merged["ONLY_IN_HERMI"] = (merged["HERMI_QTY_R"] != 0) & (merged["OCT_QTY_R"] == 0)
        merged["ONLY_IN_OCT"] = (merged["OCT_QTY_R"] != 0) & (merged["HERMI_QTY_R"] == 0)

        # STATUS agar Hermi side se aayi ho
        merged["STATUS"] = merged["STATUS"].fillna("")
        merged["IS_PUBLISHED"] = merged["STATUS"].str.upper().str.contains("PUBLISHED")

        # -------- KPIs -------- #
        total_items = len(merged)
        matched = int(merged["MATCH"].sum())
        mismatched = int(total_items - matched)
        published = int(merged["IS_PUBLISHED"].sum())
        not_published = int(total_items - published)

        st.subheader("📈 Summary")
        k1, k2, k3, k4, k5 = st.columns(5)
        k1.metric("Total Items", total_items)
        k2.metric("Matched", matched)
        k3.metric("Mismatch", mismatched)
        k4.metric("Match %", f"{(matched/total_items*100):.1f}%" if total_items else "0%")
        k5.metric("Published", published)

        # -------- Filters -------- #
        st.subheader("🔎 Filter & Search")
        f1, f2, f3 = st.columns([1, 1, 2])
        with f1:
            status_filter = st.selectbox("Match Filter", ["All", "Matched", "Mismatched"], index=0)
        with f2:
            pub_filter = st.selectbox("Publish Filter", ["All", "Published", "Not Published"], index=0)
        with f3:
            search_text = st.text_input("Search SKU / Color")

        df_view = merged.copy()

        if status_filter == "Matched":
            df_view = df_view[df_view["MATCH"]]
        elif status_filter == "Mismatched":
            df_view = df_view[~df_view["MATCH"]]

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

        # Final columns for display
        df_view = df_view[
            [
                "MODEL",
                "COLOR",
                "STATUS",
                "HERMI_QTY_R",
                "OCT_QTY_R",
                "DIFF",
                "MATCH",
                "ONLY_IN_HERMI",
                "ONLY_IN_OCT",
            ]
        ].rename(
            columns={
                "MODEL": "SKU",
                "HERMI_QTY_R": "Hermi Qty",
                "OCT_QTY_R": "OCT Qty",
                "DIFF": "Difference",
                "MATCH": "Match",
                "ONLY_IN_HERMI": "Only in Hermi",
                "ONLY_IN_OCT": "Only in OCT",
            }
        )

        st.subheader("📋 Detailed Comparison")

        def highlight_row(row):
            if row["Only in Hermi"]:
                color = "#fff3cd"   # yellow
            elif row["Only in OCT"]:
                color = "#cce5ff"   # blue
            else:
                color = "#d4edda" if row["Match"] else "#f8d7da"
            return [f"background-color: {color}"] * len(row)

        st.dataframe(df_view.style.apply(highlight_row, axis=1), use_container_width=True)

        # -------- Download Excel -------- #
        from io import BytesIO

        def to_excel_bytes(df):
            output = BytesIO()
            with pd.ExcelWriter(output, engine="xlsxwriter") as writer:
                df.to_excel(writer, index=False, sheet_name="Comparison")
            return output.getvalue()

        excel_bytes = to_excel_bytes(df_view)
        st.download_button(
            "⬇️ Download Comparison Excel",
            data=excel_bytes,
            file_name="stock_comparison.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )

    except Exception as e:
        st.error(f"Error: {e}")
else:
    st.info("Upar dono files upload karo (Hermi + OCT), phir result yahan dikhega.")
