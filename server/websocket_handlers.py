import json
import os
from flask_sock import Sock
import asyncio

os.makedirs('saved_audio', exist_ok=True)
os.makedirs('saved_volume', exist_ok=True)

# Centralized storage for active WebSocket connections
active_connections_status = []
active_connections_battery = []
active_connections_audio = {}
active_connections_volume = []

def save_room_data(room, key, value):
    """Save the latest value for a key (status, battery, audio, volume) in the room's JSON file."""
    file_path = os.path.join('saved_audio', f"{room}.json")
    if os.path.exists(file_path):
        try:
            with open(file_path, 'r') as f:
                data = json.load(f)
        except Exception:
            data = {}
    else:
        data = {}
    data[key] = value
    with open(file_path, 'w') as f:
        json.dump(data, f, indent=2)

def register_websocket_routes(sock: Sock):
    """Registers WebSocket routes with the Flask-Sock instance."""

    @sock.route('/ws/status')
    def status_websocket(ws):
        """WebSocket endpoint for real-time status updates."""
        print("Status client connected")
        active_connections_status.append(ws)
        try:
            while True:
                message = ws.receive()
                if message:
                    print(f"Received message on status websocket: {message}")
                    try:
                        status_data = json.loads(message)
                        if isinstance(status_data, dict) and 'room' in status_data and 'status' in status_data:
                            print(f"Broadcasting status update: {status_data}")
                            # Save latest status to the room's file
                            save_room_data(status_data['room'], 'status', status_data)
                            broadcast_status(status_data)
                        else:
                            print(f"Received status message with unexpected format: {status_data}")
                    except json.JSONDecodeError:
                        print(f"Received non-JSON message on status websocket: {message}")
                    except Exception as e:
                        print(f"Error processing status message: {e}")
        except Exception as e:
            print(f"Status WebSocket error: {e}")
        finally:
            if ws in active_connections_status:
                active_connections_status.remove(ws)
                print("Status client disconnected")

    @sock.route('/ws/battery')
    def battery_websocket(ws):
        """WebSocket endpoint for real-time battery updates."""
        print("Battery client connected")
        active_connections_battery.append(ws)
        try:
            while True:
                message = ws.receive()
                if message:
                    print(f"Received message on battery websocket: {message}")
                    try:
                        battery_data = json.loads(message)
                        if isinstance(battery_data, dict) and 'room' in battery_data and 'percentage' in battery_data:
                            print(f"Broadcasting battery update: {battery_data}")
                            # Save latest battery to the room's file
                            save_room_data(battery_data['room'], 'battery', battery_data)
                            broadcast_battery(battery_data)
                        else:
                            print(f"Received battery message with unexpected format: {battery_data}")
                    except json.JSONDecodeError:
                        print(f"Received non-JSON message on battery websocket: {message}")
                    except Exception as e:
                        print(f"Error processing battery message: {e}")
        except Exception as e:
            print(f"Battery WebSocket error: {e}")
        finally:
            if ws in active_connections_battery:
                active_connections_battery.remove(ws)
                print("Battery client disconnected")

    @sock.route('/ws/audio')
    def audio(ws):
        """WebSocket endpoint for real-time audio streaming (robust handling)."""
        print("Audio client connected")
        client_id = id(ws)
        active_connections_audio[client_id] = {'websocket': ws, 'room_id': None}
        try:
            while True:
                message = ws.receive()
                if message is None:
                    break
                if isinstance(message, bytes):
                    # Handle or ignore binary audio data
                    print(f"Received binary audio data: {len(message)} bytes")
                    continue
                try:
                    data = json.loads(message)
                    # Handle JSON commands, room identification, etc.
                except Exception as e:
                    print(f"Could not decode message from audio client: {e}")
                    continue
        except Exception as e:
            print(f"Audio WebSocket error for client {client_id}: {e}")
        finally:
            if client_id in active_connections_audio:
                del active_connections_audio[client_id]
                print(f"Audio client {client_id} disconnected")

    @sock.route('/ws/volume')
    def volume_websocket(ws):
        """WebSocket endpoint for real-time volume control."""
        print("Volume client connected")
        active_connections_volume.append(ws)
        try:
            while True:
                message = ws.receive()
                if message:
                    print(f"Received message on volume websocket: {message}")
                    try:
                        volume_data = json.loads(message)
                        if isinstance(volume_data, dict) and volume_data.get('type') == 'volume' and isinstance(volume_data.get('data'), dict):
                            volumes_by_room = volume_data['data']
                            print(f"Received volume control data: {volumes_by_room}")
                            # Save latest volume for each room
                            for room_id, volume_level in volumes_by_room.items():
                                save_room_data(room_id, 'volume', {"volume": volume_level})
                            forward_volume_commands(volumes_by_room)
                        else:
                            print(f"Received volume message with unexpected format: {volume_data}")
                    except json.JSONDecodeError:
                        print(f"Received non-JSON message on volume websocket: {message}")
                    except Exception as e:
                        print(f"Error processing volume message: {e}")
        except Exception as e:
            print(f"Volume WebSocket error: {e}")
        finally:
            if ws in active_connections_volume:
                active_connections_volume.remove(ws)
                print("Volume client disconnected")

    # --- Broadcasting Functions ---

    def broadcast_status(status_message):
        """Broadcast status updates to all connected status WebSocket clients."""
        for connection in list(active_connections_status):
            try:
                connection.send(json.dumps(status_message))
            except Exception as e:
                print(f"Error broadcasting status to {connection}: {e}")
                if connection in active_connections_status:
                    active_connections_status.remove(connection)

    def broadcast_battery(battery_message):
        """Broadcast battery updates to all connected battery WebSocket clients."""
        for connection in list(active_connections_battery):
            try:
                connection.send(json.dumps(battery_message))
            except Exception as e:
                print(f"Error broadcasting battery to {connection}: {e}")
                if connection in active_connections_battery:
                    active_connections_battery.remove(connection)

    def broadcast_audio(audio_data, sender_room_id, sender_client_id):
        """Broadcast audio data to other connected audio clients in the same room."""
        for client_id, client_info in list(active_connections_audio.items()):
            if client_id != sender_client_id and client_info.get('room_id') == sender_room_id:
                try:
                    client_info['websocket'].send(audio_data)
                except Exception as e:
                    print(f"Error broadcasting audio to client {client_id}: {e}")
                    if client_id in active_connections_audio:
                        del active_connections_audio[client_id]

    # --- Forwarding Function ---

    def forward_volume_commands(volumes_by_room):
        """Forwards volume control commands to relevant audio clients (ESP32s)."""
        for room_id, volume_level in volumes_by_room.items():
            for client_id, client_info in list(active_connections_audio.items()):
                if client_info.get('room_id') == room_id:
                    try:
                        volume_command = {"type": "volume_set", "volume": volume_level}
                        client_info['websocket'].send(json.dumps(volume_command))
                        print(f"Sent volume {volume_level} to client {client_id} in room {room_id}")
                    except Exception as e:
                        print(f"Error sending volume to audio client {client_id}: {e}")
                        if client_id in active_connections_audio:
                            del active_connections_audio[client_id]