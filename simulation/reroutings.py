# reroutings.py
# All comments in English.

import math
import json

# ---------- Helpers (IDs, stats containers) ----------

def get_group_id(cs_id: str) -> str:
    """
    Extract group from a charging-station id like 'cs_e5_0' -> 'e5'
    Assumes pattern 'cs_<group>_<laneIndex>'.
    """
    if not cs_id or cs_id == "NULL":
        return ""
    parts = cs_id.split("_")
    return parts[1] if len(parts) >= 3 else ""

def _new_station_data():
    """Per-station container (time-only metrics)."""
    return {
        "sessions": 0,

        # Per-session search durations for this station (DESTINATION side)
        "search_times": [],

        # Station-level aggregates (filled at finalize)
        "avg_search_time": None,
        "p95_search_time": None,

        # Reroute IN (lists + count)
        "reroute_in_times": [],
        "reroute_in_count": 0,

        # Reroute OUT (lists + count)
        "reroute_out_times": [],
        "reroute_out_count": 0,

        # IN-only aggregates at station level (as per your example)
        "avg_reroute_in_time": None,
        "p95_reroute_in_time": None,

        # OUT aggregates (added)
        "avg_reroute_out_time": None,
        "p95_reroute_out_time": None,

        # --- internal only (not written to final JSON) ---
        "_sessions_with_in": 0,   # sessions at this station with ≥1 IN (destination side)
        "_sessions_with_out": 0,  # sessions at this station with ≥1 OUT (origin side)
    }

def _percentile(values, p):
    """Inclusive p-th percentile (e.g., p=95). Returns None for empty."""
    if not values:
        return None
    arr = sorted(values)
    if len(arr) == 1:
        return float(arr[0])
    k = (p/100) * (len(arr)-1)
    f = math.floor(k)
    c = math.ceil(k)
    if f == c:
        return float(arr[int(k)])
    return float(arr[f] + (arr[c] - arr[f]) * (k - f))

def _round_floats_inplace(obj, ndigits=2):
    """Recursively round all floats inside dict/list to ndigits (in place)."""
    if isinstance(obj, dict):
        for k, v in obj.items():
            if isinstance(v, float):
                obj[k] = round(v, ndigits)
            else:
                _round_floats_inplace(v, ndigits)
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            if isinstance(v, float):
                obj[i] = round(v, ndigits)
            else:
                _round_floats_inplace(v, ndigits)

# ---------- Global data for the run ----------

def new_rerouting_data():
    """
    Create the run-level data with primitive dicts only.
    """
    return {
        "per_station": {},   # cs_id -> station_data
        "per_group": {},     # filled at finalize
        "totals": {},        # filled at finalize
        "veh_state": {},     # veh_id -> per-vehicle state

        # Group-level denominators/numerators for %OUT
        # Denominator: sessions that STARTED searching in this group
        "_group_session_starts": {},       # group -> int
        # Numerator: sessions that had ≥1 OUT away from this group
        "_group_sessions_with_out": {},    # group -> int
    }

# ---------- Vehicle state runtime model ----------

def _new_veh_state():
    """State tracked per vehicle across ticks."""
    return {
        "prev_s": "",                 # previous device.stationfinder.chargingStation
        "prev_b": "NULL",             # previous device.battery.chargingStationId

        # Search tracking
        "search_active": False,
        "search_start_t": None,
        "search_target_station": "",
        "search_target_group": "",

        # Reroute collapsing across groups
        # When first leaving a group, we open 'pending_reroute' and keep it open
        # until arrival to the final destination (group), ignoring mid-group hops.
        "pending_reroute": None,      # { origin_group, origin_station, start_t }
        "current_group": "",          # convenience
    }

# ---------- Runtime updates per tick ----------

def _ensure_station(data, cs_id):
    if cs_id not in data["per_station"]:
        data["per_station"][cs_id] = _new_station_data()
    return data["per_station"][cs_id]

def tick_update_vehicle(data, veh_id, now_s, now_b, now_time):
    """
    Feed current s/b for this tick. s refers to device.stationfinder.chargingStation,
    b refers to device.battery.chargingStationId. now_time is the current sim time (float).
    - Detect s transitions to start search.
    - Collapse within-group changes.
    - Detect inter-group changes to open/extend pending reroute (time-only).
    - Do NOT finalize here (arrival handled in handle_arrival()).
    """
    if veh_id not in data["veh_state"]:
        data["veh_state"][veh_id] = _new_veh_state()
    vs = data["veh_state"][veh_id]

    # ---- 1) Handle search start from s ----
    # Start search when s goes from "" to "cs_*" and b == "NULL"
    if (not vs["search_active"]) and now_s and now_b == "NULL":
        vs["search_active"] = True
        vs["search_start_t"] = now_time
        vs["search_target_station"] = now_s
        vs["search_target_group"] = get_group_id(now_s)
        vs["current_group"] = vs["search_target_group"]

        # Track origin group for OUT denominators
        og = vs["search_target_group"]
        if og:
            data["_group_session_starts"][og] = data["_group_session_starts"].get(og, 0) + 1

    # ---- 2) While searching, handle target updates ----
    if vs["search_active"] and now_s and now_b == "NULL":
        new_group = get_group_id(now_s)
        old_group = vs["search_target_group"]

        if new_group == old_group:
            # Within-group change: collapse to latest station; no reroute recorded
            vs["search_target_station"] = now_s
            vs["current_group"] = new_group
        else:
            # Inter-group change: open pending_reroute if not open yet
            if vs["pending_reroute"] is None:
                vs["pending_reroute"] = {
                    "origin_group": old_group,
                    "origin_station": vs["search_target_station"],
                    "start_t": now_time
                }
            # Collapse mid-groups: always aim at the latest group/station
            vs["search_target_station"] = now_s
            vs["search_target_group"] = new_group
            vs["current_group"] = new_group

    # Store previous s/b for next tick
    vs["prev_s"] = now_s
    vs["prev_b"] = now_b

def handle_arrival(data, veh_id, cs_id, now_time):
    """
    Call this when a vehicle actually starts the stop at a charging station
    (e.g., from traci.simulation.getStopStartingVehiclesIDList()).

    This finalizes:
    - search_times for the DESTINATION station
    - pending inter-group reroute as one IN at destination and one OUT at origin
    """
    if not cs_id or cs_id == "NULL":
        return

    if veh_id not in data["veh_state"]:
        data["veh_state"][veh_id] = _new_veh_state()
    vs = data["veh_state"][veh_id]

    dest_station = cs_id
    dest_group = get_group_id(dest_station)

    # --- 1) Close search (if active) and write metrics to DESTINATION station ---
    if vs["search_active"] and vs["search_start_t"] is not None:
        st = float(now_time - vs["search_start_t"])
        station_data = _ensure_station(data, dest_station)
        station_data["sessions"] += 1
        station_data["search_times"].append(st)

    # --- 2) If there was a pending inter-group reroute, finalize IN/OUT (time only) ---
    if vs["pending_reroute"] is not None:
        origin_group = vs["pending_reroute"]["origin_group"]
        origin_station = vs["pending_reroute"]["origin_station"]
        start_t = vs["pending_reroute"]["start_t"]

        # If destination group == origin group (returned to origin), discard this pending reroute.
        if dest_group == origin_group:
            vs["pending_reroute"] = None
        else:
            dur = float(now_time - start_t)

            # OUT at origin station
            if origin_station:
                station_data_orig = _ensure_station(data, origin_station)
                station_data_orig["reroute_out_times"].append(dur)
                station_data_orig["reroute_out_count"] += 1
                station_data_orig["_sessions_with_out"] += 1

            # IN at destination station
            station_data_dest = _ensure_station(data, dest_station)
            station_data_dest["reroute_in_times"].append(dur)
            station_data_dest["reroute_in_count"] += 1
            station_data_dest["_sessions_with_in"] += 1

            # Mark that this session had an OUT away from the origin group (for group-level %OUT)
            if origin_group:
                data["_group_sessions_with_out"][origin_group] = data["_group_sessions_with_out"].get(origin_group, 0) + 1

            # Clear pending reroute
            vs["pending_reroute"] = None

    # --- 3) Reset per-session state for this vehicle ---
    vs["search_active"] = False
    vs["search_start_t"] = None
    vs["search_target_station"] = ""
    vs["search_target_group"] = ""
    vs["current_group"] = ""

def finalize_json(data):
    """
    Build the final JSON exactly per your schema:
    - Per-station: compute avg/p95 for search_times, reroute_in_times, and reroute_out_times.
    - Per-group: concatenate lists across stations (no averaging of averages).
    - Totals: same idea (concatenate across all stations).
    - Round all floats to 2 decimals at the end.
    """
    per_station = data["per_station"]

    # ---- Per-station aggregates ----
    for cs_id, station_data in per_station.items():
        # Averages / p95 for search
        station_data["avg_search_time"] = (float(sum(station_data["search_times"]) / len(station_data["search_times"]))
                                           if station_data["search_times"] else None)
        station_data["p95_search_time"] = _percentile(station_data["search_times"], 95)

        # Averages / p95 for reroute IN
        station_data["avg_reroute_in_time"] = (float(sum(station_data["reroute_in_times"]) / len(station_data["reroute_in_times"]))
                                               if station_data["reroute_in_times"] else None)
        station_data["p95_reroute_in_time"] = _percentile(station_data["reroute_in_times"], 95)

        # Averages / p95 for reroute OUT (added)
        station_data["avg_reroute_out_time"] = (float(sum(station_data["reroute_out_times"]) / len(station_data["reroute_out_times"]))
                                                if station_data["reroute_out_times"] else None)
        station_data["p95_reroute_out_time"] = _percentile(station_data["reroute_out_times"], 95)

        # Sanity: counts must match lengths of lists
        if station_data["reroute_in_count"] != len(station_data["reroute_in_times"]):
            station_data["reroute_in_count"] = len(station_data["reroute_in_times"])
        if station_data["reroute_out_count"] != len(station_data["reroute_out_times"]):
            station_data["reroute_out_count"] = len(station_data["reroute_out_times"])

    # ---- Per-group by concatenation ----
    group_acc = {}  # group_id -> temp aggregation
    for cs_id, station_data in per_station.items():
        g = get_group_id(cs_id)
        if not g:
            continue
        if g not in group_acc:
            group_acc[g] = {
                "sessions": 0,
                "search_times_all": [],
                "reroute_in_times_all": [],
                "reroute_out_times_all": [],    # added
                # counts
                "reroute_in_count_total": 0,
                "reroute_out_count_total": 0,
                "_sessions_with_in_total": 0,   # destination-side
                "_sessions_with_out_total": 0,  # origin-side (station perspective)
            }

        ga = group_acc[g]
        ga["sessions"] += station_data["sessions"]
        ga["search_times_all"].extend(station_data["search_times"])
        ga["reroute_in_times_all"].extend(station_data["reroute_in_times"])
        ga["reroute_out_times_all"].extend(station_data["reroute_out_times"])  # added
        ga["reroute_in_count_total"] += station_data["reroute_in_count"]
        ga["reroute_out_count_total"] += station_data["reroute_out_count"]
        ga["_sessions_with_in_total"] += station_data["_sessions_with_in"]
        ga["_sessions_with_out_total"] += station_data["_sessions_with_out"]

    per_group = {}
    for g, ga in group_acc.items():
        avg_search_time = (float(sum(ga["search_times_all"]) / len(ga["search_times_all"]))
                           if ga["search_times_all"] else None)
        p95_search_time = _percentile(ga["search_times_all"], 95)

        avg_reroute_in_time = (float(sum(ga["reroute_in_times_all"]) / len(ga["reroute_in_times_all"]))
                               if ga["reroute_in_times_all"] else None)
        p95_reroute_in_time = _percentile(ga["reroute_in_times_all"], 95)

        # OUT aggregates (added)
        avg_reroute_out_time = (float(sum(ga["reroute_out_times_all"]) / len(ga["reroute_out_times_all"]))
                                if ga["reroute_out_times_all"] else None)
        p95_reroute_out_time = _percentile(ga["reroute_out_times_all"], 95)

        # %IN uses destination sessions (ga["sessions"])
        percent_reroute_in_sessions = (ga["_sessions_with_in_total"] / ga["sessions"]) if ga["sessions"] else None

        # %OUT uses sessions that STARTED searching in this group as denominator
        group_starts = data.get("_group_session_starts", {}).get(g, 0)
        group_out_sessions = data.get("_group_sessions_with_out", {}).get(g, 0)
        percent_reroute_out_sessions = (group_out_sessions / group_starts) if group_starts else None

        per_group[g] = {
            "sessions": ga["sessions"],

            "avg_search_time": avg_search_time,
            "p95_search_time": p95_search_time,

            "avg_reroute_in_time": avg_reroute_in_time,
            "p95_reroute_in_time": p95_reroute_in_time,

            "avg_reroute_out_time": avg_reroute_out_time,      # added
            "p95_reroute_out_time": p95_reroute_out_time,      # added

            "reroute_in_count_total": ga["reroute_in_count_total"],
            "reroute_out_count_total": ga["reroute_out_count_total"],

            "percent_reroute_in_sessions": percent_reroute_in_sessions,
            "percent_reroute_out_sessions": percent_reroute_out_sessions
        }

    # ---- Totals (concatenate across all stations) ----
    all_search_times = []
    all_rin_times = []
    all_rout_times = []  # added
    rin_count_total = 0
    rout_count_total = 0
    sessions_total = 0
    sessions_with_in_total = 0
    # For %OUT total, use group-based denominators
    group_starts_total = sum(data.get("_group_session_starts", {}).values())
    group_out_sessions_total = sum(data.get("_group_sessions_with_out", {}).values())

    for _, station_data in per_station.items():
        all_search_times.extend(station_data["search_times"])
        all_rin_times.extend(station_data["reroute_in_times"])
        all_rout_times.extend(station_data["reroute_out_times"])  # added
        rin_count_total += station_data["reroute_in_count"]
        rout_count_total += station_data["reroute_out_count"]
        sessions_total += station_data["sessions"]
        sessions_with_in_total += station_data["_sessions_with_in"]
        # station_data["_sessions_with_out"] is origin-side, not used in totals denominator directly

    totals = {
        "avg_search_time": (float(sum(all_search_times)) / len(all_search_times)) if all_search_times else None,
        "p95_search_time": _percentile(all_search_times, 95),

        "avg_reroute_in_time": (float(sum(all_rin_times)) / len(all_rin_times)) if all_rin_times else None,   # added
        "p95_reroute_in_time": _percentile(all_rin_times, 95),                                                # added

        "avg_reroute_out_time": (float(sum(all_rout_times)) / len(all_rout_times)) if all_rout_times else None,  # added
        "p95_reroute_out_time": _percentile(all_rout_times, 95),                                                  # added

        "reroute_in_count_total": rin_count_total,
        "reroute_out_count_total": rout_count_total,

        "percent_reroute_in_sessions_total": (sessions_with_in_total / sessions_total) if sessions_total else None,
        "percent_reroute_out_sessions_total": (group_out_sessions_total / group_starts_total) if group_starts_total else None
    }

    # Build final dict in your exact structure (strip internals)
    final_json = {
        "per_station": {cs: {k: v for k, v in station_data.items() if not k.startswith("_")}
                        for cs, station_data in per_station.items()},
        "per_group": per_group,
        "totals": totals
    }

    # Round everything to 2 decimals
    _round_floats_inplace(final_json, ndigits=2)
    return final_json

def dump_json(data_obj, path):
    # Defensive rounding at write time (in case caller didn't call finalize_json)
    _round_floats_inplace(data_obj, ndigits=2)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data_obj, f, ensure_ascii=False, indent=2)
