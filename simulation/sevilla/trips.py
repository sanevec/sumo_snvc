""" 
Vehicle route generation module for SUMO traffic simulations. 
This module generates vehicles routes based on input data.
"""

import random
import os
import json
import pandas as pd
import sys
if 'SUMO_HOME' in os.environ:
    sys.path.append(os.path.join(os.environ['SUMO_HOME'], 'tools'))
import sumolib  # noqa
from sumolib.net.edge import Edge
from sumolib.net import Net
from typing import List, Tuple
from collections import defaultdict
from xml.etree.ElementTree import Element, SubElement, tostring
from xml.dom import minidom
from mpi4py import MPI


class Vehicle:
    """Represents a vehicle with its route and departure time."""

    def __init__(self, id, depart_time, edges):
        """Initialize a Vehicle instance.

        Args:
            id: unique identifier for the vehicle
            depart_time: Simulation time when the vehicle departs (seconds)
            edges: List of edge IDs that form the vehicle's route
        """
        self.vehicle_id = id
        self.depart_time = depart_time
        self.edges = edges

    def __repr__(self):
        """Return a string representation of the Vehicle."""
        return (f"Vehicle(vehicle_id={self.vehicle_id}, "
                f"depart_time={self.depart_time}, edges={self.edges})")


class Route:
    """Represents a predefined route template."""

    def __init__(self, route_id, total_vehicles, edges):
        """Initialize a Route instance.

        Args:
            route_id: unique identifier for the route
            total_vehicles: number of vehicles assigned to this route
            edges: list of edge IDs that form the route
        """
        self.route_id = route_id
        self.total_vehicles = total_vehicles
        self.edges = edges
        self.processed_vehicles = []

    def add_vehicles(self, vehicles):
        """Add vehicles to the processed vehicles list."""
        self.processed_vehicles.extend(vehicles)

    def processed(self):
        """Check if more vehicles need to be generated for this route."""
        return self.total_vehicles > len(self.processed_vehicles)

    def __repr__(self):
        return (f"Route(route_id={self.route_id}, "
                f"total_vehicles={self.total_vehicles}, "
                f"edges={self.edges}, "
                f"processed_vehicles={self.processed_vehicles})")


def load_route_data(route_vehicles_file_path, route_edges_file_path) -> dict:
    """Load route data from CSV and JSON files."""
    df = pd.read_csv(route_vehicles_file_path, delimiter=",")
    hours = [col for col in df.columns if col not in ["RUTAS", "Total"]]

    with open(route_edges_file_path, "r") as f:
        edges_data = json.load(f)

    res = {}
    for hour in hours:
        hour_routes = []
        for i, route in enumerate(df["RUTAS"]):
            id_route = f"{int(route)}_{hour}"
            n_vehicles = df[hour][i]

            json_key = f"RUTA_{int(route)}"
            route_edges = []
            if json_key in edges_data:
                edge_str = edges_data[json_key]
                route_edges = [edge.strip()
                               for edge in edge_str.split(",") if edge.strip()]

            new_route = Route(id_route, n_vehicles, route_edges)
            hour_routes.append(new_route)

        total_vh = df[hour].sum()
        res[hour] = (hour_routes, total_vh)
    return res


def find_routes_by_edge(routes, current_id, vehicles, update_routes: dict):
    """Find routes that share edges with the given vehicles."""
    for vh in vehicles:
        for route in routes:
            if route.route_id != current_id:
                if any(edge_id in vh.edges for edge_id in route.edges):
                    if update_routes.get(route.route_id):
                        update_routes[route.route_id].append(vh.vehicle_id)
                    else:
                        update_routes[route.route_id] = [vh.vehicle_id]
    return update_routes


def generate_vehicles_for_hour(start_time, net: Net, target_edges,
                               routes: List[Route], total_vh, start_id: int):
    """Generate vehicles for a specific hour."""
    depart_rate = 3600 / total_vh
    depart_time_list = [start_time + round(i * float(depart_rate), 2)
                        for i in range(int(total_vh))]

    global_vehicles = []
    current_id = start_id
    update_routes = {}

    for route in routes:
        local_vehicles = []
        route_id = route.route_id

        if route_id in update_routes:
            route.add_vehicles(update_routes[route_id])

        while route.processed():
            select_depart = random.choice(depart_time_list)
            select_source_edge_id = random.choice(route.edges)
            select_target_edge = random.choice(target_edges)
            current_edge = net.getEdge(select_source_edge_id)

            try:
                shortest_path = net.getShortestPath(current_edge,
                                                    select_target_edge)[0]
                if shortest_path is None:
                    continue

                path_edges_id = [edge.getID() for edge in shortest_path]
                new_vh = Vehicle(current_id, select_depart, path_edges_id)

                route.add_vehicles([new_vh])
                local_vehicles.append(new_vh)
                current_id += 1
                depart_time_list.remove(select_depart)

            except Exception as e:
                print(f"Error generating path for route {route_id}: {e}")
                continue

        print(f"{route.route_id}: generados {len(local_vehicles)} "
              f"contenidos {len(route.processed_vehicles)}")

        for edge_id in route.edges:
            try:
                edge = net.getEdge(edge_id)
                edge._lanes[0]._length = 10
            except Exception as e:
                print(f"Warning: Could not penalize edge '{edge_id}'. "
                      f"Error: {e}")

        update_routes = find_routes_by_edge(routes, route_id,
                                            local_vehicles, update_routes)
        global_vehicles.extend(local_vehicles)

    return global_vehicles, current_id


def create_route_file(vehicles: List[Vehicle],
                      filename="generated_routes.rou.xml"):
    """Create a SUMO route file from a list of Vehicle objects."""
    root = Element("routes")

    # Add a default vehicle type with lcMode=512
    SubElement(root, "vType", {
        "id": "defaultCar",
        "type": "passenger",
        "accel": "2.6",
        "decel": "4.5",
        "sigma": "0.5",
        "length": "5",
        "minGap": "2.5",
        "maxSpeed": "70",
        "lcMode": "512"
    })

    vehicles_sorted = sorted(vehicles, key=lambda x: x.depart_time)

    for vehicle in vehicles_sorted:
        edges_str = " ".join(vehicle.edges)
        veh_elem = SubElement(root, "vehicle", {
            "id": str(vehicle.vehicle_id),
            "depart": str(vehicle.depart_time),
            "type": "defaultCar"  # assign vType with lcMode=512
        })
        SubElement(veh_elem, "route", {"edges": edges_str})

    xml_str = minidom.parseString(tostring(root)).toprettyxml(indent="    ")

    with open(filename, "w") as f:
        f.write(xml_str)

    print(f"Archivo {filename} creado exitosamente")


if __name__ == "__main__":
    comm = MPI.COMM_WORLD
    rank = comm.Get_rank()
    size = comm.Get_size()

    net = sumolib.net.readNet("osm.net.xml")
    target_edges = [edge for edge in net.getEdges()
                    if not edge.is_fringe() and edge.allows("passenger")]

    if rank == 0:
        hour_route_data: dict = load_route_data("datos_combinados_1.csv",
                                                "rutas_edges_v1.json")
        hours = list(hour_route_data.keys())
        hours_per_process = len(hours) // size
        remainder = len(hours) % size

        distribution = []
        start_idx = 0
        for i in range(size):
            end_idx = start_idx + hours_per_process + (1 if i < remainder else 0)
            process_hours = hours[start_idx:end_idx]
            distribution.append(process_hours)
            start_idx = end_idx
    else:
        hour_route_data = None
        distribution = None

    hour_route_data = comm.bcast(hour_route_data, root=0)
    local_hours = comm.scatter(distribution if rank == 0 else None, root=0)
    all_vehicles = []
    current_id = 0

    for i, hour in enumerate(local_hours):
        routes, total_vh = hour_route_data[hour]
        start_time = 3600 * i
        vehicles, current_id = generate_vehicles_for_hour(start_time,
                                                          net,
                                                          target_edges,
                                                          routes,
                                                          total_vh,
                                                          current_id)
        all_vehicles.extend(vehicles)
        print(f"vehiculos generados en {hour}: {len(vehicles)}")

    gathered_vehicles = comm.gather(all_vehicles, root=0)

    if rank == 0:
        final_vehicles = []
        for vehicle_list in gathered_vehicles:
            final_vehicles.extend(vehicle_list)
        create_route_file(final_vehicles)
        print(f"Total vehicles generated: {len(final_vehicles)}")

