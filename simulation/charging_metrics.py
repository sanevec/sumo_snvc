#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import json
import math
import xml.etree.ElementTree as ET


# ---------- Helpers ----------

def _resolve_path(cfg_path, maybe_rel_path):
    """Resolve path relative to the .sumocfg file if not absolute."""
    if os.path.isabs(maybe_rel_path):
        return maybe_rel_path
    return os.path.join(os.path.dirname(cfg_path), maybe_rel_path)


def _extract_edge_and_index(station_id):
    """
    From 'cs_<edge_id>_<i>' return ('<edge_id>', '<i>').
    Works if edge_id contains underscores.
    """
    if not station_id.startswith("cs_"):
        raise ValueError("Invalid charging station ID: " + station_id)
    body = station_id[3:]  # strip 'cs_'
    parts = body.split("_")
    if len(parts) < 2:
        raise ValueError("Invalid charging station ID: " + station_id)
    return "_".join(parts[:-1]), parts[-1]


def _parse_sumocfg(config_path):
    """Parse .sumocfg and return dict with paths and times."""
    tree = ET.parse(config_path)
    root = tree.getroot()

    time_elem = root.find("time")
    sim_begin = float(time_elem.find("begin").get("value"))
    sim_end = float(time_elem.find("end").get("value"))
    sim_duration = max(0.0, sim_end - sim_begin)

    out_elem = root.find("output")

    charging_elem = out_elem.find("chargingstations-output")
    if charging_elem is None or charging_elem.get("value") is None:
        raise RuntimeError("chargingstations-output is required to compute charging metrics but is missing in the .sumocfg <output> section.")
    charging_xml_path = _resolve_path(config_path, charging_elem.get("value"))

    fcd_elem = out_elem.find("fcd-output")
    if fcd_elem is None or fcd_elem.get("value") is None:
        raise RuntimeError("fcd-output is required to compute session waiting times and queues but is missing in the .sumocfg <output> section.")
    fcd_xml_path = _resolve_path(config_path, fcd_elem.get("value"))

    return {
        "charging_xml_path": charging_xml_path,
        "fcd_xml_path": fcd_xml_path,
        "sim_begin": sim_begin,
        "sim_end": sim_end,
        "sim_duration": sim_duration
    }


# ---------- Charging events ----------

def _load_charging_events(charging_xml_path):
    """
    Read chargingStationStats.xml and return:
      - events: list of (station_id, vehicle_id, chargingBegin, chargingEnd, totalEnergy)
      - station_metrics (initialized per station)
      - vehicles_of_interest: set of vehicle IDs
    """
    cs_tree = ET.parse(charging_xml_path)
    cs_root = cs_tree.getroot()

    events = []
    station_metrics = {}
    vehicles_of_interest = set()

    for ev in cs_root.findall("chargingEvent"):
        station_id = ev.get("chargingStationId")
        veh = ev.get("vehicle")
        energy = float(ev.get("totalEnergyChargedIntoVehicle"))
        t_begin = float(ev.get("chargingBegin"))
        t_end = float(ev.get("chargingEnd"))

        events.append((station_id, veh, t_begin, t_end, energy))
        vehicles_of_interest.add(veh)

        if station_id not in station_metrics:
            station_metrics[station_id] = {
                "total_energy_charged": 0.0,
                "total_charging_time": 0.0,
                "number_of_sessions": 0,
                "vehicles": [],
                "queues": [],  # <- nuevo: lista de longitudes de cola por sesión
                "utilization": 0.0,
                "session_wait_times": [],
                "avg_session_wait_time": 0.0,
                "p95_session_wait_time": 0.0
            }

        s = station_metrics[station_id]
        s["total_energy_charged"] += energy
        s["total_charging_time"] += (t_end - t_begin)
        s["number_of_sessions"] += 1
        s["vehicles"].append(veh)

    return events, station_metrics, vehicles_of_interest


# ---------- FCD parsing ----------

def _build_fcd_series_and_lane_zero_counts(fcd_xml_path, vehicles_filter=None):
    """
    Build:
      - per-vehicle time series: veh_id -> list[(time, lane)]
      - lane->time->count_zero_speed: dict of per-time counts of vehicles with speed==0
    Uses iterparse to be memory-friendly.
    Only vehicles in vehicles_filter are considered for per-vehicle series,
    but for queue counts we also restrict to vehicles_filter to stay consistent
    with the population that actually usa CS (y reducir memoria).
    """
    series = {}
    lane_zero_counts = {}  # lane -> {time -> count_of_veh_speed0}

    context = ET.iterparse(fcd_xml_path, events=("start", "end"))
    _, root = next(context)
    current_time = None

    for event, elem in context:
        tag = elem.tag

        if event == "start" and tag == "timestep":
            current_time = float(elem.get("time", "0"))

        elif event == "end" and tag == "vehicle":
            vid = elem.get("id")
            lane = elem.get("lane")
            # speed might be absent for stopped or 0; SUMO writes "speed"
            speed_str = elem.get("speed")
            try:
                speed = float(speed_str) if speed_str is not None else 0.0
            except ValueError:
                speed = 0.0

            if vehicles_filter is None or vid in vehicles_filter:
                # Save series for waits
                if vid and lane is not None and current_time is not None:
                    series.setdefault(vid, []).append((current_time, lane))
                # Count queue zeros (restrict to vehicles_filter for coherency)
                if lane is not None and current_time is not None and speed == 0.0:
                    lane_zero_counts.setdefault(lane, {})
                    lane_zero_counts[lane][current_time] = lane_zero_counts[lane].get(current_time, 0) + 1

            elem.clear()

        elif event == "end" and tag == "timestep":
            root.clear()

    # sort per-vehicle series by time
    for vid in series:
        series[vid].sort(key=lambda x: x[0])

    return series, lane_zero_counts


# ---------- Waits (from queue entry) ----------

def _find_queue_entry_time(samples, in_zone, t_end):
    """Find first time vehicle is in queue zone before t_end."""
    if not samples:
        return None

    lo, hi = 0, len(samples) - 1
    last_idx = -1
    while lo <= hi:
        mid = (lo + hi) // 2
        if samples[mid][0] <= t_end:
            last_idx = mid
            lo = mid + 1
        else:
            hi = mid - 1
    if last_idx == -1:
        return None

    i = last_idx
    if in_zone(samples[i][1]):
        entry_time = samples[i][0]
        while i - 1 >= 0 and in_zone(samples[i - 1][1]):
            i -= 1
            entry_time = samples[i][0]
        return entry_time
    else:
        while i - 1 >= 0:
            if in_zone(samples[i][1]) and not in_zone(samples[i - 1][1]):
                return samples[i][0]
            i -= 1
        return None


def _compute_session_waits_and_queues(events, fcd_xml_path, effective_cs_count_by_edge):
    """
    Compute:
      - per-station waits: from queue entry (to_cs_<edge>_0 or cs_lanes_<edge>_k) to charging begin
      - per-station queues: for each session, the MAX number of vehicles with speed==0
        in the *station lane* (cs_lanes_<edge>_<i>) during [chargingBegin, chargingEnd].
    """
    vehicles = set(ev[1] for ev in events)
    series, lane_zero_counts = _build_fcd_series_and_lane_zero_counts(fcd_xml_path, vehicles_filter=vehicles)
    per_station_waits = {}
    per_station_queues = {}

    for station_id, veh, t_begin, t_end, _ in events:
        edge_id, idx = _extract_edge_and_index(station_id)
        n_cs = max(1, effective_cs_count_by_edge.get(edge_id, 1))

        # Queue zone for waits
        queue_lanes = {f"to_cs_{edge_id}_0"} | {f"cs_lanes_{edge_id}_{k}" for k in range(n_cs)}
        in_zone = lambda lane_name: lane_name in queue_lanes

        # Compute wait
        samples = series.get(veh, [])
        t_enter = _find_queue_entry_time(samples, in_zone, t_begin)
        if t_enter is not None:
            wait = max(0.0, t_begin - t_enter)
            per_station_waits.setdefault(station_id, []).append(wait)

        # Compute queue length (station lane only)
        station_lane = f"cs_lanes_{edge_id}_{idx}"
        lane_counts = lane_zero_counts.get(station_lane, {})
        if lane_counts:
            # We have discrete times; take max on [t_begin, t_end]
            qmax = 0
            # Iterate only keys within interval for efficiency
            # (simple scan; keys count per lane is typically small)
            for tt, cnt in lane_counts.items():
                if t_begin <= tt <= t_end:
                    if cnt > qmax:
                        qmax = cnt
            per_station_queues.setdefault(station_id, []).append(qmax)
        else:
            per_station_queues.setdefault(station_id, []).append(0)

    return per_station_waits, per_station_queues


# ---------- Stats ----------

def _percentile_nearest_rank(values, p):
    """
    Nearest-rank percentile without interpolation.
    values: list of floats (non-empty)
    p: 0..100
    """
    if not values:
        return 0.0
    if p <= 0:
        return min(values)
    if p >= 100:
        return max(values)
    arr = sorted(values)
    rank = math.ceil((p / 100.0) * len(arr))
    idx = max(1, rank) - 1
    return arr[idx]


# ---------- Aggregation ----------

def _compute_group_and_totals(station_metrics, sim_duration, effective_cs_count_by_edge=None, cs_size=None):
    """
    Aggregate per_group and totals from station_metrics.
    Adds:
      - per_group.number_of_stations_used
      - per_group.number_of_stations_total (if cs_size is provided)
      - per_group.stations_used_ratio (if total known)
      - per_group.total_energy_charged, total_charging_time, total_number_of_sessions
      - per_group.avg_queue_length, p95_queue_length
    Uses:
      - p95_session_wait_time field name (no 'avg_' prefix) for group and totals.
    """
    # per-station derived metrics
    for s in station_metrics.values():
        s["utilization"] = (s["total_charging_time"] / sim_duration) if sim_duration > 0 else 0.0
        waits = s.get("session_wait_times", [])
        s["avg_session_wait_time"] = (sum(waits) / len(waits)) if waits else 0.0
        s["p95_session_wait_time"] = _percentile_nearest_rank(waits, 95) if waits else 0.0

    # group accumulators
    group_acc = {}
    for station_id, s in station_metrics.items():
        edge_id, _ = _extract_edge_and_index(station_id)
        g = group_acc.setdefault(edge_id, {
            "energy": [], "time": [], "sessions": [], "utilization": [],
            "waits_avg": [], "waits_p95": [], "queues_all": []
        })
        g["energy"].append(s["total_energy_charged"])
        g["time"].append(s["total_charging_time"])
        g["sessions"].append(s["number_of_sessions"])
        g["utilization"].append(s["utilization"])
        g["waits_avg"].append(s["avg_session_wait_time"])
        g["waits_p95"].append(s["p95_session_wait_time"])
        # Extiende con todas las colas registradas en la estación
        g["queues_all"].extend(s.get("queues", []))

    # build per_group with corrected station counts + queue stats
    per_group = {}
    for edge_id, acc in group_acc.items():
        used = len(acc["energy"])  # stations that actually appear in events
        n = used if used > 0 else 1

        # Queue stats (sobre TODAS las sesiones del grupo)
        queues_all = acc["queues_all"]
        avg_q = (sum(queues_all) / len(queues_all)) if queues_all else 0.0
        p95_q = _percentile_nearest_rank(queues_all, 95) if queues_all else 0.0

        group_entry = {
            # Totales solicitados
            "total_energy_charged": sum(acc["energy"]),
            "avg_energy_charged": sum(acc["energy"]) / n,
            "total_charging_time": sum(acc["time"]),
            "avg_charging_time": sum(acc["time"]) / n,
            "total_number_of_sessions": sum(acc["sessions"]),
            "avg_queue_length": avg_q,
            "p95_queue_length": p95_q,

            # Métricas previas
            "avg_utilization": sum(acc["utilization"]) / n,
            "avg_session_wait_time": sum(acc["waits_avg"]) / n,
            "p95_session_wait_time": sum(acc["waits_p95"]) / n,  # media de p95 por estación
            "number_of_stations_used": used
        }

        if cs_size is not None:
            total = int(cs_size)
            group_entry["number_of_stations_total"] = total
            group_entry["stations_used_ratio"] = (used / total) if total else 0.0

        per_group[edge_id] = group_entry

    # totals (averages across stations used) + requested totals/queues
    num_stations_used = len(station_metrics)
    all_queues = []
    for s in station_metrics.values():
        all_queues.extend(s.get("queues", []))

    totals = {
        # Totales solicitados
        "total_energy_charged": sum(s["total_energy_charged"] for s in station_metrics.values()),
        "avg_energy_charged": (sum(s["total_energy_charged"] for s in station_metrics.values()) / num_stations_used) if num_stations_used else 0.0,
        "total_charging_time": sum(s["total_charging_time"] for s in station_metrics.values()),
        "avg_charging_time": (sum(s["total_charging_time"] for s in station_metrics.values()) / num_stations_used) if num_stations_used else 0.0,
        "total_number_of_sessions": sum(s["number_of_sessions"] for s in station_metrics.values()),
        "avg_queue_length": (sum(all_queues) / len(all_queues)) if all_queues else 0.0,
        "p95_queue_length": _percentile_nearest_rank(all_queues, 95) if all_queues else 0.0,

        # Métricas previas
        "avg_utilization": (sum(s["utilization"] for s in station_metrics.values()) / num_stations_used) if num_stations_used else 0.0,
        "avg_session_wait_time": (sum(s["avg_session_wait_time"] for s in station_metrics.values()) / num_stations_used) if num_stations_used else 0.0,
        "p95_session_wait_time": (sum(s["p95_session_wait_time"] for s in station_metrics.values()) / num_stations_used) if num_stations_used else 0.0,
        "number_of_stations_used": num_stations_used,
        "simulation_duration": sim_duration
    }

    if cs_size is not None:
        num_groups = len(group_acc)  # distinct edge_ids that appeared
        total_planned = int(cs_size) * num_groups
        totals["number_of_stations_total"] = total_planned
        totals["stations_used_ratio"] = (num_stations_used / total_planned) if total_planned else 0.0

    return per_group, totals


# ---------- JSON rounding ----------

def _round_floats(obj, decimals=2):
    """Recursively round floats in nested structures."""
    if isinstance(obj, float):
        return round(obj, decimals)
    elif isinstance(obj, list):
        return [_round_floats(i, decimals) for i in obj]
    elif isinstance(obj, dict):
        return {k: _round_floats(v, decimals) for k, v in obj.items()}
    else:
        return obj


# ---------- Public API ----------

def extract_charging_metrics_from_sumocfg(config_path, output_json_path, cs_size=None):
    """
    Compute charging metrics and write JSON.

    Output JSON shape matches the requested schema:
      per_station:
        - vehicles (list)
        - queues (list)  # max queue length (stopped speed==0) at station lane during each session
      per_group:
        - total_energy_charged, total_charging_time, total_number_of_sessions
        - avg_queue_length, p95_queue_length
        - p95_session_wait_time  (no 'avg_p95...')
      totals:
        - total_energy_charged, total_charging_time, total_number_of_sessions
        - avg_queue_length, p95_queue_length
        - p95_session_wait_time

    Args:
        config_path (str): Path to the SUMO .sumocfg file.
        output_json_path (str): Path to output JSON file.
        cs_size (int|None): Intended number of stations (lanes) per group (optional).
    """
    cfg = _parse_sumocfg(config_path)
    events, station_metrics, vehicles = _load_charging_events(cfg["charging_xml_path"])

    # Infer stations-per-group from events
    inferred_counts = {}
    for sid in station_metrics.keys():
        edge_id, _ = _extract_edge_and_index(sid)
        inferred_counts[edge_id] = inferred_counts.get(edge_id, 0) + 1

    # Build effective counts per edge
    effective_cs_count_by_edge = {}
    for edge_id in inferred_counts.keys():
        effective_cs_count_by_edge[edge_id] = int(cs_size) if cs_size is not None else inferred_counts[edge_id]

    # Waits (queue entry -> charging begin) and Queues (per session)
    per_station_waits, per_station_queues = _compute_session_waits_and_queues(
        events, cfg["fcd_xml_path"], effective_cs_count_by_edge
    )

    # Attach waits & queues to station metrics
    for station_id in station_metrics.keys():
        if station_id in per_station_waits:
            station_metrics[station_id]["session_wait_times"] = per_station_waits[station_id]
        # queues might be missing if never observed; ensure present
        station_metrics[station_id]["queues"] = per_station_queues.get(station_id, station_metrics[station_id].get("queues", []))

    # Aggregations
    per_group, totals = _compute_group_and_totals(
        station_metrics, cfg["sim_duration"],
        effective_cs_count_by_edge=effective_cs_count_by_edge,
        cs_size=cs_size
    )

    full_output = _round_floats({
        "per_station": station_metrics,
        "per_group": per_group,
        "totals": totals
    })

    with open(output_json_path, "w") as f:
        json.dump(full_output, f, indent=4)
