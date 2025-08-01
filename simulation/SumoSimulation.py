
import traci
import os
import xml.etree.ElementTree as ET


class SumoSimulation:

    def __init__(self, sumoBinaryBasePath="/bin/sumo" , simulationConfigFilePath="input_sim_data/simulation.sumocfg", 
                 recordVehiclesEmissions=False, saveStreetMap=False, buildingFilePath="", saveBuildings=False):
        # Storing input parameters
        self.sumoBinaryFullPath = os.environ.get("SUMO_HOME", "") + sumoBinaryBasePath
        self.simulationConfigFilePath = simulationConfigFilePath
        self.recordVehiclesEmissions = recordVehiclesEmissions
        self.saveStreetMap = saveStreetMap
        self.buildingFilePath = buildingFilePath
        self.saveBuildings = saveBuildings

        # State variables
        self.simulationRun = False

        # Initializing the command to start SUMO
        self.startCommand = [self.sumoBinaryFullPath, "-c", self.simulationConfigFilePath]
        # Initializing a dictionary to store general simulation information
        self.simulationData = {}
        # Initializing a dictionary to store vehicle emissions if required
        self.vehicleEmissions = {}

    
    def run(self):
        # Start the SUMO simulation
        traci.start(self.startCommand)

        # Initialize the simulation information
        self._get_initial_simulation_information()


        # EXECUTE the simulation BY steps
        while traci.simulation.getMinExpectedNumber() > 0:
            if self.recordVehiclesEmissions:
                self.vehicleEmissions[int(traci.simulation.getTime())] = self._get_instant_vehicle_emissions()
            traci.simulationStep()
        
        # Get the final simulation information
        self._get_final_simulation_information()

        # Close the simulation
        traci.close()
        self.simulationRun = True


    def _get_initial_simulation_information(self):
        self.simulationData['simulationStepTime'] = traci.simulation.getDeltaT()
        mapSize = traci.simulation.getNetBoundary()
        self.simulationData['mapSize'] = {"minX": mapSize[0][0], "minY": mapSize[0][1], "maxX": mapSize[1][0], "maxY": mapSize[1][1]}
        if self.saveStreetMap:
            self.simulationData['map'] = self._get_map()
        if self.saveBuildings:
            self.simulationData['buildings'] = self._get_buildings()


    def _get_map(self):
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


    def _get_buildings(self):
        buildingsData = []

        # Open building (polygon) xml file from OSM and access to xml tree root
        polygonXmlTreeRoot = ET.parse(self.buildingFilePath).getroot()

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


    def _get_final_simulation_information(self):
        self.simulationData['duration'] = traci.simulation.getTime()
        self.simulationData['vehicleIDStr2IDInt'] = self.mapStrID2IntID()
        
    
    def mapStrID2IntID(self,):
        # Map vehicle ID from string to int
        vehicleIDStr2IDInt = {}
        # Get all vehicle unique id (string) 
        uniqueStrID = []
        [uniqueStrID.append(vehicleID) for time, vehicle in self.vehicleEmissions.items() for vehicleID in vehicle.keys()]
        uniqueStrID = list(set(uniqueStrID))
        for intID in range(len(uniqueStrID)):
            vehicleIDStr2IDInt[uniqueStrID[intID]] = intID
        return vehicleIDStr2IDInt



    def _get_instant_vehicle_emissions(self):
        vehicleEmissions = {}
        for vehicleID in traci.vehicle.getIDList():
            vehicleEmissions[vehicleID] = {
                "position": traci.vehicle.getPosition(vehicleID),
                "CO2": traci.vehicle.getCO2Emission(vehicleID)*self.simulationData['simulationStepTime'], # mg/step or mg
                "CO": traci.vehicle.getCOEmission(vehicleID)*self.simulationData['simulationStepTime'], # mg/step or mg
                "HC": traci.vehicle.getHCEmission(vehicleID)*self.simulationData['simulationStepTime'], # mg/step or mg
                "NOx": traci.vehicle.getNOxEmission(vehicleID)*self.simulationData['simulationStepTime'], # mg/step or mg
                "PMx": traci.vehicle.getPMxEmission(vehicleID)*self.simulationData['simulationStepTime'], # mg/step or mg
                "noice": traci.vehicle.getNoiseEmission(vehicleID) #dB
            }
        
        return vehicleEmissions
    

    def save_output_data(self, outputFolder):
        if not self.simulationRun:
            print("Simulation has not been run yet. Please run the simulation first.")
            return
        # Create the output folder if it does not exist
        os.makedirs(outputFolder, exist_ok=True)

        # Save simulation information
        simulationDataFilePath = os.path.join(outputFolder, "simulation_data.txt")
        self._write_file(self.simulationData, simulationDataFilePath)

        # Save vehicle emissions data
        emissionsFilePath = ""
        if self.recordVehiclesEmissions:
            emissionsFilePath = os.path.join(outputFolder, "vehicle_emissions.txt")
            self._write_file(self.vehicleEmissions, emissionsFilePath)
        
        return outputFolder, simulationDataFilePath, emissionsFilePath
            
    
    def _write_file(self, data, filePath):
        file = open(filePath,"w")
        file.write(str(data))
        file.close()
    