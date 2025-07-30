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

AUDIO_ON = False  # Default to OFF. The device should wait for a command from the dashboard to activate.
CURRENT_BATTERY = 100 # Global state for battery level

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
    """Simulates a gradual battery drain and recharge cycle for predictable testing."""
    global CURRENT_BATTERY
    while True:
        try:
            # If battery is critically low, "recharge" it back to 100% for the simulation.
            if CURRENT_BATTERY <= 5:
                print(f"--- Battery for {THIS_ROOM_ID} hit critical level. Recharging. ---")
                CURRENT_BATTERY = 100

            message = {"room": THIS_ROOM_ID, "percentage": CURRENT_BATTERY}
            await websocket.send(json.dumps(message))
            print(f"Sent battery for {THIS_ROOM_ID}: {CURRENT_BATTERY}%")

            # Decrease battery for the next cycle.
            CURRENT_BATTERY -= 2

        except websockets.exceptions.ConnectionClosedError:
            print(f"Battery WebSocket for {THIS_ROOM_ID} is closed. Exiting send_battery.")
            break
        except Exception as e:
            print(f"Error sending battery for {THIS_ROOM_ID}: {e}")
            break
        # Wait 5 seconds before the next update.
        await asyncio.sleep(5)

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

async def receive_status_commands(websocket):
    """Listens for status commands from the server (e.g., 'Turn All On')."""
    global AUDIO_ON
    while True:
        try:
            message = await websocket.recv()
            print(f"Received status command for {THIS_ROOM_ID}: {message}")
            try:
                command = json.loads(message)
                # Check if the command is for this specific room
                if command.get("room") == THIS_ROOM_ID and "status" in command:
                    new_status = command.get("status")
                    if new_status in ["Active", "On"] and not AUDIO_ON:
                        AUDIO_ON = True
                        print(f"--- Mic for {THIS_ROOM_ID} turned ON by server command ---")
                    elif new_status in ["Sleep", "Off"] and AUDIO_ON:
                        AUDIO_ON = False
                        print(f"--- Mic for {THIS_ROOM_ID} turned OFF by server command ---")
            except json.JSONDecodeError:
                print(f"Received non-JSON message on status channel: {message}")
        except websockets.exceptions.ConnectionClosedError:
            break # Connection closed, exit the loop
        except Exception as e:
            print(f"Error receiving status command for {THIS_ROOM_ID}: {e}")
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
        # Send chunks frequently to simulate real-time streaming, matching the browser's behavior.
        await asyncio.sleep(0.1) # Send every 100ms

async def run_websocket_tasks(audio_ws, status_ws, battery_ws):
    """Runs all the concurrent tasks for the virtual device and handles cleanup."""
    # --- BUG FIX: Send identification on ALL channels ---
    # The server needs to know which room each connection belongs to in order to
    # correctly route commands (like 'Active'/'Sleep') back to the device.
    id_message = json.dumps({"type": "room_identification", "roomId": THIS_ROOM_ID})

    await audio_ws.send(id_message)
    print(f"Sent room identification for {THIS_ROOM_ID} on audio channel.")
    await status_ws.send(id_message)
    print(f"Sent room identification for {THIS_ROOM_ID} on status channel.")
    await battery_ws.send(id_message)
    print(f"Sent room identification for {THIS_ROOM_ID} on battery channel.")

    tasks = [
        asyncio.create_task(send_simulated_audio_message(audio_ws)),
        asyncio.create_task(send_status(status_ws)),
        asyncio.create_task(send_battery(battery_ws)),
        asyncio.create_task(receive_commands(audio_ws)),
        asyncio.create_task(receive_status_commands(status_ws))
    ]

    try:
        # Wait for all tasks to complete. If one fails (e.g., due to a closed connection),
        # asyncio.gather will raise that exception, and we'll move to the finally block.
        await asyncio.gather(*tasks)
    finally:
        # When one task fails, we need to clean up the others.
        print(f"A task failed or connection closed for {THIS_ROOM_ID}. Cleaning up other tasks.")
        for task in tasks:
            task.cancel()
        # Wait for all tasks to acknowledge cancellation.
        await asyncio.gather(*tasks, return_exceptions=True)

async def connect_and_simulate():
    # The API key should be sent as a header, not a token in the URL.
    # This matches the behavior of the real ESP32 firmware.
    auth_headers = {'X-API-Key': DEVICE_API_KEY}
    base_uri = f"ws://{WEBSOCKET_SERVER_ADDRESS}:{WEBSOCKET_SERVER_PORT}"

    while True:
        try:
            # Use 'async with' to robustly manage the lifecycle of all three connections.
            # If any connection fails to establish, it will raise an exception and be caught below.
            async with websockets.connect(
                f"{base_uri}/ws/audio", extra_headers=auth_headers
            ) as audio_ws, \
            websockets.connect(
                f"{base_uri}/ws/status", extra_headers=auth_headers
            ) as status_ws, \
            websockets.connect(
                f"{base_uri}/ws/battery", extra_headers=auth_headers
            ) as battery_ws:
                print(f"All WebSockets connected for room: {THIS_ROOM_ID}")
                # This function will run until one of the connections fails, which raises an exception.
                await run_websocket_tasks(audio_ws, status_ws, battery_ws)
        
        # --- FIX: Corrected exception handling for modern 'websockets' library ---
        except (ConnectionRefusedError, websockets.ConnectionClosedError) as e:
            print(f"Connection refused or closed for {THIS_ROOM_ID}. Reconnecting in 5 seconds...")
            await asyncio.sleep(5)
        except websockets.WebSocketException as e:
            print(f"WebSocket error for {THIS_ROOM_ID}: {e}. Retrying in 5 seconds...")
            await asyncio.sleep(5)
        except Exception as e:
            print(f"An unexpected error occurred for {THIS_ROOM_ID}: {e}. Retrying in 5 seconds...")
            await asyncio.sleep(5)

if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python virtual_esp32.py <room_id>")
        sys.exit(1)

    THIS_ROOM_ID = sys.argv[1]
    asyncio.run(connect_and_simulate())