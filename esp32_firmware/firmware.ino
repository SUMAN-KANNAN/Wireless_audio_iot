#include <WebSocketsClient.h> // Using the more common WebSockets library by Markus Sattler
#include <WiFi.h>
#include <driver/i2s.h> // Include the I2S driver library
#include <ArduinoJson.h>  // Include ArduinoJson for parsing messages
#include <driver/adc.h> // Include ADC driver for battery reading
#include <ESPmDNS.h>      // Include for mDNS service discovery
#include "secrets.h"      // Include your WiFi credentials and API key

// --- PRODUCTION-READY CONFIGURATION ---
// Set to 1 for real-world deployment (uses physical battery sensor).
// Set to 0 for development (uses simulated battery).
#define PRODUCTION 0

// --- ARCHITECTURAL UPGRADE: Service Discovery ---
// These variables will be populated automatically by mDNS, removing the need for a hardcoded IP.
char server_address[16];
uint16_t server_port = 0;

// Each physical ESP32 device must have a unique room ID that matches one of the rooms on the server dashboard.
const char* THIS_ROOM_ID = "conferenceRoom";

// WebSocket client instances for different purposes
WebSocketsClient audioClient;
WebSocketsClient statusClient;
WebSocketsClient batteryClient;

// I2S configuration (keep as is for now)
#define I2S_BCLK_PIN 26
#define I2S_LRCK_PIN 25
#define I2S_DATA_PIN 22
#define I2S_NUM I2S_NUM_0
#define SAMPLE_RATE 16000
#define BITS_PER_SAMPLE I2S_BITS_PER_SAMPLE_16BIT
// --- Audio Tuning Parameters ---
// A larger DMA buffer provides more stability and prevents crashes/noise from network jitter.
// These values can be tuned for performance vs. memory usage
#define I2S_DMA_BUFFER_COUNT 8
#define I2S_DMA_BUFFER_LENGTH 1024

// Battery reading configuration
#define BATTERY_ADC_CHANNEL ADC1_CHANNEL_0

// MAX98357A volume control pin (adjust pin number)
#define VOLUME_CONTROL_PIN 13
uint8_t volume_pwm_channel = 0;

// --- ROBUSTNESS UPGRADE: WiFi Watchdog ---
unsigned long lastWiFiDisconnectTime = 0;
const unsigned long wifiReconnectTimeout = 30000; // 30 seconds before restarting

// --- STATE MACHINE UPGRADE: Explicitly track audio state ---
bool isAudioActive = false;

void connectWiFi() {
    Serial.printf("Connecting to WiFi SSID: %s\n", ssid);
    WiFi.begin(ssid, password);
    unsigned long startAttemptTime = millis();
    // --- ROBUSTNESS UPGRADE: Add a timeout to WiFi connection ---
    while (WiFi.status() != WL_CONNECTED && millis() - startAttemptTime < 15000) { // 15-second timeout
        delay(500);
        Serial.print(".");
    }
    if (WiFi.status() == WL_CONNECTED) {
        Serial.println("\nWiFi Connected!");
        Serial.print("IP Address: ");
        Serial.println(WiFi.localIP());
    } else {
        Serial.println("\nWiFi connection failed. Please check credentials in secrets.h");
    }
}

void discoverAudioServer() {
    Serial.println("Searching for audio server via mDNS...");
    if (!MDNS.begin(THIS_ROOM_ID)) {
        Serial.println("Error setting up MDNS responder!");
        return;
    }

    unsigned long discoveryStartTime = millis();
    const unsigned long discoveryTimeout = 10000; // 10-second timeout

    while (server_port == 0) {
        // Query for the service type "_web-audio" and protocol "_tcp"
        int n = MDNS.queryService("web-audio", "tcp");
        if (n == 0) {
            Serial.println("No audio server found, retrying in 5 seconds...");
            if (millis() - discoveryStartTime > discoveryTimeout) {
                Serial.println("mDNS discovery timed out. Will retry in the background.");
                break; // Exit the loop to prevent getting stuck
            }
            delay(5000);
        } else {
            Serial.printf("%d service(s) found\n", n);
            // --- WORKAROUND for compilation error ---
            // Instead of MDNS.IP(0), we get the hostname and then resolve its IP.
            // This avoids the function call that is failing to compile.
            String host = MDNS.hostname(0);
            if (host.length() > 0) {
                Serial.printf("Found service host: %s. Resolving IP...\n", host.c_str());
                IPAddress serverIp = MDNS.queryHost(host);

                if (serverIp != INADDR_NONE) {
                    strcpy(server_address, serverIp.toString().c_str());
                    server_port = MDNS.port(0);
                    Serial.printf("Audio Server Found! Address: %s:%d\n", server_address, server_port);
                    break; // Exit the loop once the server is found
                }
            }
            Serial.println("Could not resolve service IP. Retrying...");
            delay(2000); // Wait a bit before retrying the whole loop
        }
    }
}

void i2s_init() {
    i2s_config_t i2s_config = {
        .mode = (i2s_mode_t)(I2S_MODE_MASTER | I2S_MODE_TX),
        .sample_rate = SAMPLE_RATE,
        .bits_per_sample = BITS_PER_SAMPLE,
        .channel_format = I2S_CHANNEL_FMT_ONLY_LEFT,
        .communication_format = I2S_COMM_FORMAT_I2S,
        .intr_alloc_flags = 0,
        .dma_buf_count = I2S_DMA_BUFFER_COUNT,
        .dma_buf_len = I2S_DMA_BUFFER_LENGTH,
        .use_apll = false
    };

    i2s_pin_config_t pin_config = {
        .bck_io_num = I2S_BCLK_PIN,
        .ws_io_num = I2S_LRCK_PIN,
        .data_out_num = I2S_DATA_PIN,
        .data_in_num = I2S_PIN_NO_CHANGE
    };

    // --- ROBUSTNESS UPGRADE: Check for errors during I2S installation ---
    esp_err_t err = i2s_driver_install(I2S_NUM, &i2s_config, 0, NULL);
    if (err != ESP_OK) {
        Serial.printf("I2S driver install failed with error code: %d\n", err);
    }

    i2s_set_pin(I2S_NUM, &pin_config);
    i2s_zero_dma_buffer(I2S_NUM);
}

void playAudio(const uint8_t* data, size_t len) {
    size_t bytes_written;
    i2s_write(I2S_NUM, data, len, &bytes_written, portMAX_DELAY);
}

float readBatteryVoltage() {
    int reading = 0;
    for(int i = 0; i < 10; i++) {
        reading += adc1_get_raw(BATTERY_ADC_CHANNEL);
        delay(1);
    }
    float averageReading = reading / 10.0;
    float voltage = (averageReading / 4095.0) * 3.3 * 2.0; 
    return voltage;
}

int voltageToPercentage(float voltage) {
    // --- ACCURACY UPGRADE: Use a non-linear mapping for LiPo batteries ---
    // This provides a more realistic battery percentage on the dashboard.
    if (voltage >= 4.20) return 100;
    if (voltage >= 4.00) return map(voltage * 100, 400, 420, 76, 100);
    if (voltage >= 3.80) return map(voltage * 100, 380, 400, 52, 76);
    if (voltage >= 3.60) return map(voltage * 100, 360, 380, 28, 52);
    if (voltage >= 3.40) return map(voltage * 100, 340, 360, 5, 28);
    if (voltage >= 3.20) return map(voltage * 100, 320, 340, 0, 5);
    return 0; // Voltages below 3.2V are considered 0% for safety.
}

void setVolume(int volume) {
    float mapped_volume = (pow(1.05, volume) - 1) / (pow(1.05, 100) - 1) * 255;
    int dutyCycle = static_cast<int>(mapped_volume);
    ledcWrite(volume_pwm_channel, dutyCycle);
    Serial.printf("Setting volume. Level: %d -> PWM Duty Cycle: %d\n", volume, dutyCycle);
}

// --- WebSocket Event Handlers ---

void audioWebSocketEvent(WStype_t type, uint8_t * payload, size_t length) {
  switch(type) {
    case WStype_DISCONNECTED:
      Serial.printf("[AudioWS] Disconnected!\n");
      i2s_stop(I2S_NUM);
      i2s_zero_dma_buffer(I2S_NUM);
      // If the disconnection was unintentional (i.e., we still think we should be active),
      // update our state and inform the server so the dashboard UI is correct.
      if (isAudioActive) {
          isAudioActive = false;
          StaticJsonDocument<100> status_doc;
          status_doc["room"] = THIS_ROOM_ID;
          status_doc["status"] = "Sleep";
          char statusMessage[128];
          serializeJson(status_doc, statusMessage, sizeof(statusMessage));
          if (statusClient.isConnected()) {
              statusClient.sendTXT(statusMessage, strlen(statusMessage));
          }
      }
      break;
    case WStype_CONNECTED:
      Serial.printf("[AudioWS] Connected to url: %s\n", payload);
            {
            StaticJsonDocument<100> id_doc;
            id_doc["type"] = "room_identification";
            id_doc["roomId"] = THIS_ROOM_ID;
            char json_buffer[128];
            serializeJson(id_doc, json_buffer, sizeof(json_buffer));
            audioClient.sendTXT(json_buffer, strlen(json_buffer));
            i2s_start(I2S_NUM);
            }
      break;
    case WStype_TEXT:
            {
                StaticJsonDocument<200> doc;
                DeserializationError error = deserializeJson(doc, payload, length);
                if (!error && doc.containsKey("type") && String(doc["type"]) == "volume_set" && doc.containsKey("volume")) {
                    int volumeLevel = doc["volume"];
                    setVolume(volumeLevel);
                }
            }
      break;
    case WStype_BIN:
            playAudio(payload, length);
      break;
    default:
      break;
  }
}

void statusWebSocketEvent(WStype_t type, uint8_t * payload, size_t length) {
    switch(type) {
        case WStype_DISCONNECTED:
            Serial.printf("[StatusWS] Disconnected!\n");
            break;
        case WStype_CONNECTED:
            Serial.printf("[StatusWS] Connected to url: %s\n", payload);
            {
                StaticJsonDocument<100> id_doc;
                id_doc["type"] = "room_identification";
                id_doc["roomId"] = THIS_ROOM_ID;
                char json_buffer[128];
                serializeJson(id_doc, json_buffer, sizeof(json_buffer));
                statusClient.sendTXT(json_buffer, strlen(json_buffer));

                // --- FIX: Send initial status upon connection ---
                // This tells the dashboard that the device is online and idle (orange status).
                StaticJsonDocument<100> status_doc;
                status_doc["room"] = THIS_ROOM_ID;
                status_doc["status"] = "Sleep"; // Devices always start in sleep mode.
                serializeJson(status_doc, json_buffer, sizeof(json_buffer));
                statusClient.sendTXT(json_buffer, strlen(json_buffer));
            }
            break;
        case WStype_TEXT:
            {
                StaticJsonDocument<200> doc;
                DeserializationError error = deserializeJson(doc, payload, length);
                if (!error && doc.containsKey("room") && String(doc["room"]) == THIS_ROOM_ID && doc.containsKey("status")) {
                    String newStatus = doc["status"];
                    Serial.printf("Received status command for this room: %s\n", newStatus.c_str());

                    if ((newStatus == "Active" || newStatus == "On") && !isAudioActive) {
                        isAudioActive = true;
                        Serial.println("Server commanded to turn ON. Re-initiating audio connection...");
                        if (server_port == 0) {
                            discoverAudioServer();
                        }
                        audioClient.begin(server_address, server_port, "/ws/audio");
                    } else if ((newStatus == "Sleep" || newStatus == "Off") && isAudioActive) {
                        isAudioActive = false;
                        Serial.println("Server commanded to turn OFF. Disconnecting audio client...");
                        if (audioClient.isConnected()) {
                            audioClient.disconnect();
                        }
                        // Explicitly stop the I2S driver to be safe
                        i2s_stop(I2S_NUM);
                        i2s_zero_dma_buffer(I2S_NUM);
                    }
                }
            }
            break;
        default:
            break;
    }
}

void batteryWebSocketEvent(WStype_t type, uint8_t * payload, size_t length) {
    switch(type) {
        case WStype_DISCONNECTED:
            Serial.printf("[BatteryWS] Disconnected!\n");
            break;
        case WStype_CONNECTED:
            Serial.printf("[BatteryWS] Connected to url: %s\n", payload);
            {
                StaticJsonDocument<100> id_doc;
                id_doc["type"] = "room_identification";
                id_doc["roomId"] = THIS_ROOM_ID;
                char json_buffer[128];
                serializeJson(id_doc, json_buffer, sizeof(json_buffer));
                batteryClient.sendTXT(json_buffer, strlen(json_buffer));
            }
            break;
        case WStype_TEXT:
            // Not expecting text from server on this channel
            break;
        default:
            break;
    }
}

void setupVolumeControl() {
    // --- COMPATIBILITY UPGRADE: Handle different ESP32 Core versions ---
    #if ESP_ARDUINO_VERSION_MAJOR >= 3
        volume_pwm_channel = ledcAttach(VOLUME_CONTROL_PIN, 5000, 8);
    #else
        const int pwm_channel = 0;
        ledcSetup(pwm_channel, 5000, 8);
        ledcAttachPin(VOLUME_CONTROL_PIN, pwm_channel);
        volume_pwm_channel = pwm_channel;
    #endif
}

void setup() {
    Serial.begin(115200);
    delay(1000);

    connectWiFi();
    // --- TROUBLESHOOTING: Hardcode server IP if mDNS fails ---
    // If the device cannot find the server automatically, you can set the IP manually.
    // 1. Find your computer's IP address (e.g., run 'ipconfig' in Windows Command Prompt).
    // 2. Replace the IP below, and then comment out the discoverAudioServer() line.
    strcpy(server_address, "192.168.1.18"); // <-- Set to your computer's IP from the server log
    server_port = 5000;
    // discoverAudioServer(); // Comment this out if you hardcode the IP above.

    setupVolumeControl();
    setVolume(50);

    adc1_config_width(ADC_WIDTH_BIT_12);
    adc1_config_channel_atten(BATTERY_ADC_CHANNEL, ADC_ATTEN_DB_11); // Use ADC_ATTEN_DB_11 for full 0-3.3V range
    i2s_init();

    audioClient.onEvent(audioWebSocketEvent);
    statusClient.onEvent(statusWebSocketEvent);
    batteryClient.onEvent(batteryWebSocketEvent);

    // --- BUG FIX: Prevent audio from auto-reconnecting ---
    // The audio client should ONLY connect when commanded by the dashboard, not automatically.
    // audioClient.setReconnectInterval(5000);
    statusClient.setReconnectInterval(5000); // Set reconnect interval for all clients
    batteryClient.setReconnectInterval(5000);

    String apiKeyHeader = "X-API-Key: " + String(device_api_key);
    audioClient.setExtraHeaders(apiKeyHeader.c_str());
    statusClient.setExtraHeaders(apiKeyHeader.c_str());
    batteryClient.setExtraHeaders(apiKeyHeader.c_str());

    if (server_port != 0) {
        statusClient.begin(server_address, server_port, "/ws/status");
        batteryClient.begin(server_address, server_port, "/ws/battery");
    }

    Serial.println("\n--- Setup complete. Device is ready. ---");
}

void handleBatteryLogic() {
    static unsigned long lastBatteryUpdateTime = 0;
    const unsigned long batteryUpdateInterval = 5000; // Send update every 5 seconds

    if (millis() - lastBatteryUpdateTime >= batteryUpdateInterval && batteryClient.isConnected()) {
        int percentage;
#if PRODUCTION == 1
        float voltage = readBatteryVoltage();
        percentage = voltageToPercentage(voltage);
        Serial.printf("Sent REAL battery status: %d%% (%.2fV)\n", percentage, voltage);
#else
        // --- DEVELOPMENT UPGRADE: Match virtual_esp32.py battery simulation ---
        // This makes testing the dashboard UI predictable and consistent.
        static int simulated_battery = 100;
        simulated_battery -= 2; // Drain by 2% every 5 seconds
        if (simulated_battery <= 5) simulated_battery = 100; // "Recharge" when it hits 5%
        percentage = simulated_battery;
        Serial.printf("Sent PREDICTABLE SIMULATED battery status: %d%%\n", percentage);
#endif
        StaticJsonDocument<100> doc;
        doc["room"] = THIS_ROOM_ID;
        doc["percentage"] = percentage;
        char json_buffer[128];
        serializeJson(doc, json_buffer, sizeof(json_buffer));
        batteryClient.sendTXT(json_buffer, strlen(json_buffer));
        lastBatteryUpdateTime = millis();
    }
}

void handleDiscoveryLogic() {
    static unsigned long lastDiscoveryAttempt = 0;
    const unsigned long discoveryInterval = 30000; // Retry discovery every 30 seconds

    if (server_port == 0 && (millis() - lastDiscoveryAttempt > discoveryInterval)) {
        Serial.println("Server not yet discovered. Retrying mDNS query...");
        discoverAudioServer();
        
        if (server_port != 0) {
            Serial.println("Server discovered. Initiating connections...");
            statusClient.begin(server_address, server_port, "/ws/status");
            batteryClient.begin(server_address, server_port, "/ws/battery");
        }
        lastDiscoveryAttempt = millis();
    }
}

void handleWiFiDisconnect() {
    if (lastWiFiDisconnectTime == 0) {
        Serial.println("WiFi connection lost. Attempting to reconnect...");
        lastWiFiDisconnectTime = millis();
        // Disconnect clients cleanly before attempting WiFi reconnect
        audioClient.disconnect();
        statusClient.disconnect();
        batteryClient.disconnect();
        WiFi.disconnect();
        WiFi.begin(ssid, password);
    }

    // If it's been too long, restart the device to force a clean state
    if (millis() - lastWiFiDisconnectTime > wifiReconnectTimeout) {
        Serial.println("Failed to reconnect to WiFi. Restarting device...");
        ESP.restart();
    }
}

void loop() {
    // --- ROBUSTNESS UPGRADE: Add a WiFi connection watchdog ---
    // If WiFi disconnects, try to reconnect. If it fails for too long, restart.
    if (WiFi.status() != WL_CONNECTED) {
        handleWiFiDisconnect();
        delay(1000); // Wait a moment before next check
        return; // Don't run client loops if WiFi is down
    }
    lastWiFiDisconnectTime = 0; // Reset timer if connection is good

    if (isAudioActive) {
        audioClient.loop();
    }
    statusClient.loop();
    batteryClient.loop();
    handleBatteryLogic();
    // handleDiscoveryLogic(); // Comment this out if you hardcode the IP address
}
