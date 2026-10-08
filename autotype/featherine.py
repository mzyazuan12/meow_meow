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
# Fastest interval between letters, about 13 keys a second including the hold.
MIN_INTERVAL = 0.055
FIDGET_CHANCE = 0.22
TYPO_CHANCE = 0.25
EARLY_ENTER_CHANCE = 0.08
FIDGET_SLACK = 1.6


def plan_duration(steps: Sequence[AutotypeStep]) -> float:
    return sum(step.delay for step in steps) + KEY_HOLD * sum(step.kind != "enter" for step in steps)


def _fidget(prefix: str, suffix: str, rng: Callable[[], float]) -> List[List[str]]:
    """Short bursts typed and erased before the answer, like "ism" -> "ismsm"."""
    bursts = []
    for _ in range(1 + int(rng() * 3)):
        style = rng()
        if style < 0.35 and prefix:
            # Echo the end of the prompt, as if re-reading it.
            tail = prefix[-2:] if len(prefix) >= 2 else prefix
            burst = tail[1:] + tail if rng() < 0.5 else tail
        elif style < 0.65 and suffix:
            # A false start of the real answer.
            burst = suffix[:1 + int(rng() * min(2, len(suffix)))]
        else:
            first = (suffix or prefix or "e")[0]
            burst = first + slip_key(first, rng)
        bursts.append(burst[:3] or "e")
    return bursts


def turn_plan(suffix: str, prefix: str = "", budget: Optional[float] = None,
              rng: Optional[Callable[[], float]] = None,
              is_word: Optional[Callable[[str], bool]] = None) -> AutotypePlan:
    """Keys for one turn, ending with Enter straight after the last letter.

    The pace stays within human limits. With spare time there is sometimes a
    fidget before the answer, a corrected typo, or an Enter pressed one to
    three letters early on a non-word. Extras are dropped, then the pace is
    raised to its floor, to finish inside ``budget`` seconds.
    """
    random_fn = rng or random.random
    budget = float("inf") if budget is None else max(0.0, budget)
    base = 0.09 + random_fn() * 0.06
    # Reading the board already took two captures; this is the rest of a reaction.
    reaction = 0.03 + random_fn() * 0.12 if budget > 2.5 else random_fn() * 0.04

    def key_gap(ch: str) -> float:
        delay = base * (0.75 + random_fn() * 0.5)
        if ch in AWKWARD_LETTERS and random_fn() < 0.4:
            delay += 0.03 + random_fn() * 0.05
        return delay

    letters = [key_gap(ch) for ch in suffix]
    hesitations = {i: 0.15 + random_fn() * 0.25 for i in range(2, len(suffix))
                   if len(suffix) >= 8 and random_fn() < 0.05}
    fidget = _fidget(prefix, suffix, random_fn) if suffix and random_fn() < FIDGET_CHANCE else []
    typo_at = (1 + int(random_fn() * (len(suffix) - 2))
               if len(suffix) >= 3 and random_fn() < TYPO_CHANCE else -1)
    typo_style = random_fn()
    early_at = -1
    if len(suffix) >= 4 and random_fn() < EARLY_ENTER_CHANCE:
        at = len(suffix) - 1 - int(random_fn() * 3)
        if at >= 2 and is_word is not None and not is_word(prefix + suffix[:at]):
            early_at = at

    def build(scale: float, extras: bool) -> List[AutotypeStep]:
        steps: List[AutotypeStep] = []
        pause = reaction

        def push(typed: str, delay: float, kind: str, key: str) -> None:
            steps.append(AutotypeStep(typed, delay, kind, key))

        if extras:
            for burst in fidget:
                for n in range(1, len(burst) + 1):
                    push(burst[:n], pause if n == 1 else key_gap(burst[n - 1]) * scale, "type", burst[n - 1])
                    pause = 0.0
                for n in range(len(burst) - 1, -1, -1):
                    push(burst[:n], (0.18 + random_fn() * 0.3 if n == len(burst) - 1 else
                                     0.05 + random_fn() * 0.05), "back", "\b")
                pause = 0.12 + random_fn() * 0.3
        shown = ""
        for i, ch in enumerate(suffix):
            delay = (pause if i == 0 else letters[i] * scale) + (hesitations.get(i, 0.0) if extras else 0.0)
            pause = 0.0
            if extras and i == early_at:
                push(shown, 0.04 + random_fn() * 0.08, "early", "\n")
                delay = 0.25 + random_fn() * 0.3
            if extras and i == typo_at:
                wrong = slip_key(ch, random_fn)
                if wrong == ch:
                    wrong = "e" if ch != "e" else "a"
                push(shown + wrong, delay, "type", wrong)
                if typo_style < 0.45 and i + 1 < len(suffix):
                    # Noticed one letter late.
                    nxt = suffix[i + 1]
                    push(shown + wrong + nxt, key_gap(nxt) * scale, "type", nxt)
                    push(shown + wrong, 0.14 + random_fn() * 0.2, "back", "\b")
                    push(shown, 0.05 + random_fn() * 0.05, "back", "\b")
                else:
                    push(shown, 0.12 + random_fn() * 0.2, "back", "\b")
                delay = 0.07 + random_fn() * 0.08
            shown += ch
            push(shown, delay, "type", ch)
        push(shown, 0.0 if not steps else 0.01 + random_fn() * 0.03, "enter", "\n")
        return steps

    steps = build(1.0, True)
    # Fidgets need real spare time; a typo or early Enter needs a little.
    slack = FIDGET_SLACK if fidget else 0.6
    if plan_duration(steps) + slack > budget:
        steps = build(1.0, False)
    if plan_duration(steps) > budget and len(suffix) > 1:
        # Faster, but never beyond the human floor; the word was chosen to fit.
        fixed = plan_duration(build(0.0, False))
        natural = max(1e-6, plan_duration(steps) - fixed)
        steps = build(min(1.0, max(0.0, (budget - fixed) / natural)), False)
        for step in steps[1:]:
            if step.kind == "type":
                step.delay = max(MIN_INTERVAL, step.delay)
    return AutotypePlan(suffix, True, "turn", base, steps, 0.0)


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
        pause = base * (0.75 + random_fn() * 0.5)
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
