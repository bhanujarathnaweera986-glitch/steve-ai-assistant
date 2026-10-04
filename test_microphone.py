import subprocess

# ---- SETTINGS (you can change these later) ----
LISTEN_SECONDS = 8   # how long Ultron waits for you to start talking
# -----------------------------------------------

POWERSHELL_SCRIPT = """
$ErrorActionPreference = 'Stop'
try {
    Add-Type -AssemblyName System.Speech
    $engine = New-Object System.Speech.Recognition.SpeechRecognitionEngine
    $engine.SetInputToDefaultAudioDevice()
    $engine.LoadGrammar((New-Object System.Speech.Recognition.DictationGrammar))
    $result = $engine.Recognize([TimeSpan]::FromSeconds(%d))
    if ($result) { Write-Output $result.Text }
} catch {
    Write-Output ('ULTRON_ERROR: ' + $_.Exception.Message)
}
""" % LISTEN_SECONDS


def print_mic_help(details):
    print("\nWHAT WENT WRONG: Ultron could not use the microphone.")
    print("WHY: " + details)
    print("FIX:")
    print("  1. Press the Windows key, type 'microphone privacy settings', open it.")
    print("  2. Turn ON 'Microphone access'.")
    print("  3. Turn ON 'Let desktop apps access your microphone'.")
    print("  4. Press the Windows key, type 'sound settings', open it, and check")
    print("     your microphone is listed under 'Input' and the bar moves when you talk.")
    print("TEST: Run this again:")
    print("     python test_microphone.py\n")


def listen():
    """Listen once. Returns the text you said, '' if nothing heard, or None on error."""
    try:
        result = subprocess.run(
            ["powershell", "-NoProfile", "-Command", POWERSHELL_SCRIPT],
            capture_output=True,
            text=True,
            timeout=LISTEN_SECONDS + 30,
        )
    except subprocess.TimeoutExpired:
        print_mic_help("The microphone took too long to respond.")
        return None

    output = result.stdout.strip()
    if output.startswith("ULTRON_ERROR:"):
        print_mic_help(output.replace("ULTRON_ERROR:", "").strip())
        return None
    return output


if __name__ == "__main__":
    print("Microphone test. Speak clearly after you see 'LISTENING...'")
    print("Try saying: hello Ultron what time is it\n")
    print("LISTENING... (you have %d seconds to start talking)" % LISTEN_SECONDS)
    text = listen()
    if text is None:
        pass  # the error help was already shown
    elif text == "":
        print("\nI heard nothing. Try again a bit louder and closer to the laptop.")
    else:
        print("\nI heard: " + text)
        print("The microphone works!")