import streamlit as st
import pandas as pd
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from datetime import datetime

st.set_page_config(page_title="Search & Audit", page_icon="🔎", layout="wide")

# --- CUSTOM CSS ---
st.markdown(
    """
<style>
    div[data-testid="stMetric"] {
        background-color: #F0F2F6;
        padding: 10px;
        border-radius: 8px;
    }
</style>
""",
    unsafe_allow_html=True,
)


# --- CACHED DATA LOADING ---
@st.cache_data(ttl=60)
def load_all_data():
    try:
        scope = [
            "https://spreadsheets.google.com/feeds",
            "https://www.googleapis.com/auth/drive",
        ]
        # Try finding credentials
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

        # 1. Manifest
        sheet_manifest = workbook.worksheet("Manifest")
        data_manifest = sheet_manifest.get_all_records()
        df_manifest = pd.DataFrame(data_manifest)

        # Rename for consistency
        rename_map = {
            "Origin": "Airport",
            "Date": "Time_Depart",
            "Total_Items": "Total_Bags",
        }
        df_manifest = df_manifest.rename(columns=rename_map)

        # 2. Bags (for drill-down)
        sheet_bags = workbook.worksheet("Bags")
        data_bags = sheet_bags.get_all_records()
        df_bags = pd.DataFrame(data_bags)

        return df_manifest, df_bags

    except Exception as e:
        return None, None


# --- MAIN APP ---
st.title("🔎 ค้นหาและตรวจสอบ (Search & Audit)")

df_manifest, df_bags = load_all_data()

if df_manifest is None:
    st.error("❌ ไม่สามารถเชื่อมต่อกับ Google Sheets ได้")
    st.stop()

# --- SEARCH BAR ---
col_search, col_filter = st.columns([3, 1])
with col_search:
    query = st.text_input(
        "🔍 พิมพ์คำค้นหา (ทะเบียนรถ, ชื่อคนขับ, โรงแรม)",
        placeholder="เช่น 1กก-1234, สมชาย, Graph Hotels...",
    )

with col_filter:
    status_filter = st.selectbox(
        "สถานะงาน", ["All", "Loading", "In-Transit", "Completed", "Issue"]
    )

# --- FILTERING LOGIC ---
results = df_manifest.copy()

# Filter by Query
if query:
    query = query.lower().strip()
    mask = (
        results["Car_License"].astype(str).str.lower().str.contains(query)
        | results["Driver"].astype(str).str.lower().str.contains(query)
        | results["Destination"].astype(str).str.lower().str.contains(query)
    )
    results = results[mask]

# Filter by Status
if status_filter != "All":
    results = results[results["Status"] == status_filter]

# --- DISPLAY RESULTS ---
st.write(f"พบข้อมูลจำนวน: **{len(results)}** รายการ")

if not results.empty:
    for index, row in results.iterrows():
        with st.expander(
            f"🚛 {row['Car_License']} | 👤 {row['Driver']} | 📍 {row['Destination']} ({row['Status']})"
        ):

            # --- HEADER METRICS ---
            m1, m2, m3, m4 = st.columns(4)
            m1.metric("เวลาออก", str(row.get("Time_Depart", "-")))
            m2.metric("ต้นทาง", str(row.get("Airport", "-")))
            m3.metric("จำนวนกระเป๋า (ใบ)", str(row.get("Total_Bags", "0")))
            m4.metric("Seal Number", str(row.get("Seal_Number", "-")))

            st.divider()

            # --- BAG TAG DETAILS ---
            st.subheader("📦 รายละเอียดกระเป๋าและซีล")

            seal_num = str(row.get("Seal_Number", "")).strip()

            if seal_num and not df_bags.empty:
                # Find bags matching this seal
                # Assuming 'Seal_ID' in Bags corresponds to 'Seal_Number' in Manifest
                related_bags = df_bags[
                    df_bags["Seal_ID"].astype(str).str.strip() == seal_num
                ]

                if not related_bags.empty:
                    st.success(f"✅ พบข้อมูล Tag จำนวน {len(related_bags)} รายการ")
                    st.dataframe(
                        related_bags,
                        use_container_width=True,
                        column_config={
                            "Bag_ID": "หมายเลข Tag กระเป๋า",
                            "Seal_ID": "เลขซีลที่ผูก",
                        },
                    )
                else:
                    st.warning(f"⚠️ ไม่พบข้อมูล Tag สำหรับซีลหมายเลข: {seal_num}")
            else:
                if not seal_num:
                    st.info("ℹ️ รายการนี้ไม่มีเลข Seal Number")
                else:
                    st.error("❌ ไม่สามารถโหลดข้อมูล Bags ได้")

else:
    if query:
        st.warning("ไม่พบข้อมูลที่ค้นหา")
    else:
        st.info("กรุณาพิมพ์คำค้นหาหรือเลือกสถานะเพื่อดูข้อมูล")
