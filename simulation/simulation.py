# -*- coding: utf-8 -*-
#
# Author: Juan Alberto Gallardo Gómez <jgallardo7@us.es>
# Date: 2025
# Description: Script to run SUMO simulations.
# License: Eclipse Public License - v 2.0 (EPL-2.0)
#
# Usage: Run with `--help` to see available command-line options.

import sys
import os
# Read the SUMO_HOME environment variable
SUMO_HOME = os.environ.get("SUMO_HOME")

if SUMO_HOME is None:
    raise EnvironmentError("The SUMO_HOME environment variable is not defined.")

# Build the path to the tools/ folder inside SUMO_HOME
tools_path = os.path.join(SUMO_HOME, "tools")

# Add it to sys.path if not already present
if tools_path not in sys.path:
    sys.path.append(tools_path)

import traci
import emissions
import reroutings
import charging_metrics
import traffic_metrics

import math
from datetime import datetime
import re
import itertools
import argparse
import json
import xml.etree.ElementTree as ET

def expand_grid(flat_config):
    """
    Expands a flat configuration dictionary into all combinations of its list values.
    Each key in the dictionary can either be a scalar or a list.
    If a key's value is a list, it will be expanded into multiple configurations.
    Returns a generator yielding dictionaries with all combinations.
    """
    grid_keys = []
    grid_values = []

    for k, v in flat_config.items():
        if isinstance(v, list):
            grid_keys.append(k)
            grid_values.append(v)
        else:
            # Wrap scalar values into a list
            grid_keys.append(k)
            grid_values.append([v])

    for combination in itertools.product(*grid_values):
        yield dict(zip(grid_keys, combination))

def folder_setup(param_dict, file_names, port=''):
    """
    Creates a timestamped folder, copies the given files into it, and writes params.txt.

    Parameters:
        FOLDER (str): Path to the folder containing the original files (must end with '/')
        param_dict (dict): Dictionary of parameters to be written to params.txt
        file_names (list): List of filenames to copy from FOLDER to the new folder

    Returns:
        str: Path to the created folder
    """
    # Generate date prefix: YYMMDD
    date_prefix = datetime.now().strftime("%y%m%d")

    # Look for existing runs with same date prefix
    runs_dir = "runs/"
    os.makedirs(runs_dir, exist_ok=True)
    existing = [d for d in os.listdir(runs_dir) if os.path.isdir(os.path.join(runs_dir, d)) and d.startswith(date_prefix)]

    # Count how many runs already exist for today
    n = len(existing) + 1
    folder_name = f"{date_prefix}-{n}"
    folder_path = os.path.join(runs_dir, folder_name) + port + "/"
    os.makedirs(folder_path, exist_ok=True)

    # Copy files
    for name in file_names:
        src_path = FOLDER + name
        dst_path = folder_path + name
        
        with open(src_path, 'r', encoding='utf-8') as f_in:
            content = f_in.read()

        with open(dst_path, 'w', encoding='utf-8') as f_out:
            f_out.write(content)

    # Write params.txt
    with open(folder_path + "params.txt", 'w', encoding='utf-8') as f:
        for key, value in param_dict.items():
            f.write(f"{key}={value}\n")

    print(f"Created folder: {folder_path}")
    return folder_path

def add_charging_stations():    
    edge_ids = obtain_edge_ids_no_roundabouts()   
    for cs in CS_LIST:
        #edge_id = edge_ids[cs]
        edge_id = cs
        if edge_id not in edge_ids:
            print(f"Edge ID {edge_id} not found in the edges file. Skipping charging station addition.")
            continue
        #print('Index: '+str(cs)+', Edge ID: '+str(edge_id))
        print('Adding CS to Edge ID: '+str(edge_id))
        # Now we have the edge_id where we want to add the charging station
        # First, we need to get the point in the edge where we want to place the charging station starting node
        edge_xml = get_edge_block(edge_id)
        shape_points = extract_shape_coords(edge_xml)        
        if shape_points:
            # If the edge has a shape, we have to use the middle point of the shape
            mid_point = compute_middle_point(shape_points)
            if mid_point:
                xm, ym = mid_point
            else:
                print(f"Error computing middle point for edge {edge_id}.")
                continue
        else:
            # If the edge does not have a shape, we have to calculate the middle point using the from and to nodes
            from_node, to_node = get_edge_nodes(edge_id)
            node_coords = load_nodes()
            if from_node in node_coords and to_node in node_coords:
                x1, y1 = node_coords[from_node]
                x2, y2 = node_coords[to_node]
                xm = (x1 + x2) / 2
                ym = (y1 + y2) / 2
            else:
                print(f"Error: Nodes {from_node} or {to_node} not found.")
                continue
        # Once we have xm and ym, we can add the node to the nodes file
        node_id = f"cs_{edge_id}"
        add_node_to_xml(NODES_FILE, node_id, xm, ym)
        # Now we can split the edge by changing the attributes of the current edge in the XML file and duplicating it
        first_half_edge = replace_attribute(edge_xml, "id", f"first_{edge_id}")
        first_half_edge = replace_attribute(first_half_edge, "to", node_id)
        second_half_edge = replace_attribute(edge_xml, "id", f"second_{edge_id}")
        second_half_edge = replace_attribute(second_half_edge, "from", node_id)
        # If the edge has a shape, we need to split it into two halves and change the shape attributes accordingly
        if shape_points:
            mid_point = (xm, ym)
            # Split shape into two halves
            n = len(shape_points)
            mid_index = n // 2
            first_half = shape_points[:mid_index+1]
            second_half = shape_points[mid_index:]
            # Ensure mid_point is included in both halves
            if first_half[-1] != mid_point:
                first_half.append(mid_point)
            if second_half[0] != mid_point:
                second_half.insert(0, mid_point)
            # Build new shape strings
            new_shape1 = "".join(f"{x},{y} " for x, y in first_half)
            new_shape2 = "".join(f"{x},{y} " for x, y in second_half)
            first_half_edge = replace_attribute(first_half_edge, "shape", new_shape1[:-1])
            second_half_edge = replace_attribute(second_half_edge, "shape", new_shape2[:-1])
        # Now we replace the old edge block in the edges file with the two new edges
        replace_xml_block_in_file(EDGES_FILE, edge_xml, first_half_edge + second_half_edge)
        # And finally, we add the charging station structure
        if shape_points:
            x1, y1 = first_half[0]
            x2, y2 = second_half[-1]
        length = 65
        offset = 55
        x1, y1, x2, y2 = generate_parallel_segment_offset_from_point(x1, y1, x2, y2, xm, ym, length, offset)
        add_charging_station(edge_id, cs, x1, y1, x2, y2, length)
    print('Charging stations added successfully')

def replace_routes():
    """Replace edge IDs in CS_LIST inside ROUTES_FILE.
    Handles routes inside <vehicle> and routes defined directly under <routes> root.
    Maintains the original order of edges.
    """
    
    # Parse the XML file
    tree = ET.parse(ROUTES_FILE)
    root = tree.getroot()

    # --- 1. Replace edges inside vehicles ---
    for vehicle in root.findall('vehicle'):
        route = vehicle.find('route')
        if route is not None:
            edges = route.attrib.get('edges', "")
            edge_ids = edges.split()
            modified_edges = [
                f"first_{eid} second_{eid}" if eid in CS_LIST else eid
                for eid in edge_ids
            ]
            route.attrib['edges'] = " ".join(modified_edges)

    # --- 2. Replace edges in routes defined directly under root ---
    for route in root.findall('route'):
        edges = route.attrib.get('edges', "")
        edge_ids = edges.split()
        modified_edges = [
            f"first_{eid} second_{eid}" if eid in CS_LIST else eid
            for eid in edge_ids
        ]
        route.attrib['edges'] = " ".join(modified_edges)

    # Write back the modified XML
    tree.write(ROUTES_FILE, encoding="utf-8", xml_declaration=True)

def replace_routes2():
    """Replace whole word occurrences of each edge ID in CS_LIST inside ROUTES_FILE 
    with 'first_<id> second_<id>', while maintaining the original order of edges."""
    
    # Parse the XML file
    tree = ET.parse(ROUTES_FILE)
    root = tree.getroot()

    # Iterate over all vehicle elements
    for vehicle in root.findall('vehicle'):
        # Find the route element within the vehicle
        route = vehicle.find('route')
        if route is not None:
            # Get the value of the 'edges' attribute
            edges = route.attrib.get('edges', "")
            
            # Split the edges into a list of edge IDs
            edge_ids = edges.split()

            # Create a new list to store the modified edge IDs, while preserving order
            modified_edges = []

            # Iterate over each edge ID in the original order
            for edge_id in edge_ids:
                # Check if the edge ID is in the CS_LIST
                if edge_id in CS_LIST:
                    # Replace with the desired format 'first_<id> second_<id>'
                    modified_edges.append(f"first_{edge_id} second_{edge_id}")
                else:
                    # Otherwise, keep the edge ID as it is
                    modified_edges.append(edge_id)

            # Join the modified edge IDs back into a single string, maintaining the original order
            route.attrib['edges'] = " ".join(modified_edges)

    # Write the modified XML back to the file
    tree.write(ROUTES_FILE, encoding="utf-8", xml_declaration=True)

def fix_connections(file):
    """Fix connections file by renaming edges in CS_LIST"""
    tree = ET.parse(file)
    root = tree.getroot()

    for conn in root.findall("connection"):
        # Check 'from'
        from_edge = conn.get("from")
        if from_edge in CS_LIST:
            conn.set("from", f"second_{from_edge}")

        # Check 'to'
        to_edge = conn.get("to")
        if to_edge in CS_LIST:
            conn.set("to", f"first_{to_edge}")

    # Save back to the same file
    tree.write(file, encoding="utf-8", xml_declaration=True)

def obtain_edge_ids():
    '''
    Obtains all edge IDs from the edges file and returns them as a list.
    '''
    edge_ids = []
    with open(EDGES_FILE, "r") as f:
        content = f.read()
        lines = content.splitlines()
        for line in lines:
            if '<edge id="' in line:
                start = line.find('id="') + 4
                end = line.find('"', start)
                edge_id = line[start:end]
                edge_ids.append(edge_id)
    return edge_ids

def obtain_edge_ids_no_roundabouts():
    '''
    Obtains all edge IDs from the edges file and returns them as a list,
    excluding those that belong to roundabouts.
    '''
    edge_ids = []
    roundabout_edges = set()

    with open(EDGES_FILE, "r", encoding="utf-8") as f:
        content = f.read()
        lines = content.splitlines()

        # First pass: find all roundabout edges
        for line in lines:
            if '<roundabout ' in line:
                start = line.find('edges="') + 7
                end = line.find('"', start)
                edges_str = line[start:end]
                for edge in edges_str.split():
                    roundabout_edges.add(edge)

        # Second pass: collect edges excluding roundabouts
        for line in lines:
            if '<edge id="' in line:
                start = line.find('id="') + 4
                end = line.find('"', start)
                edge_id = line[start:end]
                if edge_id not in roundabout_edges:
                    edge_ids.append(edge_id)

    return edge_ids

def get_edge_nodes(edge_id):
    '''
    Returns the from and to nodes of an edge given its ID.
    '''
    pattern = re.compile(
        r'<edge[^>]*id="' + re.escape(edge_id) + r'"[^>]*from="([^"]+)"[^>]*to="([^"]+)"'
    )
    
    with open(EDGES_FILE, 'r', encoding='utf-8') as f:
        for line in f:
            match = pattern.search(line)
            if match:
                from_node = match.group(1)
                to_node = match.group(2)
                return from_node, to_node

    return None, None

def load_nodes():
    '''
    Loads all nodes from the nodes file and returns a dictionary with node IDs as keys
    and their coordinates as values.
    '''
    node_coords = {}
    node_re = re.compile(
        r'<node[^>]*id="([^"]+)"[^>]*x="([^"]+)"[^>]*y="([^"]+)"'
    )

    with open(NODES_FILE, 'r', encoding='utf-8') as f:
        for line in f:
            m = node_re.search(line)
            if m:
                node_id = m.group(1)
                x = float(m.group(2))
                y = float(m.group(3))
                node_coords[node_id] = (x, y)

    return node_coords

def get_edge_block(edge_id):
    '''
    Returns the XML block of an edge given its ID.
    If the edge is not found, returns None.
    '''
    edge_start_re = re.compile(
        r'<edge\b[^>]*\bid="' + re.escape(edge_id) + r'"'
    )
    
    in_edge = False
    block_lines = []
    
    with open(EDGES_FILE, 'r', encoding='utf-8') as f:
        for line in f:
            if not in_edge:
                if edge_start_re.search(line):
                    in_edge = True
                    block_lines.append(line)
                    # Check if ends in same line
                    if '/>' in line:
                        in_edge = False
                        break
            else:
                block_lines.append(line)
                if '</edge>' in line:
                    in_edge = False
                    break

    if block_lines:
        return ''.join(block_lines)
    else:
        return None

def add_charging_station(edge_id, cs_group, x1, y1, x2, y2, lane_length):
    '''
    Adds a charging station to the network by creating the necessary nodes and edges.
    The charging station consists of a start node, an end node, and a lane with multiple
    charging points. The function also adds the charging station to the additional.xml file.
    '''
    cs_start = f"cs_start_{edge_id}"
    cs_end = f"cs_end_{edge_id}"
    add_node_to_xml(NODES_FILE, cs_start, x1, y1)
    add_node_to_xml(NODES_FILE, cs_end, x2, y2)  
    lanes = "".join(f'<lane index="{i}" speed="13.89"/>' for i in range(CS_SIZE))
    edges = f"""
    <edge id="to_cs_{edge_id}" from="cs_{edge_id}" to="{cs_start}" priority="-1">
        <lane index="0" speed="13.89"/>
    </edge>
    <edge id="cs_lanes_{edge_id}" from="{cs_start}" to="{cs_end}" priority="1" numLanes="{CS_SIZE+1}">
        {lanes}
        <lane index="{CS_SIZE}" speed="13.89"/> 
    </edge>
    <edge id="from_cs_{edge_id}" from="{cs_end}" to="cs_{edge_id}" priority="-1">
        <lane index="0" speed="13.89"/>
    </edge>     
    """
    charging_points = "".join(
        f'\n<chargingStation id="cs_{edge_id}_{i}" lane="cs_lanes_{edge_id}_{i}" startPos="{lane_length-15}" endPos="{lane_length-10}" friendlyPos="true" power="{CS_POWER[0]}">'
        f'\n    <param key="group" value="{cs_group}"/>'
        f'\n    <param key="chargingPort" value="CCS2"/>'
        f'\n    <param key="allowedPowerOutput" value="{CS_POWER[0]}"/>'
        f'\n    <param key="groupPower" value="{int(CS_POWER[0]*CS_SIZE*CS_POWER[1])}"/>'
        f'\n    <param key="chargeDelay" value="5"/>'
        f'\n</chargingStation>' for i in range(CS_SIZE))
    add_edge_to_xml(EDGES_FILE, edges)
    add_cs_to_xml(ADDITIONAL_FILE, charging_points)
        
def add_node_to_xml(file_path, node_id, x, y):
    """
    Appends a <node> element to the XML file before the closing </nodes> tag.

    Parameters:
        file_path (str): Path to the nodes.xml file.
        node_id (str): ID of the new node.
        x (float): X coordinate of the new node.
        y (float): Y coordinate of the new node.
    """
    # Read the file content
    with open(file_path, 'r', encoding='utf-8') as f:
        lines = f.readlines()

    # Create the new node line
    new_node_line = f'    <node id="{node_id}" x="{x}" y="{y}" />\n'

    # Insert the new node before </nodes>
    with open(file_path, 'w', encoding='utf-8') as f:
        for line in lines:
            if line.strip() == "</nodes>":
                f.write(new_node_line)
            f.write(line)

    print(f'Node "{node_id}" added to {file_path}.')

def add_edge_to_xml(file_path, edge_block):
    """
    Appends an <edge> block to the XML file before the closing </edges> tag.

    Parameters:
        file_path (str): Path to the edges.xml file.
        edge_block (str): XML text of the edge block (can be multiline).
    """
    with open(file_path, 'r', encoding='utf-8') as f:
        lines = f.readlines()

    with open(file_path, 'w', encoding='utf-8') as f:
        for line in lines:
            if line.strip() == "</edges>":
                f.write(edge_block.rstrip() + "\n")
            f.write(line)

    print(f'Edge block added to {file_path}.')

def add_cs_to_xml(file_path, cs_block):
    """
    Appends an <chargingStation> block to the XML file before the closing </additional> tag.

    Parameters:
        file_path (str): Path to the additional.xml file.
        cs_block (str): XML text of the charging station block (can be multiline).
    """
    with open(file_path, 'r', encoding='utf-8') as f:
        lines = f.readlines()

    with open(file_path, 'w', encoding='utf-8') as f:
        for line in lines:
            if line.strip() == "</additional>":
                f.write(cs_block.rstrip() + "\n")
            f.write(line)

    print(f'Charging station block added to {file_path}.')

def replace_xml_block_in_file(file_path, old_block, new_block):
    """
    Replaces a block of XML text in a file.

    Parameters:
        file_path (str): Path to the XML file.
        old_block (str): Exact XML block to be replaced.
        new_block (str): New XML block to insert in place.

    Returns:
        bool: True if replacement was successful, False otherwise.
    """
    # Read the entire file content
    with open(file_path, 'r', encoding='utf-8') as f:
        content = f.read()

    # Check if the old block exists in the file
    if old_block not in content:
        print("The block to replace was not found.")
        return False

    # Replace the block
    updated_content = content.replace(old_block, new_block)

    # Write the updated content back to the file
    with open(file_path, 'w', encoding='utf-8') as f:
        f.write(updated_content)

    print("Block replaced successfully.")
    return True

def extract_shape_coords(edge_xml_text):
    """
    If the edge XML block contains a shape attribute, this function extracts the coordinates
    and returns them as a list of tuples (x, y). If no shape is found, returns None.
    """
    shape_re = re.compile(r'shape="([^"]+)"')
    m = shape_re.search(edge_xml_text)
    if not m:
        return None
    
    shape_str = m.group(1)
    points = []
    for pair in shape_str.strip().split():
        x_str, y_str = pair.split(',')
        points.append((float(x_str), float(y_str)))
    return points

def compute_middle_point(shape_points):
    """
    Returns the middle point of a list of shape points.
    If the list is empty, returns None.
    """
    n = len(shape_points)
    if n == 0:
        return None
    mid_index = n // 2
    return shape_points[mid_index]

def replace_attribute(xml_text, attr_name, new_value):
    """
    Replaces the value of an attribute in an XML block.
    """
    regex = re.compile(r'(' + re.escape(attr_name) + r')="[^"]*"')
    new_text, count = regex.subn(r'\1="{}"'.format(new_value), xml_text, count=1)
    if count == 0:
        # Atributo no existe → lo añadimos
        new_text = new_text.rstrip('/>\n ') + f' {attr_name}="{new_value}" />\n'
    return new_text

def generate_parallel_segment_offset_from_point(x1, y1, x2, y2, xp, yp, length=65, offset=55):
    """
    Given a reference segment AB and a point P, generate a new segment (Q1–Q2) that:
    - Is parallel to AB
    - Is at a perpendicular distance `offset` from P
    - Has same length as AB (or a fixed one if 'length' is given)
    - Forms a triangle with vertex P

    Parameters:
        x1, y1: coordinates of point A (start of AB)
        x2, y2: coordinates of point B (end of AB)
        xp, yp: coordinates of point P
        length: optional fixed length for the parallel segment
        offset: distance from P to the new segment (perpendicular displacement)

    Returns:
        (qx1, qy1), (qx2, qy2): coordinates of the new parallel segment
    """
    # Vector AB
    dx = x2 - x1
    dy = y2 - y1
    mag = math.hypot(dx, dy)
    if mag == 0:
        raise ValueError("Points A and B cannot be the same.")

    # Normalize AB
    dx /= mag
    dy /= mag

    # Length of the new segment
    seg_len = length if length is not None else mag

    # Vector perpendicular to AB (rotated +90°)
    perp_dx = dy
    perp_dy = -dx

    # Compute midpoint of the new segment, offset from P
    mx = xp + perp_dx * offset
    my = yp + perp_dy * offset

    # Half-length vector in AB direction
    half_len = seg_len / 2
    dx_half = dx * half_len
    dy_half = dy * half_len

    # Get the two endpoints
    qx1 = mx - dx_half
    qy1 = my - dy_half
    qx2 = mx + dx_half
    qy2 = my + dy_half

    return qx1, qy1, qx2, qy2

############################################

def run_simulation(port):
    # Start the SUMO simulation
    traci.start([SUMO_HOME+SUMO_BINARY, "-c", CONFIG_FILE], port=port)
    
    # Initialize the simulation information
    simulationData = emissions.get_initial_simulation_information(saveBuildings=False, saveVegetation=False, networkFilePath=NETWORK_FILE)
    reroutingData = reroutings.new_rerouting_data()
    vehicleEmissions = {}
    vehList = []

    # Execute the simulation loop
    while traci.simulation.getMinExpectedNumber() > 0:
        traci.simulationStep()
        sim_time = traci.simulation.getTime()          

        # --- Per-vehicle tick update (time-only logic) ---
        for veh in traci.vehicle.getIDList():
            vtype = traci.vehicle.getTypeID(veh)
            if vtype == "EV":              
                has_stationfinder = traci.vehicle.getParameter(veh, "has.stationfinder.device")
                has_battery = traci.vehicle.getParameter(veh, "has.battery.device")
                #print(f"Vehicle {veh} has_stationfinder: {has_stationfinder}, has_battery: {has_battery}")
                if has_stationfinder == "true" and has_battery == "true":               
                    # Get the current s and b values
                    csId_stationfinder = traci.vehicle.getParameter(veh, "device.stationfinder.chargingStation")  # 's'
                    csId_battery = traci.vehicle.getParameter(veh, "device.battery.chargingStationId")  # 'b'
                    reroutings.tick_update_vehicle(reroutingData,veh,csId_stationfinder,csId_battery,sim_time)
                    # If the EV is looking for a station, teleporting is disabled
                    if csId_stationfinder != "":
                        wt=traci.vehicle.getWaitingTime(veh)
                        if wt == 49:
                            print(f"Vehicle {veh} has waiting time {wt} at time {sim_time}")
                            x,y = traci.vehicle.getPosition(veh)
                            angle = traci.vehicle.getAngle(veh)
                            xb, yb = step_back(x,y,angle)
                            # Move the vehicle slightly to reset waiting time
                            print(f"Moving vehicle {veh} slightly to reset waiting time with angle {angle}")
                            traci.vehicle.moveToXY(veh, "", 0, xb, yb, angle=angle, keepRoute=1)

        # Vehicles which are starting to charge        
        for veh in traci.simulation.getStopStartingVehiclesIDList():
            vtype = traci.vehicle.getTypeID(veh)
            if vtype == "EV":
                csId = traci.vehicle.getParameter(veh, "device.battery.chargingStationId")
                reroutings.handle_arrival(reroutingData,veh,csId,sim_time)            
                vehList.append(veh)
                traci.chargingstation.setParameter(csId, "desiredPower", 0)
                traci.chargingstation.setParameter(csId, "aliquotPowerAdjustment", 1)

        # Vehicles which are ending to charge
        for veh in traci.simulation.getStopEndingVehiclesIDList():
            vtype = traci.vehicle.getTypeID(veh)
            if vtype == "EV":
                vehList.remove(veh)

        # Set power adjustments
        calculateAliquotPowerAdjustments(vehList)
        setChargingStationPowers(vehList)
        # Get vehicle emissions at this step
        vehicleEmissions[int(traci.simulation.getTime())] = emissions.get_instant_vehicle_emissions(simulationData)

    # Get the final simulation information
    emissions.get_final_simulation_information(simulationData, vehicleEmissions)
    reroutingResult = reroutings.finalize_json(reroutingData)
    reroutings.dump_json(reroutingResult, WORKING_FOLDER + "rerouting_metrics.json")

    # Close the simulation
    traci.close()

    # Extract metrics and save output data
    emissions.save_output_data(simulationData, vehicleEmissions, WORKING_FOLDER)
    charging_metrics.extract_charging_metrics_from_sumocfg(CONFIG_FILE, WORKING_FOLDER + "charging_metrics.json", CS_SIZE)
    traffic_metrics.extract_traffic_metrics_from_sumocfg(CONFIG_FILE, WORKING_FOLDER + "traffic_metrics.json")

def step_back(x: float, y: float, angle_deg: float):
    """
    Returns the point located 1 unit backwards from (x, y),
    using the convention: +x = right, +y = up;
    0° = facing up, 90° = facing right, 180° = facing down, 270° = facing left.
    Angles increase clockwise.
    """
    a = math.radians(angle_deg % 360)
    nx = x - math.sin(a)
    ny = y - math.cos(a)
    return nx, ny

def remove_files(WORKING_FOLDER, files_to_remove):
    """
    Delete a list of files inside a given folder.

    Parameters:
        WORKING_FOLDER (str): Path to the folder (must end with '/')
        files_to_remove (list): List of filenames to delete
    """
    for filename in files_to_remove:
        filepath = WORKING_FOLDER + filename
        try:
            if os.path.exists(filepath):
                os.remove(filepath)
                print(f"Deleted: {filepath}")
            else:
                print(f"File not found: {filepath}")
        except Exception as e:
            print(f"Error deleting {filepath}: {e}")

def calculateAliquotPowerAdjustments(vehList):
    csDict = {}
    for veh in vehList:
        csId = traci.vehicle.getParameter(veh, "device.battery.chargingStationId")
        group = traci.chargingstation.getParameter(csId, "group")
        if group in csDict: csDict[group] += [csId]
        else: csDict[group] = [csId]
    for key in csDict:
        csGroup = csDict[key]
        maxPower = int(traci.chargingstation.getParameter(csGroup[0], "groupPower"))
        sumDesired = 0
        for csId in csGroup:
            desired = traci.chargingstation.getParameter(csId, "desiredPower")
            sumDesired += float(desired)
        factor = 1
        if sumDesired > maxPower:
            factor = maxPower / sumDesired
        for csId in csGroup:
            traci.chargingstation.setParameter(csId, "aliquotPowerAdjustment", factor)

def setChargingStationPowers(vehList):
    for veh in vehList:
        csId = traci.vehicle.getParameter(veh,"device.battery.chargingStationId")
        actualBattery = float(traci.vehicle.getParameter(veh,"device.battery.actualBatteryCapacity"))
        maxBattery = float(traci.vehicle.getParameter(veh,"device.battery.maximumBatteryCapacity"))
        maxPsoc = 1.1 * maxBattery * (110 - 100 * actualBattery/maxBattery) / 33
        maxPcp = float(traci.chargingstation.getParameter(csId,"allowedPowerOutput"))
        maxPev = float(traci.vehicletype.getParameter(traci.vehicle.getTypeID(veh),"allowedPowerIntake"))
        traci.chargingstation.setParameter(csId, "power", min(maxPsoc, maxPcp, maxPev))
        power = min(maxPsoc, maxPcp, maxPev)
        traci.chargingstation.setParameter(csId, "desiredPower", power)
        factor = float(traci.chargingstation.getParameter(csId, "aliquotPowerAdjustment"))
        actualPower = power * factor
        traci.chargingstation.setParameter(csId, "power", actualPower)
        #print(f"Estacion {csId} tiene power: {actualPower}, maxPsoc: {maxPsoc}, maxPcp: {maxPcp}, maxPev: {maxPev}, factor: {factor}")

def run_debug():
    traci.start([os.environ["SUMO_HOME"]+SUMO_BINARY, "-c", CONFIG_FILE])
    while traci.simulation.getMinExpectedNumber() > 0:
        traci.simulationStep()    
        for veh in traci.vehicle.getIDList():
            capacity = float(traci.vehicle.getParameter(veh, "device.battery.capacity"))
            currentCharge = float(traci.vehicle.getParameter(veh, "device.battery.chargeLevel"))
            stateOfCharge = currentCharge / capacity 
            #print('Vehículo: ' + veh + ' SOC: ' + str(stateOfCharge))
            #if stateOfCharge < 0.4:

            route = traci.vehicle.getRoute(veh)
            csId_stationfinder = traci.vehicle.getParameter(veh, "device.stationfinder.chargingStation")
            csId_battery = traci.vehicle.getParameter(veh, "device.battery.chargingStationId")
            print(f"Vehículo {veh} tiene ruta: {route} y battery: {csId_battery} y stationfinder: {csId_stationfinder}")  
            if csId_stationfinder != "" and csId_battery == "NULL":
                print(f"Rerutado {veh} tiene ruta: {route} y battery: {csId_battery} y stationfinder: {csId_stationfinder}")
                #traci.vehicle.setParameter(veh, "device.battery.chargingStationId", csId_stationfinder)
            
        for veh in traci.simulation.getStopStartingVehiclesIDList():
            csId = traci.vehicle.getParameter(veh, "device.battery.chargingStationId")
            print('Empezando parada coche: '+ veh + ' csId: ' + csId)
                
        for veh in traci.simulation.getStopEndingVehiclesIDList():
            csId = traci.vehicle.getParameter(veh, "device.battery.chargingStationId")
            print('Saliendo parada coche: '+ veh + ' csId: ' + csId)
            
    traci.close()

def run_debug2():
    data = reroutings.new_rerouting_data()

    traci.start([os.environ["SUMO_HOME"] + SUMO_BINARY, "-c", CONFIG_FILE])
    
    while traci.simulation.getMinExpectedNumber() > 0:
        traci.simulationStep()
        sim_time = traci.simulation.getTime()

        # --- Per-vehicle tick update (time-only logic) ---
        for veh in traci.vehicle.getIDList():
            csId_stationfinder = traci.vehicle.getParameter(veh, "device.stationfinder.chargingStation")  # 's'
            csId_battery = traci.vehicle.getParameter(veh, "device.battery.chargingStationId")  # 'b'

            reroutings.tick_update_vehicle(data,veh,csId_stationfinder,csId_battery,sim_time)

        # --- Arrivals (start of stop = arrival to final CS) ---
        for veh in traci.simulation.getStopStartingVehiclesIDList():
            csId = traci.vehicle.getParameter(veh, "device.battery.chargingStationId")
            reroutings.handle_arrival(data,veh,csId,sim_time)

    # ---- finalize + dump ----
    result = reroutings.finalize_json(data)
    reroutings.dump_json(result, WORKING_FOLDER + "rerouting_metrics.json")

    traci.close()

def run(config, port=8816):
    # netconvert --sumo-net-file network.net.xml --plain-output-prefix network
    # Set up paths and files based on the configuration
    global FOLDER, WORKING_FOLDER, NODES_FILE, EDGES_FILE, ADDITIONAL_FILE
    global CON_FILE, TLL_FILE, NETWORK_FILE, CS_LIST, CS_SIZE, CS_POWER, ROUTES_FILE
    global SUMO_BINARY, CONFIG_FILE, POLY_FILE

    FOLDER = config["FOLDER"]
    file_list = [f for f in os.listdir(FOLDER) if os.path.isfile(os.path.join(FOLDER, f))]
    WORKING_FOLDER = folder_setup(config, file_list, '_'+str(port))        
    NODES_FILE = WORKING_FOLDER + config["NODES_FILE"]
    EDGES_FILE = WORKING_FOLDER + config["EDGES_FILE"]    
    
    ADDITIONAL_FILE = WORKING_FOLDER + config["ADDITIONAL_FILE"]
    NETWORK_FILE = WORKING_FOLDER + config["NETWORK_FILE"]

    # Add charging stations
    CS_LIST = config["CS_LIST"]
    CS_SIZE = config["CS_SIZE"]
    CS_POWER = config["CS_POWER"]
    add_charging_stations()

    # Replace routes file
    ROUTES_FILE = WORKING_FOLDER + config["ROUTES_FILE"]
    replace_routes()

    # Fix connections file
    CON_FILE = WORKING_FOLDER + config["CON_FILE"]
    fix_connections(CON_FILE)
    TLL_FILE = WORKING_FOLDER + config["TLL_FILE"]
    fix_connections(TLL_FILE)
    POLY_FILE = WORKING_FOLDER + config.get("POLY_FILE", "")

    # Convert network files
    os.system(SUMO_HOME+"/bin/netconvert --node-files "+NODES_FILE+" --edge-files "+EDGES_FILE+" --connection-files "+CON_FILE+" --tllogic-files "+TLL_FILE+" --output-file "+NETWORK_FILE) 
    
    # Run SUMO simulation
    SUMO_BINARY = config["SUMO_BINARY"]
    CONFIG_FILE = WORKING_FOLDER + config["CONFIG_FILE"]      
    run_simulation(port)

    # Clean up temporary files
    remove_files('', [NETWORK_FILE, EDGES_FILE, NODES_FILE, ADDITIONAL_FILE, ROUTES_FILE, CON_FILE, TLL_FILE, POLY_FILE, CONFIG_FILE])
    #ouput_files = [WORKING_FOLDER+f for f in os.listdir(WORKING_FOLDER) if f.startswith('output')]
    #remove_files('', ouput_files)

    # Print summary or calculate combined metric for genetic algorithm optimization
    return WORKING_FOLDER  

if __name__ == "__main__":
  
    parser = argparse.ArgumentParser(
        description="Run SUMO with configuration file containing global parameters.",
        formatter_class=argparse.RawTextHelpFormatter
    )
    parser.add_argument(
        "--config",
        type=str,
        required=True,
        help=(
            "Path to a JSON file with the following required keys:\n"
            "  SUMO_BINARY      (str)          → path to SUMO binary (e.g. '/bin/sumo-gui')\n"
            "  FOLDER           (str)          → input folder with SUMO network files\n"
            "  CONFIG_FILE      (str)          → .sumocfg file name used in each run\n"
            "  NODES_FILE       (str)          → .nod.xml file name used in each run\n"
            "  EDGES_FILE       (str)          → .edg.xml file name used in each run\n"
            "  CON_FILE         (str)          → .con.xml file name used in each run\n"
            "  TLL_FILE         (str)          → .tll.xml file name used in each run\n"
            "  ADDITIONAL_FILE  (str)          → .add.xml file name used in each run\n"
            "  POLY_FILE        (str)          → .poly.xml file name used in each run (optional, can be empty string)\n"
            "  NETWORK_FILE     (str)          → .net.xml file name used in each run\n"
            "  ROUTES_FILE      (str)          → .rou.xml file name used in each run\n"
            "  CS_LIST          (list of str)  → list of edges for charging stations\n"
            "  CS_SIZE          (int)          → number of charging lanes per station group (= per edge)\n"
            "  CS_POWER         (list of int)  → charging point power and charging station power factor (size*power*factor)\n"
            "If any are lists, the script will perform a grid search over all combinations."
        )
    )
    args = parser.parse_args()

    with open(args.config, "r", encoding="utf-8") as f:
        base_config = json.load(f)

    # Define the set of required keys
    required_keys = [
        "SUMO_BINARY",
        "FOLDER",
        "CONFIG_FILE",
        "NODES_FILE",
        "EDGES_FILE",
        "CON_FILE",
        "TLL_FILE",
        "ADDITIONAL_FILE",
        "NETWORK_FILE",
        "ROUTES_FILE",
        "CS_LIST",
        "CS_SIZE",
        "CS_POWER"
    ]

    # Check if any required key is missing
    missing_keys = required_keys - base_config.keys()

    if missing_keys:
        raise ValueError(f"Missing required configuration keys: {', '.join(missing_keys)}")

    # Obtain grid configurations and run simulations
    for i, config in enumerate(expand_grid(base_config)):
        print(f"\n--- Running configuration {i+1} ---")       
        for k, v in config.items():
            print(f"{k}: {v} ({type(v).__name__})")

        run(config) 