#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
SUMO charging metrics aggregator:
- Reads .sumocfg to get paths and time window
- Reads chargingStationStats.xml for per-session energy and timing
- Reads fcd.xml to compute per-session waiting time since entering the queue zone:
  queue zone = to_cs_<edge>_0 + cs_lanes_<edge>_<k> (k in [0..numLanes-1])

Outputs a JSON with:
{
  "per_station": {...},
  "per_group": {...},   # group = edge_id (from station_id = cs_<edge>_<idx>)
  "totals": {...}
}
"""

import os
import json
import argparse
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

    charging_xml_path = _resolve_path(config_path, out_elem.find("chargingstations-output").get("value"))

    fcd_elem = out_elem.find("fcd-output")
    if fcd_elem is None or fcd_elem.get("value") is None:
        raise RuntimeError("fcd-output is required to compute session waiting times but is missing in the .sumocfg <output> section.")
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


# ---------- FCD (per-session waiting time from queue entry) ----------

def _build_fcd_series(fcd_xml_path, vehicles_filter=None):
    """
    Build per-vehicle time series from FCD: veh_id -> list of (time, lane).
    Uses iterparse to be memory-friendly.
    """
    series = {}
    context = ET.iterparse(fcd_xml_path, events=("start", "end"))
    _, root = next(context)

    current_time = None
    for event, elem in context:
        tag = elem.tag

        if event == "start" and tag == "timestep":
            current_time = float(elem.get("time", "0"))

        elif event == "end" and tag == "vehicle":
            vid = elem.get("id")
            if vehicles_filter and vid not in vehicles_filter:
                elem.clear()
                continue
            lane = elem.get("lane")
            if vid and lane is not None and current_time is not None:
                if vid not in series:
                    series[vid] = []
                series[vid].append((current_time, lane))
            elem.clear()

        elif event == "end" and tag == "timestep":
            root.clear()

    for vid in series:
        series[vid].sort(key=lambda x: x[0])
    return series


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


def _compute_session_waits(events, fcd_xml_path, edge_cs_count):
    """Compute waiting times from queue entry to charging begin."""
    vehicles = set(ev[1] for ev in events)
    series = _build_fcd_series(fcd_xml_path, vehicles_filter=vehicles)
    per_station_waits = {}

    for station_id, veh, t_begin, _, _ in events:
        edge_id, _ = _extract_edge_and_index(station_id)
        n_cs = edge_cs_count.get(edge_id, 1)
        queue_lanes = {f"to_cs_{edge_id}_0"} | {f"cs_lanes_{edge_id}_{k}" for k in range(max(1, n_cs))}

        def in_zone(lane_name):
            return lane_name in queue_lanes

        samples = series.get(veh, [])
        t_enter = _find_queue_entry_time(samples, in_zone, t_begin)
        if t_enter is None:
            continue

        wait = max(0.0, t_begin - t_enter)
        per_station_waits.setdefault(station_id, []).append(wait)

    return per_station_waits


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

def _compute_group_and_totals(station_metrics, sim_duration):
    """Aggregate per_group and totals from station_metrics."""
    for s in station_metrics.values():
        s["utilization"] = (s["total_charging_time"] / sim_duration) if sim_duration > 0 else 0.0
        waits = s.get("session_wait_times", [])
        s["avg_session_wait_time"] = (sum(waits) / len(waits)) if waits else 0.0
        s["p95_session_wait_time"] = _percentile_nearest_rank(waits, 95) if waits else 0.0

    group_acc = {}
    for station_id, s in station_metrics.items():
        edge_id, _ = _extract_edge_and_index(station_id)
        g = group_acc.setdefault(edge_id, {
            "energy": [], "time": [], "sessions": [], "utilization": [],
            "avg_session_wait_time": [], "p95_session_wait_time": []
        })
        g["energy"].append(s["total_energy_charged"])
        g["time"].append(s["total_charging_time"])
        g["sessions"].append(s["number_of_sessions"])
        g["utilization"].append(s["utilization"])
        g["avg_session_wait_time"].append(s["avg_session_wait_time"])
        g["p95_session_wait_time"].append(s["p95_session_wait_time"])

    per_group = {}
    for edge_id, acc in group_acc.items():
        n = len(acc["energy"])
        per_group[edge_id] = {
            "avg_energy_charged": sum(acc["energy"]) / n,
            "avg_charging_time": sum(acc["time"]) / n,
            "avg_number_of_sessions": sum(acc["sessions"]) / n,
            "avg_utilization": sum(acc["utilization"]) / n,
            "avg_session_wait_time": sum(acc["avg_session_wait_time"]) / n,
            "avg_p95_session_wait_time": sum(acc["p95_session_wait_time"]) / n,
            "number_of_stations": n
        }

    num_stations = len(station_metrics)
    totals = {
        "avg_energy_charged": (sum(s["total_energy_charged"] for s in station_metrics.values()) / num_stations) if num_stations else 0.0,
        "avg_charging_time": (sum(s["total_charging_time"] for s in station_metrics.values()) / num_stations) if num_stations else 0.0,
        "avg_number_of_sessions": (sum(s["number_of_sessions"] for s in station_metrics.values()) / num_stations) if num_stations else 0.0,
        "avg_utilization": (sum(s["utilization"] for s in station_metrics.values()) / num_stations) if num_stations else 0.0,
        "avg_session_wait_time": (sum(s["avg_session_wait_time"] for s in station_metrics.values()) / num_stations) if num_stations else 0.0,
        "avg_p95_session_wait_time": (sum(s["p95_session_wait_time"] for s in station_metrics.values()) / num_stations) if num_stations else 0.0,
        "number_of_stations": num_stations,
        "simulation_duration": sim_duration
    }
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


# ---------- Main orchestration ----------

def extract_charging_metrics_from_sumocfg(config_path, output_json_path):
    cfg = _parse_sumocfg(config_path)
    events, station_metrics, _ = _load_charging_events(cfg["charging_xml_path"])

    # Infer cs lane counts per edge_id from station IDs present
    edge_cs_count = {}
    for sid in station_metrics.keys():
        edge_id, _ = _extract_edge_and_index(sid)
        edge_cs_count[edge_id] = edge_cs_count.get(edge_id, 0) + 1

    # Session waiting times from FCD
    per_station_waits = _compute_session_waits(events, cfg["fcd_xml_path"], edge_cs_count)
    for station_id, waits in per_station_waits.items():
        station_metrics[station_id]["session_wait_times"] = waits

    # Aggregations
    per_group, totals = _compute_group_and_totals(station_metrics, cfg["sim_duration"])

    full_output = _round_floats({
        "per_station": station_metrics,
        "per_group": per_group,
        "totals": totals
    })

    with open(output_json_path, "w") as f:
        json.dump(full_output, f, indent=4)


# ---------- CLI ----------
'''
def main():
    parser = argparse.ArgumentParser(description="Aggregate SUMO charging station metrics with per-session waiting times (includes avg and p95).")
    parser.add_argument("--config", required=True, help="Path to the SUMO .sumocfg file.")
    parser.add_argument("--output", required=True, help="Path to output JSON file.")
    args = parser.parse_args()

    extract_charging_metrics_from_sumocfg(args.config, args.output)
    print(f"[OK] Metrics saved to: {args.output}")


if __name__ == "__main__":
    main()'''
