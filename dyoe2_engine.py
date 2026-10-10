from __future__ import annotations

import json
import re
import heapq
from bisect import bisect_left, bisect_right
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Sequence

REPO_ROOT = Path(__file__).resolve().parent
DEFAULT_LAST_TXT = REPO_ROOT / "dict (7).txt"
DEFAULT_CASUAL_PREFIXES = (
    REPO_ROOT / "lll-security-audit" / "poppi" / "prefix-solve-groups-3-4-prefixes.txt"
)
DEFAULT_TRAPS = REPO_ROOT / "lll-security-audit" / "traps.txt"
DEFAULT_SPECIAL_TRAPS = REPO_ROOT / "lll-security-audit" / "special-traps.txt"
DEFAULT_NO_PLURAL = REPO_ROOT / "lll-security-audit" / "traps-not-in-dyoe-no-plural.txt"
DEFAULT_PRIORITY_PATH = Path.home() / ".last-letter-helper" / "dyoe2_trap_priorities.json"
DEFAULT_CANCELLED_PROMPTS_PATH = (
    Path.home() / ".last-letter-helper" / "dyoe2_cancelled_prompts.json"
)

# Prefixes the game will not accept as a prompt. A word is not played when the
# ending it would hand over (the next prompt) is one of these.
BLACKLISTED_TRAP_PREFIXES = frozenset({
    "bj",
    # A
    "ah", "aj", "ak", "anda", "ande", "ay", "ady",
    # B
    "bd", "baa", "bs", "bsf", "bsh", "bskt",
    # C
    "ct", "cz", "caa", "ck", "cp", "cs", "cg", "cf",
    # D
    "dl", "db", "daa", "dy", "dc", "ddt", "dib", "dj", "dk", "dn", "ds", "dsr", "dt",
    # E
    "ery", "erl", "ek", "edh", "edhs", "eue", "eueu", "ead", "ec", "eb",
    # F
    "fy", "faa", "fj", "ft", "fth", "fthm", "ftn", "ftnc", "ftne",
    # G
    "gn", "gt", "gs", "gp", "gv", "gles", "ght", "gu",
    # H
    "haa", "hox", "hp", "ht", "hs", "hr",
    # I
    "ia", "iap", "ie", "if", "ih", "ij", "ini", "io", "iq", "ip", "irg", "irk",
    "iu", "ive", "iw", "ix", "iz", "ish", "ig", "ishe", "ishes",
    # J
    "jb", "jf", "jg", "jl", "jm", "jn", "jq", "jt", "jx", "jr", "js",
    # K
    "kr", "ks", "kv", "kaa", "kh",
    # L
    "ls", "lf", "laa", "lb", "lc", "ld", "lm", "ln", "lp", "lr", "lt", "lly", "llyn", "ll",
    # Doubled letters the game will not take as a prompt.
    "bb", "cc", "dd", "gg", "hh", "rr", "ss",
    # M
    "mn", "mk", "ml", "mp", "mr", "ms", "mt",
    # N
    "nd", "ng", "nr", "ns", "nt", "naa", "naw", "nb", "nc", "nj", "np", "nv",
    "nda", "nde", "ny",
    # O
    "oj", "oy", "ofa", "ofe", "onk", "oe", "oos", "oot", "oots", "oo",
    # P
    "pt", "paa", "pyv", "pyx", "pq", "pss", "poz", "pox", "psw", "ptg", "pty", "pst",
    "psis", "ptp", "pts", "ptt", "pto", "ps", "pn",
    # Q
    "qn", "qy", "qh",
    # R
    "raa", "rc", "rb", "reaa", "ry", "rl", "rm", "rs", "rn", "rp", "rt", "rd", "rf", "rk",
    # S
    "sr", "saa", "sth", "shes",
    # T
    "tc", "tm", "tst", "tz", "taa", "td", "ty", "tl", "tn", "ts", "tion", "taum",
    # U
    "ubc", "ua", "uay", "uak", "uan", "ubb", "uc", "ud", "ue", "ueu", "ueue",
    "ught", "ugh", "urs",
    # V
    "vaa", "vox", "vr", "vug", "vs",
    # W
    "ws", "waa", "wee", "wf", "wg", "wj", "wk", "wm", "wl", "wpm", "wc", "wy", "wu",
    # X
    "xr", "xc", "xd",
    # Y
    "ym", "yt", "yl", "yn", "yr", "ys", "yq", "yd", "yx",
    # Z
    "zs",
    # Not a prompt at all.
    "-",
})

_SPLIT_SUFFIXES = re.compile(r"[,;\s\[\](){}]+")
# Same spellings the dictionary file keeps: letters, plus an apostrophe or hyphen between letters.
_DICT_WORD = re.compile(r"^[a-z]+(?:['-][a-z]+)*$|^'[a-z]+(?:['-][a-z]+)*$")

def resource_path(*parts: str) -> Path:
    return REPO_ROOT.joinpath(*parts)

def parse_trap_prefix_line(line: str) -> str | None:

    text = line.strip()
    if not text or text.startswith("#"):
        return None
    prefix = text.split("\t", 1)[0].strip().lower()
    return prefix or None

def load_prefixes_from_lines(
    lines: Sequence[str],
    *,
    start_line: int | None = None,
    end_line: int | None = None,
    lengths: set[int] | None = None,
) -> list[str]:

    out: list[str] = []
    seen: set[str] = set()
    for idx, raw in enumerate(lines, start=1):
        if start_line is not None and idx < start_line:
            continue
        if end_line is not None and idx > end_line:
            break
        prefix = parse_trap_prefix_line(raw)
        if prefix is None:
            continue
        if lengths is not None and len(prefix) not in lengths:
            continue
        if prefix in seen:
            continue
        seen.add(prefix)
        out.append(prefix)
    return out

def load_prefixes_from_file(
    path: Path | str,
    *,
    start_line: int | None = None,
    end_line: int | None = None,
    lengths: set[int] | None = None,
) -> list[str]:
    text = Path(path).read_text(encoding="utf-8", errors="replace").splitlines()
    return load_prefixes_from_lines(
        text, start_line=start_line, end_line=end_line, lengths=lengths
    )

def merge_prefix_tiers(*tiers: Iterable[str]) -> list[str]:

    out: list[str] = []
    seen: set[str] = set()
    for tier in tiers:
        for prefix in tier:
            key = prefix.lower()
            if key in seen:
                continue
            seen.add(key)
            out.append(key)
    return out

def normalize_hybrid_suffixes(raw: str) -> tuple[str, ...]:
    parts = [p.strip().lower() for p in _SPLIT_SUFFIXES.split(raw) if p.strip()]
    out: list[str] = []
    seen: set[str] = set()
    for part in parts:
        if part in seen:
            continue
        seen.add(part)
        out.append(part)
    return tuple(out)

def word_has_punctuation(word: str) -> bool:
    return "-" in word or "'" in word

@dataclass(frozen=True)
class CancelAnalysis:

    prompt: str
    groups: dict[str, tuple[str, ...]]
    kept_keys: tuple[str, ...]
    cancel_words: tuple[str, ...]
    kept_words: tuple[str, ...]

    @property
    def group_counts(self) -> list[tuple[str, int]]:
        return sorted(
            ((key, len(words)) for key, words in self.groups.items()),
            key=lambda item: (-item[1], item[0]),
        )

def group_words_by_next_letter(
    prompt: str, words: Iterable[str]
) -> dict[str, list[str]]:

    lower = prompt.strip().lower()
    groups: dict[str, list[str]] = defaultdict(list)
    for raw in words:
        word = raw.strip().lower()
        if not word.startswith(lower):
            continue
        if word == lower:
            groups[""].append(word)
            continue
        groups[word[len(lower)]].append(word)
    return {key: sorted(values) for key, values in groups.items()}

def analyze_cancel(prompt: str, words: Iterable[str]) -> CancelAnalysis:

    lower = prompt.strip().lower()
    groups = group_words_by_next_letter(lower, words)
    ordered = sorted(groups.items(), key=lambda item: (-len(item[1]), item[0]))
    kept_keys = tuple(key for key, _ in ordered[:2])
    kept_set = set(kept_keys)
    cancel_words: list[str] = []
    kept_words: list[str] = []
    for key in sorted(groups):
        bucket = groups[key]
        if key in kept_set:
            kept_words.extend(bucket)
        else:
            cancel_words.extend(bucket)
    return CancelAnalysis(
        prompt=lower,
        groups={key: tuple(values) for key, values in groups.items()},
        kept_keys=kept_keys,
        cancel_words=tuple(cancel_words),
        kept_words=tuple(kept_words),
    )

@dataclass
class TrapPools:
    casual_2: list[str] = field(default_factory=list)
    casual_3: list[str] = field(default_factory=list)
    casual_4: list[str] = field(default_factory=list)
    pro_2: list[str] = field(default_factory=list)
    pro_3: list[str] = field(default_factory=list)
    pro_4: list[str] = field(default_factory=list)

    source_tiers: dict[str, list[list[str]]] = field(default_factory=dict)

def disjoint_prefix_tiers(*tiers: Iterable[str]) -> list[list[str]]:

    result: list[list[str]] = []
    seen: set[str] = set()
    for tier in tiers:
        current: list[str] = []
        for prefix in tier:
            key = prefix.lower()
            if key in seen:
                continue
            seen.add(key)
            current.append(key)
        result.append(current)
    return result

def build_trap_pools(
    *,
    casual_path: Path | str = DEFAULT_CASUAL_PREFIXES,
    traps_path: Path | str = DEFAULT_TRAPS,
    special_path: Path | str = DEFAULT_SPECIAL_TRAPS,
    no_plural_path: Path | str = DEFAULT_NO_PLURAL,
    giveable: set[str] | None = None,
) -> TrapPools:
    casual_all = load_prefixes_from_file(casual_path)
    casual_2 = [p for p in casual_all if len(p) == 2]
    casual_3 = [p for p in casual_all if len(p) == 3]
    casual_4 = [p for p in casual_all if len(p) == 4]

    pro_2_source = load_prefixes_from_file(traps_path, start_line=9, end_line=56)

    special_p3 = merge_prefix_tiers(
        load_prefixes_from_file(special_path, start_line=11, end_line=23),
        load_prefixes_from_file(special_path, start_line=25, end_line=30),
    )
    no_plural_p3 = load_prefixes_from_file(no_plural_path, start_line=14, end_line=141)
    traps_p3 = load_prefixes_from_file(traps_path, start_line=57, end_line=711)
    pro_3_tiers = disjoint_prefix_tiers(special_p3, no_plural_p3, traps_p3)
    pro_3 = merge_prefix_tiers(*pro_3_tiers)

    special_p4 = load_prefixes_from_file(special_path, start_line=31, end_line=59)
    no_plural_p4 = load_prefixes_from_file(no_plural_path, start_line=142, end_line=750)
    traps_p4 = load_prefixes_from_file(traps_path, start_line=712, end_line=4440)
    pro_4_tiers = disjoint_prefix_tiers(special_p4, no_plural_p4, traps_p4)
    pro_4 = merge_prefix_tiers(*pro_4_tiers)

    source_tiers = {
        "casual:2": [list(casual_2)],
        "casual:3": [list(casual_3)],
        "casual:4": [list(casual_4)],
        "pro:2": [list(pro_2_source)],
        "pro:3": pro_3_tiers,
        "pro:4": pro_4_tiers,
    }

    pools = TrapPools(
        casual_2=casual_2,
        casual_3=casual_3,
        casual_4=casual_4,
        pro_2=pro_2_source,
        pro_3=pro_3,
        pro_4=pro_4,
        source_tiers=source_tiers,
    )
    pools = filter_blacklisted_pools(pools)
    if giveable is not None:
        pools = filter_giveable_pools(pools, giveable)
    return pools

def filter_blacklisted_pools(pools: TrapPools) -> TrapPools:
    def keep(items: list[str]) -> list[str]:
        return [p for p in items if p not in BLACKLISTED_TRAP_PREFIXES]

    source_tiers = {
        key: [keep(tier) for tier in tiers]
        for key, tiers in pools.source_tiers.items()
    }
    return TrapPools(
        casual_2=keep(pools.casual_2),
        casual_3=keep(pools.casual_3),
        casual_4=keep(pools.casual_4),
        pro_2=keep(pools.pro_2),
        pro_3=keep(pools.pro_3),
        pro_4=keep(pools.pro_4),
        source_tiers=source_tiers,
    )

def filter_giveable_pools(pools: TrapPools, giveable: set[str]) -> TrapPools:
    def keep(items: list[str]) -> list[str]:
        return [
            p
            for p in items
            if p in giveable and p not in BLACKLISTED_TRAP_PREFIXES
        ]

    source_tiers = {
        key: [keep(tier) for tier in tiers]
        for key, tiers in pools.source_tiers.items()
    }
    return TrapPools(
        casual_2=keep(pools.casual_2),
        casual_3=keep(pools.casual_3),
        casual_4=keep(pools.casual_4),
        pro_2=keep(pools.pro_2),
        pro_3=keep(pools.pro_3),
        pro_4=keep(pools.pro_4),
        source_tiers=source_tiers,
    )

def build_giveable_suffix_set(words: Sequence[str], suffixes: Iterable[str]) -> set[str]:

    wanted = {s.lower() for s in suffixes}
    if not wanted:
        return set()

    by_len: dict[int, set[str]] = {}
    for s in wanted:
        by_len.setdefault(len(s), set()).add(s)
    found: set[str] = set()
    remaining = set(wanted)
    for word in words:
        lower = word.lower()
        for length, group in by_len.items():
            if len(lower) < length:
                continue
            tail = lower[-length:]
            if tail in group and tail in remaining:
                found.add(tail)
                remaining.discard(tail)
        if not remaining:
            break
    return found

def build_giveable_via_reversed(
    words: Sequence[str], suffixes: Iterable[str]
) -> set[str]:

    reversed_words = sorted(w[::-1] for w in words)
    giveable: set[str] = set()
    for suffix in suffixes:
        key = suffix.lower()
        rev = key[::-1]
        start = bisect_left(reversed_words, rev)
        if start < len(reversed_words) and reversed_words[start].startswith(rev):

            giveable.add(key)
    return giveable

@dataclass
class RankedWord:
    word: str
    trap_rank: int
    trap_suffix: str | None = None

class Dyoe2Engine:

    NO_TRAP_RANK = 10_000_000

    def __init__(
        self,
        words: Sequence[str] | None = None,
        traps: TrapPools | None = None,
        *,
        validate_giveable: bool = True,
    ) -> None:
        self.wordlist: list[str] = []
        self.reversed_words: list[str] = []
        self.traps = traps or TrapPools()
        self.used_words: set[str] = set()
        self.rejected_words: set[str] = set()
        self.casual_mode = True
        self.phase = 1
        self.trap_phases: tuple[int, ...] = ()
        self.hybrid_suffixes: tuple[str, ...] = ()

        self.priority_orders: dict[str, list[str]] = {}
        self.priority_path = DEFAULT_PRIORITY_PATH
        self.cancelled_prompts: set[str] = set()
        self.cancelled_prompts_path = DEFAULT_CANCELLED_PROMPTS_PATH
        self.last_decayed_trap: str | None = None
        self.last_decayed_phase: int | None = None
        self._queue: list[str] = []
        self._ranked_cache_key: tuple | None = None
        self._ranked_cache: list[str] = []
        self._loaded = False
        self.load_priority_orders()
        self.load_cancelled_prompts()
        if words is not None:
            self.set_words(words, traps=traps, validate_giveable=validate_giveable)

    @property
    def ready(self) -> bool:
        return self._loaded and bool(self.wordlist)

    def set_words(
        self,
        words: Iterable[str],
        traps: TrapPools | None = None,
        *,
        validate_giveable: bool = True,
    ) -> None:
        cleaned = sorted({w.strip().lower() for w in words if w and w.strip()})
        self.wordlist = cleaned
        self.reversed_words = sorted(w[::-1] for w in cleaned)
        raw_traps = traps or self.traps
        if validate_giveable:
            all_suffixes = merge_prefix_tiers(
                raw_traps.casual_2,
                raw_traps.casual_3,
                raw_traps.casual_4,
                raw_traps.pro_2,
                raw_traps.pro_3,
                raw_traps.pro_4,
            )
            giveable = build_giveable_via_reversed(cleaned, all_suffixes)
            self.traps = filter_giveable_pools(raw_traps, giveable)
        else:
            self.traps = filter_blacklisted_pools(raw_traps)
        self._loaded = True
        self.clear_cache()

    def load_from_paths(
        self,
        last_txt: Path | str = DEFAULT_LAST_TXT,
        *,
        casual_path: Path | str = DEFAULT_CASUAL_PREFIXES,
        traps_path: Path | str = DEFAULT_TRAPS,
        special_path: Path | str = DEFAULT_SPECIAL_TRAPS,
        no_plural_path: Path | str = DEFAULT_NO_PLURAL,
        validate_giveable: bool = True,
    ) -> int:
        path = Path(last_txt)
        pools = build_trap_pools(
            casual_path=casual_path,
            traps_path=traps_path,
            special_path=special_path,
            no_plural_path=no_plural_path,
            giveable=None,
        )
        with path.open(encoding="utf-8", errors="replace") as stream:
            self.set_words(stream, traps=pools, validate_giveable=validate_giveable)
        return len(self.wordlist)

    def add_known_words(self, raw_words: Iterable[str]) -> dict[str, list[str]]:
        """Insert spellings into the live lists. Nothing is written to disk here."""
        added: list[str] = []
        already: list[str] = []
        rejected: list[str] = []
        seen: set[str] = set()
        for raw in raw_words:
            word = (raw or "").strip().lower()
            if not word or word in seen:
                continue
            seen.add(word)
            if _DICT_WORD.fullmatch(word) is None:
                rejected.append(word)
                continue
            if self._is_known_word(word):
                already.append(word)
                continue
            index = bisect_left(self.wordlist, word)
            self.wordlist.insert(index, word)
            rev = word[::-1]
            rev_index = bisect_left(self.reversed_words, rev)
            self.reversed_words.insert(rev_index, rev)
            added.append(word)
        if added:
            self._loaded = True
            self.clear_cache()
        return {"added": added, "already": already, "rejected": rejected}

    def forget_known_words(self, words: Iterable[str]) -> None:
        changed = False
        for raw in words:
            word = (raw or "").strip().lower()
            if not word:
                continue
            index = bisect_left(self.wordlist, word)
            if index < len(self.wordlist) and self.wordlist[index] == word:
                del self.wordlist[index]
                changed = True
            rev = word[::-1]
            rev_index = bisect_left(self.reversed_words, rev)
            if rev_index < len(self.reversed_words) and self.reversed_words[rev_index] == rev:
                del self.reversed_words[rev_index]
                changed = True
        if changed:
            self.clear_cache()

    def clear_cache(self) -> None:
        self._ranked_cache_key = None
        self._ranked_cache = []
        self._queue = []

    def set_casual_mode(self, casual: bool) -> None:
        if self.casual_mode != casual:
            self.casual_mode = casual
            self.clear_cache()

    def set_phase(self, phase: int) -> None:
        if phase not in {1, 2, 3, 4, 5}:
            raise ValueError(f"invalid phase: {phase}")
        if self.phase != phase:
            self.phase = phase
            self.clear_cache()

    def set_hybrid_suffixes(self, raw: str | Sequence[str]) -> None:
        if isinstance(raw, str):
            suffixes = normalize_hybrid_suffixes(raw)
        else:
            suffixes = normalize_hybrid_suffixes(" ".join(raw))
        if suffixes != self.hybrid_suffixes:
            self.hybrid_suffixes = suffixes
            self.clear_cache()

    def mark_used(self, word: str) -> None:
        self.used_words.add(word.lower())
        self._ranked_cache_key = None
        self._ranked_cache = []

    def clear_used(self) -> None:
        self.used_words.clear()
        self.rejected_words.clear()
        self.clear_cache()

    def mark_rejected(self, word: str) -> None:
        self.rejected_words.add(word.lower())
        self.clear_cache()

    def _is_allowed_word(self, word: str) -> bool:
        if word in self.used_words or word in self.rejected_words:
            return False
        if self.casual_mode and not getattr(self, "allow_punctuation", False) and word_has_punctuation(word):
            return False
        return True

    def _is_known_word(self, word: str) -> bool:
        if not word:
            return False
        idx = bisect_left(self.wordlist, word)
        return idx < len(self.wordlist) and self.wordlist[idx] == word

    def prefix_has_play(self, prompt: str) -> bool:
        """True when the prompt is a word or some allowed word continues it.

        Stops at the first hit so a prompt check does not build the whole group.
        """
        lower = (prompt or "").strip().lower()
        if not lower:
            return False
        if self._is_known_word(lower):
            return True
        start = bisect_left(self.wordlist, lower)
        end = bisect_right(self.wordlist, lower + "\uffff")
        for word in self.wordlist[start:end]:
            if len(word) > len(lower) and self._is_allowed_word(word):
                return True
        return False

    def prefix_candidates(self, prompt: str) -> list[str]:
        lower = prompt.strip().lower()
        if not lower:
            return []
        start = bisect_left(self.wordlist, lower)
        end = bisect_right(self.wordlist, lower + "\uffff")
        # Same test as _is_allowed_word, inlined: a one-letter prompt scans
        # tens of thousands of words on the turn's critical path.
        size = len(lower)
        blocked = self.used_words | self.rejected_words
        letters_only = self.casual_mode and not getattr(self, "allow_punctuation", False)
        return [
            word
            for word in self.wordlist[start:end]
            if len(word) > size and word not in blocked
            and not (letters_only and word_has_punctuation(word))
        ]

    @staticmethod
    def priority_key(casual: bool, phase: int) -> str:
        return f"{'casual' if casual else 'pro'}:{phase}"

    def load_priority_orders(self, path: Path | str | None = None) -> None:
        target = Path(path) if path is not None else self.priority_path
        self.priority_orders = {}
        if not target.is_file():
            return
        try:
            raw = json.loads(target.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return
        if not isinstance(raw, dict):
            return
        cleaned: dict[str, list[str]] = {}
        for key, value in raw.items():
            if not isinstance(key, str) or not isinstance(value, list):
                continue
            ordered = []
            seen: set[str] = set()
            for item in value:
                if not isinstance(item, str):
                    continue
                prefix = item.strip().lower()
                if (
                    not prefix
                    or prefix in seen
                    or prefix in BLACKLISTED_TRAP_PREFIXES
                ):
                    continue
                seen.add(prefix)
                ordered.append(prefix)
            cleaned[key] = ordered
        self.priority_orders = cleaned

    def save_priority_orders(self, path: Path | str | None = None) -> None:
        target = Path(path) if path is not None else self.priority_path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(
            json.dumps(self.priority_orders, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )

    def load_cancelled_prompts(self, path: Path | str | None = None) -> None:
        target = Path(path) if path is not None else self.cancelled_prompts_path
        self.cancelled_prompts = set()
        if not target.is_file():
            return
        try:
            raw = json.loads(target.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return
        items: Iterable[str]
        if isinstance(raw, dict):
            maybe = raw.get("prompts", [])
            items = maybe if isinstance(maybe, list) else []
        elif isinstance(raw, list):
            items = raw
        else:
            return
        cleaned: set[str] = set()
        for item in items:
            if not isinstance(item, str):
                continue
            prompt = item.strip().lower()
            if prompt:
                cleaned.add(prompt)
        self.cancelled_prompts = cleaned

    def save_cancelled_prompts(self, path: Path | str | None = None) -> None:
        target = Path(path) if path is not None else self.cancelled_prompts_path
        target.parent.mkdir(parents=True, exist_ok=True)
        payload = {"prompts": sorted(self.cancelled_prompts)}
        target.write_text(
            json.dumps(payload, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )

    def is_prompt_cancelled(self, prompt: str) -> bool:
        key = prompt.strip().lower()
        return bool(key) and key in self.cancelled_prompts

    def set_prompt_cancelled(
        self, prompt: str, cancelled: bool, *, persist: bool = True
    ) -> bool:
        key = prompt.strip().lower()
        if not key:
            return False
        before = key in self.cancelled_prompts
        if cancelled:
            self.cancelled_prompts.add(key)
        else:
            self.cancelled_prompts.discard(key)
        changed = before != (key in self.cancelled_prompts)
        if changed:
            self.clear_cache()
            if persist:
                self.save_cancelled_prompts()
        return key in self.cancelled_prompts

    def toggle_prompt_cancelled(self, prompt: str, *, persist: bool = True) -> bool:
        return self.set_prompt_cancelled(
            prompt,
            not self.is_prompt_cancelled(prompt),
            persist=persist,
        )

    def cancel_source_words(self, prompt: str) -> list[str]:

        lower = prompt.strip().lower()
        if not lower:
            return []
        start = bisect_left(self.wordlist, lower)
        end = bisect_right(self.wordlist, lower + "\uffff")
        return [
            word
            for word in self.wordlist[start:end]
            if word.startswith(lower) and not word_has_punctuation(word)
        ]

    def analyze_cancel(self, prompt: str) -> CancelAnalysis:
        return analyze_cancel(prompt, self.cancel_source_words(prompt))

    def default_trap_list(self, phase: int, *, casual: bool | None = None) -> list[str]:
        use_casual = self.casual_mode if casual is None else casual
        if use_casual:
            if phase == 2:
                return list(self.traps.casual_2)
            if phase == 3:
                return list(self.traps.casual_3)
            if phase == 4:
                return list(self.traps.casual_4)
            return []
        if phase == 2:
            return list(self.traps.pro_2)
        if phase == 3:
            return list(self.traps.pro_3)
        if phase == 4:
            return list(self.traps.pro_4)
        return []

    def default_trap_tiers(
        self, phase: int, *, casual: bool | None = None
    ) -> list[list[str]]:

        use_casual = self.casual_mode if casual is None else casual
        key = self.priority_key(use_casual, phase)
        tiers = self.traps.source_tiers.get(key)
        if tiers:
            return [list(tier) for tier in tiers if tier]
        base = self.default_trap_list(phase, casual=use_casual)
        return [base] if base else []

    def trap_tier_labels(
        self, phase: int, *, casual: bool | None = None
    ) -> list[str]:
        use_casual = self.casual_mode if casual is None else casual
        tiers = self.default_trap_tiers(phase, casual=use_casual)
        if use_casual:
            return ["CASUAL PREFIXES"] * len(tiers)
        if phase == 2:
            return ["TRAPS.TXT"] * len(tiers)
        standard = ["SPECIAL (- / ')", "NO-DYOE", "TRAPS.TXT"]
        return standard[: len(tiers)]

    def apply_priority_order(
        self,
        base: Sequence[str],
        override: Sequence[str] | None,
    ) -> list[str]:
        base_list = [
            p for p in base if p not in BLACKLISTED_TRAP_PREFIXES
        ]
        if not override:
            return base_list
        base_set = set(base_list)
        ordered: list[str] = []
        seen: set[str] = set()
        for prefix in override:
            key = prefix.lower()
            if (
                key not in base_set
                or key in seen
                or key in BLACKLISTED_TRAP_PREFIXES
            ):
                continue
            seen.add(key)
            ordered.append(key)
        ordered.extend(p for p in base_list if p not in seen)
        return ordered

    def get_ordered_traps(self, phase: int, *, casual: bool | None = None) -> list[str]:
        return [
            prefix
            for tier in self.get_ordered_trap_tiers(phase, casual=casual)
            for prefix in tier
        ]

    def get_ordered_trap_tiers(
        self, phase: int, *, casual: bool | None = None
    ) -> list[list[str]]:
        use_casual = self.casual_mode if casual is None else casual
        key = self.priority_key(use_casual, phase)
        override = self.priority_orders.get(key)
        return [
            self.apply_priority_order(tier, override)
            for tier in self.default_trap_tiers(phase, casual=use_casual)
        ]

    def set_priority_order(
        self,
        phase: int,
        order: Sequence[str],
        *,
        casual: bool | None = None,
        persist: bool = True,
    ) -> list[str]:
        use_casual = self.casual_mode if casual is None else casual
        key = self.priority_key(use_casual, phase)

        tiers = [
            self.apply_priority_order(tier, order)
            for tier in self.default_trap_tiers(phase, casual=use_casual)
        ]
        applied = [prefix for tier in tiers for prefix in tier]
        self.priority_orders[key] = list(applied)
        if persist:
            self.save_priority_orders()
        self.clear_cache()
        return applied

    def set_priority_tier_order(
        self,
        phase: int,
        tier_index: int,
        order: Sequence[str],
        *,
        casual: bool | None = None,
        persist: bool = True,
    ) -> list[str]:

        use_casual = self.casual_mode if casual is None else casual
        tiers = self.get_ordered_trap_tiers(phase, casual=use_casual)
        if not (0 <= tier_index < len(tiers)):
            return self.get_ordered_traps(phase, casual=use_casual)
        tiers[tier_index] = self.apply_priority_order(tiers[tier_index], order)
        flattened = [prefix for tier in tiers for prefix in tier]
        self.priority_orders[self.priority_key(use_casual, phase)] = flattened
        if persist:
            self.save_priority_orders()
        self.clear_cache()
        return flattened

    def reset_priority_order(
        self,
        phase: int,
        *,
        casual: bool | None = None,
        persist: bool = True,
    ) -> list[str]:
        use_casual = self.casual_mode if casual is None else casual
        key = self.priority_key(use_casual, phase)
        self.priority_orders.pop(key, None)
        if persist:
            self.save_priority_orders()
        self.clear_cache()
        return self.default_trap_list(phase, casual=use_casual)

    def rotate_for_new_game(
        self, *, casual: bool | None = None, persist: bool = True, shuffle: bool = False
    ) -> None:

        use_casual = self.casual_mode if casual is None else casual
        for phase in (2, 3, 4):
            tiers = self.get_ordered_trap_tiers(phase, casual=use_casual)
            rotated: list[list[str]] = []
            for tier in tiers:
                if len(tier) > 1:
                    if shuffle:
                        import random
                        shuffled = list(tier)
                        random.SystemRandom().shuffle(shuffled)
                        if shuffled[0] == tier[0]:
                            offset = random.SystemRandom().randrange(1, len(shuffled))
                            shuffled[0], shuffled[offset] = shuffled[offset], shuffled[0]
                        rotated.append(shuffled)
                    else:
                        rotated.append(tier[1:] + tier[:1])
                else:
                    rotated.append(tier)
            self.priority_orders[self.priority_key(use_casual, phase)] = [
                prefix for tier in rotated for prefix in tier
            ]

        if persist:
            self.save_priority_orders()
        self.clear_cache()

    def _trap_list_for_phase(self, phase: int) -> list[str]:
        return self.get_ordered_traps(phase)

    def _hybrid_fallback_traps(self) -> list[str]:

        return merge_prefix_tiers(
            self._trap_list_for_phase(4),
            self._trap_list_for_phase(3),
            self._trap_list_for_phase(2),
        )

    def _words_ending_with(self, suffix: str) -> list[str]:

        if not suffix:
            return []
        rev = suffix[::-1]
        start = bisect_left(self.reversed_words, rev)
        end = bisect_right(self.reversed_words, rev + "\uffff")
        return [self.reversed_words[i][::-1] for i in range(start, end)]

    def _matching_trap_words(
        self,
        prompt: str,
        trap: str,
        *,
        seen: set[str],
        shortest_first: bool = False,
    ) -> list[str]:

        lower = prompt.strip().lower()

        if (
            not shortest_first
            and self._is_known_word(trap)
            and trap not in self.used_words
            and self._is_allowed_word(trap)
        ):
            if trap in seen:
                return []
            if lower and not trap.startswith(lower):
                return []
            if lower and len(trap) <= len(lower):
                return []
            return [trap]

        matches: list[str] = []
        for word in self._words_ending_with(trap):
            if lower and not word.startswith(lower):
                continue
            if lower and len(word) <= len(lower):
                continue
            if word in seen:
                continue
            if not self._is_allowed_word(word):
                continue
            matches.append(word)

        if shortest_first:
            matches.sort(key=lambda w: (len(w), w))
        else:
            matches.sort(key=lambda w: (-len(w), w))
        return matches

    def _score_word(
        self,
        word: str,
        trap_rank: dict[str, int],
        lengths: Sequence[int],
    ) -> RankedWord:
        best_rank = self.NO_TRAP_RANK
        best_suffix: str | None = None
        for length in lengths:
            if len(word) < length:
                continue
            suffix = word[-length:]
            rank = trap_rank.get(suffix)
            if rank is None:
                continue
            if rank < best_rank or (
                rank == best_rank
                and (best_suffix is None or length > len(best_suffix))
            ):
                best_rank = rank
                best_suffix = suffix
        return RankedWord(word=word, trap_rank=best_rank, trap_suffix=best_suffix)

    def _rank_candidates(
        self,
        candidates: list[str],
        trap_suffixes: Sequence[str],
        *,
        limit: int | None = None,
    ) -> list[str]:

        if not candidates:
            return []
        if not trap_suffixes:
            ranked = sorted(candidates, key=lambda w: (-len(w), w))
            return ranked if limit is None else ranked[:limit]

        trap_rank = {suffix: idx for idx, suffix in enumerate(trap_suffixes)}
        lengths = sorted({len(s) for s in trap_rank}, reverse=True)
        scored = [self._score_word(word, trap_rank, lengths) for word in candidates]
        scored.sort(key=lambda item: (item.trap_rank, -len(item.word), item.word))
        out = [item.word for item in scored]
        return out if limit is None else out[:limit]

    def _rank_by_trap_walk(
        self,
        prompt: str,
        trap_suffixes: Sequence[str],
        *,
        candidate_set: set[str] | None = None,
        limit: int = 64,
        then_traps: Sequence[str] | None = None,
        primary_shortest_first: bool = False,
    ) -> list[str]:

        lower = prompt.strip().lower()
        out: list[str] = []
        seen: set[str] = set()

        def consume(
            suffixes: Sequence[str], *, shortest_first: bool = False
        ) -> None:
            for trap in suffixes:
                if not trap:
                    continue
                for word in self._matching_trap_words(
                    lower, trap, seen=seen, shortest_first=shortest_first
                ):
                    if candidate_set is not None and word not in candidate_set:
                        continue
                    out.append(word)
                    seen.add(word)
                    if len(out) >= limit:
                        return

        consume(trap_suffixes, shortest_first=primary_shortest_first)
        if len(out) < limit and then_traps:
            consume(then_traps, shortest_first=False)

        if len(out) >= limit:
            return out

        fallback = self.prefix_candidates(lower)
        fallback.sort(key=lambda w: (-len(w), w))
        for word in fallback:
            if word in seen:
                continue
            out.append(word)
            seen.add(word)
            if len(out) >= limit:
                break
        return out

    def _cache_key(self, prompt: str) -> tuple:
        lower = prompt.strip().lower()
        return (
            lower,
            self.casual_mode,
            self.phase,
            self.hybrid_suffixes,
            self.trap_phases,
            frozenset(self.used_words),
            frozenset(self.rejected_words),
            lower in self.cancelled_prompts,
        )

    def ranked_words(self, prompt: str, *, limit: int | None = None) -> list[str]:

        pool_limit = 256 if limit is None else max(limit, 256)
        key = (self._cache_key(prompt), pool_limit if self.phase == 1 and limit is not None else None)
        if self._ranked_cache_key == key and self._ranked_cache:
            ranked = self._ranked_cache
        else:
            if self.trap_phases and self.phase != 5:
                traps = merge_prefix_tiers(*(self._trap_list_for_phase(p) for p in self.trap_phases))
                ranked = self._rank_by_trap_walk(prompt, traps, limit=pool_limit)
            elif self.phase == 1:
                candidates = self.prefix_candidates(prompt)
                order = lambda w: (-len(w), w)
                ranked = (heapq.nsmallest(pool_limit, candidates, key=order)
                          if limit is not None and not (self.casual_mode and self.is_prompt_cancelled(prompt))
                          else sorted(candidates, key=order))
            elif self.phase == 5:
                custom = list(self.hybrid_suffixes)
                fallback = self._hybrid_fallback_traps()

                ranked = self._rank_by_trap_walk(
                    prompt,
                    custom,
                    limit=pool_limit,
                    then_traps=fallback,
                    primary_shortest_first=True,
                )
            else:
                traps = self._trap_list_for_phase(self.phase)
                if traps:
                    ranked = self._rank_by_trap_walk(prompt, traps, limit=pool_limit)
                else:
                    candidates = self.prefix_candidates(prompt)
                    ranked = sorted(candidates, key=lambda w: (-len(w), w))

            if self.casual_mode and self.is_prompt_cancelled(prompt):
                ranked = self._apply_cancel_priority(prompt, ranked)

            self._ranked_cache_key = key
            self._ranked_cache = ranked

        if limit is None:
            return list(ranked)
        return ranked[:limit]

    def _apply_cancel_priority(self, prompt: str, ranked: Sequence[str]) -> list[str]:
        analysis = self.analyze_cancel(prompt)
        cancel_first = [
            word for word in analysis.cancel_words if self._is_allowed_word(word)
        ]
        if not cancel_first:
            return list(ranked)
        seen = set(cancel_first)
        rest = [word for word in ranked if word not in seen]

        return cancel_first + rest

    def ensure_queue(self, prompt: str, *, size: int = 3) -> list[str]:

        ranked = self.ranked_words(prompt)

        if self._queue:
            kept = [w for w in self._queue if w not in self.used_words and w in set(ranked)]
            if kept and kept[0] in ranked:

                seen = set(kept)
                merged = list(kept)
                for word in ranked:
                    if word not in seen:
                        merged.append(word)
                        seen.add(word)
                    if len(merged) >= size:
                        break
                self._queue = merged[:size]

                if len(self._queue) < size:
                    for word in ranked:
                        if word not in self._queue:
                            self._queue.append(word)
                        if len(self._queue) >= size:
                            break
                return list(self._queue)

        self._queue = ranked[:size]
        return list(self._queue)

    def reset_queue_from_rank(self, prompt: str, *, size: int = 3) -> list[str]:

        ranked = self.ranked_words(prompt)
        self._queue = ranked[:size]
        return list(self._queue)

    def get_display_words(self, prompt: str) -> tuple[str | None, str | None, str | None]:
        queue = self.ensure_queue(prompt, size=3)
        front = queue[0] if len(queue) > 0 else None
        side_top = queue[1] if len(queue) > 1 else None
        side_bottom = queue[2] if len(queue) > 2 else None
        return front, side_top, side_bottom

    def promote_side(self, prompt: str, which: str) -> tuple[str | None, str | None, str | None]:

        self.ensure_queue(prompt, size=3)
        if len(self._queue) < 2:
            return self.get_display_words(prompt)
        if which == "top" and len(self._queue) >= 2:
            self._queue[0], self._queue[1] = self._queue[1], self._queue[0]
        elif which == "bottom" and len(self._queue) >= 3:
            self._queue[0], self._queue[2] = self._queue[2], self._queue[0]
        return self.get_display_words(prompt)

    def matched_trap_for_word(self, word: str) -> tuple[int, str] | None:

        lower = word.lower().strip()
        if not lower:
            return None

        if self.phase == 5:
            for suffix in self.hybrid_suffixes:
                if suffix and lower.endswith(suffix):
                    return 5, suffix
            for phase in (4, 3, 2):
                hit = self._best_ending_trap(lower, self.get_ordered_traps(phase))
                if hit is not None:
                    return phase, hit
            return None

        if self.trap_phases:
            for phase in self.trap_phases:
                hit = self._best_ending_trap(lower, self.get_ordered_traps(phase))
                if hit is not None:
                    return phase, hit
            return None

        if self.phase in (2, 3, 4):
            hit = self._best_ending_trap(
                lower, self.get_ordered_traps(self.phase)
            )
            if hit is not None:
                return self.phase, hit
        return None

    @staticmethod
    def _best_ending_trap(word: str, traps: Sequence[str]) -> str | None:
        best: str | None = None
        best_rank: int | None = None
        for idx, trap in enumerate(traps):
            if trap and word.endswith(trap):
                if best_rank is None or idx < best_rank:
                    best = trap
                    best_rank = idx
        return best

    def deprioritize_trap(
        self,
        phase: int,
        trap: str,
        *,
        casual: bool | None = None,
        persist: bool = True,
    ) -> bool:

        key = trap.lower().strip()
        if not key or key in BLACKLISTED_TRAP_PREFIXES:
            return False

        if phase == 5:

            return False

        if phase not in (2, 3, 4):
            return False
        use_casual = self.casual_mode if casual is None else casual
        tiers = self.get_ordered_trap_tiers(phase, casual=use_casual)
        for tier_index, tier in enumerate(tiers):
            if key not in tier:
                continue
            new_tier_order = [item for item in tier if item != key] + [key]
            self.set_priority_tier_order(
                phase,
                tier_index,
                new_tier_order,
                casual=use_casual,
                persist=persist,
            )
            return True
        return False

    def already_used(self, prompt: str) -> tuple[str | None, str | None, str | None]:

        self.ensure_queue(prompt, size=3)
        self.last_decayed_trap = None
        self.last_decayed_phase = None
        if not self._queue:
            return None, None, None
        used = self._queue.pop(0)
        self.mark_used(used)

        match = self.matched_trap_for_word(used)
        if match is not None:
            phase, trap = match
            if self.deprioritize_trap(phase, trap, persist=True):
                self.last_decayed_trap = trap
                self.last_decayed_phase = phase

        ranked = self.ranked_words(prompt)
        self._queue = ranked[:3]
        return self.get_display_words(prompt)
