from config import GA_PARAMS
from population import Population
from mpi4py import MPI

comm = MPI.COMM_WORLD
rank = comm.Get_rank()

if __name__ == "__main__":
    # Only root initializes the population
    if rank == 0:
        pop = Population(GA_PARAMS)
        pop.initialize()
    else:
        # Workers create an empty Population object (same class)
        pop = Population(GA_PARAMS)

    # First evaluation (all ranks participate)
    pop.evaluate_mpi()

    # Evolution loop
    for gen in range(GA_PARAMS["generations"]):
        if rank == 0:
            print(f"Generation {gen + 1}/{GA_PARAMS['generations']}")
            print(pop)
            pop.evolve()   # root evolves population

        # Parallel evaluation with MPI
        pop.evaluate_mpi()

    # Final result only on root
    if rank == 0:
        best = pop.get_best()
        print("Best solution:", best.genome, "Fitness:", best.fitness)
