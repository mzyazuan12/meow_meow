from __future__ import annotations

import math
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

FEATHERINE_TEMPO = 0.72
FEATHERINE_RHYTHM = "instant"

@dataclass
class AutotypeStep:
    typed: str
    delay: float
    kind: str
    key: str

@dataclass
class AutotypePlan:
    word: str
    human: bool
    rhythm: Optional[str]
    tempo: float
    steps: List[AutotypeStep]
    end_pause: float
    # Extras that actually made it into a live turn plan.
    fidgets: int = 0
    mistakes: int = 0

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

        steps[0].delay = 0.0

    return AutotypePlan(
        word=word,
        human=True,
        rhythm=rhythm,
        tempo=tempo,
        steps=steps,
        end_pause=end_pause_for(True, rhythm, random_fn),
    )

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

    random_fn = rng or random.random
    name, points = _PACE_SHAPES[int(random_fn() * len(_PACE_SHAPES))]
    steps: List[AutotypeStep] = []
    shown = ""
    correct_at = -1
    if len(word) >= 6 and random_fn() < 0.36:

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

    random_fn = rng or random.random
    style = typing_style_for_name(name or "player")
    style = dict(style)
    rhythms = (style["rhythm"], "human", "staccato", "patient")
    style["rhythm"] = rhythms[int(random_fn() * len(rhythms))]
    style["tempo"] *= 0.8 + random_fn() * 0.4
    plan = build_plan(
        word,
        human=True,
        rhythm=style["rhythm"],
        tempo=style["tempo"] * 0.82,
        immediate=True,
        rng=random_fn,
    )
    # Short corrections add variation without a long pause at the end.
    for step in plan.steps[1:]:
        step.delay = max(0.035, step.delay * 0.84)
    shape = _PACE_SHAPES[int(random_fn() * len(_PACE_SHAPES))][1]
    for i, step in enumerate(plan.steps[1:], 1):
        step.delay *= _pace_at(i, len(plan.steps), shape, random_fn) / 0.08
    plan.end_pause = 0.035 + random_fn() * 0.040
    if len(word) >= 5 and not any(s.kind == "back" for s in plan.steps) and random_fn() < 0.12:
        at = min(len(plan.steps) - 1, 1 + int(random_fn() * (len(plan.steps) - 1)))
        before = word[:at]
        wrong = slip_key(word[at], random_fn)
        if wrong != word[at]:
            plan.steps[at:at] = [AutotypeStep(before + wrong, 0.045, "type", wrong),
                               AutotypeStep(before, 0.12, "back", wrong)]
    # Occasionally reconsider a small stretch already typed. Each deletion
    # and retyped character is explicit so the final displayed text is exact.
    if len(word) >= 7 and random_fn() < 0.23:
        stop = max(4, min(len(word), int(len(word) * (0.45 + random_fn() * 0.5))))
        depth = min(stop, 2 + int(random_fn() * min(5, stop - 1)))
        for index, step in enumerate(plan.steps):
            if step.typed == word[:stop]:
                back = [AutotypeStep(word[:n], 0.075 + random_fn() * 0.15, "back", "\b")
                        for n in range(stop - 1, stop - depth - 1, -1)]
                forward = [AutotypeStep(word[:n], 0.06 + random_fn() * 0.16, "type", word[n - 1])
                           for n in range(stop - depth + 1, stop + 1)]
                plan.steps[index + 1:index + 1] = back + forward
                break
    # Rarely finish with a nearby-key slip. An early Enter is only a trial of
    # this nearly complete, visibly wrong input; final Enter still follows
    # correction and screen verification in the controller.
    if len(word) >= 6 and random_fn() < 0.08:
        wrong = slip_key(word[-1], random_fn)
        if wrong != word[-1]:
            stem = word[:-1]
            plan.steps.extend((AutotypeStep(stem, 0.09 + random_fn() * 0.15, "back", "\b"),
                               AutotypeStep(stem + wrong, 0.06 + random_fn() * 0.12, "type", wrong),
                               AutotypeStep(stem + wrong, 0.02, "enter", "\n"),
                               AutotypeStep(stem, 0.11 + random_fn() * 0.2, "back", "\b"),
                               AutotypeStep(word, 0.07 + random_fn() * 0.12, "type", word[-1])))
    # Keep very long dictionary entries at a plausible pace. Scale intervals,
    # preserving the chosen rhythm and a zero delay before the first key.
    minimum = (max(9.0, len(word) * 0.12) if len(word) >= 70 else
               len(word) * 0.16 if len(word) >= 25 else 0.0)
    maximum = 12.0 if len(word) >= 70 else float("inf")
    duration = sum(max(0.022, step.delay) for step in plan.steps[1:]) + plan.end_pause
    if minimum and not minimum <= duration <= maximum:
        target = max(minimum, min(duration, maximum))
        scale = (target - plan.end_pause) / max(0.001, duration - plan.end_pause)
        for step in plan.steps[1:]:
            step.delay *= scale
    return plan

KEY_HOLD = 0.022
# Fastest interval between letters when the clock is tight.
MIN_INTERVAL = 0.052
FIDGET_SLACK = 0.85

_FAST_PAIRS = frozenset({
    "th", "he", "in", "er", "an", "re", "on", "at", "en", "nd", "ti", "es",
    "or", "te", "of", "ed", "is", "it", "al", "ar", "st", "to", "nt", "ng",
    "se", "ha", "as", "ou", "io", "le", "ve", "co", "me", "de", "la", "li",
})

# Non-linear envelopes so a word never sits on one interval.
_TURN_SHAPES = (
    ((0.0, 1.24), (0.30, 0.80), (1.0, 0.72)),
    ((0.0, 0.76), (0.36, 0.68), (0.55, 1.40), (1.0, 0.86)),
    ((0.0, 1.10), (0.20, 0.66), (0.48, 1.20), (0.72, 0.74), (1.0, 1.04)),
    ((0.0, 0.70), (0.42, 0.94), (1.0, 1.30)),
    ((0.0, 1.16), (0.14, 0.64), (0.50, 0.70), (0.58, 1.46), (1.0, 0.82)),
    ((0.0, 0.86), (0.16, 1.28), (0.38, 0.68), (0.78, 0.76), (1.0, 1.18)),
)


def plan_duration(steps: Sequence[AutotypeStep]) -> float:
    return sum(step.delay for step in steps) + KEY_HOLD * sum(step.kind != "enter" for step in steps)


def _shape_at(index: int, length: int, points: tuple) -> float:
    pos = index / max(1, length - 1)
    delay = points[-1][1]
    for left, right in zip(points, points[1:]):
        if left[0] <= pos <= right[0]:
            width = right[0] - left[0] or 1.0
            mix = (pos - left[0]) / width
            return left[1] + (right[1] - left[1]) * mix
    return delay


# --- live turn typing ------------------------------------------------------------
#
# Everything about a turn is drawn fresh: the pace, how the pace moves inside the
# word, whether there are errors and which kind, and whether (and how) the turn
# opens with fidgets. Nothing here is a fixed set of buckets.

# One turn's pace in WPM: (low, high, weight). Slow turns do happen, and even
# the quick band stays short of anything a person could not type.
_PACE_BANDS = ((40.0, 62.0, 0.16), (62.0, 100.0, 0.49), (100.0, 128.0, 0.27), (128.0, 144.0, 0.08))
_GAME_PACE = [1.0]


def _game_drift(rng: Callable[[], float]) -> float:
    """Slow drift in how fast this player is across a game (gap multiplier)."""
    value = 1.0 + (_GAME_PACE[0] - 1.0) * 0.75 + (rng() - 0.5) * 0.24
    _GAME_PACE[0] = min(1.24, max(0.80, value))
    return _GAME_PACE[0]


def _turn_mean(rng: Callable[[], float]) -> float:
    """This turn's mean gap between letters, from a WPM drawn across the bands."""
    roll = rng() * sum(weight for _lo, _hi, weight in _PACE_BANDS)
    wpm = _PACE_BANDS[-1][1]
    for low, high, weight in _PACE_BANDS:
        if roll < weight:
            wpm = low + rng() * (high - low)
            break
        roll -= weight
    return 12.0 / wpm


def _break_runs(body: List[float]) -> None:
    """No four keys in a row may speed up or slow down steadily."""
    for i in range(len(body) - 3):
        a, b, c, d = body[i:i + 4]
        if a < b < c < d or a > b > c > d:
            body[i + 1], body[i + 2] = body[i + 2], body[i + 1]


def _human_gaps(suffix: str, mean: float, rng: Callable[[], float]) -> List[float]:
    n = len(suffix)
    if not n:
        return []
    points = _TURN_SHAPES[int(rng() * len(_TURN_SHAPES))]
    depth = 0.35 + rng() * 0.75
    hesitate = 0.04 + rng() * 0.09
    wander = 0.0
    burst = 0
    raw: List[float] = []
    for i, ch in enumerate(suffix):
        mult = 1.0 + (_shape_at(i, n, points) - 1.0) * depth
        # A smooth drift on top of the envelope: speed leans one way for a
        # few keys, then another, instead of hopping between fixed values.
        wander = wander * 0.5 + (rng() - 0.5) * 0.6
        mult *= math.exp(wander)
        if i > 0 and burst <= 0 and rng() < 0.28:
            burst = 2 + int(rng() * 3)
        if burst > 0:
            mult *= 0.62 + rng() * 0.20
            burst -= 1
            if burst == 0:
                mult *= 1.25 + rng() * 0.45
        if i and suffix[i - 1:i + 1].lower() in _FAST_PAIRS:
            mult *= 0.74 + rng() * 0.14
        if ch.lower() in AWKWARD_LETTERS:
            mult *= 1.10 + rng() * 0.30
        mult *= math.exp((rng() + rng() + rng() - 1.5) * 0.5)
        roll = rng()
        if roll < hesitate:
            mult *= 1.8 + rng() * 1.5
        elif roll < hesitate + 0.08:
            mult *= 0.62 + rng() * 0.16
        raw.append(mult)
    body = raw[1:] if n > 1 else raw[:]
    if len(body) >= 3:
        for _ in range(3):
            if max(body) > min(body) * 1.7:
                break
            slow, fast = int(rng() * len(body)), int(rng() * len(body))
            body[slow] *= 1.5 + rng() * 0.6
            body[fast] *= 0.55 + rng() * 0.15
        _break_runs(body)
    raw = ([raw[0]] + body) if n > 1 else body
    average = sum(body) / len(body) if body else 1.0
    # The turn keeps the pace it was dealt; only the shape inside it varies.
    return [min(0.62, max(0.048, mean * m / average)) for m in raw]


def _reaction(budget: float, fidget: Sequence, rng: Callable[[], float]) -> float:
    # Board reading already took a frame or two; the first key goes out at once.
    if fidget or budget <= 2.5:
        return rng() * 0.006
    return rng() * 0.012


def _fidget_text(prefix: str, suffix: str, rng: Callable[[], float]) -> str:
    roll = rng()
    first = (suffix or prefix or "e")[0]
    if roll < 0.20 and prefix:
        tail = prefix[-2:] if len(prefix) >= 2 else prefix
        if rng() < 0.4 and len(tail) == 2:
            return tail[1] + tail
        return tail
    if roll < 0.46 and suffix:
        return suffix[:1 + int(rng() * min(2, len(suffix)))]
    if roll < 0.64:
        return first + slip_key(first, rng)
    if roll < 0.80:
        wrong = slip_key(first, rng)
        return wrong if wrong != first else first
    if roll < 0.92:
        ch = suffix[int(rng() * min(2, len(suffix)))] if suffix else first
        return ch + ch
    wander = slip_key(first, rng)
    return (wander + slip_key(wander, rng))[:2] or first


_FIDGET_STYLES = ("tap", "stutter", "wander", "head", "messy", "mash", "echo")


def _fidget_act(style: str, prefix: str, suffix: str, rng: Callable[[], float]) -> list:
    """One fidget as (op, key, delay) with its own speed. It always ends empty.

    The first op's delay is 0; the caller supplies the lead-in pause.
    """
    speed = 0.55 + rng() * 1.45
    if style in ("mash", "stutter"):
        speed *= 0.65
    first = (suffix or prefix or "e")[0]
    ops: list = []

    def type_text(text: str) -> None:
        for ch in text:
            gap = 0.0 if not ops else max(0.04, (0.045 + rng() * 0.10) * speed)
            ops.append(("type", ch, gap))

    def erase(count: int, hold: float = 0.0) -> None:
        for k in range(count):
            gap = (0.07 + rng() * 0.17) if k == 0 else (0.028 + rng() * 0.075)
            ops.append(("back", "\b", max(0.03, gap * speed + (hold if k == 0 else 0.0))))

    def neighbours(count: int) -> str:
        out, ch = "", first
        for _ in range(count):
            ch = slip_key(ch, rng)
            out += ch
        return out

    if style == "stutter":
        type_text(first)
        erase(1)
        ops.append(("type", first if rng() < 0.5 else slip_key(first, rng), 0.03 + rng() * 0.08))
        erase(1)
    elif style == "wander":
        text = neighbours(1 + int(rng() * 3))
        type_text(text)
        erase(len(text), 0.10 + rng() * 0.28)
    elif style == "head" and suffix:
        text = suffix[:1 + int(rng() * min(2, len(suffix)))]
        type_text(text)
        erase(len(text), rng() * 0.16)
    elif style == "messy":
        type_text(first + neighbours(2))
        erase(1)
        type_text(slip_key(first, rng))
        erase(3)
    elif style == "mash":
        text = neighbours(3 + int(rng() * 2))
        type_text(text)
        erase(len(text))
    elif style == "echo" and prefix:
        text = prefix[-2:]
        type_text(text)
        erase(len(text))
    else:
        text = _fidget_text(prefix, suffix, rng)[:3] or "e"
        type_text(text)
        erase(len(text))
    return ops


def _fidget_acts(prefix: str, suffix: str, budget: float,
                 rng: Callable[[], float]) -> tuple:
    """Zero to three fidgets before the word, and the pause after each.

    Only a 1-2 letter prefix with time to spare fidgets repeatedly. The pauses
    between them range from almost none to a real beat.
    """
    if not suffix:
        return [], []
    tiny, short = len(prefix) <= 1, len(prefix) <= 2
    if tiny:
        chance = 0.36 if budget > 4 else 0.12
    elif short:
        chance = 0.26 if budget > 4 else 0.09
    else:
        chance = 0.09 if budget > 5 else 0.03
    if rng() >= chance:
        return [], []
    count = 1
    if short and budget > 5:
        if rng() < (0.42 if tiny else 0.30):
            count = 2
            if budget > 7 and rng() < (0.34 if tiny else 0.20):
                count = 3
    elif not short and budget > 6 and rng() < 0.10:
        count = 2
    pool = list(_FIDGET_STYLES)
    acts, pauses = [], []
    for index in range(count):
        style = pool.pop(int(rng() * len(pool)))
        acts.append(_fidget_act(style, prefix, suffix, rng))
        roll = rng()
        if index + 1 < count:
            if roll < 0.22:
                pauses.append(0.015 + rng() * 0.05)
            elif roll < 0.72:
                pauses.append(0.08 + rng() * 0.20)
            else:
                pauses.append(0.22 + rng() * 0.36)
        elif roll < 0.30:
            pauses.append(0.02 + rng() * 0.06)
        elif roll < 0.80:
            pauses.append(0.07 + rng() * 0.18)
        else:
            pauses.append(0.24 + rng() * 0.30)
    return acts, pauses


def _fix_speed(rng: Callable[[], float]) -> float:
    """How fast this slip gets corrected: mostly medium to fast, rarely slow."""
    roll = rng()
    if roll < 0.30:
        return 0.55 + rng() * 0.15
    if roll < 0.88:
        return 0.75 + rng() * 0.40
    return 1.2 + rng() * 0.5


def _one_error(prefix: str, suffix: str, low: int, rng: Callable[[], float],
               is_word: Optional[Callable[[str], bool]]) -> Optional[dict]:
    n = len(suffix)
    weights = (("sub", 0.34), ("dup", 0.12), ("swap", 0.14), ("skip", 0.12), ("end", 0.20))
    for _attempt in range(6):
        roll = rng() * sum(w for _s, w in weights)
        style = weights[-1][0]
        for name, weight in weights:
            if roll < weight:
                style = name
                break
            roll -= weight
        ev: Optional[dict] = None
        if style == "end":
            if n < 3 or low > n - 2:
                continue
            at = n - 1 if rng() < 0.65 or low > n - 2 else n - 2
            at = max(at, low)
            wrong = slip_key(suffix[at], rng)
            if wrong == suffix[at]:
                wrong = "e" if suffix[at] != "e" else "a"
            text = wrong + suffix[at + 1:]
            if is_word is not None and is_word(prefix + suffix[:at] + text):
                continue
            ev = dict(style=style, at=at, wrong=text, retype=suffix[at:], consumed=n - at,
                      enter_try=True)
        elif style in ("sub", "dup"):
            if low >= n:
                continue
            at = int(low + rng() * (n - low))
            if at == 0 and n > 2 and rng() < 0.6:
                at = 1 + int(rng() * (n - 1))
            ch = suffix[at]
            if style == "dup":
                if at + 1 < n and suffix[at + 1] == ch:
                    continue  # the word really doubles it; nothing is wrong
                ev = dict(style=style, at=at, wrong=ch + ch, back=1, retype="", consumed=1)
            else:
                wrong = slip_key(ch, rng)
                if wrong == ch:
                    wrong = "e" if ch != "e" else "a"
                pick = rng()
                run = 0 if pick < 0.50 else 1 if pick < 0.75 else 2 if pick < 0.92 else 3
                run = min(run, n - 1 - at)
                ev = dict(style=style, at=at, wrong=wrong + suffix[at + 1:at + 1 + run],
                          retype=suffix[at:at + 1 + run], consumed=1 + run)
        elif style == "swap":
            if low > n - 2:
                continue
            at = int(low + rng() * (n - 1 - low))
            if suffix[at] == suffix[at + 1]:
                continue
            run = min(1 if rng() < 0.30 else 0, n - 2 - at)
            ev = dict(style=style, at=at, wrong=suffix[at + 1] + suffix[at] + suffix[at + 2:at + 2 + run],
                      retype=suffix[at:at + 2 + run], consumed=2 + run)
        else:  # skip a letter, notice a key or two later
            if low > n - 2:
                continue
            at = int(low + rng() * (n - 1 - low))
            if suffix[at] == suffix[at + 1]:
                continue
            run = min(0 if rng() < 0.5 else 1 if rng() < 0.7 else 2, n - 2 - at)
            ev = dict(style=style, at=at, wrong=suffix[at + 1:at + 2 + run],
                      retype=suffix[at:at + 2 + run], consumed=2 + run)
        if ev is None:
            continue
        ev.setdefault("back", len(ev["wrong"]))
        fix = _fix_speed(rng)
        late = 1.0 + 0.2 * (len(ev["wrong"]) - 1)
        ev["notice"] = (0.06 + rng() * 0.24) * fix * min(1.6, late)
        ev["back_gaps"] = [max(0.03, (0.028 + rng() * 0.075) * fix) for _ in range(max(0, ev["back"] - 1))]
        ev["retype_gaps"] = [max(0.04, (0.05 + rng() * 0.11) * fix) for _ in ev["retype"]]
        ev["run_speed"] = 0.62 + rng() * 0.32
        ev["try_wait"] = 0.035 + rng() * 0.07
        if ev.get("enter_try"):
            # Enter was hit on the misspelling: the pause to read it is longer.
            ev["notice"] = max(ev["notice"], 0.09 + rng() * 0.22)
        return ev
    return None


def _error_events(prefix: str, suffix: str, rng: Callable[[], float],
                  is_word: Optional[Callable[[str], bool]]) -> dict:
    """Mistakes for this turn, keyed by the letter they start at.

    Some turns are clean, some sloppy. A slip can be caught at once or a few
    keys later, and what it looks like changes each time.
    """
    n = len(suffix)
    if n < 2:
        return {}
    mood = rng()
    chance = 0.0 if mood < 0.30 else 0.36 if mood < 0.80 else 0.66
    events: dict = {}
    covered = -1
    if rng() < chance:
        count = 1 + (n >= 6 and rng() < 0.22) + (n >= 9 and rng() < 0.10)
        for _ in range(count):
            ev = _one_error(prefix, suffix, covered + 1, rng, is_word)
            if ev is None:
                break
            events[ev["at"]] = ev
            covered = ev["at"] + ev["consumed"]
    # Now and then Enter is hit on a correct but unfinished word, then typing goes on.
    if n >= 4 and is_word is not None and rng() < 0.05:
        at = 2 + int(rng() * (n - 2))
        if at > covered and at not in events and not is_word(prefix + suffix[:at]):
            events[at] = dict(style="early", at=at, wait=0.035 + rng() * 0.07,
                              resume=0.16 + rng() * 0.18)
    return events


def turn_plan(suffix: str, prefix: str = "", budget: Optional[float] = None,
              rng: Optional[Callable[[], float]] = None,
              is_word: Optional[Callable[[str], bool]] = None) -> AutotypePlan:
    """Keys for one turn, ending with Enter straight after the last letter.

    Pace, fidgets and mistakes are all drawn per turn, and pace also drifts
    across a game. Spare time can add fidgets, then mistakes; they are dropped
    in that order, then the pace is raised to its floor, to finish inside
    ``budget`` seconds. The finished word is always what Enter submits.
    """
    random_fn = rng or random.random
    budget = float("inf") if budget is None else max(0.0, budget)
    drift = _game_drift(random_fn) if rng is None else 1.0
    mean = _turn_mean(random_fn) * drift
    letters = _human_gaps(suffix, mean, random_fn)
    acts, pauses = _fidget_acts(prefix, suffix, budget, random_fn)
    reaction = _reaction(budget, acts, random_fn)
    errors = _error_events(prefix, suffix, random_fn, is_word)
    n = len(suffix)

    def gap_at(index: int, scale: float) -> float:
        if 0 <= index < len(letters):
            return letters[index] * scale
        return mean * (0.7 + random_fn() * 0.5) * scale

    def build(scale: float, with_fidgets: bool, with_errors: bool) -> List[AutotypeStep]:
        steps: List[AutotypeStep] = []
        pause = reaction

        def push(typed: str, delay: float, kind: str, key: str) -> None:
            steps.append(AutotypeStep(typed, delay, kind, key))

        if with_fidgets:
            for act, after in zip(acts, pauses):
                shown = ""
                for position, (op, key, gap) in enumerate(act):
                    delay = pause if position == 0 else gap
                    if op == "type":
                        shown += key
                        push(shown, delay, "type", key)
                    else:
                        shown = shown[:-1]
                        push(shown, delay, "back", "\b")
                pause = after
        shown = ""
        i = 0
        while i < n:
            delay = pause if i == 0 else gap_at(i, scale)
            pause = 0.0
            ev = errors.get(i) if with_errors else None
            if ev is not None and ev["style"] == "early":
                push(shown, ev["wait"], "early", "\n")
                delay = ev["resume"]
                ev = None
            if ev is None:
                shown += suffix[i]
                push(shown, delay, "type", suffix[i])
                i += 1
                continue
            for k, ch in enumerate(ev["wrong"]):
                shown += ch
                push(shown, delay if k == 0 else gap_at(i + k, scale) * ev["run_speed"], "type", ch)
            if ev.get("enter_try"):
                push(shown, ev["try_wait"], "early", "\n")
            for k in range(ev["back"]):
                shown = shown[:-1]
                push(shown, ev["notice"] if k == 0 else ev["back_gaps"][k - 1], "back", "\b")
            for k, ch in enumerate(ev["retype"]):
                shown += ch
                push(shown, ev["retype_gaps"][k], "type", ch)
            i += ev["consumed"]
        push(shown, 0.0 if not steps else 0.01 + random_fn() * 0.03, "enter", "\n")
        return steps

    use_fidgets, use_errors = True, True
    steps = build(1.0, True, True)
    slack = FIDGET_SLACK if acts else 0.55
    if plan_duration(steps) + slack > budget:
        use_fidgets = False
        steps = build(1.0, False, True)
        if plan_duration(steps) + 0.55 > budget:
            use_errors = False
            steps = build(1.0, False, False)
    if plan_duration(steps) > budget and n > 1:
        use_fidgets = use_errors = False
        fixed = plan_duration(build(0.0, False, False))
        natural = max(1e-6, plan_duration(steps) - fixed)
        steps = build(min(1.0, max(0.0, (budget - fixed) / natural)), False, False)
        for step in steps[1:]:
            if step.kind == "type":
                step.delay = max(MIN_INTERVAL, step.delay)
    mistakes = sum(1 for ev in errors.values() if ev["style"] != "early") if use_errors else 0
    return AutotypePlan(suffix, True, "turn", mean, steps, 0.0,
                        fidgets=len(acts) if use_fidgets else 0, mistakes=mistakes)


def edit_plan(current: str, target: str, budget: Optional[float] = None,
              rng: Optional[Callable[[], float]] = None) -> AutotypePlan:
    """Fewest keys from the typed suffix to another answer, then Enter."""
    random_fn = rng or random.random
    common = 0
    for a, b in zip(current, target):
        if a != b:
            break
        common += 1
    budget = float("inf") if budget is None else budget
    steps: List[AutotypeStep] = []
    pause = 0.15 + random_fn() * 0.2 if budget > 2.0 else 0.05
    for n in range(len(current) - 1, common - 1, -1):
        steps.append(AutotypeStep(current[:n], pause, "back", "\b"))
        pause = 0.045 + random_fn() * 0.04
    base = 0.08 + random_fn() * 0.05
    for n in range(common + 1, len(target) + 1):
        steps.append(AutotypeStep(target[:n], pause, "type", target[n - 1]))
        pause = base * (0.58 + random_fn() * 0.84)
        if random_fn() < 0.12:
            pause += 0.04 + random_fn() * 0.08
    steps.append(AutotypeStep(target, 0.0 if not steps else 0.01 + random_fn() * 0.03, "enter", "\n"))
    total = plan_duration(steps)
    if total > budget and len(steps) > 2:
        scale = max(0.4, budget / total)
        for step in steps[1:-1]:
            step.delay = max(0.04, step.delay * scale)
    return AutotypePlan(target, True, "edit", base, steps, 0.0)


def featherine_plan(word: str, rng: Optional[Callable[[], float]] = None) -> AutotypePlan:

    return build_plan(word, human=True, rhythm="human", tempo=FEATHERINE_TEMPO, rng=rng)

def play_plan(
    plan: AutotypePlan,
    tap: Callable[[str, str], None],
    sleep: Callable[[float], None],
    cancelled: Optional[Callable[[], bool]] = None,
) -> bool:

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
