#!/usr/bin/env python3
"""
Gesture-Controlled DJ — Laptop App
Reads structured serial messages from ESP32 Board A and triggers audio/state changes.
"""

import argparse
import os
import sys
import time
from typing import Optional

import pygame

# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

PIANO_NOTES = ["C4", "D4", "E4", "F4", "G4", "A4", "B4"]

DRUM_SOUNDS = [
    "kick.wav",
    "snare.wav",
    "hihat.wav",
    "tom1.wav",
    "tom2.wav",
    "clap.wav",
    "crash.wav",
]

state = {
    "volume": 80,
    "pitch": 64,
    "playing": False,
    "lowpass": False,
    "reverb": 0,
    "last_gesture": None,
    "last_key": None,
    "last_drum": None,
}

# ---------------------------------------------------------------------------
# Audio helpers
# ---------------------------------------------------------------------------

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
SOUNDS_DIR = os.path.join(SCRIPT_DIR, "sounds")

loaded_notes = {}
loaded_drums = {}
song_loaded = False
song_started = False


def init_audio(song_path: Optional[str], verbose: bool) -> None:
    """Initialise pygame mixer; pre-load available sound files."""
    global song_loaded
    pygame.mixer.init()

    # Pre-load piano note sounds
    for i, note in enumerate(PIANO_NOTES):
        path = os.path.join(SOUNDS_DIR, "notes", f"{note}.wav")
        if os.path.isfile(path):
            loaded_notes[str(i + 1)] = pygame.mixer.Sound(path)
            if verbose:
                print(f"[audio] Loaded note {note} from {path}")
        else:
            if verbose:
                print(f"[audio] Note file missing (OK): {path}")

    # Pre-load drum sounds
    for i, fname in enumerate(DRUM_SOUNDS):
        path = os.path.join(SOUNDS_DIR, "drums", fname)
        if os.path.isfile(path):
            loaded_drums[str(i + 1)] = pygame.mixer.Sound(path)
            if verbose:
                print(f"[audio] Loaded drum {fname} from {path}")
        else:
            if verbose:
                print(f"[audio] Drum file missing (OK): {path}")

    # Background song
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


def play_note(key_id: str) -> None:
    """Play a piano note by key id (1-7)."""
    sound = loaded_notes.get(key_id)
    if sound:
        sound.set_volume(state["volume"] / 127.0)
        sound.play()
        print(f"[audio] Playing note {PIANO_NOTES[int(key_id) - 1]}")
    else:
        idx = int(key_id) - 1
        name = PIANO_NOTES[idx] if 0 <= idx < len(PIANO_NOTES) else key_id
        print(f"[event] KEY {key_id} -> {name} (no sound file)")


def play_drum(drum_id: str) -> None:
    """Play a drum sound by id (1-7)."""
    sound = loaded_drums.get(drum_id)
    if sound:
        sound.set_volume(state["volume"] / 127.0)
        sound.play()
        print(f"[audio] Playing drum {DRUM_SOUNDS[int(drum_id) - 1]}")
    else:
        idx = int(drum_id) - 1
        name = DRUM_SOUNDS[idx] if 0 <= idx < len(DRUM_SOUNDS) else drum_id
        print(f"[event] DRUM {drum_id} -> {name} (no sound file)")


def toggle_play_pause() -> None:
    """Toggle background song play/pause."""
    global song_started
    state["playing"] = not state["playing"]
    if song_loaded:
        if state["playing"]:
            if not song_started:
                pygame.mixer.music.play(-1)
                song_started = True
            else:
                pygame.mixer.music.unpause()
            print("[audio] Song playing")
        else:
            pygame.mixer.music.pause()
            print("[audio] Song paused")
    else:
        status = "PLAYING" if state["playing"] else "PAUSED"
        print(f"[event] BTN PLAY_PAUSE -> {status} (no song loaded)")


# ---------------------------------------------------------------------------
# Message parser & handler
# ---------------------------------------------------------------------------

def handle_message(line: str, verbose: bool) -> None:
    """Parse and handle one serial message line."""
    line = line.strip()
    if not line:
        return

    parts = line.split(",")
    msg_type = parts[0]

    # DEBUG lines
    if msg_type == "DEBUG":
        if verbose:
            print(f"[debug] {','.join(parts[1:])}")
        return

    try:
        if msg_type == "POT" and len(parts) == 3:
            control = parts[1]
            value = max(0, min(127, int(parts[2])))
            if control == "VOLUME":
                state["volume"] = value
                pygame.mixer.music.set_volume(value / 127.0)
                print(f"[state] Volume = {value} ({value / 127.0:.2f})")
            elif control == "PITCH":
                state["pitch"] = value
                print(f"[state] Pitch = {value} (placeholder)")
            else:
                if verbose:
                    print(f"[warn] Unknown POT control: {control}")

        elif msg_type == "BTN" and len(parts) == 2:
            if parts[1] == "PLAY_PAUSE":
                toggle_play_pause()
            else:
                if verbose:
                    print(f"[warn] Unknown BTN: {parts[1]}")

        elif msg_type == "KEY" and len(parts) == 2:
            key_id = parts[1]
            if key_id.isdigit() and 1 <= int(key_id) <= 7:
                state["last_key"] = key_id
                play_note(key_id)
            else:
                if verbose:
                    print(f"[warn] Invalid KEY id: {key_id}")

        elif msg_type == "DRUM" and len(parts) == 3:
            drum_id = parts[1]
            distance = parts[2]
            if drum_id.isdigit() and 1 <= int(drum_id) <= 7:
                state["last_drum"] = drum_id
                print(f"[event] Drum {drum_id} hit at {distance} cm")
                play_drum(drum_id)
            else:
                if verbose:
                    print(f"[warn] Invalid DRUM id: {drum_id}")

        elif msg_type == "GESTURE" and len(parts) == 2:
            gesture = parts[1]
            state["last_gesture"] = gesture
            print(f"[event] Gesture: {gesture}")

        elif msg_type == "EFFECT" and len(parts) == 2:
            effect = parts[1]
            if effect == "LOWPASS_ON":
                state["lowpass"] = True
                print("[effect] Lowpass ON (placeholder)")
            elif effect == "LOWPASS_OFF":
                state["lowpass"] = False
                print("[effect] Lowpass OFF (placeholder)")
            elif effect == "REVERB_UP":
                state["reverb"] = min(state["reverb"] + 1, 10)
                print(f"[effect] Reverb UP -> {state['reverb']} (placeholder)")
            elif effect == "REVERB_DOWN":
                state["reverb"] = max(state["reverb"] - 1, 0)
                print(f"[effect] Reverb DOWN -> {state['reverb']} (placeholder)")
            elif effect == "STUTTER":
                print("[effect] Stutter triggered (placeholder)")
            else:
                if verbose:
                    print(f"[warn] Unknown EFFECT: {effect}")

        else:
            if verbose:
                print(f"[warn] Malformed line: {line}")

    except (ValueError, IndexError) as e:
        if verbose:
            print(f"[warn] Parse error on '{line}': {e}")


# ---------------------------------------------------------------------------
# Input sources
# ---------------------------------------------------------------------------

MOCK_SEQUENCE = [
    "POT,VOLUME,80",
    "POT,PITCH,64",
    "BTN,PLAY_PAUSE",
    "KEY,3",
    "DRUM,2,18",
    "GESTURE,LEFT",
    "EFFECT,LOWPASS_ON",
    "EFFECT,REVERB_UP",
    "EFFECT,STUTTER",
    "BTN,PLAY_PAUSE",
]


def run_mock(verbose: bool) -> None:
    """Auto-play a predefined sequence of sample messages."""
    print("=== Mock mode: auto-play sequence ===")
    for msg in MOCK_SEQUENCE:
        print(f"\n>>> {msg}")
        handle_message(msg, verbose)
        time.sleep(0.5)
    print("\n=== Mock sequence complete ===")
    print(f"[state] Final state: {state}")


def run_mock_interactive(verbose: bool) -> None:
    """Interactive mock: user types messages line-by-line."""
    print("=== Mock interactive mode ===")
    print("Type ESP32 messages (e.g. POT,VOLUME,80). Ctrl+C to exit.\n")
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
    """Read from ESP32 serial port."""
    try:
        import serial
    except ImportError:
        print("ERROR: pyserial not installed. Run: pip install pyserial")
        sys.exit(1)

    print(f"=== Serial mode: {port} @ {baud} ===")
    try:
        ser = serial.Serial(port, baud, timeout=1)
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
        description="Gesture-Controlled DJ — Laptop App"
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--port", help="Serial port (e.g. /dev/cu.usbserial-XXXX)")
    group.add_argument("--mock", action="store_true", help="Auto-play mock sequence")
    group.add_argument("--mock-interactive", action="store_true", help="Type messages manually")

    parser.add_argument("--baud", type=int, default=115200, help="Baud rate (default: 115200)")
    parser.add_argument("--song", help="Path to background song file (.mp3/.wav/.ogg)")
    parser.add_argument("--verbose", action="store_true", help="Show DEBUG lines and warnings")

    args = parser.parse_args()

    # Init audio
    init_audio(args.song, args.verbose)

    # Run selected mode
    if args.mock:
        run_mock(args.verbose)
    elif args.mock_interactive:
        run_mock_interactive(args.verbose)
    elif args.port:
        run_serial(args.port, args.baud, args.verbose)


if __name__ == "__main__":
    main()
