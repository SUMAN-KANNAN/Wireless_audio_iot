import os
import json
from server.sock_instance import sock

volume_log = {}

@sock.route('/ws/volume')
def volume_socket(ws):
    print("🔗 WebSocket connected (volume)")
    while True:
        try:
            message = ws.receive()
            if not message:
                break

            data = json.loads(message)
            if data.get("type") == "volume":
                for entry in data.get("data", []):
                    hardware_id = entry.get("hardware_id")
                    room_id = entry.get("room_id")
                    field = entry.get("field")
                    value = entry.get("value")

                    if hardware_id and room_id and field:
                        volume_log[room_id] = {
                            "hardware_id": hardware_id,
                            "room_id": room_id,
                            "field": field,
                            "value": value
                        }
                        print(f"🔊 Volume update for {room_id}: {value}%")
                save_volume_json()
        except Exception as e:
            print(f"Volume WebSocket error: {e}")
            break

def save_volume_json():
    directory = "saved_volume"
    os.makedirs(directory, exist_ok=True)
    filename = os.path.join(directory, "volume_changes.json")
    with open(filename, 'w') as f:
        json.dump(volume_log, f, indent=2)
    print(f"✅ Volume saved to {filename}")
