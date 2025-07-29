let volumeSocket;
let statusSocket;
let batterySocket;

// --- STATE MANAGEMENT UPGRADE ---
const roomStates = {}; // Central object to hold the last known state for each room.

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
    // --- PRODUCTION UPGRADE: Use secure WebSockets (wss) if the page is loaded over https ---
    // This prevents mixed-content errors in a production environment with SSL.
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const url = `${protocol}//${window.location.host}${path}?token=${authToken}`;
    return new WebSocket(url);
}

function connectWebSocket(path, onMessageCallback) {
    const socket = createAuthenticatedSocket(path);
    if (!socket) return;

    socket.onopen = () => {
        console.log(`WebSocket connection established for ${path}`);
    };

    socket.onmessage = onMessageCallback;

    socket.onclose = () => {
        console.log(`WebSocket for ${path} closed. Reconnecting in 5 seconds...`);
        setTimeout(() => connectWebSocket(path, onMessageCallback), 5000);
    };

    socket.onerror = (error) => console.error(`WebSocket error for ${path}:`, error);
    return socket;
}

function connectBatteryWebSocket() {
    const onMessage = (event) => {
        try {
            const data = JSON.parse(event.data);
            if (data.room && data.percentage !== undefined) {
                // Update the central state and then update the entire tile UI.
                if (!roomStates[data.room]) roomStates[data.room] = {};
                roomStates[data.room].battery = data.percentage;
                updateTileUI(data.room);
            }
        } catch (e) {
            console.error("Error parsing battery message:", e);
        }
    };
    batterySocket = connectWebSocket('/ws/battery', onMessage);
}

function connectStatusWebSocket() {
    const onMessage = (event) => {
        const data = JSON.parse(event.data);
        const roomId = data.room;
        const newStatus = data.status;

        if (!roomId || !newStatus) return;

        if (!roomStates[roomId]) roomStates[roomId] = {};
        roomStates[roomId].status = newStatus;

        // --- REALISM UPGRADE: Clear battery on disconnect ---
        // If the device is disconnected, its battery level is now unknown.
        // This ensures the UI updates immediately to '--%'.
        if (newStatus === 'Disconnected') {
            roomStates[roomId].battery = undefined;
        }

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
    };
    statusSocket = connectWebSocket('/ws/status', onMessage);
}

function connectVolumeWebSocket() {
    const onMessage = (event) => {
        // Handle volume messages from the server if needed
    };
    volumeSocket = connectWebSocket('/ws/volume', onMessage);
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
    microphone: null, // This will be the MediaStreamSource
    mediaStream: null,
    audioWorkletNode: null,
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
        if (this.audioContext) return; // Already active
        try {
            // Request a 16kHz mono audio stream to match the server's processing pipeline.
            this.mediaStream = await navigator.mediaDevices.getUserMedia({ 
                audio: { 
                    channelCount: 1,
                    sampleRate: 16000//,
                    //echoCancellation: true // Enable the browser's built-in AEC
                } 
            });
            this.audioContext = new (window.AudioContext || window.webkitAudioContext)({
                sampleRate: 16000 // Ensure context sample rate matches
            });
            this.microphone = this.audioContext.createMediaStreamSource(this.mediaStream);
            
            // Load our custom audio processor worklet.
            await this.audioContext.audioWorklet.addModule('/static/js/audio-processor.js');
            this.audioWorkletNode = new AudioWorkletNode(this.audioContext, 'audio-processor');

            // Connect the microphone source to our worklet.
            this.microphone.connect(this.audioWorkletNode);

            // Connect the worklet to the destination to keep it running, even though it produces no sound.
            this.audioWorkletNode.connect(this.audioContext.destination);

            // Listen for messages (raw audio data) from the worklet.
            this.audioWorkletNode.port.onmessage = (event) => {
                // event.data is an ArrayBuffer containing the Int16 PCM data.
                // Forward this data to all active room sockets.
                Object.values(this.activeRoomSockets).forEach(ws => {
                    if (ws.readyState === WebSocket.OPEN) {
                        ws.send(event.data);
                    }
                });
            };
        } catch (error) {
            console.error("Error activating microphone:", error);
            alert('Could not access microphone. Please ensure you have granted permission.');
            this.deactivateMicrophone(); // Clean up on failure
        }
    },

    deactivateMicrophone() {
        // --- FIX: Gracefully tell server to sleep active rooms on unload ---
        // For every room that was active, send a "Sleep" command. This prevents
        // the state from being "stuck" on active if the user reloads the page.
        Object.keys(this.activeRoomSockets).forEach(roomId => {
            if (statusSocket && statusSocket.readyState === WebSocket.OPEN) {
                statusSocket.send(JSON.stringify({ room: roomId, status: "Sleep" }));
            }
        });
        if (this.audioWorkletNode) {
            this.audioWorkletNode.port.onmessage = null;
            this.audioWorkletNode.port.close();
            this.audioWorkletNode.disconnect();
            this.audioWorkletNode = null;
        }
        if (this.microphone) this.microphone.disconnect();
        if (this.mediaStream) this.mediaStream.getTracks().forEach(track => track.stop());
        if (this.audioContext) this.audioContext.close();
        this.audioContext = this.microphone = this.mediaStream = null;
        // The audio sockets are now closed after the sleep command is sent.
        Object.values(this.activeRoomSockets).forEach(ws => {
            if (ws.readyState === WebSocket.OPEN) ws.close();
        });
        this.activeRoomSockets = {};
    }
};

// --- ROBUSTNESS UPGRADE: Ensure state is cleaned up when the page is closed or reloaded ---
window.addEventListener('beforeunload', () => {
    // This is the only critical part: tell the server to stop any active streams
    // that this browser tab was controlling. This function now sends the "Sleep" commands.
    audioManager.deactivateMicrophone();

    // The rest is just cleanup, the browser will close them anyway.
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
            }
            // After setting individual sliders, update the master slider
            updateMasterSliderState();
        })
        .catch(error => {
            console.error('Error fetching initial room states:', error);
            // --- UI/UX UPGRADE: Notify user of connection issue ---
            // Instead of just logging to console, provide user feedback.
            alert("Could not load initial device states. The server may be unavailable. The page will try to reconnect automatically.");
        });
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
        masterVolumeSlider.classList.remove('indeterminate');
    } else {
        // If room volumes are not all the same, show the master slider in a mixed state.
        masterVolumeSlider.classList.add('indeterminate');
    }
}