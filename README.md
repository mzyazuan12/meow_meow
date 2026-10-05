# Last Letter autotyper

Reads the Roblox Last Letter board, tracks accepted words for the current game, and types only the ending after the supplied prefix.

## Run

Use Python 3.9 or newer with tkinter. From this folder:

```bash
python3 -m pip install -r requirements-autotype.txt
python3 autotype_app.pyw
```

On Windows, use `py` in place of `python3` if needed. Keep `autotype/`, `dyoe2_engine.py`, `dict (4).txt`, and `data/` beside the app.

Open Roblox to Last Letter. Enter your username in **YOU**, or press **It's your turn?** while the game is asking you for a word. The button adopts the username currently read from the game and immediately checks the current prompt. Username edits also take effect immediately. Your identity is kept only until the app closes; every launch starts with a blank YOU field.

The app arms when its dictionary and the Roblox player are available. **ARMED** toggles typing off. If Roblox disappears, typing stops and the app shows **ROBLOX ISN'T AVAILABLE**. If the process exists but its window cannot be captured, it shows **ROBLOX ISN'T VISIBLE**. Browser pages and Roblox Studio do not count as the player.

Choose **CASUAL**, **PRO**, or **SPAM**. In SPAM, enter comma- or space-separated endings such as `ing, ary, ness`. This uses DYOE2's hybrid selection: shortest available word for each requested ending in order, then the usual trap priorities if those endings have no available word. Accepted words are excluded from later choices. Mode and spam endings are remembered; usernames and the current game's used words are not.

Press **NEW GAME** at the start of a different match to clear used words. Opponent readings are retained through blank/incomplete frames and checked against the opponent's starting prefix and your next prefix. A uniquely supported completion can recover `mho` as `mhorr` when the next prefix is `r`. Ambiguous completions are reported without adding a guessed word. Rejected attempts are excluded separately from accepted words.

Typing uses the same rhythm, pauses, nearby-key mistakes, and corrections as the bots in `last-dletter`, with no first-key lead-in. Two matching complete board reads confirm a prompt, replacing the previous fixed settling delay. Capture, recognition, focusing, and key delivery still take processing time; OCR cannot guarantee perfect recognition on every screen.

## Platform setup

**macOS:** Allow Screen Recording and Accessibility for the Python/Terminal host running the app. The native panel stays available across Spaces and alongside fullscreen Roblox. Capture uses `llcap.dylib` and the panel uses `llpanel`; both are universal binaries for Apple Silicon and Intel, targeting macOS 11 or newer. Reading the tiles and the turn line is done in Python, so it is the same reader as on Windows and Linux. After changing a helper's source, rebuild it with Xcode command line tools:

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
python3 -m unittest autotype.test_autotype autotype.test_regressions autotype.test_ocr
```

These cover turn edges, manual identity correction, acceptance during submission, full and clipped opponent words, retries, spam selection, cancellation, and generated board images at multiple sizes. A real in-match test on each target operating system is still needed to confirm its screen permissions, game font/layout, input delivery, and fullscreen behavior.
