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

Choose **CASUAL**, **PRO**, or **SPAM**. In SPAM, enter comma- or space-separated endings such as `ing, ary, ness`. This uses DYOE2's hybrid selection: shortest available word for each requested ending in order, then the usual trap priorities if those endings have no available word. Accepted words are excluded from later choices. Mode and spam endings are remembered; usernames and the current game's used words are not.

Press **NEW GAME** at the start of a different match to clear used words and shuffle trap priorities within DYOE2's source tiers. The phase follows the actual prefix length: three letters means phase 3; four means phase 4. With more than five used words and a shorter prefix, selection can use 2-, 3-, and 4-letter traps. Opponent readings are retained through blank/incomplete frames and checked against the opponent's starting prefix and your next prefix. A uniquely supported completion can recover `mho` as `mhorr` when the next prefix is `r`. Hyphens and apostrophes are preserved. Ambiguous completions are reported without adding a guessed word. Rejected attempts are excluded separately from accepted words.

Typing uses the rhythm and nearby-key corrections from the bots in `last-dletter`, with a faster pace, shorter final pause, and no first-key lead-in. Correction keys are held long enough for the game to receive them. Occasional early Enter attempts are allowed only for a clearly read trial absent from the local dictionary, with at most two per word. Most words have none. Final Enter requires two fresh readings of every letter of the exact intended dictionary word and its full tile count; matching letter evidence can be combined across frames with unread tiles. The word must also be unused and not rejected.

Corrections confirm the cleared starting prefix in two fresh captures before retyping. Dropped Backspaces trigger another deletion of the remaining suffix, rather than appending a second word. Ordinary focus interruptions keep the script armed and recover automatically when your turn is readable again. If a long answer remains unreadable or two repairs fail, the script clears it and tries a shorter dictionary answer for that prefix. These unreadable answers are tracked separately from rejected and accepted words, and reset with **NEW GAME**. A completed word that remains on your turn gets another Enter after fresh confirmation, without retyping it. If three Enter attempts get no acceptance, the attempt is excluded and another answer is selected. New prompts release stale retry latches, and a failed recognition frame does not stop capture. Roblox may use different acceptance or filtering rules from the local dictionary.

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

Letter and username recognition is the same on every OS. Prompt tiles are matched against crops of the game's own tiles, and the turn line is matched against real header glyphs plus Roblox's Montserrat Black font. Templates are in `autotype/glyphs.bin` (rebuild with `python3 -m autotype.glyphs` when Roblox is installed). No cloud OCR, Tesseract, screenshot history, or large local model is required. Pillow and NumPy are included in `requirements-autotype.txt`.

Captures are scaled proportionally to at most 1600 pixels per dimension. The capture pipeline processes one frame at a time, and queues and letter caches are bounded so that large displays do not accumulate full-screen image copies.

## Checks

```bash
python3 -m unittest autotype.test_autotype autotype.test_regressions autotype.test_ocr autotype.test_live_fixes
```

These cover turn edges, manual identity correction, acceptance during submission, full and clipped opponent words, retries, spam selection, pause, phase rules, supplied screenshots at multiple sizes, small tiles for long words, dropped correction and deletion keys, missed Enter, unreadable-word fallback, stale completions, missed opponent turns, and capture recovery. A real in-match test on each target operating system is still needed to confirm its screen permissions, game font/layout, input delivery, and fullscreen behavior.
