# SmartFusion: Multi-Sensor Data Fusion and Environmental Monitoring

SmartFusion is an intelligent IoT-based air quality monitoring system
that leverages **Multi-Level Data Fusion** to provide accurate CO gas
concentration and environmental risk assessments.\
The system integrates hardware edge nodes with a Python-based
intelligent gateway and cloud-hosted databases.


## Features

-   **Multi-Level Fusion**
    -   Kalman Filtering (Data-level)
    -   Dempster-Shafer Theory (Decision-level)
-   **Dual Protocol Support**
    -   HTTP (REST -- Legacy)
    -   MQTT (Publish/Subscribe -- Optimized)
-   **Fault Tolerance**
    -   Local buffering for offline data persistence
-   **Real-time Analytics**
    -   Performance metrics: SNR, RMSE, VUR
-   **Cloud Integration**
    -   MongoDB Atlas
    -   Adafruit IO


## Hardware Components

The system utilizes the following hardware at the Edge layer:

-   **NodeMCU (ESP8266)** -- Main processing unit and WiFi gateway\
-   **MQ-7 Gas Sensor** -- Carbon Monoxide (CO) detection\
-   **DHT11 Sensor** -- Temperature and Humidity monitoring\
-   **Level Shifters / Potentiometers** -- Sensor calibration and
    voltage matching

## Software Stack and Platforms

### Development Environments

-   **Arduino IDE** -- Programming and flashing NodeMCU firmware\
-   **VS Code / PyCharm** -- Python Gateway and data analysis scripts

### Cloud Platforms

-   **MongoDB Atlas** -- Cloud-hosted NoSQL database\
-   **Adafruit IO** -- Real-time IoT dashboard and monitoring\
-   **HiveMQ** -- Public MQTT broker

### Software Libraries

**Python** - paho-mqtt (v2.1.0) - pymongo - matplotlib - numpy -
Adafruit_IO

**Arduino** - ESP8266WiFi - PubSubClient - DHT Sensor Library

## Communication Protocols

### 1. HTTP Protocol (Legacy)

-   **Architecture:** Client--Server (Request--Response)
-   **Workflow:** NodeMCU sends JSON payloads via POST requests to a
    Flask-based Python server
-   **Best for:** Simple point-to-point communication

### 2. MQTT Protocol (Current / Optimized)

-   **Architecture:** Publish/Subscribe
-   **Broker:** `broker.hivemq.com`
-   **Workflow:** Decouples sensor nodes from the gateway, enabling
    lower latency and higher reliability


## Edge Node Implementation

The NodeMCU firmware (`AQI.ino`) is responsible for:

-   Initializing WiFi and MQTT connections
-   Sampling data from MQ-7 (Analog) and DHT11 (Digital) sensors
-   Packaging sensor data into JSON format
-   Publishing data to the `smart_fusion/sensors` topic every 5 seconds


## Performance Metrics

| Metric | Value (Avg) | Description |
|------|-------------|-------------|
| SNR  | > 25 dB     | Signal-to-Noise Ratio |
| RMSE | < 0.05      | Root Mean Square Error |
| VUR  | ~ 85%       | Variance Reduction |



## Installation and Setup

1.  **Clone the repository**

``` bash
git clone https://github.com/yourusername/SmartFusion.git
```

2.  **Install dependencies**

``` bash
pip install paho-mqtt pymongo matplotlib numpy Adafruit_IO
```

3.  **Configure Database**

-   Update `MONGO_URI` in `main_gateway.py`

4.  **Run the Gateway**

``` bash
python main_gateway.py
```

5.  **Run the Visualizer**

``` bash
python output_analysis.py
```


## Author

Developed by **Shady Nikooei** as an Computer Engineer.
