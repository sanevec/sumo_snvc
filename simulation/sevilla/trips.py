""" 
Vehicle route generation module for SUMO traffic simulations. 
This module generates vehicles routes based on input data
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
from typing import List, Set, Tuple
from collections import defaultdict
from xml.etree.ElementTree import Element, SubElement, tostring
from xml.dom import minidom
from mpi4py import MPI
import argparse

class Vehicle:
    """ 
    Represents a vehicle with its route an departure time
    """
    def __init__(self, id, depart_time, edges):
        """  
        Initialize a Vehicle instance

        Args:
            route_id: unique identifier for the vehicle
            depart_time: Simulation time when the vehicle departs (seconds)
            edges: List of edge IDs that form the vehicle's route
        """
        self.vehicle_id = id
        self.depart_time = depart_time 
        self.edges = edges 
    
    
    def __repr__(self):
        """Return a string representation of the Vehicle."""
        return f"Vehicle(vehicle_id={self.vehicle_id}, depart_time={self.depart_time}, edges={self.edges})"


class Route:
    def __init__(self, route_id, total_vehicles, edges):
        """ 
        Initialize a Route instance
        Args:
            route_id: unique identifier for the route
            total_vehicles: number of vehicles assigned to this route
            edges: list of edges ids that form the route 
        """
        self.route_id = route_id
        self.total_vehicles = total_vehicles
        self.edges = edges
        self.processed_vehicles = [] # List of vehicle IDs processed for this route
    
    def add_vehicles(self, id_vh_list):
        """
        Add vehicles to the processed vehicles list.
        
        Args:
            vehicles: List of Vehicle objects to add
        """
        self.processed_vehicles.extend(id_vh_list)

    def processed(self):
        return self.total_vehicles > len(self.processed_vehicles)

    def __repr__(self):
        return f"Route(route_id={self.route_id}, total_vehicles={self.total_vehicles}, edges={self.edges}, processed_vehicles={self.processed_vehicles})"

def load_route_data(route_vehicles_file_path, route_edges_file_path)-> List[Route]:
    """
    Load route data from CSV and JSON files.
    
    Args:
        route_vehicles_file_path: Path to CSV file with vehicle counts per route and hour
        route_edges_file_path: Path to JSON file with edge sequences for each route
        
    Returns:
        Dictionary mapping hours to tuples of (routes, total_vehicles)
    """
    # Read vehicle counts data
    df = pd.read_csv(route_vehicles_file_path, delimiter=",")
    hours = [col for col in df.columns if col not in ['RUTAS', 'Total']]

    # Read route edges data
    with open(route_edges_file_path, "r") as f:
        edges_data = json.load(f)

    res = {}
    for hour in hours:
        hour_routes = []
        for i, route in enumerate(df["RUTAS"]):
            # Create route ID by combining route number and hour
            id_route = f"{int(route)}_{hour}"
            n_vehicles = df[hour][i]

            # Get edges for this route from JSON data
            route_edges = []
            json_key = f'RUTA_{int(route)}'
            if json_key in edges_data:
                edge_str = edges_data[json_key]
                route_edges = [edge.strip() for edge in edge_str.split(',') if edge.strip()]

            # Create Route object and add to hour's routes
            new_route = Route(id_route, n_vehicles, route_edges)
            hour_routes.append(new_route)
        
        # Calculate total vehicles for this hour
        total_vh = df[hour].sum()
        res[hour] = (hour_routes, total_vh)
    return res

def find_routes_by_edge(routes, current_id, vehicles, update_routes:dict):

    """
    Find routes that share edges with the given vehicles.
    
    Args:
        routes: List of all Route objects
        current_id: ID of the current route being processed
        vehicles: List of Vehicle objects to check
        update_routes: Dictionary to accumulate route updates
        
    Returns:
        Updated dictionary mapping route IDs to lists of vehicle IDs
    """
    
    for vh in vehicles:
        for route in routes:
            if route.route_id != current_id: # Skip the current route
                if any(edge_id in vh.edges for edge_id in route.edges):                     
                    # Add vehicle to the update list for this route
                    if update_routes.get(route.route_id):
                        update_routes[route.route_id].append(vh.vehicle_id) 
                    else:
                        update_routes[route.route_id] = [vh.vehicle_id]
    return update_routes

def generate_vehicles_for_hour(start_time, net: Net, target_edges, routes:List[Route], total_vh,
                              start_id: int) -> List[Vehicle]:

    """
    Generate vehicles for a specific hour.
    
    Args:
        start_time: Starting time for this hour (seconds)
        net: SUMO network object
        target_edges: List of valid target edges for vehicles
        routes: List of Route objects for this hour
        total_vh: Total number of vehicles to generate for this hour
        start_id: Starting ID for vehicle numbering
        
    Returns:
        Tuple of (list of generated vehicles, next available vehicle ID)
    """


    depart_rate = 3600 / total_vh
    depart_time_list = [start_time + round(i* float(depart_rate), 2) 
                       for i in range(int(total_vh))]
    
    global_vehicles = []
    current_id = start_id
    update_routes = {}
    
    for route in routes:
        local_vehicles = []

        route_id = route.route_id

        # Add any vehicles from previous routes that share edges with this one
        if route_id in update_routes:
            route.add_vehicles(update_routes[route_id])

        # Generate routes 
        while route.processed():                   
            select_depart = random.choice(depart_time_list)
            select_source_edge_id = random.choice(route.edges)
            select_target_edge = random.choice(target_edges)
            current_edge = net.getEdge(select_source_edge_id)

            try:
                shortest_path = net.getShortestPath(current_edge, select_target_edge)[0]
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
        print(f"{route.route_id}: generados {len(local_vehicles)} contenidos {len(route.processed_vehicles)}")

        # Penalize edges in this route to encourage diversity in future routes
        for edge_id in route.edges:
            net.getEdge(edge_id)._lanes[0]._length = 999999
        
        # Find routes that share edges with the generated vehicles
        update_routes = find_routes_by_edge(routes, route_id, local_vehicles, update_routes)
        
        global_vehicles.extend(local_vehicles)
    
    return global_vehicles, current_id


def create_route_file(vehicles:List[Vehicle], filename="generated_routes.rou.xml", electric_percentage = 0.0):
    """
    Create a SUMO route file from a list of Vehicle objects.
    
    Args:
        vehicles: List of Vehicle objects to include in the file
        filename: Name of the output file
    """
    root = Element('routes')
    print(electric_percentage)
    vtype_regular=  {'id': 'type1', 
         'minGap': '1.5',
         'accel': '3.2', 
         'decel': '6.0',
         'emergencyDecel': '9.0',
         'sigma': '0.7',
         'lcStrategic': '2.5',
         'lcCooperative': '0.1',
         'lcKeepRight': '0.0',
         'lcAssertive': '2.0',
         'lcSpeedGain': '1.0',
         'impatience': '0.9',
         'lcTimeToImpatience': '2.0',
         'lcMode': '512',
         'jmIgnoreFoeProb':'0.8',
         'jmIgnoreFoeSpeed': '10.0',
         'jmSigmaMinor': '0.6',
         'routeChoice': 'true',
         'reroute': 'true',
         'rerouteProbability':'1.0',
         'rerouteInterval': '5.0'         
         }
    SubElement(root, 'vType', vtype_regular)

    vtype_electric = Element('vType', {
        'id': 'EV',
        'minGap': '2.5',
        'maxSpeed': '41.66',
        'emissionClass': 'Energy/unknown',
        'color': 'green',
        'accel': '1',
        'decel': '1',
        'sigma': '0'
    })

    params = [
        ('has.battery.device', 'true'),
        ('device.battery.capacity', '64000'),
        ('device.battery.stoppingTreshold', '0.1'),
        ('allowedPowerIntake', '120000'),
        ('maximumPower', '100000'),
        ('has.stationfinder.device', 'true'),
        ('device.stationfinder.checkEnergyForRoute', 'false'),
        ('device.stationfinder.replacePlannedStop', '0'),
        ('device.stationfinder.waitForCharge', '100'),
        ('device.stationfinder.repeat', '10'),
        ('device.stationfinder.charging.waitingTime.weight', '5'),
        ('device.stationfinder.radius', '300000'),
        ('airDragCoefficient', '0.35'),
        ('constantPowerIntake', '160'),
        ('frontSurfaceArea', '3'),
        ('rotatingMass', '0.01'),
        ('propulsionEfficiency', '0.9'),
        ('radialDragCoefficient', '0.5'),
        ('recuperationEfficiency', '0.9'),
        ('rollDragCoefficient', '0.01'),
        ('mass', '1615')
    ]

    for key, value in params:
        param_elem = SubElement(vtype_electric, 'param', {'key': key, 'value': value})

    root.append(vtype_electric)

    vehicles_sorted = sorted(vehicles, key=lambda x: x.depart_time)

    electric_vehicles = set()
    if electric_percentage > 0:
        num_electric = int(len(vehicles_sorted) * electric_percentage)
        electric_vehicles = set(random.sample(range(len(vehicles_sorted)), num_electric))

    for vehicle in vehicles_sorted:
        edges_str = " ".join(vehicle.edges)
        vehicle_type = "EV" if vehicle.vehicle_id in electric_vehicles else "type1"

        veh_elem = SubElement(root, 'vehicle', {
        'id': str(vehicle.vehicle_id),
        'depart': str(vehicle.depart_time),
        'type': vehicle_type,
        })

        SubElement(veh_elem, "route", {"edges": edges_str})

    xml_str = minidom.parseString(tostring(root)).toprettyxml(indent="    ")

    with open(filename, 'w') as f:

        f.write(xml_str)
    
    print(f"Archivo {filename} creado exitosamente")

def parse_arguments():
    """
        Parse command line arguments.
    """
    parser = argparse.ArgumentParser(description='Generate SUMO vehicle routes with electric vehicle percentage')
    
    parser.add_argument('--net-file', type=str, required=True,
                       help='Path to SUMO network file (e.g., osm.net.xml)')
    
    parser.add_argument('--vehicles-file', type=str, required=True,
                       help='Path to CSV file with vehicle counts (e.g., datos_combinados_1.csv)')
    
    parser.add_argument('--edges-file', type=str, required=True,
                       help='Path to JSON file with route edges (e.g., rutas_edges_v1.json)')
    
    parser.add_argument('--output-file', type=str, default='generated_routes.rou.xml',
                       help='Output route file name (default: generated_routes.rou.xml)')
    
    parser.add_argument('--electric-percentage', type=float, default=0.0,
                       help='Percentage of electric vehicles (0.0 to 1.0, default: 0.0)')
    
    return parser.parse_args()


if __name__ == "__main__":

    args = parse_arguments()

    comm = MPI.COMM_WORLD
    rank = comm.Get_rank()
    size = comm.Get_size()


    net = sumolib.net.readNet(args.net_file)
    #net = sumolib.net.readNet("lc/osm.net.xml")
    
    target_edges = [edge for edge in net.getEdges() 
                if not edge.is_fringe() 
                        and edge.allows("passenger")]

    if rank == 0:
        hour_route_data:dict = load_route_data(args.vehicles_file, args.edges_file)
        #hour_route_data:dict = load_route_data('parseEdges/datos_combinados_1.csv', 'lc/rutas_edges_v1.json') 

        hours = list(hour_route_data.keys())
        hours_per_process = len(hours) // size  # Distribute hours evenly among processes
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
        hour_data = hour_route_data[hour]
        routes, total_vh = hour_data
        start_time = 3600*i
        vehicles, current_id = generate_vehicles_for_hour(start_time,
            net, target_edges, routes, total_vh, current_id)
        
        #vehicles, current_id = generate_vehicles_for_hour(start_time,
        #    net, target_edges, routes, total_vh, current_id)
        
        all_vehicles.extend(vehicles)
        print(f"vehiculos generados en {hour}: {len(vehicles)}")

    gathered_vehicles = comm.gather(all_vehicles, root=0)

    if rank == 0:
        final_vehicles = []
        for vehicle_list in gathered_vehicles:
            final_vehicles.extend(vehicle_list)
        create_route_file(final_vehicles, args.output_file, args.electric_percentage)

        
        print(f"Total vehicles generated: {len(final_vehicles)}")
