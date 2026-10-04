import json
import math
import os
import queue
import subprocess
import threading
import time
import tkinter as tk
import urllib.error
import urllib.request

# ---- SETTINGS (you can change these later) ----
MODEL = "llama3.2:1b"
URL = "http://localhost:11434/api/chat"
PERSONALITY = (
    "You are ULTRON, a calm, intelligent, slightly formal AI assistant. "
    "Keep answers short, 1 to 3 sentences, and simple. "
    "Do not use emojis or special symbols. "
    "If you cannot do something, say so honestly."
)
SPEECH_RATE = -1       # -10 (slowest) to 10 (fastest)
SPEECH_VOLUME = 100    # 0 to 100
SPEAK_ANSWERS = True   # False = Ultron stays silent
# -----------------------------------------------

BG = "#02060d"
PANEL = "#050d17"
CYAN = "#00e5ff"
GREEN = "#7dffb2"
AMBER = "#ffb300"
RED = "#ff3b3b"
DIM = "#0a3a4a"
PLACEHOLDER = "Type here..."


def blend(color, other, f):
    """Mix two hex colors. f=0 gives color, f=1 gives other."""
    c1 = [int(color[i:i + 2], 16) for i in (1, 3, 5)]
    c2 = [int(other[i:i + 2], 16) for i in (1, 3, 5)]
    mixed = [int(a + (b - a) * f) for a, b in zip(c1, c2)]
    return "#%02x%02x%02x" % tuple(mixed)


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


class UltronApp:
    def __init__(self, root):
        self.root = root
        self.root.title("ULTRON")
        self.root.geometry("900x740")
        self.root.configure(bg=BG)
        self.root.minsize(700, 620)

        self.status = "ULTRON ONLINE"
        self.paused = False
        self.busy = False
        self.rid = 0   # request id, used to drop answers after Pause
        self.sid = 0   # speech id, used to drop old speech events
        self.speech_proc = None
        self.placeholder_on = True
        self.q = queue.Queue()
        self.history = [{"role": "system", "content": PERSONALITY}]
        self.t0 = time.time()

        self.build_ui()
        self.add_message("ULTRON", "Online. Type a question below.")
        self.animate()
        self.poll()
        self.root.after(600, lambda: self.speak("Ultron online."))
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)

    # ---------- building the screen ----------
    def build_ui(self):
        self.status_label = tk.Label(
            self.root, text=self.status, bg=BG, fg=CYAN,
            font=("Consolas", 24, "bold"),
        )
        self.status_label.pack(pady=(14, 0))

        self.indicator_label = tk.Label(
            self.root, text="", bg=BG, fg=DIM, font=("Consolas", 11),
        )
        self.indicator_label.pack(pady=(2, 0))

        self.canvas = tk.Canvas(self.root, bg=BG, height=330, highlightthickness=0)
        self.canvas.pack(fill="both", expand=True, padx=10)

        self.text = tk.Text(
            self.root, height=9, bg=PANEL, fg="#cfefff", bd=0, wrap="word",
            font=("Consolas", 11), padx=14, pady=10, cursor="arrow",
            highlightthickness=1, highlightbackground=DIM, highlightcolor=DIM,
        )
        self.text.tag_config("you", foreground=CYAN, font=("Consolas", 11, "bold"))
        self.text.tag_config("ultron", foreground=GREEN, font=("Consolas", 11, "bold"))
        self.text.config(state="disabled")
        self.text.pack(fill="x", padx=30, pady=(4, 8))

        self.entry = tk.Entry(
            self.root, bg=PANEL, fg=DIM, insertbackground=CYAN, bd=0,
            font=("Consolas", 13), highlightthickness=1,
            highlightbackground=DIM, highlightcolor=CYAN,
        )
        self.entry.insert(0, PLACEHOLDER)
        self.entry.pack(fill="x", padx=30, ipady=9)
        self.entry.bind("<FocusIn>", self.entry_focus_in)
        self.entry.bind("<FocusOut>", self.entry_focus_out)
        self.entry.bind("<Return>", lambda e: self.send())

        row = tk.Frame(self.root, bg=BG)
        row.pack(pady=12)

        def make_button(text, command, fg, width):
            return tk.Button(
                row, text=text, command=command, bg=PANEL, fg=fg,
                activebackground=DIM, activeforeground=fg, bd=0,
                font=("Consolas", 12, "bold"), width=width, pady=8,
                cursor="hand2", highlightthickness=1, highlightbackground=fg,
            )

        self.mic_button = make_button("MIC", self.mic_pressed, CYAN, 8)
        self.send_button = make_button("SEND", self.send, CYAN, 10)
        self.pause_button = make_button("PAUSE", self.toggle_pause, RED, 12)
        self.test_button = make_button("TEST SPEAKER", self.test_speaker, GREEN, 14)
        for b in (self.mic_button, self.send_button, self.pause_button, self.test_button):
            b.pack(side="left", padx=6)

        self.update_indicators()

    # ---------- placeholder text in the input box ----------
    def entry_focus_in(self, event):
        if self.placeholder_on:
            self.entry.delete(0, "end")
            self.entry.config(fg="#cfefff")
            self.placeholder_on = False

    def entry_focus_out(self, event):
        if self.entry.get() == "":
            self.entry.insert(0, PLACEHOLDER)
            self.entry.config(fg=DIM)
            self.placeholder_on = True

    # ---------- status and indicators ----------
    def set_status(self, status):
        self.status = status
        color = {
            "ULTRON ONLINE": CYAN, "THINKING": AMBER,
            "SPEAKING": GREEN, "PAUSED": RED,
        }.get(status, CYAN)
        self.status_label.config(text=status, fg=color)
        self.update_indicators()

    def update_indicators(self):
        speaker = "SPEAKING" if self.status == "SPEAKING" else "READY"
        if not SPEAK_ANSWERS:
            speaker = "OFF"
        self.indicator_label.config(
            text="MIC: OFF     SPEAKER: %s     MODE: OFFLINE (local AI)" % speaker
        )

    # ---------- the animated core ----------
    def animate(self):
        c = self.canvas
        c.delete("all")
        w = c.winfo_width()
        h = c.winfo_height()
        cx, cy = w / 2, h / 2
        t = time.time() - self.t0

        color, speed, amp = {
            "ULTRON ONLINE": (CYAN, 1.0, 5),
            "THINKING": (AMBER, 3.0, 8),
            "SPEAKING": (GREEN, 2.0, 14),
            "PAUSED": (RED, 0.15, 1),
        }.get(self.status, (CYAN, 1.0, 5))

        # glowing rings
        for i in range(6):
            r = 40 + i * 14 + amp * math.sin(t * 2 * speed + i * 0.6)
            ring = blend(color, BG, min(0.9, 0.1 + i * 0.15))
            c.create_oval(cx - r, cy - r, cx + r, cy + r, outline=ring, width=2)

        # spinning arcs
        arcs = [(105, 80, 1), (130, 50, -1), (155, 100, 1)]
        for k, (r, extent, direction) in enumerate(arcs):
            start = (t * 60 * speed * direction * (1 + k * 0.4)) % 360
            for offset in (0, 180):
                c.create_arc(
                    cx - r, cy - r, cx + r, cy + r, start=start + offset,
                    extent=extent, style="arc", outline=color, width=3,
                )

        # center core
        core = 26 + amp * 0.8 * math.sin(t * 3 * speed)
        c.create_oval(
            cx - core, cy - core, cx + core, cy + core,
            fill=blend(color, BG, 0.5), outline=color, width=2,
        )
        inner = core * 0.45
        c.create_oval(
            cx - inner, cy - inner, cx + inner, cy + inner,
            fill=color, outline="",
        )

        self.root.after(33, self.animate)

    # ---------- showing the conversation ----------
    def add_message(self, who, message):
        self.text.config(state="normal")
        tag = "you" if who == "YOU" else "ultron"
        self.text.insert("end", who + ":\n", tag)
        self.text.insert("end", message + "\n\n")
        self.text.see("end")
        self.text.config(state="disabled")

    # ---------- buttons ----------
    def send(self):
        if self.paused or self.busy or self.placeholder_on:
            return
        question = self.entry.get().strip()
        if question == "":
            return
        self.entry.delete(0, "end")
        self.add_message("YOU", question)
        self.stop_speech()
        self.history.append({"role": "user", "content": question})
        self.busy = True
        self.rid += 1
        self.set_status("THINKING")
        threading.Thread(
            target=self.worker, args=(self.rid, list(self.history)), daemon=True
        ).start()

    def mic_pressed(self):
        self.add_message(
            "ULTRON",
            "The microphone is switched off in this version. "
            "For now, please type your question below.",
        )

    def test_speaker(self):
        if self.paused:
            return
        self.speak("Speaker test. Hello. I am Ultron. All systems are online.")

    def toggle_pause(self):
        if not self.paused:
            self.paused = True
            self.rid += 1  # any answer still on its way gets thrown away
            if self.busy:
                self.busy = False
                self.history.pop()  # remove the unanswered question
            self.stop_speech()
            self.entry.config(state="disabled")
            self.pause_button.config(text="RESUME", fg=GREEN, highlightbackground=GREEN)
            self.set_status("PAUSED")
        else:
            self.paused = False
            self.entry.config(state="normal")
            self.pause_button.config(text="PAUSE", fg=RED, highlightbackground=RED)
            self.set_status("ULTRON ONLINE")

    # ---------- talking to Ollama (runs in the background) ----------
    def worker(self, rid, history_copy):
        try:
            answer = ask_ollama(history_copy)
            self.q.put(("answer", rid, answer))
        except urllib.error.HTTPError as e:
            self.q.put(("error", rid, (
                "WHAT WENT WRONG: Ollama doesn't have the model '%s'.\n"
                "WHY: The model name is wrong or not downloaded (code %s).\n"
                "FIX: Paste this in a new PowerShell window: ollama pull %s\n"
                "TEST: Run 'ollama list' and check the name is there."
                % (MODEL, e.code, MODEL)
            )))
        except urllib.error.URLError:
            self.q.put(("error", rid, (
                "WHAT WENT WRONG: I can't reach Ollama.\n"
                "WHY: The Ollama app is probably not running.\n"
                "FIX: Press the Windows key, type Ollama, open it, wait 10 seconds.\n"
                "TEST: Paste this in PowerShell, it should say 'Ollama is running': "
                "Invoke-RestMethod http://localhost:11434"
            )))
        except TimeoutError:
            self.q.put(("error", rid, (
                "WHAT WENT WRONG: Ollama took too long to answer.\n"
                "WHY: The laptop may be busy or low on memory.\n"
                "FIX: Close other big programs (like browser tabs) and try again.\n"
                "TEST: Ask a short question like: hi"
            )))
        except Exception as e:
            self.q.put(("error", rid, (
                "WHAT WENT WRONG: Something unexpected happened.\n"
                "WHY: %s\n"
                "FIX: Close Ultron and start it again: python ultron_app.py\n"
                "TEST: Ask a short question like: hi" % e
            )))

    # ---------- speaking (runs in the background) ----------
    def speak(self, text):
        if not SPEAK_ANSWERS:
            return
        self.stop_speech()
        self.sid += 1
        self.set_status("SPEAKING")
        threading.Thread(
            target=self.run_speech, args=(text, self.sid), daemon=True
        ).start()

    def run_speech(self, text, sid):
        script = (
            "Add-Type -AssemblyName System.Speech; "
            "$s = New-Object System.Speech.Synthesis.SpeechSynthesizer; "
            "$s.Rate = %d; $s.Volume = %d; $s.Speak($env:ULTRON_TEXT)"
            % (SPEECH_RATE, SPEECH_VOLUME)
        )
        env = os.environ.copy()
        env["ULTRON_TEXT"] = text.replace("*", "").replace("#", "")
        try:
            proc = subprocess.Popen(
                ["powershell", "-NoProfile", "-Command", script],
                env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                text=True, creationflags=0x08000000,  # no popup window
            )
            self.speech_proc = proc
            _, err = proc.communicate()
            if proc.returncode != 0 and sid == self.sid:
                self.q.put(("speech_error", sid, err.strip()))
                return
        except Exception as e:
            self.q.put(("speech_error", sid, str(e)))
            return
        self.q.put(("spoken", sid, None))

    def stop_speech(self):
        self.sid += 1  # old speech events will now be ignored
        proc = self.speech_proc
        if proc is not None and proc.poll() is None:
            try:
                proc.terminate()
            except Exception:
                pass

    # ---------- handling results on the main thread ----------
    def poll(self):
        try:
            while True:
                kind, ident, data = self.q.get_nowait()
                self.handle(kind, ident, data)
        except queue.Empty:
            pass
        self.root.after(100, self.poll)

    def handle(self, kind, ident, data):
        if kind == "answer":
            if ident != self.rid:
                return
            self.busy = False
            self.history.append({"role": "assistant", "content": data})
            self.add_message("ULTRON", data)
            if SPEAK_ANSWERS:
                self.speak(data)
            else:
                self.set_status("ULTRON ONLINE")
        elif kind == "error":
            if ident != self.rid:
                return
            self.busy = False
            self.history.pop()
            self.add_message("ULTRON", data)
            self.set_status("ULTRON ONLINE")
        elif kind == "spoken":
            if ident == self.sid and not self.paused:
                self.set_status("ULTRON ONLINE")
        elif kind == "speech_error":
            if ident != self.sid:
                return
            self.add_message("ULTRON", (
                "WHAT WENT WRONG: I could not speak.\n"
                "WHY: Windows speech failed. Details: %s\n"
                "FIX: Check your volume is up and the right speakers are selected.\n"
                "TEST: Paste this in PowerShell, you should hear a voice: "
                "Add-Type -AssemblyName System.Speech; "
                "(New-Object System.Speech.Synthesis.SpeechSynthesizer).Speak('test')"
                % data
            ))
            if not self.paused:
                self.set_status("ULTRON ONLINE")

    def on_close(self):
        self.stop_speech()
        self.root.destroy()


if __name__ == "__main__":
    window = tk.Tk()
    UltronApp(window)
    window.mainloop()