import streamlit as st # type: ignore
import pandas as pd # type: ignore
import gspread
from oauth2client.service_account import ServiceAccountCredentials # type: ignore
import plotly.express as px # type: ignore
from datetime import datetime
import time

# --- 1. CONFIGURATION ---
st.set_page_config(
    page_title="APG 2026 War Room",
    page_icon="🚛",
    layout="wide",
    initial_sidebar_state="expanded"
)

# --- CSS Styling ---
st.markdown("""
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
""", unsafe_allow_html=True)

# --- 2. CONNECT GOOGLE SHEETS ---
@st.cache_data(ttl=15)
def load_data_and_colors():
    try:
        scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
        creds = ServiceAccountCredentials.from_json_keyfile_name("service_account.json", scope)
        client = gspread.authorize(creds)
        
        # 👉 URL ของคุณ (ผมใส่ลิ้งค์ล่าสุดที่คุณส่งมาให้แล้ว)
        SHEET_URL = "https://docs.google.com/spreadsheets/d/1TCXZeJexCI4VZ05LTUxildTPxXpvjiKZAnnFEx2NdvQ/edit?gid"
        
        workbook = client.open_by_url(SHEET_URL)
        
        # 2.1 โหลดข้อมูล
        sheet_manifest = workbook.worksheet("Manifest")
        data_manifest = sheet_manifest.get_all_records()
        df = pd.DataFrame(data_manifest)
        
        # 2.2 สี Modern Palette
        color_map = {
            # โรงแรม
            'หอพัก ม.สุรนารี (SUT)': '#F1C40F', 'Kantary Hotel': '#E74C3C',
            'Sima Thani Hotel': '#3498DB', 'The Imperial Hotel': '#2ECC71',
            'Fortune Hotel': '#E67E22', 'Centre Point': '#9B59B6',
            'Centara Korat': '#FF7979', 'Other': '#95A5A6',
            # สถานะ
            'Loading': '#F39C12', 'In-Transit': '#2980B9',
            'Completed': '#27AE60', 'Issue': '#C0392B',
            # สนามบิน (ใช้ชื่อ Airport)
            'BKK': '#6C5CE7', 'DMK': '#00B894'
        }
        return df, color_map
    except Exception as e:
        return None, None

# --- 3. MAIN APP ---
df, color_map = load_data_and_colors()

if df is None:
    st.error("❌ เชื่อมต่อไม่ได้ เช็คไฟล์ json หรือ URL")
    st.stop()

if df.empty:
    st.warning("⚠️ ยังไม่มีข้อมูล")
    st.stop()

# --- 4. SIDEBAR FILTER (แก้ชื่อคอลัมน์เป็น Airport) ---
with st.sidebar:
    st.title("🔍 ตัวกรอง (Filter)")
    
    # เช็คว่ามีคอลัมน์ Airport ไหม (ถ้าไม่มี สร้าง Dummy กัน Error)
    if 'Airport' not in df.columns:
        df['Airport'] = 'Unknown'
        
    # สร้างตัวเลือก
    # ใช้ชื่อคอลัมน์ 'Airport' แทน 'Origin'
    airport_options = ['All'] + sorted([x for x in df['Airport'].unique() if x != ''])
    selected_airport = st.selectbox("เลือกสนามบินต้นทาง:", airport_options)
    
    st.markdown("---")
    st.caption(f"Last Updated: {datetime.now().strftime('%H:%M:%S')}")

# --- 5. DATA PROCESSING ---
# กรองข้อมูล
if selected_airport != 'All':
    filtered_df = df[df['Airport'] == selected_airport] # แก้ตรงนี้เป็น Airport
    st.info(f"📍 แสดงข้อมูลของ: **{selected_airport}**")
else:
    filtered_df = df

st.title("🚛 APG 2026: Logistics Command Center")

# คำนวณเวลา
try:
    filtered_df['Time_Depart'] = pd.to_datetime(filtered_df['Time_Depart'], errors='coerce')
    now = datetime.now()
    filtered_df['Duration_Hours'] = filtered_df.apply(
        lambda row: (now - row['Time_Depart']).total_seconds() / 3600 if row['Status'] == 'In-Transit' and pd.notnull(row['Time_Depart']) else 0, 
        axis=1
    )
except:
    filtered_df['Duration_Hours'] = 0

# --- 6. KPI CARDS ---
col1, col2, col3, col4, col5 = st.columns(5)
total_jobs = len(filtered_df)
loading = len(filtered_df[filtered_df['Status'] == 'Loading'])
in_transit = len(filtered_df[filtered_df['Status'] == 'In-Transit'])
completed = len(filtered_df[filtered_df['Status'] == 'Completed'])
issues = len(filtered_df[filtered_df['Status'] == 'Issue'])

col1.metric("📋 งานรวม", f"{total_jobs}", delta="Jobs")
col2.metric("📦 Loading", f"{loading}", delta="Active", delta_color="off")
col3.metric("🚚 In-Transit", f"{in_transit}", delta="Running", delta_color="normal")
col4.metric("✅ Completed", f"{completed}", delta="Done")
col5.metric("🚨 Issues", f"{issues}", delta="Alert", delta_color="inverse")

st.markdown("---")

# --- 7. CRITICAL ALERTS ---
long_running = filtered_df[filtered_df['Duration_Hours'] > 4]

if issues > 0 or not long_running.empty:
    st.subheader("⚠️ Action Required")
    alert_c1, alert_c2 = st.columns(2)
    with alert_c1:
        if issues > 0:
            st.error(f"🔴 พบเคสแจ้งปัญหา : {issues} รายการ")
            st.dataframe(filtered_df[filtered_df['Status'] == 'Issue'][['Job_ID', 'Car_License', 'Destination']], use_container_width=True)
    with alert_c2:
        if not long_running.empty:
            st.warning(f"🟡 รถวิ่งนานเกิน 4 ชม. : {len(long_running)} คัน")
            st.dataframe(long_running[['Job_ID', 'Car_License', 'Destination', 'Duration_Hours']], use_container_width=True)

# --- 8. CHARTS ---
c1, c2 = st.columns([2, 1])
with c1:
    st.subheader(f"📍 ปริมาณงานแยกตามปลายทาง ({selected_airport})")
    if not filtered_df.empty:
        load_counts = filtered_df.groupby('Destination').size().reset_index(name='Count')
        fig_bar = px.bar(
            load_counts, x='Destination', y='Count', 
            color='Destination', color_discrete_map=color_map, text_auto=True
        )
        st.plotly_chart(fig_bar, use_container_width=True)

with c2:
    st.subheader("⏳ สถานะงาน")
    if not filtered_df.empty:
        status_counts = filtered_df.groupby('Status').size().reset_index(name='Count')
        fig_pie = px.pie(
            status_counts, values='Count', names='Status', hole=0.4,
            color='Status', color_discrete_map=color_map
        )
        st.plotly_chart(fig_pie, use_container_width=True)

# --- 9. LIVE TABLE ---
st.subheader("📝 บันทึกการเดินรถ (Real-time Log)")
# แก้ชื่อคอลัมน์ตรงนี้ด้วย
display_cols = ['Job_ID', 'Airport', 'Time_Depart', 'Car_License', 'Destination', 'Status', 'Seal_Number']
safe_cols = [c for c in display_cols if c in filtered_df.columns]

st.dataframe(
    filtered_df.sort_values(by='Time_Depart', ascending=False)[safe_cols],
    use_container_width=True,
    height=400
)

time.sleep(30)
st.rerun()