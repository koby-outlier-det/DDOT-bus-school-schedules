#!/usr/bin/env python
# coding: utf-8

# In[31]:


# ============================================================
# DETROIT HIGH SCHOOLS + 4 NEAREST DDOT STOPS + SCHEDULE TIMES
# ============================================================

import geopandas as gpd
import pandas as pd
import requests


# ------------------------------------------------------------
# 1. Load source files
# ------------------------------------------------------------

schools = gpd.read_file("Original/schools.geojson")
bus_stops = gpd.read_file("Original/bus_stops.geojson")
bell_schedule = pd.read_csv("Original/DPSCD BELL SCHEDULE.csv")


# ------------------------------------------------------------
# 2. Filter schools
# ------------------------------------------------------------

excluded_schools = [
    "DPSCD Virtual School",
    "Jerry L. White Center",
    "Turning Point Academy"
]

schools = schools[
    schools["GRADE_LEVELS"].astype(str).str.contains("9", na=False) &
    schools["GRADE_LEVELS"].astype(str).str.contains("10", na=False) &
    schools["GRADE_LEVELS"].astype(str).str.contains("11", na=False) &
    schools["GRADE_LEVELS"].astype(str).str.contains("12", na=False) &
    (schools["ENTITY_TYPE"].astype(str).str.strip() == "LEA School") &
    (~schools["ENTITY_NAME"].astype(str).str.strip().isin(excluded_schools))
].copy()


# ------------------------------------------------------------
# 3. Rename fields for consistency
# ------------------------------------------------------------

schools = schools.rename(columns={
    "ENTITY_ID": "school_id",
    "ENTITY_NAME": "school_name"
})

bus_stops = bus_stops.rename(columns={
    "location": "bus_stop_name"
})

schools["school_id"] = schools["school_id"].astype(str)
bus_stops["bus_stop_id"] = bus_stops["bus_stop_id"].astype(str)


# ------------------------------------------------------------
# 4. Merge bell schedule onto schools
#
# The bell schedule CSV has:
# - SCHOOL
# - START TIME
# - END TIME
#
# We merge SCHOOL to school_name.
# ------------------------------------------------------------

def hm_to_minutes(value):
    """Convert H:M or HH:MM string to minutes after midnight."""
    if pd.isna(value):
        return pd.NA

    parts = str(value).strip().split(":")
    hours = int(parts[0])
    minutes = int(parts[1])

    return hours * 60 + minutes


bell_schedule = bell_schedule.rename(columns={
    "SCHOOL": "school_name",
    "START TIME": "school_start_time",
    "END TIME": "school_end_time"
})

bell_schedule["school_name"] = bell_schedule["school_name"].astype(str).str.strip()
schools["school_name"] = schools["school_name"].astype(str).str.strip()

bell_schedule["school_start_min"] = bell_schedule["school_start_time"].apply(hm_to_minutes)
bell_schedule["school_end_min"] = bell_schedule["school_end_time"].apply(hm_to_minutes)

schools = schools.merge(
    bell_schedule[[
        "school_name",
        "school_start_time",
        "school_end_time",
        "school_start_min",
        "school_end_min"
    ]],
    on="school_name",
    how="left"
)

missing_bell_times = schools[
    schools["school_start_min"].isna() |
    schools["school_end_min"].isna()
]["school_name"].tolist()

if missing_bell_times:
    print("WARNING: Missing bell times for these schools:")
    print(missing_bell_times)


# ------------------------------------------------------------
# 5. Project to local CRS for accurate distance calculations
# ------------------------------------------------------------

schools = schools.to_crs("EPSG:4326")
bus_stops = bus_stops.to_crs("EPSG:4326")

schools_m = schools.to_crs("EPSG:26917")
bus_stops_m = bus_stops.to_crs("EPSG:26917")


# ------------------------------------------------------------
# 6. Find the 4 nearest bus stops per school
#
# Bell times are carried forward here so each school-stop pair
# has its own start/end time.
# ------------------------------------------------------------

school_stop_pairs = []

for _, school in schools_m.iterrows():
    distances = bus_stops_m.geometry.distance(school.geometry)

    nearest_indices = distances.nsmallest(4).index

    nearest_stops = bus_stops_m.loc[nearest_indices].copy()
    nearest_stops["school_id"] = school["school_id"]
    nearest_stops["school_name"] = school["school_name"]
    nearest_stops["school_start_time"] = school["school_start_time"]
    nearest_stops["school_end_time"] = school["school_end_time"]
    nearest_stops["school_start_min"] = school["school_start_min"]
    nearest_stops["school_end_min"] = school["school_end_min"]
    nearest_stops["school_geometry"] = school.geometry
    nearest_stops["distance_m"] = distances.loc[nearest_indices].values
    nearest_stops["nearest_stop_rank"] = range(1, len(nearest_stops) + 1)

    school_stop_pairs.append(nearest_stops)

nearest_stops = pd.concat(school_stop_pairs, ignore_index=True)

nearest_stops = nearest_stops[[
    "school_id",
    "school_name",
    "school_start_time",
    "school_end_time",
    "school_start_min",
    "school_end_min",
    "bus_stop_id",
    "bus_stop_name",
    "direction",
    "route_number",
    "route_name",
    "distance_m",
    "nearest_stop_rank",
    "geometry",
    "school_geometry"
]].copy()

nearest_stops["bus_stop_code"] = (
    nearest_stops["bus_stop_id"]
    .astype(str)
    .str.strip()
    .str.replace(r"\.0$", "", regex=True)
)


# ------------------------------------------------------------
# 7. Helper functions for DDOT schedule processing
# ------------------------------------------------------------

def time_to_minutes(t):
    """Convert DDOT time object to minutes after midnight."""
    if not t:
        return None

    return (
        t.get("hours", 0) * 60
        + t.get("minutes", 0)
        + t.get("seconds", 0) / 60
    )


def minutes_to_hhmm(minutes):
    """Convert minutes after midnight to HH:MM without rounding up."""
    if pd.isna(minutes):
        return None

    minutes = int(minutes)  # floors instead of rounds
    return f"{minutes // 60:02d}:{minutes % 60:02d}"


# ------------------------------------------------------------
# 8. Fetch DDOT stop schedules for all nearest stops
# ------------------------------------------------------------

all_stop_times = []

unique_stop_codes = sorted(nearest_stops["bus_stop_code"].dropna().unique())

for stop_code in unique_stop_codes:
    url = f"https://ddot.info/page-data/stop/{stop_code}/page-data.json"

    print(f"Fetching stop {stop_code}...")

    response = requests.get(url, timeout=30)

    if response.status_code != 200:
        print(f"  Skipping stop {stop_code}: HTTP {response.status_code}")
        continue

    data = response.json()

    stop_data = (
        data.get("result", {})
        .get("data", {})
        .get("postgres", {})
        .get("stop", {})
    )

    for item in stop_data.get("times", []):
        trip = item.get("trip", {})
        route = trip.get("route", {})

        route_number = str(route.get("routeShortName"))
        route_name = route.get("routeLongName")
        direction_id = trip.get("directionId")
        service_id = str(trip.get("serviceId"))

        # Keep weekday service only.
        # Based on your validation, service_id 2 is weekday.
        if service_id != "2":
            continue

        arrival_time = (
            item.get("arrivalTime")
            or item.get("departureTime")
            or item.get("time")
        )

        arrival_min = time_to_minutes(arrival_time)

        all_stop_times.append({
            "bus_stop_code": stop_code,
            "ddot_stop_id": str(stop_data.get("stopId")),
            "ddot_stop_name": stop_data.get("stopName"),
            "route_number_api": route_number,
            "route_name_api": route_name,
            "trip_id": trip.get("tripId"),
            "headsign": trip.get("tripHeadsign"),
            "direction_id": direction_id,
            "service_id": service_id,
            "arrival_min": arrival_min,
            "arrival_seconds": arrival_time.get("seconds", 0),
            "arrival_time": minutes_to_hhmm(arrival_min)
        })

stop_times = pd.DataFrame(all_stop_times)


# ------------------------------------------------------------
# 9. Remove duplicate scheduled arrivals
# ------------------------------------------------------------

stop_times = stop_times.drop_duplicates(
    subset=[
        "bus_stop_code",
        "route_number_api",
        "direction_id",
        "arrival_min"
    ]
).copy()

print("Scheduled rows:", len(stop_times))
print("Stops with schedule data:", stop_times["bus_stop_code"].nunique())


# ------------------------------------------------------------
# 10. Create school-stop-specific schedule candidate table
#
# This is the key change:
# timing is now calculated relative to each school's own bell time,
# not one global 8:00 / 3:20 schedule.
# ------------------------------------------------------------

schedule_candidates = nearest_stops[[
    "school_id",
    "school_name",
    "bus_stop_code",
    "school_start_time",
    "school_end_time",
    "school_start_min",
    "school_end_min"
]].merge(
    stop_times,
    on="bus_stop_code",
    how="left"
)


# ------------------------------------------------------------
# 11. Morning timing
#
# For each school + stop + direction:
# - find the last bus before that school's start time
# - then find the previous bus on that same route
# ------------------------------------------------------------

morning_times = schedule_candidates[
    schedule_candidates["arrival_min"] <= schedule_candidates["school_start_min"]
].copy()

morning_times = morning_times.sort_values([
    "school_id",
    "bus_stop_code",
    "direction_id",
    "arrival_min"
])

last_bus = (
    morning_times
    .groupby(["school_id", "bus_stop_code", "direction_id"])
    .tail(1)
    .copy()
)

previous_candidates = morning_times.merge(
    last_bus[[
        "school_id",
        "bus_stop_code",
        "direction_id",
        "route_number_api",
        "arrival_min"
    ]].rename(columns={
        "arrival_min": "chosen_arrival_min"
    }),
    on=["school_id", "bus_stop_code", "direction_id", "route_number_api"],
    how="inner"
)

previous_candidates = previous_candidates[
    previous_candidates["arrival_min"] < previous_candidates["chosen_arrival_min"]
]

previous_bus = (
    previous_candidates
    .sort_values([
        "school_id",
        "bus_stop_code",
        "direction_id",
        "arrival_min"
    ])
    .groupby(["school_id", "bus_stop_code", "direction_id"])
    .tail(1)
    [[
        "school_id",
        "bus_stop_code",
        "direction_id",
        "arrival_min",
        "arrival_time"
    ]]
    .rename(columns={
        "arrival_min": "previous_arrival_min",
        "arrival_time": "previous_bus_before_start"
    })
)

morning_schedule = last_bus.merge(
    previous_bus,
    on=["school_id", "bus_stop_code", "direction_id"],
    how="left"
)

morning_schedule["minutes_before_start"] = (
    morning_schedule["school_start_min"] - morning_schedule["arrival_min"]
)

morning_schedule["gap_since_previous_bus_am"] = (
    morning_schedule["arrival_min"] - morning_schedule["previous_arrival_min"]
)

morning_schedule = morning_schedule.rename(columns={
    "arrival_time": "last_bus_before_start",
    "route_number_api": "morning_route_number",
    "route_name_api": "morning_route_name",
    "headsign": "morning_headsign",
    "trip_id": "morning_trip_id"
})

morning_schedule = morning_schedule[[
    "school_id",
    "bus_stop_code",
    "direction_id",
    "last_bus_before_start",
    "minutes_before_start",
    "previous_bus_before_start",
    "gap_since_previous_bus_am",
    "morning_route_number",
    "morning_route_name",
    "morning_headsign",
    "morning_trip_id"
]]


# ------------------------------------------------------------
# 12. Afternoon timing
#
# For each school + stop + direction:
# - find the first bus after that school's end time
# - then find the next bus on that same route
# ------------------------------------------------------------

afternoon_times = schedule_candidates[
    schedule_candidates["arrival_min"] >= schedule_candidates["school_end_min"]
].copy()

afternoon_times = afternoon_times.sort_values([
    "school_id",
    "bus_stop_code",
    "direction_id",
    "arrival_min"
])

first_bus = (
    afternoon_times
    .groupby(["school_id", "bus_stop_code", "direction_id"])
    .head(1)
    .copy()
)

next_candidates = afternoon_times.merge(
    first_bus[[
        "school_id",
        "bus_stop_code",
        "direction_id",
        "route_number_api",
        "arrival_min"
    ]].rename(columns={
        "arrival_min": "chosen_arrival_min"
    }),
    on=["school_id", "bus_stop_code", "direction_id", "route_number_api"],
    how="inner"
)

next_candidates = next_candidates[
    next_candidates["arrival_min"] > next_candidates["chosen_arrival_min"]
]

next_bus = (
    next_candidates
    .sort_values([
        "school_id",
        "bus_stop_code",
        "direction_id",
        "arrival_min"
    ])
    .groupby(["school_id", "bus_stop_code", "direction_id"])
    .head(1)
    [[
        "school_id",
        "bus_stop_code",
        "direction_id",
        "arrival_min",
        "arrival_time"
    ]]
    .rename(columns={
        "arrival_min": "next_arrival_min",
        "arrival_time": "next_bus_after_end"
    })
)

afternoon_schedule = first_bus.merge(
    next_bus,
    on=["school_id", "bus_stop_code", "direction_id"],
    how="left"
)

afternoon_schedule["minutes_after_end"] = (
    afternoon_schedule["arrival_min"] - afternoon_schedule["school_end_min"]
)

afternoon_schedule["gap_to_next_bus_pm"] = (
    afternoon_schedule["next_arrival_min"] - afternoon_schedule["arrival_min"]
)

afternoon_schedule = afternoon_schedule.rename(columns={
    "arrival_time": "first_bus_after_end",
    "route_number_api": "afternoon_route_number",
    "route_name_api": "afternoon_route_name",
    "headsign": "afternoon_headsign",
    "trip_id": "afternoon_trip_id"
})

afternoon_schedule = afternoon_schedule[[
    "school_id",
    "bus_stop_code",
    "direction_id",
    "first_bus_after_end",
    "minutes_after_end",
    "next_bus_after_end",
    "gap_to_next_bus_pm",
    "afternoon_route_number",
    "afternoon_route_name",
    "afternoon_headsign",
    "afternoon_trip_id"
]]


# ------------------------------------------------------------
# 13. Combine morning and afternoon timing
# ------------------------------------------------------------

stop_schedule = morning_schedule.merge(
    afternoon_schedule,
    on=["school_id", "bus_stop_code", "direction_id"],
    how="outer"
)

stop_schedule["direction_marker"] = stop_schedule["direction_id"]


# ------------------------------------------------------------
# 14. Merge timing onto the four nearest stops
# ------------------------------------------------------------

school_stop_schedule = nearest_stops.merge(
    stop_schedule,
    on=["school_id", "bus_stop_code"],
    how="left"
)


# ------------------------------------------------------------
# 15. Create Datawrapper rows for schools
# ------------------------------------------------------------

school_rows = school_stop_schedule.copy()

school_rows["point_type"] = "school"
school_rows["title"] = school_rows["school_name"]
school_rows["icon"] = "home-1"
school_rows["color"] = "#c71e1d"
school_rows["geometry"] = school_rows["school_geometry"]


# ------------------------------------------------------------
# 16. Create Datawrapper rows for bus stops
# ------------------------------------------------------------

bus_stop_rows = school_stop_schedule.copy()

bus_stop_rows["point_type"] = "nearest_bus_stop"
bus_stop_rows["title"] = bus_stop_rows["bus_stop_name"]
bus_stop_rows["icon"] = "bus"
bus_stop_rows["color"] = "#1d81a2"



# In[32]:


# ------------------------------------------------------------
# 17. Combine school and bus stop marker rows
# ------------------------------------------------------------

map_output = pd.concat(
    [school_rows, bus_stop_rows],
    ignore_index=True
)

map_output = gpd.GeoDataFrame(
    map_output,
    geometry="geometry",
    crs="EPSG:26917"
)

map_output = map_output.to_crs("EPSG:4326")

map_output["lng"] = map_output.geometry.x
map_output["lat"] = map_output.geometry.y
map_output["scale"] = 1
map_output["anchor"] = "middle-center"


# ------------------------------------------------------------
# 18. Round numeric fields for readability
# ------------------------------------------------------------

for col in [
    "distance_m",
    "minutes_before_start",
    "gap_since_previous_bus_am",
    "minutes_after_end",
    "gap_to_next_bus_pm",
]:
    if col in map_output.columns:
        map_output[col] = map_output[col].round(1)

# ------------------------------------------------------------
# 18b. Add DDOT stop URL for fact-checking
# ------------------------------------------------------------

map_output["ddot_stop_url"] = (
    "https://ddot.info/stop/" + map_output["bus_stop_code"].astype(str)
)


# ------------------------------------------------------------
# 19. Select and order final columns
# ------------------------------------------------------------

final_output = map_output[[
    "lat",
    "lng",
    "title",
    "color",
    "icon",
    "scale",
    "anchor",
    "point_type",
    "school_id",
    "school_name",
    "school_start_time",
    "school_end_time",
    "bus_stop_id",
    "bus_stop_code",
    "bus_stop_name",
    "ddot_stop_url",
    "nearest_stop_rank",
    "distance_m",
    "direction",
    "direction_marker",
    "last_bus_before_start",
    "minutes_before_start",
    "previous_bus_before_start",
    "gap_since_previous_bus_am",
    "morning_route_number",
    "morning_route_name",
    "morning_headsign",
    "morning_trip_id",
    "first_bus_after_end",
    "minutes_after_end",
    "next_bus_after_end",
    "gap_to_next_bus_pm",
    "afternoon_route_number",
    "afternoon_route_name",
    "afternoon_headsign",
    "afternoon_trip_id"
]].copy()

print("Done!")
print("Rows:", len(final_output))
print("Schools:", final_output["school_id"].nunique())
print("Unique bus stops:", final_output["bus_stop_code"].nunique())

# # ------------------------------------------------------------
# # 20. Save one final CSV for Datawrapper
# # ------------------------------------------------------------

# final_output.to_csv(
#     "schools_4_nearest_bus_stops_with_ddot_schedule_for_datawrapper.csv",
#     index=False
# )

# print("Done!")
# print("Created schools_4_nearest_bus_stops_with_ddot_schedule_for_datawrapper.csv")
# print("Rows:", len(final_output))
# print("Schools:", final_output["school_id"].nunique())
# print("Unique bus stops:", final_output["bus_stop_code"].nunique())


# ------------------------------------------------------------
# 20b. *Optional, leave commented out* Slimmer output for DDOT/DPSCD fact checking
# ------------------------------------------------------------

# DDOT_output = map_output[[
#     "school_id",
#     "school_name",
#     "school_start_time",
#     "school_end_time",
#     "bus_stop_id",
#     "bus_stop_code",
#     "bus_stop_name",
#     "ddot_stop_url",
#     "nearest_stop_rank",
#     "distance_m",
#     "direction",
#     "direction_marker",
#     "last_bus_before_start",
#     "minutes_before_start",
#     "previous_bus_before_start",
#     "gap_since_previous_bus_am",
#     "morning_route_number",
#     "morning_route_name",
#     "morning_headsign",
#     "morning_trip_id",
#     "first_bus_after_end",
#     "minutes_after_end",
#     "next_bus_after_end",
#     "gap_to_next_bus_pm",
#     "afternoon_route_number",
#     "afternoon_route_name",
#     "afternoon_headsign",
#     "afternoon_trip_id"
# ]].copy()


# DDOT_output.to_csv(
#     "Fact checking output/schools_4_nearest_bus_stops_with_ddot_schedule.csv",
#     index=False
# )


# In[33]:


# ------------------------------------------------------------
# 21. Analysis flags and summary outputs
# ------------------------------------------------------------

# Analysis variables
CLOSE_BUS_CUTOFF_MIN = 6
LONG_GAP_CUTOFF_MIN = 25
TOO_EARLY_OR_LATE_CUTOFF_MIN = 30

WALKING_SPEED_MPH = 2.5
METERS_PER_MILE = 1609.344
MINUTES_PER_HOUR = 60
WALKING_SPEED_METERS_PER_MIN = (
    WALKING_SPEED_MPH * METERS_PER_MILE / MINUTES_PER_HOUR
)


# ------------------------------------------------------------
# 21a. Filter to school points only
#
# This avoids double-counting because final_output also contains
# bus stop marker rows.
# ------------------------------------------------------------

analysis_df = final_output[
    final_output["point_type"] == "school"
].copy()


# ------------------------------------------------------------
# 21b. Add walking duration
#
# distance_m is meters from school to bus stop.
# walk_duration is minutes, assuming WALKING_SPEED_MPH.
# ------------------------------------------------------------

analysis_df["walk_duration"] = (
    analysis_df["distance_m"] / WALKING_SPEED_METERS_PER_MIN
).round(1)


# ------------------------------------------------------------
# 21c. Add schedule problem flags
#
# AM problem:
# - bus arrives more than 30 minutes before start, OR
# - bus arrives less than 6 minutes before start AND previous bus was >25 minutes earlier
#
# PM problem:
# - bus arrives more than 30 minutes after dismissal, OR
# - bus arrives less than 6 minutes after dismissal AND next bus is >25 minutes later
# ------------------------------------------------------------

analysis_df["am_schedule_problem"] = (
    (analysis_df["minutes_before_start"] > TOO_EARLY_OR_LATE_CUTOFF_MIN) |
    (
        (analysis_df["minutes_before_start"] < CLOSE_BUS_CUTOFF_MIN) &
        (analysis_df["gap_since_previous_bus_am"] > LONG_GAP_CUTOFF_MIN)
    )
)

analysis_df["pm_schedule_problem"] = (
    (analysis_df["minutes_after_end"] > TOO_EARLY_OR_LATE_CUTOFF_MIN) |
    (
        (analysis_df["minutes_after_end"] < CLOSE_BUS_CUTOFF_MIN) &
        (analysis_df["gap_to_next_bus_pm"] > LONG_GAP_CUTOFF_MIN)
    )
)

analysis_df["any_schedule_problem"] = (
    analysis_df["am_schedule_problem"] |
    analysis_df["pm_schedule_problem"]
)

# ------------------------------------------------------------
# 21c-b. Merge analysis fields back into final_output
#
# Safe to rerun: this removes old analysis columns first,
# then merges the updated columns back in.
# This ensures final_output includes flags and walk_duration
# for archiving and downstream use.
# ------------------------------------------------------------

analysis_cols_to_merge = [
    "school_id",
    "bus_stop_code",
    "direction_marker",
    "walk_duration",
    "am_schedule_problem",
    "pm_schedule_problem",
    "any_schedule_problem"
]

analysis_value_cols = [
    "walk_duration",
    "am_schedule_problem",
    "pm_schedule_problem",
    "any_schedule_problem"
]

# If this cell has already been run, these columns may already exist.
# Drop them before merging to avoid _x/_y duplicate-column errors.
final_output = final_output.drop(
    columns=[col for col in analysis_value_cols if col in final_output.columns]
)

final_output = final_output.merge(
    analysis_df[analysis_cols_to_merge],
    on=["school_id", "bus_stop_code", "direction_marker"],
    how="left"
)


# In[36]:


# ------------------------------------------------------------
# 21c-c. Sanity checks for weekday service assumptions
#
# These checks help verify that service_id == "2" is behaving
# like weekday service and that duplicate/non-weekday service
# patterns are not sneaking into the analysis.
# ------------------------------------------------------------


# ------------------------------------------------------------
# Sanity check 1:
# Create a review table with 10 near-school stop schedules.
#
# This gives you:
# - school name
# - stop code
# - DDOT stop URL
# - service ID used
# - first bus after school ends
# - route/headsign context
#
# You can click through the DDOT links and manually confirm that
# these times match the weekday schedule in the web app.
# ------------------------------------------------------------

weekday_service_spot_check = (
    final_output[
        (final_output["point_type"] == "school") &
        (final_output["first_bus_after_end"].notna())
    ][[
        "school_name",
        "school_end_time",
        "bus_stop_code",
        "bus_stop_name",
        "ddot_stop_url",
        "direction",
        "direction_marker",
        "nearest_stop_rank",
        "first_bus_after_end",
        "minutes_after_end",
        "afternoon_route_number",
        "afternoon_route_name",
        "afternoon_headsign",
    ]]
    .drop_duplicates()
    .sort_values([
        "school_name",
        "nearest_stop_rank",
        "direction_marker"
    ])
    .head(10)
)

print("\n===== WEEKDAY SERVICE SPOT CHECK =====")
print(
    "Review these DDOT stop links by hand. Confirm that the listed "
    "first_bus_after_end appears on the weekday schedule.\n"
)
print(weekday_service_spot_check.to_string(index=False))


# In[34]:


# ------------------------------------------------------------
# Sanity check 2:
# Group and count AM previous-bus gaps.
#
# Suspiciously small gaps may indicate duplicate service patterns,
# duplicate trips, or service IDs that should not be included.
# ------------------------------------------------------------
gap_since_previous_bus_am_counts = (
    analysis_df[
        analysis_df["gap_since_previous_bus_am"].notna()
    ]
    .groupby("gap_since_previous_bus_am")
    .size()
    .reset_index(name="row_count")
    .sort_values("gap_since_previous_bus_am")
)

print("\n===== AM GAP DISTRIBUTION =====")
print(
    "Look for suspiciously small gaps, especially 0, 1, 2, or 3 minutes. "
    "Those may indicate duplicated or non-weekday service patterns.\n"
)
print(gap_since_previous_bus_am_counts.to_string(index=False))




# In[37]:


# ------------------------------------------------------------
# 21d. Save a final analysis-ready CSV with flags
# ------------------------------------------------------------

analysis_df.to_csv(
    "schools_4_nearest_bus_stops_schedule_analysis.csv",
    index=False)


# In[38]:


# ------------------------------------------------------------
# 21e. Summary statistics
# ------------------------------------------------------------

avg_distance_all_stops_miles = analysis_df["distance_m"].mean() * 0.0006213712
median_distance_all_stops_miles = analysis_df["distance_m"].median() * 0.0006213712
median_distance_all_stops_meters = analysis_df["distance_m"].median()
median_walk_duration = analysis_df["walk_duration"].median()
avg_walk_duration = analysis_df["walk_duration"].mean()

schools_with_am_problem = analysis_df[
    analysis_df["am_schedule_problem"]
]["school_name"].nunique()

schools_with_pm_problem = analysis_df[
    analysis_df["pm_schedule_problem"]
]["school_name"].nunique()

schools_with_any_problem = analysis_df[
    analysis_df["any_schedule_problem"]
]["school_name"].nunique()

summary_text = "\n".join([
    "===== SCHEDULE ANALYSIS SUMMARY =====",
    f"Average distance of walk, all school-stop pairs, miles: {avg_distance_all_stops_miles:.3f} miles",
    f"Median distance of walk, all school-stop pairs, miles: {median_distance_all_stops_miles:.3f} miles",
    f"Median distance of walk, all school-stop pairs, meters: {median_distance_all_stops_meters:.1f} meters",
    f"Median walk duration, all school-stop pairs: {median_walk_duration:.1f} minutes",
    f"Mean walk duration, all school-stop pairs: {avg_walk_duration:.1f} minutes",
    f"Schools with any AM problem stop: {schools_with_am_problem}",
    f"Schools with any PM problem stop: {schools_with_pm_problem}",
    f"Schools with any problem stop: {schools_with_any_problem}",
])


# ------------------------------------------------------------
# 21f. Print summary
# ------------------------------------------------------------

print(summary_text)


# ------------------------------------------------------------
# 21f. Detailed list of schools with any problem stop
# ------------------------------------------------------------

problem_stops = analysis_df[
    analysis_df["any_schedule_problem"]
].copy()

problem_stops = problem_stops[[
    "school_name",
    "bus_stop_code",
    "bus_stop_name",
    "direction",
    "direction_marker",
    "nearest_stop_rank",
    "distance_m",
    "walk_duration",
    "am_schedule_problem",
    "last_bus_before_start",
    "minutes_before_start",
    "previous_bus_before_start",
    "gap_since_previous_bus_am",
    "pm_schedule_problem",
    "first_bus_after_end",
    "minutes_after_end",
    "next_bus_after_end",
    "gap_to_next_bus_pm",
    "ddot_stop_url"
]].sort_values([
    "school_name",
    "nearest_stop_rank",
    "bus_stop_code"
])

# ------------------------------------------------------------
# 21g. Display problem stop table in notebook
# ------------------------------------------------------------

print("\n===== SCHOOLS WITH ANY PROBLEM STOP =====")
problem_stops.head()


# In[39]:


# ------------------------------------------------------------
# 22. Archive analysis outputs
#
# This creates dated archive files in ./Archive.
# If you run the notebook more than once on the same day,
# that day's archive files will be overwritten.
# ------------------------------------------------------------

from pathlib import Path
from datetime import date

archive_folder = Path("Archive")
archive_folder.mkdir(exist_ok=True)

archive_date = date.today().isoformat()


# ------------------------------------------------------------
# 22a. Create archive file paths
# ------------------------------------------------------------

summary_archive_path = archive_folder / f"schedule_analysis_summary_{archive_date}.txt"

final_output_archive_path = (
    archive_folder /
    f"schools_4_nearest_bus_stops_with_ddot_schedule_for_datawrapper_{archive_date}.csv"
)


# ------------------------------------------------------------
# 22b. Write archive files
# ------------------------------------------------------------

summary_archive_path.write_text(summary_text, encoding="utf-8")

final_output.to_csv(
    final_output_archive_path,
    index=False
)


# ------------------------------------------------------------
# 22d. Confirm archive output
# ------------------------------------------------------------

print("Archive complete.")
print(f"Saved summary archive: {summary_archive_path}")
print(f"Saved final output archive: {final_output_archive_path}")


# In[ ]:





# In[ ]:





# In[ ]:




