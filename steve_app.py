import json
import math
import os
import queue
import random
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
    "You are STEVE, a friendly, helpful AI assistant with a light, playful "
    "Minecraft-style sense of humor. Keep answers short, 1 to 3 sentences, "
    "and simple. Do not use emojis or special symbols. "
    "If you cannot do something, say so honestly."
)
SPEECH_RATE = 0        # -10 (slowest) to 10 (fastest)
SPEECH_VOLUME = 100    # 0 to 100
SPEAK_ANSWERS = True   # False = Steve stays silent
# -----------------------------------------------

BG = "#1b1b1b"
GRID = "#242424"
PANEL = "#111111"
WHITE = "#ffffff"
GREEN = "#55ff55"
YELLOW = "#ffff55"
AQUA = "#55ffff"
RED = "#ff5555"
GRAY = "#8b8b8b"
GRASS = "#5d9b3a"
DIRT = "#8b5a2b"
STONE = "#7f7f7f"
PLACEHOLDER = "Type here..."

# 8x8 pixel face: H = hair, S = skin, N = nose
HEAD_MAP = [
    "HHHHHHHH",
    "HHHHHHHH",
    "HSSSSSSH",
    "SSSSSSSS",
    "SSSSSSSS",
    "SSSNNSSS",
    "SSSSSSSS",
    "SSSSSSSS",
]


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


class SteveApp:
    def __init__(self, root):
        self.root = root
        self.root.title("STEVE")
        self.root.geometry("900x760")
        self.root.configure(bg=BG)
        self.root.minsize(700, 640)

        self.status = "STEVE ONLINE"
        self.indicator_text = ""
        self.paused = False
        self.busy = False
        self.rid = 0   # request id, used to drop answers after Pause
        self.sid = 0   # speech id, used to drop old speech events
        self.speech_proc = None
        self.placeholder_on = True
        self.q = queue.Queue()
        self.history = [{"role": "system", "content": PERSONALITY}]
        self.t0 = time.time()

        # mouse stuff
        self.mouse = None
        self.hop_start = None
        self.head_box = (0, 0, 0, 0)
        self.particles = []

        # pre-made colors so the pixels look a bit random but stay the same
        rng = random.Random(7)
        base_colors = {"H": "#4a2e14", "S": "#c28a5a", "N": "#a56e45"}
        self.head_cells = [
            [blend(base_colors[ch], "#000000", rng.uniform(0, 0.14)) for ch in row]
            for row in HEAD_MAP
        ]
        self.ground = [
            (blend(GRASS, "#000000", rng.uniform(0, 0.12)),
             blend(DIRT, "#000000", rng.uniform(0, 0.12)))
            for _ in range(40)
        ]

        self.build_ui()
        self.add_message("STEVE", "Online. Type a question below.")
        self.update_indicators()
        self.animate()
        self.poll()
        self.root.after(600, lambda: self.speak("Steve online."))
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)

    # ---------- building the screen ----------
    def build_ui(self):
        self.canvas = tk.Canvas(self.root, bg=BG, height=340, highlightthickness=0)
        self.canvas.pack(fill="both", expand=True)
        self.canvas.bind("<Motion>", self.on_motion)
        self.canvas.bind("<Leave>", self.on_leave)
        self.canvas.bind("<Button-1>", self.on_click)

        self.text = tk.Text(
            self.root, height=8, bg=PANEL, fg=WHITE, bd=4, relief="sunken",
            wrap="word", font=("Consolas", 11), padx=12, pady=8, cursor="arrow",
        )
        self.text.tag_config("you", foreground=AQUA, font=("Consolas", 11, "bold"))
        self.text.tag_config("steve", foreground=GREEN, font=("Consolas", 11, "bold"))
        self.text.config(state="disabled")
        self.text.pack(fill="x", padx=30, pady=(8, 8))

        self.entry = tk.Entry(
            self.root, bg=PANEL, fg="#7a7a7a", insertbackground=WHITE, bd=4,
            relief="sunken", font=("Consolas", 13),
        )
        self.entry.insert(0, PLACEHOLDER)
        self.entry.pack(fill="x", padx=30, ipady=7)
        self.entry.bind("<FocusIn>", self.entry_focus_in)
        self.entry.bind("<FocusOut>", self.entry_focus_out)
        self.entry.bind("<Return>", lambda e: self.send())

        row = tk.Frame(self.root, bg=BG)
        row.pack(pady=12)

        def make_button(text, command, base, width):
            b = tk.Button(
                row, text=text, command=command, bg=base, fg=WHITE,
                activebackground=blend(base, "#ffffff", 0.25),
                activeforeground=WHITE, bd=4, relief="raised",
                font=("Consolas", 12, "bold"), width=width, pady=4,
                cursor="hand2",
            )
            b.base = base
            b.bind("<Enter>", lambda e: b.config(bg=blend(b.base, "#ffffff", 0.25)))
            b.bind("<Leave>", lambda e: b.config(bg=b.base))
            return b

        self.mic_button = make_button("MIC", self.mic_pressed, STONE, 8)
        self.send_button = make_button("SEND", self.send, STONE, 10)
        self.pause_button = make_button("PAUSE", self.toggle_pause, "#b03a3a", 12)
        self.test_button = make_button("TEST SPEAKER", self.test_speaker, "#3f7f3f", 14)
        for b in (self.mic_button, self.send_button, self.pause_button, self.test_button):
            b.pack(side="left", padx=6)

    # ---------- placeholder text in the input box ----------
    def entry_focus_in(self, event):
        if self.placeholder_on:
            self.entry.delete(0, "end")
            self.entry.config(fg=WHITE)
            self.placeholder_on = False

    def entry_focus_out(self, event):
        if self.entry.get() == "":
            self.entry.insert(0, PLACEHOLDER)
            self.entry.config(fg="#7a7a7a")
            self.placeholder_on = True

    # ---------- status and indicators ----------
    def set_status(self, status):
        self.status = status
        self.update_indicators()

    def update_indicators(self):
        speaker = "SPEAKING" if self.status == "SPEAKING" else "READY"
        if not SPEAK_ANSWERS:
            speaker = "OFF"
        self.indicator_text = (
            "MIC: OFF     SPEAKER: %s     MODE: OFFLINE (local AI)" % speaker
        )

    # ---------- mouse ----------
    def over_head(self, x, y):
        x0, y0, x1, y1 = self.head_box
        return x0 <= x <= x1 and y0 <= y <= y1

    def on_motion(self, event):
        self.mouse = (event.x, event.y)
        self.canvas.config(cursor="hand2" if self.over_head(event.x, event.y) else "arrow")
        if random.random() < 0.35 and len(self.particles) < 200:
            self.spawn(event.x, event.y, 1, burst=False)

    def on_leave(self, event):
        self.mouse = None

    def on_click(self, event):
        if self.over_head(event.x, event.y):
            self.hop_start = time.time()
            self.spawn(event.x, event.y, 18, burst=True)
        else:
            self.spawn(event.x, event.y, 12, burst=True)

    def spawn(self, x, y, count, burst):
        colors = [GRASS, DIRT, STONE, "#c28a5a", "#4a2e14"]
        for _ in range(count):
            if burst:
                vx, vy = random.uniform(-3, 3), random.uniform(-6, -1)
                size, life = random.choice([4, 6, 8]), 35
            else:
                vx, vy = random.uniform(-0.5, 0.5), random.uniform(-1, 0)
                size, life = random.choice([3, 4]), 14
            self.particles.append(
                [x, y, vx, vy, size, random.choice(colors), life]
            )

    # ---------- drawing everything ----------
    def animate(self):
        c = self.canvas
        w = c.winfo_width()
        h = c.winfo_height()
        if w < 50:
            self.root.after(33, self.animate)
            return
        c.delete("all")
        t = time.time() - self.t0

        # faint grid background
        for x in range(0, w, 36):
            c.create_line(x, 0, x, h, fill=GRID)
        for y in range(0, h, 36):
            c.create_line(0, y, w, y, fill=GRID)

        # ground blocks
        gy = h - 36
        for i in range(w // 36 + 1):
            grass_c, dirt_c = self.ground[i % len(self.ground)]
            x = i * 36
            c.create_rectangle(x, gy, x + 36, gy + 36, fill=dirt_c,
                               outline=blend(dirt_c, "#000000", 0.35))
            c.create_rectangle(x, gy, x + 36, gy + 9, fill=grass_c,
                               outline=blend(grass_c, "#000000", 0.35))

        color, speed = {
            "STEVE ONLINE": (GREEN, 1.0),
            "THINKING": (YELLOW, 3.0),
            "SPEAKING": (AQUA, 2.0),
            "PAUSED": (RED, 0.0),
        }.get(self.status, (GREEN, 1.0))

        # status text with a Minecraft-style shadow
        c.create_text(w / 2 + 2, 28, text=self.status, fill="#2a2a2a",
                      font=("Consolas", 24, "bold"))
        c.create_text(w / 2, 26, text=self.status, fill=color,
                      font=("Consolas", 24, "bold"))
        c.create_text(w / 2, 56, text=self.indicator_text, fill=GRAY,
                      font=("Consolas", 11))

        # Steve's head
        cell = 18
        cx = w / 2
        base_cy = h / 2 + 10
        bob = math.sin(t * 2 * speed) * 4 if speed > 0 else 0
        shake = math.sin(t * 20) * 3 if self.status == "THINKING" else 0

        hop = 0
        if self.hop_start is not None:
            p = (time.time() - self.hop_start) / 0.6
            if p >= 1:
                self.hop_start = None
            else:
                hop = -abs(math.sin(p * math.pi)) * 70

        look_x = look_y = 0
        if self.mouse is not None and not self.paused:
            look_x = max(-1, min(1, (self.mouse[0] - cx) / 200))
            look_y = max(-1, min(1, (self.mouse[1] - base_cy) / 150))

        cy = base_cy + bob + hop
        ox = cx - 4 * cell + look_x * 10 + shake
        oy = cy - 4 * cell + look_y * 6
        self.head_box = (ox, oy, ox + 8 * cell, oy + 8 * cell)

        # shadow on the ground
        sw = max(20, 50 + hop * 0.3)
        c.create_oval(cx - sw, gy - 4, cx + sw, gy + 8, fill="#0d0d0d", outline="")

        for r, row in enumerate(self.head_cells):
            for col, fill in enumerate(row):
                x0 = ox + col * cell
                y0 = oy + r * cell
                c.create_rectangle(x0, y0, x0 + cell, y0 + cell, fill=fill,
                                   outline=blend(fill, "#000000", 0.25))

        # eyes (they follow the mouse)
        blink = (t % 4.0) < 0.15
        eyes_closed = self.paused or blink
        for col0 in (1, 5):
            ex = ox + col0 * cell
            ey = oy + 3 * cell
            if eyes_closed:
                c.create_rectangle(ex, ey + cell * 0.5, ex + 2 * cell,
                                   ey + cell * 0.5 + 4, fill="#2a1a0a", outline="")
            else:
                c.create_rectangle(ex, ey, ex + 2 * cell, ey + cell,
                                   fill="#ffffff", outline="#2a1a0a")
                if self.status == "THINKING":
                    lx, ly = math.cos(t * 3), -0.4
                else:
                    lx, ly = look_x, look_y * 0.5
                p_size = cell * 0.9
                px = ex + (lx + 1) / 2 * (2 * cell - p_size)
                py = ey + (cell - p_size) / 2 + ly * 3
                c.create_rectangle(px, py, px + p_size, py + p_size,
                                   fill="#3a4fd6", outline="")

        # mouth
        mx0 = ox + 2 * cell
        my0 = oy + 6 * cell + cell * 0.3
        if self.status == "SPEAKING":
            open_h = (0.3 + 0.7 * abs(math.sin(t * 10))) * cell
            c.create_rectangle(mx0, my0, mx0 + 4 * cell, my0 + open_h,
                               fill="#3a1a1a", outline="")
        elif self.status == "THINKING":
            c.create_rectangle(mx0 + 1.5 * cell, my0, mx0 + 2.5 * cell,
                               my0 + cell * 0.7, fill="#3a1a1a", outline="")
        else:
            c.create_rectangle(mx0, my0, mx0 + 4 * cell, my0 + 4,
                               fill="#3a1a1a", outline="")

        # hover hint
        if self.mouse is not None and self.over_head(*self.mouse) and not self.paused:
            c.create_text(cx + 2, oy - 12, text="Click me!", fill="#2a2a2a",
                          font=("Consolas", 14, "bold"))
            c.create_text(cx, oy - 14, text="Click me!", fill=YELLOW,
                          font=("Consolas", 14, "bold"))

        # flying blocks
        alive = []
        for p in self.particles:
            p[0] += p[2]
            p[1] += p[3]
            p[3] += 0.5
            p[6] -= 1
            if p[6] > 0 and p[1] < h:
                s = p[4]
                c.create_rectangle(p[0], p[1], p[0] + s, p[1] + s, fill=p[5],
                                   outline=blend(p[5], "#000000", 0.35))
                alive.append(p)
        self.particles = alive

        self.root.after(33, self.animate)

    # ---------- showing the conversation ----------
    def add_message(self, who, message):
        self.text.config(state="normal")
        tag = "you" if who == "YOU" else "steve"
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
            "STEVE",
            "The microphone is switched off in this version. "
            "For now, please type your question below.",
        )

    def test_speaker(self):
        if self.paused:
            return
        self.speak("Speaker test. Hello. I am Steve. All systems are online.")

    def toggle_pause(self):
        if not self.paused:
            self.paused = True
            self.rid += 1  # any answer still on its way gets thrown away
            if self.busy:
                self.busy = False
                self.history.pop()  # remove the unanswered question
            self.stop_speech()
            self.entry.config(state="disabled")
            self.pause_button.base = "#2f8f2f"
            self.pause_button.config(text="RESUME", bg="#2f8f2f")
            self.set_status("PAUSED")
        else:
            self.paused = False
            self.entry.config(state="normal")
            self.pause_button.base = "#b03a3a"
            self.pause_button.config(text="PAUSE", bg="#b03a3a")
            self.set_status("STEVE ONLINE")

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
                "FIX: Close Steve and start it again: python steve_app.py\n"
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
            "$s.Rate = %d; $s.Volume = %d; $s.Speak($env:STEVE_TEXT)"
            % (SPEECH_RATE, SPEECH_VOLUME)
        )
        env = os.environ.copy()
        env["STEVE_TEXT"] = text.replace("*", "").replace("#", "")
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
            self.add_message("STEVE", data)
            if SPEAK_ANSWERS:
                self.speak(data)
            else:
                self.set_status("STEVE ONLINE")
        elif kind == "error":
            if ident != self.rid:
                return
            self.busy = False
            self.history.pop()
            self.add_message("STEVE", data)
            self.set_status("STEVE ONLINE")
        elif kind == "spoken":
            if ident == self.sid and not self.paused:
                self.set_status("STEVE ONLINE")
        elif kind == "speech_error":
            if ident != self.sid:
                return
            self.add_message("STEVE", (
                "WHAT WENT WRONG: I could not speak.\n"
                "WHY: Windows speech failed. Details: %s\n"
                "FIX: Check your volume is up and the right speakers are selected.\n"
                "TEST: Paste this in PowerShell, you should hear a voice: "
                "Add-Type -AssemblyName System.Speech; "
                "(New-Object System.Speech.Synthesis.SpeechSynthesizer).Speak('test')"
                % data
            ))
            if not self.paused:
                self.set_status("STEVE ONLINE")

    def on_close(self):
        self.stop_speech()
        self.root.destroy()


if __name__ == "__main__":
    window = tk.Tk()
    SteveApp(window)
    window.mainloop()