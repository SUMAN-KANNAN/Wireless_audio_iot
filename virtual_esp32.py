import asyncio
import websockets
import json
import random
import sys

WEBSOCKET_SERVER_ADDRESS = "localhost"
WEBSOCKET_SERVER_PORT = 5000
THIS_ROOM_ID = None

CURRENT_STATUS = "Active"  # Track current status
AUDIO_ON = False           # Track audio button state

async def send_status(websocket):
    global CURRENT_STATUS
    while True:
        # If audio is on, force status to Active and keep it Active
        if AUDIO_ON:
            if CURRENT_STATUS != "Active":
                CURRENT_STATUS = "Active"
                message = {"room": THIS_ROOM_ID, "status": "Active"}
                try:
                    await websocket.send(json.dumps(message))
                    print(f"Sent status for {THIS_ROOM_ID}: Active (forced by audio ON)")
                except websockets.exceptions.ConnectionClosedError:
                    print(f"Status WebSocket for {THIS_ROOM_ID} is closed. Exiting send_status.")
                    break
                except Exception as e:
                    print(f"Error sending status for {THIS_ROOM_ID}: {e}")
                    break
            # While audio is ON, do not toggle status, just keep it Active
        else:
            # Randomly pick status only when audio is OFF
            status = random.choice(["Active", "Sleep"])
            CURRENT_STATUS = status
            message = {"room": THIS_ROOM_ID, "status": status}
            try:
                await websocket.send(json.dumps(message))
                print(f"Sent status for {THIS_ROOM_ID}: {status}")
            except websockets.exceptions.ConnectionClosedError:
                print(f"Status WebSocket for {THIS_ROOM_ID} is closed. Exiting send_status.")
                break
            except Exception as e:
                print(f"Error sending status for {THIS_ROOM_ID}: {e}")
                break
        await asyncio.sleep(random.uniform(5, 15))

async def send_battery(websocket):
    while True:
        if CURRENT_STATUS == "Active":
            battery_percentage = random.randint(20, 100)
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
        await asyncio.sleep(random.uniform(30, 90))

async def receive_commands(websocket):
    global AUDIO_ON
    while True:
        try:
            message = await websocket.recv()
            print(f"Received command for {THIS_ROOM_ID}: {message}")
            try:
                command = json.loads(message)
                if command.get("type") == "volume_set":
                    volume = command.get("volume")
                    if volume is not None:
                        print(f"Setting volume for {THIS_ROOM_ID} to {volume}")
                # Simulate audio button toggle via command
                if command.get("type") == "audio_on":
                    AUDIO_ON = True
                    print(f"Audio ON for {THIS_ROOM_ID}")
                elif command.get("type") == "audio_off":
                    AUDIO_ON = False
                    print(f"Audio OFF for {THIS_ROOM_ID}")
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
        if CURRENT_STATUS == "Active" and AUDIO_ON:
            simulated_audio_data = {"type": "audio_status", "message": "Simulating audio stream"}
            try:
                await websocket.send(json.dumps(simulated_audio_data))
            except websockets.exceptions.ConnectionClosedError:
                print(f"Audio WebSocket for {THIS_ROOM_ID} is closed. Exiting simulated audio send.")
                break
            except Exception as e:
                print(f"Error sending simulated audio message for {THIS_ROOM_ID}: {e}")
                break
        await asyncio.sleep(5)

async def connect_and_simulate():
    while True:
        try:
            async with websockets.connect(
                f"ws://{WEBSOCKET_SERVER_ADDRESS}:{WEBSOCKET_SERVER_PORT}/ws/audio",
                ping_interval=10, ping_timeout=10
            ) as audio_websocket, \
            websockets.connect(
                f"ws://{WEBSOCKET_SERVER_ADDRESS}:{WEBSOCKET_SERVER_PORT}/ws/status",
                ping_interval=10, ping_timeout=10
            ) as status_websocket, \
            websockets.connect(
                f"ws://{WEBSOCKET_SERVER_ADDRESS}:{WEBSOCKET_SERVER_PORT}/ws/battery",
                ping_interval=10, ping_timeout=10
            ) as battery_websocket:

                print(f"Connected virtual ESP32 for room: {THIS_ROOM_ID}")

                # Send room identification on the audio channel
                await audio_websocket.send(json.dumps({"type": "room_identification", "roomId": THIS_ROOM_ID}))
                print(f"Sent room identification for {THIS_ROOM_ID} on audio channel.")

                tasks = [
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