import os

# Get the user's home directory
home_dir = os.path.expanduser("~")

# Detect the user's shell to choose the appropriate config file
shell = os.environ.get("SHELL", "")
rc_file = ".bashrc"
if shell.endswith("zsh"):
    rc_file = ".zshrc"

# Full path to the shell config file
rc_path = os.path.join(home_dir, rc_file)

# Get the current working directory to use as SUMO_HOME
current_dir = os.getcwd()
export_line = f'export SUMO_HOME="{current_dir}"\n'

# Read the shell config file to check if SUMO_HOME is already set
if os.path.exists(rc_path):
    with open(rc_path, "r") as f:
        content = f.read()
else:
    content = ""

# If SUMO_HOME is not present, append it to the config file
if "SUMO_HOME" not in content:
    with open(rc_path, "a") as f:
        f.write("\n# Set SUMO_HOME automatically\n")
        f.write(export_line)
    print(f"Added SUMO_HOME to {rc_path}")
else:
    print(f"SUMO_HOME already set in {rc_path}")

# Set SUMO_HOME temporarily for the current script environment
os.environ["SUMO_HOME"] = current_dir
print(f"Temporarily set SUMO_HOME to: {current_dir}")
