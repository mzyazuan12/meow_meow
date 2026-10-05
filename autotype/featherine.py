"""Featherine's autotype from last-dletter.

Rhythm is `instant` at tempo 0.72: no typos, a short lead-in, and a little
jitter between keys. Awkward keys hesitate the same way the web client does.
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from typing import Callable, List, Optional, Sequence

STEADY_INTERVAL = 0.09

QWERTY_NEIGHBORS = {
    "a": "qwsz",
    "b": "vghn",
    "c": "xdfv",
    "d": "serfcx",
    "e": "wsdr",
    "f": "drtgvc",
    "g": "ftyhbv",
    "h": "gyujnb",
    "i": "ujko",
    "j": "huikmn",
    "k": "jiolm",
    "l": "kop",
    "m": "njk",
    "n": "bhjm",
    "o": "iklp",
    "p": "ol",
    "q": "wa",
    "r": "edft",
    "s": "awedxz",
    "t": "rfgy",
    "u": "yhji",
    "v": "cfgb",
    "w": "qase",
    "x": "zsdc",
    "y": "tghu",
    "z": "asx",
}

AWKWARD_LETTERS = "jqzxkvw"

# last-dletter CHARACTER_TYPING.featherine
FEATHERINE_TEMPO = 0.72
FEATHERINE_RHYTHM = "instant"


@dataclass
class AutotypeStep:
    typed: str
    delay: float
    kind: str  # "type" | "back"
    key: str


@dataclass
class AutotypePlan:
    word: str
    human: bool
    rhythm: Optional[str]
    tempo: float
    steps: List[AutotypeStep]
    end_pause: float


def slip_key(ch: str, rng: Callable[[], float]) -> str:
    lower = ch.lower()
    opts = QWERTY_NEIGHBORS.get(lower)
    if not opts:
        return ch
    pick = opts[int(rng() * len(opts))]
    return pick if ch == lower else pick.upper()


def key_delay(rhythm: str, tempo: float, rng: Callable[[], float]) -> float:
    if rhythm == "instant":
        return 0.018 + rng() * 0.018
    if rhythm == "mechanical":
        return 0.064 * tempo
    if rhythm == "staccato":
        delay = (0.034 + rng() * 0.035) * tempo
    elif rhythm == "patient":
        delay = (0.08 + rng() * 0.075) * tempo
    else:
        delay = (0.055 + rng() * 0.08) * tempo
    roll = rng()
    if rhythm == "erratic" and roll < 0.16:
        delay += 0.22 + rng() * 0.52
    elif rhythm == "staccato" and roll < 0.12:
        delay += 0.1 + rng() * 0.12
    elif roll < 0.05:
        delay += 0.25 + rng() * 0.5
    elif roll < 0.16:
        delay += 0.12 + rng() * 0.25
    if rhythm not in ("instant", "mechanical"):
        swing = rng()
        if swing < 0.22:
            delay *= 0.28 + rng() * 0.3
        elif swing < 0.40:
            delay += 0.05 + rng() * 0.18
    return delay


def typo_budget(word_length: int, rhythm: str, rng: Callable[[], float]) -> int:
    if word_length < 4 or rhythm in ("instant", "mechanical"):
        return 0
    roll = rng()
    fumble = 0.18 if rhythm == "erratic" else -0.18 if rhythm == "patient" else 0.0
    if word_length >= 10:
        if roll < 0.22 + fumble:
            return 2
        if roll < 0.72 + fumble:
            return 1
        return 0
    if word_length >= 6:
        if roll < 0.12 + fumble:
            return 2
        if roll < 0.55 + fumble:
            return 1
        return 0
    return 1 if roll < 0.42 + fumble else 0


def typing_style_for_name(name: str) -> dict:
    """Same per-name tempo and rhythm the last-dletter bots use."""
    speed_hash = sum(ord(ch) for ch in (name or ""))
    if speed_hash % 5 == 0:
        rhythm = "staccato"
    elif speed_hash % 4 == 0:
        rhythm = "patient"
    else:
        rhythm = "human"
    return {"tempo": 0.86 + (speed_hash % 48) / 100.0, "rhythm": rhythm}


def lead_in_delay(rhythm: str, rng: Callable[[], float]) -> float:
    if rhythm == "instant":
        return 0.04
    if rhythm == "mechanical":
        return 0.12
    if rhythm == "patient":
        return 0.35 + rng() * 0.32
    return 0.15 + rng() * 0.35


def end_pause_for(human: bool, rhythm: Optional[str], rng: Callable[[], float]) -> float:
    if not human:
        return 0.7
    if rhythm == "instant":
        return 0.16
    if rhythm == "staccato":
        return 0.3
    if rhythm == "mechanical":
        return 0.38
    if rhythm == "patient":
        return 0.85
    if rhythm == "erratic":
        return 0.52
    return 0.5 + rng() * 0.55


def build_plan(
    word: str,
    *,
    human: bool = True,
    rhythm: str = FEATHERINE_RHYTHM,
    tempo: float = FEATHERINE_TEMPO,
    rng: Optional[Callable[[], float]] = None,
    immediate: bool = False,
    corrections: Optional[int] = None,
) -> AutotypePlan:
    """Build the same step list last-dletter uses for Featherine."""
    random_fn = rng or random.random
    steps: List[AutotypeStep] = []

    def push(typed: str, delay: float, kind: str = "type") -> None:
        prev = steps[-1].typed if steps else ""
        key = prev[-1] if kind == "back" and prev else typed[len(prev) :]
        steps.append(AutotypeStep(typed=typed, delay=delay, kind=kind, key=key))

    if not human:
        for i in range(len(word)):
            push(word[: i + 1], STEADY_INTERVAL)
        return AutotypePlan(word, False, None, 1.0, steps, end_pause_for(False, None, random_fn))

    forced_at: Optional[int] = None
    if corrections is None:
        budget = typo_budget(len(word), rhythm, random_fn)
    else:
        budget = corrections if len(word) >= 2 else 0
        if budget > 0:
            forced_at = 1 + int(random_fn() * (len(word) - 1))
    shown = ""
    i = 0
    while i < len(word):
        ch = word[i]
        slip = budget > 0 and i >= 1 and (i == forced_at or (forced_at is None and random_fn() < 0.55))
        if slip:
            budget -= 1
            style = random_fn()
            if style < 0.28 and i + 1 < len(word):
                a = ch
                b = word[i + 1]
                push(shown + b, key_delay(rhythm, tempo, random_fn))
                push(shown + b + a, key_delay(rhythm, tempo, random_fn))
                push(shown + b, 0.2 + random_fn() * 0.3, "back")
                push(shown, 0.05 + random_fn() * 0.09, "back")
                push(shown + a, 0.1 + random_fn() * 0.12)
                push(shown + a + b, 0.08 + random_fn() * 0.1)
                shown += a + b
                i += 2
                continue
            if style < 0.5:
                push(shown + ch, key_delay(rhythm, tempo, random_fn))
                push(shown + ch + ch, key_delay(rhythm, tempo, random_fn))
                push(shown + ch, 0.16 + random_fn() * 0.26, "back")
                shown += ch
                i += 1
                continue
            if style < 0.75 and i + 1 < len(word):
                wrong = slip_key(ch, random_fn)
                nxt = word[i + 1]
                push(shown + wrong, key_delay(rhythm, tempo, random_fn))
                push(shown + wrong + nxt, key_delay(rhythm, tempo, random_fn))
                push(shown + wrong, 0.14 + random_fn() * 0.22, "back")
                push(shown, 0.05 + random_fn() * 0.09, "back")
                push(shown + ch, 0.1 + random_fn() * 0.12)
                push(shown + ch + nxt, 0.08 + random_fn() * 0.1)
                shown += ch + nxt
                i += 2
                continue
            wrong = slip_key(ch, random_fn)
            push(shown + wrong, key_delay(rhythm, tempo, random_fn))
            push(shown, 0.18 + random_fn() * 0.3, "back")
            push(shown + ch, 0.1 + random_fn() * 0.12)
            shown += ch
            i += 1
            continue

        delay = key_delay(rhythm, tempo, random_fn)
        if ch.lower() in AWKWARD_LETTERS and random_fn() < 0.45:
            delay += 0.08 + random_fn() * 0.16
        push(shown + ch, delay)
        shown += ch
        i += 1

    if steps and not immediate:
        steps[0].delay += lead_in_delay(rhythm, random_fn)
    elif steps:
        # The prompt is already here. Start on the first key; the rhythm is the gaps after it.
        steps[0].delay = 0.0

    return AutotypePlan(
        word=word,
        human=True,
        rhythm=rhythm,
        tempo=tempo,
        steps=steps,
        end_pause=end_pause_for(True, rhythm, random_fn),
    )


# Pace along one word. The first stretch and the later stretch are different speeds.
_PACE_SHAPES = (
    ("slow-fast", ((0.0, 0.15), (0.36, 0.13), (0.46, 0.052), (1.0, 0.038))),
    ("fast-slow-fast", ((0.0, 0.042), (0.28, 0.048), (0.42, 0.14), (0.62, 0.11), (1.0, 0.046))),
    ("ease", ((0.0, 0.16), (0.3, 0.09), (1.0, 0.04))),
    ("hitch", ((0.0, 0.055), (0.4, 0.048), (0.55, 0.13), (0.72, 0.045), (1.0, 0.04))),
    ("fast-slow", ((0.0, 0.04), (0.45, 0.05), (1.0, 0.15))),
)


def _pace_at(index: int, length: int, points: tuple, rng: Callable[[], float]) -> float:
    span = max(1, length - 1)
    pos = index / span
    delay = points[-1][1]
    for left, right in zip(points, points[1:]):
        if left[0] <= pos <= right[0]:
            width = right[0] - left[0] or 1.0
            mix = (pos - left[0]) / width
            delay = left[1] + (right[1] - left[1]) * mix
            break
    return max(0.022, delay * (0.84 + rng() * 0.32))


def live_plan(word: str, rng: Optional[Callable[[], float]] = None) -> AutotypePlan:
    """Type one word with a changing pace, and spell it exactly.

    A stretch can be slow and the next stretch faster, the way a person
    drifts inside a single word. Some words get one corrected slip. The slip
    is deleted before the real letter, so the word that is submitted is whole.
    """
    random_fn = rng or random.random
    name, points = _PACE_SHAPES[int(random_fn() * len(_PACE_SHAPES))]
    steps: List[AutotypeStep] = []
    shown = ""
    correct_at = -1
    if len(word) >= 6 and random_fn() < 0.36:
        # Slip near the end of the slower opening, not on every word.
        correct_at = 1 + int(random_fn() * max(1, len(word) // 2))
    for index, ch in enumerate(word):
        delay = _pace_at(index, len(word), points, random_fn)
        if index == correct_at:
            wrong = slip_key(ch, random_fn)
            if wrong == ch:
                wrong = "e" if ch != "e" else "a"
            steps.append(AutotypeStep(shown + wrong, delay, "type", wrong))
            steps.append(AutotypeStep(shown, 0.14 + random_fn() * 0.16, "back", wrong))
            steps.append(AutotypeStep(shown + ch, 0.07 + random_fn() * 0.06, "type", ch))
        else:
            steps.append(AutotypeStep(shown + ch, delay, "type", ch))
        shown += ch
    return AutotypePlan(
        word=word,
        human=True,
        rhythm=name,
        tempo=1.0,
        steps=steps,
        end_pause=0.04 + random_fn() * 0.12,
    )


def human_plan(word: str, name: str = "", rng: Optional[Callable[[], float]] = None) -> AutotypePlan:
    """Human key rhythm from the site bots, with no pause before the first letter."""
    style = typing_style_for_name(name or "player")
    return build_plan(
        word,
        human=True,
        rhythm=style["rhythm"],
        tempo=style["tempo"],
        immediate=True,
        rng=rng,
    )


def featherine_plan(word: str, rng: Optional[Callable[[], float]] = None) -> AutotypePlan:
    """Featherine's board tempo on the human plan.

    The instant rhythm is an 18ms burst with no mistakes. The plan's human
    path is the one that reads as a person: neighbor-key slips, corrections,
    awkward-letter hesitations, and the odd longer pause. Tempo 0.72 is her
    speed from the character table, applied to that human path.
    """
    return build_plan(word, human=True, rhythm="human", tempo=FEATHERINE_TEMPO, rng=rng)


def play_plan(
    plan: AutotypePlan,
    tap: Callable[[str, str], None],
    sleep: Callable[[float], None],
    cancelled: Optional[Callable[[], bool]] = None,
) -> bool:
    """Play steps. `tap(kind, key)` sends one key. Returns False if cancelled."""
    for step in plan.steps:
        if cancelled and cancelled():
            return False
        sleep(step.delay)
        if cancelled and cancelled():
            return False
        tap(step.kind, step.key)
    if cancelled and cancelled():
        return False
    sleep(plan.end_pause)
    return not (cancelled and cancelled())
