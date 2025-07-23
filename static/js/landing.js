let volumeSocket;
let statusSocket;
let batterySocket;

function updateBatteryDisplay(roomId, percentage) {
    const CRITICAL_LEVEL = 20;
    const WARNING_LEVEL = 50;
    const percentageElement = document.querySelector(`#${roomId} .battery-percentage`);
    const levelElement = document.querySelector(`#${roomId} .battery-level`);

    if (percentageElement && levelElement) {
        // Handle null or undefined percentage, which can happen on initial load
        if (percentage === null || typeof percentage === 'undefined' || isNaN(percentage)) {
            percentageElement.textContent = `--%`;
            levelElement.style.width = `100%`; // Fill the bar to show it's an error/unknown state
            levelElement.style.backgroundColor = '#cc0000'; // Darker red for unknown/error
        } else {
            percentageElement.textContent = `${percentage}%`;
            levelElement.style.width = `${percentage}%`;

            // Set color based on battery level
            if (percentage < CRITICAL_LEVEL) {
                levelElement.style.backgroundColor = '#ff4444'; // Red
            } else if (percentage < WARNING_LEVEL) {
                levelElement.style.backgroundColor = '#ffbb33'; // Yellow
            } else {
                levelElement.style.backgroundColor = '#00C851'; // Green
            }
        }
    }
    // After updating the battery, re-evaluate the status dot color
    // This ensures the dot turns red if the battery state becomes unknown.
    setStatusDot(roomId, null);
}

function createAuthenticatedSocket(path) {
    if (!authToken) {
        console.error("Authentication token is missing. Cannot connect WebSocket.");
        alert("Authentication error. Please log in again.");
        window.location.href = '/logout';
        return null;
    }
    const url = `ws://${window.location.host}${path}?token=${authToken}`;
    return new WebSocket(url);
}

function connectBatteryWebSocket() {
    batterySocket = createAuthenticatedSocket('/ws/battery');

    batterySocket.onmessage = (event) => {
        try {
            const data = JSON.parse(event.data);
            if (data.room && data.percentage !== undefined) {
                updateBatteryDisplay(data.room, data.percentage);
            }
        } catch (e) {
            console.error("Error parsing battery message:", e);
        }
    };

    batterySocket.onclose = () => {
        setTimeout(connectBatteryWebSocket, 5000);
    };

    batterySocket.onerror = (error) => {
        console.error("Battery WebSocket error:", error);
    };
}

function connectStatusWebSocket() {
    statusSocket = createAuthenticatedSocket('/ws/status');

    statusSocket.onopen = () => {
        console.log("Status WebSocket connection established");
    };

    statusSocket.onmessage = function(event) {
        const data = JSON.parse(event.data);
        const roomId = data.room;
        const newStatus = data.status;

        if (!roomId || !newStatus) return;

        // Update the status dot, which will also check battery level
        setStatusDot(roomId, newStatus);
    };

    statusSocket.onclose = () => {
        setTimeout(connectStatusWebSocket, 5000);
    };

    statusSocket.onerror = (error) => {
        console.error("Status WebSocket error:", error);
    };
}

function connectVolumeWebSocket() {
    volumeSocket = createAuthenticatedSocket('/ws/volume');

    volumeSocket.onopen = () => {
        console.log("Volume WebSocket connection established");
    };

    volumeSocket.onmessage = (event) => {
        // Handle volume messages from the server if needed
    };

    volumeSocket.onclose = () => {
        setTimeout(connectVolumeWebSocket, 5000);
    };

    volumeSocket.onerror = (error) => {
        console.error("Volume WebSocket error:", error);
    };
}

function sendVolumeUpdate() {
    const volumes = {};
    document.querySelectorAll('.volume-slider').forEach(slider => {
        // The room ID is stored in a data attribute on the slider
        const roomId = slider.dataset.room;
        if (roomId && !slider.id.includes('masterVolume')) {
            volumes[roomId] = parseInt(slider.value);
        }
    });

    const message = {
        type: "volume",
        data: volumes
    };

    if (volumeSocket && volumeSocket.readyState === WebSocket.OPEN) {
        volumeSocket.send(JSON.stringify(message));
    }
}

const audioManager = {
    // --- Audio Tuning Parameter ---
    // Lower value = lower latency, higher network traffic (e.g., 50ms)
    // Higher value = higher latency, more stable on poor networks (e.g., 250ms)
    audioChunkTimeslice: 100, // in milliseconds
    audioContext: null,
    microphone: null,
    mediaRecorder: null,
    mediaStream: null,
    isMicActive: false,
    activeRoomSockets: {}, // { roomId: WebSocket }

    async toggleMic(roomId) {
        let switchId = '';
        switch (roomId) {
            case 'conferenceRoom': switchId = 'switchConference'; break;
            case 'adminRoom': switchId = 'switchAdmin'; break;
            case 'classRoom': switchId = 'switchClass'; break;
            default: return;
        }

        const switchElement = document.getElementById(switchId);
        if (!switchElement) return;

        updateListeningCount();

        if (switchElement.checked) {
            // Turning ON
            if (Object.keys(this.activeRoomSockets).length === 0) {
                await this.activateMicrophone();
            }
            const ws = createAuthenticatedSocket('/ws/audio');
            ws.onopen = () => {
                ws.send(JSON.stringify({ type: 'room_identification', roomId, client_type: 'browser' }));
            };
            ws.onerror = (e) => { console.error(`Audio WS error for ${roomId}:`, e); };
            ws.onclose = () => { console.log(`Audio WS closed for ${roomId}`); };
            this.activeRoomSockets[roomId] = ws;

            if (statusSocket && statusSocket.readyState === WebSocket.OPEN) {
                statusSocket.send(JSON.stringify({ room: roomId, status: "Active" }));
            }
            setStatusDot(roomId, "Active");
        } else {
            // Turning OFF
            if (this.activeRoomSockets[roomId]) {
                this.activeRoomSockets[roomId].close();
                delete this.activeRoomSockets[roomId];
            }
            if (Object.keys(this.activeRoomSockets).length === 0) {
                this.deactivateMicrophone();
            }
            if (statusSocket && statusSocket.readyState === WebSocket.OPEN) {
                statusSocket.send(JSON.stringify({ room: roomId, status: "Sleep" }));
            }
            setStatusDot(roomId, "Sleep");
        }
    },

    async activateMicrophone() {
        if (this.isMicActive) return;
        try {
            // Request a mono audio stream to match the ESP32's configuration.
            // This is a key step in preventing distortion.
            this.mediaStream = await navigator.mediaDevices.getUserMedia({ 
                audio: { channelCount: 1 } 
            });
            this.audioContext = new (window.AudioContext || window.webkitAudioContext)();
            this.microphone = this.audioContext.createMediaStreamSource(this.mediaStream);

            this.mediaRecorder = new MediaRecorder(this.mediaStream);

            this.mediaRecorder.ondataavailable = (event) => {
                if (event.data.size > 0) {
                    Object.values(this.activeRoomSockets).forEach(ws => {
                        if (ws.readyState === WebSocket.OPEN) {
                            ws.send(event.data);
                        }
                    });
                }
            };

            this.mediaRecorder.start(this.audioChunkTimeslice);
            this.isMicActive = true;
        } catch (error) {
            alert('Could not access microphone. Please ensure you have granted permission.');
            this.isMicActive = false;
        }
    },

    deactivateMicrophone() {
        if (this.mediaRecorder && this.mediaRecorder.state !== "inactive") {
            this.mediaRecorder.stop();
        }
        if (this.mediaStream) {
            this.mediaStream.getTracks().forEach(track => track.stop());
            this.mediaStream = null;
        }
        this.isMicActive = false;
        this.audioContext = null;
        this.microphone = null;
        Object.values(this.activeRoomSockets).forEach(ws => {
            if (ws.readyState === WebSocket.OPEN) ws.close();
        });
        this.activeRoomSockets = {};
    }
};

window.addEventListener('beforeunload', () => {
    const roomMap = {
        'switchConference': 'conferenceRoom',
        'switchAdmin': 'adminRoom',
        'switchClass': 'classRoom'
    };
    Object.entries(roomMap).forEach(([toggleId, roomId]) => {
        const toggle = document.getElementById(toggleId);
        if (toggle && !toggle.checked) {
            if (statusSocket && statusSocket.readyState === WebSocket.OPEN) {
                statusSocket.send(JSON.stringify({ room: roomId, status: "Sleep" }));
            }
        }
    });
    audioManager.deactivateMicrophone();
    if (statusSocket && statusSocket.readyState !== WebSocket.CLOSED) {
        statusSocket.close();
    }
    if (volumeSocket && volumeSocket.readyState !== WebSocket.CLOSED) {
        volumeSocket.close();
    }
    if (batterySocket && batterySocket.readyState !== WebSocket.CLOSED) {
        batterySocket.close();
    }
});

function muteAll() {
    const switches = document.querySelectorAll('.mic-toggle');
    switches.forEach(switchElement => {
        if (switchElement.checked) {
            const switchId = switchElement.id;
            let roomId = '';
            if (switchId.includes('Conference')) roomId = 'conferenceRoom';
            else if (switchId.includes('Admin')) roomId = 'adminRoom';
            else if (switchId.includes('Class')) roomId = 'classRoom';

            if (roomId && statusSocket && statusSocket.readyState === WebSocket.OPEN) {
                const statusMessage = { room: roomId, status: "Sleep" };
                statusSocket.send(JSON.stringify(statusMessage));
            }
        }
        switchElement.checked = false;
    });
    audioManager.deactivateMicrophone();
    updateListeningCount();
}

function unmuteAll() {

    // Send status update for all rooms
    if (statusSocket && statusSocket.readyState === WebSocket.OPEN) {
        statusSocket.send(JSON.stringify({ room: "all", status: "Active" }));
    }
    // Turn on all toggles
    document.querySelectorAll('.mic-toggle').forEach(switchElement => {
        switchElement.checked = true;

    });
    // Activate microphone
    audioManager.activateMicrophone(); // <-- This triggers getUserMedia and shows the icon
    updateListeningCount();
}

document.querySelectorAll('.mic-toggle').forEach(toggle => {
    toggle.addEventListener('change', (event) => {
        const switchId = event.target.id;
        let roomId = '';
        if (switchId.includes('Conference')) roomId = 'conferenceRoom';
        else if (switchId.includes('Admin')) roomId = 'adminRoom';
        else if (switchId.includes('Class')) roomId = 'classRoom';

        audioManager.toggleMic(roomId);
        checkAndDeactivateMicIfNoneActive();
    });
});

function updateListeningCount() {
    const toggles = document.querySelectorAll('.mic-toggle');
    let count = 0;
    toggles.forEach(toggle => {
        if (toggle.checked) count++;
    });
    document.getElementById('listeningCount').innerText = count;
}

function logout() {
    audioManager.deactivateMicrophone();
    if (statusSocket && statusSocket.readyState !== WebSocket.CLOSED) {
        statusSocket.close();
    }
    if (volumeSocket && volumeSocket.readyState !== WebSocket.CLOSED) {
        volumeSocket.close();
    }
    if (batterySocket && batterySocket.readyState !== WebSocket.CLOSED) {
        batterySocket.close();
    }
    window.location.href = '/logout';
}

function loadInitialStates() {
    fetch('/get_all_room_states')
        .then(response => response.json())
        .then(states => {
            for (const roomId in states) {
                const roomState = states[roomId];
                if (roomState.status) {
                    setStatusDot(roomId, roomState.status.status);
                }
                if (roomState.battery) {
                    updateBatteryDisplay(roomId, roomState.battery.percentage);
                }
                if (roomState.volume) {
                    const volumeSlider = document.getElementById(`volume${roomId.charAt(0).toUpperCase() + roomId.slice(1)}`);
                    if (volumeSlider) {
                        volumeSlider.value = roomState.volume.volume;
                    }
                }
            }
            // After setting individual sliders, update the master slider
            updateMasterSliderState();
        })
        .catch(error => console.error('Error fetching initial room states:', error));
}

document.addEventListener('DOMContentLoaded', () => {
    // Load last known states from server on page load
    loadInitialStates();

    // Connect WebSockets
    connectStatusWebSocket();
    connectVolumeWebSocket();
    connectBatteryWebSocket();

    // Initialize UI elements
    updateListeningCount();

    document.querySelectorAll('.mic').forEach(micIcon => {
        micIcon.addEventListener('click', (event) => {
            const roomId = event.target.closest('.tile').id;
            const roomName = roomId.replace('Room', '');
            const switchId = `switch${roomName.charAt(0).toUpperCase() + roomName.slice(1)}`;
            const switchElement = document.getElementById(switchId);
            if (switchElement) {
                switchElement.checked = !switchElement.checked;
                const changeEvent = new Event('change');
                switchElement.dispatchEvent(changeEvent);
            }
        });
    });

    // Add event listeners for all volume sliders
    document.querySelectorAll('.volume-slider').forEach(slider => {
        // When an individual slider is moved, update the master slider's state
        slider.addEventListener('input', updateMasterSliderState);
        // Send the final value when the user is done sliding
        slider.addEventListener('change', sendVolumeUpdate);
    });

    // Add event listener for the new master volume slider
    const masterVolumeSlider = document.getElementById('masterVolume');
    if (masterVolumeSlider) {
        masterVolumeSlider.addEventListener('input', () => {
            const masterValue = masterVolumeSlider.value;
            // Update all individual room sliders to match the master
            document.querySelectorAll('.volume-slider[data-room]').forEach(slider => {
                slider.value = masterValue;
            });
            // Send volume update in real-time as the master slider moves
            sendVolumeUpdate();
        });
        // Also send the final update when the user is done sliding
        masterVolumeSlider.addEventListener('change', sendVolumeUpdate);
    }
});

function checkAndDeactivateMicIfNoneActive() {
    const toggles = document.querySelectorAll('.mic-toggle');
    const anyActive = Array.from(toggles).some(toggle => toggle.checked);
    if (!anyActive) {
        audioManager.deactivateMicrophone();
    }
}

function updateMasterSliderState() {
    const masterVolumeSlider = document.getElementById('masterVolume');
    if (!masterVolumeSlider) return;

    const roomSliders = document.querySelectorAll('.volume-slider[data-room]');
    if (roomSliders.length === 0) return;

    const firstValue = roomSliders[0].value;
    const allSame = Array.from(roomSliders).every(slider => slider.value === firstValue);

    if (allSame) {
        masterVolumeSlider.value = firstValue;
    }
}

function setStatusDot(roomId, newStatus) {
    const tileElement = document.getElementById(roomId);
    if (!tileElement) return;

    const checkmark = tileElement.querySelector('.checkmark');
    if (!checkmark) return;

    // Determine the status to check. If a new status came in, use it.
    // Otherwise, infer the current status from the dot's color.
    let isActive;
    if (newStatus !== null) {
        // Store the latest status on the element itself
        checkmark.dataset.status = newStatus;
        isActive = (newStatus === "Active" || newStatus === "On");
    } else {
        // Re-evaluating, so use the stored status
        isActive = (checkmark.dataset.status === "Active" || checkmark.dataset.status === "On");
    }

    // Get the current battery level from the display
    const batteryText = tileElement.querySelector('.battery-percentage').textContent;
    const currentBattery = parseInt(batteryText); // Will be NaN if text is '--%'

    // A device is "On" (green) only if it's Active AND its battery is known AND has power.
    if (isActive && !isNaN(currentBattery) && currentBattery > 0) {
        checkmark.style.backgroundColor = "#4caf50"; // Green
    } else {
        checkmark.style.backgroundColor = "#ff0000"; // Red
    }
}
// to open sidebar
function toggleSidebar(){
    const sidebar = document.querySelector('.sidebar');
    const mainContent = document.querySelector('.main-content');
    sidebar.classList.toggle('open');
    mainContent.classList.toggle('shift');
}