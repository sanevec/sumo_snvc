import os
import traci
import re

SUMO_BINARY = "/bin/sumo-gui"
FOLDER = "cs_example/"  
CONFIG_FILE = FOLDER+"simulation.sumocfg"
NODES_FILE = FOLDER+"network.nod.xml"
EDGES_FILE = FOLDER+"network.edg.xml"
ADDITIONAL_FILE = FOLDER+"infrastructure.add.xml"
NETWORK_FILE = FOLDER+"network.net.xml"

def build_world(cs_list=None):
    os.system(os.environ["SUMO_HOME"]+"/bin/netconvert --node-files "+NODES_FILE+" --edge-files "+EDGES_FILE+" --output-file "+NETWORK_FILE)
    run()

def insert_node(id):
    # read original file
    with open("network.nod.xml", "r") as f:
        content = f.read()

    # find where to insert before the closing tag
    index = content.rfind("</nodes>")

    # text to insert
    new_node = '  <node id="' + id + '" x="10.0" y="0.0" type="priority" />\n'

    # insert the new node
    content = content[:index] + new_node + content[index:]

    # save modified file
    with open("network.nod.xml", "w") as f:
        f.write(content)

def insert_charging_stations(cs_list):
    # read original file
    with open("infraestructura.add.xml", "r") as f:
        content = f.read()

    # find where to insert before the closing tag
    index = content.rfind("</additional>")

    new_cs_list = ''
    '''
    cs[0] id
    cs[1] lane
    cs[2] startPos
    cs[3] endPos
    cs[4] power
    cs[5] group
    cs[6] chargingPort
    cs[7] allowedPowerOutput
    cs[8] groupPower
    '''
    for cs in cs_list:
        # text to insert
        new_cs_list += (
            '\t<chargingStation id="'+cs[0]+'" lane="'+cs[0]+'" startPos="'+cs[0]+'" endPos="'+cs[0]+'" friendlyPos="true" power="'+cs[0]+'">\n'
            '\t\t<param key="group" value="'+cs[0]+'"/>\n'
            '\t\t<param key="chargingPort" value="'+cs[0]+'"/>\n'
            '\t\t<param key="allowedPowerOutput" value="'+cs[0]+'"/>\n'
            '\t\t<param key="groupPower" value="'+cs[0]+'"/>\n'
            '\t\t<param key="chargeDelay" value="5"/>\n'
            '\t</chargingStation>\n'
        )

    # insert the new node
    content = content[:index] + new_cs_list + content[index:]

    # save modified file
    with open("infraestructura.add.xml", "w") as f:
        f.write(content)

def individual_to_charging_stations(ind, edge_ids):    
    '''
    Each individual has the following structure, taking a solution with 5 charging stations as an example:
    [6, 43, 78, 25, 11] index of the edge (from edge_ids list) where the charging station is located
    '''
    cs_list = []
    for gen in range(0,len(ind.genome)): # iterate over the charging stations (gen = genome column index)
        lane = get_lane(edge_ids[ind.genome[gen]])
        for cp in range(3): # iterate over charging points of each charging station
            # Convert each individual to a charging station xml representation
            cs = [
                edge_ids[ind.genome[gen]] + '_' + cp,  # id
                lane,  # lane
                1.0,  # startPos
                4.0,  # endPos
                150000,  # power
                ind.genome[gen],  # group
                _,  # chargingPort
                150000,  # allowedPowerOutput
                200000  # groupPower
                ]
            cs_list.append(cs)
    return cs_list

def obtain_edge_ids():
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
    # Expresión regular para capturar los atributos from y to
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
    node_coords = {}

    # regex para capturar id, x, y
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
                    if '/>' in line or '</edge>' in line:
                        in_edge = False
                        break
            else:
                block_lines.append(line)
                if '/>' in line or '</edge>' in line:
                    in_edge = False
                    break

    if block_lines:
        return ''.join(block_lines)
    else:
        return None

def get_lane(edge_id):
    return None

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