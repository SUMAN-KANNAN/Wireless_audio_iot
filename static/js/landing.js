let audioContext;
let microphone;
let mediaRecorder;
let mediaStream;
let audioChunks = [];
let isMicActive = false;
let audioSocket;
let volumeSocket;
let statusSocket;
let batterySocket;
let activeRoomSockets = {}; // { roomId: WebSocket }

const defaultBattery = {
    conferenceRoom: 100,
    adminRoom: 80,
    classRoom: 90
};

function initBatteryDisplay() {
    for (const room in defaultBattery) {
        updateBatteryDisplay(room, defaultBattery[room]);
    }
}

function updateBatteryDisplay(roomId, percentage) {
    const percentageElement = document.querySelector(`#${roomId} .battery-percentage`);
    const levelElement = document.querySelector(`#${roomId} .battery-level`);

    if (percentageElement && levelElement) {
        percentageElement.textContent = `${percentage}%`;
        levelElement.style.width = `${percentage}%`;

        if (percentage < 20) {
            levelElement.style.backgroundColor = '#ff4444'; // Red
        } else if (percentage < 50) {
            levelElement.style.backgroundColor = '#ffbb33'; // Yellow
        } else {
            levelElement.style.backgroundColor = '#00C851'; // Green
        }
    }
}

function connectBatteryWebSocket() {
    batterySocket = new WebSocket(`ws://${window.location.host}/ws/battery`);

    batterySocket.onmessage = (event) => {
        try {
            const data = JSON.parse(event.data);
            if (data.room && data.percentage !== undefined) {
                updateBatteryDisplay(data.room, data.percentage);
            } else if (typeof data === 'object') {
                for (const room in data) {
                    updateBatteryDisplay(room, data[room]);
                }
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
    statusSocket = new WebSocket('ws://' + window.location.host + '/ws/status');

    statusSocket.onopen = () => {
        console.log("Status WebSocket connection established");
    };

    statusSocket.onmessage = function(event) {
        const data = JSON.parse(event.data);
        const room = data.room;
        const status = data.status;

        // Map room to toggle id
        let switchId = '';
        if (room === 'conferenceRoom') switchId = 'switchConference';
        else if (room === 'adminRoom') switchId = 'switchAdmin';
        else if (room === 'classRoom') switchId = 'switchClass';

        const toggle = document.getElementById(switchId);
        const tileElement = document.getElementById(room);
        const checkmark = tileElement ? tileElement.querySelector('.checkmark') : null;

        if (toggle && checkmark) {
            if (toggle.checked) {
                // If toggle is ON, always show green
                checkmark.style.backgroundColor = "#4caf50";
            } else {
                // If toggle is OFF, follow the server status
                checkmark.style.backgroundColor = (status === "Active" || status === "On") ? "#4caf50" : "#ff0000";
            }
        }
    };

    statusSocket.onclose = () => {
        setTimeout(connectStatusWebSocket, 5000);
    };

    statusSocket.onerror = (error) => {
        console.error("Status WebSocket error:", error);
    };
}

function connectVolumeWebSocket() {
    volumeSocket = new WebSocket("ws://" + window.location.host + "/ws/volume");

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
    const conferenceVolume = document.getElementById("volumeConference").value;
    const adminVolume = document.getElementById("volumeAdmin").value;
    const classVolume = document.getElementById("volumeClass").value;

    const message = {
        type: "volume",
        data: {
            conferenceRoom: parseInt(conferenceVolume),
            adminRoom: parseInt(adminVolume),
            classRoom: parseInt(classVolume)
        }
    };

    if (volumeSocket && volumeSocket.readyState === WebSocket.OPEN) {
        volumeSocket.send(JSON.stringify(message));
    }
}

async function toggleMic(roomId) {
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
        if (Object.keys(activeRoomSockets).length === 0) {
            await activateMicrophone();
        }
        const ws = new WebSocket(`ws://${window.location.host}/ws/audio`);
        ws.onopen = () => {
            ws.send(JSON.stringify({ type: 'room_identification', roomId }));
        };
        ws.onerror = (e) => { console.error(`Audio WS error for ${roomId}:`, e); };
        ws.onclose = () => { console.log(`Audio WS closed for ${roomId}`); };
        activeRoomSockets[roomId] = ws;

        if (statusSocket && statusSocket.readyState === WebSocket.OPEN) {
            statusSocket.send(JSON.stringify({ room: roomId, status: "Active" }));
        }
        setStatusDot(roomId, "Active");
    } else {
        // Turning OFF
        if (activeRoomSockets[roomId]) {
            activeRoomSockets[roomId].close();
            delete activeRoomSockets[roomId];
        }
        if (Object.keys(activeRoomSockets).length === 0) {
            deactivateMicrophone();
        }
        if (statusSocket && statusSocket.readyState === WebSocket.OPEN) {
            statusSocket.send(JSON.stringify({ room: roomId, status: "Sleep" }));
        }
        setStatusDot(roomId, "Sleep");
    }
}

async function activateMicrophone() {
    if (isMicActive) return;
    try {
        mediaStream = await navigator.mediaDevices.getUserMedia({ audio: true });
        audioContext = new (window.AudioContext || window.webkitAudioContext)();
        microphone = audioContext.createMediaStreamSource(mediaStream);

        mediaRecorder = new MediaRecorder(mediaStream);
        audioChunks = [];

        mediaRecorder.ondataavailable = (event) => {
            if (event.data.size > 0) {
                Object.values(activeRoomSockets).forEach(ws => {
                    if (ws.readyState === WebSocket.OPEN) {
                        ws.send(event.data);
                    }
                });
            }
        };

        mediaRecorder.start(100);
        isMicActive = true;
    } catch (error) {
        alert('Could not access microphone. Please ensure you have granted permission.');
        isMicActive = false;
    }
}

function deactivateMicrophone() {
    if (mediaRecorder && mediaRecorder.state !== "inactive") {
        mediaRecorder.stop();
    }
    if (mediaStream) {
        mediaStream.getTracks().forEach(track => track.stop());
        mediaStream = null;
    }
    isMicActive = false;
    audioContext = null;
    microphone = null;
    audioChunks = [];
    Object.values(activeRoomSockets).forEach(ws => {
        if (ws.readyState === WebSocket.OPEN) ws.close();
    });
    activeRoomSockets = {};
}

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
    deactivateMicrophone();
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
    deactivateMicrophone();
    updateListeningCount();
}

function unmuteAll() {
    const switches = document.querySelectorAll('.mic-toggle');
    deactivateMicrophone();
    switches.forEach(switchElement => {
        switchElement.checked = true;
        const switchId = switchElement.id;
        let roomId = '';
        if (switchId.includes('Conference')) roomId = 'conferenceRoom';
        else if (switchId.includes('Admin')) roomId = 'adminRoom';
        else if (switchId.includes('Class')) roomId = 'classRoom';

        if (roomId && statusSocket && statusSocket.readyState === WebSocket.OPEN) {
            const statusMessage = { room: roomId, status: "Active" };
            statusSocket.send(JSON.stringify(statusMessage));
        }
    });
    updateListeningCount();
}

document.querySelectorAll('.mic-toggle').forEach(toggle => {
    toggle.addEventListener('change', (event) => {
        const switchId = event.target.id;
        let roomId = '';
        if (switchId.includes('Conference')) roomId = 'conferenceRoom';
        else if (switchId.includes('Admin')) roomId = 'adminRoom';
        else if (switchId.includes('Class')) roomId = 'classRoom';

        toggleMic(roomId);
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
    deactivateMicrophone();
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

document.getElementById("volumeConference").addEventListener("change", sendVolumeUpdate);
document.getElementById("volumeAdmin").addEventListener("change", sendVolumeUpdate);
document.getElementById("volumeClass").addEventListener("change", sendVolumeUpdate);

document.addEventListener('DOMContentLoaded', () => {
    initBatteryDisplay();
    connectStatusWebSocket();
    connectVolumeWebSocket();
    connectBatteryWebSocket();
    updateListeningCount();

    document.querySelectorAll('.mic').forEach(micIcon => {
        micIcon.addEventListener('click', (event) => {
            const roomId = event.target.closest('.tile').id;
            const switchId = `switch${roomId.replace('Room', '')}`;
            const switchElement = document.getElementById(switchId);
            if (switchElement) {
                switchElement.checked = !switchElement.checked;
                const changeEvent = new Event('change');
                switchElement.dispatchEvent(changeEvent);
            }
        });
    });
});

function checkAndDeactivateMicIfNoneActive() {
    const toggles = document.querySelectorAll('.mic-toggle');
    const anyActive = Array.from(toggles).some(toggle => toggle.checked);
    if (!anyActive) {
        deactivateMicrophone();
    }
}

function setStatusDot(roomId, status) {
    const tileElement = document.getElementById(roomId);
    if (tileElement) {
        const checkmark = tileElement.querySelector('.checkmark');
        if (checkmark) {
            checkmark.style.backgroundColor = (status === "Active") ? "#4caf50" : "#ff0000";
        }
    }
}
