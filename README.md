<h1 align="center">🚗 sumo_snvc 🚦</h1>

<p align="center">
  <a href="https://github.com/eclipse-sumo/sumo">
    <img src="https://img.shields.io/badge/SUMO-%20Fork-blue?logo=github" alt="SUMO Fork" />
  </a>
  <a href="https://doi.org/10.1007/978-3-031-87345-4_6">
    <img src="https://img.shields.io/badge/Add--ons-DOI-green" alt="Add-ons DOI" />
  </a>
</p>

<p align="center">
  <strong>Fork of <a href="https://github.com/eclipse-sumo/sumo">SUMO</a> for SANEVEC project</strong><br>
  This project implements the EV fast charging and charge-site power limitations described <a href="https://doi.org/10.1007/978-3-031-87345-4_6">in this paper</a> for enhanced simulation capabilities.
</p>



## 🛠️ Build and Installation
Clone the repository:

```bash
git clone  https://github.com/sanevec/sumo_snvc
cd sumo_snvc
```
Set SUMO_HOME environment variable:

```bash
python3 set_sumo_home.py
```
Install dependencies:

```bash
sudo apt-get install $(cat build_config/build_req_deb.txt build_config/tools_req_deb.txt)
sudo apt-get install libgdal-dev
sudo apt update
sudo apt install libopenscenegraph-dev openscenegraph libopenthreads-dev
```
Configure and build:

```bash
cmake -B build .
cmake --build build -j$(nproc)
```
## 🚀 Run a Test
After compilation, binaries will be located in the bin/ folder.

A basic SUMO test simulation is available in the genetic/ folder. Run it like this:

```bash
cd genetic
../bin/sumo-gui -c simulation.sumocfg
```
To use the charging add-on capabilities, it is required to launch the simulation from a Python script and control every step using TraCI. A Python virtual environment is required to launch the simulation. Instructions to create it (outside of the project folder):
```bash
python3 -m venv venv-sumo
source venv-sumo/bin/activate
```
To run the test from genetic/ folder:
```bash
python3 traci_test.py
```
## 🧬 Genetic Algorithm
🚧 Work in Progress...

In the context of the SANEVEC project, we are proposing an optimal set of charging station locations for Sevilla Este to minimize traffic jams and contamination. 
```text
Algorithm Genetic
    Initialize population P
    Evaluate fitness of individuals in P

    For generation = 1 to MaxGenerations do
        P ← EvolvePopulation(P)
        Evaluate fitness of individuals in P
    End For

    Return best solution found in P
End Algorithm
```
Each individual of the population for the genetic algorithm has a list of charging station locations taken from a list of possible edges, taking a solution with 5 charging stations as an example, this would be the genome structure:

    [6, 43, 78, 25, 11]