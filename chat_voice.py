import json
import urllib.request
import urllib.error

from test_speaker import speak  # reuses the voice from the last stage

# ---- SETTINGS (you can change these later) ----
MODEL = "llama3.2:1b"
URL = "http://localhost:11434/api/chat"
PERSONALITY = (
    "You are ULTRON, a calm, intelligent, slightly formal AI assistant. "
    "Keep answers short, 1 to 3 sentences, and simple. "
    "Do not use emojis or special symbols. "
    "If you cannot do something, say so honestly."
)
# -----------------------------------------------


def ask_ollama(history):
    payload = json.dumps({
        "model": MODEL,
        "messages": history,
        "stream": False,
    }).encode("utf-8")

    request = urllib.request.Request(
        URL, data=payload, headers={"Content-Type": "application/json"}
    )
    with urllib.request.urlopen(request, timeout=300) as response:
        data = json.loads(response.read().decode("utf-8"))
    return data["message"]["content"]


def main():
    print("ULTRON voice chat. Type 'quit' to stop.")
    print("(The first answer can take a minute while the AI loads.)\n")

    history = [{"role": "system", "content": PERSONALITY}]
    speak("Ultron online.")

    while True:
        question = input("YOU: ").strip()
        if question.lower() in ("quit", "exit"):
            print("ULTRON: Goodbye.")
            speak("Goodbye.")
            break
        if question == "":
            continue

        history.append({"role": "user", "content": question})

        try:
            answer = ask_ollama(history)
        except urllib.error.HTTPError as e:
            print("\nWHAT WENT WRONG: Ollama doesn't have the model '" + MODEL + "'.")
            print("WHY: The model name is wrong or not downloaded. (Code " + str(e.code) + ")")
            print("FIX: Run this in a new PowerShell window:")
            print("     ollama pull " + MODEL)
            print("TEST: Run 'ollama list' and check the name is there.\n")
            history.pop()
            continue
        except urllib.error.URLError:
            print("\nWHAT WENT WRONG: I can't reach Ollama.")
            print("WHY: The Ollama app is probably not running.")
            print("FIX: Press the Windows key, type Ollama, open it, wait 10 seconds.")
            print("TEST: Run this in PowerShell, it should say 'Ollama is running':")
            print("     Invoke-RestMethod http://localhost:11434\n")
            history.pop()
            continue
        except TimeoutError:
            print("\nWHAT WENT WRONG: Ollama took too long to answer.")
            print("WHY: The laptop may be busy or low on memory.")
            print("FIX: Close other big programs (like browser tabs) and try again.")
            print("TEST: Ask a short question like: hi\n")
            history.pop()
            continue

        history.append({"role": "assistant", "content": answer})
        print("\nULTRON: " + answer + "\n")
        speak(answer)


main()