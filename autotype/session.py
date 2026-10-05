"""Round clock and DYOE picks for Last Letter.

Prefix length climbs every 5 of your rounds, capped at 4:
round 1–5 phase 1, 6–10 phase 2, 11–15 phase 3, 16+ phase 4.
A longer prefix already on the board jumps the phase up to match.
"""

from __future__ import annotations

import re
from bisect import bisect_left, bisect_right
from typing import Optional, Tuple

from dyoe2_engine import Dyoe2Engine

ROUNDS_PER_PHASE = 5
_NAME_RE = re.compile(r"([a-z0-9_]{2,24})", re.I)
_TURN_RE = re.compile(
    r"([a-z0-9_]{2,24})\s*,?\s*type an english word",
    re.I,
)


def phase_for_round(round_n: int) -> int:
    n = max(1, int(round_n or 1))
    return min(4, 1 + (n - 1) // ROUNDS_PER_PHASE)


def phase_for_prompt(round_n: int, prefix: str) -> int:
    length = len(prefix or "")
    by_len = 1 if length <= 1 else min(4, length)
    return max(phase_for_round(round_n), by_len)


def sync_round_to_prefix(round_n: int, prefix: str) -> int:
    """Bump the round counter when the board is already in a later phase."""
    need = 1 if len(prefix) <= 1 else min(4, len(prefix))
    round_n = max(1, int(round_n or 1))
    guard = 0
    while phase_for_round(round_n) < need and guard < 4:
        round_n += ROUNDS_PER_PHASE
        guard += 1
    return round_n


def _shared_run(a: str, b: str) -> int:
    best = 0
    for size in range(min(len(a), len(b)), 3, -1):
        for i in range(len(a) - size + 1):
            if a[i : i + size] in b:
                return size
        best = max(best, size)
    return 0


def names_match(ours: str, seen: str) -> bool:
    a = re.sub(r"[^a-z0-9]", "", (ours or "").lower())
    b = re.sub(r"[^a-z0-9]", "", (seen or "").lower())
    if len(a) < 3 or len(b) < 3:
        return False
    if a == b or a in b or b in a:
        return True
    # The tile header OCR often drops or swaps the first letter.
    if len(a) >= 6 and a[-6:] == b[-6:]:
        return True
    digits_a = re.sub(r"\D", "", a)
    digits_b = re.sub(r"\D", "", b)
    if len(digits_a) >= 4 and digits_a == digits_b:
        return True
    letters_a = re.sub(r"[^a-z]", "", a)
    letters_b = re.sub(r"[^a-z]", "", b)
    # "gugugaga2323332" is read as "uyugaga23233312": one dropped letter, one extra digit.
    return _shared_run(digits_a, digits_b) >= 5 and _shared_run(letters_a, letters_b) >= 5


def speaker_from_header(header: str) -> str:
    text = header or ""
    match = _TURN_RE.search(text)
    if match and len(match.group(1)) >= 4:
        return match.group(1)
    if "starting with" not in text.lower() and "english word" not in text.lower():
        return ""
    # OCR sometimes drops the comma. Take the token before "type".
    head = re.split(r"type an english", text, flags=re.I)[0]
    tokens = [token for token in _NAME_RE.findall(head) if len(token) >= 4]
    return tokens[-1] if tokens else ""


def header_is_ours(name: str, header: str) -> bool:
    """True when this turn line is addressed to us, even if OCR mangles the name."""
    if not header_is_turn(header):
        return False
    speaker = speaker_from_header(header)
    if names_match(name, speaker):
        return True
    compact = re.sub(r"[^a-z0-9]", "", (header or "").lower())
    letters = re.sub(r"[^a-z]", "", (name or "").lower())
    digits = re.sub(r"\D", "", name or "")
    if len(letters) >= 4 and letters in compact:
        return True
    return len(digits) >= 4 and digits in compact


def already_used_text(text: str) -> bool:
    """The line under the tiles when the game refuses a word that was played before."""
    low = re.sub(r"[^a-z]+", " ", (text or "").lower())
    return "already" in low and "used" in low


def header_is_turn(header: str) -> bool:
    low = (header or "").lower()
    return "english word" in low or "starting with" in low


# Tiles spawn one letter at a time. A short row has to sit still before it is
# the whole prefix. Four letters cannot grow any further, so that row settles faster.
_PREFIX_SETTLE = 0.72
_PREFIX_SETTLE_FULL = 0.24
_OURS_HEADER = 0.22
# Their prefix can still be on screen when the banner flips back to us.
_SAME_PROMPT = 0.95


class BoardWatch:
    """Turn the live tile string into a prompt to type and a word to store.

    The board grows while someone types, then collapses to the next prefix
    when the word is accepted. The first complete reading is kept, so a word
    that is only on screen for one frame is still stored in full.

    A prefix is typed only after the row stops gaining letters and the turn
    line has stayed ours. Their prompt is not typed when the banner is late.
    """

    def __init__(self) -> None:
        self.turn = ""
        self.pending = ""
        self.played = ""
        self.typed = ""
        self._memory: list[str] = []
        self._reject_hits = 0
        self._alt = ""
        self._clock = 0.0
        self._hold = ""
        self._hold_at = 0.0
        self._ours_since: Optional[float] = None
        self._opponent_prompt = ""
        self._saw_theirs = False
        self._saw_long = False
        self._released = False
        self._need_their_turn = False
        self._last_reads: list[str] = []
        self._retry_prompt = ""

    def reset(self) -> None:
        self.turn = ""
        self.pending = ""
        self.played = ""
        self.typed = ""
        self._memory = []
        self._reject_hits = 0
        self._alt = ""
        self._clock = 0.0
        self._hold = ""
        self._hold_at = 0.0
        self._ours_since = None
        self._opponent_prompt = ""
        self._saw_theirs = False
        self._saw_long = False
        self._released = False
        self._need_their_turn = False
        self._last_reads = []
        self._retry_prompt = ""

    def forget_partials(self) -> None:
        self._last_reads = []

    def rearm(self, prompt: str, now: float) -> None:
        """The last word was refused. Type another one for the same prefix."""
        prompt = self._prompt(prompt)
        self.played = ""
        self.typed = ""
        self.turn = "ours"
        self.pending = prompt
        self._need_their_turn = False
        self._released = True
        self._opponent_prompt = ""
        self._saw_theirs = True
        self._saw_long = False
        self._hold = prompt
        self._hold_at = now - _PREFIX_SETTLE - 0.05
        self._ours_since = now - _OURS_HEADER - 0.05
        self._alt = ""
        self._reject_hits = 0
        self._retry_prompt = prompt

    def _blank(self) -> dict:
        return {
            "play": "",
            "stored": "",
            "candidates": [],
            "accepted": False,
            "rejected": False,
            "board": self.pending,
            "turn": self.turn,
            "partials": list(self._last_reads),
        }

    def _remember(self, board: str) -> None:
        if len(board) < 2:
            return
        if self._memory and self._memory[-1] == board:
            return
        self._memory.append(board)
        if len(self._memory) > 32:
            self._memory = self._memory[-24:]
        self._last_reads = [word for word in self._memory if len(word) >= 4]

    def _candidates(self, prefix: str) -> list[str]:
        """Every reading from this turn that actually ends with the new prefix."""
        if not prefix:
            return []
        out: list[str] = []
        seen: set[str] = set()
        for word in self._memory:
            if word in seen or len(word) <= len(prefix) or not word.endswith(prefix):
                continue
            seen.add(word)
            out.append(word)
        if self.pending and self.pending not in seen and self._is_submit(self.pending, prefix):
            out.append(self.pending)
        return out

    def _mark_accepted(self, out: dict) -> None:
        out["accepted"] = True
        self.typed = ""
        self.played = ""
        self._memory = []
        self._reject_hits = 0
        self._alt = ""
        self._hold = ""
        self._ours_since = None
        self._need_their_turn = True
        self._saw_theirs = False
        self._saw_long = False
        self._released = False

    def _note_long(self, board: str, whose: str) -> None:
        if len(board) <= 4 or self.typed:
            return
        self._saw_long = True
        self._hold = ""
        if whose != "ours":
            self._saw_theirs = True

    def _arm_play(self, out: dict, prompt: str, whose: str, now: float) -> None:
        """Type `prompt` only when it has stopped growing and the turn is ours."""
        prompt = self._prompt(prompt)
        if whose == "theirs":
            self._saw_theirs = True
            self._ours_since = None
            self._hold = ""
            if prompt:
                self._opponent_prompt = prompt
                self._released = False
            return
        if whose != "ours" or not prompt or prompt == self.played:
            return
        if self._ours_since is None:
            self._ours_since = now
        if prompt != self._hold:
            self._hold = prompt
            self._hold_at = now
            return
        need = _PREFIX_SETTLE_FULL if len(prompt) >= 4 else _PREFIX_SETTLE
        if now - self._hold_at < need or now - self._ours_since < _OURS_HEADER:
            return
        if self._need_their_turn and not (self._saw_theirs or self._saw_long or self._released):
            return
        if prompt == self._opponent_prompt and not self._released and now - self._ours_since < _SAME_PROMPT:
            return
        out["play"] = prompt
        self._need_their_turn = True
        self._saw_theirs = False
        self._saw_long = False
        self._released = False
        self._opponent_prompt = ""
        self._hold = ""
        self._ours_since = None

    def _allow_retry(self) -> None:
        self._need_their_turn = False
        self._released = True
        self._opponent_prompt = ""
        self._ours_since = None

    def observe(
        self,
        board: str,
        whose: str,
        *,
        complete: bool = True,
        tiles: int = 0,
        now: float | None = None,
    ) -> dict:
        board = re.sub(r"[^a-z]", "", (board or "").lower())
        whose = whose if whose in ("ours", "theirs") else ""
        if now is None:
            now = self._clock
        else:
            self._clock = now
        if not complete:
            # A tile is on screen that we have not read yet. The prefix is still loading.
            if tiles and self._hold and tiles > len(self._hold):
                self._hold_at = now
            board = ""
        out = self._blank()

        if not board:
            if self.typed and whose == "theirs":
                self._mark_accepted(out)
                self.turn = "theirs"
            out["board"] = self.pending
            out["turn"] = self.turn
            out["partials"] = list(self._last_reads)
            return out

        # Letters still sitting in the box after a refused word are not a new prompt.
        if self._retry_prompt:
            if board == self._retry_prompt:
                self._retry_prompt = ""
            elif board.startswith(self._retry_prompt):
                out["board"] = self._retry_prompt
                out["turn"] = "ours"
                self.turn = "ours"
                return out

        # A word longer than a prefix is theirs, even when the last tiles were cut off.
        if (
            len(board) >= 4
            and not self.typed
            and not (self.played and board.startswith(self.played))
            and (len(board) > 4 or self.turn == "theirs" or whose == "theirs")
        ):
            self._remember(board)
        out["partials"] = list(self._last_reads)

        # Our word is in. Store it once the tiles become its ending, or their turn starts.
        if self.typed:
            still_ours = board.startswith(self.pending) and len(board) >= len(self.pending) and whose != "theirs"
            if still_ours and not (len(board) <= 4 and board != self.played and self.typed.endswith(board)):
                self.pending = board
                self.turn = whose or self.turn or "ours"
                out["board"] = board
                out["turn"] = self.turn
                return out
            same_stem = board == self.played and self.typed.endswith(board)
            accepted = whose == "theirs" or (
                len(board) <= 4
                and len(self.typed) > len(board)
                and self.typed.endswith(board)
                and board != self.played
            )
            if accepted:
                self._mark_accepted(out)
                self.pending = board
                self.turn = "theirs"
                if self._prompt(board):
                    self._opponent_prompt = board
                elif len(board) > 4:
                    self._remember(board)
                out["board"] = board
                out["turn"] = self.turn
                return out
            if same_stem and whose != "theirs":
                self._reject_hits += 1
                if self._reject_hits >= 8:
                    out["rejected"] = True
                    self.typed = ""
                    self.played = ""
                    self.pending = board
                    self._memory = []
                    self._reject_hits = 0
                    self.turn = "ours"
                    self._allow_retry()
                out["board"] = self.pending
                out["turn"] = self.turn
                return out
            if board == self.played and whose != "theirs" and len(self.pending) > len(board):
                self._reject_hits += 1
                if self._reject_hits >= 2:
                    out["rejected"] = True
                    self.typed = ""
                    self.played = ""
                    self.pending = board
                    self._memory = []
                    self._reject_hits = 0
                    self.turn = "ours"
                    self._allow_retry()
                out["board"] = self.pending
                out["turn"] = self.turn
                return out
            self.pending = board
            out["board"] = board
            out["turn"] = self.turn
            return out

        self._reject_hits = 0

        # Letters added onto the prefix we just played are our word, not a new prompt.
        if self.played and whose != "theirs" and self.turn != "theirs" and board.startswith(self.played):
            if len(board) >= len(self.pending):
                self.pending = board
            out["board"] = board
            out["turn"] = "ours"
            self.turn = "ours"
            return out

        if self.pending and board.startswith(self.pending) and len(board) > len(self.pending):
            self.pending = board
            self._note_long(board, whose)
            if whose == "theirs":
                self.turn = "theirs"
                self._remember(board)
            elif whose == "ours":
                self.turn = "ours"
            elif self.turn != "ours":
                self.turn = "theirs"
                self._remember(board)
            if self._prompt(board):
                self._arm_play(out, board, whose, now)
            out["board"] = board
            out["turn"] = self.turn
            return out

        fresh_turn = self.turn == "theirs" or self._saw_long
        if self._collapsed_to(board) and fresh_turn:
            options = self._candidates(board)
            out["candidates"] = options
            out["stored"] = max(options, key=len) if options else ""
            self._memory = []
            self.pending = board
            self.played = ""
            self._alt = ""
            self._released = True
            self._opponent_prompt = ""
            self._saw_long = True
            prompt = self._prompt(board)
            if whose == "theirs":
                self.turn = "theirs"
                self._saw_theirs = True
            else:
                self.turn = "ours"
                if prompt:
                    self._arm_play(out, prompt, whose, now)
            out["board"] = board
            out["turn"] = self.turn
            return out

        if board == self.pending:
            if whose == "theirs":
                self.turn = "theirs"
                self._saw_theirs = True
                self._ours_since = None
                self._hold = ""
                if self._prompt(board):
                    self._opponent_prompt = board
                    self._released = False
                else:
                    self._note_long(board, whose)
                self._remember(board)
                out["board"] = board
                out["turn"] = "theirs"
                return out
            if whose:
                self.turn = whose
            self._note_long(board, whose)
            prompt = self._prompt(board) if whose == "ours" else ""
            if prompt:
                self._arm_play(out, prompt, whose, now)
            out["board"] = board
            out["turn"] = self.turn
            return out

        # The whole word showed up in one frame. Keep it immediately.
        if len(board) > 4 and whose != "ours":
            self.pending = board
            self.turn = "theirs"
            self._remember(board)
            self._note_long(board, whose)
            self._alt = ""
            out["board"] = board
            out["turn"] = "theirs"
            return out

        if len(board) > 4 and whose == "ours":
            self._note_long(board, whose)
            self._remember(board)
            self.pending = board
            self._alt = ""
            out["board"] = board
            out["turn"] = self.turn
            return out

        if self._prompt(board) and whose == "ours":
            self.pending = board
            self.turn = "ours"
            self._alt = ""
            self._arm_play(out, board, whose, now)
            out["board"] = board
            out["turn"] = "ours"
            return out

        if whose == "theirs":
            self.pending = board
            self.turn = "theirs"
            self._remember(board)
            self._alt = ""
            self._arm_play(out, board, whose, now)
            out["board"] = board
            out["turn"] = "theirs"
            return out

        # One odd frame cannot erase the word already on the board.
        if board == self._alt:
            self.pending = board
            self.turn = whose or self.turn
            self._alt = ""
            self._note_long(board, whose)
            if self.turn == "theirs":
                self._remember(board)
            prompt = self._prompt(board) if whose == "ours" else ""
            if prompt:
                self._arm_play(out, prompt, whose, now)
            out["board"] = board
            out["turn"] = self.turn
            return out
        self._alt = board
        out["board"] = self.pending
        out["turn"] = self.turn
        return out

    @staticmethod
    def _prompt(board: str) -> str:
        if board.isalpha() and 1 <= len(board) <= 4:
            return board
        return ""

    @staticmethod
    def _is_submit(previous: str, current: str) -> bool:
        if len(previous) < 2 or not current or len(current) > 4 or len(previous) <= len(current):
            return False
        return previous.endswith(current)

    def _collapsed_to(self, board: str) -> bool:
        if self._is_submit(self.pending, board):
            return True
        return any(self._is_submit(word, board) for word in self._memory)


def finished_word(previous: str, current: str) -> Optional[str]:
    """A played word, once the tiles stop extending it.

    Growing tiles mean someone is still typing. A shorter board that the
    previous word ends with is the next prefix, so the previous string was
    the word they submitted.
    """
    prev = (previous or "").lower()
    cur = (current or "").lower()
    if len(prev) < 2 or prev == cur or cur.startswith(prev):
        return None
    if cur and prev.endswith(cur) and len(prev) > len(cur):
        return prev
    if len(prev) > len(cur) + 1:
        return prev
    return None


class MatchSession:
    def __init__(self, engine: Dyoe2Engine) -> None:
        self.engine = engine
        self.round = 1
        self.casual = True
        self.mode = "casual"
        self.spam_suffixes = ""
        self.last_word = ""
        self.last_suffix = ""
        self.last_trap: Optional[str] = None

    def set_casual(self, casual: bool) -> None:
        if self.mode == "spam":
            self.engine.set_casual_mode(True)
            return
        self.mode = "casual" if casual else "pro"
        self.casual = casual
        self.engine.set_casual_mode(casual)

    def set_mode(self, mode: str) -> None:
        """casual, pro, or spam. Spam plays words that end with the typed prefixes."""
        mode = mode if mode in ("casual", "pro", "spam") else "casual"
        self.mode = mode
        self.casual = mode != "pro"
        self.engine.set_casual_mode(self.casual)
        if mode == "spam":
            self.engine.set_hybrid_suffixes(self.spam_suffixes)
            self.engine.set_phase(5)
        else:
            self.engine.set_phase(phase_for_round(self.round))

    def set_spam_suffixes(self, raw: str) -> None:
        self.spam_suffixes = raw or ""
        if self.mode == "spam":
            self.engine.set_hybrid_suffixes(self.spam_suffixes)
            if self.engine.phase != 5:
                self.engine.set_phase(5)

    def new_game(self) -> None:
        self.engine.clear_used()
        self.engine.rotate_for_new_game(casual=self.casual, persist=True)
        self.round = 1
        if self.mode == "spam":
            self.engine.set_hybrid_suffixes(self.spam_suffixes)
            self.engine.set_phase(5)
        else:
            self.engine.set_phase(1)
        self.last_word = ""
        self.last_suffix = ""
        self.last_trap = None

    def note_opponent_word(self, word: str) -> bool:
        cleaned = re.sub(r"[^a-z'\-]", "", (word or "").lower())
        if len(cleaned) < 2 or cleaned in self.engine.used_words:
            return False
        if not self.engine._is_known_word(cleaned):
            return False
        self.engine.mark_used(cleaned)
        return True

    def note_seen_words(self, words: list) -> str:
        """Store the longest real word among the readings that ended the turn.

        A shorter misread is ignored when the full word was also on screen.
        """
        best = ""
        for word in words:
            cleaned = re.sub(r"[^a-z'\-]", "", (word or "").lower())
            if len(cleaned) < 2 or len(cleaned) < len(best):
                continue
            if cleaned in self.engine.used_words:
                continue
            if not self.engine._is_known_word(cleaned):
                continue
            best = cleaned
        if not best:
            return ""
        self.engine.mark_used(best)
        return best

    def recover_partial(self, partials: list, ending: str) -> str:
        """The tiles closed early. The new prompt is the ending they actually played.

        `nesti` is not a word, and the next prompt is `ing`, so the word is the
        dictionary entry that starts with that fragment and ends with `ing`.
        """
        ending = re.sub(r"[^a-z]", "", (ending or "").lower())
        if not 1 <= len(ending) <= 4:
            return ""
        fragments: list[str] = []
        for raw in partials or []:
            cleaned = re.sub(r"[^a-z]", "", (raw or "").lower())
            if len(cleaned) < 4 or cleaned == ending or cleaned in fragments:
                continue
            fragments.append(cleaned)
        fragments.sort(key=len, reverse=True)
        wordlist = self.engine.wordlist
        for partial in fragments:
            if (
                partial.endswith(ending)
                and len(partial) > len(ending)
                and partial != self.last_word
                and self.engine._is_known_word(partial)
            ):
                self.engine.mark_used(partial)
                return partial
            start = bisect_left(wordlist, partial)
            stop = bisect_right(wordlist, partial + "\uffff")
            best = ""
            best_len = 0
            ties = 0
            for word in wordlist[start:stop]:
                gap = len(word) - len(partial)
                if gap <= 0 or gap > 5 or not word.endswith(ending) or len(word) <= len(ending):
                    continue
                if not best or len(word) < best_len:
                    best = word
                    best_len = len(word)
                    ties = 1
                elif len(word) == best_len:
                    ties += 1
            if best and ties == 1:
                self.engine.mark_used(best)
                return best
        return ""

    def note_opponent_bridge(self, word: str, given: str, nxt: str) -> bool:
        """Store the opponent's word only when it actually links the two prefixes."""
        cleaned = re.sub(r"[^a-z'\-]", "", (word or "").lower())
        given = (given or "").lower()
        nxt = (nxt or "").lower()
        if cleaned == self.last_word:
            return False
        if given and (not cleaned.startswith(given) or len(cleaned) <= len(given)):
            return False
        if nxt and not cleaned.endswith(nxt):
            return False
        return self.note_opponent_word(cleaned)

    def prepare(self, prefix: str) -> int:
        if self.mode == "spam":
            self.engine.set_casual_mode(True)
            self.engine.set_hybrid_suffixes(self.spam_suffixes)
            if self.engine.phase != 5:
                self.engine.set_phase(5)
            return 5
        self.round = sync_round_to_prefix(self.round, prefix)
        phase = phase_for_prompt(self.round, prefix)
        self.engine.set_casual_mode(self.casual)
        self.engine.set_phase(phase)
        return phase

    def choices(self, prefix: str, limit: int = 3) -> list:
        """Top words the engine would play for this prefix, best first."""
        prefix = (prefix or "").strip().lower()
        self.prepare(prefix)
        if not prefix:
            return []
        out = []
        for word in self.engine.ranked_words(prefix, limit=limit):
            if not word.startswith(prefix) or len(word) <= len(prefix):
                continue
            if any(ch.isspace() for ch in word):
                continue
            out.append(word)
            if len(out) >= limit:
                break
        return out

    def choose(self, prefix: str) -> Tuple[str, str, Optional[str], int]:
        """Return word, suffix to type, trap, phase. Suffix excludes the prefix."""
        prefix = (prefix or "").strip().lower()
        phase = self.prepare(prefix)
        if not prefix:
            return "", "", None, phase
        ranked = self.choices(prefix, 12)
        for word in ranked:
            if not word.startswith(prefix) or len(word) <= len(prefix):
                continue
            suffix = word[len(prefix) :]
            if not suffix or any(ch.isspace() for ch in suffix):
                continue
            match = self.engine.matched_trap_for_word(word)
            trap = match[1] if match else None
            self.last_word = word
            self.last_suffix = suffix
            self.last_trap = trap
            return word, suffix, trap, phase
        self.last_word = ""
        self.last_suffix = ""
        self.last_trap = None
        return "", "", None, phase

    def commit_play(self, word: str) -> None:
        word = (word or "").lower()
        if not word:
            return
        match = self.engine.matched_trap_for_word(word)
        self.engine.mark_used(word)
        if match is not None:
            phase, trap = match
            self.engine.deprioritize_trap(phase, trap, persist=True)
        self.round += 1
