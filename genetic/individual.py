import random
import utils

class Individual:
    def __init__(self, genome=None, fitness=None, length=10, n_edges=50, max_charging_stations=5):
        self.genome = genome or random.sample(range(n_edges), length)
        self.fitness = fitness or None

    def evaluate(self):
        # STATS TO GET FROM SIMULATION
        self.fitness = sum(self.genome)
        utils.run2()

    def mutate(self, n_edges=50):
        while True:
            index = random.randint(0, len(self.genome) - 1)
            new_edge = random.randint(0, n_edges - 1)
            if new_edge not in self.genome:
                self.genome[index] = new_edge
                break

    def copy(self):
        return Individual(self.genome)

    def __str__(self):
        return f"Genome: {self.genome}, Fitness: {self.fitness}"