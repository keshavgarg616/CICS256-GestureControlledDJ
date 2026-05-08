#!/usr/bin/env python3
"""
Gesture-Controlled DJ — Laptop App
Reads structured serial messages from ESP32 Board A and triggers audio/state changes.

Enhancements:
  - Piano keys play real C4–B4 tones (synthesised if .wav missing)
  - Drum ultrasonic threshold reduced to 15 cm (was ~18 cm default)
  - Drums & piano overlay cleanly on top of any background soundtrack
  - POT 1 = Volume, POT 2 = LED brightness (sent back over serial)
  - PLAY_PAUSE button toggles background song
  - Gesture effects: LEFT/RIGHT = filter sweep, UP = pitch-rise stutter,
                     DOWN = reverse echo, CIRCLE = vinyl scratch spin,
                     WAVE = tremolo shimmer
"""

import argparse
import math
import os
import struct
import sys
import time
import wave
from typing import Optional

import pygame
import pygame.sndarray
import numpy as np

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

PIANO_NOTES   = ["C4", "D4", "E4", "F4", "G4", "A4", "B4"]
NOTE_FREQS    = {                        # equal-temperament Hz
    "C4": 261.63, "D4": 293.66, "E4": 329.63,
    "F4": 349.23, "G4": 392.00, "A4": 440.00, "B4": 493.88,
}

DRUM_SOUNDS = [
    "kick.wav", "snare.wav", "hihat.wav",
    "tom1.wav", "tom2.wav",  "clap.wav",  "crash.wav",
]

DRUM_TRIGGER_CM = 15          # ultrasonic distance threshold (cm)
SAMPLE_RATE     = 44100
CHANNELS        = 2

# ---------------------------------------------------------------------------
# App state
# ---------------------------------------------------------------------------

state = {
    "volume":        80,        # 0-127
    "led_brightness": 64,       # 0-127  (sent to ESP32)
    "playing":       False,
    "last_gesture":  None,
    "last_key":      None,
    "last_drum":     None,
    # effect state
    "lowpass":       False,
    "reverb":        0,
    "gesture_busy":  False,
}

# ---------------------------------------------------------------------------
# Audio setup
# ---------------------------------------------------------------------------

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
SOUNDS_DIR = os.path.join(SCRIPT_DIR, "sounds")

loaded_notes:  dict[str, pygame.mixer.Sound] = {}
loaded_drums:  dict[str, pygame.mixer.Sound] = {}
song_loaded  = False
song_started = False


# ── Synth helpers ────────────────────────────────────────────────────────────

def _sine_wave(freq: float, duration: float = 0.6,
               sample_rate: int = SAMPLE_RATE) -> np.ndarray:
    """Generate a simple sine-wave tone with a short fade-out envelope."""
    t     = np.linspace(0, duration, int(sample_rate * duration), endpoint=False)
    wave  = np.sin(2 * np.pi * freq * t).astype(np.float32)
    # mild ADSR: 5 ms attack, 20 ms decay, then linear release
    attack  = int(sample_rate * 0.005)
    decay   = int(sample_rate * 0.020)
    release = int(sample_rate * 0.15)
    env = np.ones(len(wave), dtype=np.float32)
    env[:attack]  = np.linspace(0, 1, attack)
    env[attack:attack+decay] = np.linspace(1, 0.7, decay)
    env[-release:] = np.linspace(0.7, 0, release)
    wave *= env
    stereo = np.column_stack([wave, wave])            # L + R
    return (stereo * 32767).astype(np.int16)


def _make_sound(arr: np.ndarray) -> pygame.mixer.Sound:
    """Wrap a numpy int16 stereo array as a pygame Sound."""
    sound = pygame.sndarray.make_sound(arr)
    return sound


def _synth_note(note_name: str) -> pygame.mixer.Sound:
    freq = NOTE_FREQS[note_name]
    return _make_sound(_sine_wave(freq))


def _synth_drum(index: int) -> pygame.mixer.Sound:
    """Very rough drum synthesis so the app works without .wav files."""
    sr = SAMPLE_RATE
    if index == 0:   # kick – pitch-dropping sine
        t    = np.linspace(0, 0.35, int(sr * 0.35), dtype=np.float32)
        freq = 150 * np.exp(-20 * t)
        arr  = np.sin(2 * np.pi * freq * t)
    elif index == 1:  # snare – sine + noise burst
        t    = np.linspace(0, 0.2, int(sr * 0.2), dtype=np.float32)
        arr  = 0.5 * np.sin(2 * np.pi * 180 * t) + 0.5 * np.random.randn(len(t)).astype(np.float32)
    elif index == 2:  # hi-hat – noise highpass approximation
        t    = np.linspace(0, 0.08, int(sr * 0.08), dtype=np.float32)
        arr  = np.random.randn(len(t)).astype(np.float32)
    elif index in (3, 4):  # toms
        freq = 100 if index == 3 else 70
        t    = np.linspace(0, 0.3, int(sr * 0.3), dtype=np.float32)
        arr  = np.sin(2 * np.pi * freq * np.exp(-8 * t) * t)
    elif index == 5:  # clap
        t    = np.linspace(0, 0.15, int(sr * 0.15), dtype=np.float32)
        arr  = np.random.randn(len(t)).astype(np.float32) * np.exp(-30 * t)
    else:             # crash – long noise fade
        t    = np.linspace(0, 0.8, int(sr * 0.8), dtype=np.float32)
        arr  = np.random.randn(len(t)).astype(np.float32)

    # envelope
    arr  = arr.astype(np.float32)
    fade = np.linspace(1.0, 0.0, len(arr), dtype=np.float32)
    arr *= fade
    arr  = np.clip(arr, -1.0, 1.0)
    stereo = np.column_stack([arr, arr])
    return _make_sound((stereo * 32767).astype(np.int16))


# ── Initialise ───────────────────────────────────────────────────────────────

def init_audio(song_path: Optional[str], verbose: bool) -> None:
    global song_loaded

    # Reserve plenty of channels so piano + drums + song never fight
    pygame.mixer.pre_init(SAMPLE_RATE, -16, CHANNELS, 512)
    pygame.mixer.init()
    pygame.mixer.set_num_channels(32)

    # Piano notes
    for i, note in enumerate(PIANO_NOTES):
        path = os.path.join(SOUNDS_DIR, "notes", f"{note}.wav")
        if os.path.isfile(path):
            loaded_notes[str(i + 1)] = pygame.mixer.Sound(path)
            if verbose:
                print(f"[audio] Loaded note {note} from {path}")
        else:
            loaded_notes[str(i + 1)] = _synth_note(note)
            if verbose:
                print(f"[audio] Synthesised note {note}")

    # Drum sounds
    for i, fname in enumerate(DRUM_SOUNDS):
        path = os.path.join(SOUNDS_DIR, "drums", fname)
        if os.path.isfile(path):
            loaded_drums[str(i + 1)] = pygame.mixer.Sound(path)
            if verbose:
                print(f"[audio] Loaded drum {fname} from {path}")
        else:
            loaded_drums[str(i + 1)] = _synth_drum(i)
            if verbose:
                print(f"[audio] Synthesised drum {fname}")

    # Background soundtrack  (channel 0 is reserved for music streaming)
    if song_path and os.path.isfile(song_path):
        try:
            pygame.mixer.music.load(song_path)
            song_loaded = True
            pygame.mixer.music.set_volume(state["volume"] / 127.0)
            print(f"[audio] Background song loaded: {song_path}")
        except Exception as e:
            print(f"[audio] Failed to load song: {e}")
    elif song_path:
        print(f"[audio] Song file not found: {song_path}")


# ---------------------------------------------------------------------------
# Playback helpers
# ---------------------------------------------------------------------------

def _note_volume() -> float:
    return state["volume"] / 127.0


def play_note(key_id: str) -> None:
    sound = loaded_notes.get(key_id)
    if sound:
        sound.set_volume(_note_volume())
        sound.play()
        idx  = int(key_id) - 1
        name = PIANO_NOTES[idx] if 0 <= idx < len(PIANO_NOTES) else key_id
        print(f"[audio] ♪  Note  {name}  ({NOTE_FREQS.get(name, '?'):.2f} Hz)")
    else:
        print(f"[warn]  No sound object for KEY {key_id}")


def play_drum(drum_id: str, distance_cm: float) -> None:
    """Play drum only if distance is within threshold."""
    if distance_cm > DRUM_TRIGGER_CM:
        print(f"[drum]  Drum {drum_id} skipped — {distance_cm:.1f} cm > {DRUM_TRIGGER_CM} cm")
        return
    sound = loaded_drums.get(drum_id)
    if sound:
        # Velocity: closer = louder (linear ramp from threshold down to 3 cm)
        velocity = max(0.2, 1.0 - (distance_cm - 3) / (DRUM_TRIGGER_CM - 3))
        sound.set_volume(_note_volume() * velocity)
        sound.play()
        idx  = int(drum_id) - 1
        name = DRUM_SOUNDS[idx] if 0 <= idx < len(DRUM_SOUNDS) else drum_id
        print(f"[audio] 🥁 Drum  {name}  @ {distance_cm:.1f} cm  vel={velocity:.2f}")
    else:
        print(f"[warn]  No sound object for DRUM {drum_id}")


def toggle_play_pause() -> None:
    global song_started
    state["playing"] = not state["playing"]
    if song_loaded:
        if state["playing"]:
            if not song_started:
                pygame.mixer.music.play(-1)
                song_started = True
            else:
                pygame.mixer.music.unpause()
            print("[audio] ▶  Song PLAYING")
        else:
            pygame.mixer.music.pause()
            print("[audio] ⏸  Song PAUSED")
    else:
        status = "PLAYING" if state["playing"] else "PAUSED"
        print(f"[event] BTN PLAY_PAUSE → {status}  (no song loaded)")


def _apply_volume() -> None:
    vol = state["volume"] / 127.0
    pygame.mixer.music.set_volume(vol)
    for s in loaded_notes.values():
        s.set_volume(vol)
    for s in loaded_drums.values():
        s.set_volume(vol)


# ---------------------------------------------------------------------------
# Gesture effects
# ---------------------------------------------------------------------------

def _gesture_effect(gesture: str) -> None:
    """
    Creative real-time effects triggered by gesture:

      LEFT  → filter sweep DOWN  (volume dip + gradual restore simulates LPF sweep)
      RIGHT → filter sweep UP    (stutter-rise: rapid volume bumps climbing back)
      UP    → pitch-rise stutter (rapid note re-triggers on ascending keys)
      DOWN  → reverse echo       (play notes in reverse order, decaying)
      CIRCLE→ vinyl scratch spin  (rapid volume wobble, pitch-shift illusion)
      WAVE  → tremolo shimmer    (sine-wave amplitude modulation, 8 Hz)
    """
    if state["gesture_busy"]:
        print(f"[fx]    Gesture {gesture} ignored — effect already running")
        return

    import threading

    base_vol = state["volume"] / 127.0

    def sweep_down():
        state["gesture_busy"] = True
        print("[fx] ◀  Filter sweep DOWN  ↓↓↓")
        steps = 20
        for i in range(steps):
            v = base_vol * (1 - i / steps) ** 2
            pygame.mixer.music.set_volume(v)
            time.sleep(0.03)
        for i in range(steps):
            v = base_vol * ((i + 1) / steps) ** 2
            pygame.mixer.music.set_volume(v)
            time.sleep(0.03)
        pygame.mixer.music.set_volume(base_vol)
        state["gesture_busy"] = False

    def sweep_up():
        state["gesture_busy"] = True
        print("[fx] ▶  Filter sweep UP  ↑↑↑")
        steps = 16
        for i in range(steps):
            frac = i / steps
            # stutter: brief silence then bump
            pygame.mixer.music.set_volume(0.0)
            time.sleep(0.015)
            pygame.mixer.music.set_volume(base_vol * frac)
            time.sleep(0.025)
        pygame.mixer.music.set_volume(base_vol)
        state["gesture_busy"] = False

    def pitch_rise_stutter():
        state["gesture_busy"] = True
        print("[fx] ▲  Pitch-rise stutter  ↑↑↑")
        # Rapidly retrigger piano notes ascending then descending
        pattern = [1, 2, 3, 4, 5, 6, 7, 6, 5, 4]
        for k in pattern:
            sound = loaded_notes.get(str(k))
            if sound:
                sound.set_volume(base_vol * 0.6)
                sound.play()
            time.sleep(0.07)
        state["gesture_busy"] = False

    def reverse_echo():
        state["gesture_busy"] = True
        print("[fx] ▼  Reverse echo  ↓↓↓")
        # Play notes high→low with decaying volume
        for k in range(7, 0, -1):
            sound = loaded_notes.get(str(k))
            decay = (8 - k) / 7.0
            if sound:
                sound.set_volume(base_vol * decay * 0.5)
                sound.play()
            time.sleep(0.12)
        state["gesture_busy"] = False

    def vinyl_scratch():
        state["gesture_busy"] = True
        print("[fx] ○  Vinyl scratch spin  🔄")
        # Rapid volume wobble simulates scratch
        freq = 18   # wobbles per second
        duration = 1.2
        steps = int(duration * freq * 2)
        for i in range(steps):
            v = base_vol * abs(math.sin(math.pi * i / 3))
            pygame.mixer.music.set_volume(v)
            time.sleep(1.0 / (freq * 2))
        pygame.mixer.music.set_volume(base_vol)
        state["gesture_busy"] = False

    def tremolo():
        state["gesture_busy"] = True
        print("[fx] ~  Tremolo shimmer  ~~~")
        rate     = 8       # Hz
        duration = 1.5
        depth    = 0.55    # 0 = no mod, 1 = full silence dip
        steps    = int(duration * rate * 4)
        for i in range(steps):
            t = i / (rate * 4)
            mod = 1.0 - depth * 0.5 * (1 - math.sin(2 * math.pi * rate * t))
            pygame.mixer.music.set_volume(base_vol * mod)
            time.sleep(1.0 / (rate * 4))
        pygame.mixer.music.set_volume(base_vol)
        state["gesture_busy"] = False

    dispatch = {
        "LEFT":   sweep_down,
        "RIGHT":  sweep_up,
        "UP":     pitch_rise_stutter,
        "DOWN":   reverse_echo,
        "CIRCLE": vinyl_scratch,
        "WAVE":   tremolo,
    }

    fn = dispatch.get(gesture.upper())
    if fn:
        import threading
        threading.Thread(target=fn, daemon=True).start()
    else:
        print(f"[fx]    Unknown gesture: {gesture}")


# ---------------------------------------------------------------------------
# Serial feedback (LED brightness)
# ---------------------------------------------------------------------------

_serial_port = None   # set by run_serial before loop


def _send_led(brightness: int, verbose: bool) -> None:
    """Send LED brightness back to ESP32 if connected."""
    if _serial_port is None:
        if verbose:
            print(f"[led]   LED brightness = {brightness} (no serial)")
        return
    try:
        _serial_port.write(f"LED,{brightness}\n".encode())
        if verbose:
            print(f"[led]   Sent LED,{brightness}")
    except Exception as e:
        if verbose:
            print(f"[led]   Serial write error: {e}")


# ---------------------------------------------------------------------------
# Message parser & handler
# ---------------------------------------------------------------------------

def handle_message(line: str, verbose: bool) -> None:
    line = line.strip()
    if not line:
        return

    parts    = line.split(",")
    msg_type = parts[0]

    if msg_type == "DEBUG":
        if verbose:
            print(f"[debug] {','.join(parts[1:])}")
        return

    try:
        # ── Potentiometers ───────────────────────────────────────────────────
        if msg_type == "POT" and len(parts) == 3:
            control = parts[1]
            value   = max(0, min(127, int(parts[2])))

            if control in ("VOLUME", "POT1", "1"):
                state["volume"] = value
                _apply_volume()
                print(f"[state] 🔊 Volume = {value}  ({value / 127.0:.0%})")

            elif control in ("LED", "POT2", "2"):
                state["led_brightness"] = value
                _send_led(value, verbose)
                print(f"[state] 💡 LED brightness = {value}  ({value / 127.0:.0%})")

            else:
                if verbose:
                    print(f"[warn]  Unknown POT control: {control}")

        # ── Button ───────────────────────────────────────────────────────────
        elif msg_type == "BTN" and len(parts) == 2:
            if parts[1] == "PLAY_PAUSE":
                toggle_play_pause()
            else:
                if verbose:
                    print(f"[warn]  Unknown BTN: {parts[1]}")

        # ── Piano keys ───────────────────────────────────────────────────────
        elif msg_type == "KEY" and len(parts) == 2:
            key_id = parts[1]
            if key_id.isdigit() and 1 <= int(key_id) <= 7:
                state["last_key"] = key_id
                play_note(key_id)
            else:
                if verbose:
                    print(f"[warn]  Invalid KEY id: {key_id}")

        # ── Drum pads (ultrasonic) ────────────────────────────────────────────
        elif msg_type == "DRUM" and len(parts) >= 3:
            drum_id     = parts[1]
            try:
                distance = float(parts[2])
            except ValueError:
                if verbose:
                    print(f"[warn]  Bad distance value: {parts[2]}")
                return
            if drum_id.isdigit() and 1 <= int(drum_id) <= 7:
                state["last_drum"] = drum_id
                play_drum(drum_id, distance)
            else:
                if verbose:
                    print(f"[warn]  Invalid DRUM id: {drum_id}")

        # ── Gesture ──────────────────────────────────────────────────────────
        elif msg_type == "GESTURE" and len(parts) == 2:
            gesture = parts[1]
            state["last_gesture"] = gesture
            print(f"[event] 🤚 Gesture: {gesture}")
            _gesture_effect(gesture)

        # ── Effects (legacy / explicit) ───────────────────────────────────────
        elif msg_type == "EFFECT" and len(parts) == 2:
            effect = parts[1]
            if effect == "LOWPASS_ON":
                state["lowpass"] = True
                print("[effect] Lowpass ON  (placeholder)")
            elif effect == "LOWPASS_OFF":
                state["lowpass"] = False
                print("[effect] Lowpass OFF (placeholder)")
            elif effect == "REVERB_UP":
                state["reverb"] = min(state["reverb"] + 1, 10)
                print(f"[effect] Reverb UP → {state['reverb']}")
            elif effect == "REVERB_DOWN":
                state["reverb"] = max(state["reverb"] - 1, 0)
                print(f"[effect] Reverb DOWN → {state['reverb']}")
            elif effect == "STUTTER":
                print("[effect] Stutter triggered")
                _gesture_effect("UP")   # reuse pitch-rise stutter
            else:
                if verbose:
                    print(f"[warn]  Unknown EFFECT: {effect}")

        else:
            if verbose:
                print(f"[warn]  Malformed line: {line}")

    except (ValueError, IndexError) as e:
        if verbose:
            print(f"[warn]  Parse error on '{line}': {e}")


# ---------------------------------------------------------------------------
# Mock sequences
# ---------------------------------------------------------------------------

MOCK_SEQUENCE = [
    "POT,1,80",            # volume
    "POT,2,110",           # LED brightness
    "BTN,PLAY_PAUSE",      # start song
    "KEY,1",               # C4
    "KEY,3",               # E4
    "KEY,5",               # G4
    "DRUM,1,10",           # kick (close enough)
    "DRUM,2,8",            # snare
    "DRUM,3,12",           # hi-hat
    "GESTURE,LEFT",        # filter sweep down
    "GESTURE,UP",          # pitch stutter
    "GESTURE,CIRCLE",      # vinyl scratch
    "GESTURE,WAVE",        # tremolo
    "GESTURE,DOWN",        # reverse echo
    "GESTURE,RIGHT",       # sweep up
    "POT,1,40",            # reduce volume
    "BTN,PLAY_PAUSE",      # pause
]


def run_mock(verbose: bool) -> None:
    print("=== Mock mode: auto-play sequence ===\n")
    for msg in MOCK_SEQUENCE:
        print(f">>> {msg}")
        handle_message(msg, verbose)
        time.sleep(0.6)
    time.sleep(2)   # let threaded effects finish
    print("\n=== Mock sequence complete ===")
    print(f"[state] Final state: {state}")


def run_mock_interactive(verbose: bool) -> None:
    print("=== Mock interactive mode ===")
    print("Type ESP32 messages (e.g. KEY,3  or  DRUM,2,10  or  GESTURE,CIRCLE).")
    print("Ctrl+C to exit.\n")
    try:
        while True:
            try:
                line = input("> ")
                handle_message(line, verbose)
            except EOFError:
                break
    except KeyboardInterrupt:
        pass
    print(f"\n[state] Final state: {state}")


def run_serial(port: str, baud: int, verbose: bool) -> None:
    global _serial_port
    try:
        import serial
    except ImportError:
        print("ERROR: pyserial not installed. Run: pip install pyserial")
        sys.exit(1)

    print(f"=== Serial mode: {port} @ {baud} ===")
    try:
        ser = serial.Serial(port, baud, timeout=1)
        _serial_port = ser
        print(f"[serial] Connected to {port}")
    except Exception as e:
        print(f"[serial] Failed to open {port}: {e}")
        sys.exit(1)

    try:
        while True:
            raw = ser.readline()
            if raw:
                line = raw.decode("utf-8", errors="replace").strip()
                if line:
                    handle_message(line, verbose)
    except KeyboardInterrupt:
        pass
    finally:
        ser.close()
        print(f"\n[state] Final state: {state}")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Gesture-Controlled DJ — Laptop App",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Message format reference (from ESP32):
  POT,1,<0-127>          Volume potentiometer
  POT,2,<0-127>          LED brightness potentiometer
  BTN,PLAY_PAUSE         Toggle background song
  KEY,<1-7>              Piano note C4–B4
  DRUM,<1-7>,<cm>        Ultrasonic drum hit (triggers if cm <= 15)
  GESTURE,<LEFT|RIGHT|UP|DOWN|CIRCLE|WAVE>
  EFFECT,<LOWPASS_ON|LOWPASS_OFF|REVERB_UP|REVERB_DOWN|STUTTER>

LED feedback to ESP32:
  LED,<0-127>            Sent back over serial when POT2 changes
        """
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--port",             help="Serial port (e.g. /dev/cu.usbserial-XXXX)")
    group.add_argument("--mock",             action="store_true", help="Auto-play mock sequence")
    group.add_argument("--mock-interactive", action="store_true", help="Type messages manually")

    parser.add_argument("--baud",    type=int, default=115200, help="Baud rate (default: 115200)")
    parser.add_argument("--song",    help="Path to background song (.mp3 / .wav / .ogg)")
    parser.add_argument("--verbose", action="store_true", help="Show debug/warning output")

    args = parser.parse_args()

    pygame.init()
    init_audio(args.song, args.verbose)

    if args.mock:
        run_mock(args.verbose)
    elif args.mock_interactive:
        run_mock_interactive(args.verbose)
    elif args.port:
        run_serial(args.port, args.baud, args.verbose)

    pygame.quit()


if __name__ == "__main__":
    main()
