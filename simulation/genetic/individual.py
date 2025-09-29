import random
import os
import json
from config import GA_PARAMS
import sys
parent_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.append(parent_dir)
import simulation

class Individual:
    def __init__(self, length=None, n_edges=None, genome=None, fitness=None):        
        self.genome = genome or random.sample(range(n_edges), length)
        self.fitness = fitness or None

    def evaluate(self, rank=0):
        print("Evaluating individual with genome:", self.genome)
        cs_list = [GA_PARAMS["cs_list"][i] for i in self.genome]
        print("Evaluating individual with CSs:", cs_list)
        
        with open(GA_PARAMS["config_file"], "r", encoding="utf-8") as f:
            config = json.load(f)
        
        #config['CS_LIST'] = cs_list
        print("Running simulation with config:", config)
        results_folder = simulation.run(config, port=8814+rank)        
        print(f"Simulation completed. Results in folder: {results_folder}")
        
        with open(results_folder+'charging_metrics.json', "r", encoding="utf-8") as f:
            charging_metrics = json.load(f)
        #print("Charging metrics:", charging_metrics)
        with open(results_folder+'rerouting_metrics.json', "r", encoding="utf-8") as f:
            rerouting_metrics = json.load(f)
        #print("Rerouting metrics:", rerouting_metrics)
        with open(results_folder+'traffic_metrics.json', "r", encoding="utf-8") as f:
            traffic_metrics = json.load(f)
        #print("Traffic metrics:", traffic_metrics)
        
        # !!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!
        self.fitness = sum(self.genome)  # Placeholder for actual fitness calculation!!
        print(f"Calculated fitness: {self.fitness} with rank {rank}")
        # !!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!
        
    def mutate(self, n_edges=50):
        while True:
            index = random.randint(0, len(self.genome) - 1)
            new_edge = random.randint(0, n_edges - 1)
            if new_edge not in self.genome:
                self.genome[index] = new_edge
                break

    def copy(self):
        return Individual(genome=self.genome)

    def __str__(self):
        return f"Genome: {self.genome}, Fitness: {self.fitness}"