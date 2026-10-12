# eschaton v4.9

Reads the Roblox Last Letter board, tracks accepted words for the current game, and types only the ending after the supplied prefix.

## Run

Use Python 3.9 or newer with tkinter. From this folder:

```bash
python3 -m pip install -r requirements-autotype.txt
python3 autotype_app.pyw
```

On Windows, use `py` in place of `python3` if needed. Keep `autotype/`, `dyoe2_engine.py`, `dict (7).txt`, and `data/` beside the app.

Open Roblox to Last Letter. Enter your username in **YOU**, or press **It's your turn?** once while the game is asking you for a word. The button adopts the readable username and starts the current prompt. Once identified, your turns start automatically; split usernames and temporarily unreadable headers do not require another click. If the header is covered or outside the capture, the button confirms this turn manually. Username edits also take effect immediately. Your identity is kept only until the app closes; every launch starts with a blank YOU field. Choices refresh for each readable prefix while turn detection is uncertain.

The app arms when its dictionary and the Roblox player are available. **ARMED** toggles typing off. If Roblox disappears, typing stops and the app shows **ROBLOX ISN'T AVAILABLE**. If the process exists but its window cannot be captured, it shows **ROBLOX ISN'T VISIBLE**. Browser pages and Roblox Studio do not count as the player.

**PAUSE** immediately cancels typing, pending Enter, and corrections, and suspends capture and game processing. **RESUME** reads the current turn again and clears an interrupted suffix before restarting if that same turn is still yours. Used words and username stay in memory. Escape also toggles pause when the Tk panel has focus. Used words are cleared only when you manually press **NEW GAME**.

**HIGH PERFORMANCE** is an optional, saved switch on both panels. It reads every new capture without pausing between reads, refreshes an unchanged picture more often, and keeps the capture queue short while preserving controls. It also reads the speech box above each player that shows their accepted word. Letters the reader cannot tell apart (such as q/o/g or i/l) are kept as alternatives and resolved against the dictionary. A speech-box word is used only when it starts with the prompt that player was given, matches their visible typing or the next prompt, is read in two fresh captures, and is the only word that fits; it then marks the opponent's word as used and settles which ending they handed over. Unrelated or ambiguous boxes do not become used words. This changes detection and tracking, not the typing rhythm, and uses more CPU. Screen capture and game rendering still limit how quickly a change can be observed.

Each game rolls a new trap style, and no trap list decides the choice. An ending's deadliness comes from the dictionary: how few answers it leaves (next-letter groups in CASUAL) and how long they are. Long answers make up for a few more answers, never for a crowd. The style sets how close to the deadliest ending on offer another must be to count as equally deadly, how much long answers count, which ending shapes are favoured, what length of word to play, and its own order among equals. Among equally deadly endings it picks favoured shapes first, then the least played this session, then its own order, so the same prompt is answered differently from game to game while every pick stays deadly. A prompt with one ending far deadlier than the rest still gets that ending.

Choose **CASUAL**, **PRO**, or **SPAM**. CASUAL and PRO use DYOE2's trap sources (casual prefixes; or special, no-plural and `traps.txt` for pro), but not their fixed order. The next player's prompt is as long as yours, so traps of that length come first, and one letter longer is a hedge for a stage change; a one-letter prompt can only hedge with two-letter traps. Among traps, those with the fewest solves left come first, and the game's style chooses among equally deadly ones. Solves left is the smaller of the unused dictionary answers and the dictionary total minus the times this game the prefix was already handed to an opponent, so a prefix with two solves is never given a third time even if those answers were never read. Each earlier hand-over also lowers its priority, so other deadly prefixes get used. The prefix handed over is the opponent's actual starting prompt when it is seen. Longer solves make a trap deadlier. A trap that is itself an unused word (answered by pressing Enter) is not a trap, and a prefix starting or ending with `-` or `'` is never one. In PRO, traps containing `-` or `'` rank higher. A trap whose answer is just the prompt plus `s`/`es` ranks lower. After traps come DYOE cancel words (casual), then the remaining answers.

In SPAM, enter bracket-, comma-, or space-separated endings such as `[ing][ary][ness]` or `ing, ary, ness`. SPAM is DYOE2's phase 5 hybrid: words ending with the first ending (shortest first), then the next ending, then the 4-, 3- and 2-letter traps, then everything else. Accepted words are excluded from later choices. Mode and spam endings are remembered; usernames and the current game's used words are not.

The turn clock under the table is read every frame: the coloured arc gives the fraction of the turn left, and the digits are read when legible. A turn lasts 15, 10, 7, 5 or 3 seconds depending on the stage; the stage is learned from the digits or from how fast the arc shrinks. Answers are limited to what can be typed at a human pace in the time left (about 0.18 s per letter), shorter answers are preferred under six seconds, and phase 1 answers are at most 14 typed letters.

The deadline continues counting down if the clock picture freezes or becomes unreadable. While typing, the app checks whether the remaining plan still fits; when needed it changes to a finishable answer requiring fewer edits from the letters already visible. It cannot prevent a timeout when no available dictionary answer exists or the screen/input cannot be read or controlled.

Press **NEW GAME** yourself to clear used words, hand-over counts, and roll a new trap style. One-letter prompts, unreadable headers, long breaks, dictionary loading, and Roblox reconnecting never clear used words automatically. The phase follows the actual prefix length: three letters means phase 3; four means phase 4. Opponent readings, including a word already visible in the first frame confirming our submission, are retained through blank/incomplete frames and checked against the opponent's starting prefix and your next prefix. A uniquely supported completion can recover `mho` as `mhorr` when the next prefix is `r`. Hyphens and apostrophes are preserved and allowed for typing in every autotyper mode. If a prefix has no available extension and is not itself a dictionary word, its reversal is tried. An unused self-solvable prompt of at least two letters is chosen about one quarter of the time (or whenever there is no extension); it sends Enter with no extra letters. Single-letter dictionary entries never trigger Enter-only submissions. Ambiguous completions are reported without adding a guessed word. Rejected attempts are excluded separately from accepted words.

Typing starts the actual answer with no added opening pause or fidget. It keeps a human pace (about 0.09–0.15 s per letter, varied per key, never faster than about 13 keys a second), and can make and correct a nearby-key typo later in the word. These extras are dropped when time is short, and the pace is raised only as far as needed to finish before the clock runs out.

Opponent frames are kept as read, including a final word visible just after the header changes. Prompt correction uses that word before ranking answers: `gnign` after `kinging` can resolve to `ging`, while an ordered fragment such as `size` from `vmsize` is not called a glitch or stripped down to `ze`. Mirrored prompts are labeled separately. Confirmed opponent words are recorded before choosing our answer.

A complete ending supported by the opponent's word is ready on the first capture; this includes corrected four-letter prompts. Other reads need confirmation, and short mirrored or shuffled rows still wait briefly when another tile could be coming. A partial `bil` is not accepted while the opponent's ending shows that `bils` is still drawing. Incomplete rows are not ranked, and missing tile slots are never discarded during correction.

Before Enter, a fresh readable board capture must match the intended word exactly. Missing, extra, or wrong letters are repaired from what is actually visible: `beatingg` loses its extra `g` and is checked again. An unreadable or clipped row shows **CHECKING FINAL WORD** until it can be verified; intended keystrokes alone never authorize Enter. Enter retries also require the exact word. Enter is only sent while Roblox is in front. An answer is accepted when the turn passes to the opponent or the board collapses to its ending, and it is then stored as used. A word you enter by hand on your turn is stored too, once the opponent's starting prompt confirms it.

A stopped typing worker releases its stale prompt latch after a short recovery interval. A stable complete row can also correct a phase inferred from a partial earlier read, so those states do not leave **YOUR TURN** without choices indefinitely. Ordinary confirmed prompts still start without an added opening delay.

Interrupted-input recovery counts the letters actually visible or already sent, rather than the length of the planned answer. It waits for fresh captures after deletion and limits repeated erase batches. If Backspace leaves a short row unchanged twice, that row is rechecked as the current prompt; a longer row is continued with the fewest edits from its visible letters. Delayed captures of earlier keystrokes cannot confirm a new prompt, and corrections stop when paused, cancelled, or Roblox loses focus.

The red "Already used!" banner under the table means the answer was used before. It is recorded, and the nearest unused answer is reached with the fewest keys rather than retyping: for `ism`, `ismailisms` becomes `ismailism` with one Backspace; for `ines`, `inestimableness` becomes `inestimable` by deleting `ness`. The same answer is never retyped. If nothing happens after Enter, Enter is pressed once more (nothing is retyped); if the answer still is not accepted, it is excluded and the nearest other answer is edited in the same way. After three refusals in one turn the input is cleared and a fresh answer is typed. Ordinary focus interruptions keep the script armed and recover automatically when your turn is readable again. New prompts release stale retry latches, and a failed recognition frame does not stop capture. Roblox may use different acceptance or filtering rules from the local dictionary.

Capture, recognition, focusing, and key delivery still take processing time; OCR cannot guarantee perfect recognition on every screen. Censored or covered letters cannot always be reconstructed. For an experience you control, its scripts can expose turn, prefix, and accepted-word events to a companion service through [Roblox HttpService](https://create.roblox.com/docs/cloud-services/http-service). Roblox's [Open Cloud APIs](https://create.roblox.com/docs/cloud) do not provide another experience's live client GUI or uncensored word stream. Displayed player text must still follow [Roblox text filtering](https://create.roblox.com/docs/ui/text-filtering).

## Platform setup

**macOS:** Allow Screen Recording and Accessibility for the Python/Terminal host running the app. If keyboard permission is missing, **ENABLE TYPING** opens Accessibility settings and requests access. Enable the host shown by macOS; detection resumes once access becomes available. If macOS still reports the old permission state, restart the host and app. The native panel stays available across Spaces and alongside fullscreen Roblox. Capture uses `llcap.dylib` and the panel uses `llpanel`; both are universal binaries for Apple Silicon and Intel, targeting macOS 11 or newer. On macOS 12.3 and newer, capture streams through ScreenCaptureKit: each frame carries its number and the time it was on screen, so an unchanged picture is not read twice and the final-word check knows how old every frame is. Key events carry the intended character, so `-`, `'` and letters come out right on keyboard layouts other than US. Reading the tiles and the turn line is done in Python, so it is the same reader as on Windows and Linux. After changing a helper's source, rebuild it with Xcode command line tools:

```bash
clang -fobjc-arc -O2 -framework Foundation -framework AppKit -o autotype/llpanel autotype/panel.m
clang -fobjc-arc -O2 -dynamiclib -arch arm64 -arch x86_64 -mmacosx-version-min=11.0 -framework Foundation -framework AppKit -framework CoreGraphics -framework CoreMedia -framework CoreVideo -framework Accelerate -weak_framework ScreenCaptureKit -o autotype/llcap.dylib autotype/llcap.m
```

**Windows:** Use Python from python.org, including tkinter, and install the requirements above. Window/process discovery and input use the Windows APIs with support for 64-bit handles and display scaling. Hyphens and apostrophes use the foreground game's keyboard layout, including Shift and Ctrl/Alt modifiers where required; dead-key apostrophes use literal Unicode input. Capture uses the game window's client area. The Tk panel stays on top in normal and borderless fullscreen windows; exclusive fullscreen behavior depends on Windows and the game's rendering mode.

**Linux:** Requires an X11 session, a working Roblox-compatible player, tkinter, `libX11`, and `libXtst`. For Debian/Ubuntu:

```bash
sudo apt install python3-tk libx11-6 libxtst6
```

Native Wayland capture/input is not supported. The app reports unavailable capture instead of silently pretending to work without an accessible display.

X11 punctuation is mapped in the active keyboard layout group, including Shift and AltGr levels. A missing mapping is reported as an input error rather than sending the wrong character.

Letter and username recognition is the same on every OS. The entire captured window is searched for prompt tiles, including the top edge. Glyphs are compared in upright, rotated 180°, horizontally mirrored, and vertically flipped orientations against crops of the game's own tiles, and the turn line is matched against real header glyphs plus Roblox's Montserrat Black font. Templates are in `autotype/glyphs.bin` (rebuild with `python3 -m autotype.glyphs` when Roblox is installed). No cloud OCR, Tesseract, screenshot history, or large local model is required. Pillow and NumPy are included in `requirements-autotype.txt`.

Captures are scaled proportionally to at most 1600 pixels per dimension. The capture pipeline processes one frame at a time; stale duplicate frames may be dropped from the bounded queue so controls and new prompts keep moving. Letter caches are also bounded.

High-performance word-bubble templates are bundled in `autotype/bubble_glyphs.npz`; rebuilding them with `python3 -m autotype.fast_reader` requires Roblox's fonts, but normal use does not.

## Checks

```bash
python3 -m unittest discover -s autotype -p 'test_*.py'
python3 -m unittest test_dyoe2
```

These cover turn edges, manual identity correction, acceptance during submission, full and clipped opponent words, trap exhaustion and hand-over counts, punctuation traps, the turn clock and "Already used!" banner on supplied screenshots, minimal-edit alternatives, immediate Enter, human typing plans, spam hybrid order, pause, phase rules, small tiles for long words, missed Enter, reversed prefixes, self-solves, cancel ordering, stale completions, missed opponent turns, and capture recovery. The clock digit templates are in `autotype/timer_glyphs.npz` (rebuild with `python3 -m autotype.timer` when Roblox is installed). A real in-match test on each target operating system is still needed to confirm its screen permissions, game font/layout, input delivery, and fullscreen behavior.
