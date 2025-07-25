#include <WebSocketsClient.h> // Using the more common WebSockets library by Markus Sattler
#include <WiFi.h>
#include <driver/i2s.h> // Include the I2S driver library
#include <ArduinoJson.h>  // Include ArduinoJson for parsing messages
#include <driver/adc.h> // Include ADC driver for battery reading
#include <ESPmDNS.h>      // Include for mDNS service discovery
#include "secrets.h"      // Include your WiFi credentials and API key

// --- ARCHITECTURAL UPGRADE: Service Discovery ---
// These variables will be populated automatically by mDNS, removing the need for a hardcoded IP.
String server_address;
uint16_t server_port = 0;

// Each physical ESP32 device must have a unique room ID that matches one of the rooms on the server dashboard.
const char* THIS_ROOM_ID = "conferenceRoom"; // <-- SET THIS FOR EACH ESP32 (e.g., "adminRoom", "classRoom")
// WebSocket client instances for different purposes
WebSocketsClient audioClient;
WebSocketsClient statusClient;
WebSocketsClient batteryClient;

// I2S configuration (keep as is for now)
#define I2S_BCLK_PIN 26   // Replace with your I2S BCLK pin
#define I2S_LRCK_PIN 25   // Replace with your I2S LRCK (WS) pin
#define I2S_DATA_PIN 22   // Replace with your I2S DATA (DOUT) pin
#define I2S_NUM I2S_NUM_0 // I2S port number (usually I2S_NUM_0 or I2S_NUM_1)
#define SAMPLE_RATE 16000 // Audio sample rate (adjust as needed)
#define BITS_PER_SAMPLE I2S_BITS_PER_SAMPLE_16BIT

// Audio buffer (keep as is for now)
const int audio_buffer_size = 1024; // Adjust buffer size as needed
int16_t audio_buffer[audio_buffer_size];

// Battery reading configuration
#define BATTERY_ADC_CHANNEL ADC1_CHANNEL_0 // Replace with your actual ADC channel (e.g., ADC1_CHANNEL_0 for GPIO36)
#define BATTERY_ADC_UNIT ADC_UNIT_1 // Use ADC_UNIT_1 (or ADC_UNIT_2 if needed)

// MAX98357A volume control pin (adjust pin number)
#define VOLUME_CONTROL_PIN 13  // Example GPIO pin

// Function to connect to WiFi (keep as is)
void connectWiFi() {
    Serial.printf("Connecting to WiFi SSID: %s\n", ssid);
    WiFi.begin(ssid, password);
    Serial.print("Waiting for connection...");
    while (WiFi.status() != WL_CONNECTED) {
        delay(500);
        Serial.print(".");
    }
    Serial.println("\nWiFi Connected!");
    Serial.print("IP Address: ");
    Serial.println(WiFi.localIP());
}

void discoverAudioServer() {
    Serial.println("Searching for audio server via mDNS...");
    if (!MDNS.begin(THIS_ROOM_ID)) {
        Serial.println("Error setting up MDNS responder!");
        return;
    }

    while (server_port == 0) {
        // Query for the service type "_web-audio" and protocol "_tcp"
        int n = MDNS.queryService("web-audio", "tcp");
        if (n == 0) {
            Serial.println("No audio server found, retrying in 5 seconds...");
            delay(5000);
        } else {
            Serial.printf("%d service(s) found\n", n);
            server_address = MDNS.IP(0).toString();
            server_port = MDNS.port(0);
            Serial.printf("Audio Server Found! Address: %s:%d\n", server_address.c_str(), server_port);
            break; // Exit the loop once the server is found
        }
    }
}

// Function to initialize I2S (keep as is for now)
void i2s_init() {
    i2s_config_t i2s_config = {
        .mode = (i2s_mode_t)(I2S_MODE_MASTER | I2S_MODE_TX), // Master, transmit
        .sample_rate = SAMPLE_RATE,
        .bits_per_sample = BITS_PER_SAMPLE,
        .channel_format = I2S_CHANNEL_FMT_ONLY_RIGHT, // Mono output for MAX98357A
        .communication_format = I2S_COMM_FORMAT_I2S,  // I2S format
        .intr_alloc_flags = 0,                       // Default interrupt priority
        // --- Audio Tuning Parameters ---
        // A larger DMA buffer provides more stability and prevents crashes/noise from network jitter.
        .dma_buf_count = 8,                          // Number of DMA buffers
        .dma_buf_len = 1024,                         // Size of each DMA buffer in bytes
        .use_apll = false                            // Use XTAL oscillator
    };

     i2s_pin_config_t pin_config = {
        .bck_io_num = I2S_BCLK_PIN,
        .ws_io_num = I2S_LRCK_PIN,
        .data_out_num = I2S_DATA_PIN,
        .data_in_num = I2S_PIN_NO_CHANGE // Not used in TX mode
    };

    i2s_driver_install(I2S_NUM, &i2s_config, 0, NULL);
    i2s_set_pin(I2S_NUM, &pin_config);
    i2s_zero_dma_buffer(I2S_NUM); // Clear DMA buffer to prevent noise on startup
}

void playAudio(const uint8_t* data, size_t len) {
    size_t bytes_written;
    // Write the audio data to the I2S peripheral
    i2s_write(I2S_NUM, data, len, &bytes_written, portMAX_DELAY);
}

// --- Real Battery Reading ---
float readBatteryVoltage() {
    // Perform multiple readings for a more stable value
    int reading = 0;
    for(int i = 0; i < 10; i++) {
        reading += adc1_get_raw(BATTERY_ADC_CHANNEL);
        delay(1);
    }
    float averageReading = reading / 10.0;
    
    // Convert ADC reading to voltage.
    // This formula assumes a 1:1 voltage divider (e.g., two 100k resistors) and a 3.3V reference,
    // which doubles the measured voltage to get the real battery voltage.
    // If you have no voltage divider, change the multiplication factor from 2.0 to 1.0.
    float voltage = (averageReading / 4095.0) * 3.3 * 2.0; 
    return voltage;
}

int voltageToPercentage(float voltage) {
    // This is an approximate mapping for a standard 3.7V LiPo battery.
    // For better accuracy, you should test your specific battery's discharge curve.
    return constrain(map(voltage * 100, 330, 420, 0, 100), 0, 100);
}

void setVolume(int volume) {
    // --- UPGRADE: Granular Volume Control using PWM ---
    // Map the 0-100 volume from the dashboard to an 8-bit PWM duty cycle (0-255).
    // The MAX98357A's SD_MODE (shutdown) pin can be driven by PWM for volume control.
    // A non-linear (e.g., logarithmic) curve can feel more natural to the human ear,
    // but a linear mapping is a great first step.
    int dutyCycle = map(volume, 0, 100, 0, 255);

    // NOTE: Depending on the amplifier board's logic, you might need to invert the mapping.
    // If 100% volume becomes silent, use this line instead:
    // int dutyCycle = map(volume, 0, 100, 255, 0);
    
    ledcWrite(0, dutyCycle); // Write the duty cycle to the configured PWM channel (0).
    Serial.printf("Setting volume. Level: %d -> PWM Duty Cycle: %d\n", volume, dutyCycle);
}

// --- WebSocket Event Handlers ---

void audioWebSocketEvent(WStype_t type, uint8_t * payload, size_t length) {
  switch(type) {
    case WStype_DISCONNECTED:
      Serial.printf("[AudioWS] Disconnected!\n");
      // Stop the I2S driver and clear its buffer when the audio stream stops.
      i2s_stop(I2S_NUM);
      i2s_zero_dma_buffer(I2S_NUM);
      // --- RELIABILITY FIX: Report that the device is now in a sleep state ---
      if (statusClient.isConnected()) {
          String statusMessage = "{\"room\": \"" + String(THIS_ROOM_ID) + "\", \"status\": \"Sleep\"}";
          statusClient.sendTXT(statusMessage);
          Serial.printf("Sent Sleep status: %s\n", statusMessage.c_str());
      }
      break;
    case WStype_CONNECTED:
      Serial.printf("[AudioWS] Connected to url: %s\n", payload);
            // Send room identification
            {
                String roomIdentificationMessage = "{\"type\": \"room_identification\", \"roomId\": \"" + String(THIS_ROOM_ID) + "\", \"client_type\": \"device\"}";
                audioClient.sendTXT(roomIdentificationMessage);
                Serial.printf("Sent room identification: %s\n", roomIdentificationMessage.c_str());
            }
            // Send initial "Active" status
            if (statusClient.isConnected()) {
                String statusMessage = "{\"room\": \"" + String(THIS_ROOM_ID) + "\", \"status\": \"Active\"}";
                statusClient.sendTXT(statusMessage);
                Serial.printf("Sent initial status: %s\n", statusMessage.c_str());
            }
            // Start the I2S port to be ready for audio data
            i2s_start(I2S_NUM);
      break;
    case WStype_TEXT:
            Serial.printf("[AudioWS] Received text: %s\n", payload);
            // Parse JSON for volume commands
            {
                StaticJsonDocument<200> doc;
                DeserializationError error = deserializeJson(doc, payload, length);
                if (error) {
                    Serial.print("JSON parsing failed on Audio WebSocket: ");
                    Serial.println(error.c_str());
                    return;
                }
                if (doc.containsKey("type") && String(doc["type"]) == "volume_set" && doc.containsKey("volume")) {
                    int volumeLevel = doc["volume"];
                    Serial.printf("Received volume command: %d\n", volumeLevel);
                    setVolume(volumeLevel);
                }
            }
      break;
    case WStype_BIN:
      Serial.printf("[AudioWS] Received binary of length: %u\n", length);
            playAudio(payload, length);
      break;
    case WStype_ERROR:      
    case WStype_FRAGMENT_TEXT_START:
    case WStype_FRAGMENT_BIN_START:
    case WStype_FRAGMENT:
    case WStype_FRAGMENT_FIN:
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
            break;
        case WStype_TEXT:
            Serial.printf("[StatusWS] Received text: %s\n", payload);
            // --- REACT TO SERVER COMMANDS ---
            // This allows the dashboard to turn the device on or off remotely.
            {
                StaticJsonDocument<200> doc;
                DeserializationError error = deserializeJson(doc, payload, length);
                if (error) {
                    Serial.print("JSON parsing failed on Status WebSocket: ");
                    Serial.println(error.c_str());
                    return;
                }

                // Check if the command is for this specific device
                if (doc.containsKey("room") && String(doc["room"]) == THIS_ROOM_ID && doc.containsKey("status")) {
                    String newStatus = doc["status"];
                    Serial.printf("Received status command for this room: %s\n", newStatus.c_str());

                    if ((newStatus == "Active" || newStatus == "On") && !audioClient.isConnected()) {
                        Serial.println("Server commanded to turn ON. Re-initiating audio connection...");
                        // Re-call begin() to establish a new connection if it was manually disconnected.
                        audioClient.begin(server_address, server_port, "/ws/audio");
                    } else if ((newStatus == "Sleep" || newStatus == "Off") && audioClient.isConnected()) {
                        Serial.println("Server commanded to turn OFF. Disconnecting audio client...");
                        audioClient.disconnect();
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
            break;
        case WStype_TEXT:
            Serial.printf("[BatteryWS] Received text: %s\n", payload);
            break;
        default:
            break;
    }
}

void setup() {
    Serial.begin(115200);
    delay(1000);

    connectWiFi(); // Connect to WiFi

    // Discover the server on the network
    discoverAudioServer();

    // --- Initialize PWM for Volume Control ---
    // Setup LEDC channel 0, with a 5kHz frequency and 8-bit resolution (0-255).
    ledcSetup(0, 5000, 8);
    // Attach the volume control pin to the configured PWM channel.
    ledcAttachPin(VOLUME_CONTROL_PIN, 0);
    setVolume(50); // Set a default volume on startup.

    // Configure ADC for real battery reading
    adc1_config_width(ADC_WIDTH_BIT_12);
    adc1_config_channel_atten(BATTERY_ADC_CHANNEL, ADC_ATTEN_DB_11);

    i2s_init(); // Initialize I2S for audio playback

    // Set WebSocket event and message handlers for each client
    audioClient.onEvent(audioWebSocketEvent);
    statusClient.onEvent(statusWebSocketEvent);
    batteryClient.onEvent(batteryWebSocketEvent);

    const unsigned long reconnectInterval = 5000; // 5 seconds
    audioClient.setReconnectInterval(reconnectInterval);
    statusClient.setReconnectInterval(reconnectInterval);
    batteryClient.setReconnectInterval(reconnectInterval);

    // --- SECURITY UPGRADE: Use HTTP Headers for Authentication ---
    // Sending the API key in a header is more secure than a query parameter.
    String apiKeyHeader = "X-API-Key: " + String(device_api_key);
    audioClient.setExtraHeaders(apiKeyHeader.c_str());
    statusClient.setExtraHeaders(apiKeyHeader.c_str());
    batteryClient.setExtraHeaders(apiKeyHeader.c_str());

    // Begin the initial connection for all clients (no token in URL)
    audioClient.begin(server_address, server_port, "/ws/audio");
    statusClient.begin(server_address, server_port, "/ws/status");
    batteryClient.begin(server_address, server_port, "/ws/battery");
    Serial.println("\n--- Setup complete. Device is ready. ---");
}
 
void loop() {
    // Poll each WebSocket client to process messages and events
    audioClient.loop();
    statusClient.loop();
    batteryClient.loop();

    // --- Battery Measurement and Sending Logic ---
    unsigned long currentMillis = millis();
    static unsigned long lastBatteryUpdateTime = 0;
    // Send battery status every 60 seconds to conserve power and network traffic.
    const unsigned long batteryUpdateInterval = 60000; 

    // Send battery status periodically if battery client is connected
    if (currentMillis - lastBatteryUpdateTime >= batteryUpdateInterval && batteryClient.isConnected()) {
        // --- SIMULATED BATTERY READING ---
        // For development without a physical battery circuit, this sends a random percentage.
        // To use a real battery, comment this block out and uncomment the "REAL BATTERY READING" block below.
        int percentage = random(5, 100); // Simulate a battery between 5% and 100%
        Serial.printf("Sent SIMULATED battery status: %d%%\n", percentage);

        /*
        // --- REAL BATTERY READING ---
        // Uncomment this block to use a physical battery connected to the ADC pin.
        float voltage = readBatteryVoltage();
        int percentage = voltageToPercentage(voltage);
        Serial.printf("Sent REAL battery status: %d%% (%.2fV)\n", percentage, voltage);
        */

        // Create the JSON message
        StaticJsonDocument<100> doc;
        doc["room"] = THIS_ROOM_ID;
        doc["percentage"] = percentage;
        
        String batteryMessage;
        serializeJson(doc, batteryMessage);
        batteryClient.sendTXT(batteryMessage); // Send the JSON message
        
        lastBatteryUpdateTime = currentMillis; // Update the last send time
    }

    // Add other tasks here, but avoid long blocking operations
    // For example, check for button presses, sensor readings, etc.

    // Add a small delay to the main loop to prevent watchdog timer resets
    delay(10);
}
