// landing.js (Frontend JS for Mic + Volume + WebSocket)

let audioContext;
let microphone;
let mediaRecorder;
let mediaStream;
let audioChunks = [];
let isMicActive = false;
let socket;

async function toggleMic(roomId) {
    let switchId = '';
    switch (roomId) {
        case 'conferenceRoom': switchId = 'switchConference'; break;
        case 'adminRoom': switchId = 'switchAdmin'; break;
        case 'classRoom': switchId = 'switchClass'; break;
        default: return;
    }

    const switchElement = document.getElementById(switchId);
    if (switchElement) {
        switchElement.checked = !switchElement.checked;
        updateListeningCount();

        if (switchElement.checked) {
            await activateMicrophone(roomId);
        } else {
            deactivateMicrophone();
        }
    }
}

async function activateMicrophone(roomId) {
    if (isMicActive) return;

    try {
        socket = new WebSocket(`ws://${window.location.host}/ws/audio`);
        mediaStream = await navigator.mediaDevices.getUserMedia({ audio: true });
        audioContext = new (window.AudioContext || window.webkitAudioContext)();
        microphone = audioContext.createMediaStreamSource(mediaStream);

        mediaRecorder = new MediaRecorder(mediaStream);
        audioChunks = [];

        mediaRecorder.ondataavailable = (event) => {
            if (event.data.size > 0 && socket.readyState === WebSocket.OPEN) {
                const reader = new FileReader();
                reader.onloadend = function () {
                    const base64data = reader.result.split(',')[1];
                    socket.send(JSON.stringify({
                        hardware_id: `HW_${roomId.toUpperCase()}`,
                        room_id: roomId,
                        field: "audio",
                        value: base64data
                    }));
                };
                reader.readAsDataURL(event.data);
            }
        };

        mediaRecorder.start(100);
        isMicActive = true;
        console.log(`Microphone streaming started for ${roomId}`);

    } catch (error) {
        console.error('Error accessing microphone:', error);
        alert('Could not access microphone. Please ensure you have granted permission.');
    }
}

function deactivateMicrophone() {
    if (mediaRecorder && mediaRecorder.state !== 'inactive') {
        mediaRecorder.stop();
        mediaRecorder = null;
    }
    if (mediaStream) {
        mediaStream.getTracks().forEach(track => track.stop());
        mediaStream = null;
    }
    if (microphone) {
        microphone.disconnect();
        microphone = null;
    }
    if (audioContext && audioContext.state !== 'closed') {
        audioContext.close().then(() => console.log('AudioContext closed'));
        audioContext = null;
    }
    if (socket && socket.readyState !== WebSocket.CLOSED) {
        socket.close();
        socket = null;
    }
    isMicActive = false;
    console.log('Microphone completely deactivated');
}

window.addEventListener('beforeunload', () => {
    deactivateMicrophone();
});

function muteAll() {
    document.querySelectorAll('.mic-toggle').forEach(s => s.checked = false);
    deactivateMicrophone();
    updateListeningCount();
}

function unmuteAll() {
    document.querySelectorAll('.mic-toggle').forEach(s => s.checked = true);
    deactivateMicrophone();

    let firstRoomId = null;
    document.querySelectorAll('.mic-toggle').forEach(s => {
        if (!firstRoomId) {
            if (s.id.includes('Conference')) firstRoomId = 'conferenceRoom';
            else if (s.id.includes('Admin')) firstRoomId = 'adminRoom';
            else if (s.id.includes('Class')) firstRoomId = 'classRoom';
        }
    });

    if (firstRoomId) activateMicrophone(firstRoomId);
    updateListeningCount();
}

document.querySelectorAll('.mic-toggle').forEach(toggle => {
    toggle.addEventListener('change', updateListeningCount);
});

function updateListeningCount() {
    const count = [...document.querySelectorAll('.mic-toggle')].filter(t => t.checked).length;
    document.getElementById('listeningCount').innerText = count;
}

function logout() {
    deactivateMicrophone();
    window.location.href = '/logout';
}

// Volume WebSocket
let volumeSocket = new WebSocket(`ws://${window.location.host}/ws/volume`);

function sendVolumeUpdate() {
    const message = {
        type: "volume",
        data: [
            {
                hardware_id: "HW_CONFERENCEROOM_2001",
                room_id: "cfr_2001",
                field: "volume",
                name: "conferenceRoom",
                value: parseInt(document.getElementById("volumeConference").value)
            },
            {
                hardware_id: "HW_ADMINROOM_2002",
                room_id: "adr_2002",
                field: "volume",
                name: "adminRoom",
                value: parseInt(document.getElementById("volumeAdmin").value)
            },
            {
                hardware_id: "HW_CLASSROOM_2003",
                room_id: "clr_2003",
                field: "volume",
                name: "classRoom",
                value: parseInt(document.getElementById("volumeClass").value)
            }
        ]
    };

    if (volumeSocket.readyState === WebSocket.OPEN) {
        volumeSocket.send(JSON.stringify(message));
        console.log("🔊 Sent volume update:", message.data);
    }
}

document.getElementById("volumeConference").addEventListener("change", sendVolumeUpdate);
document.getElementById("volumeAdmin").addEventListener("change", sendVolumeUpdate);
document.getElementById("volumeClass").addEventListener("change", sendVolumeUpdate);

function toggleSidebar() {
    const sidebar = document.querySelector('.sidebar');
    const mainContent = document.querySelector('.main-content');
    sidebar.classList.toggle('open');
    mainContent.classList.toggle('shift');
}
