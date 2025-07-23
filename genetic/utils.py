import sys
import os
import math
from datetime import datetime
import re
from config import GA_PARAMS

# Read the SUMO_HOME environment variable
sumo_home = os.environ.get("SUMO_HOME")

if sumo_home is None:
    raise EnvironmentError("The SUMO_HOME environment variable is not defined.")

# Build the path to the tools/ folder inside SUMO_HOME
tools_path = os.path.join(sumo_home, "tools")

# Add it to sys.path if not already present
if tools_path not in sys.path:
    sys.path.append(tools_path)

import traci

def build_world(cs_list=None):    
    #add_charging_stations(cs_list)
    #print(obtain_edge_ids())
    #print(get_edge_nodes("e7"))
    #old = get_edge_block("e7")
    #print(old)
    #new = replace_attribute(old, "speed", "20.0")
    #print(new)
    #replace_xml_block_in_file("cs_example/network.edg.xml", old, new)
    #print(load_nodes())
    add_charging_stations([100])
    os.system(os.environ["SUMO_HOME"]+"/bin/netconvert --node-files "+NODES_FILE+" --edge-files "+EDGES_FILE+" --output-file "+NETWORK_FILE)
    run()

def folder_setup(src_folder, param_dict, file_names):
    """
    Creates a timestamped folder, copies the given files into it, and writes params.txt.

    Parameters:
        src_folder (str): Path to the folder containing the original files (must end with '/')
        param_dict (dict): Dictionary of parameters to be written to params.txt
        file_names (list): List of filenames to copy from src_folder to the new folder

    Returns:
        str: Path to the created folder
    """
    # Generate timestamp and folder path
    timestamp = datetime.now().strftime("%y-%m-%d-%H-%M-%S")
    folder_path = f"runs/{timestamp}/"
    os.makedirs(folder_path, exist_ok=True)

    # Copy files
    for name in file_names:
        src_path = src_folder + name
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

def add_charging_stations(cs_list=None):    
    edge_ids = obtain_edge_ids()
    print(f"Edge IDs: {edge_ids[edge_ids.index('39723679')]}")  # Example edge ID for debugging
    #cs_list.append(edge_ids.index('39723679'))
    #cs_list.append(edge_ids.index('1374141275#0'))
    #cs_list.append(edge_ids.index('311743584'))
    #cs_list.append(edge_ids.index('39723676'))
    #cs_list.append(edge_ids.index('238193475'))
    for cs in cs_list:
        edge_id = edge_ids[cs]
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
            first_half_edge = replace_attribute(first_half_edge, "shape", new_shape1)
            second_half_edge = replace_attribute(second_half_edge, "shape", new_shape2)
        # Now we replace the old edge block in the edges file with the two new edges
        replace_xml_block_in_file(EDGES_FILE, edge_xml, first_half_edge + second_half_edge)
        # And finally, we add the charging station structure
        if shape_points:
            x1, y1 = first_half[0]
            x2, y2 = second_half[-1]
        x1, y1, x2, y2 = generate_parallel_segment_offset_from_point(x1, y1, x2, y2, xm, ym)
        add_charging_station(edge_id, cs, x1, y1, x2, y2, 3)

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

def add_charging_station(edge_id, cs_group, x1, y1, x2, y2, n_cs):
    '''
    Adds a charging station to the network by creating the necessary nodes and edges.
    The charging station consists of a start node, an end node, and a lane with multiple
    charging points. The function also adds the charging station to the additional.xml file.
    '''
    cs_start = f"cs_start_{edge_id}"
    cs_end = f"cs_end_{edge_id}"
    add_node_to_xml(NODES_FILE, cs_start, x1, y1)
    add_node_to_xml(NODES_FILE, cs_end, x2, y2)  
    lanes = "".join(f'<lane index="{i}" speed="13.89"/>' for i in range(n_cs))
    edges = f"""
    <edge id="to_cs_{edge_id}" from="cs_{edge_id}" to="{cs_start}" priority="-1">
        <lane index="0" speed="13.89"/>
    </edge>
    <edge id="cs_lanes_{edge_id}" from="{cs_start}" to="{cs_end}" priority="1" numLanes="3">
        {lanes}
    </edge>
    <edge id="from_cs_{edge_id}" from="{cs_end}" to="cs_{edge_id}" priority="-1">
        <lane index="0" speed="13.89"/>
    </edge>     
    """
    charging_points = "".join(
        f'\n<chargingStation id="cs_{edge_id}_{i}" lane="cs_lanes_{edge_id}_{i}" startPos="30.0" endPos="35.0" friendlyPos="true" power="150000">'
        f'\n    <param key="group" value="{cs_group}"/>'
        f'\n    <param key="chargingPort" value="CCS2"/>'
        f'\n    <param key="allowedPowerOutput" value="150000"/>'
        f'\n    <param key="groupPower" value="200000"/>'
        f'\n    <param key="chargeDelay" value="5"/>'
        f'\n</chargingStation>' for i in range(n_cs))
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

###############################################

def run():
    traci.start([os.environ["SUMO_HOME"]+SUMO_BINARY, "-c", CONFIG_FILE])
    vehList = []

    while traci.simulation.getMinExpectedNumber() > 0:
        traci.simulationStep()        
        for veh in traci.simulation.getStopStartingVehiclesIDList():
            csId = traci.vehicle.getParameter(veh, "device.battery.chargingStationId")
            if (csId != "NULL"):
                #print(veh)
                vehList.append(veh)
                traci.chargingstation.setParameter(csId, "desiredPower", 0)
                traci.chargingstation.setParameter(csId, "aliquotPowerAdjustment", 1)
        for veh in traci.simulation.getStopEndingVehiclesIDList():
            vehList.remove(veh)
        calculateAliquotPowerAdjustments(vehList)
        setChargingStationPowers(vehList)

    traci.close()


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


def run2():
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
            if csId_stationfinder != "" and csId_battery == "NULL":
                print(f"Vehículo {veh} tiene ruta: {route} y battery: {csId_battery} y stationfinder: {csId_stationfinder}")
                #traci.vehicle.setParameter(veh, "device.battery.chargingStationId", csId_stationfinder)
            
            print(f"Vehículo {veh} tiene ruta: {route} y battery: {csId_battery} y stationfinder: {csId_stationfinder}")

        for veh in traci.simulation.getStopStartingVehiclesIDList():
            csId = traci.vehicle.getParameter(veh, "device.battery.chargingStationId")
            print('Empezando parada coche: '+ veh + ' csId: ' + csId)
                
        for veh in traci.simulation.getStopEndingVehiclesIDList():
            csId = traci.vehicle.getParameter(veh, "device.battery.chargingStationId")
            print('Saliendo parada coche: '+ veh + ' csId: ' + csId)
            
    traci.close()


if __name__ == "__main__":
    SUMO_BINARY = "/bin/sumo-gui"
    FOLDER = "sevilla/"      
    file_list = [f for f in os.listdir(FOLDER) if os.path.isfile(os.path.join(FOLDER, f))]
    WORKING_FOLDER = folder_setup(FOLDER, GA_PARAMS, file_list)
    CONFIG_FILE = WORKING_FOLDER+"simulation.sumocfg"
    NODES_FILE = WORKING_FOLDER+"network.nod.xml"
    EDGES_FILE = WORKING_FOLDER+"network.edg.xml"
    ADDITIONAL_FILE = WORKING_FOLDER+"infrastructure.add.xml"
    NETWORK_FILE = WORKING_FOLDER+"network.net.xml"
    build_world()