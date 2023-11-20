# MTG
Magic The Gathering - my various personal stuff

## Deck Builder Assistant

To install it, follow these steps.

1. create a python virtual environment: `python3 -m venv /path/to/new/venv`
2. activate it: `. /path/to/new/venv/bin/activate`
3. install dependencies: `pip install networkx termcolor sixel`

To run the program, use the python virtual environment: `python deck_builder_assistant.py`

Digest of its help command: `python deck_builder_assistant.py -h`

```
(venv) you@host:/somewhere/MTG$ python deck_builder_assistant.py -h
usage: deck_builder_assistant.py [-h] [-c [COMBO ...]] [-l] commander_name [deck_path]

Generate a deck base, and make suggestion for an existing deck

positional arguments:
  commander_name
  deck_path             an existing deck

options:
  -h, --help            show this help message and exit
  -c [COMBO ...], --combo [COMBO ...]
                        filter combos that match the specified combo effect (regex friendly)
  -l, --list-combos-effects
                        list combos effects

Enjoy !
```

This is going to output many combos and cards lists organized by features. Those are suggestions as
a base deck. Nothing is mandatory. You do what you want. The goal is for you to filter down that
huge list (~ 1000 cards often) to a usable 99 cards EDH deck.

Tips: pipe the program by forcing terminal size and colors like the following (replace `TERM_COLS`)

```
$ TERM_COLS=190 FORCE_COLOR=1 python deck_builder_assistant.py ...  2>&1 | less -R
```

Roadmap (that should happen between few days and few years):

* Implements rules\_0 presets
* Export the result as an HTML page allowing to easily create a deck list out of it
* Implements existing deck stats and suggestions
