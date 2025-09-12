from config import GA_PARAMS
from population import Population

if __name__ == "__main__":

    pop = Population(GA_PARAMS)
    pop.initialize()
    pop.evaluate()

    for gen in range(GA_PARAMS["generations"]):
        print(f"Generation {gen + 1}/{GA_PARAMS['generations']}")
        print(pop)
        pop.evolve()
        pop.evaluate()

    best = pop.get_best()
    print("Best solution:", best.genome, "Fitness:", best.fitness)
