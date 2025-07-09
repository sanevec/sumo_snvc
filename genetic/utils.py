def build_world():
    return 0

def insert_node(id):
    # leer archivo original
    with open("network.nod.xml", "r") as f:
        content = f.read()

    # encontrar dónde insertar antes de la etiqueta de cierre
    index = content.rfind("</nodes>")

    # texto a insertar
    new_node = '  <node id="' + id + '" x="10.0" y="0.0" type="priority" />\n'

    # insertar el nuevo nodo
    content = content[:index] + new_node + content[index:]

    # guardar archivo modificado
    with open("network.nod.xml", "w") as f:
        f.write(content)

def insert_charging_stations(cs_list):
    # leer archivo original
    with open("infraestructura.add.xml", "r") as f:
        content = f.read()

    # encontrar dónde insertar antes de la etiqueta de cierre
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
        # texto a insertar
        new_cs_list += (
            '\t<chargingStation id="'+cs[0]+'" lane="'+cs[0]+'" startPos="'+cs[0]+'" endPos="'+cs[0]+'" friendlyPos="true" power="'+cs[0]+'">\n'
            '\t\t<param key="group" value="'+cs[0]+'"/>\n'
            '\t\t<param key="chargingPort" value="'+cs[0]+'"/>\n'
            '\t\t<param key="allowedPowerOutput" value="'+cs[0]+'"/>\n'
            '\t\t<param key="groupPower" value="'+cs[0]+'"/>\n'
            '\t\t<param key="chargeDelay" value="5"/>\n'
            '\t</chargingStation>\n'
        )

    # insertar el nuevo nodo
    content = content[:index] + new_cs_list + content[index:]

    # guardar archivo modificado
    with open("infraestructura.add.xml", "w") as f:
        f.write(content)

def individual_to_charging_stations(ind, edge_ids):    
    '''
    Each individual has the following structure, taking a solution with 5 charging stations as an example:
    [[6, 43, 78, 25, 11], index of the edge (from edge_ids list) where the charging station is located
    [4, 2, 1, 1, 3]] number of charging points in each charging station
    '''
    cs_list = []
    for gen in range(0,len(ind.genome[0])): # iterate over the charging stations (gen = genome column index)
        lane = get_lane(edge_ids[ind.genome[0][gen]])
        for cp in range(0, ind.genome[1][gen]): # iterate over charging points of each charging station
            # Convert each individual to a charging station xml representation
            cs = [
                edge_ids[ind.genome[0][gen]] + '_' + cp,  # id
                lane,  # lane
                1.0,  # startPos
                4.0,  # endPos
                150000,  # power
                ind.genome[0][gen],  # group
                _,  # chargingPort
                150000,  # allowedPowerOutput
                200000  # groupPower
                ]
            cs_list.append(cs)
    return cs_list

def obtain_edge_ids():
    edge_ids = []
    with open("network.edg.xml", "r") as f:
        content = f.read()
        lines = content.splitlines()
        for line in lines:
            if '<edge id="' in line:
                start = line.find('id="') + 4
                end = line.find('"', start)
                edge_id = line[start:end]
                edge_ids.append(edge_id)
    return edge_ids

def get_lane(edge_id):
    return None

###############################################

import traci

SUMO_BINARY = "/home/juan/Escritorio/SUMO/sumo-snvc/bin/sumo"  # AJUSTA AQUÍ
CONFIG_FILE = "simulacion.sumocfg"

def run():
    # Aquí configuramos cada solución 

    traci.start([SUMO_BINARY, "-c", CONFIG_FILE])
    while traci.simulation.getMinExpectedNumber() > 0:
        traci.simulationStep()

        vehList = []
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

def run2():
    # Aquí configuramos cada solución 

    traci.start([SUMO_BINARY, "-c", CONFIG_FILE])
    while traci.simulation.getMinExpectedNumber() > 0:
        traci.simulationStep()     

    traci.close()