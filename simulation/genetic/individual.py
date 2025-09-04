import random
import os
from config import GA_PARAMS

class Individual:
    def __init__(self, length=None, n_edges=None, genome=None, fitness=None):        
        self.genome = genome or random.sample(range(n_edges), length)
        self.fitness = fitness or None

    def evaluate(self):
        # STATS TO GET FROM SIMULATION
        self.fitness = sum(self.genome)  # Placeholder for actual fitness calculation
        # In a real scenario, you would call the simulation here
        cs_list = [GA_PARAMS["cs_list"][i] for i in self.genome]
        print("Evaluating individual with CSs:", cs_list)
        os.system("python3 ../simulation.py --config genetic_test.json")
        
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