import json
import os
from flask_sock import Sock
from itsdangerous import URLSafeTimedSerializer, SignatureExpired, BadTimeSignature
from urllib.parse import parse_qs
import logging
import time
import threading
from .audio_processing import process_audio_chunk
import redis

# --- ARCHITECTURAL UPGRADE: Use Redis for State Management ---
# Redis provides an atomic, in-memory data store that is faster and more reliable
# than file-based storage, preventing race conditions and performance bottlenecks.
# It's configured to return strings, which we'll then parse from JSON.
redis_client = redis.Redis(decode_responses=True)
logging.info("Redis client connected.")

# Centralized storage for active WebSocket connections
active_connections_status = {}
active_connections_battery = {}
active_connections_audio = {}
active_connections_volume = [] # This remains a list as it's only used by the browser client

# --- INTELLIGENCE UPGRADE: Enforce a single, authoritative device per room ---
# This map tracks the primary 'status' connection for each device.
room_device_map = {} # Maps room_id -> client_id of the status websocket

# --- INTELLIGENCE UPGRADE: Watchdog for immediate disconnect detection ---
device_last_seen = {}  # Maps room_id -> last_seen_timestamp
WATCHDOG_INTERVAL = 5  # Check for stale devices every 5 seconds
DEVICE_TIMEOUT = 15    # A device is stale if no message is received for 15 seconds

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

def delete_room_data_key(room, key):
    """Deletes a specific key (e.g., 'battery') from a room's hash in Redis."""
    try:
        redis_key = f"room:{room}"
        redis_client.hdel(redis_key, key)
        logging.info(f"Cleared '{key}' for room '{room}' from Redis.")
    except redis.exceptions.ConnectionError as e:
        logging.critical(f"Could not connect to Redis to delete data. Is Redis running? Error: {e}")

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

# --- Generic Broadcasting and Helper Functions (Moved to top level for clarity) ---

def _broadcast_to_browsers(clients_dict, message):
    """Generic function to broadcast a JSON message to BROWSER clients."""
    disconnected_clients = []
    # Use list() to create a copy for safe iteration while modifying
    for client_id, client_info in list(clients_dict.items()):
        if client_info.get('client_type') == 'browser':
            try:
                client_info['websocket'].send(json.dumps(message))
            except Exception as e:
                logging.error(f"Error broadcasting to browser {client_id}: {e}. Marking for removal.")
                disconnected_clients.append(client_id)
    
    for client_id in disconnected_clients:
        if client_id in clients_dict:
            del clients_dict[client_id]

def broadcast_status(status_message):
    """Broadcasts a status message to all connected browser clients."""
    _broadcast_to_browsers(active_connections_status, status_message)

# --- INTELLIGENCE UPGRADE: Watchdog Implementation (Moved to top level) ---

def _device_watchdog_task():
    """
    Background task that periodically checks for stale device connections.
    """
    while True:
        time.sleep(WATCHDOG_INTERVAL)
        now = time.time()
        # Create a copy of the dictionary to avoid "dictionary changed size during iteration" errors
        stale_rooms = [
            room_id for room_id, last_seen in list(device_last_seen.items())
            if now - last_seen > DEVICE_TIMEOUT
        ]
        
        if stale_rooms:
            logging.warning(f"Watchdog found stale devices in rooms: {stale_rooms}")
            for room_id in stale_rooms:
                disconnected_state = {'room': room_id, 'status': 'Disconnected'}
                save_room_data(room_id, 'status', disconnected_state)
                # --- REALISM UPGRADE: Clear battery on disconnect ---
                # When a device disconnects, its battery level is unknown.
                # Clearing it ensures the UI shows a '--%' state on next load.
                delete_room_data_key(room_id, 'battery')
                broadcast_status(disconnected_state)
                
                if room_id in room_device_map:
                    client_id_to_close = room_device_map[room_id]
                    for clients_dict in [active_connections_status, active_connections_battery, active_connections_audio]:
                        if client_id_to_close in clients_dict:
                            try:
                                clients_dict[client_id_to_close]['websocket'].close()
                                logging.info(f"Watchdog closed stale socket for client {client_id_to_close} in room {room_id}")
                            except Exception as e:
                                logging.error(f"Error closing stale socket for client {client_id_to_close}: {e}")
                    if room_id in room_device_map: del room_device_map[room_id]
                if room_id in device_last_seen: del device_last_seen[room_id]

def start_device_watchdog():
    """Starts the device watchdog thread. Must be called once on application startup."""
    watchdog_thread = threading.Thread(target=_device_watchdog_task, daemon=True)
    watchdog_thread.start()
    logging.info("Device connection watchdog started.")

def register_websocket_routes(sock: Sock, secret_key: str, device_api_key: str, rooms_config: list):
    """Registers WebSocket routes with the Flask-Sock instance."""
    serializer = URLSafeTimedSerializer(secret_key)

    def _get_auth_type(ws):
        """
        Verify authentication and return the client type ('device', 'browser', or None).
        """
        device_key = ws.environ.get('HTTP_X_API_KEY')
        if device_key:
            if device_key == device_api_key:
                logging.info("Device authenticated successfully via header.")
                return 'device'
            else:
                logging.warning("Auth Error: Invalid device API key in header.")
                return None

        query_string = ws.environ.get('QUERY_STRING', '')
        params = parse_qs(query_string)
        token = params.get('token', [None])[0]
        if token:
            try:
                username = serializer.loads(token, max_age=1800)
                logging.info(f"User '{username}' authenticated successfully via token.")
                return 'browser'
            except SignatureExpired:
                logging.warning("Auth Error: User token has expired.")
                return None
            except (BadTimeSignature, Exception):
                logging.warning("Auth Error: User token is invalid.")
                return None
        
        logging.warning("Auth Error: No token or API key header provided.")
        return None

    @sock.route('/ws/status')
    def status_websocket(ws):
        """WebSocket endpoint for real-time status updates."""
        client_type = _get_auth_type(ws)
        if not client_type:
            return  # Close connection immediately

        client_id = id(ws)
        logging.info(f"Status client {client_id} ({client_type}) connected")
        active_connections_status[client_id] = {'websocket': ws, 'client_type': client_type, 'room_id': None}
        try:
            while True:
                message = ws.receive()
                if message:
                    try:
                        data = json.loads(message)
                        # First, check for an identification message
                        if data.get("type") == "room_identification" and "roomId" in data:
                            room_id = data["roomId"]
                            if client_id in active_connections_status:
                                # --- WATCHDOG HEARTBEAT ---
                                # Set initial timestamp when device identifies itself
                                device_last_seen[room_id] = time.time()
                                active_connections_status[client_id]['room_id'] = room_id
                                # --- Enforce single device per room ---
                                if room_id in room_device_map and room_device_map[room_id] != client_id:
                                    old_client_id = room_device_map[room_id]
                                    if old_client_id in active_connections_status:
                                        logging.warning(f"New device connection for room '{room_id}'. Disconnecting old client {old_client_id}.")
                                        # The .close() will trigger the 'finally' block for the old connection
                                        active_connections_status[old_client_id]['websocket'].close()
                                # Register the new client as the authoritative one for this room
                                room_device_map[room_id] = client_id

                                logging.info(f"Status client {client_id} identified for room {room_id}")
                            continue # Move to next message

                        # If it's a status update message
                        if 'room' in data and 'status' in data:
                            logging.info(f"Received status update from {client_type}: {data}")
                            
                            # If from a browser, it's a command. Forward it to the correct device(s).
                            if client_type == 'browser':
                                forward_status_to_device(data)

                            # Save state and update all browsers.
                            if data['room'] == 'all':
                                for room_config in rooms_config:
                                    room_id = room_config['id']
                                    state_to_save_and_broadcast = {'room': room_id, 'status': data['status']}
                                    save_room_data(room_id, 'status', state_to_save_and_broadcast)
                                    broadcast_status(state_to_save_and_broadcast)
                            else:
                                save_room_data(data['room'], 'status', data)
                                broadcast_status(data)
                        else:
                            logging.warning(f"Received status message with unexpected format: {data}")
                    except json.JSONDecodeError:
                        logging.warning(f"Received non-JSON message on status websocket: {message}")
                    except Exception as e:
                        logging.error(f"Error processing status message: {e}")
        except Exception as e:
            logging.error(f"Status WebSocket error: {e}")
        finally:
            _handle_device_disconnect(client_id, active_connections_status, 'status')

    @sock.route('/ws/battery')
    def battery_websocket(ws):
        """WebSocket endpoint for real-time battery updates."""
        client_type = _get_auth_type(ws)
        if not client_type:
            return

        client_id = id(ws)
        logging.info(f"Battery client {client_id} ({client_type}) connected")
        active_connections_battery[client_id] = {'websocket': ws, 'client_type': client_type, 'room_id': None}
        try:
            while True:
                message = ws.receive()
                if message:
                    try:
                        data = json.loads(message)
                        # First, check for an identification message
                        if data.get("type") == "room_identification" and "roomId" in data:
                            room_id = data["roomId"]
                            if client_id in active_connections_battery:
                                active_connections_battery[client_id]['room_id'] = room_id
                                logging.info(f"Battery client {client_id} identified for room {room_id}")
                            continue # Move to next message

                        if isinstance(data, dict) and 'room' in data and 'percentage' in data:
                            room_id = data['room']
                            # --- WATCHDOG HEARTBEAT ---
                            # Update timestamp on every battery message
                            device_last_seen[room_id] = time.time()

                            logging.info(f"Broadcasting battery update: {data}")
                            save_room_data(data['room'], 'battery', data)
                            broadcast_battery(data)
                        else:
                            logging.warning(f"Received battery message with unexpected format: {data}")
                    except json.JSONDecodeError:
                        logging.warning(f"Received non-JSON message on battery websocket: {message}")
                    except Exception as e:
                        logging.error(f"Error processing battery message: {e}")
        except Exception as e:
            logging.error(f"Battery WebSocket error: {e}")
        finally:
            _handle_device_disconnect(client_id, active_connections_battery, 'battery')

    @sock.route('/ws/audio')
    def audio(ws):
        """WebSocket endpoint for real-time audio streaming (robust handling)."""
        # The audio endpoint needs to know the client type for routing.
        client_type = _get_auth_type(ws)
        if not client_type:
            return

        client_id = id(ws)
        active_connections_audio[client_id] = {'websocket': ws, 'room_id': None, 'client_type': client_type}
        try:
            while True:
                message = ws.receive()
                if message is None:
                    break
                if isinstance(message, bytes):
                    # This is audio data. Check if it's from a browser.
                    sender_info = active_connections_audio.get(client_id)
                    if sender_info and sender_info.get('client_type') == 'browser' and sender_info.get('room_id'):
                        # Process and forward the audio.
                        broadcast_audio(message, sender_info['room_id'])
                else:
                    # This is a JSON command, likely for identification.
                    try:
                        data = json.loads(message)
                        if data.get("type") == "room_identification" and "roomId" in data:
                            if client_id in active_connections_audio:
                                active_connections_audio[client_id]['room_id'] = data["roomId"]
                                room_id = data["roomId"]
                                logging.info(f"Client {client_id} identified for room {room_id} as {client_type}")
                        # You can add other JSON command handling here if needed
                    except Exception as e:
                        logging.warning(f"Could not decode JSON message from audio client: {e}")
                        continue
        except Exception as e:
            logging.error(f"Audio WebSocket error for client {client_id}: {e}")
        finally:
            _handle_device_disconnect(client_id, active_connections_audio, 'audio')

    @sock.route('/ws/volume')
    def volume_websocket(ws):
        """WebSocket endpoint for real-time volume control."""
        # This endpoint is only used by the browser, so we can be more specific.
        if _get_auth_type(ws) != 'browser':
            return

        logging.info("Volume client connected")
        active_connections_volume.append(ws)
        try:
            while True:
                message = ws.receive()
                if message:
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

    def _handle_device_disconnect(client_id, clients_dict, channel_type):
        """Helper to manage state when a device's WebSocket connection closes."""
        if client_id in clients_dict:
            client_info = clients_dict.get(client_id, {})
            room_id = client_info.get('room_id')

            if client_info.get('client_type') == 'device' and room_id:
                # --- WATCHDOG CLEANUP ---
                # If the authoritative device for a room disconnects, remove its watchdog timer.
                if room_device_map.get(room_id) == client_id and room_id in device_last_seen:
                    del device_last_seen[room_id]
                    logging.info(f"Graceful disconnect for room '{room_id}'. Watchdog timer removed.")
            # --- INTELLIGENCE UPGRADE: Only trigger "Disconnected" state on critical channel loss ---
            # The 'status' and 'battery' channels are the heartbeats of the device.
            # The 'audio' channel is ephemeral and is expected to disconnect when a room is muted.
            # We only want to mark the device as fully disconnected if a core channel is lost.
            if client_info.get('client_type') == 'device' and client_info.get('room_id') and channel_type in ['status', 'battery']:
                room_id = client_info['room_id']
                logging.info(f"Device for room '{room_id}' disconnected. Updating state to Disconnected.")

                # If this disconnecting client was the authoritative one, remove it from the map
                if room_device_map.get(room_id) == client_id:
                    del room_device_map[room_id]
                    logging.info(f"Authoritative device for room '{room_id}' disconnected. Map updated.")
                
                # Create the disconnected message
                disconnected_state = {'room': room_id, 'status': 'Disconnected'}
                
                save_room_data(room_id, 'status', disconnected_state)
                
                # --- REALISM UPGRADE: Clear battery on disconnect ---
                delete_room_data_key(room_id, 'battery')
                # Broadcast the disconnected status to all connected browsers.
                broadcast_status(disconnected_state)
            
            del clients_dict[client_id]
            logging.info(f"Client {client_id} disconnected and cleaned up from {channel_type} channel.")

    # --- Broadcasting Functions ---

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

    # --- Broadcasting and Forwarding Functions (New Implementation) ---

    def broadcast_battery(battery_message):
        _broadcast_to_browsers(active_connections_battery, battery_message)

    def broadcast_audio(audio_data, sender_room_id):
        """Processes and forwards audio data from a browser to the correct device."""
        # --- ROBUSTNESS UPGRADE: Prevent race condition on mute ---
        # Before processing and forwarding audio, check the authoritative state of the room from Redis.
        # This prevents a race condition where the browser sends a final audio packet *after*
        # sending the mute command, which would cause an error when the server tries to send
        # to the device's now-closed socket.
        room_state = get_room_data(sender_room_id)
        current_status = room_state.get('status', {}).get('status')

        if current_status != 'Active':
            # If the room is not active, simply drop the audio packet and do nothing.
            return

        processed_audio_data = process_audio_chunk(audio_data)

        for client_id, client_info in list(active_connections_audio.items()):
            if client_info.get('room_id') == sender_room_id and client_info.get('client_type') == 'device':
                try:
                    client_info['websocket'].send(processed_audio_data)
                except Exception as e:
                    logging.error(f"Error forwarding audio to device {client_id}: {e}")
                    if client_id in active_connections_audio:
                        del active_connections_audio[client_id]

    def forward_status_to_device(status_message):
        """Forwards a status command from a browser to the correct device(s)."""
        room_to_target = status_message.get('room')
        if not room_to_target:
            return

        # Find the relevant device connection(s) in the status channel
        for client_id, client_info in list(active_connections_status.items()):
            # We only forward commands to clients identified as 'device'
            if client_info.get('client_type') == 'device':
                # Check if the command is for 'all' rooms or for this specific device's room
                if room_to_target == 'all' or client_info.get('room_id') == room_to_target:
                    try:
                        # The device firmware expects a command for its specific room, not 'all'.
                        message_to_send = status_message.copy()
                        if room_to_target == 'all':
                            # If the command is for 'all', we must create a specific command
                            # for this device's room.
                            device_room_id = client_info.get('room_id')
                            if not device_room_id: continue # Skip if device hasn't identified itself yet
                            message_to_send['room'] = device_room_id

                        client_info['websocket'].send(json.dumps(message_to_send))
                        logging.info(f"Forwarded status command {message_to_send} to device {client_id}")
                        
                        # If we targeted a specific room, we can stop after finding it.
                        # If we are targeting 'all', we must continue to iterate.
                        if room_to_target != 'all':
                            break
                    except Exception as e:
                        logging.error(f"Error forwarding status to device {client_id}: {e}")