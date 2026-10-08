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

from autotype.featherine import edit_plan, turn_plan
from autotype.timer import TurnClock
from autotype.host import (focus_roblox, keyboard_available, request_keyboard_access,
                           press_enter, roblox_focused, run_capture, stop_capture, tap_key)
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

# Seconds kept back from the turn clock for Enter to reach the game.
SUBMIT_MARGIN = 0.35
# Without an acceptance or a rejection banner, Enter is sent once more, then
# the answer is treated as refused and the nearest other answer is entered.
ENTER_RETRY_AFTER = 0.9
REFUSED_AFTER = 0.8
MAX_ALTERNATIVES = 3


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
        self._input_lock = threading.Lock()
        self._queue: queue.Queue = queue.Queue(maxsize=32)
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
        self._paused = threading.Event()
        self._manual_turn = False
        self._manual_misses = 0
        self._clear = None
        self._selection_retry_at = 0.0
        self._submitted_at = 0.0
        self._submit_attempts = 0
        self._submit_read_at = 0.0
        self._submit_frames = 0
        self._alert_onset = False
        self._new_prompt = ""
        self._new_prompt_hits = 0
        self._alternatives = 0
        self._clock = TurnClock()
        self._given_seen = ""
        self._own_board = ""
        self._resume_clear = False
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
                args=(self._stop, self._enqueue_frame, self._enqueue_roblox, lambda: self._name, self._paused.is_set),
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
        tk.Label(self.spam_frame, text="ENDINGS: [ing][ary] or commas/spaces", bg=INK, fg=MUTED, font=(mono, 10)).pack(anchor="w")
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
        self.pause_btn = tk.Label(actions, text="PAUSE", bg=CARD, fg=BONE, font=(mono, 12), padx=8, pady=8)
        self.pause_btn.pack(side="left", fill="x", expand=True, padx=(0, 6))
        self.pause_btn.bind("<Button-1>", lambda _e: self._toggle_pause())
        root.bind("<Escape>", lambda _e: self._toggle_pause())
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
        # Native button input must interrupt a worker even behind queued frames.
        if kind == "ACTION" and payload[0] == "PAUSE" and not self._paused.is_set():
            self._type_cancel.set()
        # Keep input/control events moving when recognition briefly outruns
        # the UI. Prefer discarding a redundant old frame; never discard a
        # button action, submission, or change of Roblox availability.
        while not self._stop.is_set():
            try:
                self._queue.put((kind, payload), timeout=0.05)
                return
            except queue.Full:
                self._drop_queued_frame()

    def _drop_queued_frame(self) -> None:
        with self._queue.mutex:
            pending = self._queue.queue
            frames = [(index, item[1]) for index, item in enumerate(pending)
                      if item[0] == "FRAME"]
            if not frames:
                return
            def signature(frame):
                return (frame.get("prompt"), frame.get("header"), frame.get("full"),
                        frame.get("row_clipped"))
            counts = {}
            for _index, frame in frames:
                sig = signature(frame)
                counts[sig] = counts.get(sig, 0) + 1
            redundant = next((index for index, frame in frames
                              if counts[signature(frame)] > 2), None)
            victim = frames[0][0] if redundant is None else redundant
            del pending[victim]
            self._queue.unfinished_tasks -= 1
            self._queue.not_full.notify()

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
            gen, word, input_length = payload[:3]
            if gen == self._gen and not self._paused.is_set() and not self._type_cancel.is_set():
                self._submit(word, input_length)
        elif kind == "TYPE_DONE":
            gen, sent, input_length, message = payload
            # Old workers must never release a newer turn or correction.
            if gen != self._gen:
                return
            self._input_length = input_length
            self.typing = False
            if not sent:
                self.watch.played = ""
                self.watch.typed = ""
                self._typed_word = ""
                self._needs_clear = bool(input_length)
                if self.armed and self._typing_prompt:
                    self._aborted_prompt = self._typing_prompt
                if input_length:
                    self._note("Typing interrupted. Checking the input before retrying.")
            if message:
                self._note(message)
                if message.startswith("Typing failed:") and ("Accessibility" in message or "permission" in message.lower()):
                    self._input_problem = message
                    self.armed = False
                    self._want_arm = True
                    self._aborted_prompt = ""
                    self._paint_arm()
                    self._set_status("KEYBOARD CONTROL ISN'T AVAILABLE")
        elif kind == "ERASED":
            gen, prompt, success = payload
            if gen == self._gen and self._clear:
                # Sending Backspace is not proof that Roblox deleted anything.
                self._clear.update(after=time.monotonic(), read_at=0.0, hits=0, board="", working=False)
                if not success:
                    self._note("Deletion interrupted. It will resume on your turn.")

    def _drain(self) -> None:
        try:
            for _ in range(32):
                try:
                    kind, payload = self._queue.get_nowait()
                except queue.Empty:
                    break
                try:
                    self._process_event(kind, payload)
                except Exception as exc:
                    self._shown = ""
                    self._note(f"Reader recovered from a frame error: {exc}")
        finally:
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
        label = "ENABLE TYPING" if self._input_problem else "ARMED" if self.armed else "ARM"
        if self.face is not None:
            self.face.send("ARMED", "1" if self.armed else "0")
            self.face.send("ARMLABEL", label)
            return
        self.arm_btn.configure(
            text=label,
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
                self.session.new_game()
            self._emit("LOADED", count)
        except Exception as exc:
            self._emit("STATUS", "DICTIONARY FAILED")
            self._emit("LOG", str(exc))

    def _apply_loaded(self, count: int) -> None:
        self._count = count
        self.ready = count > 0 and self.engine.ready
        if not self.ready:
            self._set_status("DICTIONARY IS EMPTY")
            self._note(f"No words loaded from {DICT_PATH.name}.")
            return
        self._refresh_used()
        if self._roblox == "up":
            self.armed = self._want_arm
            if not keyboard_available():
                self._input_problem = "Allow Accessibility for Python or Terminal in macOS Settings. Then click ENABLE TYPING."
                self.armed = False
                self._note(self._input_problem)
            self._paint_arm()
            self._set_status("ALLOW ACCESSIBILITY TO TYPE" if self._input_problem else f"READY  ·  {count:,} WORDS")
            if self.armed:
                self._note("Armed. It reads the tiles and types on your turn.")
        elif self._roblox == "hidden":
            self._set_status("ROBLOX ISN'T VISIBLE")
        elif self._roblox == "down":
            self._set_status("ROBLOX ISN'T AVAILABLE")
        elif self._roblox == "unsupported":
            self._set_status("CAPTURE ISN'T AVAILABLE")
        else:
            self._set_status("LOOKING FOR ROBLOX")
        if self._last_frame and not self._paused.is_set():
            self._handle_frame(self._last_frame)
        if self._paused.is_set():
            self._set_status("PAUSED  ·  USED WORDS KEPT")

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
            self.armed = not bool(self._input_problem)
            self._paint_arm()
        if self.ready:
            self._set_status(f"READY  ·  {self._count:,} WORDS")
            self._note("Roblox is on screen.")

    def _handle_frame(self, frame: dict) -> None:
        if self._roblox != "up":
            return
        self._last_frame = dict(frame)
        if self._paused.is_set():
            return
        now = time.monotonic()
        if self._input_problem and keyboard_available():
            self._input_problem = ""
            self.armed = self._want_arm and self.ready
            self._paint_arm()
            self._resume_clear = self._needs_clear
            self._note("Keyboard control is available. Resuming.")
        if self.ready and now - self._status_at > 0.3:
            self._status_at = now
            self._set_status("KEYBOARD CONTROL ISN'T AVAILABLE" if self._input_problem
                             else f"READ {frame.get('ms', 0)}ms  ·  {self._count:,} WORDS")
        header = frame.get("header", "")
        speaker = speaker_from_header(header, self._name)
        full = bool(frame.get("full", True))
        board = frame.get("prompt", "")
        whose = ""
        if header_is_turn(header) and speaker:
            ours = header_is_ours(self._name, header) or any(names_match(alias, speaker) for alias in self._aliases)
            whose = "ours" if ours else "theirs"
        elif (not speaker and self._current_turn == "ours" and board
              and (not header or header_is_turn(header) or self.typing or self._clear
                   or self._typed_word)):
            # An unread name does not revoke a turn already identified. Board
            # acceptance and a readable different speaker still end that turn.
            whose = "ours"
        if self._manual_turn:
            mismatch = speaker and self._name and not (names_match(self._name, speaker)
                        or any(names_match(alias, speaker) for alias in self._aliases))
            self._manual_misses = self._manual_misses + 1 if mismatch else 0
            if self._manual_misses >= 3:
                self._manual_turn = False
            else:
                whose = "ours"
                if speaker and not self._aliases:
                    self._name = speaker
                    self._aliases = {speaker}
                    if self.face is not None:
                        self.face.send("NAME", speaker)
                    else:
                        self.name_var.set(speaker)
        # Normalize a reversed prefix throughout typing AND deletion recovery.
        # Preserve opponent readings as seen; our previous prefix is no longer
        # authority to rewrite another player's answer.
        active_prefix = self._typing_prompt
        active_input = (self.typing or self._typed_word or self._clear
                        or self._needs_clear or self._resume_clear)
        if whose != "theirs" and active_prefix and active_input:
            if board.startswith(active_prefix[::-1]) and not board.startswith(active_prefix):
                board = active_prefix + board[len(active_prefix):]
                frame = dict(frame, prompt=board)
        elif (self.ready and full and 1 <= len(board) <= 4 and not active_input
              and whose != "theirs"):
            board = self.session.resolve_prefix(board)
            frame = dict(frame, prompt=board)
        if whose == "theirs":
            self._theirs_streak += 1
        elif whose == "ours":
            self._theirs_streak = 0
        # One bad header read used to abort the key thread and leave the prompt
        # latched, so the turn sat on screen until a key changed the picture.
        if self._header_blip(whose, board) or self._prefix_still_ours(whose, board, full):
            whose = "ours"
        if (whose == "theirs" and self._typed_word and board == self._typed_word
                and self._theirs_streak < 3):
            # One wrong name while the submitted word remains visible is not
            # acceptance. Keep its Enter acknowledgement alive.
            whose = "ours"
        captured = frame.get("captured_at", now)
        self._clock.observe(frame.get("timer"), frame.get("timer_frac"), captured)
        if whose == "ours" and self._current_turn != "ours":
            self._clock.start_turn(captured)
            self._alternatives = 0
            self._given_seen = self._own_board = ""
        self._track_manual_entry(whose, board, full)
        self._current_turn = whose
        self._show_turn(whose, header)
        if not self.ready:
            return
        if self._clear:
            self._check_clear(frame, whose, now)
            return
        if self._resume_clear:
            if not full or not whose:
                return
            self._resume_clear = False
            old_prefix = self._typing_prompt
            if whose == "ours" and full and board.startswith(old_prefix) and old_prefix:
                self._input_length = max(0, len(board) - len(old_prefix))
                self.watch.played = ""
                if self._input_length:
                    self._clear_input(old_prefix)
                    return
                self.watch.rearm(old_prefix, now)
            self._needs_clear = False
        if (self._needs_clear and self.armed and whose == "ours" and full
                and not self.typing and not self._erasing):
            previous_prefix = self._typing_prompt
            self._needs_clear = False
            if previous_prefix and board.startswith(previous_prefix):
                self._input_length = max(0, len(board) - len(previous_prefix))
                self.watch.played = ""
                if self._input_length:
                    self._clear_input(previous_prefix)
                    return
                self.watch.rearm(previous_prefix, now)
        # Choices are useful even if the header is temporarily obscured. They
        # also make a failed turn read distinguishable from a missing dictionary.
        prefix = self.watch._prompt(board)
        if (not prefix and self._shown and not self.typing
                and not self._typed_word and not self._clear):
            self._shown = ""
            self._clear_choices()
        if (full and prefix and prefix != self._shown
                and not self.typing and not self.watch.typed):
            self._shown = prefix
            self._retried = ""
            self._present(prefix)
        if self._type_cancel.is_set():
            return
        self._show_prompt(board or ("—" if full else "READING…"))
        if self.typing and not self._typed_word:
            # These are our own live keystrokes, not a growing new prefix.
            if whose == "theirs" and self._theirs_streak >= 3:
                self._needs_clear = bool(self._input_length)
                self._cancel_typing(release=True)
                self._note("Turn changed. Typing stopped.")
            return
        if self._typed_word:
            if frame.get("captured_at", now) <= self._submitted_at:
                self._alert_onset = self._alert_onset or not frame.get("alert", False)
                return
            if self._check_enter_ack(frame, whose, now):
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
            self._commit_ours(self._typed_word)
        elif event["rejected"] and self._typed_word:
            self._schedule_retry(self._typed_word, used=False)
        self._note_turn_passed()
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
        if whose == "ours":
            text = "YOUR TURN"
        elif not header_is_turn(header):
            text = "IN LOBBY" if "play" in header.lower() else "WATCHING"
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

    def _clear_choices(self) -> None:
        if self.face is not None:
            for index in range(1, 4):
                self.face.send(f"C{index}", "—")
            self.face.send("TYPE", "—")
            self.face.send("TRAP", "—")
        else:
            for choice in self.choice_vars:
                choice.set("—")
            self.type_var.set("—")
            self.trap_var.set("—")

    def _time_left(self) -> float | None:
        return self._clock.remaining(time.monotonic())

    def _present(self, prompt: str) -> None:
        left = self._time_left()
        with self._lock:
            words = self.session.choices(prompt, 3, left)
            word, suffix, trap, _phase = self.session.choose(prompt, left)
        self._show_phase()
        labels = [f"{index + 1}  {words[index]}" if index < len(words) else "—" for index in range(3)]
        type_label = suffix or ("ENTER" if word else "—")
        if self.face is not None:
            for index, label in enumerate(labels, 1):
                self.face.send(f"C{index}", label)
            self.face.send("TYPE", type_label)
            self.face.send("TRAP", trap or "—")
        else:
            for index, label in enumerate(labels):
                self.choice_vars[index].set(label)
            self.type_var.set(type_label)
            self.trap_var.set(trap or "—")
        self._note(f"{prompt}  →  {word}" if word else f"No word for {prompt}")

    def _start_typing(self, prompt: str) -> None:
        if (self.typing or self._erasing or self._needs_clear or self.watch.typed
                or self._typed_word or self._paused.is_set() or self._input_problem):
            return
        thread = self._typing_thread
        if thread is not None and thread.is_alive():
            return
        if self._roblox != "up":
            self._set_status("ROBLOX ISN'T AVAILABLE")
            self._note("ROBLOX ISN'T AVAILABLE")
            return
        if time.monotonic() < self._selection_retry_at:
            return
        left = self._time_left()
        with self._lock:
            word, suffix, trap, _phase = self.session.choose(prompt, left)
        self._show_phase()
        type_label = suffix or ("ENTER" if word else "—")
        if self.face is not None:
            self.face.send("TYPE", type_label)
            self.face.send("TRAP", trap or "—")
        else:
            self.type_var.set(type_label)
            self.trap_var.set(trap or "—")
        if not word:
            # An empty selection is not a completed attempt and must not latch
            # this prefix for the rest of the game.
            self.watch.played = ""
            self._selection_retry_at = time.monotonic() + 0.3
            self._aborted_prompt = ""
            self._note(f"No available word for {prompt}; checking again.")
            return
        self._selection_retry_at = 0.0
        self._aborted_prompt = ""
        self._type_cancel = threading.Event()
        self._input_length = 0
        plan = turn_plan(suffix, prompt, self._budget(left), is_word=self.engine._is_known_word)
        self._launch_typing(prompt, word, plan)

    def _budget(self, left: float | None) -> float | None:
        return None if left is None else max(0.0, left - SUBMIT_MARGIN)

    def _launch_typing(self, prompt: str, word: str, plan) -> None:
        self.watch.played = prompt
        self._typed_suffix = word[len(prompt):]
        self.typing = True
        self._typing_prompt = prompt
        gen = self._gen
        thread = threading.Thread(target=self._type_suffix, args=(gen, word, plan, self._type_cancel),
                                  daemon=True)
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

    def _resume_aborted(self, board: str, whose: str) -> None:
        # The prompt was already ours. Type it again without waiting for a new
        # tile change or another two identical reads.
        if whose != "ours" or not self.armed or self.typing or self._erasing or self._needs_clear:
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
        self._clear = None
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
        """A refused answer: edit what is typed into the nearest unused one.

        The same answer is never typed again. "ismailisms" already used turns
        into "ismailism" with one Backspace, then Enter.
        """
        if not word or self._erasing or word == self._retried:
            return
        prompt = self.watch.played or self._typing_prompt or self._shown
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
        if not prompt or not word.startswith(prompt):
            self._clear_input(prompt)
            return
        # Keystrokes are the record of what is typed, unless every tile was
        # read: then a dropped or doubled key shows on the board.
        last = self._last_frame
        board = last.get("prompt", "")
        current = word
        if (last.get("full", False) and last.get("row_complete", True) and "?" not in board
                and int(last.get("tiles", len(board))) == len(board) and board.startswith(prompt)):
            current = board
        self._alternatives += 1
        left = self._time_left()
        with self._lock:
            target, _deletes, _letters = self.session.alternative(prompt, current, left)
        if not target or self._alternatives > MAX_ALTERNATIVES or not self.armed:
            self._input_length = len(current) - len(prompt)
            self._clear_input(prompt)
            return
        self._cancel_typing()
        self._type_cancel = threading.Event()
        self._input_length = len(current) - len(prompt)
        plan = edit_plan(current[len(prompt):], target[len(prompt):], self._budget(left))
        self._note(f"{current}  →  {target}")
        self._launch_typing(prompt, target, plan)

    def _clear_input(self, prompt: str, *, word: str = "") -> None:
        if self._erasing or self._paused.is_set() or not prompt:
            return
        # Invalidate queued completions and wait for any last held key through
        # the shared input lock before sending deletions.
        self._cancel_typing()
        self._resume_clear = False
        self._erasing = True
        self._needs_clear = True
        gen = self._gen
        cancel = self._type_cancel
        board = self._last_frame.get("prompt", "")
        visible = len(board) - len(prompt) if board.startswith(prompt) else 0
        input_length = max(self._input_length, visible, len(self._typed_suffix))
        self._clear = {"gen": gen, "prompt": prompt, "word": word, "after": time.monotonic(),
                       "read_at": 0.0, "board": "", "hits": 0, "working": True}
        self._erase_suffix(gen, prompt, input_length, cancel)

    def _erase_suffix(self, gen: int, prompt: str, input_length: int, cancel: threading.Event) -> None:
        def work() -> None:
            success = False
            try:
                with self._input_lock:
                    if gen != self._gen or cancel.is_set() or self._stop.is_set():
                        return
                    if focus_roblox():
                        for _ in range(input_length):
                            if gen != self._gen or self._stop.is_set() or cancel.is_set():
                                return
                            if not roblox_focused():
                                return
                            tap_key("back", "\b", 0.030)
                            if cancel.wait(0.020):
                                return
                        success = True
            except Exception as exc:
                self._emit("TYPE_DONE", (gen, False, input_length, f"Typing failed: {exc}"))
            finally:
                self._emit("ERASED", (gen, prompt, success))
        self._typing_thread = threading.Thread(target=work, daemon=True)
        self._typing_thread.start()

    def _check_clear(self, frame: dict, whose: str, now: float) -> None:
        state = self._clear
        self._show_prompt(frame.get("prompt", "") or "READING…")
        if whose == "theirs" and self._theirs_streak >= 3:
            self._cancel_typing(release=True)
            return
        if whose != "ours" or state["working"] or not self.armed:
            return
        captured = frame.get("captured_at", now)
        if captured <= state["after"] or captured <= state["read_at"]:
            return
        state["read_at"] = captured
        board = frame.get("prompt", "")
        full = (bool(frame.get("full", True)) and frame.get("row_complete", True)
                and "?" not in board)
        if not full or int(frame.get("tiles", len(board))) != len(board):
            state["hits"] = 0
            return
        state["hits"] = state["hits"] + 1 if board == state["board"] else 1
        state["board"] = board
        if state["hits"] < 2:
            return
        prompt = state["prompt"]
        if board == prompt:
            thread = self._typing_thread
            if thread is not None and thread.is_alive():
                return
            word = state["word"]
            self._clear = None
            self._erasing = self._needs_clear = False
            self._input_length = 0
            self._aborted_prompt = ""
            self.watch.rearm(prompt, now)
            if word and word not in self.engine.used_words and word not in self.engine.rejected_words:
                plan = edit_plan("", word[len(prompt):], self._budget(self._time_left()))
                self._launch_typing(prompt, word, plan)
            else:
                self._shown = prompt
                self._present(prompt)
                self._start_typing(prompt)
            return
        if board.startswith(prompt) and now - state["after"] >= 0.10:
            # A dropped Backspace left characters behind. Delete only the
            # remaining suffix, then confirm the prefix again before retyping.
            state.update(working=True, hits=0, after=now)
            self._erase_suffix(self._gen, prompt, len(board) - len(prompt), self._type_cancel)
        elif self.watch._prompt(board) and now - state["after"] >= 0.25:
            # The game advanced while deletion was pending. Release the old
            # retry and solve the new, twice-confirmed prompt.
            self._clear = None
            self._erasing = self._needs_clear = False
            self._typed_word = self.watch.typed = ""
            self._input_length = 0
            self._aborted_prompt = ""
            self.watch.rearm(board, now)
            self._shown = board
            self._present(board)
            self._start_typing(board)

    def _type_suffix(self, gen: int, word: str, plan, cancel: threading.Event) -> None:
        with self._input_lock:
            self._type_suffix_keys(gen, word, plan, cancel)

    def _type_suffix_keys(self, gen: int, word: str, plan, cancel: threading.Event) -> None:
        sent = False
        input_length = self._input_length
        message = ""
        try:
            if gen != self._gen or cancel.is_set() or self._stop.is_set():
                return
            if not focus_roblox():
                message = "Couldn't focus Roblox. Typing will retry on your turn."
                return
            previous_hold = 0.0
            for step in plan.steps:
                if cancel.wait(max(0.0, step.delay - previous_hold)) or gen != self._gen or self._stop.is_set():
                    return
                if not roblox_focused():
                    message = "Roblox lost focus. Typing stopped."
                    return
                if step.kind == "enter":
                    # The controller presses the final Enter at once, after
                    # registering the answer, so a fast turn change counts.
                    self._emit("SUBMIT", (gen, word, input_length, time.monotonic()))
                    sent = True
                    return
                if step.kind == "early":
                    # A human slip: Enter on an unfinished non-word. Typing goes on.
                    press_enter()
                    previous_hold = 0.0
                    continue
                # Key holds are included in the plan's interval, rather than
                # added to it; the first key has no artificial lead-in.
                tap_key(step.kind, step.key, 0.022)
                previous_hold = 0.022
                input_length = len(step.typed)
                if gen == self._gen:
                    self._input_length = input_length
        except Exception as exc:
            message = f"Typing failed: {exc}"
        finally:
            self._emit("TYPE_DONE", (gen, sent, input_length, message))

    @staticmethod
    def _enter_in_roblox() -> bool:
        # Enter must never land in another app.
        if not roblox_focused() and not focus_roblox():
            return False
        press_enter()
        return True

    def _submit(self, word: str, input_length: int) -> None:
        if not self.armed:
            return
        # Register the pending submission before Enter so a fast turn change
        # confirms it. Used words are recorded on acceptance.
        self._typed_word = word
        self.watch.typed = word
        self.watch.pending = word
        self._input_length = input_length
        self._alert_onset = not self._last_frame.get("alert", False)
        try:
            pressed = self._enter_in_roblox()
        except Exception as exc:
            self._typed_word = self.watch.typed = ""
            self._process_event("TYPE_DONE", (self._gen, False, input_length, f"Typing failed: {exc}"))
            return
        self._submitted_at = time.monotonic()
        self._submit_read_at = self._submitted_at
        # Unsent Enter is pressed on the next frame Roblox is in front.
        self._submit_attempts = 1 if pressed else 0
        self._submit_frames = 0
        self._new_prompt = ""
        self._new_prompt_hits = 0
        self._manual_turn = False
        self._note(f"Entered {word}.")

    def _commit_ours(self, word: str) -> None:
        self._typed_word = ""
        self.watch.typed = ""
        with self._lock:
            self.session.commit_play(word, self._typing_prompt)
        self._refresh_used()
        self._note(f"OURS  {word}")
        self._needs_clear = False
        self._input_length = 0
        self._aborted_prompt = ""
        self._given_seen = ""
        self._own_board = ""

    def _track_manual_entry(self, whose: str, board: str, full: bool) -> None:
        """Remember a complete word on our board that we did not type."""
        if whose != "ours":
            return
        prompt = self.watch.pending if self.watch._prompt(self.watch.pending) else ""
        if (full and prompt and len(board) > len(prompt) and board.startswith(prompt)
                and not self.typing and not self._typed_word and self.engine._is_known_word(board)):
            self._own_board = board

    def _note_turn_passed(self) -> None:
        """The opponent's starting prompt confirms which word ended our turn."""
        given = self.watch._given
        if self.watch.turn != "theirs" or not given or given == self._given_seen:
            return
        self._given_seen = given
        word, self._own_board = self._own_board, ""
        with self._lock:
            self.session.note_given(given)
            noted = (len(word) > len(given) and word.endswith(given)
                     and self.session.note_opponent_word(word))
        if noted:
            self._refresh_used()
            self._note(f"OURS  {word}  (entered by hand)")

    def _check_enter_ack(self, frame: dict, whose: str, now: float) -> bool:
        """Watch a submitted answer; True when it was refused and replaced."""
        word = self._typed_word
        captured = frame.get("captured_at", now)
        if whose != "ours" or captured <= self._submit_read_at or not self.armed:
            return False
        self._submit_read_at = captured
        self._submit_frames += 1
        alert = bool(frame.get("alert", False))
        if alert and self._alert_onset:
            # "Already used!" under the table, shown after this Enter.
            self._schedule_retry(word, used=True)
            return True
        self._alert_onset = self._alert_onset or not alert
        board = frame.get("prompt", "")
        prompt = self.watch._prompt(board)
        full = frame.get("full", True) and "?" not in board
        moved_on = bool(full and prompt and prompt != self.watch.played and not word.endswith(prompt))
        if full and prompt and prompt != self.watch.played and len(word) > len(prompt) and word.endswith(prompt):
            # The board collapsed to our ending: accepted, the header lags.
            return False
        # Someone else's input while the header has not caught up yet.
        foreign = bool(full and board and self.watch.played and not board.startswith(self.watch.played))
        waited = now - self._submitted_at
        if not moved_on and not foreign and (self._submit_attempts == 0 or (
                self._submit_frames >= 2 and self._submit_attempts < 2 and waited >= ENTER_RETRY_AFTER)):
            # A dropped Enter key. Press it again; nothing is retyped.
            try:
                if self._enter_in_roblox():
                    self._submitted_at = time.monotonic()
                    self._submit_read_at = self._submitted_at
                    self._submit_attempts += 1
                    self._submit_frames = 0
                    self._note(f"Enter for {word}." if self._submit_attempts == 1 else f"Enter again for {word}.")
            except Exception as exc:
                self._note(f"Couldn't send Enter: {exc}")
            return False
        if not moved_on and not foreign and self._submit_frames >= 2:
            if self._submit_attempts >= 2 and waited >= REFUSED_AFTER:
                self._note(f"No acceptance for {word}. Trying another answer.")
                self._schedule_retry(word, used=False)
                return True
        if not moved_on:
            self._new_prompt_hits = 0
            return False
        self._new_prompt_hits = self._new_prompt_hits + 1 if prompt == self._new_prompt else 1
        self._new_prompt = prompt
        if self._new_prompt_hits >= 2 and now - self._submitted_at >= 0.2:
            # A whole opponent turn can pass between captures. A new stable
            # prompt on our turn releases the old submitted word.
            self._commit_ours(word)
            self.watch.rearm(prompt, now)
        return False

    def _toggle_pause(self) -> None:
        if not self._paused.is_set():
            self._paused.set()
            self._needs_clear = self.typing or self._erasing
            self._cancel_typing(release=True)
            self._manual_turn = False
            self._set_status("PAUSED  ·  USED WORDS KEPT")
            self._note("Paused. Typing and game reading stopped; used words kept.")
        else:
            self._paused.clear()
            self._resume_clear = self._needs_clear
            if not self.watch.typed:
                self.watch.played = ""
            self._set_status("RESUMED  ·  READING CURRENT TURN")
            self._note("Resumed. Reading the current turn.")
        label = "RESUME" if self._paused.is_set() else "PAUSE"
        if self.face is not None:
            self.face.send("PAUSELABEL", label)
        else:
            self.pause_btn.configure(text=label)

    def _toggle_arm(self) -> None:
        if not self.ready:
            return
        if self._paused.is_set():
            self._note("Paused. Resume to enable typing.")
            return
        if not keyboard_available():
            self._input_problem = "Allow Accessibility for Python or Terminal, then click ENABLE TYPING."
            self.armed = False
            self._want_arm = True
            self._paint_arm()
            self._set_status("ALLOW ACCESSIBILITY TO TYPE")
            self._note(self._input_problem)
            request_keyboard_access()
            return
        if self._input_problem:
            self._input_problem = ""
            self.armed = False
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
            self._resume_clear = True
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
        speaker = speaker_from_header(frame.get("header", ""), self._name)
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
        if self.typing or self._typed_word or self.watch.typed:
            self._note("The current word is already in progress.")
            return
        speaker = speaker_from_header(self._last_frame.get("header", ""))
        if speaker:
            self._name = speaker
            self._aliases = {speaker}
            if self.face is not None:
                self.face.send("NAME", speaker)
            else:
                self.name_var.set(speaker)
            self._note(f"YOU  {speaker}  (this session)")
        else:
            self._note("This turn confirmed manually. Username will be learned when readable.")
        self._manual_turn = True
        self._manual_misses = 0
        if self._paused.is_set():
            self._note("Paused. Resume to play this turn.")
            return
        prompt = self.watch._prompt(self._last_frame.get("prompt", ""))
        self._current_turn = "ours"
        self._show_turn("ours", "")
        board = self._last_frame.get("prompt", "")
        if (self._needs_clear and self.armed and self._last_frame.get("full", True)
                and self._typing_prompt and board.startswith(self._typing_prompt)):
            self._input_length = max(0, len(board) - len(self._typing_prompt))
            if self._input_length:
                self._clear_input(self._typing_prompt)
                return
            self._needs_clear = False
        if prompt and self.ready and not self.typing:
            self.watch.rearm(prompt, time.monotonic())
            self._shown = prompt
            self._present(prompt)
            if self.armed:
                self._start_typing(prompt)

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
        self._manual_turn = False
        self._selection_retry_at = 0.0
        self._new_prompt_hits = 0
        self._alternatives = 0
        self._given_seen = self._own_board = ""
        self._clock.reset()
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
        elif key == "PAUSE":
            self._toggle_pause()
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
                try:
                    app._process_event(kind, payload)
                except Exception as exc:
                    app._shown = ""
                    app._note(f"Reader recovered from a frame error: {exc}")
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
