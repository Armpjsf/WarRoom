import streamlit as st
import pandas as pd
import gspread
from oauth2client.service_account import ServiceAccountCredentials
import plotly.express as px
from datetime import datetime
from streamlit_autorefresh import st_autorefresh

# --- 1. CONFIGURATION ---
st.set_page_config(
    page_title="APG 2026 War Room",
    page_icon="🚛",
    layout="wide",
    initial_sidebar_state="expanded",
)

# --- 2. AUTO REFRESH (ทุก 30 วินาที) ---
count = st_autorefresh(interval=30000, limit=None, key="warroom_refresh")

# --- 3. CSS STYLING ---
st.markdown(
    """
<style>
    div[data-testid="stMetric"] {
        background-color: #FFFFFF !important;
        padding: 20px !important;
        border-radius: 15px !important;
        border: 1px solid #E0E0E0;
        box-shadow: 0 4px 6px rgba(0, 0, 0, 0.1);
        color: #000000 !important;
    }
    div[data-testid="stMetricLabel"] {
        color: #666666 !important;
        font-size: 14px !important;
        font-weight: bold !important;
    }
    div[data-testid="stMetricValue"] {
        color: #2C3E50 !important;
        font-size: 32px !important;
    }
    div[data-testid="stDataFrame"] {
        background-color: #FFFFFF;
        padding: 10px;
        border-radius: 10px;
    }
</style>
""",
    unsafe_allow_html=True,
)


# --- 4. CONNECT GOOGLE SHEETS ---
@st.cache_data(ttl=15)
def load_data_and_colors():
    try:
        scope = [
            "https://spreadsheets.google.com/feeds",
            "https://www.googleapis.com/auth/drive",
        ]

        try:
            creds_dict = dict(st.secrets["gcp_service_account"])
            creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
        except:
            creds = ServiceAccountCredentials.from_json_keyfile_name(
                "service_account.json", scope
            )

        client = gspread.authorize(creds)
        SHEET_URL = "https://docs.google.com/spreadsheets/d/1TCXZeJexCI4VZ05LTUxildTPxXpvjiKZAnnFEx2NdvQ/edit?gid"
        workbook = client.open_by_url(SHEET_URL)

        # ---------------------------------------------------------
        # 1. โหลดข้อมูล Manifest (โครงสร้างใหม่)
        # ---------------------------------------------------------
        sheet_manifest = workbook.worksheet("Manifest")
        data_manifest = sheet_manifest.get_all_records()

        if not data_manifest:
            headers = sheet_manifest.row_values(1)
            df = pd.DataFrame(columns=headers)
        else:
            df = pd.DataFrame(data_manifest)

        # --- DATA CLEANING & MAPPING ---
        # ปรับชื่อคอลัมน์ให้ตรงกับที่ Code ใช้งาน (Mapping)
        # Sheet Header -> Code Variable
        rename_map = {
            "Origin": "Airport",          # ถ้าใน Sheet ชื่อ Origin (Airport) ให้แก้ตรงนี้ให้ตรง
            "Date": "Time_Depart",
            "Total_Items": "Total_Bags"
        }
        df = df.rename(columns=rename_map)

        # ถ้าชื่อคอลัมน์ใน Sheet ไม่ตรงเป๊ะๆ ให้สร้าง Dummy ขึ้นมากัน Error
        if "Airport" not in df.columns: df["Airport"] = "Unknown"
        if "Total_Bags" not in df.columns: df["Total_Bags"] = 0
        
        # แปลงตัวเลขจำนวนถุง
        df["Total_Bags"] = pd.to_numeric(df["Total_Bags"], errors='coerce').fillna(0).astype(int)


        # ---------------------------------------------------------
        # 2. โหลดข้อมูล Master_Hotels (Color Map)
        # ---------------------------------------------------------
        try:
            sheet_hotels = workbook.worksheet("Master_Hotels")
            data_hotels = sheet_hotels.get_all_records()
            df_hotels = pd.DataFrame(data_hotels)

            if not df_hotels.empty and "Hotel_Name" in df_hotels.columns and "Hex_Code" in df_hotels.columns:
                color_map = pd.Series(
                    df_hotels.Hex_Code.values, index=df_hotels.Hotel_Name
                ).to_dict()

                # เพิ่มสี Status และ Airport
                status_colors = {
                    "Loading": "#F39C12",   # ส้ม
                    "Loaded": "#F39C12",    # ส้ม (เพิ่ม Loaded เข้ามา)
                    "In-Transit": "#2980B9",# น้ำเงิน
                    "Completed": "#27AE60", # เขียว
                    "Issue": "#C0392B",     # แดง
                    "BKK": "#6C5CE7",       # ม่วง
                    "DMK": "#00B894",       # เขียวมิ้นท์
                }
                color_map.update(status_colors)
            else:
                raise ValueError("Colors missing")

        except Exception:
            # Fallback Colors (ถ้าโหลดไม่ได้ ใช้สีสำรอง)
            color_map = {
                "Loading": "#F39C12",
                "Loaded": "#F39C12",
                "In-Transit": "#2980B9",
                "Completed": "#27AE60",
                "Issue": "#C0392B",
                "BKK": "#6C5CE7",
                "DMK": "#00B894",
                "Other": "#95A5A6"
            }

        return df, color_map, None

    except Exception as e:
        return None, None, e


# --- 5. MAIN APP ---
df, color_map, error_msg = load_data_and_colors()

if df is None:
    st.error(f"❌ Error connecting to Google Sheets: {error_msg}")
    st.stop()

if df.empty:
    st.info("⚠️ ยังไม่มีข้อมูลใน Sheet 'Manifest' (Waiting for data...)")

# --- 6. SIDEBAR FILTER ---
with st.sidebar:
    st.title("🔍 ตัวกรอง (Filter)")
    
    # กรองเฉพาะ Airport ที่มีข้อมูลจริง
    airport_options = ["All"] + sorted([x for x in df["Airport"].unique() if str(x).strip() != ""])
    selected_airport = st.selectbox("เลือกสนามบินต้นทาง:", airport_options)
    
    st.markdown("---")
    st.caption(f"Last Auto-Update: {datetime.now().strftime('%H:%M:%S')}")

# --- 7. DATA PROCESSING ---
if selected_airport != "All":
    filtered_df = df[df["Airport"] == selected_airport]
    st.info(f"📍 กำลังแสดงข้อมูลของ: **{selected_airport}**")
else:
    filtered_df = df

st.title("🚛 APG 2026: Logistics Command Center")

# คำนวณระยะเวลา (Duration)
try:
    filtered_df["Time_Depart"] = pd.to_datetime(filtered_df["Time_Depart"], errors="coerce")
    now = datetime.now()
    
    # คำนวณเฉพาะรถที่ออกไปแล้ว (Loaded / In-Transit)
    filtered_df["Duration_Hours"] = filtered_df.apply(
        lambda row: (
            (now - row["Time_Depart"]).total_seconds() / 3600
            if pd.notnull(row["Time_Depart"]) and row["Status"] in ["In-Transit", "Loaded"]
            else 0
        ),
        axis=1,
    )
except:
    filtered_df["Duration_Hours"] = 0

# --- 8. DASHBOARD UI ---
col1, col2, col3, col4, col5 = st.columns(5)
total_jobs = len(filtered_df)
# นับรวม Loading และ Loaded เป็นสถานะ Active เหมือนกัน
loading = len(filtered_df[filtered_df["Status"].isin(["Loading", "Loaded"])])
in_transit = len(filtered_df[filtered_df["Status"] == "In-Transit"])
completed = len(filtered_df[filtered_df["Status"] == "Completed"])
issues = len(filtered_df[filtered_df["Status"] == "Issue"])

col1.metric("📋 งานรวม", f"{total_jobs}", delta="Jobs")
col2.metric("📦 Loading/Loaded", f"{loading}", delta="Active", delta_color="off")
col3.metric("🚚 In-Transit", f"{in_transit}", delta="Running", delta_color="normal")
col4.metric("✅ Completed", f"{completed}", delta="Done")
col5.metric("🚨 Issues", f"{issues}", delta="Alert", delta_color="inverse")

st.markdown("---")

# Alert Section
long_running = filtered_df[filtered_df["Duration_Hours"] > 4]
if issues > 0 or not long_running.empty:
    st.subheader("⚠️ Action Required")
    alert_c1, alert_c2 = st.columns(2)
    with alert_c1:
        if issues > 0:
            st.error(f"🔴 พบเคสแจ้งปัญหา : {issues} รายการ")
            st.dataframe(
                filtered_df[filtered_df["Status"] == "Issue"][
                    ["Car_License", "Destination", "Driver"]
                ],
                use_container_width=True,
            )
    with alert_c2:
        if not long_running.empty:
            st.warning(f"🟡 รถวิ่งนานเกิน 4 ชม. : {len(long_running)} คัน")
            st.dataframe(
                long_running[
                    ["Car_License", "Destination", "Duration_Hours"]
                ],
                use_container_width=True,
            )

# --- 9. SMART CHARTS ---
c1, c2 = st.columns([2, 1])

with c1:
    st.subheader(f"📍 ปริมาณงานแยกตามปลายทาง ({selected_airport})")
    if not filtered_df.empty:
        df_chart = filtered_df.copy()
        # แยก Destination ด้วยจุลภาค (เผื่อมีหลายที่)
        df_chart["Destination_Split"] = df_chart["Destination"].astype(str).str.split(",")
        df_exploded = df_chart.explode("Destination_Split")
        df_exploded["Destination_Split"] = df_exploded["Destination_Split"].str.strip()

        # นับจำนวน
        load_counts = df_exploded.groupby("Destination_Split").size().reset_index(name="Count")

        fig_bar = px.bar(
            load_counts,
            x="Destination_Split",
            y="Count",
            color="Destination_Split",
            color_discrete_map=color_map,
            text_auto=True,
        )
        fig_bar.update_layout(xaxis_title="Destination", yaxis_title="Number of Drops")
        st.plotly_chart(fig_bar, use_container_width=True)

with c2:
    st.subheader("⏳ สถานะงาน")
    if not filtered_df.empty:
        status_counts = filtered_df.groupby("Status").size().reset_index(name="Count")
        fig_pie = px.pie(
            status_counts,
            values="Count",
            names="Status",
            hole=0.4,
            color="Status",
            color_discrete_map=color_map,
        )
        st.plotly_chart(fig_pie, use_container_width=True)

# --- 10. REAL-TIME TABLE ---
st.subheader("📝 บันทึกการเดินรถ (Real-time Log)")

# เลือกคอลัมน์ที่จะโชว์ (ตัด Job_ID ออก, เพิ่ม Total_Bags)
display_cols = [
    "Time_Depart",
    "Airport",
    "Car_License",
    "Destination",
    "Total_Bags",  # อันนี้คือ Total_Items จาก Sheet
    "Status",
    "Seal_Number",
]

# กรองเอาเฉพาะคอลัมน์ที่มีอยู่จริง เพื่อป้องกัน Error
safe_cols = [c for c in display_cols if c in filtered_df.columns]

st.dataframe(
    filtered_df.sort_values(by="Time_Depart", ascending=False)[safe_cols],
    use_container_width=True,
    height=400,
)