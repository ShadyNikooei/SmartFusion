/*
 * NodeMCU Edge Sensor Node (MQTT Version)
 * Sensors: DHT11 (Temp/Hum), MQ7 (CO Gas)
 * Protocol: MQTT (JSON)
 */
#include <ESP8266WiFi.h>
#include <PubSubClient.h> // Replaces HTTPClient
#include <DHT.h>

// --- Network Configuration ---
const char* ssid = "---";
const char* password = "---";

// --- MQTT Configuration ---
const char* mqtt_broker = "broker.hivemq.com";
const char* mqtt_topic = "smart_fusion/sensors";
const int mqtt_port = 1883;

// --- Pin Definitions ---
#define DHTPIN D4
#define DHTTYPE DHT11
#define MQ7PIN A0

DHT dht(DHTPIN, DHTTYPE);
WiFiClient espClient;
PubSubClient client(espClient);

void setup_wifi() {
  delay(10);
  Serial.print("Connecting to ");
  Serial.println(ssid);
  WiFi.begin(ssid, password);
  while (WiFi.status() != WL_CONNECTED) {
    delay(500);
    Serial.print(".");
  }
  Serial.println("\nWiFi Connected");
}

void reconnect() {
  while (!client.connected()) {
    Serial.print("Attempting MQTT connection...");
    // Create a random client ID
    String clientId = "ESP8266Client-";
    clientId += String(random(0xffff), HEX);
    if (client.connect(clientId.c_str())) {
      Serial.println("connected");
    } else {
      Serial.print("failed, rc=");
      Serial.print(client.state());
      Serial.println(" try again in 5 seconds");
      delay(5000);
    }
  }
}

void setup() {
  Serial.begin(115200);
  setup_wifi();
  client.setServer(mqtt_broker, mqtt_port);
  dht.begin();
}

void loop() {
  if (!client.connected()) {
    reconnect();
  }
  client.loop();

  float h = dht.readHumidity();
  float t = dht.readTemperature();
  int co_raw = analogRead(MQ7PIN);

  if (!isnan(h) && !isnan(t)) {
    // Construct JSON payload
    String payload = "{\"temp\":" + String(t) + 
                     ",\"hum\":" + String(h) + 
                     ",\"co_raw\":" + String(co_raw) + "}";
    
    Serial.print("Publishing message: ");
    Serial.println(payload);
    
    // Publish to the common topic
    if (client.publish(mqtt_topic, payload.c_str())) {
      Serial.println("Publish success");
    } else {
      Serial.println("Publish failed");
    }
  }

  delay(5000); // 5-second sampling interval
}