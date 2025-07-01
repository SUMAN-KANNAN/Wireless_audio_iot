import os
import json
from server.sock_instance import sock

audio_log = {}

@sock.route('/ws/audio')
def audio_socket(ws):
    print("🔗 WebSocket connected (audio)")
    while True:
        try:
            message = ws.receive()
            if not message:
                break

            data = json.loads(message)
            if data.get("field") == "audio":
                hardware_id = data.get("hardware_id")
                room_id = data.get("room_id")
                field = data.get("field")
                chunk = data.get("value")

                if hardware_id and room_id and field and chunk:
                    audio_log[room_id] = {
                        "hardware_id": hardware_id,
                        "room_id": room_id,
                        "field": field,
                        "value": chunk
                    }
                    print(f"🎙️ Audio chunk received for {room_id}")
                save_audio_json()
        except Exception as e:
            print(f"Audio WebSocket error: {e}")
            break

def save_audio_json():
    directory = "saved_audio"
    os.makedirs(directory, exist_ok=True)
    filename = os.path.join(directory, "audio_activity.json")
    with open(filename, 'w') as f:
        json.dump(audio_log, f, indent=2)
    print(f"✅ Audio activity saved to {filename}")
