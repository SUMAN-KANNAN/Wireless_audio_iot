import json
import os
from flask_sock import Sock
from itsdangerous import URLSafeTimedSerializer, SignatureExpired, BadTimeSignature
from urllib.parse import parse_qs
import logging
import redis

# --- ARCHITECTURAL UPGRADE: Use Redis for State Management ---
# Redis provides an atomic, in-memory data store that is faster and more reliable
# than file-based storage, preventing race conditions and performance bottlenecks.
# It's configured to return strings, which we'll then parse from JSON.
redis_client = redis.Redis(decode_responses=True)
logging.info("Redis client connected.")

# Centralized storage for active WebSocket connections
active_connections_status = []
active_connections_battery = []
active_connections_audio = {}
active_connections_volume = []

def save_room_data(room, key, value):
    """Save the latest value for a key (status, battery, volume) in Redis."""
    try:
        # We use a Redis Hash, which is like a dictionary stored under a single key.
        # This is perfect for grouping all data related to a single room.
        redis_key = f"room:{room}"
        # The value is converted to a JSON string before storing.
        redis_client.hset(redis_key, key, json.dumps(value))
    except redis.exceptions.ConnectionError as e:
        logging.critical(f"Could not connect to Redis to save data. Is Redis running? Error: {e}")

def get_room_data(room):
    """Load the latest data for a room from Redis."""
    try:
        redis_key = f"room:{room}"
        # hgetall retrieves all fields and values from the hash.
        room_data_raw = redis_client.hgetall(redis_key)
        if not room_data_raw:
            return {}
        # We parse the JSON string for each value back into a Python object.
        return {key: json.loads(value) for key, value in room_data_raw.items()}
    except redis.exceptions.ConnectionError as e:
        logging.critical(f"Could not connect to Redis to get data. Is Redis running? Error: {e}")
        return {} # Return empty dict to prevent frontend errors

def register_websocket_routes(sock: Sock, secret_key: str, device_api_key: str, rooms_config: list):
    """Registers WebSocket routes with the Flask-Sock instance."""
    serializer = URLSafeTimedSerializer(secret_key)

    def _is_authenticated(ws):
        """
        Verify authentication for the WebSocket connection.
        - For devices: Checks for a valid 'X-API-Key' header.
        - For browsers: Checks for a valid 'token' in the query string.
        """
        # --- SECURITY UPGRADE: Prioritize Header-based auth for devices ---
        device_key_from_header = ws.environ.get('HTTP_X_API_KEY')
        if device_key_from_header:
            if device_key_from_header == device_api_key:
                logging.info("Device authenticated successfully via header.")
                return True
            else:
                logging.warning("Auth Error: Invalid device API key in header. Closing connection.")
                return False

        # Fallback to token-based auth for browser clients
        query_string = ws.environ.get('QUERY_STRING', '')
        params = parse_qs(query_string)
        token = params.get('token', [None])[0]

        if not token:
            logging.warning("Auth Error: No token or API key header provided. Closing connection.")
            return False

        # This part is now only for user session tokens from the browser
        try:
            # max_age = 30 minutes (1800 seconds)
            username = serializer.loads(token, max_age=1800)
            logging.info(f"User '{username}' authenticated successfully via token.")
            return True
        except SignatureExpired:
            logging.warning("Auth Error: User token has expired. Closing connection.")
            return False
        except (BadTimeSignature, Exception):
            logging.warning("Auth Error: User token is invalid. Closing connection.")
            return False

    @sock.route('/ws/status')
    def status_websocket(ws):
        """WebSocket endpoint for real-time status updates."""
        if not _is_authenticated(ws):
            return  # Close connection immediately

        logging.info("Status client connected")
        active_connections_status.append(ws)
        try:
            while True:
                message = ws.receive()
                if message:
                    logging.debug(f"Received message on status websocket: {message}")
                    try:
                        status_data = json.loads(message)
                        if isinstance(status_data, dict) and 'room' in status_data and 'status' in status_data:
                            logging.info(f"Broadcasting status update: {status_data}")
                            # Handle "Turn All On" (global status)
                            if status_data['room'] == "all":
                                broadcast_status_to_all(status_data['status'])
                            else:
                                # Save latest status to the room's file
                                save_room_data(status_data['room'], 'status', status_data)
                                broadcast_status(status_data)
                        else:
                            logging.warning(f"Received status message with unexpected format: {status_data}")
                    except json.JSONDecodeError:
                        logging.warning(f"Received non-JSON message on status websocket: {message}")
                    except Exception as e:
                        logging.error(f"Error processing status message: {e}")
        except Exception as e:
            logging.error(f"Status WebSocket error: {e}")
        finally:
            if ws in active_connections_status:
                active_connections_status.remove(ws)
                logging.info("Status client disconnected")

    @sock.route('/ws/battery')
    def battery_websocket(ws):
        """WebSocket endpoint for real-time battery updates."""
        if not _is_authenticated(ws):
            return

        logging.info("Battery client connected")
        active_connections_battery.append(ws)
        try:
            while True:
                message = ws.receive()
                if message:
                    logging.debug(f"Received message on battery websocket: {message}")
                    try:
                        battery_data = json.loads(message)
                        if isinstance(battery_data, dict) and 'room' in battery_data and 'percentage' in battery_data:
                            logging.info(f"Broadcasting battery update: {battery_data}")
                            # Save latest battery to the room's file
                            save_room_data(battery_data['room'], 'battery', battery_data)
                            broadcast_battery(battery_data)
                        else:
                            logging.warning(f"Received battery message with unexpected format: {battery_data}")
                    except json.JSONDecodeError:
                        logging.warning(f"Received non-JSON message on battery websocket: {message}")
                    except Exception as e:
                        logging.error(f"Error processing battery message: {e}")
        except Exception as e:
            logging.error(f"Battery WebSocket error: {e}")
        finally:
            if ws in active_connections_battery:
                active_connections_battery.remove(ws)
                logging.info("Battery client disconnected")

    @sock.route('/ws/audio')
    def audio(ws):
        """WebSocket endpoint for real-time audio streaming (robust handling)."""
        if not _is_authenticated(ws):
            return

        logging.info("Audio client connected")
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
                                logging.info(f"Client {client_id} identified for room {room_id} as {client_type}")
                        # You can add other JSON command handling here if needed
                    except Exception as e:
                        logging.warning(f"Could not decode JSON message from audio client: {e}")
                        continue
        except Exception as e:
            logging.error(f"Audio WebSocket error for client {client_id}: {e}")
        finally:
            if client_id in active_connections_audio:
                del active_connections_audio[client_id]
                logging.info(f"Audio client {client_id} disconnected")

    @sock.route('/ws/volume')
    def volume_websocket(ws):
        """WebSocket endpoint for real-time volume control."""
        if not _is_authenticated(ws):
            return

        logging.info("Volume client connected")
        active_connections_volume.append(ws)
        try:
            while True:
                message = ws.receive()
                if message:
                    logging.debug(f"Received message on volume websocket: {message}")
                    try:
                        volume_data = json.loads(message)
                        if isinstance(volume_data, dict) and volume_data.get('type') == 'volume' and isinstance(volume_data.get('data'), dict):
                            volumes_by_room = volume_data['data']
                            logging.info(f"Received volume control data: {volumes_by_room}")
                            # Save latest volume for each room
                            for room_id, volume_level in volumes_by_room.items():
                                save_room_data(room_id, 'volume', {"volume": volume_level})
                            forward_volume_commands(volumes_by_room)
                        else:
                            logging.warning(f"Received volume message with unexpected format: {volume_data}")
                    except json.JSONDecodeError:
                        logging.warning(f"Received non-JSON message on volume websocket: {message}")
                    except Exception as e:
                        logging.error(f"Error processing volume message: {e}")
        except Exception as e:
            logging.error(f"Volume WebSocket error: {e}")
        finally:
            if ws in active_connections_volume:
                active_connections_volume.remove(ws)
                logging.info("Volume client disconnected")

    # --- Broadcasting Functions ---

    def _broadcast_message(clients, message):
        """Generic function to broadcast a JSON message to a list of clients."""
        # Iterate over a copy of the list to allow for safe removal during iteration
        for client in list(clients):
            try:
                client.send(json.dumps(message))
            except Exception as e:
                logging.error(f"Error broadcasting message to {client}: {e}. Removing client.")
                # Safely remove the disconnected client from the original list
                if client in clients:
                    clients.remove(client)

    def broadcast_status(status_message): _broadcast_message(active_connections_status, status_message)
    def broadcast_battery(battery_message): _broadcast_message(active_connections_battery, battery_message)

    def broadcast_audio(audio_data, sender_room_id, sender_client_id):
        """Forwards audio data from a browser client to the device client in the same room."""
        # This function now assumes the sender is a browser and looks for a device.
        for client_id, client_info in list(active_connections_audio.items()):
            if client_info.get('room_id') == sender_room_id and client_info.get('client_type') == 'device':
                try:
                    # Forward audio to the ESP32 device in the room
                    client_info['websocket'].send(audio_data)
                except Exception as e:
                    logging.error(f"Error broadcasting audio to client {client_id}: {e}")
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
                        logging.info(f"Sent volume {volume_level} to client {client_id} in room {room_id}")
                    except Exception as e:
                        logging.error(f"Error sending volume to audio client {client_id}: {e}")
                        if client_id in active_connections_audio:
                            del active_connections_audio[client_id]

    def broadcast_status_to_all(status):
        """Broadcasts the given status to all rooms and saves it."""
        # Use the centralized rooms_config to get the list of all room IDs
        for room_info in rooms_config:
            status_message = {"room": room_info['id'], "status": status}
            broadcast_status(status_message)
            save_room_data(room_info['id'], 'status', status_message)