from __future__ import annotations

import os
import queue
import subprocess
import sys

os.environ.setdefault("TK_SILENCE_DEPRECATION", "1")

import threading
import time
import tkinter as tk
from pathlib import Path

_ROOT = Path(__file__).resolve().parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from dyoe2_engine import Dyoe2Engine

from autotype.featherine import human_plan
from autotype.host import focus_roblox, press_enter, roblox_focused, run_capture, stop_capture, tap_key
from autotype.session import (
    BoardWatch,
    MatchSession,
    already_used_text,
    header_is_ours,
    names_match,
    rejected_text,
    header_is_turn,
    speaker_from_header,
)

DICT_PATH = _ROOT / "dict (4).txt"
DATA = _ROOT / "data"
CASUAL_PATH = DATA / "casual-prefixes.txt"
TRAPS_PATH = DATA / "traps.txt"
SPECIAL_PATH = DATA / "special-traps.txt"
NO_PLURAL_PATH = DATA / "no-plural.txt"
HELPER = Path.home() / ".last-letter-helper"
MODE_PATH = HELPER / "autotype_mode.txt"
SPAM_PATH = HELPER / "autotype_spam.txt"

INK = "#0b0b0a"
BONE = "#f1efe7"
MUTED = "#98958b"
CARD = "#11110f"
LINE = "#2c2c28"

PANEL_BIN = _ROOT / "autotype" / "llpanel"

class NativeFace:

    def __init__(self, proc: subprocess.Popen) -> None:
        self.proc = proc
        self._lock = threading.RLock()
        self._values: dict[str, str] = {}

    def send(self, key: str, value: str = "") -> None:
        text = str(value).replace("\t", " ").replace("\n", " ")
        line = f"{key}\t{text}\n" if text else f"{key}\n"
        with self._lock:
            if key != "LOG" and self._values.get(key) == text:
                return
            self._values[key] = text
            if self.proc.poll() is not None or self.proc.stdin is None:
                return
            try:
                self.proc.stdin.write(line)
                self.proc.stdin.flush()
            except (BrokenPipeError, OSError):
                pass

    def close(self) -> None:
        if self.proc.poll() is None:
            self.proc.kill()

def _mono() -> str:
    if sys.platform == "darwin":
        return "Menlo"
    if sys.platform == "win32":
        return "Consolas"
    return "DejaVu Sans Mono"

class AutotypeApp:
    def __init__(self, root: tk.Tk | None = None, *, face: NativeFace | None = None,
                 start_services: bool = True) -> None:
        self.root = root
        self.face = face
        self.engine = Dyoe2Engine()
        self.session = MatchSession(self.engine)
        self.watch = BoardWatch()
        self.ready = False
        self.armed = False
        self._want_arm = True
        self.typing = False
        self._stop = threading.Event()
        self._gen = 0
        self._typed_word = ""
        self._typed_suffix = ""
        self._erasing = False
        self._retried = ""
        self._shown = ""
        self._count = 0
        self._roblox = ""
        self._last_note = ""
        self._status_at = 0.0
        self._lock = threading.Lock()
        self._queue: queue.Queue = queue.Queue(maxsize=128)
        self._name = ""
        self._aliases: set[str] = set()
        self._last_frame: dict = {}
        self._current_turn = ""
        self._type_cancel = threading.Event()
        self._typing_thread: threading.Thread | None = None
        self._typing_prompt = ""
        self._aborted_prompt = ""
        self._theirs_streak = 0
        self._input_length = 0
        self._needs_clear = False
        self._input_problem = ""
        mode = self._load_text(MODE_PATH, "casual").lower()
        if mode not in ("casual", "pro", "spam"):
            mode = "casual"
        self._mode = mode
        self._spam = self._load_text(SPAM_PATH, "")
        self._spam_shown = False
        self.session.set_spam_suffixes(self._spam)
        self.session.set_mode(mode)
        if self.face is not None:
            self.face.send("NAME", self._name)
            self.face.send("MODE", self._mode.upper())
            if self._spam:
                self.face.send("SPAMTEXT", self._spam)
            self.face.send("ARMED", "0")
        else:
            self._build()
            self._paint_mode()
        self._set_status("LOOKING FOR ROBLOX")
        self._note("Reading the dictionary.")
        if start_services:
            threading.Thread(target=self._load, daemon=True).start()
            threading.Thread(
                target=run_capture,
                args=(self._stop, self._enqueue_frame, self._enqueue_roblox, lambda: self._name),
                daemon=True,
            ).start()
            if self.root is not None:
                self.root.after(8, self._drain)

    def _load_text(self, path: Path, fallback: str) -> str:
        try:
            return path.read_text(encoding="utf-8").strip() or fallback
        except OSError:
            return fallback

    def _save_text(self, path: Path, text: str) -> None:
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text.strip() + "\n", encoding="utf-8")
        except OSError:
            pass

    def _build(self) -> None:
        win = self.root
        win.title("Last Letter")
        win.geometry(self._place())
        try:
            win.attributes("-topmost", True)
        except tk.TclError:
            pass
        mono = _mono()
        win.option_add("*Font", f"{mono} 12")

        root = tk.Frame(win, bg=INK, highlightthickness=0)
        root.pack(fill="both", expand=True)

        top = tk.Frame(root, bg=INK)
        top.pack(fill="x", padx=16, pady=(14, 0))
        tk.Label(top, text="LAST LETTER", bg=INK, fg=BONE, font=("Helvetica", 20, "bold")).pack(side="left")
        self.used_var = tk.StringVar(value="USED 0")
        tk.Label(top, textvariable=self.used_var, bg=INK, fg=MUTED, font=(mono, 11)).pack(side="right")

        self.status_var = tk.StringVar(value="LOOKING FOR ROBLOX")
        self.status = tk.Label(root, textvariable=self.status_var, bg=INK, fg=MUTED, font=(mono, 11), anchor="w")
        self.status.pack(fill="x", padx=16, pady=(6, 0))

        name_row = tk.Frame(root, bg=INK)
        name_row.pack(fill="x", padx=16, pady=(12, 0))
        tk.Label(name_row, text="YOU", bg=INK, fg=MUTED, font=(mono, 11)).pack(side="left")
        self.name_var = tk.StringVar(value=self._name)
        self.name_var.trace_add("write", self._on_name)
        name = tk.Entry(
            name_row,
            textvariable=self.name_var,
            bg=CARD,
            fg=BONE,
            insertbackground=BONE,
            relief="flat",
            font=(mono, 13),
        )
        name.pack(side="left", fill="x", expand=True, padx=(8, 0), ipady=4)

        modes = tk.Frame(root, bg=INK)
        modes.pack(fill="x", padx=16, pady=(12, 0))
        self.mode_buttons = {}
        for mode, label in (("casual", "CASUAL"), ("pro", "PRO"), ("spam", "SPAM")):
            btn = tk.Label(modes, text=label, bg=CARD, fg=BONE, font=(mono, 12), padx=8, pady=8)
            btn.pack(side="left", fill="x", expand=True, padx=(0, 6) if mode != "spam" else 0)
            btn.bind("<Button-1>", lambda _e, m=mode: self._set_mode(m))
            self.mode_buttons[mode] = btn

        self.spam_frame = tk.Frame(root, bg=INK)
        tk.Label(self.spam_frame, text="HYBRID SUFFIXES", bg=INK, fg=MUTED, font=(mono, 10)).pack(anchor="w")
        self.spam_var = tk.StringVar(value=self._spam)
        self.spam_var.trace_add("write", self._on_spam)
        spam = tk.Entry(
            self.spam_frame,
            textvariable=self.spam_var,
            bg=CARD,
            fg=BONE,
            insertbackground=BONE,
            relief="flat",
            font=(mono, 14),
        )
        spam.pack(fill="x", pady=(4, 0), ipady=6)
        tk.Label(
            self.spam_frame,
            text="Comma / space separated — shortest word per ending, then trap priority",
            bg=INK,
            fg=MUTED,
            font=(mono, 10),
        ).pack(anchor="w", pady=(4, 0))
        if self._mode == "spam":
            self._show_spam_field(True)

        self.phase_var = tk.StringVar(value="R1   ·   PHASE 1")
        tk.Label(root, textvariable=self.phase_var, bg=INK, fg=BONE, font=(mono, 12), anchor="w").pack(
            fill="x", padx=16, pady=(10, 0)
        )
        confirm = tk.Button(name_row, text="It's your turn?", command=self._confirm_turn,
                            bg=CARD, fg=BONE, relief="flat", font=(mono, 10))
        confirm.pack(side="right", padx=(8, 0))

        self.turn_var = tk.StringVar(value="WAITING")
        tk.Label(root, textvariable=self.turn_var, bg=INK, fg=BONE, font=(mono, 12), anchor="w").pack(
            fill="x", padx=16, pady=(2, 0)
        )

        card = tk.Frame(root, bg=CARD, highlightbackground=LINE, highlightthickness=1)
        card.pack(fill="both", expand=True, padx=16, pady=12)
        tk.Label(card, text="PROMPT", bg=CARD, fg=MUTED, font=(mono, 10)).pack(anchor="w", padx=14, pady=(12, 0))
        self.prompt_var = tk.StringVar(value="—")
        self.prompt_label = tk.Label(card, textvariable=self.prompt_var, bg=CARD, fg=BONE, font=("Helvetica", 28, "bold"))
        self.prompt_label.pack(anchor="w", padx=14)
        tk.Label(card, text="CHOICES", bg=CARD, fg=MUTED, font=(mono, 10)).pack(anchor="w", padx=14, pady=(8, 0))
        self.choice_vars = []
        for index in range(3):
            var = tk.StringVar(value="—")
            color = BONE if index == 0 else MUTED
            tk.Label(card, textvariable=var, bg=CARD, fg=color, font=(mono, 13), anchor="w").pack(fill="x", padx=14)
            self.choice_vars.append(var)
        foot = tk.Frame(card, bg=CARD)
        foot.pack(fill="x", padx=14, pady=(10, 12))
        tk.Label(foot, text="TYPE", bg=CARD, fg=MUTED, font=(mono, 10)).grid(row=0, column=0, sticky="w")
        tk.Label(foot, text="TRAP", bg=CARD, fg=MUTED, font=(mono, 10)).grid(row=0, column=1, sticky="w", padx=(16, 0))
        self.type_var = tk.StringVar(value="—")
        self.trap_var = tk.StringVar(value="—")
        tk.Label(foot, textvariable=self.type_var, bg=CARD, fg=BONE, font=(mono, 14)).grid(row=1, column=0, sticky="w")
        tk.Label(foot, textvariable=self.trap_var, bg=CARD, fg=MUTED, font=(mono, 14)).grid(
            row=1, column=1, sticky="w", padx=(16, 0)
        )

        actions = tk.Frame(root, bg=INK)
        actions.pack(fill="x", padx=16)
        self.arm_btn = tk.Label(actions, text="ARM", bg=CARD, fg=BONE, font=(mono, 12), padx=8, pady=8)
        self.arm_btn.pack(side="left", fill="x", expand=True, padx=(0, 6))
        self.arm_btn.bind("<Button-1>", lambda _e: self._toggle_arm())
        new_btn = tk.Label(actions, text="NEW GAME", bg=CARD, fg=BONE, font=(mono, 12), padx=8, pady=8)
        new_btn.pack(side="left", fill="x", expand=True)
        new_btn.bind("<Button-1>", lambda _e: self._new_game())

        self.log = tk.Text(
            root,
            height=6,
            bg=INK,
            fg=MUTED,
            relief="flat",
            font=(mono, 11),
            highlightthickness=0,
        )
        self.log.pack(fill="x", padx=16, pady=(10, 14))
        self.log.configure(state="disabled")
        win.protocol("WM_DELETE_WINDOW", self.close)

    def _place(self) -> str:
        width, height = 420, 700
        try:
            screen_w = self.root.winfo_screenwidth()
            x = max(0, screen_w - width - 28)
        except tk.TclError:
            x = 40
        return f"{width}x{height}+{x}+36"

    def _put_event(self, kind: str, payload) -> None:
        # Bounded backpressure preserves every turn edge and final word frame.
        while not self._stop.is_set():
            try:
                self._queue.put((kind, payload), timeout=0.05)
                return
            except queue.Full:
                continue

    def _enqueue_frame(self, frame: dict) -> None:
        self._put_event("FRAME", frame)

    def _enqueue_roblox(self, status: str) -> None:
        self._put_event("ROBLOX", status)

    def _emit(self, kind: str, payload) -> None:
        self._put_event(kind, payload)

    def _process_event(self, kind: str, payload) -> None:
        # Only this controller mutates match state, on both native and Tk UIs.
        if kind == "FRAME":
            self._handle_frame(payload)
        elif kind == "ROBLOX":
            self._apply_roblox(payload)
        elif kind == "LOADED":
            self._apply_loaded(payload)
        elif kind == "LOG":
            self._note(payload)
        elif kind == "STATUS":
            self._set_status(payload)
        elif kind == "ACTION":
            if not self.handle(*payload):
                self._stop.set()
        elif kind == "SUBMIT":
            gen, word, input_length = payload
            if gen == self._gen:
                try:
                    if self._current_turn != "ours" or self._roblox != "up" or not roblox_focused():
                        raise OSError("Roblox lost focus or the turn changed before submission")
                    # Record and submit on the controller so a capture cannot
                    # process the acceptance before this word is registered.
                    self._typed_word = word
                    self.watch.typed = word
                    press_enter()
                except Exception as exc:
                    self._process_event("TYPE_DONE", (gen, False, input_length, f"Typing failed: {exc}"))
        elif kind == "TYPE_DONE":
            gen, sent, input_length, message = payload
            # Cancelling bumps the generation, so the worker's completion is
            # stale. Still drop the prompt latch, or the same turn never retries.
            if gen != self._gen:
                if not sent and not self.typing and not self.watch.typed and not self._typed_word and self.armed:
                    self.watch.played = ""
                    if self._typing_prompt:
                        self._aborted_prompt = self._typing_prompt
                return
            self._input_length = input_length
            self.typing = False
            if not sent:
                self.watch.played = ""
                self.watch.typed = ""
                self._typed_word = ""
                # A partial input needs clearing before another attempt.
                if input_length:
                    self._needs_clear = True
                    self.armed = False
                    self._want_arm = False
                    self._paint_arm()
                    self._note("Partial input left in Roblox. ARM to clear and retry.")
                elif self.armed and not (message or "").startswith("Typing failed:"):
                    if self._typing_prompt:
                        self._aborted_prompt = self._typing_prompt
            if message:
                self._note(message)
                if message.startswith("Typing failed:"):
                    self._input_problem = message
                    self.armed = False
                    self._want_arm = False
                    self._aborted_prompt = ""
                    self._paint_arm()
                    self._set_status("KEYBOARD CONTROL ISN'T AVAILABLE")
        elif kind == "ERASED":
            gen, prompt, success = payload
            if gen == self._gen:
                self._erasing = False
                if success and self._current_turn == "ours":
                    self._needs_clear = False
                    self.watch.rearm(prompt, time.monotonic())
                elif not success:
                    self.armed = False
                    self._want_arm = False
                    self._paint_arm()
                    self._note("Couldn't clear the input. Clear it in Roblox, then ARM.")

    def _drain(self) -> None:
        for _ in range(128):
            try:
                kind, payload = self._queue.get_nowait()
            except queue.Empty:
                break
            self._process_event(kind, payload)
        if not self._stop.is_set():
            self.root.after(8, self._drain)

    def _set_status(self, text: str) -> None:
        if self.face is not None:
            self.face.send("STATUS", text)
            return
        self.status_var.set(text)
        alarm = text.startswith("ROBLOX ISN'T")
        self.status.configure(fg=BONE if alarm else MUTED)

    def _note(self, text: str) -> None:
        if not text or text == self._last_note:
            return
        self._last_note = text
        if self.face is not None:
            self.face.send("LOG", text)
            return
        self.log.configure(state="normal")
        self.log.insert("end", text + "\n")
        lines = int(self.log.index("end-1c").split(".")[0])
        if lines > 8:
            self.log.delete("1.0", f"{lines - 7}.0")
        self.log.configure(state="disabled")
        self.log.see("end")

    def _paint_mode(self) -> None:
        if self.face is not None:
            self.face.send("MODE", self._mode.upper())
            return
        for mode, btn in self.mode_buttons.items():
            on = mode == self._mode
            btn.configure(bg=BONE if on else CARD, fg=INK if on else BONE)

    def _paint_arm(self) -> None:
        if self.face is not None:
            self.face.send("ARMED", "1" if self.armed else "0")
            return
        self.arm_btn.configure(
            text="ARMED" if self.armed else "ARM",
            bg=BONE if self.armed else CARD,
            fg=INK if self.armed else BONE,
        )

    def _show_spam_field(self, show: bool) -> None:
        if self.face is not None:
            return
        if show and not self._spam_shown:
            self.spam_frame.pack(fill="x", padx=16, pady=(10, 0), after=self.mode_buttons["casual"].master)
            self._spam_shown = True
        elif not show and self._spam_shown:
            self.spam_frame.pack_forget()
            self._spam_shown = False

    def _show_phase(self) -> None:
        if self._mode == "spam":
            endings = " ".join(self.engine.hybrid_suffixes) or "TYPE ENDINGS"
            text = f"SPAM   ·   {endings}"
        else:
            phase = self.session.engine.phase
            text = f"R{self.session.round}   ·   PHASE {phase}"
        if self.face is not None:
            self.face.send("PHASE", text)
            return
        self.phase_var.set(text)

    def _refresh_used(self) -> None:
        label = f"USED {len(self.engine.used_words)}"
        if self.face is not None:
            self.face.send("USED", label)
        else:
            self.used_var.set(label)
        self._show_phase()

    def _load(self) -> None:
        try:
            with self._lock:
                count = self.engine.load_from_paths(
                    DICT_PATH,
                    casual_path=CASUAL_PATH,
                    traps_path=TRAPS_PATH,
                    special_path=SPECIAL_PATH,
                    no_plural_path=NO_PLURAL_PATH,
                    validate_giveable=False,
                )
                self.session.set_mode(self._mode)
                self.session.set_spam_suffixes(self._spam)
            self._emit("LOADED", count)
        except Exception as exc:
            self._emit("STATUS", "DICTIONARY FAILED")
            self._emit("LOG", str(exc))

    def _apply_loaded(self, count: int) -> None:
        self._count = count
        self.ready = True
        self._refresh_used()
        if self._roblox == "up":
            self.armed = self._want_arm
            self._paint_arm()
            self._set_status(f"READY  ·  {count:,} WORDS")
            self._note("Armed. It reads the tiles and types on your turn.")
        elif self._roblox == "hidden":
            self._set_status("ROBLOX ISN'T VISIBLE")
        elif self._roblox == "down":
            self._set_status("ROBLOX ISN'T AVAILABLE")
        elif self._roblox == "unsupported":
            self._set_status("CAPTURE ISN'T AVAILABLE")
        else:
            self._set_status("LOOKING FOR ROBLOX")

    def _apply_roblox(self, status: str) -> None:
        if status == self._roblox:
            return
        self._roblox = status
        if status != "up":
            self._cancel_typing()
            self._typed_word = ""
            self._needs_clear = False
            self.watch.reset()
            self.armed = False
            self._paint_arm()
            self._last_frame = {}
            self._current_turn = ""
            self._aborted_prompt = ""
            self._theirs_streak = 0
            self._show_turn("", "")
            if status == "down":
                self._set_status("ROBLOX ISN'T AVAILABLE")
                self._note("ROBLOX ISN'T AVAILABLE")
            elif status == "unsupported":
                self._set_status("CAPTURE ISN'T AVAILABLE")
                self._note("Screen capture or keyboard control is unavailable. See the setup instructions.")
            else:
                self._set_status("ROBLOX ISN'T VISIBLE")
                extra = " Allow Screen Recording for this app." if sys.platform == "darwin" else ""
                self._note("Roblox is open, but its window can't be read." + extra)
            return
        if self.ready and self._want_arm:
            self.armed = True
            self._paint_arm()
        if self.ready:
            self._set_status(f"READY  ·  {self._count:,} WORDS")
            self._note("Roblox is on screen.")

    def _handle_frame(self, frame: dict) -> None:
        if self._roblox != "up":
            return
        self._last_frame = dict(frame)
        now = time.monotonic()
        if self.ready and now - self._status_at > 0.3:
            self._status_at = now
            self._set_status("KEYBOARD CONTROL ISN'T AVAILABLE" if self._input_problem
                             else f"READ {frame.get('ms', 0)}ms  ·  {self._count:,} WORDS")
        header = frame.get("header", "")
        speaker = speaker_from_header(header)
        full = bool(frame.get("full", True))
        board = frame.get("prompt", "")
        whose = ""
        if header_is_turn(header) and speaker:
            ours = header_is_ours(self._name, header) or any(names_match(alias, speaker) for alias in self._aliases)
            whose = "ours" if ours else "theirs"
        if whose == "theirs":
            self._theirs_streak += 1
        elif whose == "ours":
            self._theirs_streak = 0
        # One bad header read used to abort the key thread and leave the prompt
        # latched, so the turn sat on screen until a key changed the picture.
        if self._header_blip(whose, board) or self._prefix_still_ours(whose, board, full):
            whose = "ours"
        self._current_turn = whose
        self._show_turn(whose, header)
        if not self.ready:
            return
        error = frame.get("error") or ""
        if rejected_text(error) and self._typed_word and not self._erasing and whose == "ours":
            prompt = self.watch.played or ""
            if not board or not prompt or board.startswith(prompt):
                self._schedule_retry(self._typed_word, used=already_used_text(error))
        if self._erasing:
            if whose == "theirs":
                self._cancel_typing()
            else:
                return
        event = self.watch.observe(board, whose, complete=full, tiles=int(frame.get("tiles") or 0), now=now)
        self._show_prompt(board or ("—" if full else "READING…"))
        if event["accepted"] and self._typed_word:
            word = self._typed_word
            self._typed_word = ""
            with self._lock:
                self.session.commit_play(word)
            self._refresh_used()
            self._note(f"OURS  {word}")
        elif event["rejected"] and self._typed_word:
            self._schedule_retry(self._typed_word, used=False)
        prompt = event["play"]
        if event.get("ending"):
            partials = event.get("partials") or []
            with self._lock:
                kept = self.session.recover_partial(partials, event["ending"], event.get("given", ""))
            self.watch.forget_partials()
            if kept:
                self._refresh_used()
                self._note(f"THEIRS  {kept}")
            elif partials:
                self._note(f"THEIRS  {max(partials, key=len)}  (couldn't confirm full word)")
        self._reap_typing()
        # Keep observing while keys are sent so a fast acceptance cannot be lost.
        if self.typing:
            if prompt and prompt != (self._typing_prompt or self.watch.played):
                # The rest of a multi-letter prefix arrived after a shorter read.
                self._cancel_typing(release=True)
                self._aborted_prompt = ""
            elif whose == "theirs" and not self._typed_word:
                self._cancel_typing(release=True)
                self._note("Turn changed. Typing stopped.")
                return
            else:
                return
        if not prompt:
            self._resume_aborted(board, whose)
            return
        if prompt != self._shown:
            self._retried = ""
            self._shown = prompt
            self._present(prompt)
        if self.armed and not self._erasing and prompt != self.watch.played:
            self._aborted_prompt = ""
            self._start_typing(prompt)

    def _show_turn(self, whose: str, header: str) -> None:
        if not header_is_turn(header):
            text = "IN LOBBY" if "play" in header.lower() else "WATCHING"
        elif whose == "ours":
            text = "YOUR TURN"
        elif whose == "theirs":
            speaker = speaker_from_header(header)
            text = f"THEIR TURN  ·  {speaker.upper()}" if speaker else "THEIR TURN"
        else:
            text = "READING TURN"
        if self.face is not None:
            self.face.send("TURN", text)
            return
        self.turn_var.set(text)

    def _show_prompt(self, text: str) -> None:
        shown = text or "—"
        if self.face is not None:
            self.face.send("PROMPT", shown)
            return
        self.prompt_var.set(shown)
        size = 15 if len(shown) > 10 else 28
        self.prompt_label.configure(font=("Helvetica", size, "bold"))

    def _present(self, prompt: str) -> None:
        with self._lock:
            words = self.session.choices(prompt, 3)
            word, suffix, trap, _phase = self.session.choose(prompt)
        self._show_phase()
        labels = [f"{index + 1}  {words[index]}" if index < len(words) else "—" for index in range(3)]
        if self.face is not None:
            for index, label in enumerate(labels, 1):
                self.face.send(f"C{index}", label)
            self.face.send("TYPE", suffix or "—")
            self.face.send("TRAP", trap or "—")
        else:
            for index, label in enumerate(labels):
                self.choice_vars[index].set(label)
            self.type_var.set(suffix or "—")
            self.trap_var.set(trap or "—")
        self._note(f"{prompt}  →  {word}" if word else f"No word for {prompt}")

    def _start_typing(self, prompt: str) -> None:
        if self.typing or self._erasing:
            return
        thread = self._typing_thread
        if thread is not None and thread.is_alive():
            return
        if self._roblox != "up":
            self._set_status("ROBLOX ISN'T AVAILABLE")
            self._note("ROBLOX ISN'T AVAILABLE")
            return
        with self._lock:
            word, suffix, trap, _phase = self.session.choose(prompt)
        self._show_phase()
        if self.face is not None:
            self.face.send("TYPE", suffix or "—")
            self.face.send("TRAP", trap or "—")
        else:
            self.type_var.set(suffix or "—")
            self.trap_var.set(trap or "—")
        if not word or not suffix:
            self.watch.played = prompt
            self._aborted_prompt = ""
            return
        self._aborted_prompt = ""
        self.watch.played = prompt
        self._typed_suffix = suffix
        self.typing = True
        self._typing_prompt = prompt
        self._input_length = 0
        self._type_cancel = threading.Event()
        gen = self._gen
        thread = threading.Thread(target=self._type_suffix, args=(gen, word, suffix, self._type_cancel), daemon=True)
        self._typing_thread = thread
        thread.start()

    def _prefix_still_ours(self, whose: str, board: str, full: bool) -> bool:
        # A mismatched username while these tiles are still the prefix we are
        # typing. Multi-letter rows also miss a tile for a frame; that shorter
        # read is the same prefix, not their turn.
        if whose != "theirs" or not self.typing or self._typed_word or self.watch.typed:
            return False
        if not full or "?" in (board or ""):
            return False
        ready = self.watch._prompt((board or "").lower())
        current = self._typing_prompt or self.watch.played
        if not ready or not current:
            return False
        # A longer board is a new prefix or their word, not a missed tile.
        return ready == current or current.startswith(ready)

    def _header_blip(self, whose: str, board: str) -> bool:
        # A single mismatched username while the tiles are still our prefix.
        if whose != "theirs" or self._theirs_streak >= 2:
            return False
        if self.watch.typed or self._typed_word:
            return False
        if self.watch.turn != "ours":
            return False
        ready = self.watch._prompt((board or "").lower())
        current = self.watch.played or self._typing_prompt or self.watch.pending
        return bool(ready and current and ready == current)

    def _reap_typing(self) -> None:
        thread = self._typing_thread
        if not self.typing or thread is None or thread.is_alive():
            return
        self.typing = False
        if self.watch.typed or self._typed_word:
            return
        self._aborted_prompt = self.watch.played or self._typing_prompt
        self.watch.played = ""

    def _resume_aborted(self, board: str, whose: str) -> None:
        # The prompt was already ours. Type it again without waiting for a new
        # tile change or another two identical reads.
        if whose != "ours" or not self.armed or self.typing or self._erasing:
            return
        if self.watch.typed or self._typed_word or not self._aborted_prompt:
            return
        thread = self._typing_thread
        if thread is not None and thread.is_alive():
            return
        ready = self.watch._prompt((board or "").lower())
        if not ready:
            return
        if ready != self._aborted_prompt:
            # One tile of a multi-letter prefix dropped out. Keep the prompt.
            if self._aborted_prompt.startswith(ready):
                return
            self._aborted_prompt = ""
            return
        self.watch.played = ""
        self._start_typing(ready)

    def _cancel_typing(self, *, release: bool = False) -> None:
        self._type_cancel.set()
        self._gen += 1
        self.typing = False
        self._erasing = False
        self._type_cancel = threading.Event()
        if release and not self.watch.typed and not self._typed_word:
            prompt = self.watch.played or self._typing_prompt
            self.watch.played = ""
            if prompt:
                self._aborted_prompt = prompt

    def _schedule_retry(self, word: str, *, used: bool) -> None:
        if not word or self._erasing or word == self._retried:
            return
        prompt = self.watch.played or self._shown
        self._retried = word
        self._typed_word = ""
        self.watch.typed = ""
        with self._lock:
            if used:
                self.session.engine.mark_used(word)
            else:
                self.session.engine.mark_rejected(word)
        self._refresh_used()
        self._note(f"ALREADY USED  {word}" if used else f"REJECTED  {word}")
        self._clear_input(prompt)

    def _clear_input(self, prompt: str) -> None:
        self._erasing = True
        gen = self._gen
        cancel = self._type_cancel
        # Clear the attempted suffix, keeping the game's starting prefix.
        input_length = self._input_length or len(self._typed_suffix)
        def work() -> None:
            success = False
            try:
                if focus_roblox():
                    for _ in range(input_length):
                        if gen != self._gen or self._stop.is_set() or cancel.is_set():
                            return
                        if not roblox_focused():
                            return
                        tap_key("back", "\b", 0.012)
                        if cancel.wait(0.02):
                            return
                    success = True
            except Exception as exc:
                self._emit("LOG", f"Couldn't clear input: {exc}")
            finally:
                self._emit("ERASED", (gen, prompt, success))
        threading.Thread(target=work, daemon=True).start()

    def _type_suffix(self, gen: int, word: str, suffix: str, cancel: threading.Event) -> None:
        sent = False
        input_length = 0
        message = ""
        try:
            if gen != self._gen or cancel.is_set() or self._stop.is_set():
                return
            if not focus_roblox():
                message = "Couldn't focus Roblox. Typing will retry on your turn."
                return
            plan = human_plan(suffix, self._name)
            previous_hold = 0.0
            for step in plan.steps:
                if cancel.wait(max(0.0, step.delay - previous_hold)) or gen != self._gen or self._stop.is_set():
                    return
                if not roblox_focused():
                    message = "Roblox lost focus. Typing stopped."
                    return
                # Key holds are included in the plan's interval, rather than
                # added to it; the first key has no artificial lead-in.
                tap_key(step.kind, step.key, 0.008)
                previous_hold = 0.008
                input_length = len(step.typed)
            if cancel.wait(plan.end_pause) or gen != self._gen or self._stop.is_set():
                return
            if not roblox_focused():
                message = "Roblox lost focus before submission."
                return
            self._emit("SUBMIT", (gen, word, input_length))
            sent = True
        except Exception as exc:
            message = f"Typing failed: {exc}"
        finally:
            self._emit("TYPE_DONE", (gen, sent, input_length, message))

    def _toggle_arm(self) -> None:
        if not self.ready:
            return
        if self._roblox != "up" and not self.armed:
            if self._roblox == "hidden":
                self._set_status("ROBLOX ISN'T VISIBLE")
                self._note("Roblox is open, but the window can't be read.")
            else:
                self._set_status("ROBLOX ISN'T AVAILABLE")
                self._note("ROBLOX ISN'T AVAILABLE")
            return
        self.armed = not self.armed
        self._want_arm = self.armed
        self._paint_arm()
        self._note("Armed." if self.armed else "Disarmed.")
        if not self.armed and (self.typing or self._erasing):
            self._needs_clear = True
            self._cancel_typing()
        if self.armed and self._needs_clear:
            if self._current_turn == "ours":
                self._clear_input(self._typing_prompt)
            else:
                self._needs_clear = False
        if self.armed and self._shown and not self.typing and not self.watch.typed:
            self._input_problem = ""
            self.watch.played = ""

    def _set_mode(self, mode: str) -> None:
        self._mode = mode
        with self._lock:
            self.session.set_mode(mode)
        self._save_text(MODE_PATH, mode)
        self._paint_mode()
        self._show_spam_field(mode == "spam")
        self._show_phase()
        if self._shown:
            self._present(self._shown)

    def _set_name(self, name: str) -> None:
        name = name.strip()
        if name == self._name:
            return
        self._name = name
        self._aliases.clear()
        self._recheck_identity()

    def _recheck_identity(self) -> None:
        frame = self._last_frame
        if not frame or self._roblox != "up":
            return
        speaker = speaker_from_header(frame.get("header", ""))
        if names_match(self._name, speaker) or speaker in self._aliases:
            prompt = frame.get("prompt", "")
            if self._current_turn != "ours" and self.watch._prompt(prompt) and not self.typing:
                self.watch.rearm(prompt, time.monotonic())
            self._handle_frame(frame)

    def _on_name(self, *_args) -> None:
        self._set_name(self.name_var.get())

    def _confirm_turn(self) -> None:
        if self._roblox != "up":
            self._note("Roblox must be visible to learn your username.")
            return
        speaker = speaker_from_header(self._last_frame.get("header", ""))
        if not speaker:
            self._note("Waiting for a readable turn username.")
            return
        self._name = speaker
        self._aliases = {speaker}
        if self.face is not None:
            self.face.send("NAME", speaker)
        else:
            self.name_var.set(speaker)
        self._note(f"YOU  {speaker}  (this session)")
        self._recheck_identity()

    def _on_spam(self, *_args) -> None:
        self._spam = self.spam_var.get()
        self._save_text(SPAM_PATH, self._spam)
        with self._lock:
            self.session.set_spam_suffixes(self._spam)
        if self._mode == "spam":
            self._show_phase()
            if self._shown:
                self._present(self._shown)

    def _new_game(self) -> None:
        if not self.ready:
            return
        self._cancel_typing()
        self._needs_clear = False
        self._typed_word = ""
        self._typed_suffix = ""
        self._retried = ""
        self._shown = ""
        self._aborted_prompt = ""
        self._theirs_streak = 0
        with self._lock:
            self.session.new_game()
            self.watch.reset()
        if self.face is not None:
            for index in range(1, 4):
                self.face.send(f"C{index}", "—")
            self.face.send("TYPE", "—")
            self.face.send("TRAP", "—")
        else:
            for var in self.choice_vars:
                var.set("—")
            self.type_var.set("—")
            self.trap_var.set("—")
        self._show_prompt("—")
        self._refresh_used()
        self._note("New game. Used words cleared.")

    def handle(self, key: str, value: str) -> bool:
        if key == "QUIT":
            return False
        if key == "ARM":
            self._toggle_arm()
        elif key == "CASUAL":
            self._set_mode("casual")
        elif key == "PRO":
            self._set_mode("pro")
        elif key == "SPAM":
            self._set_mode("spam")
        elif key == "SPAMTEXT":
            self._spam = value
            self._save_text(SPAM_PATH, self._spam)
            with self._lock:
                self.session.set_spam_suffixes(self._spam)
            if self._mode == "spam":
                self._show_phase()
                if self._shown:
                    self._present(self._shown)
        elif key == "NEW":
            self._new_game()
        elif key == "NAME":
            self._set_name(value)
        elif key == "CONFIRM":
            self._confirm_turn()
        return True

    def close(self) -> None:
        self._stop.set()
        self._cancel_typing()
        stop_capture()
        if self.root is not None:
            self.root.destroy()

def _reveal(root: tk.Tk) -> None:

    if sys.platform != "darwin":
        return
    try:
        root.deiconify()
        root.lift()
        root.attributes("-topmost", True)
        root.update_idletasks()
        width, height = root.winfo_width(), root.winfo_height()
        if width > 50 and height > 50:
            root.geometry(f"{width}x{height + 1}")
            root.after(40, lambda: root.geometry(f"{width}x{height}"))
    except tk.TclError:
        return

def main() -> None:
    if sys.platform == "darwin" and PANEL_BIN.is_file():
        proc = subprocess.Popen(
            [str(PANEL_BIN)],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            text=True,
            bufsize=1,
        )
        app = AutotypeApp(face=NativeFace(proc))
        try:
            if proc.stdout is None:
                return
            def read_actions() -> None:
                for line in proc.stdout:
                    key, _, value = line.rstrip("\n").partition("\t")
                    if key:
                        app._put_event("ACTION", (key, value))
                app._put_event("ACTION", ("QUIT", ""))
            threading.Thread(target=read_actions, daemon=True).start()
            while not app._stop.is_set():
                try:
                    kind, payload = app._queue.get(timeout=0.1)
                except queue.Empty:
                    continue
                app._process_event(kind, payload)
        finally:
            app.close()
            if proc.poll() is None:
                proc.kill()
        return
    root = tk.Tk()
    if sys.platform == "darwin":
        root.withdraw()
    AutotypeApp(root)
    root.after(0, lambda: _reveal(root))
    root.mainloop()

if __name__ == "__main__":
    main()
