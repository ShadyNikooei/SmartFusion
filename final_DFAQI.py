import time
import json
import numpy as np
import os
import urllib.parse
import paho.mqtt.client as mqtt  # Replaces Flask
from pymongo import MongoClient
from Adafruit_IO import Client

# --- 1. CONFIGURATION & CREDENTIALS ---
ADAFRUIT_IO_USERNAME = '----'
ADAFRUIT_IO_KEY = '---'
aio = Client(ADAFRUIT_IO_USERNAME, ADAFRUIT_IO_KEY)

# MongoDB Configuration
username = urllib.parse.quote_plus('----')
password = urllib.parse.quote_plus('----') 
cluster = 'cluster0.pzv5gh8.mongodb.net'
MONGO_URI = f"mongodb+srv://{username}:{password}@{cluster}/?retryWrites=true&w=majority"
BUFFER_FILE = "offline_buffer.json"

# MQTT Configuration
MQTT_BROKER = "broker.hivemq.com" # Public broker for testing
MQTT_PORT = 1883
MQTT_TOPIC = "smart_fusion/sensors"

# --- 2. DATABASE CONNECTION ---
try:
    client_db = MongoClient(MONGO_URI, serverSelectionTimeoutMS=5000)
    db = client_db["SmartFusion_DB"]
    collection = db["SensorAnalytics"]
    client_db.admin.command('ping') 
    print(">>> Cloud Database: ONLINE")
except Exception as e:
    print(f">>> Cloud Database: OFFLINE. Error: {e}")

# --- 3. GLOBAL CONSTANTS & VARIABLES ---
RL_VALUE = 10.0      
CLEAN_AIR_RATIO = 27.0 
GLOBAL_R0 = 10.0     
is_calibrated = False   
calibration_samples = [] 
gas_history = []     
raw_history = []
filtered_history = []
WINDOW_SIZE = 15

# --- 4. PERFORMANCE METRICS FUNCTION ---
def compute_performance(raw, filtered):
    global raw_history, filtered_history
    raw_history.append(raw)
    filtered_history.append(filtered)
    if len(raw_history) > WINDOW_SIZE:
        raw_history.pop(0)
        filtered_history.pop(0)
    if len(raw_history) < 5: return {}
    r, f = np.array(raw_history), np.array(filtered_history)
    rmse = np.sqrt(np.mean((r - f)**2))
    snr = 10 * np.log10(np.mean(f**2) / (np.std(r - f)**2 + 1e-6))
    vur = (1 - (np.var(f) / (np.var(r) + 1e-6))) * 100
    mae = np.mean(np.abs(r - f))
    return {"RMSE": round(rmse, 3), "SNR_dB": round(snr, 2), "VUR_pct": round(vur, 1), "MAE": round(mae, 3)}

# --- 5. DATA FUSION CLASSES ---
class KalmanFilter:
    def __init__(self, q=0.01, r=1.0, p=1.0, initial_x=0):
        self.q, self.r, self.p, self.x = q, r, p, initial_x
    def update(self, z):
        self.p += self.q
        k = self.p / (self.p + self.r) 
        self.x += k * (z - self.x)
        self.p *= (1 - k)
        return self.x

class EMAFilter:
    def __init__(self, alpha=0.3):
        self.alpha, self.state = alpha, None
    def apply(self, value):
        if self.state is None: self.state = value
        self.state = self.alpha * value + (1 - self.alpha) * self.state
        return self.state

mq7_kalman = KalmanFilter(q=0.02, r=2.0)
temp_ema = EMAFilter(alpha=0.2)

# --- 6. HELPER FUNCTIONS (Calibration, Storage, Sync) ---
def perform_calibration(raw_adc):
    global GLOBAL_R0, is_calibrated
    calibration_samples.append(raw_adc)
    print(f"Calibrating... {len(calibration_samples)}/20")
    if len(calibration_samples) >= 20:
        avg_raw = sum(calibration_samples) / 20
        v_out = (avg_raw / 1023.0) * 5.0
        if v_out > 0:
            rs_air = ((5.0 * RL_VALUE) / v_out) - RL_VALUE
            GLOBAL_R0 = rs_air / CLEAN_AIR_RATIO
            is_calibrated = True
            print(f"Calibration Success! R0: {round(GLOBAL_R0, 2)}")

def raw_to_ppm(filtered_adc):
    v_out = (filtered_adc / 1023.0) * 5.0
    if v_out <= 0: return 0
    rs_gas = ((5.0 * RL_VALUE) / v_out) - RL_VALUE
    ratio = rs_gas / GLOBAL_R0
    return round(100 * pow(ratio, -1.53), 2)

def save_locally(record):
    data = []
    if os.path.exists(BUFFER_FILE):
        try:
            with open(BUFFER_FILE, "r") as f: data = json.load(f)
        except: data = [] 
    data.append(record)
    with open(BUFFER_FILE, "w") as f: json.dump(data, f, indent=4)

def sync_local_data():
    if not os.path.exists(BUFFER_FILE): return
    try:
        with open(BUFFER_FILE, "r") as f: cached_data = json.load(f)
        if cached_data:
            collection.insert_many(cached_data)
            os.remove(BUFFER_FILE)
            print(">>> Local data synced to cloud.")
    except: pass

# --- 7. MQTT CALLBACK (The Fusion Core) ---
def on_message(client, userdata, msg):
    """
    This function triggers every time a sensor publishes data to the MQTT topic.
    """
    global is_calibrated, gas_history
    try:
        data = json.loads(msg.payload.decode())
        raw_co = data['co_raw']
        raw_temp = data['temp']
        raw_hum = data['hum']

        if not is_calibrated:
            perform_calibration(raw_co)
            return

        # A) Outlier Detection
        if len(gas_history) > 5:
            avg = sum(gas_history) / len(gas_history)
            if abs(raw_co - avg) > (avg * 0.6): raw_co = avg 
        gas_history.append(raw_co)
        if len(gas_history) > 10: gas_history.pop(0)

        # B) Fusion Pipeline
        co_filtered_adc = mq7_kalman.update(raw_co)
        fused_temp = temp_ema.apply(raw_temp)
        ppm_value = raw_to_ppm(co_filtered_adc)
        corrected_ppm = ppm_value * 0.9 if raw_hum > 70 else ppm_value

        # C) Decision Fusion (Dempster-Shafer)
        m1_danger = 0.8 if corrected_ppm > 50 else 0.1 
        m2_danger = 0.6 if fused_temp > 45 else 0.1 
        k = m1_danger*(1-m2_danger) + (1-m1_danger)*m2_danger
        danger_belief = (m1_danger * m2_danger) / (1 - k) if (1-k) != 0 else 0

        # D) Metrics & Storage
        performance_metrics = compute_performance(raw_co, co_filtered_adc)
        final_record = {
            "timestamp": time.time(),
            "fused_data": {
                "temp": round(fused_temp, 2), "ppm": round(corrected_ppm, 2),
                "danger_prob": round(danger_belief, 3), "performance": performance_metrics 
            }
        }

        try:
            collection.insert_one(final_record)
            sync_local_data()
        except:
            save_locally(final_record)

        # E) Real-time Dashboard
        print("-" * 50)
        print(f"| Gas: {corrected_ppm} PPM | Temp: {round(fused_temp,1)}C | Danger: {round(danger_belief*100,1)}% |")
        if performance_metrics:
            print(f"| SNR: {performance_metrics['SNR_dB']}dB | VUR: {performance_metrics['VUR_pct']}% |")
        
        # Adafruit Upload
        aio.send('gas-ppm', corrected_ppm)
        aio.send('danger-level', round(danger_belief * 100, 2))

    except Exception as e:
        print(f"Pipeline Error: {e}")

# --- 8. MQTT CLIENT INITIALIZATION ---
mqtt_client = mqtt.Client()
mqtt_client.on_message = on_message

print(f">>> Connecting to Broker: {MQTT_BROKER}...")
try:
    mqtt_client.connect(MQTT_BROKER, MQTT_PORT, 60)
    mqtt_client.subscribe(MQTT_TOPIC)
    print(f">>> Subscribed to Topic: {MQTT_TOPIC}")
    print(">>> Waiting for Sensor Data...")
    mqtt_client.loop_forever() # Blocks and keeps the gateway alive
except Exception as e:
    print(f"MQTT Connection Failed: {e}")