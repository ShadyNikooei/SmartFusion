import matplotlib.pyplot as plt
from pymongo import MongoClient
import urllib.parse
import time
import numpy as np

# --- 1. DATABASE CONNECTION ---
username = urllib.parse.quote_plus('---')
password = urllib.parse.quote_plus('----')
cluster = '----'
MONGO_URI = f"mongodb+srv://{username}:{password}@{cluster}/?retryWrites=true&w=majority"

client = MongoClient(MONGO_URI)
db = client["SmartFusion_DB"]
collection = db["SensorAnalytics"]

# --- 2. LIVE PLOTTING FUNCTION ---
def plot_live_data():
    plt.ion()  # Turn on interactive mode
    fig, ax = plt.subplots(2, 1, figsize=(10, 8))
    
    print(">>> Starting Real-time Visualizer...")
    
    while True:
        try:
            # Fetch the latest 30 records sorted by timestamp
            cursor = collection.find().sort("timestamp", -1).limit(30)
            data = list(cursor)[::-1]  # Reverse to chronological order

            if not data:
                print(">>> Waiting for database records...")
                time.sleep(3)
                continue

            timestamps = []
            raw_gas_adc = []
            fused_gas_ppm = []
            danger_probabilities = []

            for record in data:
                # Use .get() to prevent KeyError if gateway hasn't sent full data yet
                fused = record.get('fused_data', {})
                raw_in = record.get('raw_input', {})
                
                # Check for required fields before plotting
                if 'ppm' in fused and 'co_raw' in raw_in:
                    # Convert UNIX timestamp to readable format
                    ts = time.strftime('%H:%M:%S', time.localtime(record['timestamp']))
                    timestamps.append(ts)
                    raw_gas_adc.append(raw_in['co_raw'])
                    fused_gas_ppm.append(fused['ppm'])
                    danger_probabilities.append(fused.get('danger_prob', 0) * 100)

            if timestamps:
                # Subplot 1: Sensor Fusion Performance
                ax[0].cla()
                ax[0].plot(timestamps, raw_gas_adc, label='Raw Sensor (ADC)', color='red', linestyle='--', alpha=0.6)
                ax[0].plot(timestamps, fused_gas_ppm, label='Fused Output (PPM)', color='blue', linewidth=2)
                ax[0].set_title("Multi-Level Fusion: Raw Signal vs Processed PPM")
                ax[0].set_ylabel("Intensity / Concentration")
                ax[0].legend(loc='upper left')
                ax[0].grid(True, alpha=0.3)
                ax[0].tick_params(axis='x', rotation=45)

                # Subplot 2: Threat Assessment (Dempster-Shafer)
                ax[1].cla()
                ax[1].fill_between(timestamps, danger_probabilities, color='orange', alpha=0.2)
                ax[1].plot(timestamps, danger_probabilities, label='Danger Probability (%)', color='darkred', marker='o', markersize=3)
                ax[1].set_ylim(0, 105)
                ax[1].set_title("Dempster-Shafer Decision Fusion: Environmental Threat Level")
                ax[1].set_ylabel("Probability (%)")
                ax[1].legend(loc='upper left')
                ax[1].grid(True, alpha=0.3)
                ax[1].tick_params(axis='x', rotation=45)

                plt.tight_layout()
                plt.pause(1)  # Refresh plot every second
            
        except Exception as e:
            print(f">>> Sync Error: {e}")
            time.sleep(2)

if __name__ == "__main__":
    try:
        plot_live_data()
    except KeyboardInterrupt:
        print("\n>>> Visualizer Stopped.")