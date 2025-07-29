from flask import Flask, render_template, request, redirect, url_for, session
from datetime import timedelta
from server.sock_instance import sock
from itsdangerous import URLSafeTimedSerializer, SignatureExpired, BadTimeSignature
from server.websocket_handlers import register_websocket_routes, get_room_data, start_device_watchdog
import sys
import logging
import json
import redis
import socket
import threading
from zeroconf import ServiceInfo, Zeroconf
import os

SERVER_PORT = 5000

# Configure basic logging for more structured and informative output
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

app = Flask(__name__)
sock.init_app(app)
app.secret_key = os.environ.get('SECRET_KEY', 'you-should-set-a-secret-key')
app.permanent_session_lifetime = timedelta(minutes=30)

# Use the app's secret key for the serializer
serializer = URLSafeTimedSerializer(app.secret_key)
# Load the device API key from an environment variable for better security.
# Fallback to a default key for development convenience.
DEVICE_API_KEY = os.environ.get('DEVICE_API_KEY', 'a-very-secret-key-for-devices-only')

USER_CREDENTIALS = {
    os.environ.get('ADMIN_USER', 'admin'): os.environ.get('ADMIN_PASS', 'password'),
    os.environ.get('USER_USER', 'user'): os.environ.get('USER_PASS', '123')
}

def load_rooms_config():
    """Load room configuration from config.json."""
    try:
        with open('config.json', 'r', encoding='utf-8') as f:
            logging.info("Successfully loaded config.json")
            return json.load(f)
    except FileNotFoundError:
        logging.critical("config.json not found! The application will run but no rooms will be available.")
        return []
    except json.JSONDecodeError as e:
        logging.critical(f"config.json is not valid JSON! Error: {e}. The application will run but no rooms will be available.")
        return []

rooms_config = load_rooms_config()
register_websocket_routes(sock, app.secret_key, DEVICE_API_KEY, rooms_config)
# --- INTELLIGENCE UPGRADE: Start the watchdog for immediate disconnect detection ---
start_device_watchdog()

def get_local_ip():
    """Find the local IP address of the machine."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        # Doesn't have to be reachable
        s.connect(('10.255.255.255', 1))
        IP = s.getsockname()[0]
    except Exception:
        IP = '127.0.0.1'
    finally:
        s.close()
    return IP

def start_mdns_service():
    """Announce the web service via mDNS."""
    local_ip = get_local_ip()
    service_info = ServiceInfo(
        "_web-audio._tcp.local.",
        "Wireless Audio Server._web-audio._tcp.local.",
        addresses=[socket.inet_aton(local_ip)],
        port=SERVER_PORT,
        properties={'path': '/'},
    )
    zeroconf = Zeroconf()
    zeroconf.register_service(service_info)
    logging.info(f"mDNS service 'Wireless Audio Server' registered at {local_ip}:{SERVER_PORT}")

@app.route('/', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        if username in USER_CREDENTIALS and USER_CREDENTIALS[username] == password:
            session.permanent = True
            session['user'] = username
            # Create a token for the WebSocket connection
            session['auth_token'] = serializer.dumps(username)
            return redirect(url_for('dashboard'))
        else:
            return render_template('login.html', error="Invalid username or password")
    return render_template('login.html', error=None)

@app.route('/dashboard')
def dashboard():
    if 'user' in session:
        return render_template(
            'landing.html',
            user=session['user'],
            rooms=rooms_config,
            auth_token=session.get('auth_token') # Pass token to template
        )
    else:
        return redirect(url_for('login'))

@app.route('/get_all_room_states')
def get_all_room_states():
    """API endpoint to fetch the last known state for all rooms."""
    if 'user' not in session:
        return {}, 401 # Unauthorized
    
    all_states = {room['id']: get_room_data(room['id']) for room in rooms_config}
    return all_states

@app.route('/logout')
def logout():
    session.pop('user', None)
    return redirect(url_for('login'))

def clear_redis_on_startup(config):
    """Clear old room state from Redis to ensure a fresh start."""
    try:
        r = redis.Redis(decode_responses=True)
        # Construct the keys to delete based on the rooms in config.json
        keys_to_delete = [f"room:{room['id']}" for room in config]
        if keys_to_delete:
            # The 'delete' command can take multiple keys at once for efficiency
            deleted_count = r.delete(*keys_to_delete)
            logging.info(f"Cleared {deleted_count} old room state(s) from Redis for a fresh start.")
    except redis.exceptions.ConnectionError as e:
        logging.critical(f"Could not connect to Redis to clear old state. Is Redis running? Error: {e}")
    except Exception as e:
        logging.error(f"An unexpected error occurred while clearing Redis: {e}")

if __name__ == '__main__':
    # --- Production-Ready State Management ---
    # In development, it's useful to clear old state. In production, you usually want
    # the state to persist across server restarts. We use an environment variable to control this.
    if os.environ.get('CLEAR_REDIS_ON_STARTUP', 'True').lower() in ('true', '1', 't'):
        logging.info("CLEAR_REDIS_ON_STARTUP is True. Clearing old room states from Redis.")
        clear_redis_on_startup(rooms_config)
    else:
        logging.info("CLEAR_REDIS_ON_STARTUP is False. Preserving existing room states in Redis.")
    # Start mDNS in a background thread
    mdns_thread = threading.Thread(target=start_mdns_service, daemon=True)
    mdns_thread.start()
    # Run the Flask app
    app.run(host='0.0.0.0', port=SERVER_PORT, debug=True, use_reloader=False)