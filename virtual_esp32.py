import asyncio
import websockets
import os
import json
import random
import sys

WEBSOCKET_SERVER_ADDRESS = "localhost"
WEBSOCKET_SERVER_PORT = 5000
THIS_ROOM_ID = None

# Load the device API key from an environment variable to match the server.
# This key must match the DEVICE_API_KEY in app.py
DEVICE_API_KEY = os.environ.get('DEVICE_API_KEY', 'a-very-secret-key-for-devices-only')

AUDIO_ON = False  # Global state to track if the mic is on or off
CURRENT_BATTERY = 100 # Global state for battery level

async def keyboard_listener():
    """Listens for keyboard input in a separate thread to toggle the audio state."""
    global AUDIO_ON
    loop = asyncio.get_running_loop()
    print(f"--- Controls for {THIS_ROOM_ID}: Press 'm' then 'Enter' to toggle microphone ON/OFF ---")
    while True:
        # Run the blocking input() in a separate thread to avoid freezing the event loop
        key = await loop.run_in_executor(None, sys.stdin.readline)
        if 'm' in key:
            AUDIO_ON = not AUDIO_ON
            print(f"\n--- Toggled Mic for {THIS_ROOM_ID}. Audio is now {'ON' if AUDIO_ON else 'OFF'} ---\n")

async def send_status(websocket):
    """Sends the device status (Active/Sleep) to the server when it changes."""
    global CURRENT_BATTERY # Need to access the global battery state
    last_sent_status = ""
    while True:
        # A device can only be "Active" if the mic is toggled ON AND it has battery > 0
        status = "Active" if AUDIO_ON and CURRENT_BATTERY > 0 else "Sleep"
        if status != last_sent_status:
            message = {"room": THIS_ROOM_ID, "status": status}
            try:
                await websocket.send(json.dumps(message))
                print(f"Sent status for {THIS_ROOM_ID}: {status}")
                last_sent_status = status
            except websockets.exceptions.ConnectionClosedError:
                print(f"Status WebSocket for {THIS_ROOM_ID} is closed. Exiting send_status.")
                break
            except Exception as e:
                print(f"Error sending status for {THIS_ROOM_ID}: {e}")
                break
        await asyncio.sleep(1) # Check for status changes every second

async def send_battery(websocket):
    while True:
        global CURRENT_BATTERY # Need to modify the global battery state
        # Simulate a more realistic battery range for better UI testing
        battery_percentage = random.randint(0, 100)
        CURRENT_BATTERY = battery_percentage # Update the global state
        message = {"room": THIS_ROOM_ID, "percentage": battery_percentage}
        try:
            await websocket.send(json.dumps(message))
            print(f"Sent battery for {THIS_ROOM_ID}: {battery_percentage}%")
        except websockets.exceptions.ConnectionClosedError:
            print(f"Battery WebSocket for {THIS_ROOM_ID} is closed. Exiting send_battery.")
            break
        except Exception as e:
            print(f"Error sending battery for {THIS_ROOM_ID}: {e}")
            break
        await asyncio.sleep(random.uniform(20, 40)) # Send battery status periodically

async def receive_commands(websocket):
    """Listens for and prints commands from the server (like volume changes)."""
    while True:
        try:
            message = await websocket.recv()
            print(f"Received command for {THIS_ROOM_ID}: {message}")
            try:
                command = json.loads(message)
                if command.get("type") == "volume_set":
                    volume = command.get("volume")
                    if volume is not None:
                        print(f"-> Simulated setting volume for {THIS_ROOM_ID} to {volume}")
                else:
                    print(f"-> Received other command: {command}")
            except json.JSONDecodeError:
                print(f"Received non-JSON message on command channel: {message}")

        except websockets.exceptions.ConnectionClosedError:
            print(f"Command WebSocket for {THIS_ROOM_ID} is closed. Exiting receive_commands.")
            break
        except Exception as e:
            print(f"Error receiving command for {THIS_ROOM_ID}: {e}")
            break

async def send_simulated_audio_message(websocket):
    while True:
        if AUDIO_ON:
            # In a real scenario, this would send binary audio data.
            simulated_audio_data = b'\x01\x02\x03\x04\x05'
            try:
                await websocket.send(simulated_audio_data)
            except websockets.exceptions.ConnectionClosedError:
                print(f"Audio WebSocket for {THIS_ROOM_ID} is closed. Exiting simulated audio send.")
                break
            except Exception as e:
                print(f"Error sending simulated audio message for {THIS_ROOM_ID}: {e}")
                break
        await asyncio.sleep(5)

async def connect_and_simulate():
    auth_url_part = f"?token={DEVICE_API_KEY}"
    while True:
        try:
            async with websockets.connect(
                f"ws://{WEBSOCKET_SERVER_ADDRESS}:{WEBSOCKET_SERVER_PORT}/ws/audio{auth_url_part}",
                ping_interval=10, ping_timeout=10
            ) as audio_websocket, \
            websockets.connect(
                f"ws://{WEBSOCKET_SERVER_ADDRESS}:{WEBSOCKET_SERVER_PORT}/ws/status{auth_url_part}",
                ping_interval=10, ping_timeout=10
            ) as status_websocket, \
            websockets.connect(
                f"ws://{WEBSOCKET_SERVER_ADDRESS}:{WEBSOCKET_SERVER_PORT}/ws/battery{auth_url_part}",
                ping_interval=10, ping_timeout=10
            ) as battery_websocket:

                print(f"Connected virtual ESP32 for room: {THIS_ROOM_ID}")

                # Send room identification on the audio channel
                await audio_websocket.send(json.dumps({"type": "room_identification", "roomId": THIS_ROOM_ID}))
                print(f"Sent room identification for {THIS_ROOM_ID} on audio channel.")

                tasks = [
                    asyncio.create_task(keyboard_listener()),
                    asyncio.create_task(send_simulated_audio_message(audio_websocket)),
                    asyncio.create_task(send_status(status_websocket)),
                    asyncio.create_task(send_battery(battery_websocket)),
                    asyncio.create_task(receive_commands(audio_websocket))
                ]
                done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
                for task in pending:
                    task.cancel()
                print(f"One of the connections closed for {THIS_ROOM_ID}. Reconnecting in 5 seconds...")
                await asyncio.sleep(5)

        except (ConnectionRefusedError, websockets.exceptions.ConnectionClosedError):
            print(f"Connection refused or closed for {THIS_ROOM_ID}. Retrying in 5 seconds...")
            await asyncio.sleep(5)
        except websockets.exceptions.WebSocketException as e:
            print(f"WebSocket error for {THIS_ROOM_ID}: {e}. Retrying in 5 seconds...")
            await asyncio.sleep(5)
        except Exception as e:
            print(f"Unexpected error for {THIS_ROOM_ID}: {e}. Retrying in 5 seconds...")
            await asyncio.sleep(5)

if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python virtual_esp32.py <room_id>")
        sys.exit(1)

    THIS_ROOM_ID = sys.argv[1]
    asyncio.run(connect_and_simulate())