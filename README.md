# Wireless Audio Control System

This project is a complete, real-time system for wirelessly streaming audio from a web dashboard to multiple ESP32-based speaker devices. It features live status monitoring, individual and master volume controls, and a persistent, stateful server backend.

## Key Features

- **Web-Based Dashboard:** Control everything from a clean, modern web interface.
- **Multi-Room Support:** Manage several independent speaker devices (Conference Room, Admin Room, etc.).
- **Real-Time Audio Streaming:** Toggle microphones on the dashboard to stream audio to selected ESP32 devices with low latency.
- **Live Status Monitoring:** A three-color system (Red, Orange, Green) shows the real-time connection and activity status of each device.
- **Individual & Master Volume Control:** Adjust volume for each room separately or all at once.
- **Persistent State:** The server, powered by Redis, remembers the last known state of each room (status, battery, volume) across browser reloads and server restarts.
- **Secure Authentication:** Simple login system for the dashboard and token-based authentication for devices.
- **Intelligent Device Management:** The server automatically handles device disconnections and ensures only one authoritative device can be active per room.

## System Architecture

The system consists of three main parts:

1.  **Python Flask Server:** The central hub that manages WebSocket connections, handles authentication, serves the web dashboard, and routes data.
2.  **Web Dashboard (Client):** The front-end interface built with HTML, CSS, and JavaScript. It captures raw microphone audio and sends it to the server for processing.
3.  **ESP32 Devices (Hardware):** Microcontrollers running custom firmware. They connect to the server via WiFi to receive status commands, audio data, and report their battery levels.

```
[Browser] <--> [Flask Server] <--> [ESP32 Device]
  (UI)          (WebSockets)        (WiFi)
```

---

## Section 1: Local Development Setup

Follow these steps to run the entire system on your local computer for development and testing.

### Prerequisites

- **Python 3.8+** and `pip`.
- **Arduino IDE** (Version 1.8.19 or newer recommended).
- **Git** for version control.

### Server & Virtual Device Setup

This allows you to run the dashboard and test it with simulated ESP32 devices without needing any physical hardware.

1.  **Clone the Repository:**
    ```bash
    git clone https://github.com/SUMAN-KANNAN/Wireless_audio_iot.git
    cd Wireless_audio_iot
    ```

2.  **Set Up Python Environment:**
    Open a terminal in the project directory and run:
    ```bash
    # Create a virtual environment
    python -m venv venv

    # Activate it
    # On Windows:
    .\venv\Scripts\activate
    # On macOS/Linux:
    source venv/bin/activate

    # Install required packages
    pip install -r requirements.txt
    ```

3.  **Install and Run Redis (for State Management):**
    The server uses Redis to store the state of the rooms. This is a separate program that must be running in the background before you start the Flask server.

    #### On Windows:
    1.  **Download the Redis installer** from the official repository for Windows releases: https://github.com/tporadowski/redis/releases. Download the latest `.msi` file.
    2.  **Run the installer.** Follow the prompts.
        - **Port Number:** When asked for a port number, leave it as the default `6379`. The Python application is configured to connect to this port.
        - **Max Memory:** When asked to set a max memory limit, you can leave it at the default value (e.g., 100MB). This is a safety feature, and our application uses very little memory.
        - **PATH:** **Important:** Ensure the box to "Add the Redis installation folder to the PATH environment variable" is checked.
    3.  **Start the Redis server.** After installation, open a new Command Prompt or PowerShell window and simply run:
        ```bash
        redis-server
        ```
    *Leave this terminal window open. It is your running Redis database.*

    #### On macOS/Linux (or Windows via WSL):
    - **On macOS (using Homebrew):**
        ```bash
        brew install redis
        brew services start redis
        ```
    - **On Linux (Ubuntu/Debian):**
        ```bash
        sudo apt update && sudo apt install redis-server -y
        sudo service redis-server start
        ```

4.  **Start the Flask Server:**
    Open a **new terminal** (your Redis server should still be running in the other one). Make sure your Python virtual environment is active (`.\venv\Scripts\activate`). Then run the server:
    ```bash
    python app.py
    ```
    *The server is now running. You can access the dashboard, but no devices are connected yet.*

5.  **Run Virtual ESP32 Devices (Optional, but Recommended for Testing):**
    Ensure the Flask server from the previous step is still running. To test the dashboard, open **three new, separate terminals**. In each one, activate the virtual environment (`.\venv\Scripts\activate`) and run one of the following commands:
    ```bash
    # Terminal 1
    python virtual_esp32.py conferenceRoom

    # Terminal 2
    python virtual_esp32.py adminRoom

    # Terminal 3
    python virtual_esp32.py classRoom
    ```
    *You will now see the rooms appear as "Online" on the dashboard.*

6.  **Access the Dashboard:**
    - Open your web browser and go to `http://127.0.0.1:5000`.
    - Log in with default credentials: `admin` / `password` or `user` / `123`.

---

## Section 2: Hardware (ESP32) Setup

Follow these steps for each physical ESP32 device you want to connect to the system.

### Arduino IDE Configuration (One-Time Setup)

1.  **Add ESP32 Board Support:**
    - Open the Arduino IDE and go to `File > Preferences`.
    - In "Additional Boards Manager URLs", paste:
      `https://raw.githubusercontent.com/espressif/arduino-esp32/gh-pages/package_esp32_index.json`
    - Go to `Tools > Board > Boards Manager...`, search for "esp32", and install it.

2.  **Install Required Libraries:**
    - Go to `Tools > Manage Libraries...`
    - Search for and install `ArduinoJson` by Benoit Blanchon.
    - Search for and install `WebSockets` by Markus Sattler.

### Firmware Configuration & Upload

1.  **Open the Project in Arduino IDE:**
    - **Important:** Do not copy the `.ino` file. You must open the project from its original folder to ensure it can find all necessary files.
    - In the Arduino IDE, go to `File > Open...`
    - Navigate to the `esp32_firmware/firmware` folder inside your cloned project and open `firmware.ino`.

2.  **Configure `secrets.h`:**
    - A second tab named `secrets.h` should open automatically.
    - Fill in your WiFi network name (`ssid`) and `password`.
    - The `device_api_key` should match the one on the server (the default is fine for local testing).

3.  **Configure `firmware.ino`:**
    - **Set the Room ID:** In `firmware.ino`, change the `THIS_ROOM_ID` variable to match the `id` of a room defined in the server's `config.json` file (e.g., `"conferenceRoom"`, `"adminRoom"`). Each physical device needs a unique ID.
    - **Server IP Address:** No changes are needed for local development. The firmware uses mDNS to automatically discover the server. For production deployment, you will need to modify the firmware to use your server's public IP address.

4.  **Upload the Firmware:**
    - Go to `Tools > Board > ESP32 Arduino` and select `ESP32 Dev Module`.
    - Connect your ESP32, select the correct `Port` under `Tools`.
    - Click the "Upload" button (the arrow icon).

5.  **Verify Operation:**
    - After uploading, open the `Tools > Serial Monitor` (set baud rate to `115200`).
    - You should see messages that it's connecting to WiFi and then discovering and connecting to your server.
    - The device will now appear on your dashboard.

---

## Section 3: System Operations

### Adding a New Room

1.  **Server:** Open the `config.json` file. Add a new JSON object for your new room, following the existing format.
2.  **Firmware:** Take a new ESP32 device, set its `THIS_ROOM_ID` in `firmware.ino` to the `id` you just created, and upload the firmware.
3.  **Restart:** Restart the Python server. The new room will automatically appear on the dashboard.

### Troubleshooting Uploads

If you see an error like `Failed to connect to ESP32: Wrong boot mode detected`, it means the board didn't enter "Download Mode".

- **To fix this:** Click "Upload" again. As soon as you see "Connecting........" in the console, **press and hold** the "BOOT" or "IO0" button on your ESP32. Release it once the upload starts.