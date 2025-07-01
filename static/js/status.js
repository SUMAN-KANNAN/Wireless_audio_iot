// Connect to WebSocket
const socket = new WebSocket('ws://127.0.0.1:5000/ws/status');

socket.onopen = () => {
    console.log("WebSocket connection established");
};

socket.onmessage = (event) => {
    const data = JSON.parse(event.data);
    const checkbox = document.getElementById('roomCheckbox');
    const checkmark = document.querySelector('.checkmark'); // Target the checkmark element

    if (data.status === "New data from IoT") {
        // Check the checkbox and update UI
        checkbox.checked = true;
        checkmark.style.backgroundColor = "#4caf50"; // Green when active
        console.log("Status active - green");
    } else {
        // Uncheck the checkbox and update UI
        checkbox.checked = false;
        checkmark.style.backgroundColor = "#ff0000"; // Red when inactive
        console.log("Status inactive - red");
    }
};

socket.onclose = () => {
    console.log("WebSocket connection closed");
};

socket.onerror = (error) => {
    console.error("WebSocket error:", error);
};
