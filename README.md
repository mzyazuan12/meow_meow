# Last Letter autotyper v4.5

Reads the Roblox Last Letter board, tracks accepted words for the current game, and types only the ending after the supplied prefix.

## Run

Use Python 3.9 or newer with tkinter. From this folder:

```bash
python3 -m pip install -r requirements-autotype.txt
python3 autotype_app.pyw
```

On Windows, use `py` in place of `python3` if needed. Keep `autotype/`, `dyoe2_engine.py`, `dict (4).txt`, and `data/` beside the app.

Open Roblox to Last Letter. Enter your username in **YOU**, or press **It's your turn?** once while the game is asking you for a word. The button adopts the readable username and starts the current prompt. Once identified, your turns start automatically; split usernames and temporarily unreadable headers do not require another click. If the header is covered or outside the capture, the button confirms this turn manually. Username edits also take effect immediately. Your identity is kept only until the app closes; every launch starts with a blank YOU field. Choices refresh for each readable prefix while turn detection is uncertain.

The app arms when its dictionary and the Roblox player are available. **ARMED** toggles typing off. If Roblox disappears, typing stops and the app shows **ROBLOX ISN'T AVAILABLE**. If the process exists but its window cannot be captured, it shows **ROBLOX ISN'T VISIBLE**. Browser pages and Roblox Studio do not count as the player.

**PAUSE** immediately cancels typing, pending Enter, and corrections, and suspends capture and game processing. **RESUME** reads the current turn again and clears an interrupted suffix before restarting if that same turn is still yours. Used words and username stay in memory. Escape also toggles pause when the Tk panel has focus. Only **NEW GAME** clears used words during a running session.

Choose **CASUAL**, **PRO**, or **SPAM**. CASUAL and PRO use DYOE2's trap sources (casual prefixes; or special, no-plural and `traps.txt` for pro), but not their fixed order. The next player's prompt is as long as yours, so traps of that length come first, and one letter longer is a hedge for a stage change; a one-letter prompt can only hedge with two-letter traps. Among traps, the one with the fewest solves left wins. Solves left is the smaller of the unused dictionary answers and the dictionary total minus the times this game the prefix was already handed to an opponent, so a prefix with two solves is never given a third time even if those answers were never read. Each earlier hand-over also lowers its priority, so other deadly prefixes get used. The prefix handed over is the opponent's actual starting prompt when it is seen. Ties go to the trap whose shortest solve is longest. A trap that is itself an unused word (answered by pressing Enter) is not a trap, and a prefix starting or ending with `-` or `'` is never one. In PRO, traps containing `-` or `'` rank higher. A trap whose answer is just the prompt plus `s`/`es` ranks lower. After traps come DYOE cancel words (casual), then the remaining answers.

In SPAM, enter bracket-, comma-, or space-separated endings such as `[ing][ary][ness]` or `ing, ary, ness`. SPAM is DYOE2's phase 5 hybrid: words ending with the first ending (shortest first), then the next ending, then the 4-, 3- and 2-letter traps, then everything else. Accepted words are excluded from later choices. Mode and spam endings are remembered; usernames and the current game's used words are not.

The turn clock under the table is read every frame: the coloured arc gives the fraction of the turn left, and the digits are read when legible. A turn lasts 15, 10, 7, 5 or 3 seconds depending on the stage; the stage is learned from the digits or from how fast the arc shrinks. Answers are limited to what can be typed at a human pace in the time left (about 0.18 s per letter), shorter answers are preferred under six seconds, and phase 1 answers are at most 14 typed letters.

Press **NEW GAME** at the start of a different match to clear used words and hand-over counts. The phase follows the actual prefix length: three letters means phase 3; four means phase 4. Opponent readings, including a word already visible in the first frame confirming our submission, are retained through blank/incomplete frames and checked against the opponent's starting prefix and your next prefix. A uniquely supported completion can recover `mho` as `mhorr` when the next prefix is `r`. Hyphens and apostrophes are preserved and allowed for typing in every autotyper mode. If a prefix has no available extension and is not itself a dictionary word, its reversal is tried. An unused self-solvable prompt of at least two letters is chosen about one quarter of the time (or whenever there is no extension); it sends Enter with no extra letters. Single-letter dictionary entries never trigger Enter-only submissions. Ambiguous completions are reported without adding a guessed word. Rejected attempts are excluded separately from accepted words.

Typing keeps a human pace (about 0.09–0.15 s per letter, varied per key, never faster than about 13 keys a second). With spare time it sometimes fidgets first — for `ism`, typing and erasing things like `ismsm`, `ismdj`, `ismd` — and sometimes makes a nearby-key typo and corrects it, or presses Enter one to three letters early on an unfinished non-word and carries on. These extras are dropped when time is short, and the pace is raised only as far as needed to finish before the clock runs out.

Enter is pressed as soon as the last letter is typed. The keystrokes are the record of what was typed; the board is not read first, so long answers with tiny tiles are entered and stored like any other. Enter is only sent while Roblox is in front. An answer is accepted when the turn passes to the opponent or the board collapses to its ending, and it is then stored as used. A word you enter by hand on your turn is stored too, once the opponent's starting prompt confirms it.

The red "Already used!" banner under the table means the answer was used before. It is recorded, and the nearest unused answer is reached with the fewest keys rather than retyping: for `ism`, `ismailisms` becomes `ismailism` with one Backspace; for `ines`, `inestimableness` becomes `inestimable` by deleting `ness`. The same answer is never retyped. If nothing happens after Enter, Enter is pressed once more (nothing is retyped); if the answer still is not accepted, it is excluded and the nearest other answer is edited in the same way. After three refusals in one turn the input is cleared and a fresh answer is typed. Ordinary focus interruptions keep the script armed and recover automatically when your turn is readable again. New prompts release stale retry latches, and a failed recognition frame does not stop capture. Roblox may use different acceptance or filtering rules from the local dictionary.

Capture, recognition, focusing, and key delivery still take processing time; OCR cannot guarantee perfect recognition on every screen. Censored or covered letters cannot always be reconstructed. For an experience you control, its scripts can expose turn, prefix, and accepted-word events to a companion service through [Roblox HttpService](https://create.roblox.com/docs/cloud-services/http-service). Roblox's [Open Cloud APIs](https://create.roblox.com/docs/cloud) do not provide another experience's live client GUI or uncensored word stream. Displayed player text must still follow [Roblox text filtering](https://create.roblox.com/docs/ui/text-filtering).

## Platform setup

**macOS:** Allow Screen Recording and Accessibility for the Python/Terminal host running the app. If keyboard permission is missing, **ENABLE TYPING** opens Accessibility settings and requests access. Enable the host shown by macOS; detection resumes once access becomes available. If macOS still reports the old permission state, restart the host and app. The native panel stays available across Spaces and alongside fullscreen Roblox. Capture uses `llcap.dylib` and the panel uses `llpanel`; both are universal binaries for Apple Silicon and Intel, targeting macOS 11 or newer. Reading the tiles and the turn line is done in Python, so it is the same reader as on Windows and Linux. After changing a helper's source, rebuild it with Xcode command line tools:

```bash
clang -fobjc-arc -O2 -framework Foundation -framework AppKit -o autotype/llpanel autotype/panel.m
clang -fobjc-arc -O2 -dynamiclib -framework Foundation -framework AppKit -framework CoreGraphics -o autotype/llcap.dylib autotype/llcap.m
```

**Windows:** Use Python from python.org, including tkinter, and install the requirements above. Window/process discovery and input use the Windows APIs with support for 64-bit handles and display scaling. Capture uses the game window's client area. The Tk panel stays on top in normal and borderless fullscreen windows; exclusive fullscreen behavior depends on Windows and the game's rendering mode.

**Linux:** Requires an X11 session, a working Roblox-compatible player, tkinter, `libX11`, and `libXtst`. For Debian/Ubuntu:

```bash
sudo apt install python3-tk libx11-6 libxtst6
```

Native Wayland capture/input is not supported. The app reports unavailable capture instead of silently pretending to work without an accessible display.

Letter and username recognition is the same on every OS. The entire captured window is searched for prompt tiles, including the top edge. Glyphs are compared in upright, rotated 180°, horizontally mirrored, and vertically flipped orientations against crops of the game's own tiles, and the turn line is matched against real header glyphs plus Roblox's Montserrat Black font. Templates are in `autotype/glyphs.bin` (rebuild with `python3 -m autotype.glyphs` when Roblox is installed). No cloud OCR, Tesseract, screenshot history, or large local model is required. Pillow and NumPy are included in `requirements-autotype.txt`.

Captures are scaled proportionally to at most 1600 pixels per dimension. The capture pipeline processes one frame at a time; stale duplicate frames may be dropped from the bounded queue so controls and new prompts keep moving. Letter caches are also bounded.

## Checks

```bash
python3 -m unittest autotype.test_autotype autotype.test_regressions autotype.test_ocr autotype.test_live_fixes autotype.test_requested_fixes autotype.test_turn_fixes test_dyoe2
```

These cover turn edges, manual identity correction, acceptance during submission, full and clipped opponent words, trap exhaustion and hand-over counts, punctuation traps, the turn clock and "Already used!" banner on supplied screenshots, minimal-edit alternatives, immediate Enter, human typing plans, spam hybrid order, pause, phase rules, small tiles for long words, missed Enter, reversed prefixes, self-solves, cancel ordering, stale completions, missed opponent turns, and capture recovery. The clock digit templates are in `autotype/timer_glyphs.npz` (rebuild with `python3 -m autotype.timer` when Roblox is installed). A real in-match test on each target operating system is still needed to confirm its screen permissions, game font/layout, input delivery, and fullscreen behavior.
