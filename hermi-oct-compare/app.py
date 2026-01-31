import re
import pandas as pd
import streamlit as st

st.set_page_config(page_title="Hermi vs OCT Stock Tool", layout="wide")

st.title("📊 Hermi vs OCT Stock Comparison")
st.write("HERMIE-FILE-FOR-OUTFIT-2.xlsx (real qty) aur Untitled-spreadsheet-5.xlsx (OCT qty) ko compare karo.")

col1, col2 = st.columns(2)
with col1:
    hermi_file = st.file_uploader("Hermi File (Real Quantity)", type=["xlsx", "xls"], key="hermi")
with col2:
    oct_file = st.file_uploader("OCT File (System Quantity)", type=["xlsx", "xls"], key="oct")


@st.cache_data
def parse_hermi_file(uploaded):
    # IMPORTANT: header=1  ⇒ second row ko header le (0-indexed)
    df = pd.read_excel(uploaded, header=1)

    # Ab headers proper aayenge: NO, SKU, S, M, ..., COLOR, STATUS IN SALLA, QTY
    clean_map = {}
    for c in df.columns:
        key = str(c).strip().lower().replace("  ", " ")
        clean_map[key] = c

    sku_col = clean_map.get("sku")
    qty_col = clean_map.get("qty")
    color_col = clean_map.get("color")
    status_col = clean_map.get("status in salla") or clean_map.get("status")

    if not sku_col or not qty_col:
        st.write("DEBUG Hermi headers:", list(df.columns))
        raise ValueError("Hermi file me SKU ya QTY column nahi mila. Header row me 'SKU' aur 'QTY' hone chahiye.")

    df["SKU_CLEAN"] = df[sku_col].astype(str).str.strip()
    df["COLOR"] = df[color_col].astype(str).str.strip() if color_col else ""
    df["STATUS"] = df[status_col].astype(str).str.strip() if status_col else ""
    df["HERMI_QTY"] = pd.to_numeric(df[qty_col], errors="coerce").fillna(0)

    grouped = (
        df.groupby("SKU_CLEAN", as_index=False)
        .agg(
            {
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
    cols = {str(c).lower().strip(): c for c in df.columns}
    name_col = cols.get("display name") or list(df.columns)[0]
    qty_col = cols.get("quantity on hand") or list(df.columns)[1]

    df[name_col] = df[name_col].astype(str).str.strip()
    df["OCT_QTY_RAW"] = pd.to_numeric(df[qty_col], errors="coerce").fillna(0)

    def extract_sku(s):
        m = re.search(r"\[([^\]]+)\]", s)
        if not m:
            return None
        sku = m.group(1).split("/")[0]
        return sku.strip()

    df["SKU_CLEAN"] = df[name_col].apply(extract_sku)
    df = df.dropna(subset=["SKU_CLEAN"])

    grouped = df.groupby("SKU_CLEAN", as_index=False)["OCT_QTY_RAW"].sum()
    grouped.rename(columns={"OCT_QTY_RAW": "OCT_QTY"}, inplace=True)
    return grouped


if hermi_file and oct_file:
    try:
        hermi_df = parse_hermi_file(hermi_file)
        oct_df = parse_oct_file(oct_file)

        merged = hermi_df.merge(oct_df, on="SKU_CLEAN", how="left")
        merged["OCT_QTY"] = merged["OCT_QTY"].fillna(0)
        merged["DIFF"] = merged["OCT_QTY"] - merged["HERMI_QTY"]
        merged["MATCH"] = merged["DIFF"].round(2) == 0
        merged["IS_PUBLISHED"] = merged["STATUS"].str.upper().str.contains("PUBLISHED")

        total_items = len(merged)
        matched = int(merged["MATCH"].sum())
        mismatched = int(total_items - matched)
        published = int(merged["IS_PUBLISHED"].sum())

        st.subheader("📈 Summary")
        k1, k2, k3, k4, k5 = st.columns(5)
        k1.metric("Total Items", total_items)
        k2.metric("Matched", matched)
        k3.metric("Mismatch", mismatched)
        k4.metric("Match %", f"{(matched/total_items*100):.1f}%" if total_items else "0%")
        k5.metric("Published", published)

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
                df_view["SKU_CLEAN"].str.lower().str.contains(s)
                | df_view["COLOR"].astype(str).str.lower().str.contains(s)
            ]

        df_view = df_view[
            ["SKU_CLEAN", "COLOR", "STATUS", "HERMI_QTY", "OCT_QTY", "DIFF", "MATCH"]
        ].rename(
            columns={
                "SKU_CLEAN": "SKU",
                "HERMI_QTY": "Hermi Qty",
                "OCT_QTY": "OCT Qty",
                "DIFF": "Difference",
                "MATCH": "Match",
            }
        )

        st.subheader("📋 Detailed Comparison")

        def highlight_row(row):
            color = "#d4edda" if row["Match"] else "#f8d7da"
            return [f"background-color: {color}"] * len(row)

        st.dataframe(df_view.style.apply(highlight_row, axis=1), use_container_width=True)

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
