# Last Letter autotyper

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

Choose **CASUAL**, **PRO**, or **SPAM**. In SPAM, enter bracket-, comma-, or space-separated endings such as `[ing][ary][ness]` or `ing, ary, ness`. Requested endings join the mode’s trap candidates. Selection prefers eligible traps with the fewest remaining dictionary solves after the selected word is used. On most turns, traps without a simple `s`/`es` completion take priority; on about 20% of subsequent turns, plural traps compete equally on solve count. If only plural traps are available they remain usable. Traps that still have an unused self-solve are excluded from trap priority. After eligible traps, selection uses DYOE cancel words (words outside the two largest next-letter groups), then remaining answers. Accepted words are excluded from later choices. Mode and spam endings are remembered; usernames and the current game's used words are not.

Press **NEW GAME** at the start of a different match to clear used words and shuffle trap priorities within DYOE2's source tiers. The phase follows the actual prefix length: three letters means phase 3; four means phase 4. With more than five used words and a shorter prefix, selection can use 2-, 3-, and 4-letter traps. Opponent readings, including a word already visible in the first frame confirming our submission, are retained through blank/incomplete frames and checked against the opponent's starting prefix and your next prefix. A uniquely supported completion can recover `mho` as `mhorr` when the next prefix is `r`. Hyphens and apostrophes are preserved and allowed for typing in every autotyper mode. If a prefix has no available extension and is not itself a dictionary word, its reversal is tried. An unused self-solvable prompt of at least two letters is chosen about one quarter of the time (or whenever there is no extension); it sends Enter with no extra letters. Single-letter dictionary entries never trigger Enter-only submissions. Ambiguous completions are reported without adding a guessed word. Rejected attempts are excluded separately from accepted words.

Typing uses the rhythm and nearby-key corrections from the bots in `last-dletter`, with a faster pace, shorter final pause, and no first-key lead-in. Each word chooses a fresh rhythm and speed curve, with additional variation between individual keystrokes and occasional deletion and retyping of a short stretch. The longest dictionary word takes at least nine seconds in the typing plan, with no added pause before the first key. Correction keys are held long enough for the game to receive them. Occasional early Enter attempts are allowed only for a clearly read trial absent from the local dictionary, with at most one per word, near the end of an apparent typo. Most words have none. Final Enter normally requires two fresh readings of every letter and the full tile count; matching evidence is combined across frames and survives intervening blank captures. A clipped row cannot count as a complete answer. For long words, a stable visible slice with at least 70% readable letters can support Enter when it fits one place in the planned word and every planned key was sent. After 1.2 seconds, a complete row with some unreadable slots can instead be resolved by a unique dictionary completion when at least 70% of the letters have two observations and the delivered suffix length matches. The word must also be unused and not rejected.

Corrections confirm the cleared starting prefix in two fresh captures before retyping. Dropped Backspaces trigger another deletion of the remaining suffix, rather than appending a second word. Reversed prefixes stay normalized during deletion checks too. Repeated verified typing errors continue to repair the same answer with a longer delay after the second repair; they no longer leave the turn permanently latched. Ordinary focus interruptions keep the script armed and recover automatically when your turn is readable again. An unreadable long answer is preserved while recognition continues; it is not discarded in favor of a shorter answer. Only a stable, complete contradictory reading triggers repair. Fully covered or clipped answers can still require intervention. A completed word that remains on your turn for at least 1.25 seconds gets one more Enter after fresh confirmation, without retyping it. If two Enter attempts get no acceptance, the attempt is excluded and another answer is selected. New prompts release stale retry latches, and a failed recognition frame does not stop capture. Roblox may use different acceptance or filtering rules from the local dictionary.

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
python3 -m unittest autotype.test_autotype autotype.test_regressions autotype.test_ocr autotype.test_live_fixes autotype.test_requested_fixes test_dyoe2
```

These cover turn edges, manual identity correction, acceptance during submission, full and clipped opponent words, retries, spam selection, pause, phase rules, supplied screenshots at multiple sizes, small tiles for long words, dropped correction and deletion keys, missed Enter, long-word preservation, reversed prefixes, self-solves, cancel ordering, stale completions, missed opponent turns, and capture recovery. A real in-match test on each target operating system is still needed to confirm its screen permissions, game font/layout, input delivery, and fullscreen behavior.
