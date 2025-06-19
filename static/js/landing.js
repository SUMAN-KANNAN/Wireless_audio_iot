function toggleMic(roomId) {
    let switchId = '';
    switch (roomId) {
        case 'conferenceRoom':
            switchId = 'switchConference';
            break;
        case 'adminRoom':
            switchId = 'switchAdmin';
            break;
        case 'classRoom':
            switchId = 'switchClass';
            break;
        default:
            return;
    }

    const switchElement = document.getElementById(switchId);
    if (switchElement) {
        switchElement.checked = !switchElement.checked;
        updateListeningCount(); 
    }
}

document.querySelectorAll('.mic-toggle').forEach(toggle => {
    toggle.addEventListener('change', updateListeningCount);
});

function updateListeningCount() {
    const toggles = document.querySelectorAll('.mic-toggle');
    let count = 0;
    toggles.forEach(toggle => {
        if (toggle.checked) count++;
    });
    document.getElementById('listeningCount').innerText = count;
}

function muteAll() {
    const switches = document.querySelectorAll('.mic-toggle');
    switches.forEach(switchElement => {
        switchElement.checked = false;
    });
    updateListeningCount(); 
}

function unmuteAll() {
    const switches = document.querySelectorAll('.mic-toggle');
    switches.forEach(switchElement => {
        switchElement.checked = true;
    });
    updateListeningCount(); 
}

function logout() {
    window.location.href = '/logout'; // Redirects to login page
}

function updateAllRoomVolume() {
    const volumeConference = document.getElementById('volumeConference').value;
    const volumeAdmin = document.getElementById('volumeAdmin').value;
    const volumeClass = document.getElementById('volumeClass').value;

    // Update the volume sliders for each room
    document.getElementById('volumeConference').value = volumeConference;
    document.getElementById('volumeAdmin').value = volumeAdmin;
    document.getElementById('volumeClass').value = volumeClass;
}

function toggleConference() {
    const switchConference = document.getElementById('switchConference');
    switchConference.checked = !switchConference.checked; // Toggle the switch state
    updateListeningCount(); // Call the function to update listening count
}

function toggleAdmin() {
    const switchAdmin = document.getElementById('switchAdmin');
    switchAdmin.checked = !switchAdmin.checked; // Toggle the switch state
    updateListeningCount(); // Call the function to update listening count
}

function toggleClass() {
    const switchClass = document.getElementById('switchClass');
    switchClass.checked = !switchClass.checked; // Toggle the switch state
    updateListeningCount(); // Call the function to update listening count
}



