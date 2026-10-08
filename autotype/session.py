from __future__ import annotations

import re
import random
from bisect import bisect_left, bisect_right
from typing import Optional, Tuple

from dyoe2_engine import Dyoe2Engine

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
        self._retry_prompt = self.pending
        self._reject_hits = 0

    def _blank(self) -> dict:
        return {"play": "", "stored": "", "candidates": [], "accepted": False,
                "rejected": False, "board": self.pending, "turn": self.turn,
                "partials": list(self._last_reads), "given": self._recovery_given,
                "ending": ""}

    def _remember(self, board: str) -> None:
        if len(board) < 2 or board == self.typed or board == self._last_accepted:
            return
        if not self._memory or self._memory[-1] != board:
            self._memory.append(board)
            self._memory = self._memory[-32:]
        self._last_reads = list(self._memory)

    @staticmethod
    def _prompt(board: str) -> str:
        return board if re.fullmatch(r"[a-z'-]{1,4}", board) else ""

    def observe(self, board: str, whose: str, *, complete: bool = True,
                tiles: int = 0, now: float | None = None) -> dict:
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
                self._given = prompt if prompt == expected else ""
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
                self._given = prompt
            if not self._given and prompt and not self._memory:
                self._given = prompt
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
            self._hold_board = ""
            # A header change cannot, by itself, turn their final short word
            # into a prefix. The branch above waits for that word to collapse.
            self._recovery_pending = True
            # Attaching mid-turn can make the first short read a finished word,
            # rather than a starting prefix. Keep that reading too.
            self._recovery_given = (self._given if any(len(word) > len(self._given)
                                                      for word in self._memory) else "")
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
        if self._candidate_hits < 2:
            return out
        self._retry_prompt = ""
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


class MatchSession:
    def __init__(self, engine: Dyoe2Engine) -> None:
        self.engine = engine
        self.engine.allow_punctuation = True
        self.round = 1
        self.casual = True
        self.mode = "casual"
        self.spam_suffixes = ""
        self.last_word = ""
        self.last_suffix = ""
        self.last_trap: Optional[str] = None
        self.last_prefix = ""
        # How many times each prefix was handed to an opponent this game.
        self.given: dict[str, int] = {}
        self._given_word = ""
        self._given_key = ""
        self._choice_cache_key = None
        self._choice_cache: list[str] = []
        self._choice_traps: dict[str, str] = {}
        self._total_cache: dict[str, int] = {}
        self.unreadable_words: set[str] = set()
        self.unreadable_prefixes: set[str] = set()

    def set_casual(self, casual: bool) -> None:
        if self.mode == "spam":
            self.engine.set_casual_mode(True)
            return
        self.mode = "casual" if casual else "pro"
        self.casual = casual
        self.engine.set_casual_mode(casual)

    def set_mode(self, mode: str) -> None:

        mode = mode if mode in ("casual", "pro", "spam") else "casual"
        self.mode = mode
        self.casual = mode != "pro"
        self.engine.set_casual_mode(self.casual)
        if mode == "spam":
            self.engine.set_hybrid_suffixes(self.spam_suffixes)
            self.engine.set_phase(5)
        else:
            self.engine.set_phase(phase_for_prompt(self.round, self.last_prefix))

    def set_spam_suffixes(self, raw: str) -> None:
        self.spam_suffixes = raw or ""
        if self.mode == "spam":
            self.engine.set_hybrid_suffixes(self.spam_suffixes)
            if self.engine.phase != 5:
                self.engine.set_phase(5)

    def new_game(self) -> None:
        self.engine.clear_used()
        self.unreadable_words.clear()
        self.unreadable_prefixes.clear()
        for casual in (True, False):
            self.engine.rotate_for_new_game(casual=casual, persist=False, shuffle=True)
        self.round = 1
        self.last_prefix = ""
        self.engine.trap_phases = ()
        if self.mode == "spam":
            self.engine.set_hybrid_suffixes(self.spam_suffixes)
            self.engine.set_phase(5)
        else:
            self.engine.set_phase(1)
        self.last_word = ""
        self.last_suffix = ""
        self.last_trap = None
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
                return ""
            best_options = list(candidates)
            if len(best_options) != 1:
                return ""
            best = best_options[0]
        if best in self.engine.used_words:
            return ""
        self.engine.mark_used(best)
        return best

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
            self.engine.set_casual_mode(True)
            self.engine.set_hybrid_suffixes(self.spam_suffixes)
            if self.engine.phase != 5:
                self.engine.set_phase(5)
            return 5
        phase = phase_for_prompt(self.round, prefix)
        self.engine.set_casual_mode(self.casual)
        self.engine.set_phase(phase)
        self.engine.trap_phases = ()
        return phase

    def resolve_prefix(self, prefix: str) -> str:
        prefix = (prefix or "").strip().lower()
        if self.engine.prefix_candidates(prefix) or self.engine._is_known_word(prefix):
            return prefix
        reverse = prefix[::-1]
        if self.engine.prefix_candidates(reverse) or self.engine._is_known_word(reverse):
            return reverse
        return prefix

    def _total_solves(self, trap: str) -> int:
        """Dictionary answers for a prefix, used or not."""
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

    def _trap_value(self, trap: str, word: str):
        """Sort key for handing ``trap`` over with ``word``; None if useless.

        Fewer solves left is better. Each earlier hand-over of the same prefix
        consumed one of its solves (even ones we never saw typed) and lowers
        its priority. A prefix that is itself an unused word is answered by
        pressing Enter. Long solves are harder to finish in time.
        """
        engine = self.engine
        if trap == word or (engine._is_known_word(trap) and engine._is_allowed_word(trap)):
            return None
        solves = [w for w in engine.prefix_candidates(trap) if w != word]
        given = self.given.get(trap, 0)
        total = self._total_solves(trap) - given - (len(word) > len(trap) and word.startswith(trap))
        left = min(len(solves), total)
        if left <= 0:
            return None
        value = left + GIVEN_WEIGHT * given
        if not self.casual and ("-" in trap or "'" in trap):
            value -= PUNCTUATION_BONUS
        # Appending s/es to the prompt is an answer anyone finds at once.
        easy_plural = any(w in (trap + "s", trap + "es") for w in solves)
        if easy_plural:
            value += EASY_PLURAL_PENALTY
        shortest = min(len(w) for w in solves) - len(trap)
        return (value, easy_plural, -shortest)

    def _spam_ranked(self, prefix: str, cap: int) -> list:
        ranked = self.engine.ranked_words(prefix, limit=256)
        fitting = [w for w in ranked if len(w) - len(prefix) <= cap]
        custom = self.engine.hybrid_suffixes
        fallback = self.engine._hybrid_fallback_traps()
        self._choice_traps = {}
        for word in fitting:
            trap = next((s for s in custom if word.endswith(s)), None)
            self._choice_traps[word] = trap or self.engine._best_ending_trap(word, fallback)
        return fitting

    def choices(self, prefix: str, limit: int = 3, time_left: Optional[float] = None) -> list:
        prefix = self.resolve_prefix(prefix)
        phase = self.prepare(prefix)
        if not prefix:
            return []
        cap = max_suffix_for(time_left, phase)
        hurry = time_left is not None and time_left < 6.0
        key = (prefix, self.mode, phase, cap, hurry,
               tuple(sorted(self.engine.used_words)), tuple(sorted(self.engine.rejected_words)),
               id(self.engine.wordlist), self.engine.hybrid_suffixes,
               tuple(sorted(self.given.items())))
        if key == self._choice_cache_key:
            return self._choice_cache[:limit]
        if self.mode == "spam":
            ranked = self._spam_ranked(prefix, cap)
        else:
            ranked = self._trap_ranked(prefix, phase, cap, hurry, max(12, limit))
        if not ranked:
            # Nothing fits the clock: the shortest answers are the best chance.
            from heapq import nsmallest
            ranked = nsmallest(max(12, limit), self.engine.prefix_candidates(prefix),
                               key=lambda w: (len(w), w))
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
        pools = {n: self._trap_pool(n) for n in (exact, hedge) if n}
        cancel = set(self.engine.analyze_cancel(prefix).cancel_words) if self.casual else set()
        values: dict = {}
        traps: dict[str, str] = {}
        worst = (float("inf"),)

        def trap_value(trap: str, word: str):
            k = (trap, word if word.startswith(trap) else "")
            if k not in values:
                values[k] = self._trap_value(trap, word)
            return values[k]

        def ending(word: str, n: int):
            if not n or len(word) < n:
                return None, None
            trap = word[-n:]
            order = pools[n].get(trap)
            if order is None:
                return None, None
            value = trap_value(trap, word)
            return (trap, (*value, order)) if value is not None else (None, None)

        def score(word):
            size_key = len(word) if hurry else -len(word)
            exact_trap, exact_value = ending(word, exact)
            hedge_trap, hedge_value = ending(word, hedge)
            if exact_trap:
                traps[word] = exact_trap
                return (0, exact_value, hedge_value or worst, size_key, word)
            if hedge_trap:
                traps[word] = hedge_trap
                return (1, hedge_value, worst, size_key, word)
            return (2 if word in cancel else 3, worst, worst, size_key, word)

        from heapq import nsmallest
        candidates = [w for w in self.engine.prefix_candidates(prefix) if len(w) - len(prefix) <= cap]
        ranked = nsmallest(size, candidates, key=score)
        self._choice_traps = {w: traps[w] for w in ranked if w in traps}
        return ranked

    def choose(self, prefix: str, time_left: Optional[float] = None) -> Tuple[str, str, Optional[str], int]:
        prefix = self.resolve_prefix(prefix)
        phase = self.prepare(prefix)
        ranked = self.choices(prefix, 12, time_left)
        # The dictionary contains single-letter entries. The game does not
        # accept a lone supplied tile as a completed self-solve.
        self_solve = (len(prefix) >= 2 and self.engine._is_known_word(prefix)
                      and self.engine._is_allowed_word(prefix))
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
                    time_left: Optional[float] = None) -> Tuple[str, int, str]:
        """The unused answer reachable from ``current`` with the fewest keys.

        Returns (word, backspaces, letters to type). "ismailisms" already used
        becomes "ismailism" by deleting one letter. Among equally short edits
        the better trap wins.
        """
        prefix = self.resolve_prefix(prefix)
        phase = self.prepare(prefix)
        cap = max_suffix_for(time_left, phase)
        ranked = self.choices(prefix, 12, time_left)
        rank = {w: i for i, w in enumerate(ranked)}
        options = [w for w in self.engine.prefix_candidates(prefix) if len(w) - len(prefix) <= cap]
        if len(prefix) >= 2 and self.engine._is_known_word(prefix) and self.engine._is_allowed_word(prefix):
            options.append(prefix)
        options = [w for w in options if w != current]
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
