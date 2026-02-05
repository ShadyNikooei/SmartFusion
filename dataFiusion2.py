import time
import json
import numpy as np
import os
import urllib.parse
from flask import Flask, request, jsonify  #HTTP server
from pymongo import MongoClient
from Adafruit_IO import Client, Feed 

# --- 1. CONFIGURATION & CREDENTIALS ---
ADAFRUIT_IO_USERNAME = '--'
ADAFRUIT_IO_KEY = '---'
aio = Client(ADAFRUIT_IO_USERNAME, ADAFRUIT_IO_KEY)

username = urllib.parse.quote_plus('---')
password = urllib.parse.quote_plus('---') 
cluster = '----'

MONGO_URI = f"mongodb+srv://{username}:{password}@{cluster}/?retryWrites=true&w=majority"
BUFFER_FILE = "offline_buffer.json"

app = Flask(__name__)

# --- 2. DATABASE CONNECTION ---
try:
    client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=5000)
    db = client["SmartFusion_DB"]
    collection = db["SensorAnalytics"]
    client.admin.command('ping') 
    print(">>> Cloud Connection: ONLINE (Connected to Atlas)")
except Exception as e:
    print(f">>> Cloud Connection: OFFLINE (Local Buffer Active). Error: {e}")

# --- 3. GLOBAL CONSTANTS & VARIABLES ---
RL_VALUE = 10.0      
CLEAN_AIR_RATIO = 27.0 
GLOBAL_R0 = 10.0     

is_calibrated = False   
calibration_samples = [] 
gas_history = []     

# Memory buffers for performance evaluation
raw_history = []
filtered_history = []
WINDOW_SIZE = 15 # Size of the sliding window for statistical analysis

# --- 4. PERFORMANCE METRICS FUNCTION ---
def compute_performance(raw, filtered):
    """
    Calculates 4 key metrics to evaluate the efficiency of the fusion layer.
    """
    global raw_history, filtered_history
    raw_history.append(raw)
    filtered_history.append(filtered)
    
    if len(raw_history) > WINDOW_SIZE:
        raw_history.pop(0)
        filtered_history.pop(0)
    
    if len(raw_history) < 5: return {}

    r = np.array(raw_history)
    f = np.array(filtered_history)
    
    # 1. RMSE: Measures noise removal accuracy (Lower is better)
    rmse = np.sqrt(np.mean((r - f)**2))
    
    # 2. SNR: Signal-to-Noise Ratio in decibels (Higher is better)
    snr = 10 * np.log10(np.mean(f**2) / (np.std(r - f)**2 + 1e-6))
    
    # 3. VUR: Variance Reduction Percentage (Measures smoothing efficiency)
    vur = (1 - (np.var(f) / (np.var(r) + 1e-6))) * 100
    
    # 4. MAE: Mean Absolute Error (Measures alignment with raw sensor trend)
    mae = np.mean(np.abs(r - f))
    
    return {
        "RMSE": round(rmse, 3), 
        "SNR_dB": round(snr, 2), 
        "VUR_pct": round(vur, 1), 
        "MAE": round(mae, 3)
    }

# --- 5. DATA FUSION CLASSES ---
class KalmanFilter:
    """
    Temporal Fusion: Eliminates white noise using a recursive prediction-correction model.
    """
    def __init__(self, q=0.01, r=1.0, p=1.0, initial_x=0):
        self.q, self.r, self.p, self.x = q, r, p, initial_x
    def update(self, z):
        self.p += self.q
        k = self.p / (self.p + self.r) 
        self.x += k * (z - self.x)
        self.p *= (1 - k)
        return self.x

class EMAFilter:
    """
    Low-Pass Fusion: Smooths data using Exponential Moving Average.
    """
    def __init__(self, alpha=0.3):
        self.alpha, self.state = alpha, None
    def apply(self, value):
        if self.state is None: self.state = value
        self.state = self.alpha * value + (1 - self.alpha) * self.state
        return self.state

mq7_kalman = KalmanFilter(q=0.02, r=2.0)
temp_ema = EMAFilter(alpha=0.2)

# --- 6. HELPER FUNCTIONS ---
def perform_calibration(raw_adc):
    """
    Auto-Calibration: Calculates the specific R0 for the sensor in clean air.
    """
    global GLOBAL_R0, is_calibrated
    calibration_samples.append(raw_adc)
    print(f"Calibrating... Sample {len(calibration_samples)}/20")
    if len(calibration_samples) >= 20:
        avg_raw = sum(calibration_samples) / 20
        v_out = (avg_raw / 1023.0) * 5.0
        if v_out > 0:
            rs_air = ((5.0 * RL_VALUE) / v_out) - RL_VALUE
            GLOBAL_R0 = rs_air / CLEAN_AIR_RATIO
            is_calibrated = True
            print(f"Calibration Complete! New R0: {round(GLOBAL_R0, 2)} kOhms")

def raw_to_ppm(filtered_adc):
    """
    Conversion: Maps filtered ADC values to PPM based on MQ7 power-law curve.
    """
    v_out = (filtered_adc / 1023.0) * 5.0
    if v_out <= 0: return 0
    rs_gas = ((5.0 * RL_VALUE) / v_out) - RL_VALUE
    ratio = rs_gas / GLOBAL_R0
    ppm = 100 * pow(ratio, -1.53)
    return round(ppm, 2)

def save_locally(record):
    """
    Fault Tolerance: Caches data in a local JSON buffer if cloud is unreachable.
    """
    data = []
    if os.path.exists(BUFFER_FILE):
        try:
            with open(BUFFER_FILE, "r") as f: data = json.load(f)
        except: data = [] 
    data.append(record)
    with open(BUFFER_FILE, "w") as f: json.dump(data, f, indent=4)
    print("!!! Alert: Data cached locally (Offline Mode).")

def sync_local_data():
    """
    Data Persistence: Syncs cached offline data back to MongoDB once online.
    """
    if not os.path.exists(BUFFER_FILE): return
    try:
        with open(BUFFER_FILE, "r") as f: cached_data = json.load(f)
        if cached_data:
            print(f"Syncing {len(cached_data)} cached records to cloud...")
            collection.insert_many(cached_data)
            os.remove(BUFFER_FILE)
            print(">>> Sync Complete! Cloud Database Updated.")
    except Exception as e:
        print(f"!!! Sync failed: {e}")

# --- 7. MAIN FUSION PIPELINE ---
@app.route('/update', methods=['POST'])
def gateway_final():
    global is_calibrated, gas_history
    data = request.json
    raw_co = data['co_raw']
    raw_temp = data['temp']
    raw_hum = data['hum']
    
    if not is_calibrated:
        perform_calibration(raw_co)
        return jsonify({"status": "calibrating"}), 202

    # A) Level 0 Fusion: Outlier Detection (Statistical Gating)
    if len(gas_history) > 5:
        avg = sum(gas_history) / len(gas_history)
        if abs(raw_co - avg) > (avg * 0.6): raw_co = avg 
    gas_history.append(raw_co)
    if len(gas_history) > 10: gas_history.pop(0)

    # B) Level 1 Fusion: Kalman Filtering (Temporal Refinement)
    co_filtered_adc = mq7_kalman.update(raw_co)

    # C) Level 1 Fusion: EMA Filtering (Thermal Smoothing)
    fused_temp = temp_ema.apply(raw_temp)

    # D) Conversion: ADC -> PPM
    ppm_value = raw_to_ppm(co_filtered_adc)

    # E) Level 2 Fusion: Bayesian Humidity Correction (Contextual Refinement)
    corrected_ppm = ppm_value * 0.9 if raw_hum > 70 else ppm_value

    # F) Level 3 Fusion: Dempster-Shafer Decision Fusion (Threat Assessment)
    m1_danger = 0.8 if corrected_ppm > 50 else 0.1 
    m2_danger = 0.6 if fused_temp > 45 else 0.1 
    k = m1_danger*(1-m2_danger) + (1-m1_danger)*m2_danger
    danger_belief = (m1_danger * m2_danger) / (1 - k) if (1-k) != 0 else 0

    # G) Performance Evaluation: Real-time Metric Generation
    performance_metrics = compute_performance(raw_co, co_filtered_adc)

    # Data Persistence Object
    final_record = {
        "timestamp": time.time(),
        "fused_data": {
            "temp": round(fused_temp, 2),
            "ppm": round(corrected_ppm, 2),
            "danger_prob": round(danger_belief, 3),
            "performance": performance_metrics 
        },
        "raw_input": data
    }

    # Cloud Storage and Offline Synchronization
    try:
        collection.insert_one(final_record)
        sync_local_data()
    except Exception:
        save_locally(final_record)

    # Cloud Visualization: Adafruit IO
    try:
        aio.send('temperature', round(fused_temp, 2))
        aio.send('humidity', raw_hum)
        aio.send('gas-ppm', corrected_ppm)
        aio.send('danger-level', round(danger_belief * 100, 2))
    except Exception as e:
        print(f"Adafruit Error: {e}")

    # System Monitoring Dashboard
    print("-" * 50)
    print(f"| Temp: {round(fused_temp,1)}C | Hum: {raw_hum}% | Gas: {corrected_ppm} PPM | Danger: {round(danger_belief*100,1)}% |")
    if performance_metrics:
        print(f"| SNR: {performance_metrics['SNR_dB']}dB | VUR: {performance_metrics['VUR_pct']}% | RMSE: {performance_metrics['RMSE']} |")
    print("-" * 50)

    return jsonify({
        "status": "Success", 
        "ppm": round(corrected_ppm, 2),
        "danger": round(danger_belief, 3)
    }), 200

if __name__ == '__main__':
    # Initialize the Gateway Server
    print(">>> IoT Data Fusion Gateway ONLINE")
    app.run(host='0.0.0.0', port=5000, debug=True)