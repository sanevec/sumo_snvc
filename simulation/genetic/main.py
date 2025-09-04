from config import GA_PARAMS
from population import Population

if __name__ == "__main__":

    pop = Population(GA_PARAMS)
    pop.initialize()
    pop.evaluate_multithread()

    for gen in range(GA_PARAMS["generations"]):
        print(f"Generation {gen + 1}/{GA_PARAMS['generations']}")
        print(pop)
        pop.evolve()
        pop.evaluate_multithread()

    best = pop.get_best()
    print("Best solution:", best.genome, "Fitness:", best.fitness)
