import numpy as np
import pyworld as pw
import soundfile as sf
from scipy.ndimage import uniform_filter1d

NOTE_NAMES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]

SCALES = {
    "chromatic": [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11],
    "major": [0, 2, 4, 5, 7, 9, 11],
    "minor": [0, 2, 3, 5, 7, 8, 10],
    "dorian": [0, 2, 3, 5, 7, 9, 10],
    "mixolydian": [0, 2, 4, 5, 7, 9, 10],
    "pentatonic_major": [0, 2, 4, 7, 9],
    "pentatonic_minor": [0, 3, 5, 7, 10],
}

def hz_to_midi(hz):
    valid = hz > 0
    midi = np.zeros_like(hz)
    midi[valid] = 69.0 + 12.0 * np.log2(hz[valid] / 440.0)
    return midi

def midi_to_hz(midi):
    valid = midi > 0
    hz = np.zeros_like(midi)
    hz[valid] = 440.0 * (2.0 ** ((midi[valid] - 69.0) / 12.0))
    return hz

def get_scale_notes(root_name="C", scale_type="major"):
    root_idx = NOTE_NAMES.index(root_name.upper()) if root_name.upper() in NOTE_NAMES else 0
    scale_intervals = SCALES.get(scale_type.lower(), SCALES["chromatic"])
    allowed_pitch_classes = [(root_idx + interval) % 12 for interval in scale_intervals]
    return allowed_pitch_classes

def snap_to_scale(midi_val, allowed_pitch_classes):
    """Snaps continuous midi note to the nearest note in the allowed pitch classes."""
    octave = np.floor(midi_val / 12.0)
    pc = midi_val % 12.0
    
    # Calculate distance to each allowed pitch class
    best_target = None
    min_dist = 999.0
    for apc in allowed_pitch_classes:
        # Distance considering wrapping around 12
        dist = np.abs(pc - apc)
        if dist > 6:
            dist = 12 - dist
        if dist < min_dist:
            min_dist = dist
            # Directional offset
            diff = (apc - pc)
            if diff > 6: diff -= 12
            if diff < -6: diff += 12
            best_target = midi_val + diff
            
    return best_target

def tune_vocal(
    audio_path,
    output_path,
    root="C",
    scale="major",
    strength=0.85,
    retune_speed=0.5, # 0.0 = ultra fast/robotic, 1.0 = super slow/natural
    preserve_vibrato=True,
    vibrato_amount=1.0
):
    """
    Studio-grade vocal pitch corrector preserving natural timbre, consonants, and vibrato.
    """
    x, fs = sf.read(audio_path)
    if x.ndim > 1:
        # Process first channel for pitch or mono mix
        mono_x = np.mean(x, axis=1)
    else:
        mono_x = x
        
    mono_x = mono_x.astype(np.float64)
    
    # 1. WORLD Analysis
    # Frame period = 5.0ms for high temporal resolution
    frame_period = 5.0
    _f0, timeaxis = pw.harvest(mono_x, fs, f0_floor=65.0, f0_ceil=700.0, frame_period=frame_period)
    f0 = pw.stonemask(mono_x, _f0, timeaxis, fs)
    sp = pw.cheaptrick(mono_x, f0, timeaxis, fs)
    ap = pw.d4c(mono_x, f0, timeaxis, fs)
    
    # 2. Musical Scale Definition
    allowed_pcs = get_scale_notes(root, scale)
    
    # 3. Voiced frames analysis
    voiced_mask = f0 > 0
    if not np.any(voiced_mask):
        # Pure silence or noise, write back unchanged
        sf.write(output_path, x, fs)
        return
        
    midi = hz_to_midi(f0)
    corrected_midi = np.copy(midi)
    
    # Separate contiguous voiced islands (notes)
    # Find segments where singer is singing
    voiced_indices = np.where(voiced_mask)[0]
    segments = np.split(voiced_indices, np.where(np.diff(voiced_indices) > 1)[0] + 1)
    
    # Window size for smoothing / trend extraction (in frames)
    # 5ms * 40 = 200ms window (captures note center, isolates 5-7Hz vibrato)
    window_frames = max(3, int(0.200 / (frame_period / 1000.0)))
    
    for seg in segments:
        if len(seg) < 4:
            continue
            
        seg_midi = midi[seg]
        
        if preserve_vibrato and len(seg) >= window_frames:
            # Low-pass filter to get note trend
            trend = uniform_filter1d(seg_midi, size=window_frames, mode='nearest')
            vibrato = seg_midi - trend
        else:
            trend = seg_midi
            vibrato = np.zeros_like(seg_midi)
            
        # Target note for trend
        target_notes = np.zeros_like(trend)
        for i, val in enumerate(trend):
            target_notes[i] = snap_to_scale(val, allowed_pcs)
            
        # Smooth target transition according to retune_speed
        # Retune speed: higher speed = smoother transitions
        smooth_window = max(1, int((0.05 + 0.20 * retune_speed) / (frame_period / 1000.0)))
        smoothed_target = uniform_filter1d(target_notes, size=smooth_window, mode='nearest')
        
        # Apply correction strength
        tuned_trend = trend + (smoothed_target - trend) * strength
        
        # Re-apply natural vibrato
        final_seg_midi = tuned_trend + (vibrato * vibrato_amount)
        corrected_midi[seg] = final_seg_midi
        
    # 4. Convert back to Hz
    corrected_f0 = midi_to_hz(corrected_midi)
    
    # 5. WORLD Synthesis (Perfect Formant & Consonant Preservation)
    y = pw.synthesize(corrected_f0, sp, ap, fs, frame_period=frame_period)
    
    # Match length
    if len(y) > len(mono_x):
        y = y[:len(mono_x)]
    elif len(y) < len(mono_x):
        y = np.pad(y, (0, len(mono_x) - len(y)))
        
    if x.ndim > 1:
        # Re-apply to stereo if original was stereo
        out_audio = np.stack([y, y], axis=1)
    else:
        out_audio = y
        
    sf.write(output_path, out_audio, fs)
    print(f"Vocal tuned successfully -> {output_path}")

if __name__ == "__main__":
    # Test generation with a synthetic sung note with slight pitch drift & vibrato
    sr = 44100
    t = np.linspace(0, 3.0, int(sr * 3.0), endpoint=False)
    # Note around A3 (220Hz), but drifting slightly flat (~215Hz) with 5.5Hz vibrato
    f_drift = 215.0 + 3.0 * np.sin(2 * np.pi * 5.5 * t)
    phase = 2 * np.pi * np.cumsum(f_drift) / sr
    # Add harmonics to simulate voice
    test_voice = 0.6 * np.sin(phase) + 0.3 * np.sin(2 * phase) + 0.15 * np.sin(3 * phase)
    # Envelope
    env = np.ones_like(t)
    env[:2000] = np.linspace(0, 1, 2000)
    env[-2000:] = np.linspace(1, 0, 2000)
    test_voice *= env
    
    sf.write("test_sung_voice.wav", test_voice, sr)
    print("Created test sung voice: test_sung_voice.wav")
    
    tune_vocal("test_sung_voice.wav", "test_tuned_voice.wav", root="A", scale="minor", strength=0.9, preserve_vibrato=True)
