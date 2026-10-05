# meow_meow

Last Letter autotyper. It reads the Roblox tiles, picks a word, and types the ending.

## Run

From this folder:

```bash
python3 autotype_app.pyw
```

Open Roblox to Last Letter, then press ARM.

## What you need

Python 3.9 or newer, with tkinter. The dictionary, trap lists, and app are already in this repo:

- `autotype_app.pyw`
- `autotype/`
- `dyoe2_engine.py`
- `dict (4).txt`
- `lll-security-audit/traps.txt`
- `lll-security-audit/special-traps.txt`
- `lll-security-audit/traps-not-in-dyoe-no-plural.txt`
- `lll-security-audit/poppi/prefix-solve-groups-3-4-prefixes.txt`

Install Pillow. Windows and Linux need it to read letters. Mac uses it only if the bundled reader is missing.

```bash
pip install pillow
```

Mac also needs Screen Recording and Accessibility permission for Terminal or Python. The `autotype/llpanel`, `autotype/llwatch`, and `autotype/llcap.dylib` files are built for Apple Silicon. On an Intel Mac, rebuild them with Xcode command line tools:

```bash
clang -fobjc-arc -O2 -framework Foundation -framework AppKit -framework Vision -framework CoreGraphics -o autotype/llwatch autotype/llwatch.m
clang -fobjc-arc -O2 -framework Foundation -framework AppKit -o autotype/llpanel autotype/panel.m
clang -fobjc-arc -O2 -dynamiclib -framework Foundation -framework AppKit -framework CoreGraphics -o autotype/llcap.dylib autotype/llcap.m
```

Linux also needs the X11 libraries:

```bash
sudo apt install python3-tk libx11-6 libxtst6
```

Windows needs the Python installer from python.org, which includes tkinter, plus Pillow. No compiler.
