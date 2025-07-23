import json
import os
from flask_sock import Sock
import asyncio
from itsdangerous import URLSafeTimedSerializer, SignatureExpired, BadTimeSignature
from urllib.parse import parse_qs
os.makedirs('room_states', exist_ok=True)

# Centralized storage for active WebSocket connections
active_connections_status = []
active_connections_battery = []
active_connections_audio = {}
active_connections_volume = []

def save_room_data(room, key, value):
    """Save the latest value for a key (status, battery, audio, volume) in the room's JSON file."""
    file_path = os.path.join('room_states', f"{room}.json")
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

def get_room_data(room):
    """Load the latest data for a room from its JSON file."""
    file_path = os.path.join('room_states', f"{room}.json")
    if os.path.exists(file_path):
        try:
            with open(file_path, 'r') as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError):
            return {}
    return {}

def register_websocket_routes(sock: Sock, secret_key: str, device_api_key: str, rooms_config: list):
    """Registers WebSocket routes with the Flask-Sock instance."""
    serializer = URLSafeTimedSerializer(secret_key)

    def _is_authenticated(ws):
        """Verify the token from the WebSocket connection query string."""
        query_string = ws.environ.get('QUERY_STRING', '')
        params = parse_qs(query_string)
        token = params.get('token', [None])[0]

        if not token:
            print("Auth Error: No token provided. Closing connection.")
            return False

        # First, check if it's the static device API key
        if token == device_api_key:
            print("Device authenticated successfully.")
            return True

        # Next, check if it's a user session token
        try:
            # max_age = 30 minutes (1800 seconds)
            username = serializer.loads(token, max_age=1800)
            print(f"User '{username}' authenticated successfully.")
            return True
        except SignatureExpired:
            print("Auth Error: User token has expired. Closing connection.")
            return False
        except (BadTimeSignature, Exception):
            print("Auth Error: User token is invalid. Closing connection.")
            return False

    @sock.route('/ws/status')
    def status_websocket(ws):
        """WebSocket endpoint for real-time status updates."""
        if not _is_authenticated(ws):
            return  # Close connection immediately

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
                            # Handle "Turn All On" (global status)
                            if status_data['room'] == "all":
                                broadcast_status_to_all(status_data['status'])
                            else:
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
        if not _is_authenticated(ws):
            return

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
        if not _is_authenticated(ws):
            return

        print("Audio client connected")
        client_id = id(ws)
        active_connections_audio[client_id] = {'websocket': ws, 'room_id': None, 'client_type': None}
        try:
            while True:
                message = ws.receive()
                if message is None:
                    break
                if isinstance(message, bytes):
                    # This is audio data from the browser. Forward it.
                    sender_info = active_connections_audio.get(client_id)
                    if sender_info and sender_info.get('room_id'):
                        broadcast_audio(message, sender_info['room_id'], client_id)
                else:
                    # This is a JSON command, likely for identification.
                    try:
                        data = json.loads(message)
                        if data.get("type") == "room_identification" and "roomId" in data:
                            room_id = data["roomId"]
                            client_type = data.get("client_type", "unknown") # Get client_type
                            if client_id in active_connections_audio:
                                active_connections_audio[client_id]['room_id'] = room_id
                                active_connections_audio[client_id]['client_type'] = client_type
                                print(f"Client {client_id} identified for room {room_id} as {client_type}")
                        # You can add other JSON command handling here if needed
                    except Exception as e:
                        print(f"Could not decode JSON message from audio client: {e}")
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
        if not _is_authenticated(ws):
            return

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
        """Forwards audio data from a browser client to the device client in the same room."""
        # This function now assumes the sender is a browser and looks for a device.
        for client_id, client_info in list(active_connections_audio.items()):
            if client_info.get('room_id') == sender_room_id and client_info.get('client_type') == 'device':
                try:
                    # Forward audio to the ESP32 device in the room
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

    def broadcast_status_to_all(status):
        """Broadcasts the given status to all rooms and saves it."""
        # Use the centralized rooms_config to get the list of all room IDs
        for room_info in rooms_config:
            status_message = {"room": room_info['id'], "status": status}
            broadcast_status(status_message)
            save_room_data(room_info['id'], 'status', status_message)