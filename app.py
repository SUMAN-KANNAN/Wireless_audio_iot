from flask import Flask, render_template, request, redirect, url_for, session
from datetime import timedelta
from server.sock_instance import sock
import os
import json
from itsdangerous import URLSafeTimedSerializer
from server.websocket_handlers import register_websocket_routes, get_room_data

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

# This list now controls which rooms appear on the dashboard and which rooms the WebSocket server is aware of.
# To add a new room, just add a new dictionary here.
rooms_config = [
    {'id': 'conferenceRoom', 'name': 'Conference Room', 'switch_id': 'switchConference', 'volume_id': 'volumeConference'},
    {'id': 'adminRoom', 'name': 'Admin Room', 'switch_id': 'switchAdmin', 'volume_id': 'volumeAdmin'},
    {'id': 'classRoom', 'name': 'Class Room', 'switch_id': 'switchClass', 'volume_id': 'volumeClass'},
]
register_websocket_routes(sock, app.secret_key, DEVICE_API_KEY, rooms_config)

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

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)