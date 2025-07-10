import time
from multiprocessing import Pool
import os

# Función que simula un trabajo costoso
def multiply_by_three(x):
    pid = os.getpid()
    print(f"[Proceso {pid}] Multiplicando {x}...")
    time.sleep(2)   # simulamos retardo
    result = x * 3
    print(f"[Proceso {pid}] Resultado de {x} * 3 = {result}")
    return result

if __name__ == "__main__":
    arr = [1, 2, 3, 4, 5]

    print("\n=== EJECUCIÓN SECUENCIAL ===")
    start_seq = time.time()
    result_seq = []
    for x in arr:
        result_seq.append(multiply_by_three(x))
    end_seq = time.time()

    print(f"Resultado secuencial: {result_seq}")
    print(f"Tiempo secuencial: {end_seq - start_seq:.2f} segundos")

    print("\n=== EJECUCIÓN EN PARALELO (POOL) ===")
    print("Número de núcleos lógicos disponibles:", os.cpu_count())
    start_par = time.time()
    with Pool(processes=5) as pool:
        result_par = pool.map(multiply_by_three, arr)
    end_par = time.time()

    print(f"Resultado paralelo: {result_par}")
    print(f"Tiempo paralelo: {end_par - start_par:.2f} segundos")
