import numpy as np
import logging
from scipy.signal import butter, lfilter, medfilt

# --- Configuration Constants ---
SAMPLE_RATE = 16000  # Must match the frontend's requested sample rate
# --- INTELLIGENCE UPGRADE: Re-tuned for Audio Presence ---
# The previous settings were too aggressive. This is a more robust configuration.
# We apply gain *before* the noise gate, so the threshold is more effective.
GAIN = 4.0
NOISE_GATE_THRESHOLD = 350  # This threshold is now applied to the *amplified* signal.
HIGH_PASS_CUTOFF = 100  # Hz
# A median filter is better at removing noise without muffling speech.
# This value must be an odd integer.
MEDIAN_FILTER_SIZE = 3

def high_pass_filter(audio, cutoff=HIGH_PASS_CUTOFF, fs=SAMPLE_RATE, order=5):
    """Applies a high-pass filter to the audio data."""
    nyq = 0.5 * fs
    norm_cutoff = cutoff / nyq
    b, a = butter(order, norm_cutoff, btype='high', analog=False)

    return lfilter(b, a, audio)

def apply_noise_gate(audio, threshold=NOISE_GATE_THRESHOLD):
    """Applies a simple noise gate."""
    return np.where(np.abs(audio) < threshold, 0, audio)

# --- INTELLIGENCE UPGRADE: Replaced moving average with a median filter. ---
# A median filter is more effective at removing impulse noise (clicks/pops)
# without blurring the audio as much as a simple average.
def smooth_audio(audio, window_size=MEDIAN_FILTER_SIZE):
    """Applies a median filter to smooth the audio."""
    if len(audio) < window_size:
        return audio
    return medfilt(audio, kernel_size=window_size)

def process_audio_chunk(audio_bytes: bytes) -> bytes:
    """
    Takes a chunk of raw PCM audio bytes, applies a series of filters,
    and returns the processed audio as bytes.
    """
    try:
        # --- ROBUSTNESS UPGRADE: Ensure the processing pipeline is resilient ---
        # This try...except block prevents a single corrupted audio chunk from
        # crashing the WebSocket handler.
        audio_int16 = np.frombuffer(audio_bytes, dtype=np.int16)
        audio_float = audio_int16.astype(np.float32)

        # --- INTELLIGENCE UPGRADE: Re-ordered pipeline for better results ---
        # 1. High-pass to remove low-frequency hum before amplification.
        # 2. Gain to boost the voice signal.
        # 3. Noise gate to remove background noise from the amplified signal.
        # 4. Median filter to smooth out any remaining clicks or pops.
        audio_float = high_pass_filter(audio_float)
        audio_float *= GAIN
        audio_float = apply_noise_gate(audio_float)
        audio_float = smooth_audio(audio_float)
        
        processed_audio_int16 = np.clip(audio_float, -32767, 32767).astype(np.int16)
        return processed_audio_int16.tobytes()
    except Exception as e:
        logging.error(f"Error processing audio chunk: {e}. Returning original chunk.")
        return audio_bytes
