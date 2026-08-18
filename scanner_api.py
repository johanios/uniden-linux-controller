import sys
import os
from threading import Thread
from time import sleep, time
from fastapi import FastAPI
from fastapi.responses import FileResponse
from pydantic import BaseModel
from datetime import datetime
from fastapi.staticfiles import StaticFiles
import numpy as np
import sounddevice as sd
import soundfile as sf
import glob

# Add src to sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "src")))

from bearcat.handheld.bc125at import BC125AT, Channel, Modulation
from bearcat import OperationMode, KeyAction
from bearcat.handheld import BasicHandheld

# -------------------------------------------------------------------
# USB listing AT STARTUP
# -------------------------------------------------------------------

def list_usb_serial_devices():
    ports = glob.glob("/dev/ttyACM*") + glob.glob("/dev/ttyUSB*")
    print("\n=== Available USB serial ports ===")
    if not ports:
        print("No USB devices found.")
        return []

    for i, p in enumerate(ports, 1):
        print(f"[{i}] {p}")
    print()
    return ports

def select_device_interactive():
    ports = list_usb_serial_devices()

    if not ports:
        print("\n⚠ No USB scanner found. Using default /dev/ttyACM0.")
        return "/dev/ttyACM0"

    # Add Q option
    print("[Q] Exit without starting\n")

    while True:
        try:
            choice = input("Select a device (number or Q): ").strip().lower()
        except KeyboardInterrupt:
            print("\nExiting...")
            os._exit(0)

        # Handle Q
        if choice == "q":
            print("Exiting...")
            os._exit(0)

        # Handle numbers
        if choice.isdigit():
            idx = int(choice)
            if 1 <= idx <= len(ports):
                selected = ports[idx - 1]
                print(f"\nSelected scanner device: {selected}\n")
                return selected

        print("Invalid choice, try again.\n")

# -------------------------------------------------------------------
# Select DEVICE before anything else happens
# -------------------------------------------------------------------
def verify_scanner_device(device):
    print(f"Testing device: {device}")
    try:
        test = BC125AT(device)
        test.get_status()   # Ping the scanner
        print("✔ The device responded as a BC125AT!")
        return True
    except Exception as e:
        print(f"✖ The device did not respond as BC125AT: {e}")
        return False

# -------------------------------------------------------------------
# Select and verify DEVICE before anything else happens
# -------------------------------------------------------------------
while True:
    DEVICE = select_device_interactive()
    if verify_scanner_device(DEVICE):
        break
    print("\n⚠ ERROR: The selected device is not a BC125AT. Try again.\n")

# --- Global settings ---
bc = None
scanner_status_logged = None  # None=unknown, False=not connected, True=connected
_last_scanner_attempt = 0

# --- Global variables that the background loop updates ---
screen_text = ""
squelch_status = False
mute_status = False
current_state = None

# --- Global flag: auto-recording on/off in front end---
recording_enabled = False

# --- Global flag: auto-lockout ---
auto_lockout_enabled = False

# Track last channel/frequency and time
_last_channel_freq = None
_last_channel_time = 0
_lockout_pending_freq = None  # After lockout, wait for freq change or squelch close

# --- Global recording variables ---
recording_active = False
recording_paused = False
current_filename = ""
audio_buffer = []
stream = None
current_recording_channel = None

# --- Activity log ---
activity_log = []
MAX_ACTIVITY_LOG = 500
active_activity = None
_last_squelch_state = False

SAMPLE_RATE = 44100
NUM_CHANNELS = 2
BLOCK_SIZE = 1024

app = FastAPI(title="UBC125XLT Web API")

RECORDINGS_DIR = os.path.join(
    os.path.dirname(__file__),
    "recordings"
)

os.makedirs(RECORDINGS_DIR, exist_ok=True)

app.mount(
    "/recordings",
    StaticFiles(directory=RECORDINGS_DIR),
    name="recordings"
)

class Command(BaseModel):
    action: str
    value: str = None

# --- Scanner connection ---
def get_scanner():
    global bc, scanner_status_logged, _last_scanner_attempt

    now = time()

    # 1. If scanner already exists, test it directly
    if bc:
        try:
            bc.get_status()  # Quick "ping"
            if scanner_status_logged != True:
                print("Scanner found!")
                scanner_status_logged = True
            return bc
        except Exception:
            # Scanner dead → clear but do not reconnect immediately
            bc = None
            if scanner_status_logged != False:
                print("Scanner disconnected or turned off!")
                scanner_status_logged = False

    # 2. If scanner is None → attempt reconnect but only every 5 seconds
    if now - _last_scanner_attempt < 5:
        return None  # Skip reconnect

    _last_scanner_attempt = now

    try:
        bc = BC125AT(DEVICE)
        print("Scanner reconnected!")
        scanner_status_logged = True
    except Exception:
        bc = None
        if scanner_status_logged != False:
            print("Scanner not found!")
            scanner_status_logged = False

    return bc

# --- Recording functions ---
def audio_callback(indata, frames, time_info, status):
    if recording_active and not recording_paused:
        audio_buffer.append(indata.copy())

def start_recording(filename):
    global recording_active, recording_paused, current_filename, audio_buffer, stream
    if recording_active:
        return
    current_filename = filename
    recording_active = True
    recording_paused = False
    audio_buffer = []
    print(f"[Recorder] Start recording: {filename}")

    stream = sd.InputStream(
        samplerate=SAMPLE_RATE,
        channels=1,
        dtype='float32',
        callback=audio_callback
    )
    stream.start()

def stop_recording():
    global recording_active, recording_paused, current_filename, audio_buffer, stream
    if not recording_active:
        return
    print(f"[Recorder] Stop recording: {current_filename}")
    recording_active = False
    recording_paused = False

    if stream:
        stream.stop()
        stream.close()
        stream = None

    if audio_buffer:
        filename_path = os.path.join(RECORDINGS_DIR, current_filename)
        data = np.concatenate(audio_buffer, axis=0).astype(np.float32)
        sf.write(filename_path, data, SAMPLE_RATE)
        print(f"[Recorder] Saved recording: {filename_path}")

    audio_buffer = []
    current_filename = ""

def pause_recording():
    global recording_paused, stream
    if recording_active and not recording_paused:
        print(f"[Recorder] Pausing recording: {current_filename}")
        if stream:
            stream.stop()
        recording_paused = True

def resume_recording():
    global recording_paused, stream
    if recording_active and recording_paused:
        print(f"[Recorder] Resuming recording: {current_filename}")
        if stream:
            stream.start()
        recording_paused = False

# --- Auto-lockout helpers ---
def _recording_channel_id(state):
    return f"{state.frequency/1e6:.6f}"


def _reception_trackable(state, squelch):
    """After lockout, ignore stale open-squelch on the locked frequency."""
    global _lockout_pending_freq

    if _lockout_pending_freq is None:
        return True

    if not squelch:
        _lockout_pending_freq = None
        return True

    if state and state.frequency != _lockout_pending_freq:
        _lockout_pending_freq = None
        return True

    return False


def apply_auto_lockout(scanner, locked_freq):
    global _last_channel_freq, _last_channel_time, current_recording_channel
    global _last_squelch_state, _lockout_pending_freq

    try:
        scanner._key_action("L", KeyAction.PRESS)
        print(f"[AutoLockout] Temporary lockout applied on {locked_freq}")
    except Exception as e:
        print(f"[AutoLockout] Failed to lockout: {e}")
        return

    _lockout_pending_freq = locked_freq

    if recording_active:
        stop_recording()
    current_recording_channel = None

    if active_activity:
        stop_activity_log()

    _last_channel_freq = None
    _last_channel_time = 0
    _last_squelch_state = False

# --- Activity logging ---
def start_activity_log(state):
    global activity_log, active_activity

    now = datetime.now()

    entry = {
        "date": now.strftime("%Y-%m-%d"),
        "time": now.strftime("%H:%M:%S"),
        "channel": getattr(state, "channel", None),
        "frequency": f"{state.frequency/1e6:.6f}",
        "modulation": state.modulation.value if state.modulation else "",
        "tone": state.tone_code or "",
        "duration": None,
        "recording": None,
        "_start": time(),
        "_frequency": state.frequency,
    }

    activity_log.append(entry)
    active_activity = entry

    if len(activity_log) > MAX_ACTIVITY_LOG:
        activity_log.pop(0)


def stop_activity_log():
    global active_activity

    if active_activity:
        duration = time() - active_activity["_start"]
        active_activity["duration"] = int(duration)

        if current_filename:
            active_activity["recording"] = current_filename

        active_activity.pop("_start", None)
        active_activity.pop("_frequency", None)

    active_activity = None

# --- Background loop ---
def scanner_poll_loop():
    global screen_text, squelch_status, mute_status, current_state
    global recording_active, recording_enabled, current_recording_channel
    global _last_squelch_state, _last_channel_freq, _last_channel_time

    while True:
        scanner = get_scanner()
        if scanner:
            try:
                # Fetch screen information
                screen, squelch, mute = scanner.get_status()
                screen_text = screen
                squelch_status = squelch
                mute_status = mute

                # Fetch frequency and channel info
                try:
                    state, squelch_flag, muted_flag = scanner.get_reception_status()
                    current_state = state
                    trackable = _reception_trackable(state, squelch)

                    # --- Activity logging ---
                    if state and trackable:

                        if squelch:
                            if active_activity and active_activity.get("_frequency") != state.frequency:
                                stop_activity_log()
                                start_activity_log(state)
                            elif not _last_squelch_state:
                                start_activity_log(state)
                        elif _last_squelch_state:
                            stop_activity_log()

                        _last_squelch_state = squelch

                    # --- Auto-lockout logic ---
                    if auto_lockout_enabled and state and squelch and trackable:
                        current_channel_freq = state.frequency
                        now = time()

                        if _last_channel_freq != current_channel_freq:
                            _last_channel_freq = current_channel_freq
                            _last_channel_time = now
                        elif now - _last_channel_time > 10:  # 10 seconds
                            apply_auto_lockout(scanner, current_channel_freq)
                            _last_channel_time = now  # reset timer to avoid spamming

                    # --- Auto-recording logic ---
                    if state and recording_enabled and trackable:
                        channel_id = _recording_channel_id(state)

                        if squelch and not mute:
                            # Squelch open
                            if recording_active:
                                # If new channel
                                if current_recording_channel != channel_id:
                                    stop_recording()
                                    current_recording_channel = channel_id
                                    filename = f"{channel_id}_{int(time())}.wav"
                                    start_recording(filename)
                                else:
                                    # Resume if paused
                                    resume_recording()
                            else:
                                # Start recording on channel
                                current_recording_channel = channel_id
                                filename = f"{channel_id}_{int(time())}.wav"
                                start_recording(filename)
                        else:
                            # Squelch closed → pause
                            if recording_active and not recording_paused:
                                pause_recording()

                except Exception as e:
                    current_state = None

            except Exception as e:
                print(f"[Scanner] get_status failed: {e}")
        else:
            screen_text = ""
            squelch_status = False
            mute_status = False
            current_state = None

        sleep(0.2)

# Start background loop at FastAPI startup
@app.on_event("startup")
def start_background_thread():
    Thread(target=scanner_poll_loop, daemon=True).start()

# --- Endpoint to retrieve status ---
@app.get("/status")
def get_status_endpoint():
    return {
        "screen": screen_text,
        "squelch": squelch_status,
        "mute": mute_status,
        "state": {
            "name": current_state.name,
            "frequency": current_state.frequency,
            "modulation": current_state.modulation.value,
            "tone_code": current_state.tone_code
        } if current_state else None,
        "recording_active": recording_active,
        "recording_paused": recording_paused,
        "filename": current_filename,
        "recording_enabled": recording_enabled,
        "auto_lockout_enabled": auto_lockout_enabled
    }

# --- Endpoint for logging ---
@app.get("/activity")
def get_activity_endpoint():
    return [
        {k: v for k, v in entry.items() if not k.startswith("_")}
        for entry in activity_log[::-1]
    ]


# --- Endpoint to send commands ---
@app.post("/command")
def send_command(cmd: Command):
    global recording_enabled

    scanner = get_scanner()
    if not scanner:
        return {"error": "Scanner not connected"}

    try:
        action = cmd.action.lower()

        # --- Enable/disable auto-recording ---
        if action == "set_recording_enabled":
            recording_enabled = (cmd.value == "on")
            print(f"[Recorder] recording_enabled = {recording_enabled}")
            if not recording_enabled and recording_active:
                stop_recording()
            return {"status": "ok"}

        # --- Backlight ---
        elif action == "backlight_on":
            scanner.set_backlight(scanner.BacklightMode.ALWAYS_ON)
        elif action == "backlight_off":
            scanner.set_backlight(scanner.BacklightMode.ALWAYS_OFF)

        # --- Channel change ---
        elif action == "set_channel" and cmd.value:
            channel_number = int(cmd.value)
            if hasattr(scanner, "jump_to_channel"):
                try:
                    scanner.jump_to_channel(channel_number)
                except Exception:
                    pass
                    
        # --- Enable/disable auto-lockout ---
        elif action == "set_auto_lockout":
            global auto_lockout_enabled
            auto_lockout_enabled = (cmd.value == "on")
            print(f"[AutoLockout] auto_lockout_enabled = {auto_lockout_enabled}")
            return {"status": "ok"}

        # --- Keypad buttons ---
        elif action.startswith("key_"):
            key = cmd.action[4:].upper()
            if key not in BasicHandheld.AVAILABLE_KEYS:
                return {"error": f"Unknown button: {key}"}
            scanner._key_action(key, KeyAction.PRESS)

        else:
            return {"error": "unknown action"}

        return {"status": "ok"}

    except Exception as e:
        return {"error": str(e)}

# --- Home endpoint ---
@app.get("/")
def home():
    html_path = os.path.join(os.path.dirname(__file__), "index.html")
    if os.path.exists(html_path):
        return FileResponse(html_path)
    return {"error": "index.html missing"}
