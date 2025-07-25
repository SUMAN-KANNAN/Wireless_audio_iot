let volumeSocket;
let statusSocket;
let batterySocket;

// --- STATE MANAGEMENT UPGRADE ---
const roomStates = {}; // Central object to hold the last known state for each room.
const deviceTimeouts = {}; // Holds timeout IDs to detect disconnected devices.

function updateBatteryDisplay(roomId, percentage) {
    const CRITICAL_LEVEL = 20;
    const WARNING_LEVEL = 50;
    const percentageElement = document.querySelector(`#${roomId} .battery-percentage`);
    const levelElement = document.querySelector(`#${roomId} .battery-level`);

    if (percentageElement && levelElement) {
        // Handle null or undefined percentage, which can happen on initial load
        if (percentage === null || typeof percentage === 'undefined') {
            percentageElement.textContent = `--%`;
            levelElement.style.width = `0%`; // Show an empty bar for unknown/disconnected state
            levelElement.style.backgroundColor = '#f0f0f0'; // Match the empty bar background
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
}

function resetDeviceTimeout(roomId) {
    if (deviceTimeouts[roomId]) {
        clearTimeout(deviceTimeouts[roomId]);
    }
    // Set a timeout for 90 seconds. If it fires, the device is considered disconnected.
    deviceTimeouts[roomId] = setTimeout(() => {
        console.warn(`No signal from ${roomId} for 90 seconds. Marking as disconnected.`);
        if (roomStates[roomId]) {
            roomStates[roomId].status = 'Disconnected';
            // Clear battery state on disconnect to ensure UI updates correctly
            delete roomStates[roomId].battery;
        }
        updateTileUI(roomId); // Update the UI to reflect the disconnected state.
    }, 90000);
}

function updateTileUI(roomId) {
    const tile = document.getElementById(roomId);
    if (!tile) return;

    const checkmark = tile.querySelector('.checkmark');
    const toggle = tile.querySelector('.mic-toggle');

    const state = roomStates[roomId] || {};
    const status = state.status;
    const battery = state.battery;

    // First, update the battery bar display, as it's independent of status color.
    updateBatteryDisplay(roomId, battery);

    // A device is considered connected if we have a valid status and battery level.
    const isConnected = status && status !== 'Disconnected' && typeof battery !== 'undefined';

    if (!isConnected) {
        // RED STATE: Disconnected or Error
        checkmark.style.backgroundColor = '#ff0000'; // Red
        toggle.disabled = true;
        // If the device just disconnected, ensure its toggle is programmatically turned off.
        if (toggle.checked) {
            toggle.checked = false;
            // Dispatch a change event to ensure the audioManager cleans up the connection.
            toggle.dispatchEvent(new Event('change'));
        }
    } else {
        // Device is connected, so enable the toggle.
        toggle.disabled = false;
        if (status === 'Active') {
            // GREEN STATE: Connected and Active
            checkmark.style.backgroundColor = '#4caf50'; // Green
        } else { // status === 'Sleep'
            // ORANGE STATE: Connected and Idle
            checkmark.style.backgroundColor = '#ffbb33'; // Orange
        }
    }
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
                // Update the central state and then update the entire tile UI.
                if (!roomStates[data.room]) roomStates[data.room] = {};
                roomStates[data.room].battery = data.percentage;
                updateTileUI(data.room);
                resetDeviceTimeout(data.room);
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

        if (!roomStates[roomId]) roomStates[roomId] = {};
        roomStates[roomId].status = newStatus;

        // Sync the toggle's visual state with the reported device status.
        // This ensures the UI is accurate if a status changes from the server-side.
        const toggle = document.querySelector(`#${roomId} .mic-toggle`);
        if (toggle) {
            const shouldBeChecked = (newStatus === 'Active');
            if (toggle.checked !== shouldBeChecked) {
                toggle.checked = shouldBeChecked;
            }
        }

        updateTileUI(roomId);
        resetDeviceTimeout(roomId);
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

    async toggleMic(roomId, isTurningOn) {
        if (isTurningOn) {
            // Turning ON
            if (Object.keys(this.activeRoomSockets).length === 0) {
                await this.activateMicrophone();
            }
            const ws = createAuthenticatedSocket('/ws/audio');
            ws.onopen = () => {
                // Identify this browser tab as the audio source for a specific room
                ws.send(JSON.stringify({ type: 'room_identification', roomId, client_type: 'browser' }));
            };
            ws.onerror = (e) => { console.error(`Audio WS error for ${roomId}:`, e); };
            ws.onclose = () => { console.log(`Audio WS closed for ${roomId}`); };
            this.activeRoomSockets[roomId] = ws;

            // Inform the server that this device is now active
            if (statusSocket && statusSocket.readyState === WebSocket.OPEN) {
                statusSocket.send(JSON.stringify({ room: roomId, status: "Active" }));
            }
        } else {
            // Turning OFF
            if (this.activeRoomSockets[roomId]) { // Close the specific WebSocket for this room
                this.activeRoomSockets[roomId].close();
                delete this.activeRoomSockets[roomId];
            }
            if (Object.keys(this.activeRoomSockets).length === 0) {
                this.deactivateMicrophone();
            }
            if (statusSocket && statusSocket.readyState === WebSocket.OPEN) {
                // Inform the server that this device is now in sleep mode
                statusSocket.send(JSON.stringify({ room: roomId, status: "Sleep" }));
            }
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
    // Send a single "Sleep" command to the server, which will broadcast it.
    // This is the most efficient way to update all devices and other connected clients.
    if (statusSocket && statusSocket.readyState === WebSocket.OPEN) {
        statusSocket.send(JSON.stringify({ room: "all", status: "Sleep" }));
    }

    // On the UI, immediately turn off all toggles that are currently on.
    document.querySelectorAll('.mic-toggle').forEach(toggle => {
        if (toggle.checked) {
            toggle.checked = false;
            // Manually dispatch the change event to trigger all associated logic
            // (e.g., stopping the audio stream for that specific room).
            toggle.dispatchEvent(new Event('change'));
        }
    });
}

function unmuteAll() {
    // Send a single "Active" command to the server to be broadcast to all devices.
    if (statusSocket && statusSocket.readyState === WebSocket.OPEN) {
        statusSocket.send(JSON.stringify({ room: "all", status: "Active" }));
    }

    // --- LOGIC UPGRADE: Only unmute devices that are actually connected ---
    // On the UI, only turn on toggles for devices that are not in a 'Red' state.
    document.querySelectorAll('.mic-toggle').forEach(toggle => {
        const tile = toggle.closest('.tile');
        if (!tile) return;
        const roomId = tile.id;

        const state = roomStates[roomId] || {};
        const isConnected = state.status && state.status !== 'Disconnected' && typeof state.battery !== 'undefined';

        // If the device is connected and its toggle is off, turn it on.
        if (isConnected && !toggle.checked) {
            toggle.checked = true;
            toggle.dispatchEvent(new Event('change'));
        }
    });
}

document.querySelectorAll('.mic-toggle').forEach(toggle => {
    toggle.addEventListener('change', (event) => {
        const tile = event.target.closest('.tile');
        if (!tile) return;
        const roomId = tile.id;
        const isChecked = event.target.checked;

        // --- OPTIMISTIC UI UPDATE ---
        // Immediately update the UI for a responsive feel, without waiting for the server.
        const newStatus = isChecked ? "Active" : "Sleep";
        if (!roomStates[roomId]) roomStates[roomId] = {};
        roomStates[roomId].status = newStatus;
        updateTileUI(roomId);

        audioManager.toggleMic(roomId, isChecked);
        updateListeningCount();
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
                // Initialize the state object for the room.
                if (roomState.status) {
                    roomStates[roomId] = { status: roomState.status.status };
                }
                if (roomState.battery) {
                    if (!roomStates[roomId]) roomStates[roomId] = {};
                    roomStates[roomId].battery = roomState.battery.percentage;
                }
                if (roomState.volume) {
                    const volumeSlider = document.getElementById(`volume${roomId.charAt(0).toUpperCase() + roomId.slice(1)}`);
                    if (volumeSlider) volumeSlider.value = roomState.volume.volume;
                }
                // Now update the entire tile's UI based on the loaded state.
                updateTileUI(roomId);
                // If the device was connected, start its disconnect timer.
                if (roomStates[roomId] && roomStates[roomId].status !== 'Disconnected') {
                    resetDeviceTimeout(roomId);
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

    // --- ROBUSTNESS UPGRADE: Make mic icon click handler more reliable ---
    // This ensures that clicking the mic icon correctly toggles the switch.
    document.querySelectorAll('.mic').forEach(micIcon => {
        micIcon.addEventListener('click', (event) => {
            const tile = event.target.closest('.tile');
            if (!tile) return;
            const roomId = tile.id;

            // --- LOGIC UPGRADE: Check status before allowing click ---
            // A user should not be able to activate a disconnected (Red) device.
            const state = roomStates[roomId] || {};
            const isConnected = state.status && state.status !== 'Disconnected' && typeof state.battery !== 'undefined';

            if (!isConnected) {
                console.log(`Action blocked: Device ${roomId} is disconnected.`);
                return; // Do nothing if the device is not connected.
            }

            const switchElement = tile.querySelector('.mic-toggle');
            if (switchElement) {
                // Programmatically clicking the hidden checkbox is the cleanest way
                // to trigger its 'change' event and all associated logic.
                switchElement.click();
            }
        });
    });

    // --- BUG FIX: Make selector more specific to avoid adding this listener to the master slider ---
    // Add event listeners for individual room volume sliders only.
    // This prevents the master slider from fighting with itself when all room volumes are the same.
    document.querySelectorAll('.volume-slider[data-room]').forEach(slider => {
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
