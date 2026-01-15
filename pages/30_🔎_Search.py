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
            "Coler": "Color",  # Handle typo if present
        }
        df_manifest = df_manifest.rename(columns=rename_map)

        # 2. Bags
        sheet_bags = workbook.worksheet("Bags")
        data_bags = sheet_bags.get_all_records()
        df_bags = pd.DataFrame(data_bags)

        # 3. Seals (Use get_all_values for safety)
        sheet_seals = workbook.worksheet("Seals")
        # Explicitly handle columns by index to ensure Country (Col D) is captured
        # Col A=Seal_ID, B=Car, C=Hotel, D=Country
        raw_seals = sheet_seals.get_all_values()

        if len(raw_seals) > 1:
            headers = raw_seals[0]
            rows = raw_seals[1:]

            # Normalize headers
            headers = [h.strip() for h in headers]

            df_seals = pd.DataFrame(rows, columns=headers)

            # If D column exists but header is empty or named "Country"
            # If standard 4 columns:
            # We want to force map properly.
            # Let's verify if "Country" is in headers.
            if "Country" not in df_seals.columns:
                # Assuming standard structure: A, B, C, D
                # If dataframe has at least 4 columns, rename the 4th to Country
                if len(df_seals.columns) >= 4:
                    cols = list(df_seals.columns)
                    cols[3] = "Country"
                    df_seals.columns = cols
                else:
                    # Create empty if missing
                    df_seals["Country"] = ""
        else:
            df_seals = pd.DataFrame(
                columns=["Seal_ID", "Car_License", "Hotel_Name", "Country"]
            )

        return df_manifest, df_bags, df_seals

    except Exception as e:
        st.error(f"Error loading data: {e}")
        return None, None, None


# --- MAIN APP ---
st.title("🔎 ค้นหาและตรวจสอบ (Search & Audit)")

if st.button("🔄 Refresh Data"):
    load_all_data.clear()
    st.rerun()

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

if query:
    query = query.lower().strip()

    def contains_query(series):
        return series.astype(str).str.lower().str.contains(query, na=False)

    mask = (
        contains_query(results["Car_License"])
        | contains_query(results["Driver"])
        | contains_query(results["Destination"])
        | contains_query(results.get("Country", pd.Series()))
    )
    results = results[mask]

if status_filter != "All":
    results = results[results["Status"] == status_filter]

# --- DISPLAY RESULTS ---
st.write(f"พบข้อมูลจำนวน: **{len(results)}** รายการ")

# --- GLOBAL CSV EXPORT ---
if not results.empty and not df_bags.empty and not df_seals.empty:
    with st.expander("📥 Download/Export Data (CSV)"):
        relevant_seals = []
        for s in results["Seal_Number"].dropna():
            relevant_seals.extend([x.strip() for x in str(s).split(",")])

        export_bags = df_bags[
            df_bags["Seal_ID"].astype(str).isin(relevant_seals)
        ].copy()

        # Enforce String Type for consistent merging/mapping
        export_bags["Seal_ID"] = export_bags["Seal_ID"].astype(str).str.strip()

        if not df_seals.empty:
            df_seals["Seal_ID"] = df_seals["Seal_ID"].astype(str)

            # Capture Manifest info relative to the Seal (via search results)
            seal_meta = {}
            for idx, r in results.iterrows():
                s_list = [x.strip() for x in str(r["Seal_Number"]).split(",")]
                for s in s_list:
                    seal_meta[s] = {
                        "Time_Depart": r.get("Time_Depart", ""),
                        "Driver": r.get("Driver", ""),
                        "Status": r.get("Status", ""),
                        "Manifest_Car": r["Car_License"],
                        "Manifest_Dest": r["Destination"],
                    }

            export_df = pd.merge(export_bags, df_seals, on="Seal_ID", how="left")

            # Add Meta
            export_df["Time_Depart"] = export_df["Seal_ID"].map(
                lambda x: seal_meta.get(x, {}).get("Time_Depart", "")
            )
            export_df["Driver"] = export_df["Seal_ID"].map(
                lambda x: seal_meta.get(x, {}).get("Driver", "")
            )
            export_df["Status"] = export_df["Seal_ID"].map(
                lambda x: seal_meta.get(x, {}).get("Status", "")
            )
            export_df["Manifest_Car"] = export_df["Seal_ID"].map(
                lambda x: seal_meta.get(x, {}).get("Manifest_Car", "")
            )

            # Ensure Country is Present
            if "Country" not in export_df.columns:
                export_df["Country"] = "-"

            # Select Reordered Columns for Clean Export
            cols_order = [
                "Bag_ID",
                "Seal_ID",
                "Country",
                "Hotel_Name",
                "Manifest_Car",
                "Driver",
                "Time_Depart",
                "Status",
            ]
            # Add unexpected cols to end
            existing_cols = export_df.columns.tolist()
            final_cols = [c for c in cols_order if c in existing_cols] + [
                c for c in existing_cols if c not in cols_order
            ]

            st.download_button(
                "📄 Download Detailed Report (.csv)",
                export_df[final_cols].to_csv(index=False).encode("utf-8"),
                "report.csv",
                "text/csv",
            )
        else:
            st.warning("Seals data missing for export.")

if not results.empty:
    for index, row in results.iterrows():
        country_display = row.get("Country", "")
        if pd.isna(country_display) or country_display == "":
            # Fallback to Seals lookup for display if Manifest Country is empty
            # (Though GAS updates both, but for old records maybe useful)
            country_display = "-"

        with st.expander(
            f"🚛 {row['Car_License']} | 🌏 {country_display} | 📍 {row['Destination']} ({row['Status']})"
        ):
            m1, m2, m3, m4 = st.columns(4)
            m1.metric("เวลาออก", str(row.get("Time_Depart", "-")))
            m2.metric("คนขับ", str(row.get("Driver", "-")))
            m3.metric("จำนวนกระเป๋า", str(row.get("Total_Bags", "0")))
            m4.metric("Seal Number", str(row.get("Seal_Number", "-")))

            st.divider()
            st.subheader("📦 รายละเอียด (Bag Traceability)")

            seal_list = [x.strip() for x in str(row.get("Seal_Number", "")).split(",")]
            current_bags = df_bags[
                df_bags["Seal_ID"].astype(str).isin(seal_list)
            ].copy()

            if not current_bags.empty and not df_seals.empty:
                df_seals["Seal_ID"] = df_seals["Seal_ID"].astype(str)
                current_bags["Seal_ID"] = current_bags["Seal_ID"].astype(str)

                merged_view = pd.merge(current_bags, df_seals, on="Seal_ID", how="left")

                cols_to_show = ["Bag_ID", "Seal_ID", "Country", "Hotel_Name"]
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
                st.info("No bags found.")

else:
    if query:
        st.warning("ไม่พบข้อมูลที่ค้นหา")
    else:
        st.info("กรุณาพิมพ์คำค้นหาหรือเลือกสถานะ")
