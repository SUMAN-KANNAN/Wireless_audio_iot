<<<<<<< HEAD
from flask import Flask, render_template, request, redirect, url_for, session
from datetime import timedelta

app = Flask(__name__)
app.secret_key = 'maud82hd92m!@f8dsJDFN3209dfnv@#3j'
app.permanent_session_lifetime = timedelta(minutes=30)

# Dummy credentials
USER_CREDENTIALS = {
    'admin': 'password',
    'user': '123'
}

@app.route('/', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']

        # Authentication check
        if username in USER_CREDENTIALS and USER_CREDENTIALS[username] == password:
            session.permanent = True
            session['user'] = username
            return redirect(url_for('dashboard'))
        else:
            return render_template('login.html', error="Invalid username or password")

    return render_template('login.html', error=None)

@app.route('/dashboard')
def dashboard():
    if 'user' in session:
        return render_template('landing.html', user=session['user'])  # <-- render landing.html here
    else:
        return redirect(url_for('login'))

@app.route('/logout')
def logout():
    session.pop('user', None)
    return redirect(url_for('login'))

if __name__ == '__main__':
    app.run(debug=True)
=======
from flask import Flask, render_template, request, redirect, url_for, session
from datetime import timedelta
from server.sock_instance import sock
import server.sendaud
import server.sendvol
from flask_sock import Sock
import json
import asyncio
import server.receivestatus
import server.receivebattery

app = Flask(__name__)
sock.init_app(app)
app.secret_key = 'maud82hd92m!@f8dsJDFN3209dfnv@#3j'
app.permanent_session_lifetime = timedelta(minutes=30)

# Dummy credentials
USER_CREDENTIALS = {
    'admin': 'password',
    'user': '123'
}

# Store active WebSocket connections
active_connections = []

@app.route('/', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        if username in USER_CREDENTIALS and USER_CREDENTIALS[username] == password:
            session.permanent = True
            session['user'] = username
            return redirect(url_for('dashboard'))
        else:
            return render_template('login.html', error="Invalid username or password")
    return render_template('login.html', error=None)

@app.route('/dashboard')
def dashboard():
    if 'user' in session:
        return render_template('landing.html', user=session['user'])
    else:
        return redirect(url_for('login'))

@app.route('/logout')
def logout():
    session.pop('user', None)
    return redirect(url_for('login'))



@sock.route('/ws/status')
def status_websocket(ws):
    """WebSocket endpoint for real-time status updates."""
    active_connections.append(ws)
    try:
        while True:
            # Keep the connection alive
            message = ws.receive()
            if message:
                print(f"Received message: {message}")
    except Exception as e:
        print(f"WebSocket error: {str(e)}")
    finally:
        active_connections.remove(ws)

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

if __name__ == '__main__':
    loop = asyncio.get_event_loop()
    # Schedule the receive_iot_data coroutine to run in the background
    loop.create_task(receive_iot_data())
    # asyncio.run(receive_iot_data())
    app.run(debug=True)
>>>>>>> f1ee74b (first commit)
