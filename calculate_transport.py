import pandas as pd
import math

# Load Data
file_path = "บริษัท สะมะดุน จำกัด (สำนักงานใหญ่) REV2  ทุน.xlsx"
df = pd.read_excel(file_path, header=9)  # Row 10 is header (0-indexed 9)

# Clean Columns
# Actual columns based on previous `print(df.to_markdown())` view:
# Col 2: Date (Arrival)
# Col 4: Time (Arrival)
# Col 3: Flight Code (Arrival)
# Col 13: Lugguge
# Col 14: Sport Equipment (Oversize)
# Col 11: Wheelchair Manual
# Col 12: Wheelchair Battery
# Col 9: NPC/Group

# Select relevant columns and rename
# Note: The structure has Arrival and Departure side by side.
# Let's handle ARRIVAL first (Cols 1-5 ish) and counts (Cols 11-14).
# Wait, look at the markdown again.
# Row 9 (Header) has:
# Col 2: ARRIVAL (Date under it?) -> No, Row 10+ has values.
# Col 3: FLIGHT CODE
# Col 4: TIMING
# Counts seem to be in Col 11 (Manual), 12 (Battery), 13 (Personal), 14 (Sport Eq).
# These counts seem to apply to the row.

# Let's extract the arrival schedule rows
data = df.iloc[1:, [1, 2, 3, 4, 9, 11, 12, 13, 14]].copy()
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
]

# Filter valid rows (has flight info)
data = data.dropna(subset=["Flight", "Time"])


# Clean numeric columns
def clean_num(x):
    try:
        if pd.isna(x) or x == "-":
            return 0
        return float(x)
    except:
        return 0


for col in ["WC_Man", "WC_Elec", "Luggage", "Sport_Eq"]:
    data[col] = data[col].apply(clean_num)

# Calculate Total Items
data["Total_Items"] = (
    data["Luggage"] + data["Sport_Eq"] + data["WC_Man"] + data["WC_Elec"]
)

# Aggregate by Flight
agg_df = (
    data.groupby(["Date", "Time", "Flight"])
    .agg(
        {
            "Group": lambda x: ", ".join(set(str(v) for v in x if pd.notnull(v))),
            "Total_Items": "sum",
            "Luggage": "sum",
            "Sport_Eq": "sum",
            "WC_Man": "sum",
            "WC_Elec": "sum",
        }
    )
    .reset_index()
)

# Calculate Trucks Needed (Max 30 items)
BAGS_PER_TRUCK = 30
agg_df["Trucks_Needed"] = agg_df["Total_Items"].apply(
    lambda x: math.ceil(x / BAGS_PER_TRUCK)
)

# Format Output
agg_df["Date"] = pd.to_datetime(agg_df["Date"], errors="coerce").dt.strftime("%Y-%m-%d")
agg_df = agg_df.sort_values(by=["Date", "Time"])

print(
    agg_df[
        ["Date", "Time", "Flight", "Group", "Total_Items", "Trucks_Needed"]
    ].to_markdown(index=False)
)
