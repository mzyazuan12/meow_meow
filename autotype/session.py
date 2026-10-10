from __future__ import annotations

import math
import re
import random
import zlib
from bisect import bisect_left, bisect_right
from collections import Counter
from dataclasses import dataclass
from typing import Iterable, Optional, Tuple

from dyoe2_engine import BLACKLISTED_TRAP_PREFIXES, Dyoe2Engine, word_has_punctuation

ROUNDS_PER_PHASE = 5
# OCR can split a username and confuse I/l/1 in the instruction itself.
_INSTRUCTION_RE = re.compile(r"t[yv?]pe\s*a[n?]\s*en[g9?][il1?]{2}s[h?]\s*w[o0q?]rd", re.I)
_TURN_RE = re.compile(r"(?:t[yv?]pe\s*a[n?]\s*en[g9?][il1?]{2}s[h?]\s*w[o0q?]rd|start[il1?]ng\s*with)", re.I)

def phase_for_round(round_n: int) -> int:
    n = max(1, int(round_n or 1))
    return min(4, 1 + (n - 1) // ROUNDS_PER_PHASE)

def phase_for_prompt(round_n: int, prefix: str) -> int:
    length = len(prefix or "")
    by_len = 1 if length <= 1 else min(4, length)
    return by_len

def sync_round_to_prefix(round_n: int, prefix: str) -> int:

    need = 1 if len(prefix) <= 1 else min(4, len(prefix))
    round_n = max(1, int(round_n or 1))
    guard = 0
    while phase_for_round(round_n) < need and guard < 4:
        round_n += ROUNDS_PER_PHASE
        guard += 1
    return round_n

def _name_key(value: str) -> str:
    return re.sub(r"[^a-z0-9_]", "", (value or "").lower())


def _ocr_distance(a: str, b: str) -> float:
    groups = ("o0q", "il1", "yv", "g9", "s5", "b8")
    row = list(range(len(b) + 1))
    for i, left in enumerate(a, 1):
        nxt = [float(i)]
        for j, right in enumerate(b, 1):
            cost = 0.0 if left == right else 0.25 if any(left in g and right in g for g in groups) else 1.0
            nxt.append(min(row[j] + 1, nxt[-1] + 1, row[j - 1] + cost))
        row = nxt
    return row[-1]


def names_match(ours: str, seen: str) -> bool:
    a, b = _name_key(ours), _name_key(seen)
    if not a or not b:
        return False
    if a == b:
        return True
    if min(len(a), len(b)) < 4:
        return False
    letters_a = re.sub(r"[0-9_]", "", a)
    letters_b = re.sub(r"[0-9_]", "", b)
    if letters_a == letters_b and re.sub(r"[^0-9]", "", a) != re.sub(r"[^0-9]", "", b):
        # player1 and player2 are separate people, even though most letters match.
        return False
    # Never match just a shared number or a tiny substring of someone else's name.
    if min(len(a), len(b)) < max(len(a), len(b)) * 0.65:
        return False
    return _ocr_distance(a, b) <= max(0.5, max(len(a), len(b)) * 0.26)


def speaker_from_header(header: str, name: str = "") -> str:
    text = header or ""
    match = _INSTRUCTION_RE.search(text)
    if not match:
        # The second instruction line can survive when the first is misread.
        match = _TURN_RE.search(text)
        if not match:
            return ""
        text = text[:match.start()].split(",", 1)[0]
        match = None
    # The name is the last token on the instruction's line. Menu icons sit in
    # front of it, separated by real gaps, so they must not be glued on.
    head = re.split(r"\n|\|", text[:match.start()] if match else text)[-1]
    tokens = re.findall(r"[A-Za-z0-9_]{1,32}", head)
    if not tokens:
        return ""
    if name:
        # OCR inserts spaces inside long usernames. Compare joined trailing
        # tokens with the configured identity without joining menu icons blindly.
        candidates = [_name_key("".join(tokens[start:])) for start in range(len(tokens))]
        matches = [joined for joined in candidates if names_match(name, joined)]
        if matches:
            return min(matches, key=lambda joined: _ocr_distance(_name_key(name), joined))
    tokens = [token for token in tokens if len(token) >= 2]
    return _name_key(tokens[-1]) if tokens else ""


def header_is_ours(name: str, header: str) -> bool:
    return header_is_turn(header) and names_match(name, speaker_from_header(header, name))


def already_used_text(text: str) -> bool:
    low = re.sub(r"[^a-z]+", " ", (text or "").lower())
    return "already" in low and "used" in low


def rejected_text(text: str) -> bool:
    low = (text or "").lower()
    return already_used_text(low) or any(term in low for term in ("not a word", "invalid word", "not an english word"))


def header_is_turn(header: str) -> bool:
    return bool(_TURN_RE.search(header or ""))


# A glitched prompt is the real ending shuffled, sometimes with stray letters
# (kinging -> "gnigk" instead of "ging"). More strays than this is not a shuffle
# of anything we can name.
MAX_SCRAMBLE_EXTRA = 2
# How long a prompt shorter than the last one played must stay on screen
# before it is believed. Tiles of a longer prompt land well inside this.
SHORT_PROMPT_HOLD = 0.3
# The same for a prompt worked out from a mirrored or shuffled row while it
# could still gain a tile: "noi" is the start of "noit" ("tion" mirrored).
DERIVED_HOLD = 0.12


def _clean_word(text: str) -> str:
    return re.sub(r"[^a-z'\-]", "", (text or "").lower())


def _fits(ending: str, read: str) -> bool:
    """Every letter of ``ending`` is present in ``read``, in any order."""
    return not (Counter(ending) - Counter(read))


def prompt_lengths(given_len: int, phase: int = 0) -> list:
    """Lengths the next prompt can have, most likely first.

    The phase is the prompt length: a player handed "king" is in phase 4 and
    the prompt after their word is 4 letters too. The prompt only gains a
    letter at a stage change, so one longer is the second guess.
    """
    base = given_len if 1 <= given_len <= 4 else (phase if 1 <= phase <= 4 else 0)
    if not base:
        return []
    return [base] + ([base + 1] if base < 4 else [])


def _plausible_read(read: str, given: str, words: list) -> bool:
    """Whether a clean capture could show ``read`` while that word is typed.

    It is either the prompt they were given (and their word growing from it),
    a piece of their word, or the ending their word hands over.
    """
    if given and read.startswith(given):
        return True
    return any(word.endswith(read) or word.startswith(read) for word in words)


class BoardWatch:
    """Track acceptance at turn boundaries, separately from letters being typed.

    Two complete, identical board reads confirm a prompt. There is no timer-based
    lead-in; incomplete tiles reset confirmation and never lose their positions.
    """

    def __init__(self) -> None:
        self.reset()

    def reset(self) -> None:
        self.turn = ""
        self.pending = ""
        self.played = ""
        self.typed = ""
        self._memory: list[str] = []
        self._last_reads: list[str] = []
        self._given = ""
        self._opponent_active = False
        self._await_opponent = False
        self._candidate = ""
        self._candidate_hits = 0
        self._recovery_pending = False
        self._recovery_given = ""
        self._reject_hits = 0
        self._reject_since = 0.0
        self._last_accepted = ""
        self._retry_prompt = ""
        self._clock = 0.0
        self._hold_board = ""
        self._hold_since = 0.0
        # Latest word the opponent actually typed. A mirrored prompt is checked
        # against this ending before a dictionary reverse is trusted.
        self._opponent_word = ""
        # Prompts only get longer within a game. A read shorter than the last
        # one played is usually a row still drawing in ("lee" for "leet").
        self.floor = 0
        self._candidate_since = 0.0
        # Their word, prompt and readings, kept for the whole of our reply.
        self._context: Optional[Tuple[str, str, list]] = None

    def forget_partials(self) -> None:
        self._last_reads = []
        self._recovery_pending = False

    def rearm(self, prompt: str, now: float) -> None:
        self.played = ""
        self.typed = ""
        self.pending = self._prompt(prompt)
        self.turn = "ours"
        self._await_opponent = False
        self._candidate = self.pending
        self._candidate_hits = 1
        self._candidate_since = now
        self._retry_prompt = self.pending
        self._reject_hits = 0
        self.floor = max(self.floor, len(self.pending))

    def forget_context(self) -> None:
        self._context = None

    def _blank(self) -> dict:
        return {"play": "", "stored": "", "candidates": [], "accepted": False,
                "rejected": False, "board": self.pending, "turn": self.turn,
                "partials": list(self._last_reads), "given": self._recovery_given,
                "ending": ""}

    def _remember(self, board: str) -> None:
        if len(board) < 2 or board == self.typed or board == self._last_accepted:
            return
        if (len(board) > 4 and self._given and len(self._opponent_word) > len(self._given)
                and self._opponent_word.startswith(self._given)
                and not board.startswith(self._given)):
            # Their word must grow out of the prompt they were handed. A long
            # read that does not is a glitched frame; it must not overwrite
            # the word the ending is worked out from.
            return
        if not self._memory or self._memory[-1] != board:
            self._memory.append(board)
            self._memory = self._memory[-32:]
        self._last_reads = list(self._memory)
        # Keep the word they built. A later 1–4 letter prompt must not replace
        # it, but a backspaced correction longer than any prompt does.
        if "?" not in board and (len(board) > 4 or len(board) >= len(self._opponent_word)):
            self._opponent_word = board

    @property
    def opponent_word(self) -> str:
        return self._opponent_word

    def scramble_context(self) -> Optional[Tuple[str, str, list]]:
        """What a glitched prompt can be solved from, or None between turns.

        ``(their word, the prompt they were given, every reading of it)``. Their
        word stays the context until our answer to it is accepted, so the fix
        holds on every capture of our turn, not just the first one.
        """
        if not self._opponent_active:
            return self._context
        return self._opponent_word, self._given, [m for m in self._memory if "?" not in m]

    @staticmethod
    def _prompt(board: str) -> str:
        return board if re.fullmatch(r"[a-z'-]{1,4}", board) else ""

    def observe(self, board: str, whose: str, *, complete: bool = True,
                tiles: int = 0, now: float | None = None, derived: bool = False) -> dict:
        board = re.sub(r"[^a-z?'\-]", "", (board or "").lower())
        whose = whose if whose in ("ours", "theirs") else ""
        self._clock = now if now is not None else self._clock
        complete = complete and "?" not in board and (not tiles or tiles == len(board))
        out = self._blank()
        previous_turn = self.turn
        previous_board = self.pending
        prompt = self._prompt(board) if complete else ""

        # Submission is not acceptance. A new speaker or the submitted word's
        # ending becoming the board confirms that Enter was accepted.
        if self.typed:
            collapsed = bool(prompt and prompt != self.played and len(self.typed) > len(prompt)
                             and self.typed.endswith(prompt) and board != previous_board)
            if whose == "theirs" or collapsed:
                out["accepted"] = True
                expected = self.typed[-len(prompt):] if prompt else ""
                self._last_accepted = self.typed
                self.typed = ""
                self.played = ""
                self._await_opponent = True
                self._opponent_active = True
                self._memory = []
                self._last_reads = []
                self._opponent_word = ""
                self._context = None
                self._given = prompt if prompt == expected else ""
                self.floor = max(self.floor, len(self._given))
                self._candidate = ""
                self._candidate_hits = 0
                self._reject_hits = 0
                # A fast opponent can already have typed their whole answer
                # in the very capture that confirms our Enter. Keep that frame.
                if whose == "theirs":
                    self._remember(board)
                # Header can lag the board by one capture; do not replay it.
                self.turn = "theirs"
                if board:
                    self.pending = board
                out.update(board=self.pending, turn=self.turn, partials=[])
                return out
            if complete and board == self.played and (self._reject_hits or len(previous_board) > len(board)):
                self._reject_hits += 1
                if self._reject_hits == 1:
                    self._reject_since = self._clock
                # A valid word can end with its own starting prefix. Give the
                # speaker line time to catch up before treating that as a reset.
                same_ending = self.typed.endswith(board)
                if self._reject_hits >= 2 and (not same_ending or self._clock - self._reject_since >= 0.5):
                    out["rejected"] = True
                    self.typed = ""
                    self.played = ""
                    self._await_opponent = False
            else:
                self._reject_hits = 0
            if board and complete:
                self.pending = board
            out.update(board=self.pending, turn=self.turn)
            return out

        if whose == "theirs":
            if previous_turn != "theirs" and not self._opponent_active:
                self._memory = []
                self._last_reads = []
                self._opponent_word = ""
                self._context = None
                self._given = prompt
            if not self._given and prompt and not self._memory:
                self._given = prompt
            elif (prompt and self._given and len(self._given) < len(prompt) <= self.floor
                    and prompt.startswith(self._given)):
                # Read while it was still drawing in: their prompt is at least
                # as long as the last one played.
                self._given = prompt
            last = self._last_accepted
            if (prompt and last and len(last) > len(prompt) > len(self._given)
                    and last.endswith(prompt) and len(prompt) <= max(self.floor, 1) + 1):
                # Their prompt is the ending of our word. Its first tiles can
                # read before the rest of it lands, so the longest one counts,
                # and our next prompt is at least that long.
                self._given = prompt
                self.floor = max(self.floor, len(prompt))
            self._opponent_active = True
            self._await_opponent = False
            self.turn = "theirs"
            self._candidate = ""
            self._candidate_hits = 0
            self._remember(board)
            if complete and board:
                self.pending = board
            out.update(board=self.pending, turn=self.turn, partials=list(self._last_reads))
            return out

        # Record the last long reading even if the header has already flipped.
        if self._opponent_active and board and not prompt:
            self._remember(board)
        if not complete or not board:
            self._candidate = ""
            self._candidate_hits = 0
            out.update(partials=list(self._last_reads))
            return out

        if whose != "ours":
            # A blank/unread header is never authority to start typing.
            out.update(board=self.pending, partials=list(self._last_reads))
            return out

        if self._await_opponent and prompt == self._given and not self._memory:
            # The board collapsed before the speaker changed. Repeated captures
            # of that same ending are still the opponent's starting prefix.
            out.update(board=self.pending, partials=list(self._last_reads))
            return out

        if self._opponent_active and prompt:
            if board == previous_board and self._given and len(board) > len(self._given):
                # A 2–4 letter prefix is often already on screen while the
                # header still names the opponent, and it is longer than the
                # prefix they were given. Their own short word is the only
                # reading we have in that case; a prefix we watched them play
                # toward is shorter than that word. Hold the short word briefly
                # so it can collapse, then accept a prefix that stays.
                longer = any(len(word) > len(board) and "?" not in word for word in self._memory)
                if not longer:
                    if self._hold_board != board:
                        self._hold_board = board
                        self._hold_since = self._clock
                    if self._clock - self._hold_since < 0.25:
                        out.update(partials=list(self._last_reads))
                        return out
                    self._candidate = prompt
                    self._candidate_hits = 1
                    self._candidate_since = self._hold_since
            self._hold_board = ""
            # A header change cannot, by itself, turn their final short word
            # into a prefix. The branch above waits for that word to collapse.
            self._recovery_pending = True
            # Attaching mid-turn can make the first short read a finished word,
            # rather than a starting prefix. Keep that reading too.
            self._recovery_given = (self._given if any(len(word) > len(self._given)
                                                      for word in self._memory) else "")
            self._context = (self._opponent_word, self._given,
                             [m for m in self._memory if "?" not in m])
            self._opponent_active = False
            self._await_opponent = False
            self.played = ""
            self._last_reads = list(self._memory)
            self._memory = []
            self._given = ""

        self.turn = "ours"
        self.pending = board
        out.update(board=board, turn=self.turn, partials=list(self._last_reads), given=self._recovery_given)
        if self._recovery_pending and prompt:
            options = [word for word in self._last_reads if "?" not in word
                       and len(word) > len(prompt) and word.endswith(prompt)
                       and (not self._recovery_given or word.startswith(self._recovery_given))]
            out.update(candidates=options, stored=max(options, key=len) if options else "")
        # "i" can confirm before the rest of "is" lands. A latched short word
        # can also collapse to the ending that is the real prefix. A different
        # word (their "wow" while we still hold "sk") must not steal the latch.
        grew = prompt.startswith(self.played) and len(prompt) > len(self.played)
        collapsed = self.played.endswith(prompt) and len(self.played) > len(prompt)
        if whose == "ours" and prompt and self.played and not self.typed and (grew or collapsed):
            self.played = ""
            self._candidate = ""
            self._candidate_hits = 0
        if not prompt or self.played or self._await_opponent:
            return out
        if self._retry_prompt and prompt != self._retry_prompt and self._retry_prompt.startswith(prompt):
            # A clipped old prefix is not a new turn. An unrelated stable
            # prefix must still be allowed after a missed opponent boundary.
            return out
        if prompt == self._candidate:
            self._candidate_hits += 1
        else:
            self._candidate, self._candidate_hits = prompt, 1
            self._candidate_since = self._clock
        # The ending of the word they just typed already confirms this read;
        # anything else waits for a second identical capture. A board already
        # worked out from that word (unshuffled, unmirrored) is not a read.
        word = self._opponent_word
        short = len(prompt) < self.floor
        vouched = not derived and not short and len(word) > len(prompt) and word.endswith(prompt)
        if self._candidate_hits < (1 if vouched else 2):
            return out
        held = self._clock - self._candidate_since
        if short and held < SHORT_PROMPT_HOLD:
            # Shorter than a prompt already played: the rest of the row is
            # usually still drawing. A new game's prompt stays and is taken.
            return out
        if derived and len(prompt) < 4 and held < DERIVED_HOLD:
            return out
        self._retry_prompt = ""
        self.floor = len(prompt)
        out["play"] = prompt
        if self._recovery_pending:
            options = [word for word in self._last_reads if "?" not in word
                       and len(word) > len(prompt) and word.endswith(prompt)
                       and (not self._recovery_given or word.startswith(self._recovery_given))]
            out.update(candidates=options, stored=max(options, key=len) if options else "", ending=prompt)
            self._recovery_pending = False
        return out

def finished_word(previous: str, current: str) -> Optional[str]:

    prev = (previous or "").lower()
    cur = (current or "").lower()
    if len(prev) < 2 or prev == cur or cur.startswith(prev):
        return None
    if cur and prev.endswith(cur) and len(prev) > len(cur):
        return prev
    if len(prev) > len(cur) + 1:
        return prev
    return None

PHASE1_MAX_SUFFIX = 14
MAX_SUFFIX = 30
# Seconds per typed letter assumed when fitting an answer into the turn clock,
# including reaction time; human pace, not the fastest the keys can go.
SECONDS_PER_LETTER = 0.18
GIVEN_WEIGHT = 3
PUNCTUATION_BONUS = 2
EASY_PLURAL_PENALTY = 3
# An ending with more playable answers than this is never treated as a trap.
TRAP_SCAN = 40
_TRAP_CHARS = re.compile(r"^[a-z'\-]+$")


def max_suffix_for(time_left: Optional[float], phase: int) -> int:
    cap = MAX_SUFFIX if time_left is None else int((time_left - 1.0) / SECONDS_PER_LETTER)
    cap = max(2, min(MAX_SUFFIX, cap))
    return min(cap, PHASE1_MAX_SUFFIX) if phase == 1 else cap


def edit_cost(current: str, target: str) -> Tuple[int, int]:
    """Backspaces and letters needed to turn the typed word into another."""
    common = 0
    for a, b in zip(current, target):
        if a != b:
            break
        common += 1
    return len(current) - common, len(target) - common


_SPREADS = (("razor", 0.5), ("sharp", 0.75), ("wide", 1.0))
_FOCUS = (0.3, 0.5, 0.75, 1.0)
_WORD_STYLES = ("long", "short", "mid", "any")
# How much the length of the answers counts against how few there are. Low
# prefers the fewest answers, high accepts a few more if they are all long.
_WEIGHTS = (0.3, 0.5, 0.8)
# Endings a game may lean towards. They only favour; nothing is ever excluded.
_FAMILIES = ("any", "rare", "cluster", "vowel", "soft")
_RARE_LETTERS = frozenset("jqxzkvwy")
_VOWELS = frozenset("aeiou")


def trap_family(trap: str, family: str) -> bool:
    """Whether an ending belongs to a family of endings."""
    if family == "rare":
        return any(c in _RARE_LETTERS for c in trap)
    if family == "cluster":
        return len(trap) >= 2 and not any(c in _VOWELS for c in trap[-2:]) and trap[-1].isalpha()
    if family == "vowel":
        return trap[-1] in _VOWELS
    if family == "soft":
        return trap[-1] in "lmnrsth" and any(c in _VOWELS for c in trap)
    return True


@dataclass(frozen=True)
class TrapStyle:
    """How one game picks its traps and words.

    A trap is any ending of our word, scored from the dictionary alone: how few
    answers it leaves and how long they are. Nothing is looked up in a list.
    A style only decides what counts as equally deadly (``width``: bands on a
    log scale, so 1 left is never mixed with 30 left), how much long answers
    count against few of them (``weight``), which endings are favoured this
    game (``focus`` share, ``family`` shape), and what our word looks like.
    """
    seed: int
    spread: str
    width: float
    focus: float
    words: str
    target: int
    weight: float = 0.5
    family: str = "any"

    @classmethod
    def roll(cls, previous: Optional["TrapStyle"] = None,
             rng: Optional[random.Random] = None) -> "TrapStyle":
        rng = rng or random.SystemRandom()
        for _ in range(12):
            spread, width = rng.choice(_SPREADS)
            style = cls(rng.randrange(1 << 30), spread, width, rng.choice(_FOCUS),
                        rng.choice(_WORD_STYLES), rng.randint(3, 9),
                        rng.choice(_WEIGHTS), rng.choice(_FAMILIES))
            if previous is None or style.signature != previous.signature:
                break
        return style

    @property
    def signature(self) -> tuple:
        return (self.spread, self.focus, self.words, self.target if self.words == "mid" else 0,
                self.weight, self.family)

    def hash(self, key: str) -> float:
        return zlib.crc32(f"{self.seed}:{key}".encode()) / 4294967296.0

    def favours(self, trap: str) -> bool:
        if not trap_family(trap, self.family):
            return False
        return self.focus >= 1.0 or self.hash("f:" + trap) < self.focus

    @property
    def label(self) -> str:
        words = {"long": "long words", "short": "short words", "any": "mixed words",
                 "mid": f"~{self.target}-letter endings"}[self.words]
        focus = "all traps" if self.focus >= 1.0 else f"{round(self.focus * 100)}% of traps"
        family = "" if self.family == "any" else f" · {self.family} endings"
        reach = {0.3: "fewest", 0.5: "few + long", 0.8: "long first"}.get(self.weight, "")
        return f"{self.spread} · {reach} · {focus}{family} · {words}"


# The plain order, used before any game has rolled a style.
CLASSIC_STYLE = TrapStyle(0, "razor", 0.25, 1.0, "long", 5, 0.5, "any")


class MatchSession:
    def __init__(self, engine: Dyoe2Engine) -> None:
        self.engine = engine
        # None plays the plain fewest-answers-left order. A game started with
        # new_game() draws a style, so no two games choose alike.
        self.style: Optional[TrapStyle] = None
        self.round = 1
        self.casual = True
        self.mode = "casual"
        # Spam is casual or pro, plus the typed endings in front of that ranking.
        self.spam_base = "casual"
        self._allow_punctuation()
        self.spam_suffixes = ""
        self.last_word = ""
        self.last_suffix = ""
        self.last_trap: Optional[str] = None
        self.opponent_word = ""
        self.last_prefix = ""
        # How many times each prefix was handed to an opponent this game.
        self.given: dict[str, int] = {}
        self._given_word = ""
        self._given_key = ""
        self._choice_cache_key = None
        self._choice_cache: list[str] = []
        self._choice_traps: dict[str, str] = {}
        self._total_cache: dict[str, int] = {}
        self._total_stamp: tuple = ()
        self.unreadable_words: set[str] = set()
        self.unreadable_prefixes: set[str] = set()

    def _allow_punctuation(self) -> None:
        # Casual is letters only. Pro, and spam set to pro, can still play - and '.
        allowed = not self.casual
        if getattr(self.engine, "allow_punctuation", False) == allowed:
            return
        self.engine.allow_punctuation = allowed
        self.engine.clear_cache()

    def set_casual(self, casual: bool) -> None:
        if self.mode == "spam":
            self.set_spam_base("casual" if casual else "pro")
            return
        self.mode = "casual" if casual else "pro"
        self.casual = casual
        self._allow_punctuation()
        self.engine.set_casual_mode(casual)

    def set_mode(self, mode: str) -> None:

        mode = mode if mode in ("casual", "pro", "spam") else "casual"
        self.mode = mode
        if mode == "spam":
            self.casual = self.spam_base != "pro"
        else:
            self.casual = mode != "pro"
        self._allow_punctuation()
        self.engine.set_casual_mode(self.casual)
        if mode == "spam":
            self.engine.set_hybrid_suffixes(self.spam_suffixes)
        else:
            self.engine.set_hybrid_suffixes(())
        self.engine.set_phase(phase_for_prompt(self.round, self.last_prefix))

    def set_spam_base(self, base: str) -> None:
        """Spam keeps casual or pro rules, and only adds the typed endings."""
        self.spam_base = "pro" if str(base or "").strip().lower() == "pro" else "casual"
        if self.mode != "spam":
            return
        self.casual = self.spam_base != "pro"
        self._allow_punctuation()
        self.engine.set_casual_mode(self.casual)
        self._choice_cache_key = None

    def set_spam_suffixes(self, raw: str) -> None:
        self.spam_suffixes = raw or ""
        if self.mode == "spam":
            self.engine.set_hybrid_suffixes(self.spam_suffixes)
            self._choice_cache_key = None

    def new_game(self) -> None:
        self.engine.clear_used()
        self.unreadable_words.clear()
        self.unreadable_prefixes.clear()
        self.style = TrapStyle.roll(self.style)
        for casual in (True, False):
            self.engine.rotate_for_new_game(casual=casual, persist=False, shuffle=True)
        self.round = 1
        self.last_prefix = ""
        self.engine.trap_phases = ()
        if self.mode == "spam":
            self.casual = self.spam_base != "pro"
            self._allow_punctuation()
            self.engine.set_casual_mode(self.casual)
            self.engine.set_hybrid_suffixes(self.spam_suffixes)
        self.engine.set_phase(1)
        self.last_word = ""
        self.last_suffix = ""
        self.last_trap = None
        self.opponent_word = ""
        self.given = {}
        self._given_word = self._given_key = ""
        self._choice_cache_key = None
        self._choice_cache = []

    def note_opponent_word(self, word: str) -> bool:
        cleaned = re.sub(r"[^a-z'\-]", "", (word or "").lower())
        if len(cleaned) < 2 or cleaned in self.engine.used_words:
            return False
        if not self.engine._is_known_word(cleaned):
            return False
        self.engine.mark_used(cleaned)
        return True

    def note_seen_words(self, words: list) -> str:

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

    def recover_partial(self, partials: list, ending: str, given: str = "") -> str:
        """Recover using the longest reading, its tile slots, and both prefixes.

        A complete valid reading wins. A clipped reading is completed only when
        the starting letters and next prefix uniquely identify a word.
        """
        ending = re.sub(r"[^a-z'\-]", "", (ending or "").lower())
        given = re.sub(r"[^a-z'\-]", "", (given or "").lower())
        if not 1 <= len(ending) <= 4:
            return ""
        fragments = {re.sub(r"[^a-z?'\-]", "", str(raw).lower()) for raw in partials or []}
        fragments = [f for f in fragments if len(f.replace("?", "")) >= 2
                     and f != given and f != ending]
        if not fragments:
            fragments = [given] if given else []
        if not fragments:
            return ""
        longest = max(len(f) for f in fragments)
        fragments = [f for f in fragments if len(f) == longest]
        # Complementary unread slots across fast frames can identify the word.
        merged = []
        for index in range(longest):
            seen = {f[index] for f in fragments if f[index] != "?"}
            if len(seen) > 1:
                break
            merged.append(next(iter(seen), "?"))
        if len(merged) == longest:
            fragments = ["".join(merged)]
        exact = {f for f in fragments if "?" not in f and f.startswith(given)
                 and f.endswith(ending) and self.engine._is_known_word(f)}
        if len(exact) == 1:
            best = exact.pop()
        else:
            candidates: dict[str, int] = {}
            for fragment in fragments:
                stem = fragment.split("?", 1)[0]
                if given and stem and not (stem.startswith(given) or given.startswith(stem)):
                    continue
                stem = stem or given
                if not stem:
                    continue
                start = bisect_left(self.engine.wordlist, stem)
                stop = bisect_right(self.engine.wordlist, stem + "\uffff")
                for index in range(start, stop):
                    word = self.engine.wordlist[index]
                    gap = len(word) - len(fragment)
                    if gap < 0 or len(word) < len(ending):
                        continue
                    if not word.startswith(given) or not word.endswith(ending):
                        continue
                    if not all(a == "?" or a == b for a, b in zip(fragment, word)):
                        continue
                    candidates[word] = gap
            if not candidates:
                # The tail of the read was garbled (kickkf for kickoffs). The
                # first letters still stand, so look for the one word that
                # starts with them and ends with the prompt we were handed.
                candidates = self._complete_from_head(fragments, given, ending)
            if not candidates:
                return ""
            best_options = list(candidates)
            if len(best_options) != 1:
                return ""
            best = best_options[0]
        if best in self.engine.used_words:
            return ""
        self.engine.mark_used(best)
        return best

    def _complete_from_head(self, fragments: list, given: str, ending: str) -> dict:
        wordlist = self.engine.wordlist
        for fragment in sorted(fragments, key=len, reverse=True):
            head = fragment.split("?", 1)[0][:4]
            if len(head) < max(3, len(given) + 1):
                continue
            start = bisect_left(wordlist, head)
            stop = bisect_right(wordlist, head + "\uffff")
            found = {w: 0 for w in wordlist[start:stop]
                     if len(w) > len(ending) and w.startswith(given) and w.endswith(ending)}
            if found:
                return found
        return {}

    def note_opponent_bridge(self, word: str, given: str, nxt: str) -> bool:

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
        self.last_prefix = prefix
        if self.mode == "spam":
            self.casual = self.spam_base != "pro"
            self.engine.set_hybrid_suffixes(self.spam_suffixes)
        phase = phase_for_prompt(self.round, prefix)
        self._allow_punctuation()
        self.engine.set_casual_mode(self.casual)
        self.engine.set_phase(phase)
        self.engine.trap_phases = ()
        return phase

    def _hands_blacklisted(self, word: str, length: int) -> bool:
        """True when playing ``word`` would hand the opponent a banned prompt."""
        if length < 2 or len(word) < length:
            return False
        return word[-length:] in BLACKLISTED_TRAP_PREFIXES

    def _direction_from_head(self, opponent: str, prefix: str, reverse: str) -> str:
        """Which way a prompt reads, from the first letters of their word.

        ``kickkf`` is a clipped read of the word they typed. Dictionary words
        beginning with its first four letters (``kick``) can end in ``fs`` but
        never in ``sf``, so the prompt ``sf`` must be the mirror of ``fs``.
        Returns "" unless exactly one direction is possible.
        """
        if len(opponent) < 4 or reverse == prefix:
            return ""
        words = self.engine.wordlist
        for size in (4, 3):
            head = opponent[:size]
            start = bisect_left(words, head)
            stop = bisect_right(words, head + "\uffff")
            pool = [w for w in words[start:stop] if len(w) > len(prefix)]
            if not pool:
                continue
            forward = any(w.endswith(prefix) for w in pool)
            backward = any(w.endswith(reverse) for w in pool)
            if backward and not forward:
                return reverse
            if forward and not backward:
                return prefix
            return ""
        return ""

    def resolve_prefix(self, prefix: str) -> str:
        """Use the read prompt, or its reverse when that is the real one.

        A forward reading that has dictionary answers is kept, unless the
        opponent's word ends with the reverse and not with the reading. Their
        ending wins in both directions: ``elet`` stays ``elet`` when they ended
        there, and a mirrored ``tele`` is turned back when they ended in ``elet``.
        """
        prefix = (prefix or "").strip().lower()
        if not prefix:
            return ""
        reverse = prefix[::-1]
        opponent = re.sub(r"[^a-z'\-]", "", (self.opponent_word or "").lower())
        if opponent and len(opponent) >= len(prefix):
            ended = opponent.endswith(prefix)
            ended_backwards = reverse != prefix and opponent.endswith(reverse)
            if ended_backwards and not ended:
                return reverse
            if ended and not ended_backwards:
                return prefix
        # The tail of what we saw of their word can be garbled (kickkf for
        # kickoffs) while its first letters are reliable. Only one direction
        # can be handed over from those letters, so that direction wins.
        decided = self._direction_from_head(opponent, prefix, reverse)
        if decided:
            return decided
        if self.engine.prefix_has_play(prefix):
            return prefix
        if reverse != prefix and self.engine.prefix_has_play(reverse):
            return reverse
        return prefix

    def descramble_prompt(self, read: str, word: str = "", given: str = "",
                          seen: Optional[list] = None, floor: int = 0) -> str:
        """The real prompt behind a glitched read, or "" when it is not one.

        A fast opponent can leave the board mid-shuffle: after "kinging" on
        the prefix "king" the tiles read "gnigk" instead of "ging". The prompt
        is always the last letters of their word, and its length is the phase
        (the length of the prefix they were given). So the read is an anomaly
        when it is neither their prompt growing, nor part of their word, nor
        its ending, and the answer is the ending of that length whose letters
        are all in the read, extra tile and shuffled order included.

        Their word is used when it is a whole dictionary word. When their
        last reading was clipped (the opponent typed faster than the capture),
        the dictionary words that begin with what was seen settle it, as long
        as exactly one ending fits.

        ``floor`` is the longest prompt played this game; prompts never get
        shorter, so "slo" for "ols" is not an "s" with two stray tiles.
        """
        read = _clean_word(read)
        word = _clean_word(word)
        given = _clean_word(given)
        seen = [w for w in (_clean_word(s) for s in (seen or [])) if w]
        if len(read) < 2 or not (word or given):
            return ""
        if _plausible_read(read, given, [w for w in [word, *seen] if w]):
            return ""
        lengths = [n for n in prompt_lengths(max(len(given), floor), self.engine.phase)
                   if n <= len(read) and len(read) - n <= MAX_SCRAMBLE_EXTRA]
        if not lengths:
            return ""
        engine = self.engine
        flipped = read[::-1] if len(read) in lengths else ""
        if word and word.startswith(given) and engine._is_known_word(word):
            if flipped and len(word) > len(read) and word.endswith(flipped):
                # The whole row the other way round, not a shorter prompt
                # with stray tiles.
                return flipped
            for n in lengths:
                if len(word) > n and word[-n:] != read and _fits(word[-n:], read):
                    return word[-n:]
        # Their last reading was cut short (or is a word on the way to a
        # longer one): complete it from the dictionary.
        stems = sorted({w for w in [word, *seen] if w.startswith(given) and len(w) > len(given)},
                       key=len, reverse=True)
        if not stems:
            return ""
        wordlist, used = engine.wordlist, engine.used_words
        tried = set()
        for stem in stems[:2]:
            # The final tile of a clipped read can itself be wrong.
            for cut in range(3):
                head = stem[:len(stem) - cut]
                if len(head) <= len(given) or head in tried:
                    continue
                tried.add(head)
                start = bisect_left(wordlist, head)
                stop = bisect_right(wordlist, head + "\uffff")
                if flipped:
                    tails = {w[-len(read):] for w in wordlist[start:stop]
                             if len(w) > len(read) and w not in used}
                    if read in tails:
                        return ""
                    if flipped in tails:
                        return flipped
                for n in lengths:
                    endings = {w[-n:] for w in wordlist[start:stop]
                               if len(w) > n and w not in used and _fits(w[-n:], read)}
                    if read in endings:
                        # A word it can still be ends exactly so: "ts" after a
                        # clipped "abstrac" is clean, not a shuffled "st".
                        return ""
                    if len(endings) == 1:
                        return endings.pop()
                    if endings:
                        return ""
        return ""

    def _total_solves(self, trap: str) -> int:
        """Dictionary answers for a prefix, used or not."""
        stamp = (id(self.engine.wordlist), len(self.engine.wordlist))
        if stamp != self._total_stamp:
            self._total_cache.clear()
            self._total_stamp = stamp
        if trap not in self._total_cache:
            start = bisect_left(self.engine.wordlist, trap)
            stop = bisect_right(self.engine.wordlist, trap + "\uffff")
            self._total_cache[trap] = sum(len(w) > len(trap) for w in self.engine.wordlist[start:stop])
        return self._total_cache[trap]

    def _trap_pool(self, length: int) -> dict[str, int]:
        """DYOE2's trap sources for one prefix length, in their list order.

        A prefix that starts or ends with - or ' can never be handed over as
        a prompt, so it is not a trap.
        """
        pool = self.engine.get_ordered_traps(length) if 2 <= length <= 4 else []
        return {t: i for i, t in enumerate(pool)
                if t[0] not in "-'" and t[-1] not in "-'"}

    def _trap_stats(self, trap: str, blocked: frozenset, letters_only: bool):
        """What handing ``trap`` over would leave the opponent; None if useless.

        This reads the dictionary only. A trap is an ending with few answers
        left, and long ones. Returns ``(left, value, easy_plural, shortest,
        mean)`` where ``left`` is the answers still playable, ``value`` adds the
        penalties for earlier hand-overs, and shortest/mean are how many
        letters the opponent still has to type.

        A prefix that starts or ends with - or ' can never be a prompt, and
        one that is itself an unused word is answered by pressing Enter.
        """
        engine = self.engine
        n = len(trap)
        if (not trap or trap[0] in "-'" or trap[-1] in "-'" or trap in BLACKLISTED_TRAP_PREFIXES
                or not _TRAP_CHARS.match(trap)):
            return None
        if letters_only and ("-" in trap or "'" in trap):
            return None
        if trap not in blocked and engine._is_known_word(trap):
            return None
        wordlist = engine.wordlist
        start = bisect_left(wordlist, trap)
        stop = bisect_right(wordlist, trap + "\uffff")
        solves = []
        for index in range(start, stop):
            word = wordlist[index]
            if len(word) > n and word not in blocked and not (letters_only and word_has_punctuation(word)):
                solves.append(word)
                if len(solves) > TRAP_SCAN:
                    return None  # far too many answers to be a trap
        if not solves:
            return None
        given = self.given.get(trap, 0)
        left = len(solves)
        if given:
            left = min(left, self._total_solves(trap) - given)
            if left <= 0:
                return None
        # Each earlier hand-over of the same prefix consumed one of its answers
        # (even ones we never saw typed) and lowers its priority.
        value = left + GIVEN_WEIGHT * given
        if not self.casual and ("-" in trap or "'" in trap):
            value -= PUNCTUATION_BONUS
        # Appending s/es to the prompt is an answer anyone finds at once.
        easy_plural = any(w in (trap + "s", trap + "es") for w in solves)
        if easy_plural:
            value += EASY_PLURAL_PENALTY
        reach = [len(w) - n for w in solves]
        return (left, value, easy_plural, min(reach), sum(reach) / len(reach))

    def _spam_ranked(self, prefix: str, phase: int, cap: int, hurry: bool, size: int) -> list:
        """Typed endings first, then the same deadly traps casual or pro would play."""
        exact = len(prefix) if 2 <= len(prefix) <= 4 else 0
        suffixes = [s for s in self.engine.hybrid_suffixes
                    if s and s not in BLACKLISTED_TRAP_PREFIXES
                    and s[0] not in "-'" and s[-1] not in "-'"]
        ranked = self._trap_ranked(prefix, phase, cap, hurry, size)
        if not suffixes:
            return ranked
        candidates = [w for w in self.engine.prefix_candidates(prefix)
                      if len(w) - len(prefix) <= cap and len(w) > len(prefix)
                      and not self._hands_blacklisted(w, exact)]
        spam: list[str] = []
        seen: set[str] = set()
        for suffix in suffixes:
            group = sorted((w for w in candidates if w.endswith(suffix)), key=lambda w: (len(w), w))
            for word in group:
                if word not in seen:
                    seen.add(word)
                    spam.append(word)
        traps = dict(self._choice_traps)
        for word in spam:
            traps[word] = next(s for s in suffixes if word.endswith(s))
        merged = spam + [w for w in ranked if w not in seen]
        self._choice_traps = {w: traps[w] for w in merged if w in traps}
        return merged

    def choices(self, prefix: str, limit: int = 3, time_left: Optional[float] = None,
                resolve: bool = True) -> list:
        prefix = self.resolve_prefix(prefix) if resolve else (prefix or "").strip().lower()
        phase = self.prepare(prefix)
        if not prefix:
            return []
        cap = max_suffix_for(time_left, phase)
        hurry = time_left is not None and time_left < 6.0
        key = (prefix, self.mode, self.spam_base, phase, cap, hurry, self.style,
               tuple(sorted(self.engine.used_words)), tuple(sorted(self.engine.rejected_words)),
               id(self.engine.wordlist), self.engine.hybrid_suffixes,
               tuple(sorted(self.given.items())))
        if key == self._choice_cache_key:
            return self._choice_cache[:limit]
        if self.mode == "spam":
            ranked = self._spam_ranked(prefix, phase, cap, hurry, max(12, limit))
        else:
            ranked = self._trap_ranked(prefix, phase, cap, hurry, max(12, limit))
        if not ranked:
            # Nothing fits the clock: the shortest legal answers are the best chance.
            from heapq import nsmallest
            handed = len(prefix) if 2 <= len(prefix) <= 4 else 0
            pool = self.engine.prefix_candidates(prefix)
            pool = [w for w in pool if not self._hands_blacklisted(w, handed)] or pool
            ranked = nsmallest(max(12, limit), pool, key=lambda w: (len(w), w))
            self._choice_traps = {}
        self._choice_cache_key = key
        self._choice_cache = ranked
        return ranked[:limit]

    def _trap_ranked(self, prefix: str, phase: int, cap: int, hurry: bool, size: int) -> list:
        # The next player's prompt is as long as ours, except at a stage change
        # where it gains a letter. Exact-length traps come first; the longer
        # one is a hedge. A single-letter stage can only hedge.
        exact = len(prefix) if 2 <= len(prefix) <= 4 else 0
        hedge = len(prefix) + 1 if len(prefix) + 1 <= 4 else 0
        engine = self.engine
        blocked = frozenset(engine.used_words | engine.rejected_words)
        letters_only = bool(engine.casual_mode and not getattr(engine, "allow_punctuation", False))
        style = self.style or CLASSIC_STYLE
        plain = style is CLASSIC_STYLE
        # The curated lists no longer decide what is a trap. Their order only
        # settles ties between endings the dictionary rates the same.
        orders = {n: self._trap_pool(n) for n in (exact, hedge) if n}
        cancel: Optional[set] = None
        traps: dict[str, str] = {}
        worst = (float("inf"),)
        stats: dict[str, Optional[tuple]] = {}

        def trap_stats(trap: str):
            if trap not in stats:
                stats[trap] = self._trap_stats(trap, blocked, letters_only)
            return stats[trap]

        def ending(word: str, n: int):
            if not n or len(word) <= n:
                return None, None
            trap = word[-n:]
            info = trap_stats(trap)
            if info is None:
                return None, None
            left, value, easy, shortest, mean = info
            if word.startswith(trap):
                # The word itself is one of the trap's answers; it won't be left.
                left -= 1
                value -= 1
                if left <= 0:
                    return None, None
            # Few answers left and long ones: the lower, the deadlier. A hyphen
            # or apostrophe trap ranks ahead of a plain one. Traps inside the
            # same band are equally deadly this game; a favoured trap beats an
            # unfavoured one a band closer. The curated list only prefers a
            # trap when the dictionary rates it the same as another.
            span = (shortest + mean) / 2
            pull = 0.65 + 0.45 * style.weight
            quality = math.log2(max(0.0, value) + 1) - pull * math.log2(1 + span)
            band = math.floor(quality / style.width)
            if not style.favours(trap):
                band += 1
            marked = 0 if ("-" in trap or "'" in trap) else 1
            listed = 0 if trap in orders[n] else 1
            return trap, (marked, band, easy, listed,
                          0.0 if plain else style.hash(trap), trap)

        def word_key(word: str, cheap: bool):
            if hurry:
                return len(word)
            if plain or style.words == "long":
                return -len(word)
            if style.words == "short":
                return len(word)
            if style.words == "mid":
                return abs(len(word) - len(prefix) - style.target)
            return -len(word) if cheap else style.hash("w:" + word)

        def score(word, rank_rest=True):
            nonlocal cancel
            exact_trap, exact_value = ending(word, exact)
            hedge_trap, hedge_value = ending(word, hedge)
            tie = 0.0 if plain else style.hash(word)
            if exact_trap:
                traps[word] = exact_trap
                return (0, exact_value, hedge_value or worst, word_key(word, False), tie, word)
            if hedge_trap:
                traps[word] = hedge_trap
                return (1, hedge_value, worst, word_key(word, False), tie, word)
            size_key = word_key(word, True)
            if not rank_rest:
                return (3, worst, worst, size_key, 0.0, word)
            if cancel is None:
                cancel = set(self.engine.analyze_cancel(prefix).cancel_words) if self.casual else set()
            return (2 if word in cancel else 3, worst, worst, size_key, 0.0, word)

        from heapq import nsmallest
        fitting = [w for w in self.engine.prefix_candidates(prefix) if len(w) - len(prefix) <= cap]
        # A banned hand-over is avoided while anything else fits, never at the
        # cost of the turn: "tg" is only answered by "tgif".
        candidates = [w for w in fitting if not self._hands_blacklisted(w, exact)] or fitting
        # Rate each distinct ending once. Trap endings always outrank the rest,
        # so when enough words end in one, the tens of thousands of others
        # behind a one-letter prompt can't reach the top and are never scored.
        good = {}
        for n in (exact, hedge):
            if n:
                good[n] = {t for t in {w[-n:] for w in candidates if len(w) > n} if trap_stats(t)}
        trapped = [w for w in candidates
                   if any(n and len(w) > n and w[-n:] in good[n] for n in (exact, hedge))]
        strong = [(key, w) for key, w in ((score(w, False), w) for w in trapped) if key[0] < 2]
        if len(strong) >= size:
            ranked = [w for _key, w in nsmallest(size, strong)]
        else:
            ranked = nsmallest(size, candidates, key=score)
        self._choice_traps = {w: traps[w] for w in ranked if w in traps}
        return ranked

    def search(self, prefix: str, limit: int = 3, time_left: Optional[float] = None) -> Optional[dict]:
        """Choices for a prompt typed by hand, as the live turn would rank them.

        The text is used exactly as typed (never mirrored), and the live turn's
        remembered word, trap and prefix are left untouched.
        """
        prefix = re.sub(r"[^a-z'\-]", "", (prefix or "").lower())
        if not prefix:
            return None
        saved = (self.last_prefix, self.last_word, self.last_suffix, self.last_trap)
        try:
            words = self.choices(prefix, limit, time_left, resolve=False)
            if not words and len(prefix) >= 2 and self.engine._is_known_word(prefix) \
                    and self.engine._is_allowed_word(prefix):
                words = [prefix]
            first = words[0] if words else ""
            suffix = first[len(prefix):] if first.startswith(prefix) else ""
            return {"prefix": prefix, "words": list(words), "suffix": suffix,
                    "trap": self._choice_traps.get(first), "phase": self.engine.phase}
        finally:
            self.last_prefix, self.last_word, self.last_suffix, self.last_trap = saved
            self._choice_cache_key = None

    def _can_self_solve(self, prefix: str) -> bool:
        """Whether Enter on the bare prompt is an answer.

        A prompt that is the opponent's whole word ("vp" + "n" handing over
        "vpn" at a stage change) was just played, even if it was never
        confirmed as their word.
        """
        return (len(prefix) >= 2 and self.engine._is_known_word(prefix)
                and self.engine._is_allowed_word(prefix)
                and prefix != self._their_word())

    def _their_word(self) -> str:
        """The word the opponent just typed, used even when never confirmed."""
        return _clean_word(self.opponent_word)

    def choose(self, prefix: str, time_left: Optional[float] = None,
               resolve: bool = True) -> Tuple[str, str, Optional[str], int]:
        prefix = self.resolve_prefix(prefix) if resolve else (prefix or "").strip().lower()
        phase = self.prepare(prefix)
        theirs = self._their_word()
        ranked = [w for w in self.choices(prefix, 12, time_left, resolve=False) if w != theirs]
        # The dictionary contains single-letter entries. The game does not
        # accept a lone supplied tile as a completed self-solve.
        self_solve = self._can_self_solve(prefix)
        top_is_trap = bool(ranked) and ranked[0] in self._choice_traps
        if self_solve and (not ranked or (time_left is not None and time_left < 1.2)
                           or (not top_is_trap and random.random() < 0.25)):
            ranked = [prefix] + ranked
        for word in ranked:
            suffix = word[len(prefix):]
            trap = self._choice_traps.get(word)
            self.last_word, self.last_suffix, self.last_trap = word, suffix, trap
            return word, suffix, trap, phase
        self.last_word, self.last_suffix, self.last_trap = "", "", None
        return "", "", None, phase

    def alternative(self, prefix: str, current: str,
                    time_left: Optional[float] = None,
                    resolve: bool = True) -> Tuple[str, int, str]:
        """The unused answer reachable from ``current`` with the fewest keys.

        Returns (word, backspaces, letters to type). "ismailisms" already used
        becomes "ismailism" by deleting one letter. Among equally short edits
        the better trap wins.
        """
        prefix = self.resolve_prefix(prefix) if resolve else (prefix or "").strip().lower()
        phase = self.prepare(prefix)
        cap = max_suffix_for(time_left, phase)
        ranked = self.choices(prefix, 12, time_left, resolve=False)
        rank = {w: i for i, w in enumerate(ranked)}
        options = [w for w in self.engine.prefix_candidates(prefix) if len(w) - len(prefix) <= cap]
        if self._can_self_solve(prefix):
            options.append(prefix)
        theirs = self._their_word()
        options = [w for w in options if w != current and w != theirs]
        if not options:
            return "", 0, ""

        def key(word):
            deletes, inserts = edit_cost(current, word)
            return (deletes + inserts, rank.get(word, len(rank)), -len(word), word)

        best = min(options, key=key)
        deletes, inserts = edit_cost(current, best)
        self.last_word, self.last_suffix = best, best[len(prefix):]
        self.last_trap = self._choice_traps.get(best)
        return best, deletes, best[len(best) - inserts:]

    def last_resort(self, prefix: str, skip: Iterable[str] = ()) -> str:
        """The shortest unused answer at all, once nothing ranked is left.

        A word refused earlier (often a slow acknowledgement) and a punctuated
        word are both better than letting the clock run out.
        """
        prefix = _clean_word(prefix)
        if not prefix:
            return ""
        engine = self.engine
        skip = set(skip) | {self._their_word()}
        start = bisect_left(engine.wordlist, prefix)
        stop = bisect_right(engine.wordlist, prefix + "\uffff")
        pool = [w for w in engine.wordlist[start:stop]
                if len(w) > len(prefix) and w not in engine.used_words and w not in skip]
        return min(pool, key=lambda w: (len(w), w)) if pool else ""

    def note_given(self, prompt: str) -> None:
        """The opponent's actual starting prompt after our last word."""
        prompt = (prompt or "").lower()
        word = self._given_word
        if not word or len(prompt) < 2 or not word.endswith(prompt) or len(word) <= len(prompt):
            return
        self._given_word = ""
        if prompt == self._given_key:
            return
        if self._given_key and self.given.get(self._given_key):
            self.given[self._given_key] -= 1
        self.given[prompt] = self.given.get(prompt, 0) + 1
        self._given_key = prompt
        self._choice_cache_key = None

    def commit_play(self, word: str, prefix: str = "") -> None:
        word = (word or "").lower()
        if not word:
            return
        self.engine.mark_used(word)
        # Until the opponent's prompt is seen, assume it is as long as ours.
        prefix = prefix or self.last_prefix
        n = len(prefix) if prefix and word.startswith(prefix) else 0
        self._given_word, self._given_key = word, ""
        if 2 <= n < len(word):
            self._given_key = word[-n:]
            self.given[self._given_key] = self.given.get(self._given_key, 0) + 1
        self._choice_cache_key = None
        self.round += 1
