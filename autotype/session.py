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
        self._allow_easy_plural = False
        self._choice_cache_key = None
        self._choice_cache: list[str] = []
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
        self._allow_easy_plural = False
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
        self.engine.trap_phases = (4, 3, 2) if phase < 4 and len(self.engine.used_words) > 5 else ()
        return phase

    def resolve_prefix(self, prefix: str) -> str:
        prefix = (prefix or "").strip().lower()
        if self.engine.prefix_candidates(prefix) or self.engine._is_known_word(prefix):
            return prefix
        reverse = prefix[::-1]
        if self.engine.prefix_candidates(reverse) or self.engine._is_known_word(reverse):
            return reverse
        return prefix

    def choices(self, prefix: str, limit: int = 3) -> list:
        prefix = self.resolve_prefix(prefix)
        phase = self.prepare(prefix)
        if not prefix:
            return []
        key = (prefix, self.mode, phase, self._allow_easy_plural,
               tuple(sorted(self.engine.used_words)), tuple(sorted(self.engine.rejected_words)),
               id(self.engine.wordlist), self.engine.hybrid_suffixes,
               self.engine.trap_phases)
        if key == self._choice_cache_key:
            return self._choice_cache[:limit]
        candidates = self.engine.prefix_candidates(prefix)
        cancel = set(self.engine.analyze_cancel(prefix).cancel_words)
        phases = self.engine.trap_phases or ((4, 3, 2) if phase == 5 else (phase,))
        traps = {t for p in phases for t in self.engine.get_ordered_traps(p)}
        if self.mode == "spam":
            traps.update(self.engine.hybrid_suffixes)
        lengths = {len(t) for t in traps}
        counts = {}
        self._choice_traps = {}
        def difficulty(t, played):
            key = (t, played if played.startswith(t) else "")
            if key not in counts:
                solves = self.engine.prefix_candidates(t)
                solves = [w for w in solves if w != played]
                # Match the website's easy plural rule: appending s/es to the
                # prompt, rather than any obscure answer that happens to be plural.
                plural = sum(w in (t + "s", t + "es") for w in solves)
                easy = bool(plural) and not self._allow_easy_plural
                counts[key] = (easy, len(solves), plural / max(1, len(solves)))
            return counts[key]
        def score(word):
            endings = [word[-n:] for n in lengths if len(word) >= n
                       for t in (word[-n:],) if t in traps
                       and not (self.engine._is_known_word(t) and t not in self.engine.used_words and t != word)]
            if endings:
                trap = min(endings, key=lambda t: (*difficulty(t, word), t))
                self._choice_traps[word] = trap
                easy, n, plural = difficulty(trap, word)
                return (0, easy, n, plural, -len(word), word)
            return (1 if word in cancel else 2, False, 0, 0, -len(word), word)
        # Only the displayed choices and the current answer are needed. Avoid
        # retaining and sorting every answer for one-letter prompts.
        from heapq import nsmallest
        ranked = nsmallest(max(12, limit), candidates, key=score)
        self._choice_traps = {word: self._choice_traps[word] for word in ranked
                              if word in self._choice_traps}
        self._choice_cache_key = key
        self._choice_cache = ranked
        return ranked[:limit]

    def choose(self, prefix: str) -> Tuple[str, str, Optional[str], int]:
        prefix = self.resolve_prefix(prefix)
        phase = self.prepare(prefix)
        ranked = self.choices(prefix, 12)
        # The dictionary contains single-letter entries. The game does not
        # accept a lone supplied tile as a completed self-solve.
        self_solve = (len(prefix) >= 2 and self.engine._is_known_word(prefix)
                      and self.engine._is_allowed_word(prefix))
        if self_solve and (not ranked or random.random() < 0.25):
            ranked.insert(0, prefix)
        for word in ranked:
            suffix = word[len(prefix):]
            trap = self._choice_traps.get(word)
            self.last_word, self.last_suffix, self.last_trap = word, suffix, trap
            return word, suffix, trap, phase
        self.last_word, self.last_suffix, self.last_trap = "", "", None
        return "", "", None, phase

    def commit_play(self, word: str) -> None:
        word = (word or "").lower()
        if not word:
            return
        match = self.engine.matched_trap_for_word(word)
        self.engine.mark_used(word)
        if match is not None:
            phase, trap = match
            self.engine.deprioritize_trap(phase, trap, persist=False)
        self.round += 1
        # Keep a turn's choices stable across repeated screen refreshes. Easy
        # plural traps are eligible every turn, but get equal priority only
        # occasionally when stronger nontrivial alternatives exist.
        self._allow_easy_plural = random.random() < 0.2
