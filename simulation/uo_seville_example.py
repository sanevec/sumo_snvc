# pip install https://api.v2.urbanobservatory.ac.uk/lib/uo-pyfetch.tar.gz
from datetime import datetime, timedelta, timezone
import uo_pyfetch
import pandas as pd
import matplotlib.pyplot as plt
import os

# Define output folder
output_dir = "uo_seville_output"
os.makedirs(output_dir, exist_ok=True)

# Bounding box for Sevilla 
bbox = [-6.0075, 37.3600, -5.9300, 37.4100]
#bbox = [-1.652756, 54.973377, -1.620483, 54.983721]  # Newcastle (test)

# Fetch available sensor variables
try:
    variables = uo_pyfetch.get_variables()
    variables_df = pd.DataFrame(variables["Variables"])
    variables_df.to_csv(os.path.join(output_dir, "variables.csv"), index=False)
    print("✔ Variables saved.")
except Exception as e:
    print(f"Failed to fetch variables: {e}")

# Fetch available sensor themes
try:
    themes = uo_pyfetch.get_themes()
    themes_df = pd.DataFrame(themes["Themes"])
    themes_df.to_csv(os.path.join(output_dir, "themes.csv"), index=False)
    print("✔ Themes saved.")
except Exception as e:
    print(f"Failed to fetch themes: {e}")

# Fetch sensors in bbox
print("Fetching sensors in bbox...")
try:
    sensors_df = uo_pyfetch.get_sensors(limit=500, bbox=bbox)
    sensors_df.to_csv(os.path.join(output_dir, "sensors.csv"), index=False)
    print("✔ Sensors saved.")
except Exception as e:
    print(f"Failed to fetch sensors: {e}")
    sensors_df = pd.DataFrame()

# Fetch sensor data for last 2 hours
print("Fetching sensor data (last 2 hours)...")
try:
    realtime_df = uo_pyfetch.get_sensor_data(
        last_n_hours=2,
        bbox=bbox,
        limit=1000
    )
    realtime_df.to_csv(os.path.join(output_dir, "realtime_data.csv"), index=False)
    print("✔ Realtime data saved.")
except Exception as e:
    print(f"Failed to fetch real-time data: {e}")

# Fetch sensor data for last 24 hours
print("Fetching sensor data (last 24 hours)...")
try:
    last_day_df = uo_pyfetch.get_sensor_data(
        last_n_hours=24,
        bbox=bbox,
        limit=2000
    )
    last_day_df.to_csv(os.path.join(output_dir, "last_day_data.csv"), index=False)
    print("✔ Last day data saved.")
except Exception as e:
    print(f"Failed to fetch last day data: {e}")
    last_day_df = pd.DataFrame()

# Fetch historical data for most active sensor (last 7 days)
print("Fetching historical data...")
if not last_day_df.empty:
    sensor_counts = last_day_df["Sensor_Name"].value_counts()
    sensor_name = sensor_counts.index[0]  # Most active sensor

    start = datetime.now(timezone.utc) - timedelta(days=7)
    end = datetime.now(timezone.utc)

    try:
        history_df = uo_pyfetch.get_sensor_data_by_name(
            sensor_name,
            start=start,
            end=end
        )
        history_df.to_csv(os.path.join(output_dir, f"history_{sensor_name}.csv"), index=False)
        print(f"✔ History for {sensor_name} saved.")

        # Plot if possible
        if "Timestamp" in history_df.columns and "Value" in history_df.columns and not history_df.empty:
            history_df["Timestamp"] = pd.to_datetime(history_df["Timestamp"])
            plt.figure(figsize=(10, 5))
            plt.plot(history_df["Timestamp"], history_df["Value"], marker='o', linestyle='-')
            plt.title(f"{sensor_name} - Value over Time")
            plt.xlabel("Timestamp")
            plt.ylabel("Value")
            plt.xticks(rotation=45)
            plt.tight_layout()
            plot_path = os.path.join(output_dir, f"{sensor_name}_plot.png")
            plt.savefig(plot_path)
            plt.close()
            print(f"✔ Plot saved to {plot_path}")
        else:
            print(f"No valid data to plot for {sensor_name}.")

    except Exception as e:
        print(f"Failed to fetch history for sensor {sensor_name}: {e}")
else:
    print("No recent sensor data available.")
