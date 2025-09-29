import itertools
import argparse
import json

def expand_grid(flat_config):
    grid_keys = []
    grid_values = []

    for k, v in flat_config.items():
        if isinstance(v, list):
            grid_keys.append(k)
            grid_values.append(v)
        else:
            # Wrap scalar values into a list
            grid_keys.append(k)
            grid_values.append([v])

    for combination in itertools.product(*grid_values):
        yield dict(zip(grid_keys, combination))

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Run SUMO with config file containing global parameters.",
        formatter_class=argparse.RawTextHelpFormatter
    )
    parser.add_argument(
        "--config",
        type=str,
        required=True,
        help=(
            "Path to a JSON file with the following required keys:\n"
            "  SUMO_BINARY      (str)          → path to SUMO binary (e.g. '/bin/sumo-gui')\n"
            "  FOLDER           (str)          → input folder with SUMO network files\n"
            "  CONFIG_FILE      (str)          → .sumocfg file name used in each run\n"
            "  NODES_FILE       (str)          → .nod.xml file name used in each run\n"
            "  EDGES_FILE       (str)          → .edg.xml file name used in each run\n"
            "  ADDITIONAL_FILE  (str)          → .add.xml file name used in each run\n"
            "  NETWORK_FILE     (str)          → .net.xml output file name\n"
            "  CS_LIST          (list of int)  → list of edge indices for charging stations\n"
            "  CS_SIZE          (int)          → number of charging lanes per station group\n"
            "If any are lists, the script will perform a grid search over all combinations."
        )
    )
    args = parser.parse_args()

    with open(args.config, "r", encoding="utf-8") as f:
        base_config = json.load(f)

    # Define the set of required keys
    required_keys = [
        "SUMO_BINARY",
        "FOLDER",
        "CONFIG_FILE",
        "NODES_FILE",
        "EDGES_FILE",
        "ADDITIONAL_FILE",
        "NETWORK_FILE",
        "CS_LIST",
        "CS_SIZE"
    ]

    # Check if any required key is missing
    missing_keys = required_keys - base_config.keys()

    if missing_keys:
        raise ValueError(f"Missing required configuration keys: {', '.join(missing_keys)}")

    for i, config in enumerate(expand_grid(base_config)):
        print(f"\n--- Running configuration {i+1} ---")       
        for k, v in config.items():
            print(f"{k}: {v} ({type(v).__name__})")

        SUMO_BINARY = config["SUMO_BINARY"]
        FOLDER = config["FOLDER"]
        working_folder = 'test'
        CONFIG_FILE = working_folder + config["CONFIG_FILE"]
        NODES_FILE = working_folder + config["NODES_FILE"]
        EDGES_FILE = working_folder + config["EDGES_FILE"]
        ADDITIONAL_FILE = working_folder + config["ADDITIONAL_FILE"]
        NETWORK_FILE = working_folder + config["NETWORK_FILE"]
        CS_LIST = config["CS_LIST"]
        CS_SIZE = config["CS_SIZE"]
        
        