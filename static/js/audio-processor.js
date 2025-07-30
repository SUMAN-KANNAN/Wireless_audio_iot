/**
 * This class runs in a separate, high-priority thread to capture raw audio
 * data without blocking the main UI.
 */
class AudioProcessor extends AudioWorkletProcessor {
    constructor() {

        super();
    }

    // This method is called by the browser for every 128 audio frames.
    process(inputs, outputs, parameters) {
        // Get the raw audio data from the first channel.
        const channelData = inputs[0][0];

        if (!channelData) {
            return true; // Keep the processor running.
        }

        // Convert the audio data from Float32 (-1.0 to 1.0) to Int16 (-32767 to 32767).
        const pcmData = new Int16Array(channelData.length);
        for (let i = 0; i < channelData.length; i++) {
            pcmData[i] = Math.max(-1, Math.min(1, channelData[i])) * 32767;
        }


        // Send the raw Int16 audio data back to the main JavaScript thread.
        this.port.postMessage(pcmData.buffer, [pcmData.buffer]);
        return true;
    }
}

registerProcessor('audio-processor', AudioProcessor);