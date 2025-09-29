# traffic_metrics.py
# -*- coding: utf-8 -*-

import os
import math
import xml.etree.ElementTree as ET

# Reuse helpers from charging_metrics.py
from charging_metrics import _resolve_path, _round_floats, _percentile_nearest_rank


# ---------- Parse .sumocfg (traffic needs) ----------

def _parse_sumocfg_traffic(config_path, include_queue_output):
    """
    Return paths needed for traffic metrics:
      - tripinfo-output
      - lanedata-output
      - net-file (for speed limits; LoS uses speed limits)
      - queue-output (optional; read from .sumocfg only if include_queue_output is True)
    """
    tree = ET.parse(config_path)
    root = tree.getroot()

    input_elem = root.find("input")
    net_file = None
    if input_elem is not None and input_elem.find("net-file") is not None:
        net_file = _resolve_path(config_path, input_elem.find("net-file").get("value"))

    out_elem = root.find("output")
    if out_elem is None:
        raise RuntimeError("Missing <output> section in .sumocfg")

    tripinfo_elem = out_elem.find("tripinfo-output")
    if tripinfo_elem is None or tripinfo_elem.get("value") is None:
        raise RuntimeError("tripinfo-output is required for Average Vehicle Delay.")

    lane_elem = out_elem.find("lanedata-output")
    if lane_elem is None or lane_elem.get("value") is None:
        raise RuntimeError("lanedata-output is required for SVI/LoS/occupancy/density.")

    tripinfo_xml_path = _resolve_path(config_path, tripinfo_elem.get("value"))
    lanedata_xml_path = _resolve_path(config_path, lane_elem.get("value"))

    queue_xml_path = None
    if include_queue_output:
        queue_elem = out_elem.find("queue-output")
        # Accept either <queue-output value="..."/> or <queue-output value="..."></queue-output>
        if queue_elem is not None and queue_elem.get("value"):
            queue_xml_path = _resolve_path(config_path, queue_elem.get("value"))

    # sim time (optional)
    time_elem = root.find("time")
    sim_begin = float(time_elem.find("begin").get("value")) if time_elem is not None else 0.0
    sim_end = float(time_elem.find("end").get("value")) if time_elem is not None else 0.0
    sim_duration = max(0.0, sim_end - sim_begin) if time_elem is not None else 0.0

    return {
        "tripinfo_xml_path": tripinfo_xml_path,
        "lanedata_xml_path": lanedata_xml_path,
        "queue_xml_path": queue_xml_path,
        "net_xml_path": net_file,
        "sim_duration": sim_duration
    }


# ---------- Network parsing (lane speeds) ----------

def _parse_net_lane_speed_limits(net_xml_path):
    """
    Return:
      - lane_speed_limit: lane_id -> speed_limit (m/s)
    """
    lane_speed_limit = {}
    if not net_xml_path or not os.path.exists(net_xml_path):
        return lane_speed_limit

    context = ET.iterparse(net_xml_path, events=("start", "end"))
    _, root = next(context)

    current_edge_speed = None
    for event, elem in context:
        tag = elem.tag
        if event == "start" and tag == "edge":
            current_edge_speed = float(elem.get("speed")) if elem.get("speed") else None

        elif event == "end" and tag == "lane":
            lid = elem.get("id")
            sp = elem.get("speed")
            if lid:
                if sp is not None:
                    lane_speed_limit[lid] = float(sp)
                elif current_edge_speed is not None:
                    lane_speed_limit.setdefault(lid, float(current_edge_speed))
            elem.clear()

        elif event == "end" and tag == "edge":
            current_edge_speed = None
            root.clear()

    return lane_speed_limit


# ---------- Tripinfo: Average Vehicle Delay ----------

def _compute_delay_from_tripinfo(tripinfo_xml_path):
    per_vehicle = {}
    time_losses = []

    context = ET.iterparse(tripinfo_xml_path, events=("end",))
    for _, elem in context:
        if elem.tag == "tripinfo":
            vid = elem.get("id")
            tl = float(elem.get("timeLoss", "0"))
            dur = float(elem.get("duration", "0"))
            depd = float(elem.get("departDelay", "0"))
            if vid:
                per_vehicle[vid] = {"timeLoss": tl, "duration": dur, "departDelay": depd}
                time_losses.append(tl)
            elem.clear()

    summary = {
        "avg_timeLoss": (sum(time_losses)/len(time_losses)) if time_losses else 0.0,
        "p95_timeLoss": _percentile_nearest_rank(time_losses, 95) if time_losses else 0.0,
        "vehicles_count": len(time_losses)
    }
    return per_vehicle, summary


# ---------- LaneData: SVI, Occupancy, Density, LoS ----------

def _edge_from_lane_id(lane_id):
    if not lane_id or "_" not in lane_id:
        return lane_id
    return lane_id.rsplit("_", 1)[0]

def _weighted_stats(values, weights):
    if not values or not weights or len(values) != len(weights):
        return 0.0, 0.0
    W = sum(weights)
    if W <= 0:
        return 0.0, 0.0
    m = sum(v*w for v, w in zip(values, weights)) / W
    var = sum(w * (v - m) ** 2 for v, w in zip(values, weights)) / W
    return m, math.sqrt(var)

def _collect_lanedata(lanedata_xml_path):
    context = ET.iterparse(lanedata_xml_path, events=("end",))
    for _, elem in context:
        if elem.tag == "lane":
            lid = elem.get("id")
            ss = float(elem.get("sampledSeconds", "0"))
            sp = float(elem.get("speed", "0"))
            oc = float(elem.get("occupancy", "0"))
            wt = float(elem.get("waitingTime", "0"))
            den = float(elem.get("density", "0"))
            yield (lid, ss, sp, oc, wt, den)
            elem.clear()

def _compute_lane_metrics(lanedata_xml_path, lane_speed_limit):
    """
    Per-lane aggregates:
      - avg_speed, SVI (std/mean), occupancy_avg, occupancy_peak
      - waiting_rate = total_waitingTime / total_sampledSeconds
      - density_avg (weighted), density_peak
      - LoS (from avg_speed / speed_limit)
    Returns: per_lane dict and per_edge aggregates (pooled from lanes)
    """
    acc = {}  # lane -> accumulators

    for lid, ss, sp, oc, wt, den in _collect_lanedata(lanedata_xml_path):
        if lid not in acc:
            acc[lid] = {
                "w": 0.0,
                "speeds": [], "ws": [],
                "occ_sum": 0.0, "occ_max": 0.0,
                "wait_sum": 0.0,
                "den_vals": [], "den_ws": [], "den_max": 0.0
            }
        a = acc[lid]
        a["w"] += ss
        a["speeds"].append(sp); a["ws"].append(ss)
        a["occ_sum"] += oc * ss
        if oc > a["occ_max"]: a["occ_max"] = oc
        a["wait_sum"] += wt
        a["den_vals"].append(den); a["den_ws"].append(ss)
        if den > a["den_max"]: a["den_max"] = den

    per_lane = {}
    for lid, a in acc.items():
        total_w = a["w"] if a["w"] > 0 else 1.0

        avg_speed, std_speed = _weighted_stats(a["speeds"], a["ws"])
        svi = (std_speed / avg_speed) if avg_speed > 0 else 0.0

        occ_avg = (a["occ_sum"] / total_w) if total_w > 0 else 0.0
        occ_peak = a["occ_max"]

        waiting_rate = (a["wait_sum"] / total_w) if total_w > 0 else 0.0  # s per s

        den_avg, _ = _weighted_stats(a["den_vals"], a["den_ws"])
        den_peak = a["den_max"]

        vlim = lane_speed_limit.get(lid, None)
        ratio = (avg_speed / vlim) if (vlim and vlim > 0) else 1.0
        if ratio > 0.85: los = "A"
        elif ratio > 0.67: los = "B"
        elif ratio > 0.50: los = "C"
        elif ratio > 0.40: los = "D"
        elif ratio > 0.30: los = "E"
        else: los = "F"

        per_lane[lid] = {
            "avg_speed": avg_speed,
            "speed_variance_index": svi,
            "occupancy_avg": occ_avg,
            "occupancy_peak": occ_peak,
            "waiting_rate": waiting_rate,
            "density_avg": den_avg,
            "density_peak": den_peak,
            "LoS": los
        }

    # Aggregate per-edge
    per_edge = {}
    edge_speed_vals = {}
    edge_los_counts = {}

    for lid, m in per_lane.items():
        edge = _edge_from_lane_id(lid)
        if edge not in per_edge:
            per_edge[edge] = {
                "avg_speed": 0.0, "speed_variance_index": 0.0,
                "occupancy_avg": 0.0, "occupancy_peak": 0.0,
                "waiting_rate": 0.0,
                "density_avg": 0.0,
                "lanes_count": 0
            }
            edge_speed_vals[edge] = {"values": [], "weights": []}
            edge_los_counts[edge] = {"A":0, "B":0, "C":0, "D":0, "E":0, "F":0}

        e = per_edge[edge]
        e["avg_speed"] += m["avg_speed"]
        e["occupancy_avg"] += m["occupancy_avg"]
        e["waiting_rate"] += m["waiting_rate"]
        e["density_avg"] += m["density_avg"]
        e["occupancy_peak"] = max(e["occupancy_peak"], m["occupancy_peak"])
        e["lanes_count"] += 1

        edge_speed_vals[edge]["values"].append(m["avg_speed"])
        edge_speed_vals[edge]["weights"].append(1.0)
        edge_los_counts[edge][m["LoS"]] += 1

    for edge, e in per_edge.items():
        n = max(1, e["lanes_count"])
        e["avg_speed"] /= n
        e["occupancy_avg"] /= n
        e["waiting_rate"] /= n
        e["density_avg"] /= n

        vals = edge_speed_vals[edge]["values"]; wts = edge_speed_vals[edge]["weights"]
        mean_s, std_s = _weighted_stats(vals, wts)
        e["speed_variance_index"] = (std_s / mean_s) if mean_s > 0 else 0.0
        e["LoS_distribution"] = edge_los_counts[edge]

    return per_lane, per_edge


# ---------- QueueOutput (read from .sumocfg) ----------

def _parse_queue_output(queue_xml_path):
    """
    Parse SUMO queue-output (experimental).
    Returns per_lane dict with:
      - queue_length_avg, queue_length_peak
      - queue_length_experimental_avg, queue_length_experimental_peak
      - queue_time_avg
    """
    if not queue_xml_path or not os.path.exists(queue_xml_path):
        return {}

    acc = {}  # lane -> {len_sum, len_max, len_exp_sum, len_exp_max, time_sum, count}
    context = ET.iterparse(queue_xml_path, events=("end",))
    for _, elem in context:
        if elem.tag == "lane":
            lid = elem.get("id")
            # attribute names per SUMO docs (experimental output)
            qlen = float(elem.get("queueing_length", "0"))
            qlen_exp = float(elem.get("queueing_length_experimental", "0"))
            qtime = float(elem.get("queueing_time", "0"))
            if lid:
                a = acc.get(lid)
                if a is None:
                    a = {"len_sum":0.0,"len_max":0.0,"len_exp_sum":0.0,"len_exp_max":0.0,"time_sum":0.0,"count":0}
                    acc[lid] = a
                a["len_sum"] += qlen
                a["len_exp_sum"] += qlen_exp
                a["time_sum"] += qtime
                if qlen > a["len_max"]: a["len_max"] = qlen
                if qlen_exp > a["len_exp_max"]: a["len_exp_max"] = qlen_exp
                a["count"] += 1
            elem.clear()

    per_lane = {}
    for lid, a in acc.items():
        c = max(1, a["count"])
        per_lane[lid] = {
            "queue_length_avg": a["len_sum"]/c,
            "queue_length_peak": a["len_max"],
            "queue_length_experimental_avg": a["len_exp_sum"]/c,
            "queue_length_experimental_peak": a["len_exp_max"],
            "queue_time_avg": a["time_sum"]/c
        }
    return per_lane


def _merge_queue_into_lane_edge(per_lane, per_edge, queue_per_lane):
    """
    Add queue metrics into per_lane / per_edge dicts (creating fields if needed).
    For edges: average lane averages; peaks as max across lanes.
    """
    # per-lane merge
    for lid, qm in queue_per_lane.items():
        lm = per_lane.get(lid)
        if lm is None:
            lm = {
                "avg_speed": 0.0, "speed_variance_index": 0.0,
                "occupancy_avg": 0.0, "occupancy_peak": 0.0,
                "waiting_rate": 0.0, "density_avg": 0.0, "density_peak": 0.0,
                "LoS": "A"
            }
            per_lane[lid] = lm
        lm.update(qm)

    # per-edge aggregation
    by_edge = {}
    for lid, qm in queue_per_lane.items():
        edge = _edge_from_lane_id(lid)
        e = by_edge.get(edge)
        if e is None:
            e = {
                "queue_length_avg": 0.0, "queue_length_peak": 0.0,
                "queue_length_experimental_avg": 0.0, "queue_length_experimental_peak": 0.0,
                "queue_time_avg": 0.0, "lanes": 0
            }
            by_edge[edge] = e
        e["queue_length_avg"] += qm.get("queue_length_avg", 0.0)
        e["queue_length_experimental_avg"] += qm.get("queue_length_experimental_avg", 0.0)
        e["queue_time_avg"] += qm.get("queue_time_avg", 0.0)
        e["queue_length_peak"] = max(e["queue_length_peak"], qm.get("queue_length_peak", 0.0))
        e["queue_length_experimental_peak"] = max(e["queue_length_experimental_peak"], qm.get("queue_length_experimental_peak", 0.0))
        e["lanes"] += 1

    for edge, e in by_edge.items():
        if edge not in per_edge:
            per_edge[edge] = {
                "avg_speed": 0.0, "speed_variance_index": 0.0,
                "occupancy_avg": 0.0, "occupancy_peak": 0.0,
                "waiting_rate": 0.0, "density_avg": 0.0,
                "LoS_distribution": {"A":0,"B":0,"C":0,"D":0,"E":0,"F":0},
                "lanes_count": 0
            }
        n = max(1, e["lanes"])
        per_edge[edge]["queue_length_avg"] = e["queue_length_avg"]/n
        per_edge[edge]["queue_length_experimental_avg"] = e["queue_length_experimental_avg"]/n
        per_edge[edge]["queue_time_avg"] = e["queue_time_avg"]/n
        per_edge[edge]["queue_length_peak"] = e["queue_length_peak"]
        per_edge[edge]["queue_length_experimental_peak"] = e["queue_length_experimental_peak"]


# ---------- Totals ----------

def _compute_totals(delay_summary, per_lane, per_edge):
    edges = list(per_edge.values())

    def mean(values):
        return (sum(values)/len(values)) if values else 0.0

    totals = {
        "avg_timeLoss": delay_summary.get("avg_timeLoss", 0.0),
        "p95_timeLoss": delay_summary.get("p95_timeLoss", 0.0),
        "vehicles_count": delay_summary.get("vehicles_count", 0),
        "network_avg_speed": mean([e["avg_speed"] for e in edges]),
        "network_SVI": mean([e["speed_variance_index"] for e in edges]),
        "occupancy_avg": mean([e["occupancy_avg"] for e in edges]),
        "occupancy_peak": max([e["occupancy_peak"] for e in edges]) if edges else 0.0,
        "waiting_rate": mean([e["waiting_rate"] for e in edges]),
        "density_avg": mean([e["density_avg"] for e in edges]),
        "LoS_distribution": {"A":0, "B":0, "C":0, "D":0, "E":0, "F":0}
    }

    # optional queue totals (present if merged)
    q_avg = [e.get("queue_length_avg") for e in edges if "queue_length_avg" in e]
    q_peak = [e.get("queue_length_peak") for e in edges if "queue_length_peak" in e]
    qx_avg = [e.get("queue_length_experimental_avg") for e in edges if "queue_length_experimental_avg" in e]
    qx_peak = [e.get("queue_length_experimental_peak") for e in edges if "queue_length_experimental_peak" in e]
    qt_avg = [e.get("queue_time_avg") for e in edges if "queue_time_avg" in e]

    if q_avg:
        totals["queue_length_avg"] = mean(q_avg)
        totals["queue_length_peak"] = max(q_peak) if q_peak else 0.0
    if qx_avg:
        totals["queue_length_experimental_avg"] = mean(qx_avg)
        totals["queue_length_experimental_peak"] = max(qx_peak) if qx_peak else 0.0
    if qt_avg:
        totals["queue_time_avg"] = mean(qt_avg)

    # LoS histogram (sum across edges)
    for e in per_edge.values():
        for k, v in e.get("LoS_distribution", {}).items():
            totals["LoS_distribution"][k] = totals["LoS_distribution"].get(k, 0) + v

    return totals


# ---------- Public API ----------

def extract_traffic_metrics_from_sumocfg(config_path, output_json_path, include_queue_output=True):
    """
    Compute traffic metrics from SUMO XML logs:
      - tripinfo.xml -> Average Vehicle Delay (avg/p95)
      - laneData.xml -> SVI, occupancy, waiting_rate, density (per-lane & per-edge) + LoS
      - net.xml      -> lane speed limits (for LoS)
      - queue-output -> read from .sumocfg ONLY if include_queue_output=True (default)

    Output JSON:
    {
      "per_lane": { "<lane_id>": { avg_speed, speed_variance_index, occupancy_avg, occupancy_peak,
                                   waiting_rate, density_avg, density_peak, LoS,
                                   [queue_length_avg, queue_length_peak, queue_length_experimental_avg,
                                    queue_length_experimental_peak, queue_time_avg] } },
      "per_edge": { "<edge_id>": { avg_speed, speed_variance_index, occupancy_avg, occupancy_peak,
                                   waiting_rate, density_avg, LoS_distribution, lanes_count,
                                   [queue_length_avg, queue_length_peak, queue_length_experimental_avg,
                                    queue_length_experimental_peak, queue_time_avg] } },
      "totals":   { avg_timeLoss, p95_timeLoss, vehicles_count, network_avg_speed, network_SVI,
                    occupancy_avg, occupancy_peak, waiting_rate, density_avg, LoS_distribution,
                    [queue_length_avg, queue_length_peak, queue_length_experimental_avg,
                     queue_length_experimental_peak, queue_time_avg] }
    }
    All floats are rounded to 2 decimals.
    """
    cfg = _parse_sumocfg_traffic(config_path, include_queue_output)

    lane_speed_limit = _parse_net_lane_speed_limits(cfg["net_xml_path"])
    _, delay_summary = _compute_delay_from_tripinfo(cfg["tripinfo_xml_path"])

    per_lane, per_edge = _compute_lane_metrics(cfg["lanedata_xml_path"], lane_speed_limit)

    # Queue output integration (if present in .sumocfg and flag enabled)
    if include_queue_output and cfg["queue_xml_path"]:
        queue_per_lane = _parse_queue_output(cfg["queue_xml_path"])
        if queue_per_lane:
            _merge_queue_into_lane_edge(per_lane, per_edge, queue_per_lane)

    totals = _compute_totals(delay_summary, per_lane, per_edge)

    output = _round_floats({
        "per_lane": per_lane,
        "per_edge": per_edge,
        "totals": totals
    }, decimals=2)

    # Write JSON
    with open(output_json_path, "w") as f:
        import json
        json.dump(output, f, indent=4)
