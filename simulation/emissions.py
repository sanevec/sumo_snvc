import traci
import os
#import xml.etree.ElementTree as ET
'''
SAMPLE USE AT MAIN SIMULATION FILE:
    import emissions
    # Start the SUMO simulation
    traci.start()

    # Initialize the simulation information
    simulationData = emissions.get_initial_simulation_information()
    vehicleEmissions = {}

    # EXECUTE the simulation BY steps
    while traci.simulation.getMinExpectedNumber() > 0:
        vehicleEmissions[int(traci.simulation.getTime())] = emissions.get_instant_vehicle_emissions(simulationData)
        traci.simulationStep()
    
    # Get the final simulation information
    emissions.get_final_simulation_information(simulationData, vehicleEmissions)
    emissions.save_output_data(simulationData, vehicleEmissions, WORKING_FOLDER)

    # Close the simulation
    traci.close()
'''

def get_initial_simulation_information(saveStreetMap=False, saveBuildings=False):
    simulationData = {}
    simulationData['simulationStepTime'] = traci.simulation.getDeltaT()
    mapSize = traci.simulation.getNetBoundary()
    simulationData['mapSize'] = {"minX": mapSize[0][0], "minY": mapSize[0][1], "maxX": mapSize[1][0], "maxY": mapSize[1][1]}
    if saveStreetMap:
        simulationData['map'] = get_map()
    if saveBuildings:
        simulationData['buildings'] = get_buildings()
    return simulationData


def get_map():
    mapData = {"edges": []}
    for edgeID in traci.edge.getIDList():
        # Number of lanes in the edge
        numLanes = traci.edge.getLaneNumber(edgeID)

        # Get initial and end junction IDs for the edge
        initJointID = traci.edge.getFromJunction(edgeID)
        endJointID = traci.edge.getToJunction(edgeID)

        # Get joints positions (x,y)
        initJointPosition = traci.junction.getPosition(initJointID)
        endJointPosition = traci.junction.getPosition(endJointID)

        # Filter edges with no length
        if initJointPosition == endJointPosition:
            continue

        mapData["edges"].append({"edgeID": edgeID, "numLanes": numLanes, 
                                    "initX": initJointPosition[0], "initY": initJointPosition[1], 
                                    "endX": endJointPosition[0], "endY": endJointPosition[1]})

    return mapData

def get_buildings():
    buildingsData = []

    # Open building (polygon) xml file from OSM and access to xml tree root
    polygonXmlTreeRoot = ET.parse(buildingFilePath).getroot()

    # Iterate through each child to find buildings polygons
    for child in polygonXmlTreeRoot:
        if "type" in child.attrib and "building" in child.attrib["type"]:
            poligonFormatPoint = []
            listOfRawPoints = child.attrib["shape"].split(" ")
            for rawPoint in listOfRawPoints:
                poligonFormatPoint.append(list(rawPoint.split(",")))
            # Add building info (list of point in [x,y] format)
            buildingsData.append(poligonFormatPoint)

    return buildingsData


def get_final_simulation_information(simulationData, vehicleEmissions):
    simulationData['duration'] = traci.simulation.getTime()
    simulationData['vehicleIDStr2IDInt'] = mapStrID2IntID(vehicleEmissions)
    

def mapStrID2IntID(vehicleEmissions):
    # Map vehicle ID from string to int
    vehicleIDStr2IDInt = {}
    # Get all vehicle unique id (string) 
    uniqueStrID = []
    [uniqueStrID.append(vehicleID) for time, vehicle in vehicleEmissions.items() for vehicleID in vehicle.keys()]
    uniqueStrID = list(set(uniqueStrID))
    for intID in range(len(uniqueStrID)):
        vehicleIDStr2IDInt[uniqueStrID[intID]] = intID
    return vehicleIDStr2IDInt

def get_instant_vehicle_emissions(simulationData):
    vehicleEmissions = {}
    for vehicleID in traci.vehicle.getIDList():
        vehicleEmissions[vehicleID] = {
            "position": traci.vehicle.getPosition(vehicleID),
            "CO2": traci.vehicle.getCO2Emission(vehicleID)*simulationData['simulationStepTime'], # mg/step or mg
            "CO": traci.vehicle.getCOEmission(vehicleID)*simulationData['simulationStepTime'], # mg/step or mg
            "HC": traci.vehicle.getHCEmission(vehicleID)*simulationData['simulationStepTime'], # mg/step or mg
            "NOx": traci.vehicle.getNOxEmission(vehicleID)*simulationData['simulationStepTime'], # mg/step or mg
            "PMx": traci.vehicle.getPMxEmission(vehicleID)*simulationData['simulationStepTime'], # mg/step or mg
            "noise": traci.vehicle.getNoiseEmission(vehicleID) #dB
        }
    
    return vehicleEmissions


def save_output_data(simulationData, vehicleEmissions, outputFolder):

    # Save simulation information
    simulationDataFilePath = os.path.join(outputFolder, "simulation_data.txt")
    write_file(simulationData, simulationDataFilePath)

    # Save vehicle emissions data
    emissionsFilePath = ""
    emissionsFilePath = os.path.join(outputFolder, "vehicle_emissions.txt")
    write_file(vehicleEmissions, emissionsFilePath)
    
    return outputFolder, simulationDataFilePath, emissionsFilePath
        
def write_file(data, filePath):
    file = open(filePath,"w")
    file.write(str(data))
    file.close()
