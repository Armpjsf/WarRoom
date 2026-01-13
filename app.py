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

# --- 2. AUTO REFRESH ---
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
        # 1. โหลดข้อมูล Manifest (งานหลัก)
        # ---------------------------------------------------------
        sheet_manifest = workbook.worksheet("Manifest")
        data_manifest = sheet_manifest.get_all_records()

        if not data_manifest:
            # กรณีไม่มีข้อมูล ให้ดึงเฉพาะหัวตารางมาสร้าง DataFrame ว่างๆ
            headers = sheet_manifest.row_values(1)
            df = pd.DataFrame(columns=headers)
        else:
            df = pd.DataFrame(data_manifest)

        # ---------------------------------------------------------
        # 2. คำนวณยอดกระเป๋า (Total_Bags) จาก Seals & Bags
        # ---------------------------------------------------------
        try:
            # ถ้า DataFrame หลักไม่ว่าง ให้ลองไปดึงข้อมูลถุงมานับ
            if not df.empty:
                sheet_seals = workbook.worksheet("Seals")
                data_seals = sheet_seals.get_all_records()
                df_seals = pd.DataFrame(data_seals)

                sheet_bags = workbook.worksheet("Bags")
                data_bags = sheet_bags.get_all_records()
                df_bags = pd.DataFrame(data_bags)

                if not df_seals.empty and not df_bags.empty:
                    # เชื่อม Bags -> Seals (ผ่าน Seal_ID)
                    merged_bags = df_bags.merge(df_seals, on="Seal_ID", how="left")

                    # นับจำนวนกระเป๋าต่อ Job (Group by Job_ID)
                    job_counts = (
                        merged_bags.groupby("Job_ID")["Bag_ID"].count().reset_index()
                    )
                    job_counts.columns = ["Job_ID", "Total_Bags"]

                    # เอาไปแปะรวมกับ df หลัก
                    df = df.merge(job_counts, on="Job_ID", how="left")
                    df["Total_Bags"] = df["Total_Bags"].fillna(0).astype(int)
                else:
                    df["Total_Bags"] = 0
            else:
                # ถ้า df หลักว่าง ก็สร้างคอลัมน์เปล่าๆ ไว้กัน Error
                df["Total_Bags"] = 0

        except Exception as e:
            # ถ้ามีปัญหาตอนดึงถุง (เช่น ยังไม่สร้าง Sheet) ให้ใส่ 0 ไปก่อน อย่าให้โปรแกรมพัง
            if not df.empty:
                df["Total_Bags"] = 0

        # ---------------------------------------------------------
        # 3. โหลดข้อมูล Master_Hotels (Color Map)
        # ---------------------------------------------------------
        try:
            sheet_hotels = workbook.worksheet("Master_Hotels")
            data_hotels = sheet_hotels.get_all_records()
            df_hotels = pd.DataFrame(data_hotels)

            # Create Color Map dictionary: { 'Hotel_Name': 'Hex_Code' }
            if (
                not df_hotels.empty
                and "Hotel_Name" in df_hotels.columns
                and "Hex_Code" in df_hotels.columns
            ):
                color_map = pd.Series(
                    df_hotels.Hex_Code.values, index=df_hotels.Hotel_Name
                ).to_dict()

                # Add static status colors that might not be in Hotels list
                status_colors = {
                    "Loading": "#F39C12",
                    "In-Transit": "#2980B9",
                    "Completed": "#27AE60",
                    "Issue": "#C0392B",
                    "BKK": "#6C5CE7",
                    "DMK": "#00B894",
                }
                color_map.update(status_colors)
            else:
                # กรณี Master_Hotels มีปัญหา ให้ใช้ค่า Default
                raise ValueError("Master_Hotels empty or missing columns")

        except Exception as color_error:
            # Fallback colors
            color_map = {
                "หอพัก ม.สุรนารี (SUT)": "#F1C40F",
                "Kantary Hotel": "#E74C3C",
                "Sima Thani Hotel": "#3498DB",
                "The Imperial Hotel": "#2ECC71",
                "Fortune Hotel": "#E67E22",
                "Centre Point": "#9B59B6",
                "Centara Korat": "#FF7979",
                "Other": "#95A5A6",
                "Loading": "#F39C12",
                "In-Transit": "#2980B9",
                "Completed": "#27AE60",
                "Issue": "#C0392B",
                "BKK": "#6C5CE7",
                "DMK": "#00B894",
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
    st.info("⚠️ ยังไม่มีข้อมูลใน Sheet 'Manifest' (Waiting for AppSheet data...)")
    # ไม่ st.stop() แล้ว เพื่อให้ระบบรันต่อได้ (แสดงกราฟว่างๆ)

# --- 6. SIDEBAR FILTER ---
with st.sidebar:
    st.title("🔍 ตัวกรอง (Filter)")
    if "Airport" not in df.columns:
        df["Airport"] = "Unknown"
    airport_options = ["All"] + sorted([x for x in df["Airport"].unique() if x != ""])
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

try:
    filtered_df["Time_Depart"] = pd.to_datetime(
        filtered_df["Time_Depart"], errors="coerce"
    )
    now = datetime.now()
    filtered_df["Duration_Hours"] = filtered_df.apply(
        lambda row: (
            (now - row["Time_Depart"]).total_seconds() / 3600
            if row["Status"] == "In-Transit" and pd.notnull(row["Time_Depart"])
            else 0
        ),
        axis=1,
    )
except:
    filtered_df["Duration_Hours"] = 0

# --- 8. DASHBOARD UI ---
col1, col2, col3, col4, col5 = st.columns(5)
total_jobs = len(filtered_df)
loading = len(filtered_df[filtered_df["Status"] == "Loading"])
in_transit = len(filtered_df[filtered_df["Status"] == "In-Transit"])
completed = len(filtered_df[filtered_df["Status"] == "Completed"])
issues = len(filtered_df[filtered_df["Status"] == "Issue"])

col1.metric("📋 งานรวม", f"{total_jobs}", delta="Jobs")
col2.metric("📦 Loading", f"{loading}", delta="Active", delta_color="off")
col3.metric("🚚 In-Transit", f"{in_transit}", delta="Running", delta_color="normal")
col4.metric("✅ Completed", f"{completed}", delta="Done")
col5.metric("🚨 Issues", f"{issues}", delta="Alert", delta_color="inverse")

st.markdown("---")

long_running = filtered_df[filtered_df["Duration_Hours"] > 4]
if issues > 0 or not long_running.empty:
    st.subheader("⚠️ Action Required")
    alert_c1, alert_c2 = st.columns(2)
    with alert_c1:
        if issues > 0:
            st.error(f"🔴 พบเคสแจ้งปัญหา : {issues} รายการ")
            st.dataframe(
                filtered_df[filtered_df["Status"] == "Issue"][
                    ["Job_ID", "Car_License", "Destination"]
                ],
                use_container_width=True,
            )
    with alert_c2:
        if not long_running.empty:
            st.warning(f"🟡 รถวิ่งนานเกิน 4 ชม. : {len(long_running)} คัน")
            st.dataframe(
                long_running[
                    ["Job_ID", "Car_License", "Destination", "Duration_Hours"]
                ],
                use_container_width=True,
            )

# --- 9. SMART CHARTS (Multi-Drop Support) ---
c1, c2 = st.columns([2, 1])

with c1:
    st.subheader(f"📍 ปริมาณงานแยกตามปลายทาง ({selected_airport})")
    if not filtered_df.empty:
        # LOGIC ใหม่: แยก Destination ที่มีจุลภาคออกจากกันเพื่อนับแยก
        # 1. แปลงคอลัมน์ Destination ให้เป็น list (โดยแยกด้วยจุลภาค)
        # 2. 'explode' เพื่อกระจายแถว 1 งาน -> หลายแถวตามจำนวนสถานที่

        # สร้าง copy เพื่อไม่ให้กระทบ df หลัก
        df_chart = filtered_df.copy()
        df_chart["Destination_Split"] = (
            df_chart["Destination"].astype(str).str.split(",")
        )
        df_exploded = df_chart.explode("Destination_Split")

        # ตัดช่องว่างทิ้ง (Trim whitespace) เช่น " Hotel A" -> "Hotel A"
        df_exploded["Destination_Split"] = df_exploded["Destination_Split"].str.strip()

        # นับจำนวน
        load_counts = (
            df_exploded.groupby("Destination_Split").size().reset_index(name="Count")
        )

        fig_bar = px.bar(
            load_counts,
            x="Destination_Split",
            y="Count",
            color="Destination_Split",
            color_discrete_map=color_map,  # สีจะกลับมาถูกต้องแม่นยำ
            text_auto=True,
        )
        # ปรับชื่อแกนให้น่าอ่าน
        fig_bar.update_layout(
            xaxis_title="Destination Points", yaxis_title="Number of Drops"
        )
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

# Table
st.subheader("📝 บันทึกการเดินรถ (Real-time Log)")
display_cols = [
    "Job_ID",
    "Airport",
    "Time_Depart",
    "Car_License",
    "Destination",
    "Total_Bags",
    "Status",
    "Seal_Number",
]
safe_cols = [c for c in display_cols if c in filtered_df.columns]
st.dataframe(
    filtered_df.sort_values(by="Time_Depart", ascending=False)[safe_cols],
    use_container_width=True,
    height=400,
)
