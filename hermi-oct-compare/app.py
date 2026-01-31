import streamlit as st
import pandas as pd
import requests
import plotly.express as px

# ============== DATA LOADING ==============
@st.cache_data
def load_data(uploaded_file, sheet_name):
    """Load and clean data from uploaded Excel file"""
    try:
        raw = pd.read_excel(uploaded_file, sheet_name=sheet_name)

        # Check if row 1 has headers (like your Sheet6 format)
        if raw.iloc[0].isna().all() or raw.iloc[1].isna().sum() < raw.iloc[0].isna().sum():
            new_cols = raw.iloc[1].tolist()
            df = raw.iloc[2:].copy()
            df.columns = new_cols
        else:
            df = raw.copy()

        # Try to rename common columns
        rename_map = {
            "MODEL": "model",
            "PURCHASE YEAR": "purchase_year",
            "CATEOGRY": "category",
            "SEASON": "season",
            "Brand": "brand",
            "Sum of PURCHASE QUANTITY": "purchase_qty",
            "Sum of AVAILABLE QUANTITY": "available_qty",
            "Sum of COST": "unit_cost",
            "Sum of TOTAL COST": "total_cost",
            "Sum of SOLD VALUE": "sold_value",
            "Sum of SOLD QUANTITY": "sold_qty",
            "Sum of AVIALBLE VALUE": "available_value",
        }
        df = df.rename(columns=rename_map)

        # Convert numeric columns
        num_cols = [
            "purchase_qty", "available_qty", "unit_cost", "total_cost",
            "sold_value", "sold_qty", "available_value"
        ]
        for c in num_cols:
            if c in df.columns:
                df[c] = pd.to_numeric(df[c], errors="coerce")

        return df.dropna(how="all")
    except Exception as e:
        st.error(f"Error loading data: {e}")
        return pd.DataFrame()


# ============== ANALYSIS FUNCTIONS ==============
def kpi_overview(df):
    """Calculate main KPIs"""
    kpis = {}
    if "model" in df.columns:
        kpis["total_models"] = int(df["model"].nunique())
    if "purchase_qty" in df.columns:
        kpis["total_purchase_qty"] = float(df["purchase_qty"].sum())
    if "available_qty" in df.columns:
        kpis["total_available_qty"] = float(df["available_qty"].sum())
    if "total_cost" in df.columns:
        kpis["total_cost"] = float(df["total_cost"].sum())
    if "sold_value" in df.columns:
        kpis["total_sold_value"] = float(df["sold_value"].sum())
    if "available_value" in df.columns:
        kpis["total_available_value"] = float(df["available_value"].sum())
    if "sold_qty" in df.columns:
        kpis["total_sold_qty"] = float(df["sold_qty"].sum())
    return kpis


def top_models_by_profit(df, n=20):
    """Find top profitable models"""
    if not all(c in df.columns for c in ["sold_value", "available_value", "total_cost"]):
        return pd.DataFrame()

    temp = df.copy()
    temp["approx_profit"] = (
        temp["sold_value"].fillna(0) + 
        temp["available_value"].fillna(0) - 
        temp["total_cost"].fillna(0)
    )
    temp["profit_margin_%"] = (temp["approx_profit"] / temp["total_cost"].replace(0, pd.NA)) * 100
    return temp.sort_values("approx_profit", ascending=False).head(n)


def category_summary(df):
    """Summary by category"""
    if "category" not in df.columns:
        return pd.DataFrame()

    grp = df.groupby("category", dropna=False).agg({
        "model": "nunique",
        "purchase_qty": "sum",
        "available_qty": "sum",
        "total_cost": "sum",
        "sold_value": "sum",
        "available_value": "sum",
    }).reset_index()

    grp["sell_through_%"] = (
        grp["sold_value"] / (grp["sold_value"] + grp["available_value"]).replace(0, pd.NA) * 100
    )
    return grp.sort_values("sold_value", ascending=False)


def brand_summary(df, category_filter=None, season_filter=None):
    """Summary by brand with optional filters"""
    if "brand" not in df.columns:
        return pd.DataFrame()

    temp = df.copy()
    if category_filter:
        temp = temp[temp["category"] == category_filter]
    if season_filter:
        temp = temp[temp["season"] == season_filter]

    grp = temp.groupby("brand", dropna=False).agg({
        "model": "nunique",
        "purchase_qty": "sum",
        "available_qty": "sum",
        "total_cost": "sum",
        "sold_value": "sum",
        "available_value": "sum",
    }).reset_index()

    grp["roi_%"] = (
        (grp["sold_value"] + grp["available_value"] - grp["total_cost"]) / 
        grp["total_cost"].replace(0, pd.NA) * 100
    )
    return grp.sort_values("sold_value", ascending=False)


def dead_stock_analysis(df, threshold_days=90):
    """Find slow-moving or dead stock"""
    if not all(c in df.columns for c in ["available_qty", "sold_qty"]):
        return pd.DataFrame()

    temp = df.copy()
    temp["total_qty"] = temp["purchase_qty"].fillna(0)
    temp["sold_pct"] = (temp["sold_qty"].fillna(0) / temp["total_qty"].replace(0, pd.NA)) * 100

    dead = temp[temp["sold_pct"] < 20].copy()
    dead = dead.sort_values("available_value", ascending=False)
    return dead.head(50)


# ============== LLM FUNCTION ==============
def call_data_analyst_llm(question: str, data_sample: pd.DataFrame, api_key: str, model_name: str) -> str:
    """Call OpenAI API for data analysis"""
    if not api_key:
        return "❌ API key missing hai. Sidebar me OpenAI API key daalo."

    sample = data_sample.head(100).to_dict(orient="records")

    system_prompt = """You are a senior retail fashion data analyst for a Saudi apparel brand called Swag.

You MUST:
- Analyze the structured data provided (columns: model, category, season, purchase_qty, available_qty, total_cost, sold_value, sold_qty, available_value)
- Give numeric answers with clear calculations
- When asked for top/bottom items, return concrete lists with model codes, quantities, and values
- Calculate metrics like ROI, profit margin, sell-through rate when relevant
- Be specific and actionable - this is for business decisions
- If data is insufficient, explain what's missing
- Answer in simple Hindi/Urdu + English mix (like the user talks)"""

    payload = {
        "model": model_name,
        "messages": [
            {"role": "system", "content": system_prompt},
            {
                "role": "user",
                "content": f"Data sample ({len(sample)} rows):\n{sample}\n\nQuestion: {question}",
            },
        ],
        "temperature": 0.3,
    }

    try:
        resp = requests.post(
            "https://api.openai.com/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json=payload,
            timeout=45,
        )
        resp.raise_for_status()
        data = resp.json()
        return data["choices"][0]["message"]["content"]
    except Exception as e:
        return f"❌ LLM error: {e}"


# ============== STREAMLIT APP ==============
st.set_page_config(page_title="Swag Data Analyst Chat", layout="wide", page_icon="📊")

# Initialize session state
if "chat_history" not in st.session_state:
    st.session_state.chat_history = []
if "df" not in st.session_state:
    st.session_state.df = None

# ============== SIDEBAR ==============
with st.sidebar:
    st.title("📊 Swag Analytics")
    st.markdown("---")

    # File upload
    st.subheader("1️⃣ Upload Data")
    uploaded_file = st.file_uploader("Upload Excel file", type=["xlsx", "xls"])

    if uploaded_file:
        # Get sheet names
        xls = pd.ExcelFile(uploaded_file)
        sheet_names = xls.sheet_names

        selected_sheet = st.selectbox("Select Sheet", options=sheet_names)

        if st.button("Load Data"):
            with st.spinner("Loading data..."):
                st.session_state.df = load_data(uploaded_file, selected_sheet)
                st.success(f"✅ Loaded {len(st.session_state.df)} rows from {selected_sheet}")

    st.markdown("---")

    # Filters (only show if data is loaded)
    if st.session_state.df is not None and not st.session_state.df.empty:
        df = st.session_state.df

        st.subheader("2️⃣ Filters")

        # Year filter
        if "purchase_year" in df.columns:
            years = sorted([y for y in df["purchase_year"].dropna().unique() if pd.notna(y)])
            year_filter = st.selectbox("Purchase Year", ["All"] + years)
        else:
            year_filter = "All"

        # Season filter
        if "season" in df.columns:
            seasons = sorted([s for s in df["season"].dropna().unique() if pd.notna(s)])
            season_filter = st.selectbox("Season", ["All"] + seasons)
        else:
            season_filter = "All"

        # Category filter
        if "category" in df.columns:
            categories = sorted([c for c in df["category"].dropna().unique() if pd.notna(c)])
            category_filter = st.selectbox("Category", ["All"] + categories)
        else:
            category_filter = "All"

        # Brand filter
        if "brand" in df.columns:
            brands = sorted([b for b in df["brand"].dropna().unique() if pd.notna(b)])
            brand_filter = st.selectbox("Brand", ["All"] + brands)
        else:
            brand_filter = "All"

        # Apply filters
        filtered_df = df.copy()
        if year_filter != "All":
            filtered_df = filtered_df[filtered_df["purchase_year"] == year_filter]
        if season_filter != "All":
            filtered_df = filtered_df[filtered_df["season"] == season_filter]
        if category_filter != "All":
            filtered_df = filtered_df[filtered_df["category"] == category_filter]
        if brand_filter != "All":
            filtered_df = filtered_df[filtered_df["brand"] == brand_filter]

        st.markdown("---")

        # LLM Settings
        st.subheader("3️⃣ AI Settings")
        llm_mode = st.radio("Chat Mode", ["Off", "Advanced AI Analyst"])

        if llm_mode == "Advanced AI Analyst":
            api_key = st.text_input("OpenAI API Key", type="password", key="api_key")
            model_name = st.text_input("Model", value="gpt-4o-mini", key="model")
        else:
            api_key = None
            model_name = None
    else:
        filtered_df = pd.DataFrame()
        llm_mode = "Off"
        api_key = None
        model_name = None


# ============== MAIN AREA ==============
if st.session_state.df is None or st.session_state.df.empty:
    st.title("🏪 Swag Data Analyst Dashboard")
    st.info("👈 Sidebar se Excel file upload karo aur sheet select karo")

    st.markdown("""
    ### Features:
    - 📤 **Excel upload** with sheet selection
    - 📊 **Advanced KPIs** - profit, ROI, sell-through
    - 🔍 **Smart filters** - year, season, category, brand
    - 🤖 **AI Chat Analyst** - powered by GPT-4
    - 📈 **Quick insights** - top products, dead stock, brand performance
    - 📉 **Visual charts** - category breakdown, trends
    """)
else:
    # KPIs at top
    st.title("📊 Swag Analytics Dashboard")

    kpis = kpi_overview(filtered_df)

    col1, col2, col3, col4, col5 = st.columns(5)

    with col1:
        st.metric("Models", kpis.get("total_models", 0))
    with col2:
        st.metric("Purchase Qty", f"{kpis.get('total_purchase_qty', 0):,.0f}")
    with col3:
        st.metric("Sold Value", f"{kpis.get('total_sold_value', 0):,.0f} SAR")
    with col4:
        st.metric("Available Qty", f"{kpis.get('total_available_qty', 0):,.0f}")
    with col5:
        profit = kpis.get('total_sold_value', 0) + kpis.get('total_available_value', 0) - kpis.get('total_cost', 0)
        st.metric("Total Profit", f"{profit:,.0f} SAR")

    st.markdown("---")

    # Quick Analysis Buttons
    st.subheader("🔥 Quick Insights")

    tab1, tab2, tab3, tab4 = st.tabs(["Top Performers", "Category Analysis", "Brand Performance", "Dead Stock"])

    with tab1:
        if st.button("Show Top 20 Profitable Models", key="top20"):
            top_df = top_models_by_profit(filtered_df, n=20)
            if not top_df.empty:
                st.dataframe(
                    top_df[["model", "category", "brand", "sold_value", "available_value", "approx_profit", "profit_margin_%"]],
                    use_container_width=True
                )
            else:
                st.warning("Insufficient data for profit analysis")

    with tab2:
        cat_df = category_summary(filtered_df)
        if not cat_df.empty:
            st.dataframe(cat_df, use_container_width=True)

            # Chart
            fig = px.bar(cat_df, x="category", y="sold_value", 
                        title="Sales by Category",
                        labels={"sold_value": "Sold Value (SAR)", "category": "Category"})
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.warning("No category data available")

    with tab3:
        brand_df = brand_summary(
            filtered_df,
            category_filter if category_filter != "All" else None,
            season_filter if season_filter != "All" else None
        )
        if not brand_df.empty:
            st.dataframe(brand_df, use_container_width=True)

            # Chart
            fig = px.pie(brand_df, names="brand", values="sold_value", 
                        title="Sales by Brand")
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.warning("No brand data available")

    with tab4:
        dead_df = dead_stock_analysis(filtered_df)
        if not dead_df.empty:
            st.dataframe(
                dead_df[["model", "category", "brand", "available_qty", "sold_qty", "available_value", "sold_pct"]],
                use_container_width=True
            )
        else:
            st.success("No dead stock found!")

    st.markdown("---")

    # Chat Interface
    st.subheader("💬 Data Analyst Chat")

    # Display chat history
    for role, msg in st.session_state.chat_history:
        if role == "user":
            st.markdown(f"**🙋 You:** {msg}")
        else:
            st.markdown(f"**🤖 Analyst:** {msg}")

    # Chat input
    col_input, col_btn = st.columns([4, 1])

    with col_input:
        user_question = st.text_input(
            "Ask anything about your data...",
            placeholder="e.g. Top 5 categories by profit margin? Dead stock ka value kitna hai?",
            key="user_input"
        )

    with col_btn:
        st.write("")  # spacing
        ask_button = st.button("Ask 🚀", use_container_width=True)

    if ask_button and user_question:
        st.session_state.chat_history.append(("user", user_question))

        with st.spinner("Analyzing..."):
            if llm_mode == "Advanced AI Analyst" and api_key:
                answer = call_data_analyst_llm(user_question, filtered_df, api_key, model_name)
            else:
                answer = "❌ AI mode off hai. Sidebar se 'Advanced AI Analyst' enable karo aur API key daalo."

        st.session_state.chat_history.append(("assistant", answer))
        st.rerun()

    # Sample questions
    with st.expander("💡 Sample Questions"):
        st.markdown("""
        - Top 10 models by profit?
        - Which category has highest sell-through rate?
        - Brand wise ROI comparison
        - Dead stock ki list with value
        - Season wise performance comparison
        - Kaunse models me restock zaruri hai?
        """)

    # Raw data viewer
    with st.expander("📋 View Raw Data"):
        st.dataframe(filtered_df, use_container_width=True)

        # Download button
        csv = filtered_df.to_csv(index=False).encode('utf-8')
        st.download_button(
            "Download CSV",
            csv,
            "swag_data_export.csv",
            "text/csv",
            key='download-csv'
        )
