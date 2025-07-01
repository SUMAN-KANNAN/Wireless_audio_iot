// // Initial setup when page loads
// document.addEventListener('DOMContentLoaded', () => {
//     initBatteryDisplay();
    
//     // Start WebSocket connection
//     connectBatteryWebSocket();
// });

// // Battery display elements
// const batteryElements = {
//     conferenceRoom: {
//         percentage: document.querySelector('#conferenceRoom .battery-percentage'),
//         level: document.querySelector('#conferenceRoom .battery-level')
//     },
//     adminRoom: {
//         percentage: document.querySelector('#adminRoom .battery-percentage'),
//         level: document.querySelector('#adminRoom .battery-level')
//     },
//     classRoom: {
//         percentage: document.querySelector('#classRoom .battery-percentage'),
//         level: document.querySelector('#classRoom .battery-level')
//     }
// };

// // Default battery values
// const defaultBattery = {
//     conferenceRoom: 70,
//     adminRoom: 80,
//     classRoom: 90
// };


// // Initialize with default values
// function initBatteryDisplay() {
//     // Set defaults immediately for better UX
//     for (const room in defaultBattery) {
//         updateBatteryDisplay(room, defaultBattery[room]);
//     }
    
//     // Then try to fetch live data
//     fetch('http://localhost:5000/api/battery')
//         .then(res => {
//             if (!res.ok) throw new Error('Network response was not ok');
//             return res.json();
//         })
//         .then(data => {
//             for (const room in data) {
//                 updateBatteryDisplay(room, data[room]);
//             }
//         })
//         .catch(error => {
//             console.error('Error fetching battery data, using defaults:', error);
//         });
// }

// // Update battery display for a specific room
// function updateBatteryDisplay(roomId, percentage) {
//     const element = batteryElements[roomId];
//     if (element) {
//         element.percentage.textContent = `${percentage}%`;
//         element.level.style.width = `${percentage}%`;
        
//         // Set color based on battery level
//         if (percentage < 20) {
//             element.level.style.backgroundColor = '#ff4444';
//         } else if (percentage < 50) {
//             element.level.style.backgroundColor = '#ffbb33';
//         } else {
//             element.level.style.backgroundColor = '#00C851';
//         }
//     }
// }

// // Connect to WebSocket for real-time updates
// function connectBatteryWebSocket() {
//     const socket = new WebSocket(`ws://${window.location.hostname}:5000/ws/battery`);
    
//     socket.onmessage = (event) => {
//         const data = JSON.parse(event.data);
        
//         // If the data is an object with battery status, update the display
//         if (typeof data === 'object') {
//             for (const room in data) {
//                 updateBatteryDisplay(room, data[room]);
//             }
//         } else {
//             // Otherwise, it's an update for a specific room
//             updateBatteryDisplay(data.room, data.percentage);
//         }
//     };
    
//     socket.onclose = () => {
//         console.log('WebSocket disconnected, retrying...');
//         setTimeout(connectBatteryWebSocket, 5000);
//     };
// }



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