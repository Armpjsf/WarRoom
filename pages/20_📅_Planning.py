import streamlit as st
import pandas as pd
import math
import plotly.express as px

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
        c_date = st.number_input("Col: Date (Index)", value=1)
        c_flight = st.number_input("Col: Flight (Index)", value=2)
        c_time = st.number_input("Col: Time (Index)", value=3)
        c_hotel = st.number_input("Col: Hotel/Dest (Index)", value=4)
        c_qty = st.number_input("Col: Total Qty (Index)", value=5)

    show_raw = st.checkbox("Show Raw Data for Debugging")


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
    # content: { 'Dest A': total_items, 'Dest B': total_items }
    # We need granular items actually?
    # For simulation, we treat items as bulk per destination for now.

    dest_groups = []
    for _, row in flight_data.iterrows():
        d = str(row["Destination"]).strip()

        # Handle Empty/Nan Destination -> "Unknown"
        if d.lower() in ["nan", "", "none", "nat"]:
            d = "Unassigned Hotel"

        qty = row["Total_Items"]
        if qty > 0:
            dest_groups.append({"dest": d, "qty": qty, "group": row.get("Group", "-")})

    # Sort by quantity descending (Greedy approach)
    dest_groups.sort(key=lambda x: x["qty"], reverse=True)

    for item in dest_groups:
        qty_left = item["qty"]

        # Try to fit into existing trucks first (Multi-drop)
        # Prioritize trucks that have space and ideally SAME destination (logic: keep single drop if possible)
        # But user wants to know multi-drops.

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
                    # Add to this truck
                    truck["stops"].add(item["dest"])
                    truck["items"] += qty_left
                    truck["load"].append(
                        {"dest": item["dest"], "qty": qty_left, "group": item["group"]}
                    )
                    truck["multi_drop"] = len(truck["stops"]) > 1
                    placed = True
                    break

            if not placed:
                # New Truck
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

        if show_raw:
            st.warning("🔧 Debug Mode: Showing first 20 rows of raw data")
            st.dataframe(df.head(20))
            st.write("Columns found:", df.columns.tolist())
            if layout_mode == "Detailed Breakdown (แยกประเภทของ)":
                st.write(
                    f"Trying to read Destination from Column Index: {dest_col_idx}"
                )

        # --- DATA EXTRACTION ---
        if layout_mode == "Detailed Breakdown (แยกประเภทของ)":
            # Column Indices Mapping
            # [1, 2, 3, 4, 9, 11, 12, 13, 14] + Destination
            # Using iloc is risky if columns shift.
            # But sticking to user logic for now.

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

        else:
            # --- SIMPLE LIST MODE ---
            # Select columns by user index (Date, Flight, Time, Hotel, Qty)
            target_cols = [c_date, c_flight, c_time, c_hotel, c_qty]
            if max(target_cols) >= len(df.columns):
                st.error(
                    f"❌ Column Index exceeds file width ({len(df.columns)} cols). Check settings."
                )
                st.stop()

            data = df.iloc[:, target_cols].copy()
            data.columns = ["Date", "Flight", "Time", "Destination", "Total_Items"]

            # Cleaning
            data = data.dropna(subset=["Flight", "Total_Items"])
            data["Total_Items"] = pd.to_numeric(
                data["Total_Items"], errors="coerce"
            ).fillna(0)
            data["Group"] = "-"  # Optional placeholder

        # --- Algorithm Calculation ---

        all_trucks = []

        # Group by Flight/Time to optimize per batch
        for (date, time, flight), group_df in data.groupby(["Date", "Time", "Flight"]):
            trucks = optimize_transport(group_df, bags_per_truck)
            for t in trucks:
                t["Date"] = date
                t["Time"] = time
                t["Flight"] = flight
                t["Stops_Str"] = ", ".join(sorted(list(t["stops"])))
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

        col_main, col_detail = st.columns([1.5, 1])

        with col_main:
            st.subheader("🚛 Truck Manifest (รายคัน)")

            if not truck_df.empty:
                # Format for display
                display_trucks = truck_df[
                    ["Date", "Time", "Flight", "Stops_Str", "items", "multi_drop"]
                ].copy()
                display_trucks["Type"] = display_trucks["multi_drop"].apply(
                    lambda x: "🟡 Multi-Drop" if x else "🟢 Direct"
                )

                # Highlight Multi-Drop
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
                # Pie Chart: Direct vs Multi
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
