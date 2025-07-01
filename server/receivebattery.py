from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
import json
import uvicorn

app = FastAPI()

# Enable CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Battery status storage with default values
battery_status = {
    "conferenceRoom": 100,
    "adminRoom": 80,
    "classRoom": 90
}

# Default status for the module
module_status = {
    "active": False
}

# WebSocket connections
active_connections = []

@app.websocket("/ws/battery")
async def websocket_battery(websocket: WebSocket):
    await websocket.accept()
    active_connections.append(websocket)
    
    # Send the current battery status to the newly connected client
    await websocket.send_text(json.dumps(battery_status))
    
    try:
        while True:
            data = await websocket.receive_text()
            # Could receive updates from client if needed
    except WebSocketDisconnect:
        active_connections.remove(websocket)

@app.get("/api/battery")
async def get_battery():
    return battery_status

@app.post("/api/update_battery")
async def update_battery(room: str, percentage: int):
    if room in battery_status:
        battery_status[room] = percentage
        # Notify all WebSocket clients
        for connection in active_connections:
            await connection.send_text(json.dumps({
                "room": room,
                "percentage": percentage
            }))
        return {"status": "updated"}
    return {"status": "room not found"}

@app.get("/api/default_battery")
async def get_default_battery():
    # Return default values if no updates have been made
    return {
        "conferenceRoom": 70,
        "adminRoom": 80,
        "classRoom": 90
    }

@app.websocket("/ws/status")
async def websocket_status(websocket: WebSocket):
    await websocket.accept()
    active_connections.append(websocket)
    
    # Send the current status to the newly connected client
    await websocket.send_text(json.dumps(module_status))
    
    try:
        while True:
            data = await websocket.receive_text()
            # Update status based on received data
            message = json.loads(data)
            if "active" in message:
                module_status["active"] = message["active"]
                # Notify all WebSocket clients about the status change
                for connection in active_connections:
                    await connection.send_text(json.dumps(module_status))
    except WebSocketDisconnect:
        active_connections.remove(websocket)

@app.get("/api/status")
async def get_status():
    return module_status

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=5000)




@app.websocket("/ws/battery")
async def battery_websocket(websocket: WebSocket):
    await websocket.accept()
    # Handle battery updates here
  