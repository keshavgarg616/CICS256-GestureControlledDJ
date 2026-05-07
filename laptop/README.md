# Gesture-Controlled DJ — Laptop App

Reads structured serial messages from ESP32 Board A and triggers audio/state changes using pygame.

## Install

```bash
pip install -r laptop/requirements.txt
```

## Run

### Mock mode (no hardware)

Auto-play a sample message sequence:

```bash
python laptop/dj_app.py --mock --verbose
```

Interactive — type messages manually:

```bash
python laptop/dj_app.py --mock-interactive
```

### Real serial mode (Board A connected via USB)

```bash
python laptop/dj_app.py --port /dev/cu.usbserial-XXXX --baud 115200
```

### With background song

Add `--song` to any mode:

```bash
python laptop/dj_app.py --mock --song path/to/song.mp3
```

## Sound files

Place sound files in the `sounds/` subdirectories:

| Directory | Files | Example |
|---|---|---|
| `sounds/notes/` | `C4.wav`, `D4.wav`, `E4.wav`, `F4.wav`, `G4.wav`, `A4.wav`, `B4.wav` | Piano key 1 → C4.wav |
| `sounds/drums/` | `kick.wav`, `snare.wav`, `hihat.wav`, `tom1.wav`, `tom2.wav`, `clap.wav`, `crash.wav` | Drum 1 → kick.wav |
| `sounds/songs/` | Any `.mp3`/`.wav`/`.ogg` | Passed via `--song` |

Missing files are OK — the app logs a message and continues.

## Expected ESP32 serial protocol

Board A sends these messages over USB Serial at 115200 baud:

| Message | Description |
|---|---|
| `POT,VOLUME,<0-127>` | Potentiometer 1 → volume |
| `POT,PITCH,<0-127>` | Potentiometer 2 → pitch |
| `BTN,PLAY_PAUSE` | Button press → toggle play/pause |
| `KEY,<1-7>` | Touch pad → piano note |
| `DRUM,<1-7>,<cm>` | Ultrasonic sensor → drum hit |
| `GESTURE,<name>` | Gesture detected |
| `EFFECT,<name>` | Effect triggered (LOWPASS_ON, LOWPASS_OFF, REVERB_UP, REVERB_DOWN, STUTTER) |
| `DEBUG,<text>` | Debug output (shown only with `--verbose`) |

## Notes

- Hardware testing requires ESP32 Board A connected over USB.
- Pitch shifting, reverb, and low-pass filtering are placeholders in v1.
- Board B sends ultrasonic data to Board A over UART2 — the laptop does not communicate with Board B directly.
