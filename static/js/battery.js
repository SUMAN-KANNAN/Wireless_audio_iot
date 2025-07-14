// Default battery values
const defaultBattery = {
    conferenceRoom: 100,
    adminRoom: 80,
    classRoom: 90
};

// Function to initialize battery display
function initBatteryDisplay() {
    for (const room in defaultBattery) {
        updateBatteryDisplay(room, defaultBattery[room]);
    }
}

// Function to update battery display for a specific room
function updateBatteryDisplay(roomId, percentage) {
    const percentageElement = document.querySelector(`#${roomId} .battery-percentage`);
    const levelElement = document.querySelector(`#${roomId} .battery-level`);

    if (percentageElement && levelElement) {
        percentageElement.textContent = `${percentage}%`;
        levelElement.style.width = `${percentage}%`;

        // Set color based on battery level
        if (percentage < 20) {
            levelElement.style.backgroundColor = '#ff4444'; // Red
        } else if (percentage < 50) {
            levelElement.style.backgroundColor = '#ffbb33'; // Yellow
        } else {
            levelElement.style.backgroundColor = '#00C851'; // Green
        }
    }
}

// Call this function when the page loads
document.addEventListener('DOMContentLoaded', () => {
    initBatteryDisplay();
});
function connectBatteryWebSocket() {
    const socket = new WebSocket(`ws://${window.location.host}/ws/battery`);

    socket.onmessage = (event) => {
        const data = JSON.parse(event.data);
        if (data.type === 'battery_update') {
            updateBatteryDisplay(data.room, data.percentage);
        }
    };

    socket.onclose = () => {
        console.log('WebSocket disconnected, retrying...');
        setTimeout(connectBatteryWebSocket, 5000);
    };
}

// Call this function to start the WebSocket connection
connectBatteryWebSocket();