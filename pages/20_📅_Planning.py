import streamlit as st
import pandas as pd
import math
import plotly.express as px
import gspread
from oauth2client.service_account import ServiceAccountCredentials

# page config
st.set_page_config(page_title="Transport Planning", page_icon="📅", layout="wide")

# Custom CSS
st.markdown(
    """
<style>
    div[data-testid="stMetric"] {
        background-color: #F0F2F6;
        padding: 15px;
        border-radius: 10px;
        border: 1px solid #D1D5DB;
    }
    div[data-testid="stMetricValue"] {
        font-size: 28px !important;
        color: #1F2937;
    }
</style>
""",
    unsafe_allow_html=True,
)

st.title("📅 Transport Planning & Calculator")
st.caption("Utilities for counting trucks and managing logistics based on Excel plans.")

# --- Sidebar ---
with st.sidebar:
    st.header("⚙️ Configuration")

    # Uploader
    uploaded_file = st.file_uploader("📂 Upload Plan (Excel)", type=["xlsx"])

    st.divider()

    # Parameters
    st.subheader("🚛 Truck Capacity")
    bags_per_truck = st.slider(
        "Max Items per Truck", min_value=10, max_value=100, value=30, step=5
    )
    st.caption(f"Current Limit: **{bags_per_truck}** items/truck")

    st.divider()

    st.subheader("🔧 Advanced")

    # File Layout Selection
    layout_mode = st.radio(
        "รูปแบบไฟล์ (File Layout)",
        ["Detailed Breakdown (แยกประเภทของ)", "Simple List (รวมจำนวนมาแล้ว)"],
        index=1,
    )

    st.divider()

    if layout_mode == "Detailed Breakdown (แยกประเภทของ)":
        st.caption("สำหรับไฟล์ที่มีแยก Luggage, Wheelchair, Sport Eq.")
        header_row_idx = st.number_input(
            "Header Row Index (0-based)", min_value=0, value=9
        )
        dest_col_idx = st.number_input(
            "Destination Column Index (0-based)", min_value=0, value=16
        )

    else:
        st.caption("สำหรับไฟล์ที่มีคอลัมน์ 'จำนวนรวม' มาให้เลย (เช่น แผนงาน.xlsx)")
        header_row_idx = st.number_input(
            "Header Row Index (0-based)",
            min_value=0,
            value=0,
            help="บรรทัดแรกของหัวตาราง (เริ่มนับที่ 0)",
        )

        # Default indices based on 'แผนงาน.xlsx' inspection
        # 0: Country, 1: Date, 2: Flight, 3: Time, 4: Hotel, 5: Qty
        c_country = st.number_input("Col: Country (Index)", value=0)
        c_date = st.number_input("Col: Date (Index)", value=1)
        c_flight = st.number_input("Col: Flight (Index)", value=2)
        c_time = st.number_input("Col: Time (Index)", value=3)
        c_hotel = st.number_input("Col: Hotel/Dest (Index)", value=4)
        c_qty = st.number_input("Col: Total Qty (Index)", value=5)

    st.divider()
    st.subheader("🛫 Airport / Origin")
    origin_mode = st.radio(
        "ระบุต้นทาง (Origin Source)", ["Fix Value (ระบุเอง)", "From Column (อ่านจากไฟล์)"]
    )

    selected_origin = "Unspecified"
    c_origin = -1

    if origin_mode == "Fix Value (ระบุเอง)":
        selected_origin = st.radio(
            "เลือกสนามบิน:", ["BKK (Suvarnabhumi)", "DMK (Don Mueang)"]
        )
    else:
        c_origin = st.number_input("Col: Origin/Airport (Index)", min_value=0, value=6)

    show_raw = st.checkbox("Show Raw Data for Debugging")


# --- Helper: Fetch Drivers from Local CSV ---
@st.cache_data(ttl=600)
def fetch_drivers():
    try:
        # Check if local CSV exists
        csv_path = "WarRoom - Master_Cars.csv"
        try:
            df_drivers = pd.read_csv(csv_path)
            # Expected columns: License_Plate, Driver_Name, Phone, Station (Optional)

            # Standardize Station names if exists
            if "Station" in df_drivers.columns:
                df_drivers["Station"] = (
                    df_drivers["Station"].astype(str).str.upper().str.strip()
                )
            else:
                df_drivers["Station"] = "ANY"  # Default if not specified

            return df_drivers.to_dict("records")
        except FileNotFoundError:
            st.warning(f"⚠️ ไม่พบไฟล์ {csv_path} ในโฟลเดอร์เดียวกัน")
            return []
        except Exception as e:
            st.error(f"❌ Error reading {csv_path}: {e}")
            return []
    except Exception as e:
        st.error(f"❌ Failed to fetch drivers: {str(e)}")
        return []


# --- Helper: Bin Packing Algorithm ---
def optimize_transport(flight_data, max_cap):
    """
    Returns a list of trucks:
    [
      {'truck_id': 1, 'flight': 'GA-123', 'stops': ['Hotel A', 'Hotel B'], 'items': 28, 'details': [...]}
    ]
    """
    trucks = []

    # 1. Group by Destination
    dest_groups = []

    # Get representative Info (Country, Group) from the first row of this flight block
    # Note: flight_data is already filtered for one specific Flight+Time

    for _, row in flight_data.iterrows():
        d = str(row["Destination"]).strip()

        # Handle Empty/Nan/#N/A Destination -> "Other"
        # Includes standard pandas NaN string "nan" and Excel error "#n/a"
        if d.lower() in ["nan", "", "none", "nat", "#n/a"]:
            d = "Other"

        qty = row["Total_Items"]
        if qty > 0:
            dest_groups.append({"dest": d, "qty": qty, "group": row.get("Group", "-")})

    # Sort by quantity descending (Greedy approach)
    dest_groups.sort(key=lambda x: x["qty"], reverse=True)

    for item in dest_groups:
        qty_left = item["qty"]

        # Strategy: Fill full trucks for this destination first
        while qty_left >= max_cap:
            trucks.append(
                {
                    "stops": {item["dest"]},
                    "items": max_cap,
                    "load": [
                        {"dest": item["dest"], "qty": max_cap, "group": item["group"]}
                    ],
                    "multi_drop": False,
                }
            )
            qty_left -= max_cap

        if qty_left > 0:
            # Try to fit remainder in existing open trucks
            placed = False
            for truck in trucks:
                space = max_cap - truck["items"]
                if space >= qty_left:
                    truck["stops"].add(item["dest"])
                    truck["items"] += qty_left
                    truck["load"].append(
                        {"dest": item["dest"], "qty": qty_left, "group": item["group"]}
                    )
                    truck["multi_drop"] = len(truck["stops"]) > 1
                    placed = True
                    break

            if not placed:
                trucks.append(
                    {
                        "stops": {item["dest"]},
                        "items": qty_left,
                        "load": [
                            {
                                "dest": item["dest"],
                                "qty": qty_left,
                                "group": item["group"],
                            }
                        ],
                        "multi_drop": False,
                    }
                )

    return trucks


# --- Main Logic ---
if uploaded_file:
    try:
        # Load Excel File (Wrapper to get sheet names)
        xl_file = pd.ExcelFile(uploaded_file)
        sheet_names = xl_file.sheet_names

        with st.sidebar:
            st.divider()
            selected_sheet = st.selectbox("เลือก Tab (Sheet)", sheet_names, index=0)

        # Read Excel
        # Use user-defined header row (default 9)
        df = pd.read_excel(
            uploaded_file, sheet_name=selected_sheet, header=header_row_idx
        )

        # Load Drivers
        drivers_list = fetch_drivers()

        if show_raw:
            st.warning("🔧 Debug Mode: Showing first 20 rows of raw data")
            st.dataframe(df.head(20))
            st.write("Columns found:", df.columns.tolist())
            if layout_mode == "Detailed Breakdown (แยกประเภทของ)":
                st.write(
                    f"Trying to read Destination from Column Index: {dest_col_idx}"
                )
            st.write(f"Drivers Loaded: {len(drivers_list)}")

        # --- DATA EXTRACTION ---
        normalized_data = None

        if layout_mode == "Detailed Breakdown (แยกประเภทของ)":
            # Column Indices Mapping
            # [1, 2, 3, 4, 9, 11, 12, 13, 14] + Destination
            req_indices = [1, 2, 3, 4, 9, 11, 12, 13, 14, dest_col_idx]

            # Validate bounds
            if max(req_indices) >= len(df.columns):
                st.error(
                    f"❌ Column Index {max(req_indices)} out of bounds. File has {len(df.columns)} columns."
                )
                st.stop()

            # Extract
            data = df.iloc[1:, req_indices].copy()
            data.columns = [
                "No",
                "Date",
                "Flight",
                "Time",
                "Group",
                "WC_Man",
                "WC_Elec",
                "Luggage",
                "Sport_Eq",
                "Destination",
            ]

            # Use Sheet Name as Country for Detailed Mode
            data["Country"] = selected_sheet

            # Handle Origin
            if origin_mode == "Fix Value (ระบุเอง)":
                data["Origin"] = selected_origin
            else:
                if c_origin < len(df.columns):
                    data["Origin"] = df.iloc[1:, c_origin].astype(str)
                else:
                    data["Origin"] = "Unknown"

            # Filter NA
            data = data.dropna(subset=["Flight", "Time"])

            # Clean Numerics
            def clean_num(x):
                try:
                    if pd.isna(x) or str(x).strip() in ["-", "", "nan"]:
                        return 0
                    return float(x)
                except:
                    return 0

            for c in ["WC_Man", "WC_Elec", "Luggage", "Sport_Eq"]:
                data[c] = data[c].apply(clean_num)

            # Calc Total
            data["Total_Items"] = (
                data["Luggage"] + data["Sport_Eq"] + data["WC_Man"] + data["WC_Elec"]
            )
            normalized_data = data

        else:
            # --- SIMPLE LIST MODE ---
            # Select columns by user index (Country, Date, Flight, Time, Hotel, Qty)
            # Need to handle dynamic Origin col if selected

            target_cols = [c_country, c_date, c_flight, c_time, c_hotel, c_qty]
            if origin_mode == "From Column (อ่านจากไฟล์)":
                target_cols.append(c_origin)

            if max(target_cols) >= len(df.columns):
                st.error(
                    f"❌ Column Index exceeds file width ({len(df.columns)} cols). Check settings."
                )
                st.stop()

            # Careful extraction
            data_extracted = df.iloc[:, target_cols].copy()

            # Rename columns
            base_names = [
                "Country",
                "Date",
                "Flight",
                "Time",
                "Destination",
                "Total_Items",
            ]
            if origin_mode == "From Column (อ่านจากไฟล์)":
                base_names.append("Origin")

            data_extracted.columns = base_names

            if origin_mode == "Fix Value (ระบุเอง)":
                data_extracted["Origin"] = selected_origin

            # Cleaning
            data = data_extracted.dropna(subset=["Flight", "Total_Items"])
            data["Total_Items"] = pd.to_numeric(
                data["Total_Items"], errors="coerce"
            ).fillna(0)
            data["Group"] = "-"  # Optional placeholder
            normalized_data = data

        data = normalized_data

        # --- Algorithm Calculation ---

        all_trucks = []

        # Parse Time for Sorting (Attempt standard formats)
        try:
            data["Time_Str"] = (
                data["Time"]
                .astype(str)
                .str.replace(r"(\d+:\d+):\d+", r"\1", regex=True)
            )
        except:
            data["Time_Str"] = data["Time"]

        # Group by Flight/Time/Country AND ORIGIN to optimize per batch

        # Prepare Driver Pools
        drivers_by_station = {}
        for d in drivers_list:
            s = d.get("Station", "ANY")
            if s not in drivers_by_station:
                drivers_by_station[s] = []
            drivers_by_station[s].append(d)

        # Indices for round-robin per station
        station_indices = {k: 0 for k in drivers_by_station.keys()}

        # Fallback pool (ANY)
        pool_any = drivers_by_station.get("ANY", [])
        idx_any = 0

        # Sort Groups
        data["Sort_Key"] = data["Time"].astype(str)
        sorted_groups = data.groupby(
            ["Origin", "Country", "Date", "Sort_Key", "Flight", "Time"]
        )

        current_truck_global_id = 0

        for keys, group_df in sorted_groups:
            # keys: (Origin, Country, Date, Sort_Key, Flight, Time)
            origin_raw = str(group_df["Origin"].iloc[0]).strip().upper()
            # Map Origin to Station keys (simple logic: check if BKK/DMK is in string)
            station_key = "ANY"
            if "BKK" in origin_raw:
                station_key = "BKK"
            elif "DMK" in origin_raw:
                station_key = "DMK"

            # If exact match exists in CSV stations, use it
            if origin_raw in drivers_by_station:
                station_key = origin_raw

            country = group_df["Country"].iloc[0]
            date = group_df["Date"].iloc[0]
            time = group_df["Time"].iloc[0]
            flight = group_df["Flight"].iloc[0]

            trucks = optimize_transport(group_df, bags_per_truck)

            for t in trucks:
                current_truck_global_id += 1
                t["Origin"] = group_df["Origin"].iloc[0]
                t["Date"] = date
                t["Time"] = time
                t["Flight"] = flight
                t["Country"] = country
                t["Stops_Str"] = " + ".join(sorted(list(t["stops"])))

                # Assign Driver Logic
                selected_driver = None

                # 1. Try Specific Station Pool
                if (
                    station_key in drivers_by_station
                    and drivers_by_station[station_key]
                ):
                    pool = drivers_by_station[station_key]
                    idx = station_indices[station_key]
                    selected_driver = pool[idx % len(pool)]
                    station_indices[station_key] += 1

                # 2. Try 'ANY' Pool if not found
                elif pool_any:
                    selected_driver = pool_any[idx_any % len(pool_any)]
                    idx_any += 1

                # Assign
                if selected_driver:
                    t["Car_Plate"] = selected_driver.get("License_Plate", "-")
                    t["Driver"] = selected_driver.get("Driver_Name", "-")
                    t["Phone"] = str(selected_driver.get("Phone", "-"))
                else:
                    t["Car_Plate"] = "No Driver"
                    t["Driver"] = "-"
                    t["Phone"] = "-"

                all_trucks.append(t)

        truck_df = pd.DataFrame(all_trucks)

        # --- Dashboard ---
        st.divider()

        # Metrics
        total_items_all = data["Total_Items"].sum()
        total_trucks_all = len(truck_df)
        multi_drop_count = len(truck_df[truck_df["multi_drop"] == True])

        m1, m2, m3, m4 = st.columns(4)
        m1.metric("📦 Total Items", f"{int(total_items_all):,}")
        m2.metric("🚛 Total Trucks", f"{int(total_trucks_all):,}")
        m3.metric(
            "🔄 Multi-Drop Trucks",
            f"{multi_drop_count}",
            delta="Sharing",
            delta_color="inverse",
        )
        m4.metric("🎯 Flights", data["Flight"].nunique())

        st.divider()

        # --- NEW: OPERATION PLAN TABLE ---
        st.subheader("📋 Operation Transport Plan (ตารางแผนปฏิบัติงาน)")
        st.caption("จัดเรียงตามเวลาเครื่องลง (Arrival Time) | สำหรับ Staff หน้างาน")

        # Driver Status Indicator
        if len(drivers_list) > 0:
            st.success(
                f"✅ เชื่อมต่อข้อมูลรถสำเร็จ: พบ {len(drivers_list)} คัน (จาก Master_Cars)"
            )
        else:
            st.warning(
                "⚠️ ไม่พบข้อมูลรถในระบบ (Master_Cars) หรือเชื่อมต่อไม่ได้ -> แสดงผลเป็น 'No Data'"
            )

        if not truck_df.empty:
            # Prepare Operational Table
            op_table = truck_df.copy()

            # Format Time nicely
            def format_time_display(val):
                s = str(val)
                # Try to clean if it looks like default pandas string output
                if "days" in s:  # e.g. "0 days 07:50:00.000000000"
                    try:
                        # Extract time part
                        import re

                        match = re.search(r"\d{2}:\d{2}:\d{2}", s)
                        if match:
                            return match.group(0)
                    except:
                        pass
                # Try standard splits if it's HH:MM:SS
                if ":" in s:
                    parts = s.split(":")
                    if len(parts) >= 2:
                        return f"{parts[0].zfill(2)}:{parts[1].zfill(2)}"
                return s

            op_table["Time_Display"] = op_table["Time"].apply(format_time_display)

            # Sort by Time
            op_table["Sort_Key"] = op_table["Time"].astype(str)
            op_table = op_table.sort_values(by=["Date", "Sort_Key"])

            op_table["Type"] = op_table["multi_drop"].apply(
                lambda x: "🟡 Shared" if x else "🟢 Direct"
            )

            # Select and Rename Cols
            # Use Time_Display instead of Raw Time
            display_cols = [
                "Origin",
                "Time_Display",
                "Flight",
                "Country",
                "Stops_Str",
                "items",
                "Car_Plate",
                "Driver",
                "Phone",
            ]

            # Ensure cols exist (Handle renaming)
            final_cols = []
            for c in display_cols:
                if c == "Time_Display":
                    final_cols.append(c)
                elif c in op_table.columns:
                    final_cols.append(c)

            op_table = op_table[final_cols]

            # Display
            st.dataframe(
                op_table,
                use_container_width=True,
                height=500,
                column_config={
                    "Origin": st.column_config.TextColumn("🛫 Origin", width="small"),
                    "Time_Display": st.column_config.TextColumn(
                        "⏰ Time", width="small"
                    ),
                    "Flight": st.column_config.TextColumn("✈️ Flight", width="small"),
                    "Country": st.column_config.TextColumn("🏳️ Country", width="small"),
                    "Stops_Str": st.column_config.TextColumn(
                        "🏨 Destination / Hotels", width="large"
                    ),
                    "items": st.column_config.ProgressColumn(
                        "📦 Load",
                        min_value=0,
                        max_value=bags_per_truck,
                        format="%d",
                        width="small",
                    ),
                    "Car_Plate": st.column_config.TextColumn(
                        "🚛 License Plate", width="medium"
                    ),
                    "Driver": st.column_config.TextColumn("👨‍✈️ Driver", width="medium"),
                    "Phone": st.column_config.TextColumn("📞 Phone", width="medium"),
                },
                hide_index=True,
            )

            # Export CSV
            csv = op_table.to_csv(index=False).encode("utf-8")
            st.download_button(
                "📥 Download Operation Plan (CSV)",
                csv,
                "operation_plan.csv",
                "text/csv",
                key="download-op-csv",
            )

        else:
            st.info("No data to display.")

        st.divider()

        # (Below is Analysis Section - kept for analytics view)
        col_main, col_detail = st.columns([1.5, 1])

        with col_main:
            st.subheader("� Trucks Details (รายคัน)")
            if not truck_df.empty:
                # ... (Existing logic for Truck Manifest if needed, or remove if redundancy is confusing)
                # Let's keep it but maybe collapse it
                pass

            if not truck_df.empty:
                display_trucks = truck_df[
                    ["Date", "Time", "Flight", "Stops_Str", "items", "multi_drop"]
                ].copy()
                display_trucks["Type"] = display_trucks["multi_drop"].apply(
                    lambda x: "🟡 Multi-Drop" if x else "🟢 Direct"
                )

                st.dataframe(
                    display_trucks.sort_values(by=["Date", "Time", "Flight"]),
                    use_container_width=True,
                    column_config={
                        "multi_drop": st.column_config.CheckboxColumn("Multi"),
                        "items": st.column_config.ProgressColumn(
                            "Capacity",
                            min_value=0,
                            max_value=bags_per_truck,
                            format="%d items",
                        ),
                    },
                )
            else:
                st.info("No data to display.")

        with col_detail:
            st.subheader("📊 Route Analysis")
            if not truck_df.empty:
                type_counts = truck_df["multi_drop"].value_counts()
                type_counts.index = [
                    "Multi-Drop" if x else "Single-Drop" for x in type_counts.index
                ]

                fig_type = px.pie(
                    values=type_counts.values,
                    names=type_counts.index,
                    title="Truck Type Ratio",
                    hole=0.4,
                    color_discrete_map={
                        "Multi-Drop": "#E67E22",
                        "Single-Drop": "#27AE60",
                    },
                )
                st.plotly_chart(fig_type, use_container_width=True)

                # List Multi-Drop Details
                if multi_drop_count > 0:
                    st.warning(f"⚠️ พบรถต้องส่งหลายจุด {multi_drop_count} คัน:")
                    multi_trucks = truck_df[truck_df["multi_drop"] == True]
                    for i, r in multi_trucks.iterrows():
                        st.markdown(
                            f"**{r['Flight']}**: {r['Stops_Str']} ({int(r['items'])} items)"
                        )

        # Detailed Original Data
        with st.expander("📄 See Original Flight Data"):
            st.dataframe(data)

    except Exception as e:
        st.error(f"❌ Error processing file: {e}")
        st.expander("See details").write(e)

else:
    # Empty State
    st.info("👆 Please upload the Excel file in the sidebar to begin.")

    st.markdown(
        """
    ### ℹ️ Instructions
    1. Export your plan as **.xlsx**
    2. Ensure the format matches the standard layout (Header at Row 10)
    3. Upload to see the calculated truck requirements.
    """
    )
