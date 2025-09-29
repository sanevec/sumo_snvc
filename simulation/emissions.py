import traci
import os
import xml.etree.ElementTree as ET
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

def get_initial_simulation_information(saveStreetMap=True, saveBuildings=True, buildingFilePath="", saveVegetation=True, vegetationFilePath="", 
                                       listOfVegetationTags=["landuse.orchard", "leisure.park", "leisure.garden", "landuse.forest", "landuse.grass", "landuse.village_green",
                                                            "natural.heath", "natural.tree_row", "natural.tree", "leisure.golf_course", "landuse.farmland", "natural.wood", 
                                                            "natural.scrub", "natural.shrubbery", "natural.grassland", "natural.fell", "natural.tundra", "landuse.vineyard", 
                                                            "landuse.flowerbed", "landuse.meadow", "landuse.greenery", "landuse.plant_nursery"], 
                                        applyOriginOffset=True, networkFilePath=""):
    simulationData = {}
    simulationData['simulationStepTime'] = traci.simulation.getDeltaT()
    mapSize = traci.simulation.getNetBoundary()
    simulationData['mapSize'] = {"minX": mapSize[0][0], "minY": mapSize[0][1], "maxX": mapSize[1][0], "maxY": mapSize[1][1]}
    if saveStreetMap:
        simulationData['map'] = get_map()
    if saveBuildings:
        simulationData['buildings'] = get_buildings(buildingFilePath, applyOriginOffset, networkFilePath)
    if saveVegetation:
        simulationData['vegetation'] = get_vegetation(vegetationFilePath, listOfVegetationTags, applyOriginOffset, networkFilePath)
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

def get_buildings(buildingFilePath, applyOriginOffset, networkFilePath):
    buildingsData = []

    # Open building (polygon) xml file from OSM and access to xml tree root
    polygonXmlTreeRoot = ET.parse(buildingFilePath).getroot()
    
    # Calculate offset between buildings and street origin point
    originOffset = get_origin_offset(polygonXmlTreeRoot, applyOriginOffset, networkFilePath)

    # Iterate through each child to find buildings polygons
    for child in polygonXmlTreeRoot:
        if "type" in child.attrib and "building" in child.attrib["type"] and "shape" in child.attrib:
            listOfRawPoints = child.attrib["shape"].split(" ")
            poligonFormatPoint = format_raw_poligon(listOfRawPoints, originOffset)
            # Add building info (list of point in [x,y] format)
            buildingsData.append(poligonFormatPoint)

    return buildingsData


def get_vegetation(vegetationFilePath, listOfVegetationTags, applyOriginOffset, networkFilePath):
        vegetationData = []

        # Open building (polygon) xml file from OSM and access to xml tree root
        polygonXmlTreeRoot = ET.parse(vegetationFilePath).getroot()

        # Calculate offset between buildings and street origin point
        originOffset = get_origin_offset(polygonXmlTreeRoot, applyOriginOffset, networkFilePath)

        # Iterate through each child to find vegetation polygons (has one type of listOfVegetationTags with shape atributte)
        for child in polygonXmlTreeRoot:
            for tag in listOfVegetationTags:
                if "type" in child.attrib and tag in child.attrib["type"] and "shape" in child.attrib:
                    listOfRawPoints = child.attrib["shape"].split(" ")
                    poligonFormatPoint = format_raw_poligon(listOfRawPoints, originOffset)
                    # Add vegetation info (list of point in [x,y] format)
                    vegetationData.append(poligonFormatPoint)
                    break

        return vegetationData


def get_origin_offset(polygonXmlTreeRoot, applyOriginOffset, networkFilePath):
        # Calculate offset between buildings and street origin point
        if applyOriginOffset:
            #   1) Open network xml file from OSM 
            networkXmlTreeRoot = ET.parse(networkFilePath).getroot()
            #   2) Get the "netOffset" attribute of "location" element of network and polygon xml
            networkOffset = networkXmlTreeRoot[0].attrib["netOffset"].split(",")
            buildingOffset = polygonXmlTreeRoot[0].attrib["netOffset"].split(",")
            #   3) Calculate the difference in origin offset between both data sources
            originOffset = [float(networkOffset[0])-float(buildingOffset[0]), float(networkOffset[1])-float(buildingOffset[1])]
        else:
            originOffset = [0.0, 0.0]
        return originOffset


def format_raw_poligon(listOfRawPoints, originOffset):
        # Convert from raw string format to list of [x,y] points with offset applied
        poligonFormatPoint = []
        for rawPoint in listOfRawPoints:
            strPoint = list(rawPoint.split(","))
            formatOffsetPoint = [float(strPoint[0])+originOffset[0], float(strPoint[1])+originOffset[1]]
            poligonFormatPoint.append(formatOffsetPoint)
        return poligonFormatPoint


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
    # Create the output folder if it does not exist
    os.makedirs(outputFolder, exist_ok=True)

    # Save simulation information
    simulationDataFilePath = os.path.join(outputFolder, "simulation_data.txt")
    write_file(simulationData, simulationDataFilePath)

    # Save vehicle emissions data
    emissionsFilePath = os.path.join(outputFolder, "vehicle_emissions.txt")
    write_file(vehicleEmissions, emissionsFilePath)
    
    return outputFolder, simulationDataFilePath, emissionsFilePath
        
def write_file(data, filePath):
    file = open(filePath,"w")
    file.write(str(data))
    file.close()
