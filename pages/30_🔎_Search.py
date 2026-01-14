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

        rename_map = {
            "Origin": "Airport",
            "Date": "Time_Depart",
            "Total_Items": "Total_Bags",
        }
        df_manifest = df_manifest.rename(columns=rename_map)

        # 2. Bags
        sheet_bags = workbook.worksheet("Bags")
        data_bags = sheet_bags.get_all_records()
        df_bags = pd.DataFrame(data_bags)

        # 3. Seals (New for Country Traceability)
        sheet_seals = workbook.worksheet("Seals")
        # Seals Sheet Columns: Seal_ID, Car_License, Hotel_Name, Country
        # get_all_records requires headers. Assuming Row 1 is header.
        # If Row 1 in Seals is NOT header, we need to inspect.
        # Step 285 GAS code: sealSheet.appendRow([sealId, carLicense, hotelName, country])
        # BUT GAS appends to *existing* sheet.
        # If headers are missing, get_all_records fails.
        # I'll Assume headers exist: Seal_ID, Car_License, Hotel_Name, Country
        try:
            data_seals = sheet_seals.get_all_records()
            df_seals = pd.DataFrame(data_seals)
        except:
            # Fallback if no headers or empty
            df_seals = pd.DataFrame(
                columns=["Seal_ID", "Car_License", "Hotel_Name", "Country"]
            )

        return df_manifest, df_bags, df_seals

    except Exception as e:
        st.error(f"Error loading data: {e}")
        return None, None, None


# --- MAIN APP ---
st.title("🔎 ค้นหาและตรวจสอบ (Search & Audit)")

df_manifest, df_bags, df_seals = load_all_data()

if df_manifest is None:
    st.error("❌ ไม่สามารถเชื่อมต่อกับ Google Sheets ได้")
    st.stop()

# --- SEARCH BAR ---
col_search, col_filter = st.columns([3, 1])
with col_search:
    query = st.text_input(
        "🔍 พิมพ์คำค้นหา (ทะเบียนรถ, ชื่อคนขับ, โรงแรม, ประเทศ)",
        placeholder="เช่น 1กก-1234, Japan, Graph Hotels...",
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

    # Needs to handle numeric/NaN columns safely
    def contains_query(series):
        return series.astype(str).str.lower().str.contains(query, na=False)

    mask = (
        contains_query(results["Car_License"])
        | contains_query(results["Driver"])
        | contains_query(results["Destination"])
        | contains_query(results.get("Country", pd.Series()))  # Safe get
    )
    results = results[mask]

# Filter by Status
if status_filter != "All":
    results = results[results["Status"] == status_filter]

# --- DISPLAY RESULTS ---
st.write(f"พบข้อมูลจำนวน: **{len(results)}** รายการ")

# --- GLOBAL CSV EXPORT ---
if not results.empty and not df_bags.empty and not df_seals.empty:
    with st.expander("📥 Download/Export Data (CSV)"):
        # Logic to merge EVERYTHING for thefiltered results
        # 1. Expand Manifest Rows (Seals are comma separated)?
        # Better: Start from BAGS level.
        # Filter Bags that belong to the resulting Manifests

        # Get list of relevant Seal Numbers from Results
        relevant_seals = []
        for s in results["Seal_Number"].dropna():
            relevant_seals.extend([x.strip() for x in str(s).split(",")])

        # Filter Bags
        export_bags = df_bags[
            df_bags["Seal_ID"].astype(str).isin(relevant_seals)
        ].copy()

        # Check column names in df_seals for merge
        # If using GAS v10, headers might need check.
        # Standardize df_seals columns for merge
        if not df_seals.empty:
            # Ensure Seal_ID is string
            df_seals["Seal_ID"] = df_seals["Seal_ID"].astype(str)

            # Merge Bags + Seals (Left Join)
            export_df = pd.merge(export_bags, df_seals, on="Seal_ID", how="left")

            # Merge with Manifest info (Optional, via Seal_ID matching? Harder if many-to-many)
            # But Seals already has Car_License.
            # So Bags+Seals gives: BagID, SealID, Car, Hotel, Country.
            # We can add Driver/Date from Manifest if we join on Car_License?
            # Car_License is not unique in Manifest (multiple trips).
            # Need unique Trip ID? Seal_ID is likely unique enough for this project scope.

            # Let's try to map Driver/Time from Manifest using Seal_Number match (contains) ???
            # Optimization: Build a Seal -> Manifest Map
            seal_to_manifest = {}
            for idx, r in results.iterrows():
                s_list = [x.strip() for x in str(r["Seal_Number"]).split(",")]
                for s in s_list:
                    seal_to_manifest[s] = {
                        "Driver": r.get("Driver", ""),
                        "Time_Depart": r.get("Time_Depart", ""),
                        "Status": r["Status"],
                        "Origin": r.get("Airport", ""),
                    }

            # Apply Map
            export_df["Driver"] = export_df["Seal_ID"].map(
                lambda x: seal_to_manifest.get(x, {}).get("Driver", "")
            )
            export_df["Time_Depart"] = export_df["Seal_ID"].map(
                lambda x: seal_to_manifest.get(x, {}).get("Time_Depart", "")
            )
            export_df["Status"] = export_df["Seal_ID"].map(
                lambda x: seal_to_manifest.get(x, {}).get("Status", "")
            )

            st.download_button(
                "📄 Download Detailed Report (.csv)",
                export_df.to_csv(index=False).encode("utf-8"),
                "report.csv",
                "text/csv",
            )
        else:
            st.warning("Seals data missing for export.")

if not results.empty:
    for index, row in results.iterrows():
        # Clean Country display
        country_display = row.get("Country", "")
        if pd.isna(country_display):
            country_display = "-"

        with st.expander(
            f"🚛 {row['Car_License']} | 🌏 {country_display} | 📍 {row['Destination']} ({row['Status']})"
        ):
            # --- HEADER METRICS ---
            m1, m2, m3, m4 = st.columns(4)
            m1.metric("เวลาออก", str(row.get("Time_Depart", "-")))
            m2.metric("คนขับ", str(row.get("Driver", "-")))
            m3.metric("จำนวนกระเป๋า", str(row.get("Total_Bags", "0")))
            m4.metric("Seal Number", str(row.get("Seal_Number", "-")))

            st.divider()

            # --- BAG TAG DETAILS ---
            st.subheader("📦 รายละเอียด (Bag Traceability)")

            seal_list = [x.strip() for x in str(row.get("Seal_Number", "")).split(",")]

            # Fetch relevant bags
            current_bags = df_bags[
                df_bags["Seal_ID"].astype(str).isin(seal_list)
            ].copy()

            # Merge with Seal Info (to get granular Country/Hotel per bag)
            if not current_bags.empty and not df_seals.empty:
                # Ensure column types
                df_seals["Seal_ID"] = df_seals["Seal_ID"].astype(str)
                current_bags["Seal_ID"] = current_bags["Seal_ID"].astype(str)

                merged_view = pd.merge(current_bags, df_seals, on="Seal_ID", how="left")

                # Select/Rename Cols
                # Available from Seans: Seal_ID, Car_License, Hotel_Name, Country
                cols_to_show = ["Bag_ID", "Seal_ID", "Country", "Hotel_Name"]
                # Filter only existing cols
                cols_to_show = [c for c in cols_to_show if c in merged_view.columns]

                st.dataframe(
                    merged_view[cols_to_show],
                    use_container_width=True,
                    column_config={
                        "Bag_ID": "Tag ID",
                        "Seal_ID": "Seal ID",
                        "Country": "Country (ประเทศ)",
                        "Hotel_Name": "Hotel (ย่อย)",
                    },
                )
            elif not current_bags.empty:
                st.dataframe(current_bags, use_container_width=True)
            else:
                st.info("No bags found for this shipment.")

else:
    if query:
        st.warning("ไม่พบข้อมูลที่ค้นหา")
    else:
        st.info("กรุณาพิมพ์คำค้นหาหรือเลือกสถานะเพื่อดูข้อมูล")
