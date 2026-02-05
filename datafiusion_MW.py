import time
import urllib.parse
from flask import Flask, request, jsonify
from pymongo import MongoClient
import BlynkLib

# --- CONFIGURATION ---
BLYNK_AUTH = 'YOUR_BLYNK_AUTH_TOKEN'
# MongoDB Atlas Credentials
MONGO_USER = urllib.parse.quote_plus('your_username')
MONGO_PASS = urllib.parse.quote_plus('your_password')
# Replace xxxxx with your Cluster address from Atlas    
# mongodb+srv://shadyNikooei:<db_password>@cluster0.pzv5gh8.mongodb.net/
#MONGO_URI = f"mongodb+srv://{MONGO_USER}:{MONGO_PASS}@cluster0.xxxxx.mongodb.net/?retryWrites=true&w=majority"
MONGO_URI = f"mongodb+srv://shadyNikooei:SHAD@03niko@cluster0.pzv5gh8.mongodb.net/"
# Initialize Global Services
app = Flask(__name__)
blynk = BlynkLib.Blynk(BLYNK_AUTH)
client = MongoClient(MONGO_URI)
db = client["SmartFusion_DB"]
collection = db["SensorAnalytics"]

# --- DATA FUSION TECHNIQUES CLASSES/FUNCTIONS ---

# 1. Kalman Filter for MQ7 Noise Reduction
class KalmanFilter:
    def __init__(self, q=0.01, r=1.0, p=1.0, initial_x=0):
        self.q, self.r, self.p, self.x = q, r, p, initial_x
    def update(self, z):
        self.p += self.q
        k = self.p / (self.p + self.r)
        self.x += k * (z - self.x)
        self.p *= (1 - k)
        return self.x

# 2. Exponential Moving Average (EMA) for Smoothing
class EMAFilter:
    def __init__(self, alpha=0.3):
        self.alpha, self.state = alpha, None
    def apply(self, value):
        if self.state is None: self.state = value
        self.state = self.alpha * value + (1 - self.alpha) * self.state
        return self.state

# Initialize Global Filters
mq7_kalman = KalmanFilter(q=0.02, r=2.0)
temp_ema = EMAFilter(alpha=0.2)
gas_history = [] # For Outlier Detection

# 3. Fusion Logic Pipeline
def apply_advanced_fusion(t_raw, h_raw, co_raw):
    global gas_history
    
    # Technique A: Outlier Detection (Statistical Fusion)
    if len(gas_history) > 5:
        avg = sum(gas_history) / len(gas_history)
        if abs(co_raw - avg) > (avg * 0.6): # If 60% deviation, ignore outlier
            co_raw = avg
    gas_history.append(co_raw)
    if len(gas_history) > 10: gas_history.pop(0)

    # Technique B: Kalman Filtering (Temporal Fusion)
    co_kalman = mq7_kalman.update(co_raw)

    # Technique C: EMA Smoothing (Low-pass Fusion)
    fused_temp = temp_ema.apply(t_raw)

    # Technique D: Bayesian Correction (Contextual Fusion)
    # Correcting MQ7 bias in High Humidity (>70%)
    bayesian_co = co_kalman * 0.9 if h_raw > 70 else co_kalman

    # Technique E: Dempster-Shafer (Decision Fusion)
    m1_danger = 0.8 if bayesian_co > 400 else 0.1 # Evidence from Gas
    m2_danger = 0.6 if fused_temp > 45 else 0.1  # Evidence from Temp
    k = m1_danger*(1-m2_danger) + (1-m1_danger)*m2_danger
    danger_belief = (m1_danger * m2_danger) / (1 - k)

    return round(fused_temp, 2), round(bayesian_co, 2), round(danger_belief, 3)

@app.route('/update', methods=['POST'])
def gateway_api():
    data = request.json
    try:
        # Step 1: Execute Pipeline
        f_temp, f_gas, belief = apply_advanced_fusion(data['temp'], data['hum'], data['co_raw'])

        # Step 2: Persistence (MongoDB Atlas)
        record = {
            "timestamp": time.time(),
            "fused_data": {"temp": f_temp, "gas": f_gas, "danger": belief},
            "raw_input": data
        }
        collection.insert_one(record)

        # Step 3: Distribution (Blynk)
        blynk.virtual_write(1, f_temp)      # V1: Temperature Gauge
        blynk.virtual_write(2, f_gas)       # V2: Gas Level Chart
        blynk.virtual_write(3, belief*100)  # V3: Danger Probability (%)

        print(f"Update Success: Danger {belief*100}%")
        return jsonify({"status": "Success", "fused_gas": f_gas}), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500

if __name__ == '__main__':
    # host='0.0.0.0' makes the gateway accessible to NodeMCU
    app.run(host='0.0.0.0', port=5000, debug=True)