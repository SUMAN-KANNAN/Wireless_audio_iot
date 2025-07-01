import asyncio
import websockets
import json

# Global variable to store active WebSocket connections
active_connections = []

async def listen_to_websocket():
    uri = "ws://127.0.0.1:5000/ws/status"  # Replace with your WebSocket server URL
    async with websockets.connect(uri) as websocket:
        print("WebSocket connection established.")
        print("Waiting for data from the API...")  # Indicate waiting for data
        while True:
            try:
                message = await websocket.recv()  # Receive message from the server
                data = json.loads(message)  # Parse the JSON message
                
                # Check the type of data received
                if data.get("type") == "volume":
                    for room_id, volume in data.get("data", {}).items():
                        print(f"Volume for {room_id} set to {volume}%")
                        # Here you can add logic to save the volume data
                        # save_volume_json()  # Uncomment if you have a function to save volume data
                else:
                    checkbox_status = data.get('status', '')  # Get the status from the message

                    # Update the checkbox status based on the received data
                    if checkbox_status == "New data from IoT":
                        print("Checkbox should be checked.")
                        # Here you can add logic to update your application state
                    else:
                        print("Checkbox should be unchecked.")
                        # Here you can add logic to update your application state

            except Exception as e:
                print(f"Error: {e}")
                break

async def broadcast_status(status):
    """Broadcast status updates to all connected WebSocket clients."""
    for connection in active_connections:
        await connection.send(json.dumps({"status": status}))

async def receive_iot_data():
    """Simulate receiving data from an IoT server."""
    while True:
        await asyncio.sleep(5)  # Simulate delay
        status_update = "New data from IoT"  # Replace with actual data
        await broadcast_status(status_update)

if __name__ == "__main__":
    # Start the WebSocket listener and IoT data simulation
    loop = asyncio.get_event_loop()
    loop.create_task(receive_iot_data())
    loop.run_until_complete(listen_to_websocket())
