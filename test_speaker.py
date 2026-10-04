import os
import subprocess

# ---- SETTINGS (you can change these later) ----
SPEECH_RATE = -1      # -10 (slowest) to 10 (fastest). Slightly slow sounds more "AI".
SPEECH_VOLUME = 100   # 0 to 100
# -----------------------------------------------


def speak(text):
    """Make Ultron say something out loud using the built-in Windows voice."""
    script = (
        "Add-Type -AssemblyName System.Speech; "
        "$s = New-Object System.Speech.Synthesis.SpeechSynthesizer; "
        "$s.Rate = " + str(SPEECH_RATE) + "; "
        "$s.Volume = " + str(SPEECH_VOLUME) + "; "
        "$s.Speak($env:ULTRON_TEXT)"
    )
    env = os.environ.copy()
    env["ULTRON_TEXT"] = text
    result = subprocess.run(
        ["powershell", "-NoProfile", "-Command", script],
        env=env,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        print("\nWHAT WENT WRONG: Ultron could not speak.")
        print("WHY: Windows speech failed. Details: " + result.stderr.strip())
        print("FIX: Check your volume is up and the right speakers are selected.")
        print("TEST: Paste this in PowerShell, you should hear a voice:")
        print('     Add-Type -AssemblyName System.Speech; (New-Object System.Speech.Synthesis.SpeechSynthesizer).Speak("test")\n')
        return False
    return True


if __name__ == "__main__":
    print("Speaker test starting. Turn your volume up.")
    if speak("Speaker test. Hello. I am Ultron. All systems are online."):
        print("Done. Did you hear Ultron speak? If yes, the speakers work.")