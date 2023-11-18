#!/usr/bin/env python3
"""
Deck builder using the Scryfall JSON cards collection
"""

# pylint: disable=line-too-long

import os
import sys
import json
import re
import csv
from argparse import ArgumentParser
from urllib.request import urlopen,urlretrieve
from pathlib import Path
from math import comb, prod
from datetime import datetime
from os.path import join as pjoin
# import pprint
import networkx as nx
from sixel import sixel, converter, cellsize
from termcolor import colored, cprint

# user input
# TODO extract those from the commander's card infos
COMMANDER_FEATURES_REGEXES = [
#    r'(opponent|target player|owner).*(lose|have lost).*life',
#    r'(you|target player|owner).*(gain|have gained).*life',
#    r'(you|target player|owner).*(draw|have draw)',
]
COMMANDER_FEATURES_EXCLUDE_REGEX = r'('+('|'.join([
    '[Ss]acrifice|[Ee]xile|[Tt]ransform|[Dd]iscard',
#    '^\\s*((First strike|Flying|Skulk|Deathtouch)( \\([^)]+\\))?)?\\s*Lifelink \\([^)]+\\)\\s*$'
]))+')'

# Add a parameter to express if a 1-drop at turn 1 is important,
# that will exclude land that are not usable at turn 1 or colorless at turn 1
TURN_1_WANTS_1_DROP = False

# Add a parameter to express if you expect to fill your graveyard pretty fast (mill),
# that will include card that relies on other cards being in the graveyard
FILL_GRAVEYARD_FAST = False

# constants
TERM_COLS, TERM_LINES = os.getenv('TERM_COLS', None), os.getenv('TERM_LINES', None)

SCRYFALL_API_BULK_URL = 'https://api.scryfall.com/bulk-data'

# see https://github.com/SpaceCowMedia/commander-spellbook-site/blob/main/scripts/download-data/get-google-sheets-data.ts
# see https://github.com/SpaceCowMedia/commander-spellbook-site/blob/main/scripts/download-data/get-combo-changelog.ts
# see https://github.com/SpaceCowMedia/commander-spellbook-site/blob/main/scripts/download-data/get-edhrec-combo-data.ts
# see https://github.com/SpaceCowMedia/commander-spellbook-site/blob/main/scripts/download-data/get-backend-data.ts
COMMANDERSPELLBOOK_COMBOS_SHEET_DB_URL = 'https://sheets.googleapis.com/v4/spreadsheets/1KqyDRZRCgy8YgMFnY0tHSw_3jC99Z0zFvJrPbfm66vA/values:batchGet?ranges=combos!A2:Q&key=AIzaSyBD_rcme5Ff37Evxa4eW5BFQZkmTbgpHew'
COMMANDERSPELLBOOK_COMBOS_DB_URL = 'https://commanderspellbook.com/api/combo-data.json'
COMMANDERSPELLBOOK_VARIANTS_DB_URL = 'https://spellbook-prod.s3.us-east-2.amazonaws.com/variants.json'
COMMANDERSPELLBOOK_VARIANTS_IDMAP_URL = 'https://spellbook-prod.s3.us-east-2.amazonaws.com/variant_id_map.json'
COMMANDERSPELLBOOK_PROPERTIES = {
  'c': 'Cards',
  'i': 'Color Identity',
  'p': 'Prerequisites',
  's': 'Steps',
  'r': 'Results',
  # adds
  'd': 'Identifier',
  't': 'Other Prerequisites',
}

XMAGE_COMMANDER_BANNED_LIST_URL = 'https://github.com/magefree/mage/raw/master/Mage.Server.Plugins/Mage.Deck.Constructed/src/mage/deck/Commander.java'
XMAGE_DUELCOMMANDER_BANNED_LIST_URL = 'https://github.com/magefree/mage/raw/master/Mage.Server.Plugins/Mage.Deck.Constructed/src/mage/deck/DuelCommander.java'
XMAGE_BANNED_LINE_REGEX = r'^\s*banned(Commander)?\.add\("(?P<name>[^"]+)"\);\s*$'
XMAGE_COMMANDER_BANNED_LIST_FILE = "/tmp/xmage-Commander-banned-list.txt"
XMAGE_DUELCOMMANDER_BANNED_LIST_FILE = "/tmp/xmage-DuelCommander-banned-list.txt"
XMAGE_COMMANDER_CARDS_BANNED = []

ALL_COLORS = set(['R', 'G', 'U', 'B', 'W'])
COLOR_NAME = {
    'B': 'dark_grey',
    'U': 'light_blue',
    'W': 'white',
    'G': 'light_green',
    'R': 'red',
    'M': 'yellow',
    'C': 'light_yellow',
    'X': 'light_yellow',
    'Y': 'light_yellow',
    'Z': 'light_yellow',
    'TK': 'light_yellow',
    'T': 'magenta',
    'Q': 'magenta',
    'E': 'cyan',
    'PW': 'light_yellow',
    'CHAOS': 'light_yellow',
    'A': 'light_yellow',
    '½': 'light_yellow',
    '∞': 'light_yellow',
    'P': 'light_yellow',
    'HW': 'white',
    'HR': 'red',
    'S': 'light_yellow'}
ALL_COLORS_COUNT = len(ALL_COLORS)
COLOR_TO_LAND = {
    'G': 'Forest',
    'R': 'Mountain',
    'W': 'Plains',
    'U': 'Island',
    'B': 'Swamp'}
COMMANDER_KEYWORDS = []
DRAW_CARDS_REGEX = [
    r'(when|whenever|instead) [^.]+ (,|you [^.]+ (and )?)draw (a card|your)',
    'put (that card|one pile) into your hand',
    '([:,.] )?(you( may)? |then |target player |and )?draws? \\w+ cards?( for each)?',
    '(then )?draws? cards equal']
DRAW_CARDS_EXCLUDE_REGEX = r'toto'
TUTOR_CARDS_REGEX = [
    (r"search(es)? [^.]+ cards?[, ][^.]* puts? (it|that card|those cards|them) "+
     r"(into (your|that player's) (hand|graveyard)|onto the battlefield|on top|\w+ from the top)"),
    r'(search|exile) [^.]+ cards?.*\. (you may )?put (one|that card) (into your hand|onto the battlefield)',
    r'search [^.]+ card\. [^.]+ put it onto the battlefield',
    r"search [^.]+ cards?.*\. you may cast that card without paying its mana cost",
    r'search [^.]+ cards? and exile it.*. you may [^.]+ play that card',
    r'search [^.]+ cards [^.]+ and exile them.*, then draws a card for each card exiled',
    r'reveal cards from [^.]*your library[^.]*, then put that card into your hand',
    r'search [^.]+ cards?.* put (that [^.]*card onto the battlefield|put it into your hand)',
]
TUTOR_CARDS_JOIN_TEXTS_REGEX = [
    r"search [^.]+ cards?, exile them[,. ].*\. (draw a card|put that card into its owner's hand)",
    r'search [^.]+ cards?, exile them[,. ].* you may cast a spell [^.]+ from among cards exiled',
]
TUTOR_CARDS_EXCLUDE_REGEX = r'(cards? named|same name)'
TUTOR_GENERIC_EXCLUDE_REGEX = r'('+('|'.join([
    'mercenary', 'cleric', 'dinosaur', 'rebel', 'squadron', 'trap', 'sliver', 'goblin', 'pirate',
    'vampire', 'rune', 'vehicle', 'demon', 'faerie', 'myr', 'merfolk', 'curse', 'ninja',
    'assembly-worker', 'spirit']))+')'
REMOVAL_CARDS_REGEX = [
    r'(destroy|remove|exile|put that card in the graveyard)'
]
REMOVAL_CARDS_EXCLUDE_REGEX = r'('+('|'.join([
    "exile target player's graveyard",
    'remove any number of [^.]*counter',
    'counters? removed this way',
    'remove (x|that many)? [^.]*counters',
    'exile [^.]+ you control',
    'exile this permanent',
    r'return [^.+] card from your graveyard.* exile it',
    "exile target card from defending player's graveyard",
    'look at [^.]+ your library[, ].*exile (one|that card)',
    'rather than cast this card from your hand, pay [^.]+ and exile it',
    'remove [^.]+ from combat',
    'remove [^.]+ counters? from',
    r'exile [^.]+\. at the beginning of the next end step, return it',
    'exile [^]*, then return it to the battlefield transformed',
    r'you may exile [^.]+\. If you do, return them',
    "exiles? [^.]+ (of|from) (your|a|their|target player's) (hand|graveyard|library)",
    'you may cast this card from exile',
    'search [.^]+ library [^.]+ cards? and exile (it|them)',
    'if [^.]+ would die, exile it instead',
    'if [^.]+ would be put into your graveyard, exile it instead',
    "this effect doesn't remove",
    'look at [^.]+ library, then exile',
    'remove [^.]+ from it',
    'exile it instead of putting it into',
    r'destroy target \w+ you own',
    'when this spell card is put into a graveyard after resolving, exile it',
]))+')'

COMMANDER_COLOR_IDENTITY = set([])
COMMANDER_COLOR_IDENTITY_COUNT = 0
INVALID_COLORS = set([])
LAND_MULTICOLORS_EXCLUDE_REGEX = r'('+('|'.join([
    'you may', 'reveal', 'only', 'gains', 'return', 'create']))+')'
LAND_MULTICOLORS_GENERIC_EXCLUDE_REGEX = r'('+('|'.join([
    'dragon', 'elemental', 'phyrexian', 'time lord', 'alien', 'gates', 'devoid', 'ally', 'pilot',
    'vehicle', 'sliver', 'vampire', 'cleric', 'rogue', 'warrior', 'wizard']))+')'
LAND_BICOLORS_EXCLUDE_REGEX = r'('+('|'.join([
    'you may reveal',
    'this turn',
    'more opponents',
    'depletion',
    'two or (more|fewer) other lands',
    'basic lands']))+')'
LAND_SACRIFICE_SEARCH_REGEX = r'sacrifice.*search.*land'
RAMP_CARDS_REGEX = r'('+('|'.join([
    '(look for |search |play )[^.]+ land',
    'adds? (an additional )?\\{[crgbuw0-9]\\}',
    'adds? [^.]+ to your mana pool',
    'adds? [^.]+ of any color',
    'adds? \\w+ mana',
    '(you may )?adds? an amount of \\{[crgbuw]\\} equal to',
    'that player adds? \\w+ mana of any color they choose',
    ('spells? (you cast )?(of the chosen type |that share a card type with the exiled card )?'+
     'costs? (up to )?\\{\\d+\\} less to cast'),
    'abilities (of creatures (you control )?)?costs? \\{\\d+\\} less to activate',
    'adds? \\w+ additional mana',
    'spells? (you cast)? have (convoke|improvise)',
    'double the amount of [^.]+ mana you have',
    ("(reveal|look at) the top card of your library.*if it's a land card, "+
     "(then |you may )?put (it|that card) onto the battlefield"),
    'look at the top \\w+ cards of your library\\. put \\w+ of them into your hand',
    'reveal a card in your hand, then put that card onto the battlefield',
    'for each \\{[crgbuw]\\} in a cost, you may pay \\d+ life rather than pay that mana',
    'you may [^.]+ untap target [^.]+ land',
    'put (a|up to \\w+) lands? cards? from your hand onto the battlefield',
    'choose [^.]+ land.* untap all tapped permanents of that type that player controls',
    "gain control of a land you don't control",
]))+')'
RAMP_CARDS_EXCLUDE_REGEX = r'('+('|'.join([
    'defending player controls? [^.]+ land',
    'this spell costs \\{\\d+\\} less to cast',
    '\\{\\d+\\}(, \\{t\\})?: add one mana of any color',
    '\\{\\d+\\}(, \\{t\\})?, sacrifice [^:]+: add (one mana of any color|\\{[crgbuw]\\})',
]))+')'
RAMP_CARDS_LAND_FETCH_REGEX = r'search(es)? (your|their) library for .* ' \
        '(land|'+('|'.join(map(lambda c: c.lower()+'s?', COLOR_TO_LAND.values())))+') card'
LAND_CYCLING_REGEX = r'(land ?|'+('|'.join(map(str.lower, COLOR_TO_LAND.values())))+')cycling'
LAND_RECOMMENDED_MULTICOLOR = [
'']
LAND_RECOMMENDED_BICOLORS = [

    # TODO programmatically select those, according to the commander's color
    'Tundra',  # {T}: Add {W} or {U}.
    'Darkwater Catacombs',  # {1}, {T}: Add {U}{B}.
    'Underground Sea',  # {T}: Add {U} or {B}.
    'Skycloud Expanse',  # {1}, {T}: Add {W}{U}.
    'Scrubland',  # {T}: Add {W} or {B}.
    'Glacial Fortress',  # Glacial Fortress enters the battlefield tapped unless you control a Plains or an Island. {T}: Add {W} or {U}.
    'Isolated Chapel',  # Isolated Chapel enters the battlefield tapped unless you control a Plains or a Swamp. {T}: Add {W} or {B}.
    'Drowned Catacomb',  # Drowned Catacomb enters the battlefield tapped unless you control an Island or a Swamp. {T}: Add {U} or {B}.
    ]

# help to colorize abilities and keywords
# see https://mtg.fandom.com/wiki/Keyword_action
KEYWORDS_ACTIONS = [
    # evergreen action
    '[Aa]ctivate', '[Aa]ttach', '[Cc]ast', '[Cc]ounter', '[Cc]reate', '[Dd]estroy', '[Dd]iscard',
    '[Ee]xchange', '[Ee]xile', '[Ff]ight', '[Mm]ill', '[Pp]lay', '[Rr]eveal', '[Ss]acrifice',
    '[Ss]cry', '[Ss]earch', '[Ss]huffle', '[Tt]ap', '[Uu]ntap',
    # former evergreen action
    '[Aa]nte', '[Bb]ury', '[Rr]egenerate',
    # other
    '[Dd]ouble', '[Ff]ateseal', '[Cc]lash', '[Pp]laneswalk', '[Ss]et [Ii]n [Mm]otion', '[Aa]bandon',
    '[Pp]roliferate', '[Tt]ransform', '[Dd]etain', '[Pp]opulate', '[Mm]onstrosity', '[Vv]ote',
    '[Bb]olster', '[Mm]anifest', '[Ss]upport', '[Ii]nvestigate', '[Mm]eld', '[Gg]oad', '[Ee]xert',
    '[Ee]xplore', '[Aa]ssemble', '[Ss]urveil', '[Aa]dapt', '[Aa]mass', '[Ll]earn',
    '[Vv]enture [Ii]nto [Tt]he [Dd]ungeon', '[Cc]onnive', '[Oo]pen [Aa]n [Aa]ttraction',
    '[Rr]oll [Tt]o [Vv]isit [Yy]our [Aa]ttractions', '[Cc]onvert', '[Ii]ncubate',
    '[Tt]he [Rr]ing [Tt]empts [Yy]ou', '[Ff]ace [Aa] [Vv]illainous [Cc]hoice', '[Tt]ime [Tt]ravel',
    '[Dd]iscover']
ACTIONS_REGEX_PART = '('+('|'.join(KEYWORDS_ACTIONS))+')'
# see https://mtg.fandom.com/wiki/Keyword_ability
# see https://mtg.fandom.com/wiki/Evergreen
# see https://mtg.fandom.com/wiki/Deciduous
KEYWORDS_ABILITIES = [
    # evergreen abilities
    '[Dd]eathtouch', '[Dd]efender', '[Dd]ouble [Ss]trike', '[Ee]nchant', '[Ee]quip',
    '[Ff]irst [Ss]trike', '[Ff]lash', '[Ff]lying', '[Hh]aste', '[Hh]exproof', '[Ii]ndestructible',
    '[Ll]ifelink', '[Mm]enace', '[Pp]rotection', '[Rr]each', '[Tt]rample', '[Vv]igilance',
    '[Ww]ard',
    # former evergreen abilities
    '[Bb]anding', '[Ff]ear', '[Ss]hroud', '[Ii]ntimidate', '[Ll]andwalk', '[Pp]rowess',
	# deciduous
    '[Aa]ffinity', '[Cc]ycling', '[Ff]lashback', '[Kk]icker', '[Pp]hasing',
    # other
    '[Rr]ampage', '[Cc]umulative [Uu]pkeep', '[Ff]lanking', '[Bb]uyback', '[Ss]hadow', '[Ee]cho',
    '[Hh]orsemanship', '[Ff]ading', '[Mm]adness', '[Mm]orph', '[Aa]mplify', '[Pp]rovoke',
    '[Ss]torm', '[Ee]ntwine', '[Mm]odular', '[Ss]unburst', '[Bb]ushido', '[Ss]oulshift',
    '[Ss]plice', '[Oo]ffering', '[Nn]injutsu', '[Ee]pic', '[Cc]onvoke', '[Dd]redge', '[Tt]ransmute',
    '[Bb]loodthirst', '[Hh]aunt', '[Rr]eplicate', '[Ff]orecast', '[Gg]raft', '[Rr]ecover',
    '[Rr]ipple', '[Ss]plit [Ss]econd', '[Ss]uspend', '[Vv]anishing', '[Aa]bsorb', '[Aa]ura [Ss]wap',
    '[Dd]elve', '[Ff]ortify', '[Ff]renzy', '[Gg]ravestorm', '[Pp]oisonous', '[Tt]ransfigure',
    '[Cc]hampion', '[Cc]hangeling', '[Ee]voke', '[Hh]ideaway', '[Pp]rowl', '[Rr]einforce',
    '[Cc]onspire', '[Pp]ersist', '[Ww]ither', '[Rr]etrace', '[Dd]evour', '[Ee]xalted', '[Uu]nearth',
    '[Cc]ascade', '[Aa]nnihilator', '[Ll]evel [Uu]p', '[Rr]ebound', '[Tt]otem [Aa]rmor',
    '[Ii]nfect', '[Bb]attle [Cc]ry', '[Ll]iving [Ww]eapon', '[Uu]ndying', '[Mm]iracle',
    '[Ss]oulbond', '[Oo]verload', '[Ss]cavenge', '[Uu]nleash', '[Cc]ipher', '[Ee]volve',
    '[Ee]xtort', '[Ff]use', '[Bb]estow', '[Tt]ribute', '[Dd]ethrone', '[Hh]idden [Aa]genda',
    '[Oo]utlast', '[Dd]ash', '[Ee]xploit', '[Rr]enown', '[Aa]waken', '[Dd]evoid', '[Ii]ngest',
    '[Mm]yriad', '[Ss]urge', '[Ss]kulk', '[Ee]merge', '[Ee]scalate', '[Mm]elee', '[Cc]rew',
    '[Ff]abricate', '[Pp]artner', '[Uu]ndaunted', '[Ii]mprovise', '[Aa]ftermath', '[Ee]mbalm',
    '[Ee]ternalize', '[Aa]fflict', '[Aa]scend', '[Aa]ssist', '[Jj]ump-[Ss]tart', '[Mm]entor',
    '[Aa]fterlife', '[Rr]iot', '[Ss]pectacle', '[Ee]scape', '[Cc]ompanion', '[Mm]utate',
    '[Ee]ncore', '[Bb]oast', '[Ff]oretell', '[Dd]emonstrate', '[Dd]aybound [Aa]nd [Nn]ightbound',
    '[Dd]isturb', '[Dd]ecayed', '[Cc]leave', '[Tt]raining', '[Cc]ompleated', '[Rr]econfigure',
    '[Bb]litz', '[Cc]asualty', '[Ee]nlist', '[Rr]ead [Aa]head', '[Rr]avenous', '[Ss]quad',
    '[Ss]pace [Ss]culptor', '[Vv]isit', '[Pp]rototype', '[Ll]iving [Mm]etal',
    '[Mm]ore [Tt]han [Mm]eets [Tt]he [Ee]ye', '[Ff]or Mirrodin!', '[Tt]oxic', '[Bb]ackup',
    '[Bb]argain', '[Cc]raft']
ABILITIES_REGEX_PART = '('+('|'.join(KEYWORDS_ABILITIES))+')'
# see https://mtg.fandom.com/wiki/Ability_word
ABILITY_WORDS = [
    '[Aa[damant', '[Aa[ddendum', '[Aa[lliance', '[Bb[attalion', '[Bb[loodrush', '[Cc[elebration',
    '[Cc[hannel', '[Cc[hroma', '[Cc[ohort', '[Cc[onstellation', '[Cc[onverge',
    '[Cc[ouncil’s [Dd]ilemma', '[Cc[oven', '[Dd[elirium', '[Dd[escend 4', '[Dd[escend 8',
    '[Dd[omain', '[Ee[minence', '[Ee[nrage', '[Ff[ateful [Hh]our', '[Ff[athomless [Dd]escent',
    '[Ff[erocious', '[Ff[ormidable', '[Gg[randeur', '[Hh[ellbent', '[Hh[eroic', '[Ii[mprint',
    '[Ii[nspired', '[Jj[oin [Ff]orces', '[Kk[inship', '[Ll[andfall', '[Ll[ieutenant',
    '[Mm[agecraft', '[Mm[etalcraft', '[Mm[orbid', '[Pp[ack [Tt]actics', '[Pp[aradox', '[Pp[arley',
    '[Rr[adiance', '[Rr[aid', '[Rr[ally', '[Rr[evolt', '[Ss[ecret [Cc]ouncil',
    '[Ss[pell [Mm]astery', '[Ss[trive', '[Ss[weep', '[Tt[empting [Oo]ffer', '[Tt[hreshold',
    '[Uu[ndergrowth', '[Aa[nd [Ww]ill [Oo]f [Tt]he [Cc]ouncil']
ABILITIES_WORDS_REGEX_PART = '('+('|'.join(ABILITY_WORDS))+')'

# see https://mtg.fandom.com/wiki/Mechanic
MECHANICS = [
    '[Dd]raw',
    '[Ll]ife', # gain or loss or payment
    '[Ww]in',  # the game
]
MECHANICS_REGEX_PART = '('+('|'.join(MECHANICS))+')'

COMMANDER_FEATURES_REGEX = '('+('|'.join(KEYWORDS_ACTIONS + KEYWORDS_ACTIONS + ABILITY_WORDS +
                                         MECHANICS))+')'

COLORIZE_KEYWORD_REGEX_PART = '('+('|'.join(KEYWORDS_ABILITIES + ABILITY_WORDS))+')'

# see https://mtg.fandom.com/wiki/Category:Miscellaneous_mechanics
# TODO: craft some regex to detect each

# Card object example:
#
# {
#   "object": "card",
#   "id": "86bf43b1-8d4e-4759-bb2d-0b2e03ba7012",
#   "oracle_id": "0004ebd0-dfd6-4276-b4a6-de0003e94237",
#   "multiverse_ids": [
#     15862
#   ],
#   "mtgo_id": 15870,
#   "mtgo_foil_id": 15871,
#   "tcgplayer_id": 3094,
#   "cardmarket_id": 3081,
#   "name": "Static Orb",
#   "lang": "en",
#   "released_at": "2001-04-11",
#   "uri": "https://api.scryfall.com/cards/86bf43b1-8d4e-4759-bb2d-0b2e03ba7012",
#   "scryfall_uri": "https://scryfall.com/card/7ed/319/static-orb?utm_source=api",
#   "layout": "normal",
#   "highres_image": true,
#   "image_status": "highres_scan",
#   "image_uris": {
#     "small": "https://cards.scryfall.io/small/front/8/6/86bf43b1-8d4e-4759-bb2d-0b2e03ba7012.jpg?
#     "normal": "https://cards.scryfall.io/normal/front/8/6/86bf43b1-8d4e-4759-bb2d-0b2e03ba7012.jp
#     "large": "https://cards.scryfall.io/large/front/8/6/86bf43b1-8d4e-4759-bb2d-0b2e03ba7012.jpg?
#     "png": "https://cards.scryfall.io/png/front/8/6/86bf43b1-8d4e-4759-bb2d-0b2e03ba7012.png?1562
#     "art_crop": "https://cards.scryfall.io/art_crop/front/8/6/86bf43b1-8d4e-4759-bb2d-0b2e03ba701
#     "border_crop": "https://cards.scryfall.io/border_crop/front/8/6/86bf43b1-8d4e-4759-bb2d-0b2e0
#   },
#   "mana_cost": "{3}",
#   "cmc": 3,
#   "type_line": "Artifact",
#   "oracle_text": "As long as Static Orb is untapped, players can't untap more than two permanent
#   "colors": [],
#   "color_identity": [],
#   "keywords": [],
#   "legalities": {
#     "standard": "not_legal",
#     "future": "not_legal",
#     "historic": "not_legal",
#     "gladiator": "not_legal",
#     "pioneer": "not_legal",
#     "explorer": "not_legal",
#     "modern": "not_legal",
#     "legacy": "legal",
#     "pauper": "not_legal",
#     "vintage": "legal",
#     "penny": "not_legal",
#     "commander": "legal",
#     "oathbreaker": "legal",
#     "brawl": "not_legal",
#     "historicbrawl": "not_legal",
#     "alchemy": "not_legal",
#     "paupercommander": "not_legal",
#     "duel": "legal",
#     "oldschool": "not_legal",
#     "premodern": "legal",
#     "predh": "legal"
#   },
#   "games": [
#     "paper",
#     "mtgo"
#   ],
#   "reserved": false,
#   "foil": false,
#   "nonfoil": true,
#   "finishes": [
#     "nonfoil"
#   ],
#   "oversized": false,
#   "promo": false,
#   "reprint": true,
#   "variation": false,
#   "set_id": "230f38aa-9511-4db8-a3aa-aeddbc3f7bb9",
#   "set": "7ed",
#   "set_name": "Seventh Edition",
#   "set_type": "core",
#   "set_uri": "https://api.scryfall.com/sets/230f38aa-9511-4db8-a3aa-aeddbc3f7bb9",
#   "set_search_uri": "https://api.scryfall.com/cards/search?order=set&q=e%3A7ed&unique=prints",
#   "scryfall_set_uri": "https://scryfall.com/sets/7ed?utm_source=api",
#   "rulings_uri": "https://api.scryfall.com/cards/86bf43b1-8d4e-4759-bb2d-0b2e03ba7012/rulings",
#   "prints_search_uri": "https://api.scryfall.com/cards/search?order=released&q=oracleid%3A0004ebd0
#   "collector_number": "319",
#   "digital": false,
#   "rarity": "rare",
#   "flavor_text": "The warriors fought against the paralyzing waves until even their thoughts froze
#   "card_back_id": "0aeebaf5-8c7d-4636-9e82-8c27447861f7",
#   "artist": "Terese Nielsen",
#   "artist_ids": [
#     "eb55171c-2342-45f4-a503-2d5a75baf752"
#   ],
#   "illustration_id": "6f8b3b2c-252f-4f95-b621-712c82be38b5",
#   "border_color": "white",
#   "frame": "1997",
#   "full_art": false,
#   "textless": false,
#   "booster": true,
#   "story_spotlight": false,
#   "edhrec_rank": 3389,
#   "prices": {
#     "usd": "18.45",
#     "usd_foil": null,
#     "usd_etched": null,
#     "eur": "12.73",
#     "eur_foil": null,
#     "tix": "0.23"
#   },
#   "related_uris": {
#     "gatherer": "https://gatherer.wizards.com/Pages/Card/Details.aspx?multiverseid=15862",
#     "tcgplayer_infinite_articles": "https://infinite.tcgplayer.com/search?contentMode=article&game
#     "tcgplayer_infinite_decks": "https://infinite.tcgplayer.com/search?contentMode=deck&game=magic
#     "edhrec": "https://edhrec.com/route/?cc=Static+Orb"
#   },
#   "purchase_uris": {
#     "tcgplayer": "https://www.tcgplayer.com/product/3094?page=1&utm_campaign=affiliate&utm_medium=
#     "cardmarket": "https://www.cardmarket.com/en/Magic/Products/Search?referrer=scryfall&searchStr
#     "cardhoarder": "https://www.cardhoarder.com/cards/15870?affiliate_id=scryfall&ref=card-profile
#   }
# }

def hypergeometric_draw(tup_expected_in_quantity, deck_size = 99, draw_count = 7, percentage = False):
    """Return the probability/percentage of having certains cards in a drawing in certains quantity,
       depending on the amount of those cards in the deck, the deck size, and the drawing number.

       This is the Multivariate Hypergeometric Distribution function as described here:
       https://en.wikipedia.org/wiki/Hypergeometric_distribution#Multivariate_hypergeometric_distribution

       Parameters:
            tup_expected_in_quantity: a list of 2-tuples, first is quantity of sample in deck,
                                      second is expected samples in the draw
            percentage: if 'True' is will return result in percentage rather than probability [0-1]
       """
#     print("[hypergeometric_draw]", 'deck:', deck_size, ', draw:', draw_count, ', tuples:', tup_expected_in_quantity)
#     print("[hypergeometric_draw]", 'comb:', 'prod(', [('comb('+str(tup[0])+', '+str(tup[1])+')') for tup in tup_expected_in_quantity], ')')
#     print("[hypergeometric_draw]", 'deck_rest:', deck_size - sum(map(lambda t: t[0], tuples)))
#     print("[hypergeometric_draw]", 'hand_rest:', draw_count - sum(map(lambda t: t[1], tuples)))
#     print("[hypergeometric_draw]", 'comb(',deck_size - sum(map(lambda t: t[0], tuples)),',',draw_count - sum(map(lambda t: t[1], tuples)), ')')
#     print("[hypergeometric_draw]", 'comb:', comb(deck_size - sum(map(lambda t: t[0], tuples)), draw_count - sum(map(lambda t: t[1], tuples))))
#     print("[hypergeometric_draw]", 'denom:', 'comb(', deck_size, ',', draw_count, ')')
    result = (prod([comb(tup[0], tup[1]) for tup in tup_expected_in_quantity])
              * comb(deck_size - sum(map(lambda t: t[0], tup_expected_in_quantity)),
                     draw_count - sum(map(lambda t: t[1], tup_expected_in_quantity)))
              / comb(deck_size, draw_count))
    if percentage:
        return result * 100
    return result

# tuples = [(5, 2), (10, 2), (15, 2)]
# print(hypergeometric_draw(tuples, deck_size=30, draw_count=6))
# tuples = [(17, 3)]
# print(hypergeometric_draw(tuples, deck_size=40))
# tuples = [(11, 2), (6, 1)]
# print(hypergeometric_draw(tuples, deck_size=40))
# tuples = [(6, 2), (11, 1)]
# print(hypergeometric_draw(tuples, deck_size=40))
# sys.exit(0)

def get_sources_requirements(item):
    """Return the number of colored source in the deck for that card to be played on turn X, where
       X is its CMC.

       example: it requires 19 green mana sources for a Bird Of Paradise to be played on turn X = 1
                because its CMC cost is 1, so we intend to play it at the turn matching its CMC.

       see: https://www.channelfireball.com/article/How-Many-Sources-Do-You-Need-to-Consistently-Cast-Your-Spells-A-2022-Update/dc23a7d2-0a16-4c0b-ad36-586fcca03ad8/
            and the table from where are extracted the numbers: https://mktg-assets.tcgplayer.com/content/channel-fireball/article-images/2022/08/How-many-sources-99-cards.png

       TODO Skip the colorless cards ? How ?
            For colorless mana it should match the number of lands required to drop a land by each
            turn until the card can be played
    """
    if item['cmc'] == 0:
        return 0
    if item['cmc'] == 1:
        if re.match(r'^\{\w\}$', item['mana_cost']):
            return 19
    if item['cmc'] == 2:
        if re.match(r'^\{1\}\{\w\}$', item['mana_cost']):
            return 19
        if re.match(r'^\{\w\}\{\w\}$', item['mana_cost']):
            return 30
    if item['cmc'] == 3:
        if re.match(r'^\{2\}\{\w\}$', item['mana_cost']):
            return 18
        if re.match(r'^\{1\}\{\w\}\{\w\}$', item['mana_cost']):
            return 28
        if re.match(r'^\{\w\}\{\w\}\{\w\}$', item['mana_cost']):
            return 36
    if item['cmc'] == 4:
        if re.match(r'^\{3\}\{\w\}$', item['mana_cost']):
            return 16
        if re.match(r'^\{2\}\{\w\}\{\w\}$', item['mana_cost']):
            return 26
        if re.match(r'^\{1\}\{\w\}\{\w\}\{\w\}$', item['mana_cost']):
            return 33
        if re.match(r'^\{\w\}\{\w\}\{\w\}\{\w\}$', item['mana_cost']):
            return 39
    if item['cmc'] == 5:
        if re.match(r'^\{4\}\{\w\}$', item['mana_cost']):
            return 15
        if re.match(r'^\{3\}\{\w\}\{\w\}$', item['mana_cost']):
            return 23
        if re.match(r'^\{2\}\{\w\}\{\w\}\{\w\}$', item['mana_cost']):
            return 30
        if re.match(r'^\{1\}\{\w\}\{\w\}\{\w\}\{\w\}$', item['mana_cost']):
            return 36
    if item['cmc'] == 6:
        if re.match(r'^\{5\}\{\w\}$', item['mana_cost']):
            return 14
        if re.match(r'^\{4\}\{\w\}\{\w\}$', item['mana_cost']):
            return 22
        if re.match(r'^\{3\}\{\w\}\{\w\}\{\w\}$', item['mana_cost']):
            return 28
    if item['cmc'] == 7:
        if re.match(r'^\{5\}\{\w\}\{\w\}$', item['mana_cost']):
            return 20
        if re.match(r'^\{4\}\{\w\}\{\w\}\{\w\}$', item['mana_cost']):
            return 26
    raise Exception("Not implemented")

def get_scryfall_bulk_data(outdir = '/tmp', update = False):
    """Download Scryfull bulk data informations.

       Scryfall recommends to not download it more than once a week, so the filename
       after downloading it to disk would contain the week number in order to prevent
       other downloads the same week.

       Options:

       outdir      string   The directory where the image is going to be downloaded
       update       bool    If 'True' force updating the image on local store
    """

    date_text = datetime.utcnow().strftime('%Y-%W')
    bulk_data_file_name = 'scryfall-bulk-data-'+date_text+'.json'
    bulk_data_file_path = pjoin(outdir, bulk_data_file_name)
    bulk_data_file_ref = Path(bulk_data_file_path)

    if not bulk_data_file_ref.is_file() or update:

        print("DEBUG Getting Scryfall bulk data from '"+SCRYFALL_API_BULK_URL+"' ...",
            file=sys.stderr)
        with urlopen(SCRYFALL_API_BULK_URL) as r_json:
            bulk_data = json.load(r_json)

        if 'object' not in bulk_data or bulk_data['object'] != 'list':
            print('Error: the Scryfall bulk-data information is not valid.'
                    "Key 'object' is not in the data or with an invalid value.",
                    file=sys.stderr)
            sys.exit(1)

        if 'data' not in bulk_data or not bulk_data['data']:
            print('Error: the Scryfall bulk-data information is not valid.'
                    "Key 'data' is not in the data or with an invalid value.",
                    file=sys.stderr)
            sys.exit(1)

        new_bulk_data = bulk_data
        while 'has_more' in new_bulk_data and new_bulk_data['has_more']:

            if 'next_page' not in new_bulk_data or not new_bulk_data['next_page']:
                print('Error: the Scryfall bulk-data information is not valid.'
                        "Key 'next_page' is not in the data or with an invalid value.",
                        file=sys.stderr)
                sys.exit(1)

            print("DEBUG Getting Scryfall next bulk data from '"+new_bulk_data['next_page']+"' ...",
                file=sys.stderr)
            with urlopen(new_bulk_data['next_page']) as r_json:
                new_bulk_data = json.load(r_json)

            if 'object' not in new_bulk_data or new_bulk_data['object'] != 'list':
                print('Error: the Scryfall bulk-data information is not valid.'
                        "Key 'object' is not in the data or with an invalid value.",
                        file=sys.stderr)
                sys.exit(1)

            if 'data' not in new_bulk_data or not new_bulk_data['data']:
                print('Error: the Scryfall bulk-data information is not valid.'
                        "Key 'data' is not in the data or with an invalid value.",
                        file=sys.stderr)
                sys.exit(1)

            for obj in new_bulk_data['data']:
                bulk_data['data'].append(obj)

        print("DEBUG Saving Scryfall bulk data to local file '"+bulk_data_file_path+"' ...",
              file=sys.stderr)
        with open(bulk_data_file_path, 'w', encoding="utf8") as f_write:
            json.dump(bulk_data, f_write)

    else:
        # print("DEBUG Getting Scryfall bulk data from local file ...")
        with open(bulk_data_file_path, 'r', encoding="utf8") as f_read:
            bulk_data = json.load(f_read)

    return bulk_data


def get_scryfall_cards_db(bulk_data, outdir = '/tmp', update = False):
    """Download Scryfull cards database as a JSON file.

       Scryfall recommends to not download it more than once a week, so the filename
       after downloading it to disk would contain the week number in order to prevent
       other downloads the same week.

       Options:

       outdir      string   The directory where the image is going to be downloaded
       update       bool    If 'True' force updating the image on local store
    """

    oracle_cards_src = []
    for obj in bulk_data['data']:
        if 'type' in obj and obj['type'] == 'oracle_cards':
            if 'download_uri' not in obj or not obj['download_uri']:
                print('Error: the Scryfall bulk-data information is not valid.'
                        "Key 'download_uri' is not in the data or with an invalid value.",
                        file=sys.stderr)
                sys.exit(1)

            # if 'updated_at' not in obj or not obj['updated_at']:
            #     print('Error: the Scryfall bulk-data information is not valid.'
            #             "Key 'updated_at' is not in the data or with an invalid value.",
            #             file=sys.stderr)
            #     sys.exit(1)

            oracle_cards_src.append(obj)

            if len(oracle_cards_src) > 1:
                print('Error: the Scryfall bulk-data information is not valid.'
                        "Too many 'oracle_cards' objects.", file=sys.stderr)
                sys.exit(1)

    if not oracle_cards_src:
        print('Error: the Scryfall bulk-data information is not valid.'
                "No 'oracle_cards' object found.", file=sys.stderr)
        sys.exit(1)

    date_text = datetime.utcnow().strftime('%Y-%W')
    cards_json_file_name = 'scryfall-oracle-cards-'+date_text+'.json'
    cards_json_file_path = pjoin(outdir, cards_json_file_name)
    cards_json_file_ref = Path(cards_json_file_path)
    oracle_cards_uri = oracle_cards_src[0]['download_uri']
    if not cards_json_file_ref.is_file() or update:
        print("DEBUG Getting Scryfall cards JSON database from '"+oracle_cards_uri+"' ...",
              file=sys.stderr)
        urlretrieve(oracle_cards_uri, cards_json_file_path)
    return cards_json_file_path

def get_xmage_commander_banned_list(include_duel = True, update = False):
    """Return a list of banned card for Commander format in XMage

       Options:

       include_duel  bool  If 'True' include DuelCommander format banned list
       update        bool  If 'True' force updating banned list files
    """
    commander_banned_file_path = Path(XMAGE_COMMANDER_BANNED_LIST_FILE)
    commander_banned_cards = []
    if not commander_banned_file_path.is_file() or update:
        print("DEBUG Getting XMage Commander banned list from '"+
              XMAGE_COMMANDER_BANNED_LIST_FILE+"' ...",
              file=sys.stderr)
        with open(XMAGE_COMMANDER_BANNED_LIST_FILE, 'w', encoding="utf8") as f_write:
            with urlopen(XMAGE_COMMANDER_BANNED_LIST_URL) as webpage:
                for line in webpage:
                    matches = re.search(XMAGE_BANNED_LINE_REGEX, line.decode('utf-8'))
                    if matches:
                        card = matches.group('name')
                        commander_banned_cards.append(card)
                        f_write.write(card+'\n')
    else:
        # print("Getting Commander banned list from local file ...")
        with open(XMAGE_COMMANDER_BANNED_LIST_FILE, 'r', encoding="utf8") as f_read:
            commander_banned_cards = list(map(str.strip, list(f_read)))

    if include_duel:
        commanderduel_banned_file_path = Path(XMAGE_DUELCOMMANDER_BANNED_LIST_FILE)
        if not commanderduel_banned_file_path.is_file() or update:
            print("DEBUG Getting Xmage DuelCommander banned list from '"+
                  XMAGE_DUELCOMMANDER_BANNED_LIST_FILE+"' ...",
                  file=sys.stderr)
            with open(XMAGE_DUELCOMMANDER_BANNED_LIST_FILE, 'w', encoding="utf8") as f_write:
                with urlopen(XMAGE_DUELCOMMANDER_BANNED_LIST_URL) as webpage:
                    for line in webpage:
                        matches = re.search(XMAGE_BANNED_LINE_REGEX, line.decode('utf-8'))
                        if matches:
                            card = matches.group('name')
                            commander_banned_cards.append(card)
                            f_write.write(card+'\n')
        else:
            # print("DEBUG Getting DuelCommander banned list from local file '"+
            #       XMAGE_DUELCOMMANDER_BANNED_LIST_FILE+"' ...",
            #       file=sys.stderr)
            with open(XMAGE_DUELCOMMANDER_BANNED_LIST_FILE, 'r', encoding="utf8") as f_read:
                commander_banned_cards += list(map(str.strip, list(f_read)))

    return sorted(set(commander_banned_cards))

def get_card_image(card, imgformat = 'small', outdir = '/tmp', update = False):
    """Download the card's image in format specified to the directory specified,
       and return its local path, its width and its height

       Options:

       imgformat   string   See https://scryfall.com/docs/api/images
       outdir      string   The directory where the image is going to be downloaded
       update       bool    If 'True' force updating the image on local store
    """
    filename = (re.sub(r'[^A-Za-z_-]', '', card['name'])+imgformat+
                ('.jpg' if imgformat != 'png' else '.png'))
    filepath = pjoin(outdir, filename)
    filepathinfo = Path(filepath)
    imgurl = card['image_uris'][imgformat]
    if not filepathinfo.is_file() or update:
        print("DEBUG Getting Scryfall card's image from '"+imgurl+"' ...", file=sys.stderr)
        urlretrieve(imgurl, filepath)
    imgformats = {
        'png': (745, 1040),
        'border_crop': (480, 680),
        'art_crop': (None, None),
        'large': (672, 936),
        'normal': (488, 680),
        'small': (146, 204)}
    return filepath, *(imgformats[imgformat])


def get_commanderspellbook_combos(outdir = '/tmp', update = False):
    """Download CommanderSpellbook combos database as a JSON file.

       To avoid downloading/updating too often, the downloaded filename would contain the week
       number in order to prevent other downloads the same week.

       Options:

       outdir      string   The directory where the image is going to be downloaded
       update       bool    If 'True' force updating the image on local store
    """

    date_text = datetime.utcnow().strftime('%Y-%W')
    combos_json_file_name = 'commanderspellbook-combos-'+date_text+'.json'
    combos_json_file_path = pjoin(outdir, combos_json_file_name)
    combos_json_file_ref = Path(combos_json_file_path)

    if not combos_json_file_ref.is_file() or update:
        print("DEBUG Getting CommanderSpellbook combos JSON database from '"
              +COMMANDERSPELLBOOK_COMBOS_DB_URL+"' ...", file=sys.stderr)
        urlretrieve(COMMANDERSPELLBOOK_COMBOS_DB_URL, combos_json_file_path)

    ## GoogleSheet is deprecated
    # with open("Commander Spellbook Database - combos.tsv", "r", encoding="utf8") as s_file:
    #     f_reader = csv.DictReader(s_file, dialect='excel-tab')
    #     combos = list(f_reader)
    with open(combos_json_file_path, 'r', encoding='utf-8') as f_read:
        combos = json.load(f_read)

    return combos

def get_oracle_texts(card):
    """Return a list of 'oracle_text', one per card's faces"""
    return ([card['oracle_text']] if 'oracle_text' in card
            else ([face['oracle_text'] for face in card['card_faces']]
                  if 'card_faces' in card and card['card_faces'] else []))

def get_mana_cost(card, remove_braces = True):
    """Return a list of 'mana_cost', one per card's faces"""
    mana_cost = ([card['mana_cost']] if 'mana_cost' in card
                 else ([face['mana_cost'] for face in card['card_faces']]
                       if 'card_faces' in card and card['card_faces'] else []))
    if remove_braces:
        mana_cost = list(map(lambda c: re.sub(r'\{(\w|\w/\w)\}', r'\1', c), mana_cost))
    return mana_cost

def get_type_lines(card):
    """Return a list of 'type_line', one per card's faces"""
    return ([card['type_line']] if 'type_line' in card
            else ([face['type_line'] for face in card['card_faces']]
                  if 'card_faces' in card and card['card_faces'] else []))

def get_powr_tough(card):
    """Return a list of 'power' and 'toughness', one per card's faces"""
    return ([card['power']+'/'+card['toughness']] if 'power' in card and 'toughness' in card
            else ([face['power']+'/'+face['toughness'] for face in card['card_faces']
                   if 'power' in face and 'toughness' in face]
                  if 'card_faces' in card and card['card_faces'] else []))

def get_keywords(card):
    """Return a list of 'keywords', one per card's faces"""
    return ([card['keywords']] if 'keywords' in card
            else ([face['keywords'] for face in card['keywords']]
                  if 'card_faces' in card and card['card_faces'] else []))

def in_strings(string, texts):
    """Search a string in a list of strings"""
    return filter(lambda t: string in t, texts)

def in_strings_exclude(string, exclude, texts):
    """Search for a string in a list of strings without the exclude string"""
    return filter(lambda t: string in t and exclude not in t, texts)

def in_strings_excludes(string, excludes, texts):
    """Search a string in a list of strings without the excludes strings"""
    return filter(lambda t: string in t and not bool([e for e in excludes if e in t]), texts)

def not_in_strings_exclude(string, exclude, texts):
    """Search for absence of a string in a list of strings or with the exclude string"""
    return filter(lambda t: string not in t or exclude in t, texts)

def not_in_strings_excludes(string, excludes, texts):
    """Search for absence of a string in a list of strings or with the excludes strings"""
    return filter(lambda t: string not in t or bool([e for e in excludes if e in t]), texts)

def search_strings(regex, texts):
    """Search a regex in a list of strings"""
    return filter(lambda t: re.search(regex, t), texts)

def filter_empty(item):
    """Remove empty cards"""
    if not item:
        return False
    return True

def filter_xmage_banned(item):
    """Remove cards that are banned"""
    return item['name'] not in XMAGE_COMMANDER_CARDS_BANNED

def filter_not_legal_and_banned(item):
    """Remove cards that are not legal or banned"""
    if ('legalities' in item and 'commander' in item['legalities']
            and item['legalities']['commander'] != 'legal'):
        return False
    return True

def filter_mythic_and_special(item):
    """Remove mythic cards and special ones"""
    if ('rarity' in item and item['rarity'] == 'mythic' or item['rarity'] == 'special'):
        return False
    return True

def filter_colors(item):
    """Remove card from colors not in the commander identity"""
    # if 'produced_mana' in item and bool(INVALID_COLORS & set(item['produced_mana'])):
    #     return False
    if 'color_identity' in item:
        return not bool(INVALID_COLORS & set(item['color_identity']))
    return True

def filter_price(item):
    """Remove card if price above a certain value (in EUR or USD)"""
    if ('prices' in item and (
            ('eur' in item['prices'] and float(item['prices']['eur'] or 0) > 100)
            or ('usd' in item['prices'] and float(item['prices']['usd'] or 0) > 120))):
        return False
    return True

def filter_no_keywords(item):
    """Remove cards that have no keywords"""
    return 'keywords' in item and item['keywords']

def filter_no_text(item):
    """Remove cards that have no text"""
    return any(filter(len, get_oracle_texts(item)))

def filter_all_at_once(item):
    """Remove card if it doesn't pass all filters"""

    # empty card
    if not filter_empty(item):
        return False

    # commander legal
    if not filter_not_legal_and_banned(item):
        return False

    # xmage banned
    if not filter_xmage_banned(item):
        return False

    # rarity
    if not filter_mythic_and_special(item):
        return False

    # price: not above 100€ or 120$
    if not filter_price(item):
        return False

    # color: no green no red
    if not filter_colors(item):
        return False

    # default
    return True

def filter_lands(item):
    """Keep only lands"""
    return (item['type_line'].startswith('Land')
            or item['type_line'].startswith('Legendary Land')
            or item['type_line'].startswith('Basic Land')
            or item['type_line'].startswith('Artifact Land')
            or item['type_line'].startswith('Snow Land')
            or item['type_line'].startswith('Basic Snow Land'))

def filter_sacrifice(item):
    """Remove card if its text contains 'sacrifice' without containing 'unless'"""
    return bool(list(not_in_strings_exclude('sacrifice', 'unless',
                                            map(str.lower, get_oracle_texts(item)))))

def filter_tapped(item):
    """Remove card if its text contains ' tapped'"""
    return not bool(list(in_strings('tapped', map(str.lower, get_oracle_texts(item)))))

def filter_tapped_or_untappable(item):
    """Remove card if its text contains ' tapped' without containing 'tapped if' or 'unless'
       or 'become tapped' or 'untap' or 'tap an untapped' or 'create a tapped '"""
    return (
        not bool(list(in_strings(item['name']+' enters the battlefield tapped.',
                                 get_oracle_texts(item))))
        and bool(list(not_in_strings_excludes(
                'tapped',
                ['tapped if', 'unless', 'become tapped', 'becomes tapped', 'untap', 'tap an untapped',
                'create a tapped '],
                map(str.lower, get_oracle_texts(item))))))

def filter_add_one_colorless_mana(item):
    """Remove card if its text contains '{T}: Add {C}'"""
    return not bool(list(in_strings('{T}: Add {C}', get_oracle_texts(item))))

def filter_multicolors_lands(item):
    """Keep only lands that can produce all colors"""
    return ('produced_mana' in item
            and len(ALL_COLORS & set(item['produced_mana'])) >= ALL_COLORS_COUNT)

def filter_tricolors_lands(item):
    """Keep only lands that can produce all commander identity colors"""
    return 'produced_mana' in item and (
        len(COMMANDER_COLOR_IDENTITY & set(item['produced_mana'])) >= COMMANDER_COLOR_IDENTITY_COUNT
        and len(ALL_COLORS & set(item['produced_mana'])) < ALL_COLORS_COUNT)

def filter_bicolors_lands(item):
    """Keep only lands that can produce at least two colors of the commander identity"""
    return 'produced_mana' in item and (
        len(COMMANDER_COLOR_IDENTITY & set(item['produced_mana'])) >= 2
        and len(COMMANDER_COLOR_IDENTITY & set(item['produced_mana'])) < COMMANDER_COLOR_IDENTITY_COUNT)

def compute_invalid_colors():
    """Compute the list of colors not in the commander identity"""
    global INVALID_COLORS
    INVALID_COLORS = ALL_COLORS - COMMANDER_COLOR_IDENTITY

def join_oracle_texts(card, truncate = False, colorize = True):
    """Return a string with card's oracle text joined"""
    texts = get_oracle_texts(card)
    texts_truncated = texts
    if truncate:
        trunc_len = ((int(truncate / 2) - 2) if int(truncate) > 4 and 'card_faces' in card
                     else truncate)
        texts_truncated = list(map(lambda t: truncate_text(t, trunc_len), texts))
    texts_colorized = texts_truncated
    if colorize:
        texts_colorized = list(map(colorize_ability, texts_truncated))
    texts_joined = ' // '.join(texts_colorized).replace('\n', '. ')
    return texts_joined

def order_cards_by_cmc_and_name(cards_list):
    """Return an ordered cards list by CMC + Mana cost length as a decimal, and Name"""
    return list(sorted(cards_list, key=lambda c: (
        str((c['cmc'] if 'cmc' in c else 0) + float('0.'+str(len(c['mana_cost']) if 'mana_cost' in c else '0')))
        +c['name'])))

def print_all_cards_stats(cards, total_cards):
    """Print statistics about all cards"""

    print('')
    print('### All Cards Stats ###')
    print('')

    print('Total cards:', total_cards)

    # empty cards
    prev_total_cards = total_cards
    cards = list(filter(filter_empty, cards))
    total_cards = len(cards)
    print('Empty cards:', prev_total_cards - total_cards)
    print('')

    # commander legal
    prev_total_cards = total_cards
    cards_legal = list(filter(filter_not_legal_and_banned, cards))
    new_total_cards = len(cards_legal)
    print('Illegal or banned:', prev_total_cards - new_total_cards)
    print('')

    # xmage banned
    prev_total_cards = total_cards
    cards_not_banned = list(filter(filter_xmage_banned, cards))
    new_total_cards = len(cards_not_banned)
    print('XMage banned:', prev_total_cards - new_total_cards)
    print('')

    # mythic or special
    prev_total_cards = total_cards
    cards_below_mythic = list(filter(filter_mythic_and_special, cards))
    new_total_cards = len(cards_below_mythic)
    print('Mythic or special:', prev_total_cards - new_total_cards)
    print('')

    # max price
    no_price_eur = len(list(filter(lambda c: not c['prices']['eur'], cards)))
    no_price_usd = len(list(filter(lambda c: not c['prices']['usd'], cards)))
    max_price_eur = max(map(lambda c: float(c['prices']['eur'] or 0), cards))
    max_price_usd = max(map(lambda c: float(c['prices']['usd'] or 0), cards))
    print('No price EUR:', no_price_eur)
    print('No price USD:', no_price_usd)
    print('Price max EUR:', max_price_eur)
    print('Price max USD:', max_price_usd)
    print('')

    # price above 100€ or 120$
    prev_total_cards = total_cards
    cards_price_ok = list(filter(filter_price, cards))
    new_total_cards = len(cards_price_ok)
    print('Price >100€ or >120$:', prev_total_cards - new_total_cards)
    print('')

    # no text
    prev_total_cards = total_cards
    cards_with_text = list(filter(filter_no_text, cards))
    new_total_cards = len(cards_with_text)
    print('Without text:', prev_total_cards - new_total_cards)
    print('')

    # no keywords
    prev_total_cards = total_cards
    cards_with_keywords = list(filter(filter_no_keywords, cards))
    new_total_cards = len(cards_with_keywords)
    print('Without keywords:', prev_total_cards - new_total_cards)
    print('')

    # no text and no keywords
    prev_total_cards = total_cards
    cards_with_keywords_or_text = list(
        filter(lambda c: filter_no_keywords(c) or filter_no_text(c), cards))
    new_total_cards = len(cards_with_keywords_or_text)
    print('Without keywords and text:', prev_total_cards - new_total_cards)

def assist_land_selection(lands, land_types_invalid_regex):
    """Show pre-selected lands organised by features, for the user to select some"""

    # lands selection
    selected_lands = []
    # lands_no_sacrifice = list(filter(filter_sacrifice, lands))
    # lands_no_tapped = list(filter(filter_tapped_or_untappable, lands))
    # lands_no_sacrifice_or_tapped = list(filter(
    #     lambda c: filter_sacrifice(c) and filter_tapped_or_untappable(c), lands))

    # select multicolor lands
    cards_lands_multicolors = list(filter(filter_multicolors_lands, lands))
    cards_lands_multicolors_generic_enough = list(filter(
        lambda c: not list(search_strings(LAND_MULTICOLORS_GENERIC_EXCLUDE_REGEX,
                                            map(str.lower, get_oracle_texts(c)))),
        cards_lands_multicolors))
    cards_lands_multicolors_no_tapped = list(filter(
        filter_tapped_or_untappable, cards_lands_multicolors_generic_enough))
    cards_lands_multicolors_tapped = [
        c for c in cards_lands_multicolors if c not in cards_lands_multicolors_no_tapped]
    cards_lands_multicolors_filtered = list(filter(
        lambda c: not list(search_strings(LAND_MULTICOLORS_EXCLUDE_REGEX,
        map(str.lower, get_oracle_texts(c)))),
            filter(filter_add_one_colorless_mana,
                filter(filter_sacrifice,
                    filter(filter_tapped,
                        cards_lands_multicolors_generic_enough)))))
    selected_lands += cards_lands_multicolors_filtered
    cards_lands_multicolors_no_tapped = [
        c for c in cards_lands_multicolors_no_tapped
        if c not in cards_lands_multicolors_filtered]
    cards_lands_multicolors_tapped = [
        c for c in cards_lands_multicolors_tapped if c not in cards_lands_multicolors_filtered]
    cards_lands_multicolors_producers = list(filter(
        lambda c: bool(list(search_strings(
            r'(^\s*|\n|\r|[^,] )\{T\}: Add ', get_oracle_texts(c)))),
        [c for c in cards_lands_multicolors_generic_enough
            if c not in cards_lands_multicolors_filtered]))

    # converters/mana fixers with colorless production
    # TODO exclude them ?
    cards_lands_converters_colorless_producers = list(filter(
        lambda c: c['name'] == "Cascading Cataracts" or bool(list(search_strings(
            r'\{T\}: Add \{C\}.(\s+|\n|\r)?\{\d+\}, \{T\}: Add one mana of any color',
            get_oracle_texts(c)))),
        cards_lands_multicolors_producers))
    cards_lands_converters_colorless_producers_not_tapped = list(filter(
        filter_tapped_or_untappable, cards_lands_converters_colorless_producers))
    cards_lands_converters_colorless_producers_tapped = [
        c for c in cards_lands_converters_colorless_producers
        if c not in cards_lands_converters_colorless_producers_not_tapped]

    # update multicolors producers to exclude those that only produces colorless mana
    cards_lands_multicolors_producers = [
        c for c in cards_lands_multicolors_producers
        if c not in cards_lands_converters_colorless_producers]

    # remove under optimized cards
    cards_lands_multicolors_producers = list(filter(
        lambda c: bool(
            # shity
            not list(in_strings(
                '{T}, Sacrifice '+c['name']+': Add one mana of any color', get_oracle_texts(c)))
            # shity
            and not list(in_strings(
                'When '+c['name']+' enters the battlefield, add one mana of any color',
                get_oracle_texts(c)))
            # shity
            and c['name'] != "Springjack Pasture"
            # specific
            and (c['name'] != "The Grey Havens" or FILL_GRAVEYARD_FAST)),
        cards_lands_multicolors_producers))

    # split multicolors producers between tapped or not
    cards_lands_multicolors_producers_not_tapped = list(filter(
        filter_tapped_or_untappable, cards_lands_multicolors_producers))
    cards_lands_multicolors_producers_tapped = [
        c for c in cards_lands_multicolors_producers
        if c not in cards_lands_multicolors_producers_not_tapped]

    # remove under optimized cards
    cards_lands_multicolors_producers_tapped_filtered = list(filter(
        lambda c: bool(
            # pay {1} or sacrifice it
            not list(in_strings('sacrifice it unless you pay {1}', get_oracle_texts(c)))
            # color selection: mono color
            and not list(in_strings(
                '{T}: Add one mana of the chosen color', get_oracle_texts(c)))
            # color selection: bi-color
            and not list(search_strings(
                r'\{T\}: Add \{\w\} or one mana of the chosen color', get_oracle_texts(c)))
            and not list(in_strings(
                '{T}: Add one mana of either of the circled colors', get_oracle_texts(c)))
            # charge counter
            and not list(in_strings(
                '{T}, Remove a charge counter from '+c['name']+': Add one mana of any color',
                get_oracle_texts(c)))),
        cards_lands_multicolors_producers_tapped))

    # multicolors producers that produce mana only for a given spell type
    cards_lands_multicolors_producers_not_tapped_selective = list(filter(
        lambda c: list(in_strings('only to cast', map(str.lower, get_oracle_texts(c)))),
        cards_lands_multicolors_producers_not_tapped))
    cards_lands_multicolors_producers_not_tapped_not_selective = [
        c for c in cards_lands_multicolors_producers_not_tapped
        if c not in cards_lands_multicolors_producers_not_tapped_selective]


    # converters/mana fixers without production
    # TODO exclude them ?
    cards_lands_converters_no_producers = list(filter(
        lambda c: bool(list(search_strings(r'\{\d+\}, \{T\}: Add one mana of any color',
                                            get_oracle_texts(c)))),
        [c for c in cards_lands_multicolors_generic_enough
            if c not in cards_lands_converters_colorless_producers]))
    cards_lands_converters_no_producers_not_tapped = list(filter(
        filter_tapped_or_untappable, cards_lands_converters_no_producers))
    cards_lands_converters_no_producers_tapped = [
        c for c in cards_lands_converters_no_producers
        if c not in cards_lands_converters_no_producers_not_tapped]

    # update converters list
    cards_lands_converters = (cards_lands_converters_colorless_producers
                                + cards_lands_converters_no_producers)

    # tri-colors lands
    cards_lands_tricolors = list(filter(
        lambda c: not bool(list(in_strings('return', map(str.lower, get_oracle_texts(c))))),
        filter(filter_add_one_colorless_mana,
                filter(filter_tricolors_lands, lands))))
    selected_lands += cards_lands_tricolors

    # bi-colors lands
    cards_lands_bicolors = list(filter(filter_bicolors_lands, lands))
    cards_lands_bicolors_filtered = list(filter(
        lambda c: (
            ' // ' not in c['name']
            and not list(in_strings('storage counter', get_oracle_texts(c)))
            and not list(in_strings("doesn't untap", get_oracle_texts(c)))
            and not list(search_strings(LAND_BICOLORS_EXCLUDE_REGEX,
                                        map(str.lower, get_oracle_texts(c))))),
        cards_lands_bicolors))
    cards_lands_bicolors_filtered_not_tapped = list(filter(filter_tapped_or_untappable,
        cards_lands_bicolors_filtered))
    cards_lands_bicolors_filtered_tapped = [
        c for c in cards_lands_bicolors_filtered
        if c not in cards_lands_bicolors_filtered_not_tapped]
    selected_lands += cards_lands_bicolors_filtered_not_tapped

    # land fetcher
    cards_lands_sacrifice_search = list(
        filter(
            lambda c: not list(in_strings('destroy', map(str.lower, get_oracle_texts(c)))),
            filter(
                lambda c: not list(search_strings(land_types_invalid_regex,
                                                    map(str.lower, get_oracle_texts(c)))),
                filter(
                    lambda c: list(search_strings(LAND_SACRIFICE_SEARCH_REGEX,
                                                    map(str.lower, get_oracle_texts(c)))),
                    lands))))
    cards_lands_sacrifice_search_no_tapped = list(
        filter(filter_tapped_or_untappable, cards_lands_sacrifice_search))
    selected_lands += cards_lands_sacrifice_search_no_tapped

    # nonbasic lands that are producers
    cards_lands_producers_non_basic = list(filter(
            lambda c: (
                bool(list(search_strings(r'(\s+|\n|\r)?\{T\}: Add \{\w\}',
                                            get_oracle_texts(c))))
                and not bool(list(in_strings('roll a', map(str.lower, get_oracle_texts(c)))))
                and not bool(list(in_strings('phased out', map(str.lower, get_oracle_texts(c)))))
                and not bool(list(in_strings('venture into the dungeon',
                                            map(str.lower, get_oracle_texts(c)))))),
            filter(
                lambda c: not c['type_line'].lower().startswith('basic land'),
                [c for c in lands if c not in cards_lands_multicolors_generic_enough
                and c not in cards_lands_converters
                and c not in cards_lands_tricolors
                and c not in cards_lands_bicolors
                and c not in cards_lands_sacrifice_search])))
    cards_lands_producers_non_basic_no_colorless = list(filter(
        filter_add_one_colorless_mana, cards_lands_producers_non_basic))
    cards_lands_producers_non_basic_colorless = [
        c for c in cards_lands_producers_non_basic
        if c not in cards_lands_producers_non_basic_no_colorless]
    cards_lands_producers_non_basic_no_colorless_not_tapped = list(filter(
        filter_tapped, cards_lands_producers_non_basic_no_colorless))
    cards_lands_producers_non_basic_no_colorless_tapped = [
        c for c in cards_lands_producers_non_basic_no_colorless
        if c not in cards_lands_producers_non_basic_no_colorless_not_tapped]

    # print land results
    print('Multicolors lands generic enough (total):', len(cards_lands_multicolors_generic_enough))
    print('')
    print('Multicolors lands producers (total):', len(cards_lands_multicolors_producers))
    print('')
    # print('   Multicolors lands (not tapped, conditionnal):', len(cards_lands_multicolors_no_tapped))
    # for card in cards_lands_multicolors_no_tapped:
    #     print('      ', card['name'], ' ', join_oracle_texts(card))
    # print('')
    # print('   Multicolors lands (tapped):', len(cards_lands_multicolors_tapped))
    # for card in cards_lands_multicolors_tapped:
    #     print('      ', card['name'], ' ', join_oracle_texts(card))
    # print('')
    print('   Multicolors lands producers (not tapped, no sacrifice, no colorless mana):',
            len(cards_lands_multicolors_filtered))
    for card in cards_lands_multicolors_filtered:
        print_card(card, trunc_name = 25, print_mana = False, print_type = False, print_powr_tough = False, indent = 5)
    print('')
    print('   Multicolors lands producers (not tapped or untappable):',
            len(cards_lands_multicolors_producers_not_tapped))
    print('')
    print('   Multicolors lands producers (not tapped or untappable, not selective):',
            len(cards_lands_multicolors_producers_not_tapped_not_selective))
    for card in cards_lands_multicolors_producers_not_tapped_not_selective:
        print_card(card, trunc_name = 25, print_mana = False, print_type = False, print_powr_tough = False, indent = 5)
    print('')
    print('   Multicolors lands producers (not tapped or untappable, selective):',
            len(cards_lands_multicolors_producers_not_tapped_selective))
    for card in cards_lands_multicolors_producers_not_tapped_selective:
        print_card(card, trunc_name = 25, print_mana = False, print_type = False, print_powr_tough = False, indent = 5)
    print('')
    print('   Multicolors lands producers (tapped):',
            len(cards_lands_multicolors_producers_tapped))
    print('')
    print('   Multicolors lands producers (tapped, no color selection, no charge counter, no pay {1}):',
            len(cards_lands_multicolors_producers_tapped_filtered))
    for card in cards_lands_multicolors_producers_tapped_filtered:
        print_card(card, trunc_name = 25, print_mana = False, print_type = False, print_powr_tough = False, indent = 5)
    print('')

    print('Lands converters (total):', len(cards_lands_converters))
    print('')
    print('   Lands converters colorless producers (total):',
            len(cards_lands_converters_colorless_producers))
    print('')
    print('   Lands converters colorless producers (not tapped or untappable):',
            len(cards_lands_converters_colorless_producers_not_tapped))
    for card in cards_lands_converters_colorless_producers_not_tapped:
        print_card(card, trunc_name = 25, print_mana = False, print_type = False, print_powr_tough = False, indent = 5)
    print('')
    print('   Lands converters colorless producers (tapped):',
            len(cards_lands_converters_colorless_producers_tapped))
    for card in cards_lands_converters_colorless_producers_tapped:
        print_card(card, trunc_name = 25, print_mana = False, print_type = False, print_powr_tough = False, indent = 5)
    print('')

    ### NOTE: I prefer artifacts for the job of converting mana,
    ###       since their colorless mana will turn into a ramp, instead of a bad mana
    # print('   Lands converters not producers (total):',
    #       len(cards_lands_converters_no_producers))
    # print('')
    # print('   Lands converters not producers (not tapped or untappable):',
    #       len(cards_lands_converters_no_producers_not_tapped))
    # for card in cards_lands_converters_no_producers_not_tapped:
    #     print('      ', card['name'], ' ', join_oracle_texts(card))
    # print('')
    # print('   Lands converters not producers (tapped):',
    #       len(cards_lands_converters_no_producers_tapped))
    # for card in cards_lands_converters_no_producers_tapped:
    #     print('      ', card['name'], ' ', join_oracle_texts(card))
    # print('')
    #
    # print('Tricolors lands:', len(cards_lands_tricolors))
    # for card in cards_lands_tricolors:
    #     print('   ', card['produced_mana'], ' ', card['name'], ' ', join_oracle_texts(card))
    # print('')

    print('Bicolors lands:', len(cards_lands_bicolors))
    print('')
    print('Bicolors lands (filtered):', len(cards_lands_bicolors_filtered))
    print('')
    print('Bicolors lands (filtered, not tapped or untappable):',
            len(cards_lands_bicolors_filtered_not_tapped))
    for card in cards_lands_bicolors_filtered_not_tapped:
        print_card(card, trunc_name = 25, print_mana = False, print_type = False, print_powr_tough = False, indent = 5)
    print('')
    print('Bicolors lands (filtered, tapped):',
            len(cards_lands_bicolors_filtered_tapped))
    # for card in cards_lands_bicolors_filtered_tapped:
    #     print('   ', card['produced_mana'], ' ', card['name'], ' ', join_oracle_texts(card))
    print('')

    print('Sacrifice/Search lands:', len(cards_lands_sacrifice_search))
    print('Sacrifice/Search lands (not tapped or untappable):',
            len(cards_lands_sacrifice_search_no_tapped))
    for card in cards_lands_sacrifice_search_no_tapped:
        print_card(card, trunc_name = 25, print_mana = False, print_type = False, print_powr_tough = False, indent = 5)
    print('')

    # print('Lands producers of mana that are nonbasic:', len(cards_lands_producers_non_basic))
    # print('')
    # # NOTE: those fetchable lands are useless
    # # cards_lands_producers_non_basic_fetchable = list(filter(
    # #     lambda c: re.search(
    # #         r'('+('|'.join(map(str.lower, COLOR_TO_LAND.values())))+')',
    # #         c['type_line'].lower()),
    # #     cards_lands_producers_non_basic))
    # # print('   Lands producers of mana that are nonbasic (fetchable):',
    # #       len(cards_lands_producers_non_basic_fetchable))
    # # for card in cards_lands_producers_non_basic_fetchable:
    # #     print('      ', card['name'], ' ', join_oracle_texts(card))
    # # print('')
    # print('   Lands producers of mana that are nonbasic (no colorless):',
    #        len(cards_lands_producers_non_basic_no_colorless))
    # print('')
    # print('   Lands producers of mana that are nonbasic (no colorless, not tapped):',
    #        len(cards_lands_producers_non_basic_no_colorless_not_tapped))
    # for card in cards_lands_producers_non_basic_no_colorless_not_tapped:
    #     print_card(card, trunc_name = 25, print_mana = False, print_type = False, print_powr_tough = False, indent = 5)
    # print('')
    # print('   Lands producers of mana that are nonbasic (no colorless, tapped):',
    #        len(cards_lands_producers_non_basic_no_colorless_tapped))
    # print('')
    # print('   Lands producers of mana that are nonbasic (colorless):',
    #         len(cards_lands_producers_non_basic_colorless))
    # for card in cards_lands_producers_non_basic_colorless:
    #     print_card(card, trunc_name = 25, print_mana = False, print_type = False, print_powr_tough = False, indent = 5)
    # print('')
    # print('')

    # TODO select monocolor lands to match 37 lands cards (at the end)
    #      42 cards recommanded: @see https://www.channelfireball.com/article/What-s-an-Optimal-Mana-Curve-and-Land-Ramp-Count-for-Commander/e22caad1-b04b-4f8a-951b-a41e9f08da14/
    #      - 3 land for each 5 ramp cards
    #      - 2 land for each 5 draw cards


def assist_land_fetch(cards, land_types_invalid_regex):
    """Show pre-selected land fetchers organised by features, for the user to select some"""

    cards_ramp_cards_land_fetch = []
    cards_ramp_cards_land_fetch_channel = []
    cards_ramp_cards_land_fetch_land_cycling = []

    for card in cards:
        card_oracle_texts = list(get_oracle_texts(card))
        card_oracle_texts_low = list(map(str.lower, card_oracle_texts))
        if not list(search_strings(land_types_invalid_regex, card_oracle_texts_low)):
            if card['name'] not in ["Strata Scythe", "Trench Gorger"]:
                if list(search_strings(LAND_CYCLING_REGEX, card_oracle_texts_low)):
                    cards_ramp_cards_land_fetch_land_cycling.append(card['name'])
                    cards_ramp_cards_land_fetch.append(card)
                elif (bool(list(search_strings(RAMP_CARDS_LAND_FETCH_REGEX, card_oracle_texts_low)))
                        #and not list(search_strings(r'(you|target player|opponent).*discard',
                        #                            card_oracle_texts_low))
                        and card['name'] not in ['Mana Severance', 'Settle the Wreckage']
                        and not filter_lands(card)):
                    if bool(list(in_strings('channel', card_oracle_texts_low))):
                        cards_ramp_cards_land_fetch_channel.append(card['name'])
                    cards_ramp_cards_land_fetch.append(card)

    cards_ramp_cards_land_fetch_by_feature = {
        'to battlefield': [],
        'to battlefield (conditional)': [],
        'to hand': [],
        'to hand (conditional)': [],
        'to top of library': [],
        'to top of library (conditional)': []}
    for card in cards_ramp_cards_land_fetch:
        card_oracle_texts = list(get_oracle_texts(card))
        card_oracle_texts_low = list(map(str.lower, card_oracle_texts))
        conditional = (bool(list(in_strings('more lands', card_oracle_texts_low)))
                       or bool(list(in_strings('fewer lands', card_oracle_texts_low))))
        cond_text = ' (conditional)' if conditional else ''
        if list(search_strings(
                r'puts? (it|that card|one( of them)?|them|those cards|a card [^.]+) into your hand',
                card_oracle_texts_low)):
            cards_ramp_cards_land_fetch_by_feature['to hand'+cond_text].append(card)
        elif list(search_strings(
                r'puts? (it|that card|one( of them)?|them|those cards) onto the battlefield',
                card_oracle_texts_low)):
            cards_ramp_cards_land_fetch_by_feature['to battlefield'+cond_text].append(card)
        elif list(search_strings('put that card on top', card_oracle_texts_low)):
            cards_ramp_cards_land_fetch_by_feature['to top of library'+cond_text].append(card)
        else:
            print('UNKNOWN', print_card(card, return_str = True, trunc_text = False))

    print('Land fetch (total):', len(cards_ramp_cards_land_fetch))
    print('')

    for feature, cards_list in cards_ramp_cards_land_fetch_by_feature.items():
        if cards_list:
            extra_text = 'RAMP CARDS ' if feature.startswith('to battlefield') else ''
            print('   '+extra_text+'Land fetch ('+feature+'):', len(cards_list))
            if ' (conditional)' in feature:
                print('')
                continue
            land_cycling = []
            channel = []
            organized = {'creature': [], 'instant': [], 'sorcery': [], 'enchantment': [],
                        'artifact': []}
            for card in cards_list:
                if card['name'] in cards_ramp_cards_land_fetch_land_cycling:
                    land_cycling.append(card)
                elif card['name'] in cards_ramp_cards_land_fetch_channel:
                    channel.append(card)
                else:
                    organized[get_card_type(card)].append(card)

            for card_type, sub_cards_list in organized.items():
                organized[card_type] = order_cards_by_cmc_and_name(sub_cards_list)

            for card_type, sub_cards_list in organized.items():
                if sub_cards_list:
                    print('      '+extra_text+'Land fetch '+feature+' ('+card_type+'):',
                          len(sub_cards_list))
                    for card in sub_cards_list:
                        if card_type == 'unknown':
                            print_card(card, print_powr_tough = False, indent = 8,
                                       merge_type_powr_tough = False)
                        else:
                            print_card(card, print_powr_tough = (card_type == 'creature'),
                                       print_type = False, indent = 8,
                                       print_mana = (card_type not in ['land','stickers']))
                    print('')
            if land_cycling:
                print('      Land fetch '+feature+' (land cycling):', len(land_cycling))
                for card in order_cards_by_cmc_and_name(land_cycling):
                    print_card(card, indent = 8)
                print('')
            if channel:
                print('      Land fetch '+feature+' (channel):', len(channel))
                for card in order_cards_by_cmc_and_name(channel):
                    print_card(card, indent = 8)
                print('')
            print('')

    return cards_ramp_cards_land_fetch

def truncate_text(text, length):
    """Truncate a text to length and add an ellipsis if text was lengther"""
    if length and len(text) > length:
        return text[:length - 1]+'…'
    return text

def is_creature(card, include_vehicle = True):
    """Return 'True' if the card is a creature, or one of its face is one"""
    return (bool(list(in_strings('creature', map(str.lower, get_type_lines(card)))))
            or (bool(list(in_strings('vehicle', map(str.lower, get_type_lines(card)))))
                and include_vehicle))

def get_card_type(card):
    """Return the card type amongst following:
       - creature
       - planeswalker
       - instant
       - enchantment
       - artifact
       - sorcery
       - land
       - stickers
       - unknown
    """
    if is_creature(card):
        return 'creature'
    if 'planeswalker' in card['type_line'].lower():
        return 'planeswalker'
    if 'instant' in card['type_line'].lower():
        return 'instant'
    if 'sorcery' in card['type_line'].lower():
        return 'sorcery'
    if 'enchantment' in card['type_line'].lower():
        return 'enchantment'
    if 'artifact' in card['type_line'].lower():
        return 'artifact'
    if filter_lands(card):
        return 'land'
    if 'stickers' in card['type_line'].lower():
        return 'stickers'
    return 'unknown'

def organize_by_type(cards):
    """Return a dict with cards dispatched amongst following keys:
       - creature
       - planeswalker
       - instant
       - enchantment
       - artifact
       - sorcery
       - land
       - stickers
       - unknown
    """
    orga = {
        'creature': [],
        'planeswalker': [],
        'instant': [],
        'enchantment': [],
        'artifact': [],
        'sorcery': [],
        'land': [],
        'stickers': [],
        'unknown': [],
    }
    for card in cards:
        orga[get_card_type(card)].append(card)
    return orga

def print_card(card, indent = 0, print_mana = True, print_type = True, print_powr_tough = True,
               trunc_name = 25, trunc_type = 16, trunc_text = 'auto', trunc_mana = 10,
               merge_type_powr_tough = True, return_str = False, print_text = True,
               print_keywords = False, print_edhrank = True, print_price = True,
               trunc_powr_tough = 6, separator_color = 'dark_grey', trunc_line = True):
    """Display a card or return a string representing it"""

    merge_type_powr_tough = merge_type_powr_tough and print_type and print_powr_tough
    if merge_type_powr_tough and (not trunc_type or trunc_type > 10):
        trunc_type = 10  # default power/toughness length
    len_type = '16' if not trunc_type else str(trunc_type)

    line = ''
    line_visible_len = 0
    separator = ' | '
    separator_colored = colored(separator, separator_color)

    indent_fmt = '{:<'+str(indent)+'}'
    indent_part = indent_fmt.format('')
    line += indent_part
    line_visible_len += len(indent_part)

    if print_edhrank:
        edhrank_fmt = '# {:>5}'
        edhrank_part = edhrank_fmt.format(card['edhrec_rank'] if 'edhrec_rank' in card else '')
        line += edhrank_part + separator_colored
        line_visible_len += len(edhrank_part + separator)

    if print_price:
        price_fmt = '$ {:>5}'
        price_part = price_fmt.format(str(card['prices']['usd'])
                                      if 'prices' in card and 'usd' in card['prices']
                                      and card['prices']['usd'] else '')
        line += price_part + separator_colored
        line_visible_len += len(price_part + separator)

    if print_mana:
        mana_fmt = '{:>'+('21' if not trunc_mana else str(trunc_mana))+'}'
        mana_part = mana_fmt.format(
            truncate_text((' // '.join(get_mana_cost(card)) if print_mana else ''),
                          trunc_mana))
        mana_part_colored = colorize_mana(mana_part, no_braces = True)
        line += mana_part_colored + separator_colored
        line_visible_len += len(mana_part + separator)

    if merge_type_powr_tough:
        if is_creature(card):
            powr_tough_fmt = '{:>'+len_type+'}'
            powr_tough_part = powr_tough_fmt.format(' // '.join(get_powr_tough(card)))
            line += powr_tough_part + separator_colored
            line_visible_len += len(powr_tough_part + separator)

        else:
            type_fmt = '{:<'+len_type+'}'
            type_part = type_fmt.format(truncate_text((' // '.join(get_type_lines(card))),
                                                      trunc_type))
            line += type_part + separator_colored
            line_visible_len += len(type_part + separator)
    else:
        if print_powr_tough:
            powr_tough_fmt = '{:>'+str(trunc_powr_tough)+'}'
            powr_tough_part = powr_tough_fmt.format('')
            if is_creature(card):
                powr_tough_part = powr_tough_fmt.format(' // '.join(get_powr_tough(card)))
            line += powr_tough_part + separator_colored
            line_visible_len += len(powr_tough_part + separator)

        if print_type:
            type_fmt = '{:<'+len_type+'}'
            type_part = type_fmt.format(truncate_text((' // '.join(get_type_lines(card))),
                                                      trunc_type))
            line += type_part + separator_colored
            line_visible_len += len(type_part + separator)

    name_fmt = '{:<'+('40' if not trunc_name else str(trunc_name))+'}'
    name_part = name_fmt.format(truncate_text(card['name'], trunc_name),
                                        get_card_colored(card))
    name_part_colored = colored(name_part)
    line += name_part_colored + separator_colored
    line_visible_len += len(name_part + separator)

    if print_keywords:
        keywords_fmt = '{}'
        keywords_part = keywords_fmt.format(' // '.join(list(map(lambda k: ', '.join(k),
                                                                 get_keywords(card)))))
        line += keywords_part + (separator_colored if print_text else '')
        line_visible_len += len(keywords_part + (separator if print_text else ''))

    if print_text:
        text_fmt = '{}'
        text_part_colored = text_fmt.format(join_oracle_texts(
            card, (trunc_text if trunc_text != 'auto' else False)))

        if trunc_text == 'auto' and TERM_COLS:
            # Note: 2 is a margin, because joined lines have a dot and a space added (+1 char)
            len_left = int(TERM_COLS) - 2 - line_visible_len
            text_part_no_color = text_fmt.format(join_oracle_texts(
                card, (trunc_text if trunc_text != 'auto' else False), colorize = False))
            future_len = line_visible_len + len(text_part_no_color)
            if future_len > int(TERM_COLS) - 2:
                # TODO find a way to count for invisible chars
                # Note: this is not perfect because some invisible char are already inside the text,
                #       so the text will be shorter than expected
                text_part_colored = text_part_colored[:len_left]+'…'+'\033[0m'

        text_part_colored = colorize_mana(text_part_colored)
        line += text_part_colored

    if not return_str:
        print(line)

    return line

def assist_ramp_cards(cards, land_types_invalid_regex):
    """Show pre-selected ramp cards organised by features, for the user to select some"""

    cards_ramp_cards = []
    for card in cards:
        if card['name'] not in ["Strata Scythe", "Trench Gorger"]:
            oracle_texts = list(get_oracle_texts(card))
            oracle_texts_low = list(map(str.lower, oracle_texts))
            if (list(search_strings(RAMP_CARDS_REGEX, oracle_texts_low))
                    and not list(search_strings(RAMP_CARDS_EXCLUDE_REGEX, oracle_texts_low))
                    and not list(search_strings(land_types_invalid_regex, oracle_texts_low))
                    # and not list(search_strings(r'(you|target player|opponent).*discard',
                    #                             oracle_texts_low))
                    # and not list(in_strings('graveyard', oracle_texts_low))
                    and not filter_lands(card)):
                cards_ramp_cards.append(card)
    cards_ramp_cards = list(sorted(cards_ramp_cards, key=lambda c: c['cmc']))
    print('Ramp cards:', len(cards_ramp_cards))
    for card in cards_ramp_cards:
        print_card(card)
    print('')

    return cards_ramp_cards

def assist_draw_cards(cards, land_types_invalid_regex):
    """Show pre-selected draw cards organised by features, for the user to select some"""

    cards_draw_cards = []
    cards_draw_cards_repeating = []
    cards_draw_cards_multiple = []
    if DRAW_CARDS_REGEX:
        for card in cards:
            oracle_texts = list(get_oracle_texts(card))
            oracle_texts_low = list(map(str.lower, oracle_texts))
            for regexp in DRAW_CARDS_REGEX:
                if (list(search_strings(regexp, oracle_texts_low))
                        and not list(search_strings(DRAW_CARDS_EXCLUDE_REGEX, oracle_texts_low))
                        and not list(search_strings(land_types_invalid_regex, oracle_texts_low))
                        # and not list(search_strings(r'(you|target player|opponent).*discard',
                        #                             oracle_texts_low))
                        # and not list(in_strings('graveyard', oracle_texts_low))
                        and not filter_lands(card)):
                    cards_draw_cards.append(card)

                    if (list(search_strings(r'(whenever|everytime|at begining|upkeep|\\{t\\}:)',
                                           oracle_texts_low))
                            and not list(in_strings("next turn's upkeep", oracle_texts_low))
                            and not list(in_strings('Sacrifice '+card['name'], oracle_texts))
                            and not list(search_strings(
                                r'whenever [^.]+ deals combat damage to a player',
                                oracle_texts_low))):
                        cards_draw_cards_repeating.append(card)

                    elif list(search_strings(r'draws? (two|three|four|five|six|seven|X) ',
                                             oracle_texts_low)):
                        cards_draw_cards_multiple.append(card)
                    break
    cards_draw_cards = list(sorted(cards_draw_cards, key=lambda c: c['cmc']))
    print('Draw cards:', len(cards_draw_cards))
    print('')

    cards_draw_cards_not_repeating_cmc_3 = order_cards_by_cmc_and_name(list(filter(
        lambda c: int(c['cmc']) <= 3,
        [c for c in cards_draw_cards if c not in cards_draw_cards_repeating
         and c not in cards_draw_cards_multiple])))

    connives = list(filter(lambda c: bool(list(in_strings('connives',
                                                          map(str.lower, get_oracle_texts(c))))),
                           cards))

    print('Draw cards (repeating):', len(cards_draw_cards_repeating))
    print('')
    for card in order_cards_by_cmc_and_name(cards_draw_cards_repeating):
        print_card(card)
    print('')

    print('Draw cards (multiple):',
          len(cards_draw_cards_multiple))
    print('')
    for card in order_cards_by_cmc_and_name(cards_draw_cards_multiple):
        print_card(card)
    print('')

    print('Draw cards (connives):',
          len(connives))
    print('')
    for card in order_cards_by_cmc_and_name(connives):
        print_card(card)
    print('')

    print('Draw cards (not repeating, CMC <= 3):',
          len(cards_draw_cards_not_repeating_cmc_3))
    print('')
    for card in order_cards_by_cmc_and_name(cards_draw_cards_not_repeating_cmc_3):
        print_card(card)
    print('')

    return cards_draw_cards

def assist_tutor_cards(cards, land_types_invalid_regex):
    """Show pre-selected tutor cards organised by features, for the user to select some"""

    cards_tutor_cards = []
    for card in cards:
        if 'tutor' in card['name'].lower():
            cards_tutor_cards.append(card)
        elif TUTOR_CARDS_REGEX:
            oracle_texts = list(get_oracle_texts(card))
            oracle_texts_low = list(map(str.lower, oracle_texts))
            card_found = False
            for regexp in TUTOR_CARDS_REGEX:
                if (list(search_strings(regexp, oracle_texts_low))
                        and not list(search_strings(TUTOR_CARDS_EXCLUDE_REGEX, oracle_texts_low))
                        and not list(search_strings(land_types_invalid_regex, oracle_texts_low))
                        and not filter_lands(card)):
                    cards_tutor_cards.append(card)
                    card_found = True
                    break
            if not card_found and TUTOR_CARDS_JOIN_TEXTS_REGEX:
                for regexp in TUTOR_CARDS_JOIN_TEXTS_REGEX:
                    if (re.search(regexp, join_oracle_texts(card).lower())
                            and not list(search_strings(TUTOR_CARDS_EXCLUDE_REGEX, oracle_texts_low))
                            and not list(search_strings(land_types_invalid_regex, oracle_texts_low))
                            and not filter_lands(card)):
                        cards_tutor_cards.append(card)
                        card_found = True
                        break

    # filter out not generic enough cards
    cards_tutor_cards_generic = list(filter(
        lambda c: (not list(search_strings(TUTOR_GENERIC_EXCLUDE_REGEX,
                                          map(str.lower, get_oracle_texts(c))))
                   or (re.search(TUTOR_GENERIC_EXCLUDE_REGEX, c['name'].lower())
                       and list(in_strings('When '+c['name']+' enters the battlefield',
                                           get_oracle_texts(c))))),
        cards_tutor_cards))

    # regroup some cards by theme
    cards_tutor_cards_against = list(filter(
        lambda c: (list(in_strings_excludes(
                        'opponent',
                        ['opponent choose', 'choose an opponent', 'opponent gains control',
                         'opponent looks at'],
                        map(str.lower, get_oracle_texts(c))))
                   or list(in_strings('counter target', map(str.lower, get_oracle_texts(c))))
                   or list(in_strings('destroy', map(str.lower, get_oracle_texts(c))))),
        cards_tutor_cards_generic))
    cards_tutor_cards_aura = list(filter(
        lambda c: list(in_strings_exclude('Aura', 'Auramancers', get_oracle_texts(c))),
        cards_tutor_cards_generic))
    cards_tutor_cards_arcane = list(filter(
        lambda c: list(in_strings('Arcane', get_oracle_texts(c))),
        cards_tutor_cards_generic))
    cards_tutor_cards_equipment = list(filter(
        lambda c: list(in_strings('Equipment', get_oracle_texts(c))),
        cards_tutor_cards_generic))
    cards_tutor_cards_artifact = list(filter(
        lambda c: list(in_strings_excludes(
            'artifact', ['artifact and/or', 'artifact or', 'artifact, creature'],
            map(str.lower, get_oracle_texts(c)))),
        [c for c in cards_tutor_cards_generic if c not in cards_tutor_cards_equipment]))
    cards_tutor_cards_transmute = list(filter(
        lambda c: list(in_strings('transmute', map(str.lower, get_oracle_texts(c)))),
        [c for c in cards_tutor_cards_generic if c not in cards_tutor_cards_equipment]))
    cards_tutor_cards_graveyard = list(filter(
        lambda c: c['name'] != 'Dark Petition' and list(in_strings_excludes(
            'graveyard', ["if you don't, put it into", 'graveyard from play',
                          'the other into your graveyard', 'cast from a graveyard'],
            map(str.lower, get_oracle_texts(c)))),
        cards_tutor_cards_generic))

    cards_tutor_cards_themed = (
            cards_tutor_cards_against
            + cards_tutor_cards_aura
            + cards_tutor_cards_arcane
            + cards_tutor_cards_equipment
            + cards_tutor_cards_artifact
            + cards_tutor_cards_transmute
            + cards_tutor_cards_graveyard)
    cards_tutor_cards_not_themed = [
        c for c in cards_tutor_cards_generic if c not in cards_tutor_cards_themed]

    cards_tutor_cards_to_battlefield = list(filter(
        lambda c: list(in_strings('onto the battlefield', map(str.lower, get_oracle_texts(c)))),
        cards_tutor_cards_not_themed))
    cards_tutor_cards_to_hand = list(filter(
        lambda c: list(in_strings('hand', map(str.lower, get_oracle_texts(c)))),
        [c for c in cards_tutor_cards_not_themed if c not in cards_tutor_cards_to_battlefield]))
    cards_tutor_cards_to_top_library = list(filter(
        lambda c: (list(in_strings('that card on top', map(str.lower, get_oracle_texts(c))))
                   or list(in_strings('third from the top', map(str.lower, get_oracle_texts(c))))),
        [c for c in cards_tutor_cards_not_themed if c not in cards_tutor_cards_to_battlefield
         and c not in cards_tutor_cards_to_hand]))
    cards_tutor_cards_other = [
        c for c in cards_tutor_cards_not_themed if c not in cards_tutor_cards_to_battlefield
        and c not in cards_tutor_cards_to_hand and c not in cards_tutor_cards_to_top_library]

    print('Tutor cards:', len(cards_tutor_cards))
    print('')
    print('   Tutor cards (not generic enough):',
          len(cards_tutor_cards) - len(cards_tutor_cards_generic))
    print('')
    print('   Tutor cards (not themed):', len(cards_tutor_cards_not_themed))
    print('')
    print('      Tutor cards (not themed, to battlefield):', len(cards_tutor_cards_to_battlefield))
    print('')
    for card in order_cards_by_cmc_and_name(cards_tutor_cards_to_battlefield):
        print_card(card, indent = 5)
    print('')
    print('      Tutor cards (not themed, to hand):', len(cards_tutor_cards_to_hand))
    print('')
    for card in order_cards_by_cmc_and_name(cards_tutor_cards_to_hand):
        print_card(card, indent = 5)
    print('')
    print('      Tutor cards (not themed, to top of library):',
          len(cards_tutor_cards_to_top_library))
    print('')
    for card in order_cards_by_cmc_and_name(cards_tutor_cards_to_top_library):
        print_card(card, indent = 5)
    print('')
    print('      Tutor cards (not themed, other):', len(cards_tutor_cards_other))
    print('')
    for card in order_cards_by_cmc_and_name(cards_tutor_cards_other):
        print_card(card, indent = 5)
    print('')

    print('   Tutor cards (themed):', len(cards_tutor_cards_themed))
    print('')
    print('      Tutor cards (themed, against):', len(cards_tutor_cards_against))
    print('')
    for card in order_cards_by_cmc_and_name(cards_tutor_cards_against):
        print_card(card, indent = 5)
    print('')
    print('      Tutor cards (themed, transmute):', len(cards_tutor_cards_transmute))
    print('')
    for card in order_cards_by_cmc_and_name(cards_tutor_cards_transmute):
        print_card(card, indent = 5)
    print('')
    print('      Tutor cards (themed, artifact):', len(cards_tutor_cards_artifact))
    print('')
    for card in order_cards_by_cmc_and_name(cards_tutor_cards_artifact):
        print_card(card, indent = 5)
    print('')
    print('      Tutor cards (themed, graveyard):', len(cards_tutor_cards_graveyard))
    print('')
    print('      Tutor cards (themed, Equipment):', len(cards_tutor_cards_equipment))
    print('')
    print('      Tutor cards (themed, Aura):', len(cards_tutor_cards_aura))
    print('')
    print('      Tutor cards (themed, Arcane):', len(cards_tutor_cards_arcane))
    print('')

    return cards_tutor_cards

def assist_removal_cards(cards):
    """Show pre-selected removal cards organised by features, for the user to select some"""

    cards_removal = []
    if REMOVAL_CARDS_REGEX:
        for card in cards:
            oracle_texts = list(get_oracle_texts(card))
            oracle_texts_filtered = list(map(lambda t: (
                t.replace('(Then exile this card. You may cast the creature later from exile.)', '')
                 .replace('(Then exile this card. You may cast the artifact later from exile.)', '')
                 .replace("(Effects that say "+'"destroy"'+" don't destroy this artifact.)", '')
                 .replace("(Damage and effects that say "+'"destroy"'+" don't destroy them.)", '')
                 .replace("(Damage and effects that say "+'"destroy"'+" don't destroy it.)", '')
                 .replace("(Any amount of damage it deals to a creature is enough to destroy it.)",
                          '')
                 .replace("(You may cast this spell for its cleave cost. If you do, remove the"+
                          " words in square brackets.)", '')
                 .replace("(If you discard this card, discard it into exile. When you do, cast it"+
                          " for its madness cost or put it into your graveyard.)", '')
                 .replace('(You may cast this card from your graveyard for its flashback cost. '+
                          'Then exile it.)', '')
                 .replace('(You may cast this card from your graveyard for its flashback cost '+
                          'and any additional costs. Then exile it.)', '')
                 .replace('Exile this Saga, then return it to the battlefield transformed', '')
                 .replace('Exile '+card['name'], '')
                 .replace('destroy '+card['name'], '')
                 .replace('If '+card['name']+' would be put into a graveyard from anywhere, '+
                          'exile it instead.', '')),
                oracle_texts))
            if 'card_faces' in card:
                for face in card['card_faces']:
                    oracle_texts_filtered = list(map(lambda t: (
                        t.replace('Exile '+face['name'], '')
                         .replace('destroy '+face['name'], '')
                         .replace('If '+face['name']+' would be put into a graveyard from anywhere'+
                                  ', exile it instead.', '')),
                        oracle_texts_filtered))
            oracle_texts_low = list(map(str.lower, oracle_texts_filtered))
            for regexp in REMOVAL_CARDS_REGEX:
                if (list(search_strings(regexp, oracle_texts_low))
                        and not list(search_strings(REMOVAL_CARDS_EXCLUDE_REGEX,
                                                    oracle_texts_low))):
                    cards_removal.append(card)
                    break

    cards_removal_cmc_3 = list(filter(lambda c: c['cmc'] <= 3, cards_removal))

    cards_removal_cmc_3_destroy_land = list(filter(lambda c: bool(list(
        search_strings('destroy target (nonbasic )?land', map(str.lower, get_oracle_texts(c))))),
        cards_removal_cmc_3))
    cards_removal_cmc_3_not_destroy_land = [
        c for c in cards_removal_cmc_3 if c not in cards_removal_cmc_3_destroy_land]

    # group by target type
    cards_removal_cmc_3_destroy_permanent = list(filter(lambda c: bool(list(
        search_strings(r'(destroy|exile) target (\w+ )?permanent',
                       map(str.lower, get_oracle_texts(c))))),
        cards_removal_cmc_3_not_destroy_land))
    cards_removal_cmc_3_destroy_three = list(filter(lambda c: bool(list(
        search_strings(r'(destroy|exile) target (\w+ )?('
                       + 'creature.* enchantment.* artifact'
                       +'|creature.* artifact.* enchantment'
                       +'|enchantment.* creature.* artifact'
                       +'|enchantment.* artifact.* creature'
                       +'|artifact.* enchantment.* creature'
                       +'|artifact.* creature.* enchantment)',
                       map(str.lower, get_oracle_texts(c))))),
        cards_removal_cmc_3_not_destroy_land))
    cards_removal_cmc_3_destroy_two = list(filter(lambda c: bool(list(
        search_strings(r'(destroy|exile) target (\w+ )?('
                       + 'creature.* enchantment'
                       +'|creature.* artifact'
                       +'|enchantment.* creature'
                       +'|enchantment.* artifact'
                       +'|artifact.* enchantment'
                       +'|artifact.* creature)',
                       map(str.lower, get_oracle_texts(c))))),
        [c for c in cards_removal_cmc_3_not_destroy_land
         if c not in cards_removal_cmc_3_destroy_three]))
    cards_removal_cmc_3_destroy_creature = list(filter(lambda c: bool(list(
        search_strings(r'(destroy|exile) target (\w+ )?creature',
                       map(str.lower, get_oracle_texts(c))))),
        cards_removal_cmc_3_not_destroy_land))
    cards_removal_cmc_3_destroy_creature_no_sacrifice = list(filter(lambda c: bool(list(
        not_in_strings_exclude('as an additional cost to cast this spell, sacrifice a creature',
                               'sacrifice a creature or discard',
                               map(str.lower, get_oracle_texts(c))))),
        cards_removal_cmc_3_destroy_creature))
    cards_removal_cmc_3_destroy_creature_no_exclusion = list(filter(lambda c: bool(list(
        search_strings(r'([Dd]estroy|[Ee]xile) target creature( or \w+)?( an opponent controls)?\.',
                       get_oracle_texts(c)))),
        cards_removal_cmc_3_destroy_creature_no_sacrifice))
    cards_removal_cmc_3_destroy_creature_exclusion = [
        c for c in cards_removal_cmc_3_destroy_creature
        if c not in cards_removal_cmc_3_destroy_creature_no_exclusion]
    cards_removal_cmc_3_destroy_enchantment = list(filter(lambda c: bool(list(
        search_strings(r'(destroy|exile) target (\w+ )?enchantment',
                       map(str.lower, get_oracle_texts(c))))),
        cards_removal_cmc_3_not_destroy_land))
    cards_removal_cmc_3_destroy_other = [
        c for c in cards_removal_cmc_3_not_destroy_land
        if c not in cards_removal_cmc_3_destroy_permanent
        and c not in cards_removal_cmc_3_destroy_three
        and c not in cards_removal_cmc_3_destroy_two
        and c not in cards_removal_cmc_3_destroy_creature
        and c not in cards_removal_cmc_3_destroy_enchantment]

    print('Removal cards:', len(cards_removal))
    print('')
    print('   Removal cards (CMC <= 3, not destroy land):',
          len(cards_removal_cmc_3_not_destroy_land))
    print('')
    print('      Removal cards (CMC <= 3, destroy permanent):',
          len(cards_removal_cmc_3_destroy_permanent))
    print('')
    for card in order_cards_by_cmc_and_name(cards_removal_cmc_3_destroy_permanent):
        print_card(card, indent = 5, trunc_text = False)
    print('')
    print('      Removal cards (CMC <= 3, destroy three choices):',
          len(cards_removal_cmc_3_destroy_three))
    print('')
    for card in order_cards_by_cmc_and_name(cards_removal_cmc_3_destroy_three):
        print_card(card, indent = 5, trunc_text = False)
    print('')
    print('      Removal cards (CMC <= 3, destroy two choices):',
          len(cards_removal_cmc_3_destroy_two))
    print('')
    for card in order_cards_by_cmc_and_name(cards_removal_cmc_3_destroy_two):
        print_card(card, indent = 5, trunc_text = False)
    print('')
    print('      Removal cards (CMC <= 3, destroy creature, sacrifice one):',
          len(cards_removal_cmc_3_destroy_creature)
          - len(cards_removal_cmc_3_destroy_creature_no_sacrifice))
    print('')
    print('      Removal cards (CMC <= 3, destroy creature, no exclusion):',
          len(cards_removal_cmc_3_destroy_creature_no_exclusion))
    print('')
    for card in order_cards_by_cmc_and_name(cards_removal_cmc_3_destroy_creature_no_exclusion):
        print_card(card, indent = 5, trunc_text = False)
    print('')
    print('      Removal cards (CMC <= 3, destroy creature, exclusion):',
          len(cards_removal_cmc_3_destroy_creature_exclusion))
    print('')
    for card in order_cards_by_cmc_and_name(cards_removal_cmc_3_destroy_creature_exclusion):
        print_card(card, indent = 5, trunc_text = False)
    print('')
    print('      Removal cards (CMC <= 3, destroy enchantments):',
          len(cards_removal_cmc_3_destroy_enchantment))
    print('')
    for card in order_cards_by_cmc_and_name(cards_removal_cmc_3_destroy_enchantment):
        print_card(card, indent = 5, trunc_text = False)
    print('')
    print('      Removal cards (CMC <= 3, destroy other):',
          len(cards_removal_cmc_3_destroy_other))
    print('')
    for card in order_cards_by_cmc_and_name(cards_removal_cmc_3_destroy_other):
        print_card(card, indent = 5, trunc_text = False)
    print('')

    return cards_removal

def assist_best_cards(cards, limit = 10):
    """Show pre-selected best cards organised by features, for the user to select some"""

    best_cards = []

    # Best creature power-to-cmc
    power_to_cmc = {}
    for card in cards:
        if 'card_faces' in card:
            for face in card['card_faces']:
                if 'power' in face and 'cmc' in face and '*' not in face['power']:
                    power = float(face['power'])
                    cmc = float(face['cmc']) if float(face['cmc']) > 1 else 1.0
                    ratio = round(power / cmc, 3)
                    if ratio not in power_to_cmc:
                        power_to_cmc[ratio] = []
                    power_to_cmc[ratio].append(card)
        else:
            if 'power' in card and 'cmc' in card and '*' not in card['power']:
                power = float(card['power'])
                cmc = float(card['cmc']) if float(card['cmc']) > 1 else 1.0
                ratio = round(power / cmc, 3)
                if ratio not in power_to_cmc:
                    power_to_cmc[ratio] = []
                power_to_cmc[ratio].append(card)
    power_to_cmc = dict(sorted(power_to_cmc.items(), reverse = True))
    print('Best Power to CMC ratio:')
    print('')
    ratio_count = 0
    for ratio, cards_list in power_to_cmc.items():
        print('  ', ratio)
        for card in order_cards_by_cmc_and_name(cards_list):
            print_card(card, indent = 5)
        ratio_count = ratio_count + 1
        if ratio_count > limit:
            break
    print('')

    # Best creature toughness-to-cmc
    toughness_to_cmc = {}
    for card in cards:
        if 'card_faces' in card:
            for face in card['card_faces']:
                if 'toughness' in face and 'cmc' in face and '*' not in face['toughness']:
                    toughness = float(face['toughness'])
                    cmc = float(face['cmc']) if float(face['cmc']) > 1 else 1.0
                    ratio = round(toughness / cmc, 3)
                    if ratio not in toughness_to_cmc:
                        toughness_to_cmc[ratio] = []
                    toughness_to_cmc[ratio].append(card)
        else:
            if 'toughness' in card and 'cmc' in card and '*' not in card['toughness']:
                toughness = float(card['toughness'])
                cmc = float(card['cmc']) if float(card['cmc']) > 1 else 1.0
                ratio = round(toughness / cmc, 3)
                if ratio not in toughness_to_cmc:
                    toughness_to_cmc[ratio] = []
                toughness_to_cmc[ratio].append(card)
    toughness_to_cmc = dict(sorted(toughness_to_cmc.items(), reverse = True))
    print('Best toughness to CMC ratio:')
    print('')
    ratio_count = 0
    for ratio, cards_list in toughness_to_cmc.items():
        print('  ', ratio)
        for card in order_cards_by_cmc_and_name(cards_list):
            print_card(card, indent = 5)
        ratio_count = ratio_count + 1
        if ratio_count > limit:
            break
    print('')

    # Best 5 creature power and toughness to cmc
    powr_tough_to_cmc = {}
    for card in cards:
        if 'card_faces' in card:
            for face in card['card_faces']:
                if ('toughness' in face and 'cmc' in face and '*' not in face['toughness']
                        and 'power' in face and 'cmc' in face and '*' not in face['power']):
                    power = float(face['power'])
                    toughness = float(face['toughness'])
                    cmc = float(face['cmc']) if float(face['cmc']) > 1 else 1.0
                    ratio = round((power + toughness) / cmc, 3)
                    if ratio not in powr_tough_to_cmc:
                        powr_tough_to_cmc[ratio] = []
                    powr_tough_to_cmc[ratio].append(card)
        else:
            if ('toughness' in card and 'cmc' in card and '*' not in card['toughness']
                    and 'power' in card and 'cmc' in card and '*' not in card['power']):
                power = float(card['power'])
                toughness = float(card['toughness'])
                cmc = float(card['cmc']) if float(card['cmc']) > 1 else 1.0
                ratio = round((power + toughness) / cmc, 3)
                if ratio not in powr_tough_to_cmc:
                    powr_tough_to_cmc[ratio] = []
                powr_tough_to_cmc[ratio].append(card)
    powr_tough_to_cmc = dict(sorted(powr_tough_to_cmc.items(), reverse = True))
    print('Best power+toughness to CMC ratio:')
    print('')
    ratio_count = 0
    for ratio, cards_list in powr_tough_to_cmc.items():
        print('  ', ratio)
        for card in order_cards_by_cmc_and_name(cards_list):
            print_card(card, indent = 5)
        ratio_count = ratio_count + 1
        if ratio_count > limit:
            break
    print('')

    # Best 5 creature amount of (evergreen?) keywords by cmc
    keywords_to_cmc = {}
    for card in cards:
        if 'card_faces' in card:
            for face in card['card_faces']:
                if 'keywords' in face and face['keywords'] and 'cmc' in face:
                    keywords = len(face['keywords'])
                    cmc = float(face['cmc']) if float(face['cmc']) > 1 else 1.0
                    ratio = round((keywords) / cmc, 3)
                    if ratio not in keywords_to_cmc:
                        keywords_to_cmc[ratio] = []
                    keywords_to_cmc[ratio].append(card)
        else:
            if 'keywords' in card and card['keywords'] and 'cmc' in card:
                keywords = len(card['keywords'])
                cmc = float(card['cmc']) if float(card['cmc']) > 1 else 1.0
                ratio = round(keywords / cmc, 3)
                if ratio not in keywords_to_cmc:
                    keywords_to_cmc[ratio] = []
                keywords_to_cmc[ratio].append(card)
    keywords_to_cmc = dict(sorted(keywords_to_cmc.items(), reverse = True))
    print('Best keywords count to CMC ratio:')
    print('')
    ratio_count = 0
    for ratio, cards_list in keywords_to_cmc.items():
        print('  ', ratio)
        for card in order_cards_by_cmc_and_name(cards_list):
            print_card(card, indent = 5, print_text = False, print_keywords = True)
        ratio_count = ratio_count + 1
        if ratio_count > 2:
            break
    print('')

    # Best ? creature with first|double strike and deathtouch (and flying?)
    deathtouch_strike = []
    for card in cards:
        if 'card_faces' in card:
            for face in card['card_faces']:
                if ('keywords' in face and 'Deathtouch' in face['keywords']
                        and ('Double strike' in face['keywords']
                             or 'First strike' in face['keywords'])):
                    deathtouch_strike.append(card)
        else:
            if ('keywords' in card and 'Deathtouch' in card['keywords']
                    and ('Double strike' in card['keywords']
                            or 'First strike' in card['keywords'])):
                deathtouch_strike.append(card)
    print('Best Deathtouch + First strike/Double strike:')
    print('')
    for card in order_cards_by_cmc_and_name(deathtouch_strike):
        print_card(card, indent = 5)
    print('')

    # Best 5 creature with flying and deathtouch
    deathtouch_flying = []
    for card in cards:
        if 'card_faces' in card:
            for face in card['card_faces']:
                if ('keywords' in face and 'Deathtouch' in face['keywords']
                        and 'Flying' in face['keywords']):
                    deathtouch_flying.append(card)
        else:
            if ('keywords' in card and 'Deathtouch' in card['keywords']
                    and 'Flying' in card['keywords']):
                deathtouch_flying.append(card)
    print('Best Deathtouch + Flying:')
    print('')
    for card in order_cards_by_cmc_and_name(deathtouch_flying):
        print_card(card, indent = 5)
    print('')

    # Best 5 creature with flying by power|toughness
    flying_power_to_cmc = {}
    for card in cards:
        if 'card_faces' in card:
            for face in card['card_faces']:
                if ('power' in face and 'cmc' in face and '*' not in face['power']
                        and ('keywords' in face and 'Flying' in face['keywords'])):
                    power = float(face['power'])
                    cmc = float(face['cmc']) if float(face['cmc']) > 1 else 1.0
                    ratio = round(power / cmc, 3)
                    if ratio not in flying_power_to_cmc:
                        flying_power_to_cmc[ratio] = []
                    flying_power_to_cmc[ratio].append(card)
        else:
            if ('power' in card and 'cmc' in card and '*' not in card['power']
                    and ('keywords' in card and 'Flying' in card['keywords'])):
                power = float(card['power'])
                cmc = float(card['cmc']) if float(card['cmc']) > 1 else 1.0
                ratio = round(power / cmc, 3)
                if ratio not in flying_power_to_cmc:
                    flying_power_to_cmc[ratio] = []
                flying_power_to_cmc[ratio].append(card)
    flying_power_to_cmc = dict(sorted(flying_power_to_cmc.items(), reverse = True))
    print('Best Flying + Power to CMC ratio:')
    print('')
    ratio_count = 0
    for ratio, cards_list in flying_power_to_cmc.items():
        print('  ', ratio)
        for card in order_cards_by_cmc_and_name(cards_list):
            print_card(card, indent = 5)
        ratio_count = ratio_count + 1
        if ratio_count > limit:
            break
    print('')
    flying_toughness_to_cmc = {}
    for card in cards:
        if 'card_faces' in card:
            for face in card['card_faces']:
                if ('toughness' in face and 'cmc' in face and '*' not in face['toughness']
                        and ('keywords' in face and 'Flying' in face['keywords'])):
                    toughness = float(face['toughness'])
                    cmc = float(face['cmc']) if float(face['cmc']) > 1 else 1.0
                    ratio = round(toughness / cmc, 3)
                    if ratio not in flying_toughness_to_cmc:
                        flying_toughness_to_cmc[ratio] = []
                    flying_toughness_to_cmc[ratio].append(card)
        else:
            if ('toughness' in card and 'cmc' in card and '*' not in card['toughness']
                    and ('keywords' in card and 'Flying' in card['keywords'])):
                toughness = float(card['toughness'])
                cmc = float(card['cmc']) if float(card['cmc']) > 1 else 1.0
                ratio = round(toughness / cmc, 3)
                if ratio not in flying_toughness_to_cmc:
                    flying_toughness_to_cmc[ratio] = []
                flying_toughness_to_cmc[ratio].append(card)
    flying_toughness_to_cmc = dict(sorted(flying_toughness_to_cmc.items(), reverse = True))
    print('Best Flying + toughness to CMC ratio:')
    print('')
    ratio_count = 0
    for ratio, cards_list in flying_toughness_to_cmc.items():
        print('  ', ratio)
        for card in order_cards_by_cmc_and_name(cards_list):
            print_card(card, indent = 5)
        ratio_count = ratio_count + 1
        if ratio_count > limit:
            break
    print('')

    # Best 5 instant|sorcery damage to cmc

    # Best 5 instant|sorcery wide damage to cmc

    # Best 5 copy card

    return best_cards

def print_combo_card_names(combo):
    """Print card's names of a combo"""

    card_names = []
    for num in range(1, 11):
        if combo['Card '+str(num)]:
            card_names.append(combo['Card '+str(num)])
    print(' + '.join(card_names))

def print_tup_combo(tup_combo, indent = 0, print_header = False, max_cards = 4, max_name_len = 30):
    """Print a combo"""
    c_format = '{indent:>'+str(indent)+'}{cmc_total:>9} | {cmc_max:>7} | {cmc_min:>7} | '
    c_format += ' + '.join(list(map(lambda i: '{name_'+str(i)+':^'+ str(max_name_len)+'}',
                                    range(1, max_cards + 1))))
    if print_header:
        c_params = {
            'indent': '',
            'cmc_total': 'CMC total',
            'cmc_max': 'CMC max',
            'cmc_min': 'CMC min'}
        for index in range(1, max_cards + 1):
            c_params['name_'+str(index)] = 'card '+str(index)
        c_header = c_format.format(**c_params)
        print(c_header)
    c_params = {
        'indent': '',
        'cmc_total': int(tup_combo[1]['cmc_total']),
        'cmc_max': int(tup_combo[1]['cmc_max']),
        'cmc_min': int(tup_combo[1]['cmc_min'])}
    for index, name in enumerate(tup_combo[0]):
        c_params['name_'+str(index + 1)] = truncate_text(name, max_name_len)
    c_line = c_format.format(**c_params)
    print(c_line)

def get_card(name, cards, return_face = False, strict = False):
    """Find a card by its name in a list of cards objects
       (if return_face use faces instead of cards)"""
    for card in cards:
        if card['name'] == name:
            return card
        if not strict and 'card_faces' in card:
            for face in card['card_faces']:
                if face['name'] == name:
                    if return_face:
                        return face
                    return card
    return None

def names_to_cards(names, cards, return_face = False):
    """Return a card list from a list of card names (if return_face use faces instead of cards)"""
    return list(map(lambda n: get_card(n, cards, return_face), names))

def get_combos(combos, cards, name = None, only_ok = True, combo_res_regex = None,
               max_cards = None, excludes = None):
    """Return a dict containing:
         -   key: a tuple of cards comboting together
         - value: a dict with keys: 'infos' the combo infos, 'cards' the combo's cards

       Parameters:
           name             string   a card name to match combo against
           only_ok          boolean  if 'True' ensure all combo's card belong to the given list
           cards            list     the list of cards to search in
           combo_res_regex  string   if not None add combo only if its Results matches this regex
           max_cards        int      only consider combos with at most this number of cards
           excludes         list     a list of tuple of card names to exclude
    """
    card_combos = {}
    for combo in combos:
        card_names = tuple(sorted(combo['c'])) if 'c' in combo and combo['c'] else tuple()
        if not card_names or (excludes and card_names in excludes):
            continue
        add_combo = not name or any(filter(lambda names: name in names, card_names))
        if add_combo:
            if max_cards and len(card_names) > max_cards:
                continue
            if len(card_names) <= 1:
                print('Warning: skipping following combo because it only has 1 card.',
                      card_names, file=sys.stderr)
                continue
            if name:
                card_names = tuple((name, *(sorted(set(card_names) - {name}))))
            combo_cards = names_to_cards(card_names, cards, return_face = True)
            combo_cards_not_found = any(map(lambda c: c is None, combo_cards))
            if combo_cards_not_found:
                if only_ok:
                    continue
                print('Warning: skipping following combo because of card not found.',
                      card_names, file=sys.stderr)
                continue
            if combo_res_regex and not (combo['r']
                    and re.search(combo_res_regex, combo['r'].lower())):
                continue
            card_combos[card_names] = {'infos': combo,
                                       'cards': order_cards_by_cmc_and_name(combo_cards)}
            analyse_combo(card_combos[card_names])
    return card_combos

def get_nx_graph(cards_relations):
    """Return an nx.Graph instance build from the cards relations"""

    nx_graph = nx.Graph()
    card_ids = {}
    card_id = 0
    for name in cards_relations:
        card_ids[name] = card_id
        nx_graph.add_node(card_id, card=name)
        card_id = card_id + 1

    for name, relations in cards_relations.items():
        card_id = card_ids[name]
        for relation in relations:
            target_id = card_ids[relation]
            nx_graph.add_edge(card_id, target_id)

    return nx_graph

def k_core_cards(nx_graph, max_k = 20):
    """Return a tuple:
        * the k-core nodes matching the lowest k
        * the k lowest number returning nodes
        * the number of k-core nodes
    """
    prev_k = 0
    prev_nodes = []
    prev_nodes_len = 0
    for k in range(1, max_k):
        nodes = nx.k_core(nx_graph, k=k).nodes()
        nodes_len = len(nodes)
        if not nodes_len:
            break
        prev_k = k
        prev_nodes = nodes
        prev_nodes_len = nodes_len
    return (prev_nodes, prev_k, prev_nodes_len)

def export_gexf(cards_relations):
    """Export to a gexf file the cards relations specified"""

    date_text = datetime.utcnow().strftime('%Y-%m-%d+%H:%M')
    xml_header =('<?xml version="1.0" encoding="UTF-8"?>'+"\n"
                +'<gexf xmlns:viz="http:///www.gexf.net/1.1draft/viz" version="1.1" '+
                    'xmlns="http://www.gexf.net/1.1draft">'+"\n"
                +"\t"+'<meta lastmodifieddate="'+date_text+'">'+"\n"
                +"\t"+"\t"+'<creator>MTG Deck Build by Michael Bideau</creator>'+"\n"
                +"\t"+'</meta>'+"\n"
                +"\t"+'<graph defaultedgetype="undirected" idtype="string" type="static">'+"\n"
                +"\t"+"\t"+'<nodes count="'+str(len(cards_relations))+'">"'+"\n")
    card_ids = {}
    with open('/tmp/combo_cards.gexf', 'w', encoding='utf-8') as f_write:
        f_write.write(xml_header)
        card_id = 0.0
        for name in cards_relations:
            card_ids[name] = card_id
            f_write.write("\t"+"\t"+"\t"+'<node id="'+str(card_id)+'" label="'+name+'"/>'+"\n")
            card_id = card_id + 1
        f_write.write("\t"+"\t"+'</nodes>'+"\n")
        edge_id = 0
        edges_lines = []
        for name, relations in cards_relations.items():
            card_id = card_ids[name]
            for relation in relations:
                target_id = card_ids[relation]
                edges_lines.append(
                    "\t"+"\t"+"\t"+'<edge id="'+str(edge_id)+'" source="'+str(card_id)+'" '+
                    'target="'+str(target_id)+'"/>')
                edge_id = edge_id + 1
        edges_tag = "\t"+"\t"+'<edges count="'+str(len(edges_lines))+'">'+"\n"
        f_write.write(edges_tag)
        f_write.write("\n".join(edges_lines)+"\n")
        f_write.write("\t"+"\t"+'</edges>'+"\n")
        f_write.write("\t"+'</graph>'+"\n")
        f_write.write('</gexf>')

# def combo_replace_effects_by_cards(combos, cards_list):
#     """Return a copy of combos dict with effects (value) replaced by the list of cards
#        matching the card names (key)"""
#
#     new_combos = {}
#     for names in combos.keys():
#         new_combos[names] = names_to_cards(names, cards_list)
#     return new_combos

def analyse_combo(combo):
    """Return a dict of a combo with added following attributes to its values:
       cards_count: the number of cards in the combo
           cmc_min: the CMC cost of the least expensive cards in the combo
           cmc_max: the CMC cost of the most expensive cards in the combo
         cmc_total: the combo with the total CMC cost specified

        Arguments:
            combos  dict   value={'infos': combos infos, 'cards': cards}
    """
    cmc_min = 99999999999999
    cmc_max = 0
    cmc_total = 0
    for card_or_face in combo['cards']:
        if 'cmc' in card_or_face:
            cmc_min = min(cmc_min, card_or_face['cmc'])
            cmc_max = max(cmc_max, card_or_face['cmc'])
            cmc_total = cmc_total + float(card_or_face['cmc'])
    combo['cards_count'] = len(combo['cards'])
    combo['cmc_min'] = cmc_min if cmc_min != 99999999999999 else 0
    combo['cmc_max'] = cmc_max
    combo['cmc_total'] = cmc_total
    return combo

def colorize_mana(text, no_braces = False):
    """Return the text with colorized mana"""
    colorized_text = text
    for letter, color in COLOR_NAME.items():
        if no_braces:
            colorized_text = colorized_text.replace(letter, colored(letter, color))
        else:
            colorized_text = colorized_text.replace('{'+letter+'}', colored('{'+letter+'}', color))
    if not no_braces:
        colorized_text = re.sub(r'(\{\d\})', colored(r'\1', COLOR_NAME['C']), colorized_text)
        colorized_text = re.sub(r'(\{\w/\w\})', colored(r'\1', COLOR_NAME['C']), colorized_text)
    return colorized_text

def colorize_ability(text, color = 'white', bold = False, dark = True):
    """Return the text with abilities colorized"""
    extraopts = {'attrs': []} if bold or dark else {}
    if bold:
        extraopts['attrs'].append('bold')
    if dark:
        extraopts['attrs'].append('dark')
    colorized_text = text
    colorized_text = re.sub(r'(^|\n)([^—\n]+( \d|\{\w\})?)( *—)',
                            r'\1'+colored(r'\2', color, **extraopts)+r'\4', colorized_text)
    # colorized_text = re.sub(r'(^|\n)(\w+( \d|\{\w\})?)( *\()',
    #                        r'\1'+colored(r'\2', color, **extraopts)+r'\4', colorized_text)
    colorized_text = re.sub('('+COLORIZE_KEYWORD_REGEX_PART+r'( \d)?)+( *)(\{|\(|\.|,|$|\n)',
                            colored(r'\1', color, **extraopts)+r'\4\5', colorized_text)
    return colorized_text

def get_card_colored(card):
    """"Return the card's color"""
    card_color_letter = 'C'
    if 'color_identity' in card and card['color_identity']:
        card_color_letter = card['color_identity'][0]
        if len(card['color_identity']) > 1:
            card_color_letter = 'M'
    elif 'produced_mana' in card and card['produced_mana']:
        card_color_letter = card['produced_mana'][0]
        if len(card['produced_mana']) > 1:
            card_color_letter = 'M'
    return COLOR_NAME[card_color_letter]

def main():
    """Main program"""
    global COMMANDER_NAME
    global COMMANDER_COLOR_IDENTITY
    global COMMANDER_COLOR_IDENTITY_COUNT
    global XMAGE_COMMANDER_CARDS_BANNED
    global TERM_COLS
    global TERM_LINES

    parser = ArgumentParser(
        prog='MTG Deck Science',
        description='Generate a deck base, and make suggestion for an existing deck',
        epilog='Enjoy !')

    parser.add_argument('commander_name')
    parser.add_argument('deck_path', nargs='?', help='an existing deck')
    args = parser.parse_args()

    COMMANDER_NAME = args.commander_name

    if sys.stdout.isatty():  # in a terminal
        TERM_COLS, TERM_LINES = os.get_terminal_size()

    XMAGE_COMMANDER_CARDS_BANNED = get_xmage_commander_banned_list()

    scryfall_bulk_data = get_scryfall_bulk_data()
    scryfall_cards_db_json_file = get_scryfall_cards_db(scryfall_bulk_data)

    with open(scryfall_cards_db_json_file, "r", encoding="utf8") as r_file:
        cards = json.load(r_file)

        # TODO Add a parameter to exclude MTG sets by name or code

        total_cards = len(cards)
        #print_all_cards_stats(cards, total_cards)

        # for name in ['War of the Last Alliance', 'Wall of Shards', 'Vexing Sphinx', 'Mistwalker',
        #              'Pixie Guide', 'Library of Lat-Nam', 'Time Beetle', "Mastermind's Acquisition",
        #              'Dark Petition', 'Sky Skiff', 'Bloodvial Purveyor', 'Battlefield Raptor',
        #              'Plumeveil', 'Sleep-Cursed Faerie', 'Path of Peril', 'Sadistic Sacrament',
        #              'Incisor Glider',]:
        #     card = get_card(name, cards, strict = True)
        #     print_card(card, print_type = False)
        # sys.exit(0)

        print('')
        print('')
        print('### Commander card ###')
        print('')

        commander_card = list(filter(lambda c: c['name'] == COMMANDER_NAME, cards))[0]
        if not commander_card:
            print("Error: failed to find the commander card '", COMMANDER_NAME, "'")
            sys.exit(1)

        # display image (if terminal is sixel compatible, see https://www.arewesixelyet.com)
        if sys.stdout.isatty():  # in a terminal
            imgpath, imgwidth, imgheight = get_card_image(commander_card, imgformat = 'normal')
            extraopts = {}
            if imgwidth is not None and imgheight is not None:
                extraopts['w'] = imgwidth
                extraopts['h'] = imgheight
            # print('Image width:', imgwidth)
            # print('Term columns:', TERM_COLS)
            sys.stdout.flush()
            sys.stderr.flush()
            if TERM_COLS > 100:
                img_writer = sixel.SixelWriter()
                # img_writer.save_position(sys.stdout)
                # img_writer.move_y(1, False, sys.stdout)
                cell_x = int(TERM_COLS / 2) - 3
                #img_writer.move_x(cell_x, True, sys.stdout)
                extraopts['x'] = cell_x
                extraopts['absolute'] = True
                img_writer.draw(imgpath, **extraopts)
                for index in range(1, 19):
                    print('\033[3A')  # move one line up
                # print('\033[')  # reset
                # img_writer.restore_position(sys.stdout)
                # for index in range(1, 4):  # move 3 lines down
                #     print('')
                print('')
            else:
                img_writer = converter.SixelConverter(imgpath, **extraopts)
                img_writer.write(sys.stdout)

        commander_color_identity = commander_card['color_identity']
        if not COMMANDER_COLOR_IDENTITY:
            COMMANDER_COLOR_IDENTITY = set(commander_card['color_identity'])
        COMMANDER_COLOR_IDENTITY_COUNT = len(COMMANDER_COLOR_IDENTITY)
        commander_colors = commander_card['colors']
        commander_mana_cost = commander_card['mana_cost']
        commander_mana_cmc = commander_card['cmc']
        commander_type = commander_card['type_line']
        commander_keywords = commander_card['keywords']
        if not commander_keywords:
            commander_keywords = COMMANDER_KEYWORDS
        commander_keywords = set(commander_keywords)
        commander_text = commander_card['oracle_text']
        commander_combos_features = []
        commander_features_match = re.finditer(COMMANDER_FEATURES_REGEX, commander_text)
        # print('DEBUG', 'commander_features_match', commander_features_match, file=sys.stderr)
        for match in commander_features_match:
            # print('DEBUG', 'commander_features match', match, file=sys.stderr)
            ability = match[0].lower()
            if ability and ability not in commander_combos_features:
                commander_combos_features.append(ability)
        commander_combos_regex = '(win|'+('|'.join(commander_combos_features))+')'

        commander_color_name = get_card_colored(commander_card)

        print('Commander:', colored(COMMANDER_NAME, commander_color_name))
        print(' Identity:', ','.join(list(map(lambda t: colorize_mana(t, no_braces = True),
                                              commander_color_identity))))
        print('   Colors:', ','.join(list(map(lambda t: colorize_mana(t, no_braces = True),
                                              commander_colors))))
        print('     Mana:', colorize_mana(commander_mana_cost), '(CMC:'+str(commander_mana_cmc)+')')
        print('     Type:', colored(commander_type, commander_color_name))
        print(' Keywords:', commander_card['keywords'], '+', COMMANDER_KEYWORDS)
        print('     Text:', commander_text)
        print('Combo exp:', commander_combos_regex)

        print('')
        print('')
        print('### Stats for this deck ###')
        print('')

        # invalid colors
        compute_invalid_colors()
        prev_total_cards = total_cards
        cards_valid_colors = list(filter(filter_colors, cards))
        new_total_cards = len(cards_valid_colors)
        print('Invalid colors', ','.join(list(map(lambda t: colorize_mana(t, no_braces = True),
                                                  INVALID_COLORS))),
              ':', prev_total_cards - new_total_cards)
        print('')

        # all filters
        prev_total_cards = total_cards
        cards_ok = list(filter(filter_all_at_once, cards))
        total_cards_ok = len(cards_ok)
        print('Filtered cards:', prev_total_cards - total_cards_ok)
        print('')
        print('Cards OK:', total_cards_ok)
        print('')

        # max price
        no_price_eur_ok = len(list(filter(lambda c: not c['prices']['eur'], cards_ok)))
        no_price_usd_ok = len(list(filter(lambda c: not c['prices']['usd'], cards_ok)))
        max_price_eur_ok = max(map(lambda c: float(c['prices']['eur'] or 0), cards_ok))
        max_price_usd_ok = max(map(lambda c: float(c['prices']['usd'] or 0), cards_ok))
        print('No price EUR:', no_price_eur_ok)
        print('No price USD:', no_price_usd_ok)
        print('Price max EUR:', max_price_eur_ok)
        print('Price max USD:', max_price_usd_ok)
        print('')

        # no text
        prev_total_cards = total_cards_ok
        cards_with_text_ok = list(filter(filter_no_text, cards_ok))
        new_total_cards = len(cards_with_text_ok)
        print('Without text:', prev_total_cards - new_total_cards)
        print('')

        # no keywords
        prev_total_cards = total_cards_ok
        cards_with_keywords_ok = list(filter(filter_no_keywords, cards_ok))
        new_total_cards = len(cards_with_keywords_ok)
        print('Without keywords:', prev_total_cards - new_total_cards)
        print('')

        # no text and no keywords
        prev_total_cards = total_cards_ok
        cards_with_keywords_or_text_ok = list(
                filter(lambda c: filter_no_keywords(c) or filter_no_text(c), cards_ok))
        new_total_cards = len(cards_with_keywords_or_text_ok)
        print('Without keywords and text:', prev_total_cards - new_total_cards)


        print('')
        print('')
        print('### Deck building ###')
        print('')

        # combo
        combos = get_commanderspellbook_combos()
        print('DEBUG Combos database:', len(combos))
        print('')

        combos_effects = []
        for combo in combos:
            if 'r' in combo and combo['r']:
                for line in combo['r'].replace('. ', '\n').split('\n'):
                    line_striped = line.strip()
                    if line_striped and line_striped not in combos_effects:
                        combos_effects.append(line_striped)
        print('DEBUG Combos effects:', len(combos_effects))
        print('')
        # for effect in combos_effects:
        #     print('   ', effect)

        # rank 1
        commander_combos = get_combos(combos, cards, name = COMMANDER_NAME, only_ok = False)
        commander_combos_ok = get_combos(combos, cards_ok, name = COMMANDER_NAME)
        commander_combos_filtered = get_combos(combos, cards_ok, name = COMMANDER_NAME,
                                               combo_res_regex = commander_combos_regex)

        commander_combos_filtered_2_cards = {
            k: v for k, v in commander_combos_filtered.items() if len(k) == 2}
        commander_combos_filtered_3_cards = {
            k: v for k, v in commander_combos_filtered.items() if len(k) == 3}
        commander_combos_filtered_4_plus_cards = {
            k: v for k, v in commander_combos_filtered.items() if len(k) > 3}

        commander_combos_filtered_2_cards_order_cmc_total = list(sorted(
            commander_combos_filtered_2_cards.items(), key=lambda t: t[1]['cmc_total']))
        commander_combos_filtered_3_cards_order_cmc_total = list(sorted(
            commander_combos_filtered_3_cards.items(), key=lambda t: t[1]['cmc_total']))
        commander_combos_filtered_4_plus_cards_order_cmc_total = list(sorted(
            commander_combos_filtered_4_plus_cards.items(), key=lambda t: t[1]['cmc_total']))

        commander_combos_filtered_cards_names = set(filter(
            lambda n: n != COMMANDER_NAME,
            [name for names in commander_combos_filtered for name in names]))
        commander_combos_filtered_2_cards_names = set(filter(
            lambda n: n != COMMANDER_NAME,
            [name for names in commander_combos_filtered_2_cards for name in names]))
        commander_combos_filtered_3_cards_names = set(filter(
            lambda n: n != COMMANDER_NAME,
            [name for names in commander_combos_filtered_3_cards for name in names]))
        commander_combos_filtered_4_plus_cards_names = set(filter(
            lambda n: n != COMMANDER_NAME,
            [name for names in commander_combos_filtered_4_plus_cards for name in names]))

        print('Commander combos:', len(commander_combos))
        print('')
        print('Commander combos (OK):', len(commander_combos_ok))
        print('')
        print('Commander combos filtered '+commander_combos_regex+':',
              len(commander_combos_filtered))
        print('')
        print('    2 cards:', len(commander_combos_filtered_2_cards), 'combos,',
              '+'+str(len(commander_combos_filtered_2_cards_names)), 'cards')
        print('')
        for index, tup_combo in enumerate(commander_combos_filtered_2_cards_order_cmc_total):
            print_tup_combo(tup_combo, indent = 8, max_cards = 2, print_header = index == 0)
        print('')
        print('    3 cards:', len(commander_combos_filtered_3_cards), 'combos,',
              '+'+str(len(commander_combos_filtered_3_cards_names)), 'cards')
        print('')
        for index, tup_combo in enumerate(commander_combos_filtered_3_cards_order_cmc_total):
            print_tup_combo(tup_combo, indent = 8, max_cards = 3, print_header = index == 0)
        print('')
        print('   4+ cards:', len(commander_combos_filtered_4_plus_cards), 'combos,',
              '+'+str(len(commander_combos_filtered_4_plus_cards_names)), 'cards')
        print('')
        for index, tup_combo in enumerate(commander_combos_filtered_4_plus_cards_order_cmc_total):
            print_tup_combo(tup_combo, indent = 8, max_cards = 4, print_header = index == 0)
        print('')

        # rank 2
        print('')
        commander_combos_cards = []
        for card_names in commander_combos_filtered:
            for card_name in card_names:
                if card_name not in commander_combos_cards and card_name != COMMANDER_NAME:
                    commander_combos_cards.append(card_name)
        commander_combos_cards = tuple(sorted(commander_combos_cards))
        combos_rank_2 = {}
        combos_rank_2_excludes = list(commander_combos_filtered.keys())
        for card_name in commander_combos_cards:
            print('DEBUG Searching for combos related to', card_name, '...', flush=True,
                  file=sys.stderr)
            card_combos = get_combos(combos, cards_ok, name = card_name,
                                     combo_res_regex = commander_combos_regex,
                                     excludes = combos_rank_2_excludes)
            if card_combos:
                for c_cards, c_info in card_combos.items():
                    if c_cards not in combos_rank_2:
                        combos_rank_2[c_cards] = c_info
        print('')

        combos_rank_2_2_cards = {k: v for k, v in combos_rank_2.items() if len(k) == 2}
        combos_rank_2_3_cards = {k: v for k, v in combos_rank_2.items() if len(k) == 3}
        combos_rank_2_4_plus_cards = {k: v for k, v in combos_rank_2.items() if len(k) > 3}

        combos_rank_2_2_cards_order_cmc_total = list(sorted(combos_rank_2_2_cards.items(),
                                                            key=lambda t: t[1]['cmc_total']))
        combos_rank_2_3_cards_order_cmc_total = list(sorted(combos_rank_2_3_cards.items(),
                                                            key=lambda t: t[1]['cmc_total']))

        combos_rank_2_2_cards_names = set(filter(
            lambda n: n != COMMANDER_NAME and n not in commander_combos_filtered_cards_names,
            [name for names in combos_rank_2_2_cards for name in names]))
        combos_rank_2_3_cards_names = set(filter(
            lambda n: n != COMMANDER_NAME and n not in commander_combos_filtered_cards_names,
            [name for names in combos_rank_2_3_cards for name in names]))

        print('Commander combos rank 2:', len(combos_rank_2))
        print('')
        print('    2 cards:', len(combos_rank_2_2_cards), 'combos,',
              '+'+str(len(combos_rank_2_2_cards_names)), 'cards')
        print('')
        for index, tup_combo in enumerate(combos_rank_2_2_cards_order_cmc_total):
            print_tup_combo(tup_combo, indent = 8, max_cards = 2, print_header = index == 0)
        print('')
        print('    3 cards:', len(combos_rank_2_3_cards), 'combos,',
              '+'+str(len(combos_rank_2_3_cards_names)), 'cards')
        print('')
        for index, tup_combo in enumerate(combos_rank_2_3_cards_order_cmc_total):
            print_tup_combo(tup_combo, indent = 8, max_cards = 3, print_header = index == 0)
        print('')
        print('   4+ cards:', len(combos_rank_2_4_plus_cards), 'combos')
        print('')


        print("DEBUG Searching for all 2 cards combos with", commander_combos_regex, "...",
              flush=True, file=sys.stderr)
        all_combos_2_cards_excludes = (list(commander_combos_filtered.keys())
                                       + list(combos_rank_2.keys()))
        all_combos_2_cards_other = get_combos(combos, cards_ok, max_cards = 2,
                                              combo_res_regex = commander_combos_regex,
                                              excludes = all_combos_2_cards_excludes)

        print('')
        print('All 2 cards combos with', commander_combos_regex, ':', len(all_combos_2_cards_other))
        # all_combos_2_cards_other_order_cmc_total = list(sorted(
        #     all_combos_2_cards_other.items(), key=lambda t: t[1]['cmc_total']))
        # for index, tup_combo in enumerate(all_combos_2_cards_other_order_cmc_total):
        #     print_tup_combo(tup_combo, indent = 8, max_cards = 2, print_header = index == 0)
        # print('')

        all_combos_2_cards_other_relations = {}
        for combo_cards in all_combos_2_cards_other:
            for name in combo_cards:
                for other_name in combo_cards:
                    if other_name != name:
                        if name not in all_combos_2_cards_other_relations:
                            all_combos_2_cards_other_relations[name] = []
                        if other_name not in all_combos_2_cards_other_relations[name]:
                            all_combos_2_cards_other_relations[name].append(other_name)

        print('')
        print('Cards in those combos:', len(all_combos_2_cards_other_relations))
        print('')

        nx_graph = get_nx_graph(all_combos_2_cards_other_relations)
        (k_nodes, k_num, k_len) = k_core_cards(nx_graph)
        k_cards = list(map(lambda n: nx_graph.nodes[n]['card'], k_nodes))

        k_combos = {}
        for card_names, combo_infos in all_combos_2_cards_other.items():
            add_combo = True
            for name in card_names:
                if name not in k_cards:
                    add_combo = False
                    break
            if add_combo:
                k_combos[card_names] = combo_infos

        print('DEBUG NX Graph:', 'nodes:', nx_graph.number_of_nodes(), ',',
              'edges:', nx_graph.number_of_edges(), file=sys.stderr)
        print('')
        if not k_nodes:
            print('Warning: impossible to find a k-core', file=sys.stderr)
        else:
            print('Combos '+str(k_num)+'-core cards:', k_len, 'cards')
            print('')
            for node in k_nodes:
                card_name = nx_graph.nodes[node]['card']
                print_card(get_card(card_name, cards_ok))
            print('')

            print('Combos matching those cards: ', len(k_combos), 'combos')
            print('')
            k_combos_order_cmc_max = list(sorted(k_combos.items(), key=lambda t: t[1]['cmc_max']))
            for index, tup_combo in enumerate(k_combos_order_cmc_max):
                print_tup_combo(tup_combo, indent = 3, max_cards = 2, print_header = index == 0)
            print('')

        # one common keyword
        # TODO use a regex to also include cards that have no keywords but a text that could match
        #      the keywords
        cards_common_keyword = list(
            filter(lambda c: bool(commander_keywords & set(c['keywords'])), cards_ok))
        print('One common keyword', (commander_keywords if commander_keywords else ''), ':',
              len(cards_common_keyword))
        print('')
        if COMMANDER_FEATURES_REGEXES:
            commander_common_feature = []
            for card in cards_ok:
                oracle_texts = get_oracle_texts(card)
                oracle_texts = list(map(
                    lambda t: t.replace(
                        '(Damage dealt by this creature also causes you to gain that much life.)',
                        ''),
                    oracle_texts))
                oracle_texts_low = list(map(str.lower, oracle_texts))
                for regexp in COMMANDER_FEATURES_REGEXES:
                    if list(search_strings(regexp, oracle_texts_low)):
                        if (COMMANDER_FEATURES_EXCLUDE_REGEX == r'()'
                            or not re.search(COMMANDER_FEATURES_EXCLUDE_REGEX,
                                            join_oracle_texts(card))):
                            commander_common_feature.append(card)
                            break
            print('Commander feature in common:', len(commander_common_feature))
            print('')
            commander_common_feature_organized = organize_by_type(commander_common_feature)
            for card_type, cards_list in commander_common_feature_organized.items():
                if cards_list:
                    print('   Commander feature in common ('+card_type+'):', len(cards_list))
                    print('')
                    for card in order_cards_by_cmc_and_name(cards_list):
                        if card_type == 'unknown':
                            print_card(card, print_powr_tough = False, indent = 5,
                                       merge_type_powr_tough = False)
                        else:
                            print_card(card, print_powr_tough = (card_type == 'creature'),
                                       print_type = False, indent = 5,
                                       print_mana = (card_type not in ['land','stickers']))
                    print('')
            print('')

        lands = list(filter(filter_lands, cards_ok))
        land_types_invalid = [COLOR_TO_LAND[c] for c in INVALID_COLORS]
        print('Land types not matching commander:', land_types_invalid)
        print('')
        land_types_invalid_regex = r'('+('|'.join(land_types_invalid)).lower()+')'
        assist_land_selection(lands, land_types_invalid_regex)

        # TODO select 5 ramp cards that are land related (search or play)
        cards_ramp_cards_land_fetch = assist_land_fetch(cards_ok, land_types_invalid_regex)

        # TODO select 5 multicolor ramp cards (artifacts ?)
        # TODO select 5 colorless ramp cards (artifacts ?)
        cards_ramp_cards = assist_ramp_cards(
            [c for c in cards_ok if c not in cards_ramp_cards_land_fetch],
            land_types_invalid_regex)

        # TODO select 10 draw cards
        cards_draw_cards = assist_draw_cards(
            [c for c in cards_ok if c not in cards_ramp_cards_land_fetch],
            land_types_invalid_regex)

        # with open('draw_cards.list.txt', 'r', encoding='utf-8') as f_draw_read:
        #     print('')
        #     print('Draw card missing')
        #     print('')
        #     for card_name in f_draw_read:
        #         card_name = card_name.strip()
        #         found = False
        #         card = None
        #         for c in cards_ok:
        #             if c['name'] == card_name and not filter_lands(c):
        #                 found = True
        #                 card = c
        #                 break
        #         # if not found:
        #         #     print('NOT PLAYABLE', card_name)
        #         no_print = False
        #         for c in cards_ramp_cards:
        #             if c['name'] == card_name:
        #                 # print('RAMP', card_name)
        #                 no_print = True
        #                 break
        #         for c in cards_ramp_cards_land_fetch:
        #             if c['name'] == card_name:
        #                 # print('FETCHER', card_name)
        #                 no_print = True
        #                 break
        #         for c in cards_draw_cards:
        #             if c['name'] == card_name:
        #                 # print('DRAW', card_name)
        #                 no_print = True
        #                 break
        #         if found and not no_print and card:
        #             print_card(card, trunc_text = False)


        # TODO select 7 tutors
        cards_tutor_cards = assist_tutor_cards(
            [c for c in cards_ok if c not in cards_ramp_cards_land_fetch],
            land_types_invalid_regex)

        # with open('tutor_cards.list.txt', 'r', encoding='utf-8') as f_tutor_read:
        #     print('')
        #     print('Tutor card missing')
        #     print('')
        #     for card_name in f_tutor_read:
        #         card_name = card_name.strip()
        #         found = False
        #         card = None
        #         for c in cards_ok:
        #             if c['name'] == card_name and not filter_lands(c):
        #                 found = True
        #                 card = c
        #                 break
        #         # if not found:
        #         #     print('NOT PLAYABLE', card_name)
        #         no_print = False
        #         for c in cards_ramp_cards:
        #             if c['name'] == card_name:
        #                 print('RAMP', card_name)
        #                 no_print = True
        #                 break
        #         for c in cards_ramp_cards_land_fetch:
        #             if c['name'] == card_name:
        #                 print('FETCHER', card_name)
        #                 no_print = True
        #                 break
        #         for c in cards_draw_cards:
        #             if c['name'] == card_name:
        #                 print('DRAW', card_name)
        #                 # no_print = True
        #                 break
        #         for c in cards_tutor_cards:
        #             if c['name'] == card_name:
        #                 # print('TUTOR', card_name)
        #                 no_print = True
        #                 break
        #         if found and not no_print and card:
        #             print_card(card, trunc_text = False)

        # TODO select 7 removal cards (3 creatures, 4 artifacts/enchantments)
        cards_removal = assist_removal_cards([
            c for c in cards_ok if c not in cards_ramp_cards
            and c not in cards_draw_cards and c not in cards_tutor_cards])

        # best cards
        cards_best = assist_best_cards(cards_ok)

        # TODO select 25 cards combos (starting with the commander and the selected cards)
        # WIP:
        #  - list the commanders features keyword that may combo
        #  - from that build a regex to match thoses features against other cards
        #  - based on the list of others thoses cards, find the ones that
        #      * requires only 2 cards to combos, ordered by CMC
        #      * requires 3 cards to combos, ordered by CMC
        #      * contains an existing deck card in their combo
        #      * contains a card in their combos that have a high number of combos

        # TODO select 3 board wipe cards

        # TODO select 1 graveyard hate

        # TODO select 1 'I win' suprise card

        # for index, card in enumerate(deck_cards):
            # print(card['name'])

        # for each turn N present a list of possible N-drop cards

if __name__ == '__main__':
    try:
        main()
    except BrokenPipeError:
        pass
    except KeyboardInterrupt:
        print('')
        print('Ciao !')
