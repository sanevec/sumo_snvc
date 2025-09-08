import random
from multiprocessing import Pool
import os
from individual import Individual
from config import GA_PARAMS

class Population:
    def __init__(self, params):
        self.params = params
        self.individuals = []

    def initialize(self):
        self.individuals = [Individual(length=self.params["chromosome_length"],n_edges=len(GA_PARAMS["cs_list"])) for _ in range(self.params["population_size"])]

    def evaluate(self):
        for ind in self.individuals:
            ind.evaluate()

    def evolve(self):
        new_individuals = []
        # First, we add the best individual to the new population
        self.individuals.sort(key=lambda ind: ind.fitness, reverse=True)
        for ind in self.individuals[:self.params["elitism_size"]]:
            new_individuals.append(ind.copy())

        # Then, we evolve part of the population using tournament selection
        while len(new_individuals) < self.params["population_size"]- self.params["elitism_size"]:
            parents = self.tournament_selection(self.individuals)
            new_individual = self.crossover(parents[0], parents[1])
            if random.random() < self.params["mutation_prob"]:
                new_individual.mutate(n_edges=len(GA_PARAMS["cs_list"]))
            new_individuals.append(new_individual)

        # Finally, we add the same number of new individuals as the elitism size
        while len(new_individuals) < self.params["population_size"]:
            new_individuals.append(Individual(length=self.params["chromosome_length"],n_edges=len(GA_PARAMS["cs_list"])))

        self.individuals = new_individuals
            

    def tournament_selection(self, population, tournament_size=1, n_winners=2):
        winners = []
        for _ in range(n_winners):
            # Elegir individuos al azar
            tournament = random.sample(population, tournament_size)
            
            # Elegir el mejor del torneo
            best = max(tournament, key=lambda ind: ind.fitness)
            winners.append(best)
        return winners


    def crossover(self, parent1, parent2):
        # Add crossover logic here using a single-point crossover
        genome1 = parent1.genome
        crossover_point = random.randint(1, len(genome1) - 1)
        child_edges = genome1[:crossover_point] 

        # Add the rest of the parent2's genome
        i = 0
        while len(child_edges) < len(genome1):
            if parent2.genome[i] not in child_edges:
                child_edges.append(parent2.genome[i])
            i += 1
        
        return Individual(genome=child_edges)

    def get_best(self):
        # Return the best individual in the population
        return max(self.individuals, key=lambda ind: ind.fitness)
    
    def __str__(self):
        return "\n".join(str(ind) for ind in self.individuals) 
    
    """
    def evaluate2(self):
        comm = MPI.COMM_WORLD
        rank = comm.Get_rank()
        size = comm.Get_size()

        n = len(self.individuals)
        chunk_size = n // size
        remainder = n % size

        if rank < remainder:
            start = rank * (chunk_size + 1)
            end = start + (chunk_size + 1)
        else:
            start = rank * chunk_size + remainder
            end = start + chunk_size

        # Cada proceso evalúa sus individuos
        local_chunk = self.individuals[start:end]
        for ind in local_chunk:
            ind.evaluate()
            print(f"Proceso {rank} evaluando individuo {ind.genome} con fitness {ind.fitness}")

        # Recolectar resultados de todos los procesos
        all_chunks = comm.gather(local_chunk, root=0)
        if rank == 0:
            self.individuals = all_chunks

        print(f"Proceso {rank} ha terminado de evaluar sus individuos.")
        print(self)
    """

    def evaluate_multithread(self, n_threads=3):
        with Pool(n_threads) as pool:
            result = pool.map(self.evaluate_ind, self.individuals)
        self.individuals = result
       
            
    def evaluate_ind(self, ind):     
        ind.evaluate()
        pid = os.getpid()
        print(f"[Proceso {pid}] Resultado: {ind}")
        return ind