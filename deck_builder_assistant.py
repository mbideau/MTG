#!/usr/bin/env python3
#
# Copyright 2023 Michael Bideau, France <mica.devel@gmail.com>
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program; if not, see <http://www.gnu.org/licenses/>.
"""
Deck builder using the Scryfall JSON cards collection, and the CommanderSpeelbook
database.
"""

# pylint: disable=line-too-long
# pylint: disable=too-many-lines
# pylint: disable=too-many-statements
# pylint: disable=too-many-locals
# pylint: disable=too-many-branches
# pylint: disable=too-many-return-statements
# pylint: disable=too-many-arguments
# pylint: disable=too-many-nested-blocks
# pylint: disable=too-many-boolean-expressions

import os
import sys
import json
import re
# import csv
from argparse import ArgumentParser
from urllib.request import urlopen,urlretrieve
from pathlib import Path
from math import comb, prod
from datetime import datetime
from time import monotonic_ns, sleep
from os.path import join as pjoin
from textwrap import wrap
# import pprint
USE_NX = False
USE_SIXEL = False
try:
    import networkx as nx
    USE_NX = True
except ImportError:
    pass
try:
    from sixel import sixel, converter
    USE_SIXEL = True
except ImportError:
    pass
try:
    from termcolor import colored
except ImportError:
    def colored(text, *pos, **kwargs):  # pylint: disable=unused-argument
        """Fallback function"""
        return text

SOURCE_URL = 'https://github.com/mbideau/MTG/blob/main/deck_builder_assistant.py'

# user input
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
LAST_SCRYFALL_CALL_TS_N = 0

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
    'M': 'light_yellow',
    'C': 'yellow',
    'X': 'yellow',
    'Y': 'yellow',
    'Z': 'yellow',
    'TK': 'yellow',
    'T': 'magenta',
    'Q': 'magenta',
    'E': 'cyan',
    'PW': 'yellow',
    'CHAOS': 'yellow',
    'A': 'yellow',
    '½': 'yellow',
    '∞': 'yellow',
    'P': 'yellow',
    'HW': 'white',
    'HR': 'red',
    'S': 'yellow'}
ALL_COLORS_COUNT = len(ALL_COLORS)
COLOR_TO_LAND = {
    'G': 'Forest',
    'R': 'Mountain',
    'W': 'Plains',
    'U': 'Island',
    'B': 'Swamp'}
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
    r'(destroy|remove|exile|put that card in the graveyard)',
    r"returns? .* to (its|their) owner('s|s') hand",
    r"puts? .* on the bottom of (its|their) owner('s|s') library",
    r"puts? .* on top of (its|their) owner('s|s') library",
    r"puts? .* into (its|their) owner('s|s') library",
    r"shuffles it into (its|their) library",
    r"creatures? gets? [+-][0-9Xx]+/-[1-9Xx]+",
    r"(target|each|every) (opponents?|players?) sacrifices? an?( attacking)? creature"
]
REMOVAL_CARDS_EXCLUDE_REGEX = r'('+('|'.join([
    'remove any number of [^.]*counter',
    'counters? removed this way',
    'remove (x|that many)? [^.]*counters',
    'exile [^.]+ you control',
    'exile this permanent',
    r"(return|put)s? [^.]+ cards?(( each)? with (total )?(mana value|power) [0-9x]+( or less)?)? from (a|your|target player's) graveyard",
    'look at [^.]+ your library[, ].*exile (one|that card)',
    'rather than cast this card from your hand, pay [^.]+ and exile it',
    'remove [^.]+ from combat',
    'remove [^.]+ counters? from',
    r'exile [^.]+\. at the beginning of the next end step, return it',
    'exile [^]*, then return it to the battlefield transformed',
    r'you may exile [^.]+\. If you do, return them',
    "exiles? [^.]+ (of|from) (your|a|their|target player's) (hand|graveyard|library)",
    'you may cast this card from exile',
    'search [^.]+ library [^.]+ cards?(,| and) exile (it|them)', # TODO wrongly exclude Deicide and Wail of the Forgotten
    'if [^.]+ would die, exile it instead',
    'if [^.]+ would be put into your graveyard, exile it instead',
    "this effect doesn't remove",
    'look at [^.]+ library, then exile',
    'remove [^.]+ from it',
    'exile it instead of putting it into',
    r'destroy target \w+ you own',
    'when this spell card is put into a graveyard after resolving, exile it',
    r"return .*you control.* to its owner's hand",
    "when this creature dies or is put into exile from the battlefield, return it to its owner's hand",
    r"creature gets -\d/-1 until end of turn\.",
    'put one of them into your hand and the rest into your graveyard',
    # 'exile it, then cast it transformed', # mess with Invasion of New Capenna
    'if it has [^.]+ counters on it, remove all of them',
    "put target card from a graveyard on the bottom of its owner's library",
    'you own in exile',
    # graveyard hate
    'you may play lands and cast spells from your graveyard',
    r'return [^.+] card from your graveyard.* exile it',
    "exile target card from defending player's graveyard",
    "exile target player's graveyard",
    r"exiles? (up to \w+ )?target cards? from( (a|(target|that) player's)( single)?)? graveyard",
    "if a nontoken creature would enter the battlefield and it wasn't cast, exile it instead",
    "exile (all cards from )?(all|target player's) graveyard",
    r"exile all creature cards (with mana value \d or less )?from (target player's|all) graveyard",
    "if a permanent would be put into a graveyard, exile it instead",
    'whenever another card is put into a graveyard from anywhere, exile that card',
]))+')'
DISABLING_CARDS_REGEX = [
    r"(activated abilities can't be activated|activated abilities of [^.]+ can't be activated)",
    r"creature can't (block|attack( or block)?)",
    r"(creature doesn't untap|if enchanted creature is untapped, tap it)",
    r"creature phases out",
    r"(base power and toughness \d/\d|enchanted \w+ (is|becomes) a )"]
DISABLING_CARDS_EXCLUDE_REGEX = r'('+('|'.join([
    'toto'
]))+')'
COPY_CARDS_REGEX = [
    '(copy|duplicate)']
COPY_CARDS_EXCLUDE_REGEX = r'('+('|'.join([
    'copy this spell',
    'whenever you (cast or )?copy',
    'when you cast this spell, copy it',
    "exile this card from your graveyard: create a token that's a copy of it",
]))+')'

WIPE_CARDS_REGEX = [
    r'((destroy|remove|exile) (all|every|each)|put (those( cards)?|them) in the graveyard)'
]
WIPE_CARDS_EXCLUDE_REGEX = r'('+('|'.join([
    '[Rr]emove all damage',
    '[Ee]xile all other cards revealed',
    "[Ee]xile each opponent's (library|hand|graveyard)",
    r'[Rr]emove all ((\w+|[+-]\d/[+-]\d) )?counter',
    "[Ee]xile (all cards from )?(all|target player's) graveyard",
    r"[Ee]xile all creature cards (with mana value \d or less )?from (target player's|your) "
        "(library|hand|graveyard)",
    r'[Dd]estroy all (\w+ )?tokens',
    '[Rr]emove all attackers (and blockers )?from combat',
    '([Ee]xile|[Rr]emove) all attacking creatures',
    '[Ee]xile all (the )?cards from your (library|hand|graveyard)',
    '[Ii]f [^.]+ has [^.]+ counters on it, remove all of them',
    '[Ee]xile all spells and abilities from the stack',
    '[Dd]estroy all creatures that entered the battlefield this turn',
    '[Ee]xile (all|every|each) (nontoken )?creatures? you control',
    "[Ee]xile [Aa]ll [Hh]allow's [Ee]ve",
    '[Ee]xile all ([Ww]arriors|[Zz]ombies)',
    "[Ee]xile all creature cards from all graveyards",
]))+')'
GRAVEYARD_HATE_CARDS_REGEX = {
    'all cards': [
        "exile each opponent's graveyard",
        "exile (all cards from )?(all|target player's) graveyard",
        r"exile all creature cards (with mana value \d or less )?from (target player's|all) graveyard",
        'exile all (the )?cards from your graveyard',
        r"(remove|exile) (all|every|each) ((target )?(player|opponent)'s|(cards?|creatures?) "
        r"(in|from) (all (players|opponents)|target (player|opponent)'s)) graveyard",
        'cards in graveyards lose all abilities',
        'whenever another card is put into a graveyard from anywhere, exile that card',
        "players can't cast spells from graveyards or libraries",
        "creature cards in graveyards and libraries can't enter the battlefield",
        'each opponent chooses two cards in their graveyard and exiles the rest'],
    'some cards': [
        r"exiles? (up to \w+ )?target cards? from( (a|(target|that) player's)( single)?)? graveyard",
        'you may exile (a|target) creature card from a graveyard',
        'exile target creature card from a graveyard',
        "exile x target cards from target player's graveyard",
        'target player exiles a card from their graveyard',
        "if a nontoken creature would enter the battlefield and it wasn't cast, exile it instead",
        "if a permanent would be put into a graveyard, exile it instead",
        'exile target artifact card from a graveyard',
        '(that player|target opponent) may exile a card from their graveyard',
        'target opponent exiles a card from their graveyard']
    }
GRAVEYARD_HATE_CARDS_EXCLUDE_REGEX = r'('+('|'.join([
    'toto'
]))+')'
GRAVEYARD_RECURSION_CARDS_REGEX = [
    'returns? (it|that card) to the battlefield',
    r"(return|put)s? [^.]+ cards?(( each)? with (total )?(mana value|power) [0-9x]+( or less)?)? "
        "from (a|your|target player's) graveyard (on)?to (the battlefield|(your|their|its owner's) "
        "hand)",
    "puts? [^.]+ cards? from (a|your|target player's) graveyard on top of (your|their) library",
    'enchant creature card in a graveyard',
    'choose an instant or sorcery card in your graveyard. you may cast it',
    'you may play lands and cast spells from your graveyard',
    'you may cast a permanent spell( with mana value 2 or less)? from your graveyard',
    'you may cast target instant card from your graveyard',
    'choose [^.]+ cards in your graveyard',
    'leave the chosen cards in your graveyard and put the rest into your hand',
    'exile a creature or planeswalker card from each graveyard',
    "put target card from a graveyard on the top or bottom of its owner's library",
    "if the top card of target player's graveyard is a creature card, put that card on top of "
    "that player's library",
    "put target creature card from a graveyard onto the battlefield",
]
GRAVEYARD_RECURSION_CARDS_EXCLUDE_REGEX = r'('+('|'.join([
    "exile target attacking creature",
    "when [^.]+ dies, if it had no [^.]+ counters on it",
    "when this creature dies, return it to the battlefield",
    "when [^.]+ dies( this turn)?,( you may)? return it to the battlefield",
    "return it to the battlefield transformed",
    "when [^.]+ dies, you may pay [^.]+. if you do, return it to the battlefield",
    "whenever a (nontoken )?creature is put into your graveyard [^.]+, you may pay [^.]+. "
        "if you do, return that card to the battlefield",
    "whenever equipped creature dies, return that card to the battlefield",
    "whenever a creature dealt damage by equipped creature this turn dies, "
        "return that card to the battlefield",
    "(sacrifice|exile) (aethergeode miner|biolume egg), (then )?return it to the battlefield",
    r"exile ((\w+)( \w+)?|nezahal, primal tide|ghost council of orzhova|djinn of the fountain).( then)? return it to the battlefield",
    "when target creature dies this turn, return that card to the battlefield",
    "when enchanted creature dies, return that card to the battlefield",
    "causes a land to be put into your graveyard [^.]+, return that card to the battlefield",
    "exile target creature. if you do, return that card to the battlefield",
    "whenever a creature an opponent controls [^.]+ dies, you may return that card to the battlefield",
    "if a permanent you control would be put into a graveyard [^.]+, exile it instead. return it to the battlefield",
    "when [^.]+ dies, if it dealt combat damage [^.]+, return it to the battlefield",
    "whenever a creature dealt damage [^.]+ dies, return it to the battlefield",
    r"exile target creature that has a \w+ counter on it, then return it to the battlefield",
    "exile target creature..* at the beginning of your next upkeep, return that card to the battlefield",
    "exile [^.]+ you control.* return (it|that card) to the battlefield",
    "whenever a creature you don't control dies, return it to the battlefield",
    "whenever a creature an opponent controls dies, you may pay [^.]+. if you do, return that card to the battlefield"
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
RAMP_CARDS_REGEX_BY_FEATURES = {
    'land fetch': [
        '(look for |search |play )[^.]+ land',
        ("(reveal|look at) the top card of your library.*if it's a land card, "+
        "(then |you may )?put (it|that card) onto the battlefield"),
        'put (a|up to \\w+) lands? cards? from your hand onto the battlefield',
        "gain control of a land you don't control"],
    'mana': [
        'adds? (an additional )?\\{[crgbuw0-9]\\}',
        'adds? [^.]+ to your mana pool',
        'adds? [^.]+ of any color',
        'adds? \\w+ mana',
        '(you may )?adds? an amount of \\{[crgbuw]\\} equal to',
        'that player adds? \\w+ mana of any color they choose',
        'adds? \\w+ additional mana',
        'double the amount of [^.]+ mana you have'],
    'cost reduction': [
        ('spells? (you cast )?(of the chosen type |that share a card type with the exiled card )?'+
        'costs? (up to )?\\{\\d+\\} less to cast'),
        'abilities (of creatures (you control )?)?costs? \\{\\d+\\} less to activate',
        'spells? (you cast)? have (convoke|improvise)'],
    'draw': [
        'look at the top \\w+ cards of your library\\. put \\w+ of them into your hand',
        'reveal a card in your hand, then put that card onto the battlefield'],
    'pay with life instead of mana': [
        'for each \\{[crgbuw]\\} in a cost, you may pay \\d+ life rather than pay that mana'],
    'untap land or permanent': [
        'you may [^.]+ untap target [^.]+ land',
        'choose [^.]+ land.* untap all tapped permanents of that type that player controls']}
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

COLORIZE_KEYWORD_REGEX_PART = '('+('|'.join(KEYWORDS_ABILITIES + ABILITY_WORDS))+')'

# see https://mtg.fandom.com/wiki/Category:Miscellaneous_mechanics
# TODO: craft some regex to detect each

# functions

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
    raise Exception("Not implemented")  # pylint: disable=broad-exception-raised

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
    global LAST_SCRYFALL_CALL_TS_N
    filename = (re.sub(r'[^A-Za-z_-]', '', card['name'])+'--'+imgformat+
                ('.jpg' if imgformat != 'png' else '.png'))
    filepath = pjoin(outdir, filename)
    filepathinfo = Path(filepath)
    imgurl = card['image_uris'][imgformat]
    if not filepathinfo.is_file() or update:
        # delaying up to 200 milliseconds like Scryfall API ask for fairness
        now_ts_n = monotonic_ns()
        while now_ts_n - LAST_SCRYFALL_CALL_TS_N < 200000:
            print("DEBUG last scryfall call was less than 200 ms, sleeping 200 ms", file=sys.stderr)
            sleep(0.2) # sleep 200 milliseconds
            now_ts_n = monotonic_ns()
        print("DEBUG Getting Scryfall card's image from '"+imgurl+"' ...", file=sys.stderr)
        urlretrieve(imgurl, filepath)
        LAST_SCRYFALL_CALL_TS_N = monotonic_ns()
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

# TODO rename to 'rules_0' and use some 'preset'
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
    texts_joined = (' // '.join(texts_colorized).replace('\n', '. ').replace('..', '.')
                          .replace('—.', '—').replace('. •', ' •'))
    return texts_joined

def sort_cards_by_cmc_and_name(cards_list):
    """Return an ordered cards list by CMC + Mana cost length as a decimal, and Name"""
    return list(sorted(cards_list, key=lambda c: (
        str((c['cmc'] if 'cmc' in c else 0) + float('0.'+str(len(c['mana_cost']) if 'mana_cost' in c else '0')))
        +c['name'])))

def print_all_cards_stats(cards, outformat = 'console'):
    """Print statistics about all cards"""

    empty = list(filter(lambda c: not filter_empty(c), cards))
    illegal = list(filter(lambda c: not filter_not_legal_and_banned(c), cards))
    xmage_banned = list(filter(lambda c: not filter_xmage_banned(c), cards))
    cards_mythic_or_special = list(filter(lambda c: not filter_mythic_and_special(c), cards))
    without_price_eur = list(filter(lambda c: not c['prices']['eur'], cards))
    without_price_usd = list(filter(lambda c: not c['prices']['usd'], cards))
    max_price_eur = max(map(lambda c: float(c['prices']['eur'] or 0), cards))
    max_price_usd = max(map(lambda c: float(c['prices']['usd'] or 0), cards))
    price_below_100 = list(filter(filter_price, cards))
    without_text = list(filter(lambda c: not filter_no_text(c), cards))
    without_keywords = list(filter(lambda c: not filter_no_keywords(c), cards))
    without_keywords_nor_text = list(
        filter(lambda c: not filter_no_keywords(c) and not filter_no_text(c), cards))

    if outformat == 'html':
        html = ''
        html += '  <section>'+'\n'
        html += '    <h3>Stats: all cards</h3>'+'\n'
        html += '    <dl>'+'\n'
        html += '      <dt>Total cards</dt>'+'\n'
        html += '      <dd>'+str(len(cards))+'</dd>'+'\n'
        html += '      <dt>Empty cards</dt>'+'\n'
        html += '      <dd>'+str(len(empty))+'</dd>'+'\n'
        html += '      <dt>Illegal or banned</dt>'+'\n'
        html += '      <dd>'+str(len(illegal))+'</dd>'+'\n'
        html += '      <dt>XMage banned</dt>'+'\n'
        html += '      <dd>'+str(len(xmage_banned))+'</dd>'+'\n'
        html += '      <dt>Mythic or special</dt>'+'\n'
        html += '      <dd>'+str(len(cards_mythic_or_special))+'</dd>'+'\n'
        html += '      <dt>Without price EUR</dt>'+'\n'
        html += '      <dd>'+str(len(without_price_eur))+'</dd>'+'\n'
        html += '      <dt>Without price USD</dt>'+'\n'
        html += '      <dd>'+str(len(without_price_usd))+'</dd>'+'\n'
        html += '      <dt>Price max EUR</dt>'+'\n'
        html += '      <dd>'+str(max_price_eur)+'</dd>'+'\n'
        html += '      <dt>Price max USD</dt>'+'\n'
        html += '      <dd>'+str(max_price_usd)+'</dd>'+'\n'
        html += '      <dt>Price >100€ or >120$</dt>'+'\n'
        html += '      <dd>'+str(len(price_below_100))+'</dd>'+'\n'
        html += '      <dt>Without text</dt>'+'\n'
        html += '      <dd>'+str(len(without_text))+'</dd>'+'\n'
        html += '      <dt>Without keywords</dt>'+'\n'
        html += '      <dd>'+str(len(without_keywords))+'</dd>'+'\n'
        html += '      <dt>Without keywords and text</dt>'+'\n'
        html += '      <dd>'+str(len(without_keywords_nor_text))+'</dd>'+'\n'
        html += '    </dl>'+'\n'
        html += '  </section>'+'\n'
        print(html)

    if outformat == 'console':
        print('')
        print('')
        print('### All Cards Stats ###')
        print('')
        print('Total cards:', len(cards))
        print('')
        print('Empty cards:', len(empty))
        print('')
        print('Illegal or banned:', len(illegal))
        print('')
        print('XMage banned:', len(xmage_banned))
        print('')
        print('Mythic or special:', len(cards_mythic_or_special))
        print('')
        print('Without price EUR:', len(without_price_eur))
        print('Without price USD:', len(without_price_usd))
        print('Price max EUR:', max_price_eur)
        print('Price max USD:', max_price_usd)
        print('')
        print('Price >100€ or >120$:', len(price_below_100))
        print('')
        print('Without text:', len(without_text))
        print('')
        print('Without keywords:', len(without_keywords))
        print('')
        print('Without keywords and text:', len(without_keywords_nor_text))
        print('')

def print_deck_cards_stats(cards, valid_colors, valid_rules0, outformat = 'console'):
    """Print statistics about deck's cards"""

    invalid_colors_len = len(cards) - len(valid_colors)
    invalid_colors_colored = ','.join(list(map(lambda t: colorize_mana(t, no_braces = True),
                                               INVALID_COLORS)))
    removed_by_rules0_len = len(valid_colors) - len(valid_rules0)
    max_price_eur = max(map(lambda c: float(c['prices']['eur'] or 0), valid_rules0))
    max_price_usd = max(map(lambda c: float(c['prices']['usd'] or 0), valid_rules0))

    if outformat == 'html':
        html = ''
        html += '  <section>'+'\n'
        html += "    <h3>Stats: deck's cards and rules 0</h3>"+'\n'
        html += '    <dl>'+'\n'
        html += '      <dt>Invalid colors</dt>'+'\n'
        html += '      <dd>'+invalid_colors_colored+' ('+str(invalid_colors_len)+')'+'</dd>'+'\n'
        html += '      <dt>Removed by rules 0</dt>'+'\n'
        html += '      <dd>'+str(removed_by_rules0_len)+'</dd>'+'\n'
        html += '      <dt>Price max EUR</dt>'+'\n'
        html += '      <dd>'+str(max_price_eur)+'</dd>'+'\n'
        html += '      <dt>Price max USD</dt>'+'\n'
        html += '      <dd>'+str(max_price_usd)+'</dd>'+'\n'
        html += '    </dl>'+'\n'
        html += '  </section>'+'\n'
        print(html)

    if outformat == 'console':
        print('')
        print('')
        print('### Stats for this deck and rules 0 ###')
        print('')
        print('Invalid colors', invalid_colors_colored, '('+str(invalid_colors_len)+')')
        print('')
        print('Removed by rules 0:', removed_by_rules0_len)
        print('')
        print('Price max EUR:', max_price_eur)
        print('Price max USD:', max_price_usd)
        print('')

def assist_land_selection(lands, land_types_invalid_regex, max_list_items = None,
                          outformat = 'console'):
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
            and (c['name'] != "The gray Havens" or FILL_GRAVEYARD_FAST)),
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

    # NOTE: not generic enought or not really usefull lands
    # # nonbasic lands that are producers
    # cards_lands_producers_non_basic = list(filter(
    #         lambda c: (
    #             bool(list(search_strings(r'(\s+|\n|\r)?\{T\}: Add \{\w\}',
    #                                         get_oracle_texts(c))))
    #             and not bool(list(in_strings('roll a', map(str.lower, get_oracle_texts(c)))))
    #             and not bool(list(in_strings('phased out', map(str.lower, get_oracle_texts(c)))))
    #             and not bool(list(in_strings('venture into the dungeon',
    #                                         map(str.lower, get_oracle_texts(c)))))),
    #         filter(
    #             lambda c: not c['type_line'].lower().startswith('basic land'),
    #             [c for c in lands if c not in cards_lands_multicolors_generic_enough
    #             and c not in cards_lands_converters
    #             and c not in cards_lands_tricolors
    #             and c not in cards_lands_bicolors
    #             and c not in cards_lands_sacrifice_search])))
    # cards_lands_producers_non_basic_no_colorless = list(filter(
    #     filter_add_one_colorless_mana, cards_lands_producers_non_basic))
    # cards_lands_producers_non_basic_colorless = [
    #     c for c in cards_lands_producers_non_basic
    #     if c not in cards_lands_producers_non_basic_no_colorless]
    # cards_lands_producers_non_basic_no_colorless_not_tapped = list(filter(
    #     filter_tapped, cards_lands_producers_non_basic_no_colorless))
    # cards_lands_producers_non_basic_no_colorless_tapped = [
    #     c for c in cards_lands_producers_non_basic_no_colorless
    #     if c not in cards_lands_producers_non_basic_no_colorless_not_tapped]
    #
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

    land_stats_data = {
        'Multicolors lands generic enough (total)': cards_lands_multicolors_generic_enough,
        'Multicolors lands producers (total)': cards_lands_multicolors_producers,
        'Multicolors lands producers (not tapped, no sacrifice, no colorless mana':
            cards_lands_multicolors_filtered,
        'Multicolors lands producers (not tapped or untappable)':
            cards_lands_multicolors_producers_not_tapped,
        'Multicolors lands producers (not tapped or untappable, not selective)':
            cards_lands_multicolors_producers_not_tapped_not_selective,
        'Multicolors lands producers (not tapped or untappable, selective)':
            cards_lands_multicolors_producers_not_tapped_selective,
        'Multicolors lands producers (tapped)': cards_lands_multicolors_producers_tapped,
        'Multicolors lands producers (tapped, no color selection, no charge counter, no pay {1})':
            cards_lands_multicolors_producers_tapped_filtered,
        'Lands converters (total)': cards_lands_converters,
        'Lands converters colorless producers (total)': cards_lands_converters_colorless_producers,
        'Lands converters colorless producers (not tapped or untappable)':
            cards_lands_converters_colorless_producers_not_tapped,
        'Lands converters colorless producers (tapped)':
            cards_lands_converters_colorless_producers_tapped,
        # NOTE: I prefer artifacts for the job of converting mana,
        #       since their colorless mana will turn into a ramp, instead of a bad mana
        'Lands converters not producers (total)': cards_lands_converters_no_producers,
        'Lands converters not producers (not tapped or untappable)':
            cards_lands_converters_no_producers_not_tapped,
        'Lands converters not producers (tapped)': cards_lands_converters_no_producers_tapped,
        # NOTE: tricolors lands are always tapped, not so good then
        'Tricolors lands (tapped)': cards_lands_tricolors,
        'Bicolors lands': cards_lands_bicolors,
        'Bicolors lands (filtered)': cards_lands_bicolors_filtered,
        'Bicolors lands (filtered, not tapped or untappable)':
            cards_lands_bicolors_filtered_not_tapped,
        'Bicolors lands (filtered, tapped)': cards_lands_bicolors_filtered_tapped,
        'Sacrifice/Search lands': cards_lands_sacrifice_search,
        'Sacrifice/Search lands (not tapped or untappable)':
            cards_lands_sacrifice_search_no_tapped,
    }
    land_output_data = {
        'Multicolors lands producers': [
            ('Multicolors lands producers (not tapped, no sacrifice, '
             'no colorless mana', cards_lands_multicolors_filtered),
            ('Multicolors lands producers (not tapped or untappable, not selective)',
             cards_lands_multicolors_producers_not_tapped_not_selective),
            ('Multicolors lands producers (not tapped or untappable, selective)',
             cards_lands_multicolors_producers_not_tapped_selective),
            ('Multicolors lands producers (tapped, no color selection, no charge counter, '
             'no pay {1})', cards_lands_multicolors_producers_tapped_filtered)],
        'Lands converters (mana fixers)': [
            ('Lands converters colorless producers (not tapped or untappable)',
             cards_lands_converters_colorless_producers_not_tapped),
            ('Lands converters colorless producers (tapped)',
             cards_lands_converters_colorless_producers_tapped)],
        'Bicolors lands': [
            ('Bicolors lands (filtered, not tapped or untappable)',
             cards_lands_bicolors_filtered_not_tapped)],
        'Sacrifice/Search lands': [
            ('Sacrifice/Search lands (not tapped or untappable)',
             cards_lands_sacrifice_search_no_tapped)]
    }

    if outformat == 'html':
        html = ''
        html += '  <section>'+'\n'
        html += '    <h3 id="lands">Lands</h3>\n'
        html += '    <h4>Stats</h4>'+'\n'
        html += '    <dl>'+'\n'
        for title, cards_list in land_stats_data.items():
            html += '      <dt>'+title+'</dt>'+'\n'
            html += '      <dd>'+str(len(cards_list))+'</dd>'+'\n'
        html += '    </dl>'+'\n'
        for section, data in land_output_data.items():
            html += '    <h4>'+section+'</h4>'+'\n'
            for tup in data:
                title = tup[0]+': '+str(len(tup[1]))
                html += '    <article>'+'\n'
                html += '      <details>'+'\n'
                html += '        <summary>'+title+'</summary>'+'\n'
                html += print_cards_list(tup[1], limit = max_list_items, print_mana = False,
                                        print_type = False, print_powr_tough = False,
                                        outformat = outformat, return_str = True)
                html += '      </details>'+'\n'
                html += '    </article>'+'\n'

        html += '  </section>'+'\n'

        print(html)

    if outformat == 'console':

        for title, cards_list in land_stats_data.items():
            print(title+':', len(cards_list))
        print('')
        print('')

        for section, data in land_output_data.items():
            print(section)
            print('')
            for tup in data:
                print('   '+tup[0]+': '+str(len(tup[1])))
                print('')
                print_cards_list(tup[1], limit = max_list_items, indent = 5, print_mana = False,
                                 print_type = False, print_powr_tough = False, outformat=outformat)

    # TODO select monocolor lands to match 37 lands cards (at the end)
    #      42 cards recommanded: @see https://www.channelfireball.com/article/What-s-an-Optimal-Mana-Curve-and-Land-Ramp-Count-for-Commander/e22caad1-b04b-4f8a-951b-a41e9f08da14/
    #      - 3 land for each 5 ramp cards
    #      - 2 land for each 5 draw cards

def assist_land_fetch(cards, land_types_invalid_regex, max_list_items = None, outformat = 'console'):
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
        'to battlefield, conditional': [],
        'to hand': [],
        'to hand, conditional': [],
        'to top of library': [],
        'to top of library, conditional': []}
    for card in cards_ramp_cards_land_fetch:
        card_oracle_texts = list(get_oracle_texts(card))
        card_oracle_texts_low = list(map(str.lower, card_oracle_texts))
        conditional = (bool(list(in_strings('more lands', card_oracle_texts_low)))
                       or bool(list(in_strings('fewer lands', card_oracle_texts_low))))
        cond_text = ', conditional' if conditional else ''
        if list(search_strings(
                r'puts? '
                '(it|that card|one( of them)?|them|those cards|a card [^.]+|[^.]+ and the rest) '
                'in(to)? (your|their) hand', card_oracle_texts_low)):
            cards_ramp_cards_land_fetch_by_feature['to hand'+cond_text].append(card)
        elif list(search_strings(
                r'puts? (it|that card|one( of them| of those cards)?|them|those cards) '
                'on(to)? the battlefield', card_oracle_texts_low)):
            cards_ramp_cards_land_fetch_by_feature['to battlefield'+cond_text].append(card)
        elif list(search_strings('put (that card|them) on top', card_oracle_texts_low)):
            cards_ramp_cards_land_fetch_by_feature['to top of library'+cond_text].append(card)
        else:
            print('UNKNOWN land fetch categorie',
                  print_card(card, return_str = True, trunc_text = False, outformat = 'console'),
                  file=sys.stderr)

    for feature, cards_list in cards_ramp_cards_land_fetch_by_feature.items():
        organized = {}
        if cards_list:
            for card in cards_list:
                if card['name'] in cards_ramp_cards_land_fetch_land_cycling:
                    if 'land cycling' not in organized:
                        organized['land cycling'] = []
                    organized['land cycling'].append(card)
                elif card['name'] in cards_ramp_cards_land_fetch_channel:
                    if 'channel' not in organized:
                        organized['channel'] = []
                    organized['channel'].append(card)
                else:
                    card_type = get_card_type(card)
                    if card_type not in organized:
                        organized[card_type] = []
                    organized[card_type].append(card)
        cards_ramp_cards_land_fetch_by_feature[feature] = organized

    if outformat == 'html':
        html = ''
        html += '  <section>'+'\n'
        html += '    <h3 id="land-fetchers">Land fetchers</h3>\n'
        html += '    <h4>Stats</h4>'+'\n'
        html += '    <dl>'+'\n'
        html += '      <dt>Land fetchers (total)</dt>'+'\n'
        html += '      <dd>'+str(len(cards_ramp_cards_land_fetch))+'</dd>'+'\n'
        for feature, organized in cards_ramp_cards_land_fetch_by_feature.items():
            for card_type, cards_list in organized.items():  # pylint: disable=no-member
                extra_text = '(Ramp cards) ' if feature.startswith('to battlefield') else ''
                title = extra_text+'Land fetchers ('+feature+') '+card_type
                html += '      <dt>'+title+'</dt>'+'\n'
                html += '      <dd>'+str(len(cards_list))+'</dd>'+'\n'
        html += '    </dl>'+'\n'
        html += '    <h4>Land fetchers by feature</h4>'+'\n'
        for feature, organized in cards_ramp_cards_land_fetch_by_feature.items():
            html += '      <h5>Land fetchers ('+feature+') by card type</h5>'+'\n'
            for card_type, cards_list in organized.items():  # pylint: disable=no-member
                extra_text = '(Ramp cards) ' if feature.startswith('to battlefield') else ''
                title = extra_text+'Land fetch ('+card_type+')'+': '+str(len(cards_list))
                html += '    <article>'+'\n'
                html += '      <details>'+'\n'
                html += '        <summary>'+title+'</summary>'+'\n'
                html += print_cards_list(sort_cards_by_cmc_and_name(cards_list),
                                        print_powr_tough = (card_type == 'creature'),
                                        print_type = (feature not in ['land cycling', 'channel']),
                                        limit = max_list_items,
                                        print_mana = (card_type not in ['land', 'stickers']),
                                        outformat = outformat, return_str = True)
                html += '      </details>'+'\n'
                html += '    </article>'+'\n'
        html += '  </section>'+'\n'
        print(html)

    if outformat == 'console':
        print('Land fetch (total):', len(cards_ramp_cards_land_fetch))
        print('')
        for feature, organized in cards_ramp_cards_land_fetch_by_feature.items():
            for card_type, cards_list in organized.items():  # pylint: disable=no-member
                extra_text = '(Ramp cards) ' if feature.startswith('to battlefield') else ''
                title = extra_text+'Land fetch ('+card_type+')'+': '+str(len(cards_list))
                print('   '+title)
                if ', conditional' in feature:
                    print('')
                    continue
                print_cards_list(sort_cards_by_cmc_and_name(cards_list),
                                 print_powr_tough = (card_type == 'creature'),
                                 print_type = (feature not in ['land cycling', 'channel']),
                                 indent = 8, limit = max_list_items,
                                 print_mana = (card_type not in ['land', 'stickers']),
                                 outformat = outformat)
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
               trunc_powr_tough = 6, separator_color = 'dark_grey', rank_price_color = 'light_grey',
               rank_price_attrs = None, outformat = 'console'):
    """Display a card or return a string representing it"""

    merge_type_powr_tough = merge_type_powr_tough and print_type and print_powr_tough
    if merge_type_powr_tough and (not trunc_type or trunc_type > 10):
        trunc_type = 10  # default power/toughness length
    len_type = '16' if not trunc_type else str(trunc_type)

    line = ''

    if outformat == 'html':
        html = ''
        html += '        <tr class="card-line">'+'\n'
        html += '          <td class="input">'
        html += '<input type="checkbox" name="cards" value="'+card['name']+'" '
        card_type = get_card_type(card)
        html += 'onchange="update_deck_list(this, '+f"'{card_type}'"+')"/></td>\n'
        if print_edhrank:
            edhrank_value = card['edhrec_rank'] if 'edhrec_rank' in card else ''
            html += '          <td class="edhrank '+rank_price_color+'">'+str(edhrank_value)+'</td>\n'
        if print_price:
            price = (str(card['prices']['usd']) if 'prices' in card and 'usd' in card['prices']
                     and card['prices']['usd'] else '')
            html += '          <td class="price '+rank_price_color+'">'+str(price)+'</td>'+'\n'
        if print_mana:
            mana = colorize_mana(' // '.join(get_mana_cost(card)), no_braces = True)
            html += '          <td class="mana">'+mana+'</td>'+'\n'
        if merge_type_powr_tough:
            if is_creature(card):
                powr_tough = ' // '.join(get_powr_tough(card))
                html += '          <td class="power-toughness">'+powr_tough+'</td>'+'\n'
            else:
                typel = truncate_text((' // '.join(get_type_lines(card))), trunc_type)
                html += '          <td class="type">'+typel+'</td>'+'\n'
        else:
            if print_powr_tough:
                powr_tough = ''
                if is_creature(card):
                    powr_tough = ' // '.join(get_powr_tough(card))
                html += '          <td class="power-toughness">'+powr_tough+'</td>'+'\n'
            if print_type:
                typel = truncate_text((' // '.join(get_type_lines(card))), trunc_type)
                html += '          <td class="type">'+typel+'</td>'+'\n'

        name = card['name']
        imgurl = ''
        if 'image_uris' in card and 'normal' in card['image_uris']:
            imgurl = card['image_uris']['normal']
        elif ('card_faces' in card and card['card_faces'] and 'image_uris' in card['card_faces'][0]
              and 'normal' in card['card_faces'][0]['image_uris']):
            imgurl = card['card_faces'][0]['image_uris']['normal']
        img_element = '<img src="#" data-imgurl="'+imgurl+'" alt="image of card '+name+'" />'
        if not imgurl:
            img_element = '<span class="card-not-found">/<span>'
        name_and_link = ('<a class="'+get_card_colored(card)+'" href="#" onmouseover="loadimg(this);">'
                            +'<span class="name">'+name+'</span>'
                            +'<span class="image">'+img_element+'</span>'
                          +'</a>')
        html += '          <td class="name">'+name_and_link+'</td>'+'\n'

        if print_keywords:
            keywords = ' // '.join(list(map(lambda k: ', '.join(k), get_keywords(card))))  # pylint: disable=unnecessary-lambda
            html += '          <td class="keywords">'+keywords+'</td>'+'\n'

        if print_text:
            text = join_oracle_texts(card, (trunc_text if trunc_text != 'auto' else False))
            html += '          <td class="text">'+text+'</td>'+'\n'

        html += '        </tr>'+'\n'
        line = html

    if outformat == 'console':
        line_visible_len = 0
        separator = ' | '
        separator_colored = colored(separator, separator_color)

        rank_price_attrs = rank_price_attrs if rank_price_attrs is not None else ['dark']

        indent_fmt = '{:<'+str(indent)+'}'
        indent_part = indent_fmt.format('')
        line += indent_part
        line_visible_len += len(indent_part)

        if print_edhrank:
            edhrank_fmt = '# {:>5}'
            edhrank_part = edhrank_fmt.format(card['edhrec_rank'] if 'edhrec_rank' in card else '')
            edhrank_part_colored = colored(edhrank_part, rank_price_color, attrs=rank_price_attrs)
            line += edhrank_part_colored + separator_colored
            line_visible_len += len(edhrank_part + separator)

        if print_price:
            price_fmt = '$ {:>5}'
            price_part = price_fmt.format(str(card['prices']['usd'])
                                        if 'prices' in card and 'usd' in card['prices']
                                        and card['prices']['usd'] else '')
            price_part_colored = colored(price_part, rank_price_color, attrs=rank_price_attrs)
            line += price_part_colored + separator_colored
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
        name_part = name_fmt.format(truncate_text(card['name'], trunc_name))
        name_part_colored = colored(name_part, get_card_colored(card))
        line += name_part_colored + separator_colored
        line_visible_len += len(name_part + separator)

        if print_keywords:
            keywords_fmt = '{}'
            keywords_part = keywords_fmt.format(' // '.join(list(map(lambda k: ', '.join(k),  # pylint: disable=unnecessary-lambda
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
                # text_part_no_color = text_fmt.format(join_oracle_texts(
                #     card, (trunc_text if trunc_text != 'auto' else False), colorize = False))
                text_wrapped = wrap(text_part_colored, width = len_left, placeholder = '…')
                text_part_colored = (
                    '⤵\n'+('{:>'+str(line_visible_len)+'}').format('')).join(text_wrapped)

            text_part_colored = colorize_mana(text_part_colored)
            line += text_part_colored

    if not return_str:
        print(line)

    return line

def assist_ramp_cards(cards, land_types_invalid_regex, max_list_items = None, outformat = 'console'):
    """Show pre-selected ramp cards organised by features, for the user to select some"""

    cards_ramp_cards = []
    cards_ramp_cards_by_features = {}
    for card in cards:
        if card['name'] not in ["Strata Scythe", "Trench Gorger"]:
            oracle_texts = list(get_oracle_texts(card))
            oracle_texts_low = list(map(str.lower, oracle_texts))
            if (not list(search_strings(RAMP_CARDS_EXCLUDE_REGEX, oracle_texts_low))
                    and not list(search_strings(land_types_invalid_regex, oracle_texts_low))
                    # and not list(search_strings(r'(you|target player|opponent).*discard',
                    #                             oracle_texts_low))
                    # and not list(in_strings('graveyard', oracle_texts_low))
                    and not filter_lands(card)):
                for feature, regexes in RAMP_CARDS_REGEX_BY_FEATURES.items():
                    regex = r'('+('|'.join(regexes))+')'
                    if list(search_strings(regex, oracle_texts_low)):
                        if feature not in cards_ramp_cards_by_features:
                            cards_ramp_cards_by_features[feature] = []
                        cards_ramp_cards_by_features[feature].append(card)
                        cards_ramp_cards.append(card)

    cards_ramp_cards_selected = []
    for cards_list in cards_ramp_cards_by_features.values():
        cards_ramp_cards_selected += sort_cards_by_cmc_and_name(cards_list)[:max_list_items]

    if outformat == 'html':
        html = ''
        html += '  <section>'+'\n'
        html += '    <h3 id="ramp-cards">Ramp cards</h3>\n'
        html += '    <h4>Stats</h4>'+'\n'
        html += '    <dl>'+'\n'
        html += '      <dt>Ramp cards (total)</dt>'+'\n'
        html += '      <dd>'+str(len(cards_ramp_cards))+'</dd>'+'\n'
        html += '    </dl>'+'\n'
        html += '    <h4>Ramp cards by feature</h4>'+'\n'
        for feature, cards_list in cards_ramp_cards_by_features.items():
            cards_list_sorted = sort_cards_by_cmc_and_name(cards_list)
            title = 'Ramp cards ('+feature+'): '+str(len(cards_list_sorted))
            html += '    <article>'+'\n'
            html += '      <details>'+'\n'
            html += '        <summary>'+title+'</summary>'+'\n'
            html += print_cards_list(cards_list_sorted, limit = max_list_items,
                                     outformat = outformat, return_str = True)
            html += '      </details>'+'\n'
            html += '    </article>'+'\n'
        html += '  </section>'+'\n'
        print(html)

    if outformat == 'console':
        print('Ramp cards:', len(cards_ramp_cards))
        print('')
        for feature, cards_list in cards_ramp_cards_by_features.items():
            cards_list_sorted = sort_cards_by_cmc_and_name(cards_list)
            print('Ramp cards ('+feature+'):', len(cards_list_sorted))
            print('')
            print_cards_list(cards_list_sorted, limit = max_list_items, indent = 3)
            print('')

    return cards_ramp_cards_selected

def assist_draw_cards(cards, land_types_invalid_regex, max_list_items = None, outformat = 'console'):
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

    cards_draw_cards_not_repeating_cmc_3 = sort_cards_by_cmc_and_name(list(filter(
        lambda c: int(c['cmc']) <= 3,
        [c for c in cards_draw_cards if c not in cards_draw_cards_repeating
         and c not in cards_draw_cards_multiple])))

    connives = list(filter(lambda c: bool(list(
        in_strings('connives', map(str.lower, get_oracle_texts(c))))), cards))

    draw_output_data = {
        'repeating': cards_draw_cards_repeating,
        'multiple': cards_draw_cards_multiple,
        'connives': connives,
        'not repeating, CMC <= 3': cards_draw_cards_not_repeating_cmc_3}

    cards_draw_cards_selected = []
    for cards_list in draw_output_data.values():
        cards_draw_cards_selected += sort_cards_by_cmc_and_name(cards_list)[:max_list_items]

    if outformat == 'html':
        html = ''
        html += '  <section>'+'\n'
        html += '    <h3 id="draw-cards">Draw cards</h3>\n'
        html += '    <h4>Stats</h4>'+'\n'
        html += '    <dl>'+'\n'
        html += '      <dt>Draw cards (total)</dt>'+'\n'
        html += '      <dd>'+str(len(cards_draw_cards))+'</dd>'+'\n'
        html += '    </dl>'+'\n'
        html += '    <h4>Draw cards by feature</h4>'+'\n'
        for feature, cards_list in draw_output_data.items():
            title = 'Draw cards ('+feature+'): '+str(len(cards_list))
            html += '    <article>'+'\n'
            html += '      <details>'+'\n'
            html += '        <summary>'+title+'</summary>'+'\n'
            html += print_cards_list(sort_cards_by_cmc_and_name(cards_list),
                                     limit = max_list_items, outformat = outformat, return_str = True)
            html += '      </details>'+'\n'
            html += '    </article>'+'\n'
        html += '  </section>'+'\n'
        print(html)

    if outformat == 'console':
        print('Draw cards:', len(cards_draw_cards))
        print('')
        for feature, cards_list in draw_output_data.items():
            title = 'Draw cards ('+feature+'): '+str(len(cards_list))
            print(title)
            print('')
            print_cards_list(sort_cards_by_cmc_and_name(cards_list), limit = max_list_items,
                             indent = 3, outformat = outformat)
        print('')

    return cards_draw_cards_selected

def assist_tutor_cards(cards, land_types_invalid_regex, max_list_items = None, outformat='console'):
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

    tutor_stats_data = {
        'Tutor cards': len(cards_tutor_cards),
        'Tutor cards (not generic enough)':
            len(cards_tutor_cards) - len(cards_tutor_cards_generic),
        'Tutor cards (not themed)': len(cards_tutor_cards_not_themed),
        'Tutor cards (not themed, to battlefield)': len(cards_tutor_cards_to_battlefield),
        'Tutor cards (not themed, to hand)': len(cards_tutor_cards_to_hand),
        'Tutor cards (not themed, to top of library)': len(cards_tutor_cards_to_top_library),
        'Tutor cards (not themed, other)': len(cards_tutor_cards_other),
        'Tutor cards (themed)': len(cards_tutor_cards_themed),
        'Tutor cards (themed, against)': len(cards_tutor_cards_against),
        'Tutor cards (themed, transmute)': len(cards_tutor_cards_transmute),
        'Tutor cards (themed, artifact)': len(cards_tutor_cards_artifact),
        'Tutor cards (themed, graveyard)': len(cards_tutor_cards_graveyard),
        'Tutor cards (themed, Equipment)': len(cards_tutor_cards_equipment),
        'Tutor cards (themed, Aura)': len(cards_tutor_cards_aura)}

    tutor_output_data = {
        'Tutor cards (not themed)': {
            'Tutor cards (not themed, to battlefield)': cards_tutor_cards_to_battlefield,
            'Tutor cards (not themed, to hand)': cards_tutor_cards_to_hand,
            'Tutor cards (not themed, to top of library)': cards_tutor_cards_to_top_library,
            'Tutor cards (not themed, other)': cards_tutor_cards_other},
        'Tutor cards (themed)': {
            'Tutor cards (themed, against)': cards_tutor_cards_against,
            'Tutor cards (themed, transmute)': cards_tutor_cards_transmute,
            'Tutor cards (themed, artifact)': cards_tutor_cards_artifact,
            'Tutor cards (themed, graveyard)': cards_tutor_cards_graveyard,
            'Tutor cards (themed, Equipment)': cards_tutor_cards_equipment,
            'Tutor cards (themed, Aura)': cards_tutor_cards_aura}}

    cards_tutor_cards_selected = []
    for data in tutor_output_data.values():
        for cards_list in data.values():
            cards_tutor_cards_selected += sort_cards_by_cmc_and_name(cards_list)[:max_list_items]

    if outformat == 'html':
        html = ''
        html += '  <section>'+'\n'
        html += '    <h3 id="tutor-cards">Tutor cards</h3>\n'
        html += '    <h4>Stats</h4>'+'\n'
        html += '    <dl>'+'\n'
        for title, count in tutor_stats_data.items():
            html += '      <dt>'+title+'</dt>'+'\n'
            html += '      <dd>'+str(count)+'</dd>'+'\n'
        html += '    </dl>'+'\n'
        for section, data in tutor_output_data.items():
            html += '    <h4>'+section+'</h4>'+'\n'
            for title, cards_list in data.items():
                title += ': '+str(len(cards_list))
                html += '    <article>'+'\n'
                html += '      <details>'+'\n'
                html += '        <summary>'+title+'</summary>'+'\n'
                html += print_cards_list(sort_cards_by_cmc_and_name(cards_list),
                                         limit = max_list_items, outformat = outformat, return_str = True)
                html += '      </details>'+'\n'
                html += '    </article>'+'\n'
        html += '  </section>'+'\n'
        print(html)

    if outformat == 'console':
        for title, count in tutor_stats_data.items():
            print(title+':', count)
        print('')
        for section, data in tutor_output_data.items():
            print(section)
            for title, cards_list in data.items():
                print('   '+title+':', len(cards_list))
                print_cards_list(sort_cards_by_cmc_and_name(cards_list), limit = max_list_items,
                                 indent = 8, outformat = outformat)
        print('')

    return cards_tutor_cards_selected

def assist_removal_cards(cards, max_list_items = None, outformat = 'console'):
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
                 .replace('Exile '+card['name'], '')  # pylint: disable=cell-var-from-loop
                 .replace('Exile '+card['name']+'. Return it to the battlefield', '')  # pylint: disable=cell-var-from-loop
                 .replace('destroy '+card['name'], '')  # pylint: disable=cell-var-from-loop
                 .replace('Return '+card['name']+" to its owner's hand", '')  # pylint: disable=cell-var-from-loop
                 .replace('return '+card['name']+" to its owner's hand", '')  # pylint: disable=cell-var-from-loop
                 .replace('If '+card['name']+' would be put into a graveyard from anywhere, '+  # pylint: disable=cell-var-from-loop
                          'exile it instead.', '')),
                oracle_texts))
            if 'card_faces' in card:
                for face in card['card_faces']:
                    oracle_texts_filtered = list(map(lambda t: (
                        t.replace('Exile '+face['name'], '')  # pylint: disable=cell-var-from-loop
                         .replace('destroy '+face['name'], '')  # pylint: disable=cell-var-from-loop
                         .replace('If '+face['name']+' would be put into a graveyard from anywhere'+  # pylint: disable=cell-var-from-loop
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

    cards_removal_cmc_3_return_to_hand = list(filter(
        lambda c: bool(list(search_strings(r"returns? .* to (its|their) owner('s|s') hand",
                                           list(map(str.lower, get_oracle_texts(c)))))),
        cards_removal_cmc_3))

    cards_removal_cmc_3_put_to_library_bottom = list(filter(
        lambda c: bool(list(search_strings(
            r"puts? .* on the bottom of (its|their) owner('s|s') library",
            list(map(str.lower, get_oracle_texts(c)))))),
        cards_removal_cmc_3))
    cards_removal_cmc_3_put_to_library_top = list(filter(
        lambda c: bool(list(search_strings(r"puts? .* on top of (its|their) owner('s|s') library",
                                           list(map(str.lower, get_oracle_texts(c)))))),
        cards_removal_cmc_3))
    cards_removal_cmc_3_put_to_library_other = list(filter(
        lambda c: bool(list(search_strings(
            r"(puts? .* into (its|their) owner('s|s') library|shuffles it into (its|their) library)",
            list(map(str.lower, get_oracle_texts(c)))))),
        cards_removal_cmc_3))

    cards_removal_cmc_3_untargetted = list(filter(
        lambda c: bool(list(search_strings(
            r"(target|each|every) (opponents?|players?) sacrifices? an?( attacking)? creature",
            list(map(str.lower, get_oracle_texts(c)))))),
        cards_removal_cmc_3))

    cards_removal_cmc_3_creature_toughness_malus = list(filter(
        lambda c: bool(list(search_strings(
            r"creatures? gets? [+-][0-9Xx]+/-[1-9Xx]+",
            list(map(str.lower, get_oracle_texts(c)))))),
        cards_removal_cmc_3))

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

    removal_stats_data = {
        'Removal cards': len(cards_removal),
        'Removal cards (CMC <= 3, not destroy land)': len(cards_removal_cmc_3_not_destroy_land),
        'Removal cards (CMC <= 3, destroy permanent)': len(cards_removal_cmc_3_destroy_permanent),
        'Removal cards (CMC <= 3, destroy three choices)': len(cards_removal_cmc_3_destroy_three),
        'Removal cards (CMC <= 3, destroy two choices)': len(cards_removal_cmc_3_destroy_two),
        'Removal cards (CMC <= 3, destroy creature, sacrifice one)':
            len(cards_removal_cmc_3_destroy_creature)
            - len(cards_removal_cmc_3_destroy_creature_no_sacrifice),
        'Removal cards (CMC <= 3, destroy creature, no exclusion)':
            len(cards_removal_cmc_3_destroy_creature_no_exclusion),
        'Removal cards (CMC <= 3, destroy creature, exclusion)':
            len(cards_removal_cmc_3_destroy_creature_exclusion),
        'Removal cards (CMC <= 3, destroy enchantments)':
            len(cards_removal_cmc_3_destroy_enchantment),
        'Removal cards (CMC <= 3, destroy other)': len(cards_removal_cmc_3_destroy_other),
        'Removal cards (CMC <= 3, destroy untargetted)': len(cards_removal_cmc_3_untargetted),
        'Removal cards (CMC <= 3, return to hand)': len(cards_removal_cmc_3_return_to_hand),
        'Removal cards (CMC <= 3, put to library, bottom)':
            len(cards_removal_cmc_3_put_to_library_bottom),
        'Removal cards (CMC <= 3, put to library, top)':
            len(cards_removal_cmc_3_put_to_library_top),
        'Removal cards (CMC <= 3, put to library, other)':
            len(cards_removal_cmc_3_put_to_library_other),
        'Removal cards (CMC <= 3, creature, toughness malus)':
            len(cards_removal_cmc_3_creature_toughness_malus),
        }

    removal_output_data = {
        'Removal cards (CMC <= 3) choice in target': {
            'Removal cards (CMC <= 3, destroy permanent)': cards_removal_cmc_3_destroy_permanent,
            'Removal cards (CMC <= 3, destroy three choices)': cards_removal_cmc_3_destroy_three,
            'Removal cards (CMC <= 3, destroy two choices)': cards_removal_cmc_3_destroy_two},
        'Removal cards (CMC <= 3) specific target': {
            'Removal cards (CMC <= 3, destroy creature, no exclusion)':
                cards_removal_cmc_3_destroy_creature_no_exclusion,
            'Removal cards (CMC <= 3, destroy creature, exclusion)':
                cards_removal_cmc_3_destroy_creature_exclusion,
            'Removal cards (CMC <= 3, destroy enchantments)':
                cards_removal_cmc_3_destroy_enchantment,
            'Removal cards (CMC <= 3, destroy other)': cards_removal_cmc_3_destroy_other},
        'Removal cards (CMC <= 3, untargetted)': {
            'Removal cards (CMC <= 3, untargetted)': cards_removal_cmc_3_untargetted},
        'Removal cards (CMC <= 3, return to hand)': {
            'Removal cards (CMC <= 3, return to hand)': cards_removal_cmc_3_return_to_hand},
        'Removal cards (CMC <= 3, put to library)': {
            'Removal cards (CMC <= 3, put to library, bottom)':
                cards_removal_cmc_3_put_to_library_bottom,
            'Removal cards (CMC <= 3, put to library, top)':
                cards_removal_cmc_3_put_to_library_top,
            'Removal cards (CMC <= 3, put to library, other)':
                cards_removal_cmc_3_put_to_library_other},
        'Removal cards (CMC <= 3, creature affection)': {
            'Removal cards (CMC <= 3, creature, toughness malus)':
                cards_removal_cmc_3_creature_toughness_malus}}

    cards_removal_cards_selected = []
    for data in removal_output_data.values():
        for cards_list in data.values():
            cards_removal_cards_selected += sort_cards_by_cmc_and_name(cards_list)[:max_list_items]

    if outformat == 'html':
        html = ''
        html += '  <section>'+'\n'
        html += '    <h3 id="removal-cards">Removal cards</h3>\n'
        html += '    <h4>Stats</h4>'+'\n'
        html += '    <dl>'+'\n'
        for title, count in removal_stats_data.items():
            html += '      <dt>'+title+'</dt>'+'\n'
            html += '      <dd>'+str(count)+'</dd>'+'\n'
        html += '    </dl>'+'\n'
        for section, data in removal_output_data.items():
            html += '    <h4>'+section+'</h4>'+'\n'
            for title, cards_list in data.items():
                title += ': '+str(len(cards_list))
                html += '    <article>'+'\n'
                html += '      <details>'+'\n'
                html += '        <summary>'+title+'</summary>'+'\n'
                html += print_cards_list(sort_cards_by_cmc_and_name(cards_list),
                                         limit = max_list_items, outformat = outformat, return_str = True)
                html += '      </details>'+'\n'
                html += '    </article>'+'\n'
        html += '  </section>'+'\n'
        print(html)

    if outformat == 'console':
        for title, count in removal_stats_data.items():
            print(title+':', count)
        print('')
        for section, data in removal_output_data.items():
            print(section)
            for title, cards_list in data.items():
                print('   '+title+':', len(cards_list))
                print_cards_list(sort_cards_by_cmc_and_name(cards_list), limit = max_list_items,
                                 indent = 8, outformat = outformat)
        print('')

    return cards_removal

def assist_disabling_cards(cards, max_list_items = None, outformat = 'console'):
    """Show pre-selected disabling cards organised by features, for the user to select some"""

    cards_disabling = []
    if DISABLING_CARDS_REGEX:
        for card in cards:
            oracle_texts = list(get_oracle_texts(card))
            oracle_texts_filtered = list(map(lambda t: (
                t.replace("(This creature can't attack.)", '')
                 .replace(card['name']+' becomes a Shapeshifter artifact creature '  # pylint: disable=cell-var-from-loop
                          'with base power and toughness', '')),
                oracle_texts))
            if 'card_faces' in card:
                for face in card['card_faces']:
                    oracle_texts_filtered = list(map(lambda t: (
                        t.replace("(This creature can't attack.)", '')
                          .replace(face['name']+' becomes a Shapeshifter artifact creature'  # pylint: disable=cell-var-from-loop
                                   ' with base power and toughness', '')),
                        oracle_texts_filtered))
            oracle_texts_low = list(map(str.lower, oracle_texts_filtered))
            for regexp in DISABLING_CARDS_REGEX:
                if (list(search_strings(regexp, oracle_texts_low))
                        and not list(search_strings(DISABLING_CARDS_EXCLUDE_REGEX,
                                                    oracle_texts_low))):
                    cards_disabling.append(card)
                    break

    cards_disabling_cmc_3 = list(filter(lambda c: c['cmc'] <= 3, cards_disabling))

    cards_disabling_cmc_3_creature_no_abilities = list(filter(
        lambda c: bool(list(search_strings(
            r"(activated abilities can't be activated|activated abilities of [^.]+ can't be activated)",
            list(map(str.lower, get_oracle_texts(c)))))),
        cards_disabling_cmc_3))

    cards_disabling_cmc_3_creature_cant_attack_or_block = list(filter(
        lambda c: bool(list(search_strings(
            r"creature can't (block|attack( or block)?)",
            list(map(str.lower, get_oracle_texts(c)))))),
        cards_disabling_cmc_3))

    cards_disabling_cmc_3_creature_tap = list(filter(
        lambda c: bool(list(search_strings(
            r"(creature doesn't untap|if enchanted creature is untapped, tap it)",
            list(map(str.lower, get_oracle_texts(c)))))),
        cards_disabling_cmc_3))

    cards_disabling_cmc_3_creature_phaseout = list(filter(
        lambda c: bool(list(search_strings(
            r"creature phases out",
            list(map(str.lower, get_oracle_texts(c)))))),
        cards_disabling_cmc_3))

    cards_disabling_cmc_3_creature_mutate = list(filter(
        lambda c: bool(list(search_strings(
            r"(base power and toughness \d/\d|enchanted \w+ (is|becomes) a )",
            list(map(str.lower, get_oracle_texts(c)))))),
        cards_disabling_cmc_3))

    disabling_stats_data = {
        'Disabling cards': len(cards_disabling),
        'Disabling cards (CMC <= 3, creature, loses all abilities)':
            len(cards_disabling_cmc_3_creature_no_abilities),
        "Disabling cards (CMC <= 3, creature, can't attack or block)":
            len(cards_disabling_cmc_3_creature_cant_attack_or_block),
        'Disabling cards (CMC <= 3, creature, tap)': len(cards_disabling_cmc_3_creature_tap),
        'Disabling cards (CMC <= 3, creature, phase out)':
            len(cards_disabling_cmc_3_creature_phaseout),
        'Disabling cards (CMC <= 3, creature, mutate)': len(cards_disabling_cmc_3_creature_mutate),
        }

    disabling_output_data = {
        'Disabling cards (CMC <= 3, creature affection)': {
            'Disabling cards (CMC <= 3, creature, loses all abilities)':
                cards_disabling_cmc_3_creature_no_abilities,
            "Disabling cards (CMC <= 3, creature, can't attack or block)":
                cards_disabling_cmc_3_creature_cant_attack_or_block,
            'Disabling cards (CMC <= 3, creature, tap)': cards_disabling_cmc_3_creature_tap,
            'Disabling cards (CMC <= 3, creature, phase out)': cards_disabling_cmc_3_creature_phaseout,
            'Disabling cards (CMC <= 3, creature, mutate)': cards_disabling_cmc_3_creature_mutate}}

    cards_disabling_cards_selected = []
    for data in disabling_output_data.values():
        for cards_list in data.values():
            cards_disabling_cards_selected += sort_cards_by_cmc_and_name(cards_list)[:max_list_items]

    if outformat == 'html':
        html = ''
        html += '  <section>'+'\n'
        html += '    <h3 id="disabling-cards">Disabling cards</h3>\n'
        html += '    <h4>Stats</h4>'+'\n'
        html += '    <dl>'+'\n'
        for title, count in disabling_stats_data.items():
            html += '      <dt>'+title+'</dt>'+'\n'
            html += '      <dd>'+str(count)+'</dd>'+'\n'
        html += '    </dl>'+'\n'
        for section, data in disabling_output_data.items():
            html += '    <h4>'+section+'</h4>'+'\n'
            for title, cards_list in data.items():
                title += ': '+str(len(cards_list))
                html += '    <article>'+'\n'
                html += '      <details>'+'\n'
                html += '        <summary>'+title+'</summary>'+'\n'
                html += print_cards_list(sort_cards_by_cmc_and_name(cards_list),
                                         limit = max_list_items, outformat = outformat, return_str = True)
                html += '      </details>'+'\n'
                html += '    </article>'+'\n'
        html += '  </section>'+'\n'
        print(html)

    if outformat == 'console':
        for title, count in disabling_stats_data.items():
            print(title+':', count)
        print('')
        for section, data in disabling_output_data.items():
            print(section)
            for title, cards_list in data.items():
                print('   '+title+':', len(cards_list))
                print_cards_list(sort_cards_by_cmc_and_name(cards_list), limit = max_list_items,
                                 indent = 8, outformat = outformat)
        print('')

    return cards_disabling

def assist_wipe_cards(cards, max_list_items = None, outformat = 'console'):
    """Show pre-selected board wipe cards organised by features, for the user to select some"""

    cards_wipe = []
    if WIPE_CARDS_REGEX:
        for card in cards:
            oracle_texts = list(get_oracle_texts(card))
            oracle_texts_low = list(map(str.lower, oracle_texts))
            for regexp in WIPE_CARDS_REGEX:
                if (list(search_strings(regexp, oracle_texts_low))
                        and not list(search_strings(WIPE_CARDS_EXCLUDE_REGEX,
                                                    oracle_texts_low))):
                    cards_wipe.append(card)
                    break

    cards_wipe_sorted = sort_cards_by_cmc_and_name(cards_wipe)
    cards_wipe_selected = cards_wipe_sorted[:max_list_items]

    if outformat == 'html':
        html = ''
        html += '  <section>'+'\n'
        html += '    <h3 id="wipe-cards">Board wipe cards</h3>\n'
        title = 'Board wipe cards: '+str(len(cards_wipe))
        html += '    <article>'+'\n'
        html += '      <details>'+'\n'
        html += '        <summary>'+title+'</summary>'+'\n'
        html += print_cards_list(cards_wipe_sorted, limit = max_list_items,
                                 outformat = outformat, return_str = True)
        html += '      </details>'+'\n'
        html += '    </article>'+'\n'
        html += '  </section>'+'\n'
        print(html)

    if outformat == 'console':
        title = 'Board wipe cards: '+str(len(cards_wipe))
        print(title)
        print('')
        print_cards_list(cards_wipe_sorted, limit = max_list_items, indent = 8,
                         outformat = outformat)
        print('')

    return cards_wipe_selected

def assist_graveyard_recursion_cards(cards, max_list_items = None, outformat = 'console'):
    """Show pre-selected graveyard recursion cards organised by features, for the user to select some"""

    cards_grav_recur = []
    if GRAVEYARD_RECURSION_CARDS_REGEX:
        for card in cards:
            oracle_texts = list(get_oracle_texts(card))
            oracle_texts_low = list(map(str.lower, oracle_texts))
            for regexp in GRAVEYARD_RECURSION_CARDS_REGEX:
                if (list(search_strings(regexp, oracle_texts_low))
                        and not list(search_strings(GRAVEYARD_RECURSION_CARDS_EXCLUDE_REGEX,
                                                    oracle_texts_low))):
                    cards_grav_recur.append(card)
                    break

    cards_grav_recur_cmc_3 = list(filter(lambda c: c['cmc'] <= 3, cards_grav_recur))

    cards_grav_recur_cmc_3_target_creature = list(filter(
        lambda c: bool(list(in_strings('creature', list(map(str.lower, get_oracle_texts(c)))))),
        cards_grav_recur_cmc_3))
    cards_grav_recur_cmc_3_target_creature_battlefield = list(filter(
        lambda c: bool(list(in_strings('battlefield', list(map(str.lower, get_oracle_texts(c)))))),
        cards_grav_recur_cmc_3_target_creature))
    cards_grav_recur_cmc_3_target_creature_hand = list(filter(
        lambda c: bool(list(in_strings('hand', list(map(str.lower, get_oracle_texts(c)))))),
        [c for c in cards_grav_recur_cmc_3_target_creature
         if c not in cards_grav_recur_cmc_3_target_creature_battlefield]))
    cards_grav_recur_cmc_3_target_creature_library = list(filter(
        lambda c: bool(list(in_strings('library', list(map(str.lower, get_oracle_texts(c)))))),
        [c for c in cards_grav_recur_cmc_3_target_creature
         if c not in cards_grav_recur_cmc_3_target_creature_battlefield
         and c not in cards_grav_recur_cmc_3_target_creature_hand]))

    cards_grav_recur_cmc_3_target_artifact = list(filter(
        lambda c: bool(list(in_strings('artifact', list(map(str.lower, get_oracle_texts(c)))))),
        [c for c in cards_grav_recur_cmc_3 if c not in cards_grav_recur_cmc_3_target_creature]))

    cards_grav_recur_cmc_3_target_instant_or_sorcery = list(filter(
        lambda c: bool(list(search_strings('instant|sorcery', list(map(str.lower, get_oracle_texts(c)))))),
        [c for c in cards_grav_recur_cmc_3 if c not in cards_grav_recur_cmc_3_target_creature
         and c not in cards_grav_recur_cmc_3_target_artifact]))

    cards_grav_recur_cmc_3_other = [
        c for c in cards_grav_recur_cmc_3 if c not in cards_grav_recur_cmc_3_target_creature
        and c not in cards_grav_recur_cmc_3_target_artifact
        and c not in cards_grav_recur_cmc_3_target_instant_or_sorcery]

    grav_recur_stats_data = {
        'Graveyard recursion cards': len(cards_grav_recur),
        'Graveyard recursion cards (CMC <= 3)': len(cards_grav_recur_cmc_3),
        'Graveyard recursion cards (CMC <= 3, creatures)': len(cards_grav_recur_cmc_3_target_creature),
        'Graveyard recursion cards (CMC <= 3, creatures, to battlefield)': len(cards_grav_recur_cmc_3_target_creature_battlefield),
        'Graveyard recursion cards (CMC <= 3, creatures, to hand)': len(cards_grav_recur_cmc_3_target_creature_hand),
        'Graveyard recursion cards (CMC <= 3, creatures, to library)': len(cards_grav_recur_cmc_3_target_creature_library),
        'Graveyard recursion cards (CMC <= 3, artifacts)': len(cards_grav_recur_cmc_3_target_artifact),
        'Graveyard recursion cards (CMC <= 3, instants or sorcery)': len(cards_grav_recur_cmc_3_target_instant_or_sorcery),
        'Graveyard recursion cards (CMC <= 3, other)': len(cards_grav_recur_cmc_3_other),
        }

    grav_recur_output_data = {
        'Graveyard recursion cards (CMC <= 3) by target': {
            'Graveyard recursion cards (CMC <= 3, creatures, to battlefield)':
                cards_grav_recur_cmc_3_target_creature_battlefield,
            'Graveyard recursion cards (CMC <= 3, creatures, to hand)':
                cards_grav_recur_cmc_3_target_creature_hand,
            'Graveyard recursion cards (CMC <= 3, creatures, to library)':
                cards_grav_recur_cmc_3_target_creature_library,
            'Graveyard recursion cards (CMC <= 3, artifacts)':
                cards_grav_recur_cmc_3_target_artifact,
            'Graveyard recursion cards (CMC <= 3, instants or sorcery)':
                cards_grav_recur_cmc_3_target_instant_or_sorcery,
            'Graveyard recursion cards (CMC <= 3, other)':
                cards_grav_recur_cmc_3_other}}

    cards_grav_recur_cards_selected = []
    for data in grav_recur_output_data.values():
        for cards_list in data.values():
            cards_grav_recur_cards_selected += sort_cards_by_cmc_and_name(cards_list)[:max_list_items]

    if outformat == 'html':
        html = ''
        html += '  <section>'+'\n'
        html += '    <h3 id="graveyard-recursion-cards">Graveyard recursion cards</h3>\n'
        html += '    <h4>Stats</h4>'+'\n'
        html += '    <dl>'+'\n'
        for title, count in grav_recur_stats_data.items():
            html += '      <dt>'+title+'</dt>'+'\n'
            html += '      <dd>'+str(count)+'</dd>'+'\n'
        html += '    </dl>'+'\n'
        for section, data in grav_recur_output_data.items():
            html += '    <h4>'+section+'</h4>'+'\n'
            for title, cards_list in data.items():
                title += ': '+str(len(cards_list))
                html += '    <article>'+'\n'
                html += '      <details>'+'\n'
                html += '        <summary>'+title+'</summary>'+'\n'
                html += print_cards_list(sort_cards_by_cmc_and_name(cards_list),
                                         limit = max_list_items, outformat = outformat, return_str = True)
                html += '      </details>'+'\n'
                html += '    </article>'+'\n'
        html += '  </section>'+'\n'
        print(html)

    if outformat == 'console':
        for title, count in grav_recur_stats_data.items():
            print(title+':', count)
        print('')
        for section, data in grav_recur_output_data.items():
            print(section)
            for title, cards_list in data.items():
                print('   '+title+':', len(cards_list))
                print_cards_list(sort_cards_by_cmc_and_name(cards_list), limit = max_list_items,
                                 indent = 8, outformat = outformat)
        print('')

    return cards_grav_recur_cards_selected

def assist_graveyard_hate_cards(cards, max_list_items = None, outformat = 'console'):
    """Show pre-selected graveyard hate cards organised by features, for the user to select some"""

    cards_grav_hate = {}
    if GRAVEYARD_HATE_CARDS_REGEX:
        for card in cards:
            oracle_texts = list(get_oracle_texts(card))
            oracle_texts_low = list(map(str.lower, oracle_texts))
            for target, regexes in GRAVEYARD_HATE_CARDS_REGEX.items():
                for regexp in regexes:
                    if (list(search_strings(regexp, oracle_texts_low))
                            and not list(search_strings(GRAVEYARD_HATE_CARDS_EXCLUDE_REGEX,
                                                        oracle_texts_low))):
                        if target not in cards_grav_hate:
                            cards_grav_hate[target] = []
                        cards_grav_hate[target].append(card)
                        break

    grav_hate_stats_data = {'Graveyard hate cards (total)': sum(map(len, cards_grav_hate.values()))}
    grav_hate_output_data = {'Graveyard hate cards (CMC <= 3) by target': {}}
    cards_grav_hate_keys = list(cards_grav_hate.keys())
    for target in cards_grav_hate_keys:
        cards_list = cards_grav_hate[target]
        target_cmc3 = target+' (CMC <= 3)'
        cards_grav_hate[target_cmc3] = list(filter(lambda c: c['cmc'] <= 3, cards_list))
        title = 'Graveyard hate cards'
        title_target = title + ' ('+target+')'
        title_target_cmc3 = title + ' ('+target+', CMC <= 3)'
        grav_hate_stats_data[title_target] = len(cards_list)
        grav_hate_stats_data[title_target_cmc3] = len(cards_grav_hate[target_cmc3])
        grav_hate_output_data['Graveyard hate cards (CMC <= 3) by target'][title_target_cmc3] = \
            cards_grav_hate[target_cmc3]

    cards_grav_hate_cards_selected = []
    for data in grav_hate_output_data.values():
        for cards_list in data.values():
            cards_grav_hate_cards_selected += sort_cards_by_cmc_and_name(cards_list)[:max_list_items]

    if outformat == 'html':
        html = ''
        html += '  <section>'+'\n'
        html += '    <h3 id="graveyard-hate-cards">Graveyard hate cards</h3>\n'
        html += '    <h4>Stats</h4>'+'\n'
        html += '    <dl>'+'\n'
        for title, count in grav_hate_stats_data.items():
            html += '      <dt>'+title+'</dt>'+'\n'
            html += '      <dd>'+str(count)+'</dd>'+'\n'
        html += '    </dl>'+'\n'
        for section, data in grav_hate_output_data.items():
            html += '    <h4>'+section+'</h4>'+'\n'
            for title, cards_list in data.items():
                title += ': '+str(len(cards_list))
                html += '    <article>'+'\n'
                html += '      <details>'+'\n'
                html += '        <summary>'+title+'</summary>'+'\n'
                html += print_cards_list(sort_cards_by_cmc_and_name(cards_list),
                                         limit = max_list_items, outformat = outformat, return_str = True)
                html += '      </details>'+'\n'
                html += '    </article>'+'\n'
        html += '  </section>'+'\n'
        print(html)

    if outformat == 'console':
        for title, count in grav_hate_stats_data.items():
            print(title+':', count)
        print('')
        for section, data in grav_hate_output_data.items():
            print(section)
            for title, cards_list in data.items():
                print('   '+title+':', len(cards_list))
                print_cards_list(sort_cards_by_cmc_and_name(cards_list), limit = max_list_items,
                                 indent = 8, outformat = outformat)
        print('')

    return cards_grav_hate_cards_selected

def assist_best_cards(cards, max_list_items = None, outformat = 'console'):
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

    # Best creature power and toughness to cmc
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

    # Best creature amount of (evergreen?) keywords by cmc
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

    # Best creature with first|double strike and deathtouch (and flying?)
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

    # Best creature with flying and deathtouch
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

    # Best creature with flying by power|toughness
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

    damage_to_cmc = {}
    for card in cards:
        if 'card_faces' in card:
            for face in card['card_faces']:
                if ('type_line' in face and face['type_line'] in ['Instant', 'Sorcery']
                        and 'oracle_text' in face and 'cmc' in face):
                    damage = None
                    matches = re.search('deals ([0-9x]+) damage', face['oracle_text'].lower())
                    if matches and matches.group(1) != 'x':
                        damage = float(matches.group(1))
                    if not damage:
                        continue
                    cmc = float(face['cmc']) if float(face['cmc']) > 1 else 1.0
                    ratio = round(damage / cmc, 3)
                    if ratio not in damage_to_cmc:
                        damage_to_cmc[ratio] = []
                    damage_to_cmc[ratio].append(card)
        else:
            if ('type_line' in card and card['type_line'] in ['Instant', 'Sorcery']
                    and 'oracle_text' in card and 'cmc' in card):
                damage = None
                matches = re.search('deals ([0-9x]+) damage', card['oracle_text'].lower())
                if matches and matches.group(1) != 'x':
                    damage = float(matches.group(1))
                if not damage:
                    continue
                cmc = float(card['cmc']) if float(card['cmc']) > 1 else 1.0
                ratio = round(damage / cmc, 3)
                if ratio not in damage_to_cmc:
                    damage_to_cmc[ratio] = []
                damage_to_cmc[ratio].append(card)
    damage_to_cmc = dict(sorted(damage_to_cmc.items(), reverse = True))

    # TODO Best 5 instant|sorcery wide damage to cmc

    best_cards_output_data = {
        'Best Power to CMC ratio': {
            'min_ratio': 2,
            'ratio:cards': power_to_cmc},
        'Best toughness to CMC ratio': {
            'min_ratio': 2,
            'ratio:cards': toughness_to_cmc},
        'Best power+toughness to CMC ratio': {
            'min_ratio': 4,
            'ratio:cards': powr_tough_to_cmc},
        'Best keywords count to CMC ratio': {
            'min_ratio': 1,
            'ratio:cards': keywords_to_cmc},
        'Best Deathtouch + First strike/Double strike': {
            'cards': deathtouch_strike},
        'Best Deathtouch + Flying': {
            'cards': deathtouch_flying},
        'Best Flying + Power to CMC ratio': {
            'min_ratio': 1.5,
            'ratio:cards': flying_power_to_cmc},
        'Best Flying + toughness to CMC ratio': {
            'min_ratio': 1.5,
            'ratio:cards': flying_toughness_to_cmc},
        'Best damage to CMC ratio': {
            'min_ratio': 1.01,
            'ratio:cards': damage_to_cmc},
    }

    if outformat == 'html':
        html = ''
        html += '  <section>'+'\n'
        html += '    <h3 id="best-cards">Best cards</h3>\n'
        for title, data in best_cards_output_data.items():
            html += '    <article>'+'\n'
            html += '      <details>'+'\n'
            html += '        <summary>'+title+'</summary>'+'\n'
            if 'ratio:cards' in data:
                min_ratio = data['min_ratio'] if 'min_ratio' in data else 0
                for ratio, cards_list in data['ratio:cards'].items():
                    if ratio <= min_ratio:
                        break
                    html += '      <h6>ratio '+str(ratio)+'</h6>'+'\n'
                    html += print_cards_list(sort_cards_by_cmc_and_name(cards_list),
                                             limit=max_list_items,
                                             outformat = outformat,
                                             return_str = True)
            if 'cards' in data:
                html += print_cards_list(sort_cards_by_cmc_and_name(data['cards']),
                                         limit = max_list_items, outformat = outformat, return_str = True)
            html += '      </details>'+'\n'
            html += '    </article>'+'\n'
        html += '  </section>'+'\n'
        print(html)

    if outformat == 'console':
        for title, data in best_cards_output_data.items():
            print(title)
            print('')
            if 'ratio:cards' in data:
                min_ratio = data['min_ratio'] if 'min_ratio' in data else 0
                for ratio, cards_list in data['ratio:cards'].items():
                    if ratio <= min_ratio:
                        break
                    print('  ratio', ratio)
                    print_cards_list(sort_cards_by_cmc_and_name(cards_list), limit=max_list_items,
                                    indent = 5, outformat = outformat)
                print('')
            if 'cards' in data:
                print_cards_list(sort_cards_by_cmc_and_name(data['cards']), limit = max_list_items,
                                 indent = 5, outformat = outformat)
                print('')
        print('')

    # TODO evasion cards (except flying)

    # TODO only return showed/selected cards (like other assist methods)
    return best_cards

def assist_copy_cards(cards, max_list_items = None, outformat = 'console'):
    """Show pre-selected copy cards organised by features, for the user to select some"""

    cards_copy = []
    if COPY_CARDS_REGEX:
        for card in cards:
            oracle_texts = list(get_oracle_texts(card))
            oracle_texts_filtered = list(map(lambda t: (
                t.replace("its controller may cast a copy of the encoded card without paying its mana cost", '')
                 .replace("(Create a token that's a copy of a creature token you control.)", '')
                 .replace('copy it and you may choose a new target for the copy', '')
                 .replace("create a token that's a copy of this creature that's tapped and attacking that player", '')),
                oracle_texts))
            if 'card_faces' in card:
                for face in card['card_faces']:
                    oracle_texts_filtered = list(map(lambda t: (
                        t.replace("its controller may cast a copy of the encoded card without paying its mana cost", '')
                         .replace("(Create a token that's a copy of a creature token you control.)", '')
                         .replace('copy it and you may choose a new target for the copy', '')
                         .replace("create a token that's a copy of this creature that's tapped and attacking that player", '')),
                        oracle_texts_filtered))
            oracle_texts_low = list(map(str.lower, oracle_texts_filtered))
            for regexp in COPY_CARDS_REGEX:
                if (list(search_strings(regexp, oracle_texts_low))
                        and not list(search_strings(COPY_CARDS_EXCLUDE_REGEX,
                                                    oracle_texts_low))):
                    cards_copy.append(card)
                    break

    cards_copy_cmc_3 = list(filter(lambda c: c['cmc'] <= 3, cards_copy))

    cards_copy_cmc_3_target_creature = list(filter(
        lambda c: bool(list(in_strings('creature', list(map(str.lower, get_oracle_texts(c)))))),
        cards_copy_cmc_3))
    cards_copy_cmc_3_target_creature_graveyard = list(filter(
        lambda c: bool(list(in_strings('graveyard', list(map(str.lower, get_oracle_texts(c)))))),
        cards_copy_cmc_3_target_creature))
    cards_copy_cmc_3_target_creature_hand = list(filter(
        lambda c: bool(list(in_strings('hand', list(map(str.lower, get_oracle_texts(c)))))),
        [c for c in cards_copy_cmc_3_target_creature
         if c not in cards_copy_cmc_3_target_creature_graveyard]))
    cards_copy_cmc_3_target_creature_battlefield = [
        c for c in cards_copy_cmc_3_target_creature
        if c not in cards_copy_cmc_3_target_creature_graveyard
        and c not in cards_copy_cmc_3_target_creature_hand]

    cards_copy_cmc_3_target_artifact = list(filter(
        lambda c: bool(list(in_strings('artifact', list(map(str.lower, get_oracle_texts(c)))))),
        [c for c in cards_copy_cmc_3 if c not in cards_copy_cmc_3_target_creature]))

    cards_copy_cmc_3_target_instant_or_sorcery = list(filter(
        lambda c: bool(list(search_strings('instant|sorcery', list(map(str.lower, get_oracle_texts(c)))))),
        [c for c in cards_copy_cmc_3 if c not in cards_copy_cmc_3_target_creature
         and c not in cards_copy_cmc_3_target_artifact]))

    copy_stats_data = {
        'Copy cards': len(cards_copy),
        'Copy cards (CMC <= 3)': len(cards_copy_cmc_3),
        'Copy cards (CMC <= 3, creatures)': len(cards_copy_cmc_3_target_creature),
        'Copy cards (CMC <= 3, creatures, from battlefield)': len(cards_copy_cmc_3_target_creature_battlefield),
        'Copy cards (CMC <= 3, creatures, from graveyard)': len(cards_copy_cmc_3_target_creature_graveyard),
        'Copy cards (CMC <= 3, creatures, from hand)': len(cards_copy_cmc_3_target_creature_hand),
        'Copy cards (CMC <= 3, artifacts)': len(cards_copy_cmc_3_target_artifact),
        'Copy cards (CMC <= 3, instants or sorcery)': len(cards_copy_cmc_3_target_instant_or_sorcery),
        }

    copy_output_data = {
        'Copy cards (CMC <= 3) by target': {
            'Copy cards (CMC <= 3, creatures, from battlefield)':
                cards_copy_cmc_3_target_creature_battlefield,
            'Copy cards (CMC <= 3, creatures, from graveyard)':
                cards_copy_cmc_3_target_creature_graveyard,
            'Copy cards (CMC <= 3, creatures, from hand)':
                cards_copy_cmc_3_target_creature_hand,
            'Copy cards (CMC <= 3, artifacts)':
                cards_copy_cmc_3_target_artifact,
            'Copy cards (CMC <= 3, instants or sorcery)':
                cards_copy_cmc_3_target_instant_or_sorcery}}

    cards_copy_cards_selected = []
    for data in copy_output_data.values():
        for cards_list in data.values():
            cards_copy_cards_selected += sort_cards_by_cmc_and_name(cards_list)[:max_list_items]

    if outformat == 'html':
        html = ''
        html += '  <section>'+'\n'
        html += '    <h3 id="copy-cards">Copy cards</h3>\n'
        html += '    <h4>Stats</h4>'+'\n'
        html += '    <dl>'+'\n'
        for title, count in copy_stats_data.items():
            html += '      <dt>'+title+'</dt>'+'\n'
            html += '      <dd>'+str(count)+'</dd>'+'\n'
        html += '    </dl>'+'\n'
        for section, data in copy_output_data.items():
            html += '    <h4>'+section+'</h4>'+'\n'
            for title, cards_list in data.items():
                title += ': '+str(len(cards_list))
                html += '    <article>'+'\n'
                html += '      <details>'+'\n'
                html += '        <summary>'+title+'</summary>'+'\n'
                html += print_cards_list(sort_cards_by_cmc_and_name(cards_list),
                                         limit = max_list_items, outformat = outformat, return_str = True)
                html += '      </details>'+'\n'
                html += '    </article>'+'\n'
        html += '  </section>'+'\n'
        print(html)

    if outformat == 'console':
        for title, count in copy_stats_data.items():
            print(title+':', count)
        print('')
        for section, data in copy_output_data.items():
            print(section)
            for title, cards_list in data.items():
                print('   '+title+':', len(cards_list))
                print_cards_list(sort_cards_by_cmc_and_name(cards_list), limit = max_list_items,
                                 indent = 8, outformat = outformat)
        print('')

    return cards_copy

def print_combo_card_names(combo):
    """Print card's names of a combo"""

    card_names = []
    for num in range(1, 11):
        if combo['Card '+str(num)]:
            card_names.append(combo['Card '+str(num)])
    print(' + '.join(card_names))

def print_tup_combo(tup_combo, cards, indent = 0, print_header = False, max_cards = 4,
                    max_name_len = 30, separator_color = 'light_grey', separator_attrs = None,
                    outformat = 'console', return_str = False):
    """Print a combo from a tuple (cards_names, combo_infos)"""

    ret = ''

    if outformat == 'html':
        html = ''
        if print_header:
            html += '        <tr class="header">'+'\n'
            html += '          <th class="cmc-total">CMC total</th>'+'\n'
            html += '          <th class="cmc-max">CMC max</th>'+'\n'
            html += '          <th class="cmc-min">CMC min</th>'+'\n'
            for index in range(1, max_cards + 1):
                html += '          <th class="combo-card">Card '+str(index)+'</th>'+'\n'
            html += '        </tr>'+'\n'

        html += '        <tr class="combo-line">'+'\n'
        html += '          <td class="cmc-total">'+str(int(tup_combo[1]['cmc_total']))+'</td>'+'\n'
        html += '          <td class="cmc-max">'+str(int(tup_combo[1]['cmc_max']))+'</td>'+'\n'
        html += '          <td class="cmc-min">'+str(int(tup_combo[1]['cmc_min']))+'</td>'+'\n'
        for index, name in enumerate(tup_combo[0]):
            name_and_link = ''
            card = get_card(name, cards, strict = True)
            imgurl = ''
            if 'image_uris' in card and 'normal' in card['image_uris']:
                imgurl = card['image_uris']['normal']
            elif ('card_faces' in card and card['card_faces'] and 'image_uris' in card['card_faces'][0]
                and 'normal' in card['card_faces'][0]['image_uris']):
                imgurl = card['card_faces'][0]['image_uris']['normal']
            img_element = '<img src="'+imgurl+'" alt="image of card '+name+'" />'
            if not imgurl:
                img_element = '<span class="card-not-found">/<span>'
            name_and_link = ('<a class="'+get_card_colored(card)+'" href="#">'
                                +'<span class="name">'+name+'</span>'
                                +'<span class="image">'+img_element+'</span>'
                             +'</a>')
            html += '          <td class="combo-card">'+name_and_link+'</td>'+'\n'
        if len(tup_combo[0]) < max_cards:
            for index in range(len(tup_combo[0]), max_cards):
                html += '          <td class="combo-card"></td>'+'\n'
        html += '        </tr>'+'\n'

        ret = html

    if outformat == 'console':
        separator_attrs = separator_attrs if separator_attrs is not None else ['dark']
        separator = ' | '
        separator_colored = colored(separator, separator_color, attrs=separator_attrs)
        plus = ' + '
        plus_colored = colored(plus, separator_color, attrs=separator_attrs)

        c_format = '{indent:>'+str(indent)+'}{cmc_total:>9}{sep}{cmc_max:>7}{sep}{cmc_min:>7}{sep}'
        c_format += '{plus}'.join(list(map(lambda i: '{name_'+str(i)+'}', range(1, max_cards + 1))))
        if print_header:
            c_params = {
                'indent': '',
                'sep': separator,
                'plus': plus,
                'cmc_total': 'CMC total',
                'cmc_max': 'CMC max',
                'cmc_min': 'CMC min'}
            for index in range(1, max_cards + 1):
                c_params['name_'+str(index)] = ('{:^'+str(max_name_len)+'}').format('card '+str(index))
            c_header = colored(c_format.format(**c_params), separator_color, attrs=separator_attrs)
            ret = c_header
        c_params = {
            'indent': '',
            'sep': separator_colored,
            'plus': plus_colored,
            'cmc_total': int(tup_combo[1]['cmc_total']),
            'cmc_max': int(tup_combo[1]['cmc_max']),
            'cmc_min': int(tup_combo[1]['cmc_min'])}
        for index, name in enumerate(tup_combo[0]):
            card = get_card(name, cards, strict = True)
            c_params['name_'+str(index + 1)] = colored(
                    ('{:^'+str(max_name_len)+'}').format(truncate_text(name, max_name_len)),
                    get_card_colored(card))
        if len(tup_combo[0]) < max_cards:
            # print('Warning', 'too few cards combo:', tup_combo[0], file=sys.stderr)
            for index in range(len(tup_combo[0]), max_cards):
                c_params['name_'+str(index + 1)] = ''
        c_line = c_format.format(**c_params)
        ret += c_line

    if not return_str:
        print(ret)

    return ret

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
               max_cards = None, min_cards = 2, excludes = None):
    """Return a dict containing:
         -   key: a tuple of cards comboting together
         - value: a dict with keys: 'infos' the combo infos, 'cards' the combo's cards

       Parameters:
           name             string   a card name to match combo against
           only_ok          boolean  if 'True' ensure all combo's card belong to the given list
           cards            list     the list of cards to search in
           combo_res_regex  string   if not None add combo only if its effect matches this regex
           max_cards        int      only consider combos with at most this number of cards
           min_cards        int      only consider combos with at least this number of cards
           excludes         list     a list of tuple of card names to exclude
    """
    card_combos = {}
    for combo in combos:
        card_names = tuple(sorted(combo['c'])) if 'c' in combo and combo['c'] else tuple()
        if not card_names or (excludes and card_names in excludes):
            continue
        add_combo = not name or any(filter(lambda names: name in names, card_names))
        if add_combo:
            if ((max_cards and len(card_names) > max_cards)
                    or (min_cards and len(card_names) < min_cards)):
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
                                       'cards': sort_cards_by_cmc_and_name(combo_cards)}
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

def assist_k_core_combos(combos, cards, regex, num_cards, excludes, max_cards = 20,
                         outformat = 'console'):
    """Print k_core combos that have exaclty 'num_cards' cards and matching regex"""
    print('DEBUG Searching for all', num_cards, 'cards combos with', regex, "...",
          'Please wait up to '+str(num_cards - 1)+' minute(s) ...', flush=True, file=sys.stderr)
    new_combos = get_combos(combos, cards, max_cards = num_cards, min_cards = num_cards,
                            combo_res_regex = regex, excludes = excludes)

    # TODO use a graph of combos:
    #       - with weighted edges for percentage of shared cards
    #       - or multiple graph one for combos that share 1 card, then for 2 cards, etc.
    new_combos_relations = {}
    for combo_cards in new_combos:
        for name in combo_cards:
            for other_name in combo_cards:
                if other_name != name:
                    if name not in new_combos_relations:
                        new_combos_relations[name] = []
                    if other_name not in new_combos_relations[name]:
                        new_combos_relations[name].append(other_name)

    nx_graph = get_nx_graph(new_combos_relations)
    print('DEBUG NX Graph:', 'nodes:', nx_graph.number_of_nodes(), ',',
            'edges:', nx_graph.number_of_edges(), file=sys.stderr)
    (k_nodes, k_num, k_len) = k_core_cards(nx_graph)

    if not k_nodes:
        print('Warning: impossible to find a k-core for all', num_cards, 'cards combos with', regex,
              file=sys.stderr)
        return

    if k_len > max_cards:
        print('DEBUG Too much cards ('+str(k_len)+') in the '+str(k_num)+'-core, skipping it',
              file=sys.stderr)
        return

    k_cards = tuple(sorted(list(map(lambda n: nx_graph.nodes[n]['card'], k_nodes))))

    k_combos = {}
    for card_names, combo_infos in new_combos.items():
        add_combo = True
        for name in card_names:
            if name not in k_cards:
                add_combo = False
                break
        if add_combo and card_names not in k_combos:
            k_combos[card_names] = combo_infos

    k_combos_order_cmc_max = list(sorted(k_combos.items(), key=lambda t: t[1]['cmc_max']))

    if outformat == 'html':
        html = ''
        html += '    <article>'+'\n'
        html += '      <details>'+'\n'
        html += '        <summary>'
        html += ('All '+str(num_cards)+' cards combos with '+regex+' '+str(k_num)+'-core cards: '
                 +str(k_len)+' cards')
        html += '</summary>'+'\n'
        html += '        <table class="cards-list">'+'\n'
        for node in k_nodes:
            card_name = nx_graph.nodes[node]['card']
            html += print_card(get_card(card_name, cards), outformat = outformat,
                               return_str = True)
        html += '        </table>'+'\n'
        html += '      </details>'+'\n'
        html += '      <details>'+'\n'
        html += '        <summary>'
        html += ('All '+str(num_cards)+' cards combos with '+regex+' '+str(k_num)+'-core combos: '
                 +str(len(k_combos))+' combos')
        html += '</summary>'+'\n'
        html += '        <table class="combos-list">'+'\n'
        for index, tup_combo in enumerate(k_combos_order_cmc_max):
            html += print_tup_combo(tup_combo, cards, max_cards = num_cards,
                                    print_header = index == 0, outformat = outformat, return_str = True)
        html += '        </table>'+'\n'
        html += '      </details>'+'\n'
        html += '    </article>'
        print(html)

    if outformat == 'console':
        print('All', num_cards, 'cards combos with', regex, str(k_num)+'-core cards:', k_len,
                'cards')
        print('')
        for node in k_nodes:
            card_name = nx_graph.nodes[node]['card']
            print_card(get_card(card_name, cards))
        print('')

        print('All', num_cards, 'cards combos with', regex, str(k_num)+'-core combos:',
                len(k_combos), 'combos')
        print('')
        for index, tup_combo in enumerate(k_combos_order_cmc_max):
            print_tup_combo(tup_combo, cards, indent = 3, max_cards = num_cards,
                            print_header = index == 0, outformat = outformat)
        print('')

def combo_effect_normalize(text):
    """Return a combo effect text normalized"""
    return (text.strip().lower().replace('near-infinite', 'infinite')
                                .replace('card draw', 'draw').replace('draws', 'draw'))

def print_cards_list(cards, limit = None, indent = 0, outformat = 'console', return_str = False,
                     **kwargs):
    """Loop over a cards list and print each cards, limit the list to 'limit' items"""
    ret = ''
    if cards:

        if outformat == 'html':
            ret = '      <table class="cards-list">'+'\n'

        item_count = 0
        has_reach_limit = False
        for card in cards:
            item_count += 1
            if limit and item_count > limit:
                has_reach_limit = True
                break
            ret += print_card(card, indent = indent, outformat = outformat, return_str = True,
                              **kwargs)
            if outformat == 'console':
                ret += '\n'

        if outformat == 'html':
            ret += '      </table>'+'\n'

        if has_reach_limit:
            if outformat == 'html':
                ret += '      <p class="truncated-symbol">...</p>'+'\n'

            if outformat == 'console':
                ret += ('{:>'+str(indent)+'}...').format('')

    if not return_str:
        print(ret)

    return ret

def display_html_header(title = 'MTG Deck Builder Assistant | made by Michael Bideau'):
    """Print an HTML header with title specified, and CSS and JS"""
    html = ''
    html += '<!DOCTYPE html>'+'\n'
    html += '<html lang="en">'+'\n'
    html += '<head>'+'\n'
    html += '  <meta charset="utf-8" />'+'\n'
    html += '  <title>'+title+'</title>'+'\n'
    html += '  <style>'+'\n'
    html += '    body { margin: 0px; padding: 0 10px 0; color: #444; background: white; }'+'\n'
    html += '    .main-head { grid-area: header; background: white; box-shadow: 0 30px 40px rgb(255, 255, 255); }'+'\n'
    html += '    .main-nav { grid-area: nav; background: white; }'+'\n'
    html += '    .side-nav { display: none; }'+'\n'
    html += '    .content-nav { display: none; }'+'\n'
    html += '    .content { grid-area: content; }'+'\n'
    html += '    .side { grid-area: sidebar; background: white; }'+'\n'
    html += '    .main-footer { grid-area: footer; background: white; }'+'\n'
    html += '    .commander-card { display: flex; flex-direction: column; }'+'\n'
    html += '    .wrapper {'+'\n'
    html += '      display: grid;'+'\n'
    html += '      grid-gap: 20px;'+'\n'
    html += '      grid-template-areas:'+'\n'
    html += '        "header"'+'\n'
    html += '        "nav"'+'\n'
    html += '        "sidebar"'+'\n'
    html += '        "content"'+'\n'
    html += '        "footer";'+'\n'
    html += '    }'+'\n'
    html += '    @media (min-width: 500px) {'+'\n'
    html += '      .main-nav { display: none; }'+'\n'
    html += '      .side-nav { display: block; }'+'\n'
    html += '      .wrapper {'+'\n'
    html += '        grid-template-columns: 1fr 3fr;'+'\n'
    html += '        grid-template-areas:'+'\n'
    html += '          "header  header"'+'\n'
    html += '          "content sidebar"'+'\n'
    html += '          "footer  footer";'+'\n'
    html += '      }'+'\n'
    html += '    }'+'\n'
    html += '    @media (min-width: 1130px) {'+'\n'
    html += '      .main-nav { display: block; }'+'\n'
    html += '      .side-nav { display: none; }'+'\n'
    html += '      .wrapper {'+'\n'
    html += '        grid-template-columns: 1fr 4fr 1fr;'+'\n'
    html += '        grid-template-areas:'+'\n'
    html += '          "header header  header"'+'\n'
    html += '          "nav    content sidebar"'+'\n'
    html += '          "nav    content sidebar"'+'\n'
    html += '          "nav    footer  sidebar";'+'\n'
    html += '      }'+'\n'
    html += '    .commander-card { display: grid; gap: 20px; }'+'\n'
    html += '    }'+'\n'
    html += ''+'\n'
    html += '    .main-head, .main-nav, .side { position: sticky; box-sizing: border-box; }'+'\n'
    html += '    .main-head { top: 0; }'+'\n'
    html += '    .main-nav, .side { top: 150px; height: 100vh; }'+'\n'
    html += ''+'\n'
    html += '    header h1 { margin-bottom: 0; }'+'\n'
    html += '    header .subtitle { margin-top: 5px; color: gray; font-size: 0.7em; }'+'\n'
    html += '    header .subtitle a { color: inherit; }'+'\n'
    html += '    .commander-card .image { grid-column-start: 1; grid-column-end: 1; }'+'\n'
    html += '    .commander-card .attributes { grid-column-start: 2; grid-column-end: 3; }'+'\n'
    html += '    .commander-card .image > img {  max-height: 400px; width: auto; border-radius: 20px; }'+'\n'
    html += '    dl {'+'\n'
    html += '      display: grid;'+'\n'
    html += '      grid-template-columns: max-content auto;'+'\n'
    html += '    }'+'\n'
    html += '    dt {'+'\n'
    html += '      grid-column-start: 1;'+'\n'
    html += '      font-size: 0.9em;'+'\n'
    html += '      vertical-align: middle;'+'\n'
    html += '      color: gray;'+'\n'
    html += '    }'+'\n'
    html += '    dd {'+'\n'
    html += '      grid-column-start: 2;'+'\n'
    html += '    }'+'\n'
    html += '    summary::-webkit-details-marker {'+'\n'
    html += '      color: #00ACF3;'+'\n'
    html += '      font-size: 125%;'+'\n'
    html += '      margin-right: 2px;'+'\n'
    html += '    }'+'\n'
    html += '    summary:focus {'+'\n'
    html += '      outline-style: none;'+'\n'
    html += '    }'+'\n'
    html += '    details > * { margin-left: 20px; }'+'\n'
    html += '    details summary {'+'\n'
    html += '      margin: 16px 0 10px;'+'\n'
    html += '      font-size: 1em;'+'\n'
    html += '      font-weight: normal;'+'\n'
    html += '      background-color: #eee;'+'\n'
    html += '      padding: 10px;'+'\n'
    html += '      border-radius: 10px;'+'\n'
    html += '      cursor: pointer;'+'\n'
    html += '    }'+'\n'
    html += '    details details summary {'+'\n'
    html += '      font-size: 1.2em;'+'\n'
    html += '    }'+'\n'
    html += '    .toc { color: grey; }'+'\n'
    html += '    .toc > ol > li > a { color: inherit; }'+'\n'
    html += '    .combos-list th, .combos-list td { padding: 0 10px; text-align: center; }'+'\n'
    html += '    .combos-list th { color: gray; }'+'\n'
    html += '    .cards-list td { padding: 0 10px; text-align: right; }'+'\n'
    html += '    .cards-list td.name { text-align: center; }'+'\n'
    html += '    .cards-list td.name span.name { white-space: nowrap; }'+'\n'
    html += '    .cards-list td.edhrank:after { content: " #"; }'+'\n'
    html += '    .cards-list td.price:after { content: " $"; }'+'\n'
    html += '    .cards-list td.edhrank, .cards-list td.price, .cards-list td.mana, '+'\n'
    html += '      .cards-list td.type, .cards-list td.power-toughness { white-space: nowrap; }'+'\n'
    html += '    .cards-list td.text { text-align: left; font-size: 0.9em; padding-bottom: 7px; }'+'\n'
    html += '    .card-line .name a, .combo-card a { position:relative; text-decoration: dotted; }'+'\n'
    html += '    .card-line .name a span.image, .combo-card a span.image { position:absolute; display:none; z-index:99; }'+'\n'
    html += '    .card-line .name a:hover span.image, .combo-card a:hover span.image { display:block; left: 100%; bottom: 100%; }'+'\n'
    html += '    .card-line .name a:hover span.image > img, .combo-card a:hover span.image > img { max-height: 400px; width: auto; border-radius: 20px; }'+'\n'
    # leeched from Scryfall CSS: begin
    html += '    .card-not-found {'+'\n'
    html += '      display: block;'+'\n'
    html += '      pointer-events: none;'+'\n'
    html += '      position: absolute;'+'\n'
    html += '      z-index: 9000000;'+'\n'
    html += '      background-image: -webkit-repeating-linear-gradient(145deg, #DDD, #DDD 5px, #CCC 5px, #CCC 10px);'+'\n'
    html += '      background-image: -o-repeating-linear-gradient(145deg, #DDD, #DDD 5px, #CCC 5px, #CCC 10px);'+'\n'
    html += '      background-image: repeating-linear-gradient(-55deg, #DDD, #DDD 5px, #CCC 5px, #CCC 10px);'+'\n'
    html += '      -webkit-border-radius: 4.75% / 3.5%;'+'\n'
    html += '      border-radius: 4.75% / 3.5%;'+'\n'
    html += '      height: 340px !important;'+'\n'
    html += '      width: 244px !important;'+'\n'
    html += '      -webkit-box-orient: horizontal;'+'\n'
    html += '      -webkit-box-direction: normal;'+'\n'
    html += '      -webkit-flex-flow: row nowrap;'+'\n'
    html += '      -ms-flex-flow: row nowrap;'+'\n'
    html += '      flex-flow: row nowrap'+'\n'
    html += '    }'+'\n'
    # leeched from Scryfall CSS: end
    html += '    button.action {'+'\n'
    html += '      margin-top: 15px;'+'\n'
    html += '      font-size: 1.2em;'+'\n'
    html += '      padding: 10px 20px;'+'\n'
    html += '      background-color: lightgray;'+'\n'
    html += '      border-radius: 7px;'+'\n'
    html += '      width: 95%;'+'\n'
    html += '    }'+'\n'
    html += '    button.show { background-color: lightgreen; }'+'\n'
    html += '    button.download { background-color: lightblue; }'+'\n'
    html += '    #deck-list { margin-left: 10px; }'+'\n'
    html += '    .red, a.red { color: red; }'+'\n'
    html += '    .blue, a.blue { color: blue; }'+'\n'
    html += '    .gray, a.gray { color: gray; }'+'\n'
    html += '    .yellow, a.yellow { color: burlywood; }'+'\n'
    html += '    .light_green, a.light_green { color: green; }'+'\n'
    html += '    .white, a.white { color: darkgrey; }'+'\n'
    html += '    .magenta, a.magenta { color: magenta; }'+'\n'
    html += '    .cyan, a.cyan { color: cyan; }'+'\n'
    html += '    .light_grey, a.light_grey { color: silver; }'+'\n'
    html += '    .light_yellow, a.light_yellow { color: darkkhaki; }'+'\n'
    html += '    .light_blue, a.light_blue { color: lightblue; }'+'\n'
    html += '    .dark_grey, a.dark_grey { color: dimgray; }'+'\n'
    # dark theme
    html += '    @media (prefers-color-scheme: dark) {'+'\n'
    html += '      body { color: #ddd; background: black; }'+'\n'
    html += '      .main-head { background: black; box-shadow: 0 30px 40px rgb(0, 0, 0); }'+'\n'
    html += '      .main-nav { background: black; }'+'\n'
    html += '      .side { background: black; }'+'\n'
    html += '      .main-footer { background: black; }'+'\n'
    html += '      header .subtitle { color: #bbb; }'+'\n'
    html += '      dt { color: #aaa; }'+'\n'
    html += '      summary::-webkit-details-marker { color: #00ACF3; }'+'\n'
    html += '      details summary { background-color: #444; }'+'\n'
    html += '      .toc { color: #bbb; }'+'\n'
    html += '      .combos-list th { color: gray; }'+'\n'
    html += '      .red, a.red { color: red; }'+'\n'
    html += '      .blue, a.blue { color: blue; }'+'\n'
    html += '      .gray, a.gray { color: gray; }'+'\n'
    html += '      .yellow, a.yellow { color: burlywood; }'+'\n'
    html += '      .light_green, a.light_green { color: lightgreen; }'+'\n'
    html += '      .white, a.white { color: white; }'+'\n'
    html += '      .magenta, a.magenta { color: magenta; }'+'\n'
    html += '      .cyan, a.cyan { color: cyan; }'+'\n'
    html += '      .light_grey, a.light_grey { color: #999; }'+'\n'
    html += '      .light_yellow, a.light_yellow { color: darkkhaki; }'+'\n'
    html += '      .light_blue, a.light_blue { color: lightblue; }'+'\n'
    html += '      .dark_grey, a.dark_grey { color: dimgray; }'+'\n'
    html += '      button.show { background-color: #31f231; }'+'\n'
    html += '      button.download { background-color: #51d1fb; }'+'\n'
    html += '    }'+'\n'
    html += '  </style>'+'\n'
    html += '  <script>'+'\n'
    html += '    var deck_list = [];'+'\n'
    html += '    function update_deck_list(checkboxElement, cardType) {'+'\n'
    html += '      let card_name = checkboxElement.value;'+'\n'
    html += '      let in_deck_list = deck_list.indexOf(card_name);'+'\n'
    html += '      var elementCount = document.getElementById(cardType+"-count");'+'\n'
    html += '      if(checkboxElement.checked && in_deck_list < 0) {'+'\n'
    html += '        deck_list.push(card_name);'+'\n'
    html += '        elementCount.innerHTML = Number(elementCount.innerHTML) + 1;'+'\n'
    html += '      }'+'\n'
    html += '      else if(! checkboxElement.checked && in_deck_list > -1) {'+'\n'
    html += '        deck_list.splice(in_deck_list, 1);'+'\n'
    html += '        elementCount.innerHTML = Number(elementCount.innerHTML) - 1;'+'\n'
    html += '      };'+'\n'
    html += '      var deck_size_elt = document.getElementById("deck-size");'+'\n'
    html += '      deck_size_elt.innerHTML = " ("+deck_list.length+" cards)";'+'\n'
    html += '    }'+'\n'
    html += '    function get_commander_name(clean = false) {'+'\n'
    html += '      var nameElt = document.getElementById("commander-name");'+'\n'
    html += '      if (clean) { return nameElt.innerHTML.replace(/\\W/g, ""); }'+'\n'
    html += '      return nameElt.innerHTML;'+'\n'
    html += '    }'+'\n'
    html += '    function generate_deck_list() {'+'\n'
    html += '      var dek_list = "";'+'\n'
    html += '      if (deck_list.length > 0) {'+'\n'
    html += '        dek_list = "1 "+deck_list.join("\\n1 ")+"\\n\\n";'+'\n'
    html += '      }'+'\n'
    html += '      dek_list += "1 "+get_commander_name();'+'\n'
    html += '      return dek_list;'+'\n'
    html += '    }'+'\n'
    html += '    function show_deck_list() {'+'\n'
    html += '      var div = document.getElementById("deck-list");'+'\n'
    html += '      div.innerHTML = "<p>"+generate_deck_list().replaceAll("\\n", "<br/>")+"</p>";\n'
    html += '    }'+'\n'
    html += '    function download_deck_list() {'+'\n'
    html += '      var mime_type = "text/plain";'+'\n'
    html += '      var blob = new Blob([generate_deck_list()], {type: mime_type});'+'\n'
    html += '      var dlink = document.createElement("a");'+'\n'
    html += '      dlink.download = get_commander_name(true)+".dek";'+'\n'
    html += '      dlink.href = window.URL.createObjectURL(blob);'+'\n'
    html += '      dlink.onclick = function(e) {'+'\n'
    html += '        // revokeObjectURL needs a delay to work properly'+'\n'
    html += '        var that = this;'+'\n'
    html += '        setTimeout(function() {'+'\n'
    html += '          window.URL.revokeObjectURL(that.href);'+'\n'
    html += '        }, 1500);'+'\n'
    html += '      };'+'\n'
    html += '      dlink.click();'+'\n'
    html += '      dlink.remove();'+'\n'
    html += '    }'+'\n'
    html += '    function loadimg(element) {'+'\n'
    html += '      imgelt = element.querySelector("img[src='+"'#'"+']");'+'\n'
    html += '      if (imgelt && "imgurl" in imgelt.dataset) {'+'\n'
    html += '        imgelt.setAttribute("src", imgelt.dataset.imgurl);'+'\n'
    html += '      }'+'\n'
    html += '    }'+'\n'
    html += '  </script>'+'\n'
    html += '</head>'+'\n'
    html += '<body>'+'\n'
    html += '  <div class="wrapper">'+'\n'
    html += '    <header class="main-head">'+'\n'
    html += '      <h1>'+title+'</h1>'+'\n'
    html += '      <p class="subtitle">'
    html += 'Get the <a href="'+SOURCE_URL+'">source code on Github</a>'
    html += '</p>'+'\n'
    html += '    </header>'+'\n'
    html += get_html_toc(cssclass = 'main-nav')
    html += '    <aside class="side">'+'\n'
    html += get_html_toc(cssclass = 'side-nav')
    html += '      <h2>Deck<span id="deck-size"></span></h2>'+'\n'
    html += '      <dl>'+'\n'
    html += '        <dt>Lands</dt>'+'\n'
    html += '        <dd id="land-count">0</dd>'+'\n'
    html += '        <dt>Creatures</dt>'+'\n'
    html += '        <dd id="creature-count">0</dd>'+'\n'
    html += '        <dt>Planeswalkers</dt>'+'\n'
    html += '        <dd id="planeswalker-count">0</dd>'+'\n'
    html += '        <dt>Artifacts</dt>'+'\n'
    html += '        <dd id="artifact-count">0</dd>'+'\n'
    html += '        <dt>Enchantments</dt>'+'\n'
    html += '        <dd id="enchantment-count">0</dd>'+'\n'
    html += '        <dt>Instants</dt>'+'\n'
    html += '        <dd id="instant-count">0</dd>'+'\n'
    html += '        <dt>Sorceries</dt>'+'\n'
    html += '        <dd id="sorcery-count">0</dd>'+'\n'
    html += '        <dt>Stickers</dt>'+'\n'
    html += '        <dd id="stickers-count">0</dd>'+'\n'
    html += '        <dt>Unkown</dt>'+'\n'
    html += '        <dd id="unknown-count">0</dd>'+'\n'
    html += '      </dl>'+'\n'
    html += '      <button class="action show" onclick="show_deck_list()">'
    html += 'Show <small>/update</small> deck list</button>'+'\n'
    html += '      <button class="action download" onclick="download_deck_list()">'
    html += 'Download deck list</button>'+'\n'
    html += '      <div id="deck-list"></div>'+'\n'
    html += '    </aside>'+'\n'
    html += '    <div class="content">'+'\n'
    print(html)

def display_commander_card(card, commander_combos_regex, outformat = 'console', outdir = '/tmp'):
    """Display the commander card and extracted attributes/features"""

    commander_color_name = get_card_colored(card)

    # image
    get_commander_img = outformat == 'html' or (USE_SIXEL and sys.stdout.isatty())
    imgpath, imgwidth, imgheight = None, None, None
    if get_commander_img:
        imgpath, imgwidth, imgheight = get_card_image(card, imgformat = 'normal', outdir = outdir)

    # html
    if outformat == 'html':
        html = ''
        html += '  <h2 class="commander-title">Commander</h2>'+'\n'
        html += '  <div class="commander-card">'+'\n'
        html += '    <div class="image">'+'\n'
        html += '      <img src="'+imgpath+'" />'+'\n'
        html += '    </div>'+'\n'
        html += '    <div class="attributes">'+'\n'
        html += '      <dl>'+'\n'
        html += '        <dt>Name</dt>'+'\n'
        html += '        <dd id="commander-name" class="'+commander_color_name+'">'+card['name']+'</dd>'+'\n'
        html += '        <dt>Identity</dt>'+'\n'
        html += '        <dd>'+','.join(list(map(lambda t: colorize_mana(t, no_braces = True),
                                                    card['color_identity'])))+'</dd>'+'\n'
        html += '        <dt>Colors</dt>'+'\n'
        html += '        <dd>'+','.join(list(map(lambda t: colorize_mana(t, no_braces = True),
                                                    card['colors'])))+'</dd>'+'\n'
        html += '        <dt>Mana</dt>'+'\n'
        html += '        <dd>'+(colorize_mana(card['mana_cost'])
                                +'(CMC:'+str(card['cmc'])+')')+'</dd>'+'\n'
        html += '        <dt>Type</dt>'+'\n'
        html += '        <dd class="'+commander_color_name+'">'+card['type_line']+'</dd>'+'\n'
        html += '        <dt>Keywords</dt>'+'\n'
        html += '        <dd>'+','.join(card['keywords'])+'</dd>'+'\n'
        html += '        <dt>Text</dt>'+'\n'
        html += '        <dd>'+join_oracle_texts(card)+'</dd>'+'\n'
        html += '        <dt>Combo exp</dt>'+'\n'
        html += '        <dd>'+commander_combos_regex+'</dd>'+'\n'
        html += '      </dl>'+'\n'
        html += '    </div>'+'\n'
        html += '  </div>'+'\n'
        print(html)

    # console
    if outformat == 'console':
        print('')
        print('')
        print('### Commander card ###')
        print('')

        # display image (if terminal is sixel compatible, see https://www.arewesixelyet.com)
        if USE_SIXEL and sys.stdout.isatty():  # in a terminal
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
                for _ in range(1, 19):
                    print('\033[3A')  # move one line up
                # print('\033[')  # reset
                # img_writer.restore_position(sys.stdout)
                # for index in range(1, 4):  # move 3 lines down
                #     print('')
                print('')
            else:
                img_writer = converter.SixelConverter(imgpath, **extraopts)
                img_writer.write(sys.stdout)

        print('Commander:', colored(card['name'], commander_color_name))
        print(' Identity:', ','.join(list(map(lambda t: colorize_mana(t, no_braces = True),
                                              card['color_identity']))))
        print('   Colors:', ','.join(list(map(lambda t: colorize_mana(t, no_braces = True),
                                              card['colors']))))
        print('     Mana:', colorize_mana(card['mana_cost']), '(CMC:'+str(card['cmc'])+')')
        print('     Type:', colored(card['type_line'], commander_color_name))
        print(' Keywords:', card['keywords'])
        print('     Text:', card['oracle_text'])
        print('Combo exp:', commander_combos_regex)

def get_html_toc(cssclass = ''):
    """Return the HTML Table Of Content"""
    html = '  <nav class="toc'+((' '+cssclass) if cssclass else '')+'">'+'\n'
    html += '    <ol>'+'\n'
    html += '      <li><a href="#stats-all-cards">Stats all cards</a></li>'+'\n'
    html += '      <li><a href="#commander-card">Commander card</a></li>'+'\n'
    html += '      <li><a href="#commander-combos">Commander combos</a></li>'+'\n'
    html += '      <li><a href="#combos-k-core">Combos k-core</a></li>'+'\n'
    html += '      <li><a href="#with-commanders-keyword">'+"With commander's keyword</a></li>"+'\n'
    html += '      <li><a href="#lands">Lands</a></li>'+'\n'
    html += '      <li><a href="#land-fetchers">Land fetchers</a></li>'+'\n'
    html += '      <li><a href="#ramp-cards">Ramp cards</a></li>'+'\n'
    html += '      <li><a href="#draw-cards">Draw cards</a></li>'+'\n'
    html += '      <li><a href="#tutor-cards">Tutor cards</a></li>'+'\n'
    html += '      <li><a href="#removal-cards">Removal cards</a></li>'+'\n'
    html += '      <li><a href="#disabling-cards">Disabling cards</a></li>'+'\n'
    html += '      <li><a href="#wipe-cards">Board wipe cards</a></li>'+'\n'
    html += '      <li><a href="#graveyard-recursion-cards">Graveyard recursion cards</a></li>\n'
    html += '      <li><a href="#graveyard-hate-cards">Graveyard hate cards</a></li>'+'\n'
    html += '      <li><a href="#copy-cards">Copy cards</a></li>'+'\n'
    html += '      <li><a href="#best-cards">Best cards</a></li>'+'\n'
    html += '    </ol>'+'\n'
    html += '  </nav>'+'\n'
    return html

def display_deck_building_header(outformat = 'console'):
    """Display the deck building header"""

    # html
    if outformat == 'html':
        html = '  <h2>Deck building</h2>'+'\n'
        html += get_html_toc(cssclass = 'content-nav')
        print(html)

    # console
    if outformat == 'console':
        print('')
        print('')
        print('### Deck building ###')
        print('')

def assist_commander_combos(commander_combos_no_filter, commander_combos, commander_combos_regex,
                            combos, cards, outformat = 'console'):
    """Show commander's combos cards organised by rank, for the user to select some"""

    combos_rank_1 = {}
    combos_rank_2 = {}

    commander_combos_filtered = None

    c_combos_rank_1_x_cards = {}
    c_combos_rank_2_x_cards = {}

    if commander_combos:

        c_combos = commander_combos

        if commander_combos_regex:
            commander_combos_filtered = get_combos(combos, cards, name = COMMANDER_NAME,
                                                   combo_res_regex = commander_combos_regex)
            c_combos = commander_combos_filtered

        # rank 1
        combos_rank_1 = c_combos
        combos_rank_1_names = set([])
        for count in range(2, 5):
            key = '4+' if count == 4 else str(count)

            if key not in c_combos_rank_1_x_cards:
                c_combos_rank_1_x_cards[key] = {}

            c_combos_rank_1_x_cards[key]['combos'] = dict(sorted(
                {k: v for k, v in c_combos.items() if len(k) == count}.items(),
                key=lambda t: t[1]['cmc_total']))

            c_combos_rank_1_x_cards[key]["cards names"] = set(filter(
                lambda n: n != COMMANDER_NAME,
                [name for names in c_combos_rank_1_x_cards[key]['combos'].keys() for name in names]))

            combos_rank_1_names |= c_combos_rank_1_x_cards[key]['cards names']

        # rank 2
        c_combos_cards = []
        for card_names in c_combos:
            for card_name in card_names:
                if card_name not in c_combos_cards and card_name != COMMANDER_NAME:
                    c_combos_cards.append(card_name)
        c_combos_cards = tuple(sorted(c_combos_cards))
        combos_rank_2_excludes = list(map(lambda names: tuple(sorted(names)), c_combos.keys()))

        for card_name in c_combos_cards:
            print('DEBUG Searching for combos related to', card_name, '...', flush=True,
                file=sys.stderr)
            card_combos = get_combos(combos, cards, name = card_name,
                                     combo_res_regex = commander_combos_regex,
                                     excludes = combos_rank_2_excludes)
            if card_combos:
                for c_cards, c_info in card_combos.items():
                    if c_cards not in combos_rank_2:
                        combos_rank_2[c_cards] = c_info

        for count in range(2, 5):
            key = '4+' if count == 4 else str(count)

            if key not in c_combos_rank_2_x_cards:
                c_combos_rank_2_x_cards[key] = {}

            c_combos_rank_2_x_cards[key]['combos'] = dict(sorted(
                {k: v for k, v in combos_rank_2.items() if len(k) == count}.items(),
                key=lambda t: t[1]['cmc_total']))

            c_combos_rank_2_x_cards[key]['cards names'] = set(filter(
                lambda n: n != COMMANDER_NAME and n not in combos_rank_1_names,
                [name for names in c_combos_rank_2_x_cards[key]['combos'].keys() for name in names]))

    # HTML
    if outformat == 'html':
        html = '  <section>'
        html += '    <h3 id="commander-combos">Commander combos</h3>'+'\n'
        html += '    <dl>'+'\n'
        html += '      <dt>Commander combos (total)</dt>'+'\n'
        html += '      <dd>'+str(len(commander_combos_no_filter))+'</dd>'+'\n'
        if commander_combos:
            html += '      <dt>Commander combos (valid rules 0)</dt>'+'\n'
            html += '      <dd>'+str(len(commander_combos))+'</dd>'+'\n'

            if commander_combos_filtered:
                html += '      <dt>Commander combos '+commander_combos_regex+'</dt>'+'\n'
                html += '      <dd>'+str(len(commander_combos_filtered))+'</dd>'+'\n'

        html += '    </dl>'+'\n'

        if c_combos_rank_1_x_cards:
            html += '    <h4 id="commander-combos-rank-1">'
            html += 'Combos rank 1 <small>(directly tied to the commander)</small></h4>'+'\n'

            for count in range(2, 5):
                key = '4+' if count == 4 else str(count)

                html += '    <details>'+'\n'
                html += '      <summary>'
                html += ('Rank 1 combos with '+key+' cards: '
                         +str(len(c_combos_rank_1_x_cards[key]['combos']))+' combos,'
                         +'+'+str(len(c_combos_rank_1_x_cards[key]['cards names']))+' cards')
                html += '</summary>'+'\n'
                html += '      <h5>Combos</h5>'+'\n'
                html += '      <table class="combos-list">'+'\n'
                for index, tup_combo in enumerate(c_combos_rank_1_x_cards[key]['combos'].items()):
                    html += print_tup_combo(tup_combo, cards, max_cards = count,
                                            print_header = index == 0, outformat = outformat, return_str = True)
                html += '      </table>'+'\n'
                html += '      <h5>Cards</h5>'+'\n'
                html += '      <table class="cards-list">'+'\n'
                for name in c_combos_rank_1_x_cards[key]['cards names']:
                    html += print_card(get_card(name, cards), outformat = outformat, return_str = True)
                html += '      </table>'+'\n'
                html += '    </details>'+'\n'

        if c_combos_rank_2_x_cards:
            html += '    <h4 id="commander-combos-rank-2">'
            html += 'Combos rank 2 <small>(indirectly tied to the commander)</small></h4>\n'

            for count in range(2, 5):
                key = '4+' if count == 4 else str(count)

                html += '    <details>'+'\n'
                html += '      <summary>'
                html += ('Rank 2 combos with '+key+' cards: '
                         +str(len(c_combos_rank_2_x_cards[key]['combos']))+' combos,'
                         +'+'+str(len(c_combos_rank_2_x_cards[key]['cards names']))+' cards')
                html += '</summary>'+'\n'
                html += '      <h5>Combos</h5>'+'\n'
                html += '      <table class="combos-list">'+'\n'
                for index, tup_combo in enumerate(c_combos_rank_2_x_cards[key]['combos'].items()):
                    html += print_tup_combo(tup_combo, cards, max_cards = count,
                                            print_header = index == 0, outformat = outformat, return_str = True)
                html += '      </table>'+'\n'
                html += '      <h5>Cards</h5>'+'\n'
                html += '      <table class="cards-list">'+'\n'
                for name in c_combos_rank_2_x_cards[key]['cards names']:
                    html += print_card(get_card(name, cards), outformat = outformat, return_str = True)
                html += '      </table>'+'\n'
                html += '    </details>'+'\n'

        html += '  </section>'+'\n'

        print(html)

    # console
    if outformat == 'console':
        print('Commander combos:', len(commander_combos_no_filter))
        print('')
        if commander_combos:
            print('Commander combos (valid rules 0):', len(commander_combos))

            if commander_combos_filtered:
                print('Commander combos filtered '+commander_combos_regex+':',
                    len(commander_combos_filtered))
                print('')

            for count in range(2, 5):
                key = '4+' if count == 4 else str(count)

                if c_combos_rank_1_x_cards[key]['combos']:
                    print('    '+key+' cards:', len(c_combos_rank_1_x_cards[key]['combos']),
                          'combos,', '+'+str(len(c_combos_rank_1_x_cards[key]['cards names'])),
                          'cards')
                    print('')
                    for index, tup_combo in enumerate(
                            c_combos_rank_1_x_cards[key]['combos'].items()):
                        print_tup_combo(tup_combo, cards, indent = 8, max_cards = count,
                                        print_header = index == 0)
                    print('')
            print('')

            if combos_rank_2:
                print('Commander combos rank 2:', len(combos_rank_2))
                print('')

                for count in range(2, 5):
                    key = '4+' if count == 4 else str(count)

                    if c_combos_rank_2_x_cards[key]['combos']:
                        print('    '+key+' cards:', len(c_combos_rank_2_x_cards[key]['combos']),
                              'combos,', '+'+str(len(c_combos_rank_2_x_cards[key]['cards names'])),
                              'cards')
                        print('')
                        if count < 4:
                            for index, tup_combo in enumerate(
                                    c_combos_rank_2_x_cards[key]['combos'].items()):
                                print_tup_combo(tup_combo, cards, indent = 8, max_cards = count,
                                                print_header = index == 0)
                            print('')

    return combos_rank_1, combos_rank_2

def assist_commander_keywords_common(commander_card, cards, limit = None, outformat = 'console'):
    """Show cards with at least one commander's keywords, for the user to select some"""

    commander_keywords = set(commander_card['keywords'])
    cards_common_keyword = sort_cards_by_cmc_and_name(list(
        filter(lambda c: bool(commander_keywords & set(c['keywords'])), cards)))

    if COMMANDER_FEATURES_REGEXES:
        commander_common_feature = []
        for card in cards:
            oracle_texts = get_oracle_texts(card)
            oracle_texts_low = list(map(str.lower, oracle_texts))
            for regexp in COMMANDER_FEATURES_REGEXES:
                if list(search_strings(regexp, oracle_texts_low)):
                    if (COMMANDER_FEATURES_EXCLUDE_REGEX == r'()'
                        or not re.search(COMMANDER_FEATURES_EXCLUDE_REGEX,
                                         join_oracle_texts(card))):
                        commander_common_feature.append(card)
                        break

        commander_common_feature_organized = organize_by_type(commander_common_feature)

    if outformat == 'html':
        html = ''
        html += '  <section>'+'\n'
        html += "    <h3 "+'id="with-commanders-keyword"'+">Cards with a commander's keyword</h3>\n"
        html += '    <article>'+'\n'
        html += '      <details>'+'\n'
        html += "        <summary>Cards with a commander's keyword "
        html += (('('+','.join(commander_keywords)+')') if commander_keywords else '')+': '
        html += str(len(cards_common_keyword))+'</summary>'+'\n'
        html += print_cards_list(cards_common_keyword, limit = limit,
                                 outformat = outformat, return_str = True)
        html += '      </details>'+'\n'
        html += '    </article>'+'\n'

        if COMMANDER_FEATURES_REGEXES:
            html += '    <article>'+'\n'
            html += '      <details>'+'\n'
            html += '        <summary>Cards matching specified features: '
            html += str(len(commander_common_feature))+'</summary>'+'\n'
            for card_type, cards_list in commander_common_feature_organized.items():
                if cards_list:
                    html += '        <details>'+'\n'
                    html += '          <summary>Commander feature in common ('+card_type+'): '
                    html += str(len(cards_list))+'</summary>'+'\n'
                    html += '          <table class="cards-list">'+'\n'
                    for card in sort_cards_by_cmc_and_name(cards_list):
                        if card_type == 'unknown':
                            html += print_card(card, print_powr_tough = False,
                                               merge_type_powr_tough = False,
                                               outformat = outformat,
                                               return_str = True)
                        else:
                            html += print_card(card, print_powr_tough = (card_type == 'creature'),
                                               print_type = False,
                                               print_mana = (card_type not in ['land','stickers']),
                                               outformat = outformat,
                                               return_str = True)
                    html += '          </table>'+'\n'
                    html += '        </details>'+'\n'
            html += '      </details>'+'\n'
            html += '    </article>'+'\n'
        html += '  </section>'+'\n'
        print(html)

    if outformat == 'console':
        print('Cards with one common keyword', (commander_keywords if commander_keywords else ''),
              ':', len(cards_common_keyword))
        print('')
        print_cards_list(cards_common_keyword, limit = limit, indent = 5, outformat = outformat)

        if COMMANDER_FEATURES_REGEXES:
            print('Commander feature in common:', len(commander_common_feature))
            print('')
            for card_type, cards_list in commander_common_feature_organized.items():
                if cards_list:
                    print('   Commander feature in common ('+card_type+'):', len(cards_list))
                    print('')
                    for card in sort_cards_by_cmc_and_name(cards_list):
                        if card_type == 'unknown':
                            print_card(card, print_powr_tough = False, indent = 5,
                                       merge_type_powr_tough = False,
                                       outformat = outformat)
                        else:
                            print_card(card, print_powr_tough = (card_type == 'creature'),
                                       print_type = False, indent = 5,
                                       print_mana = (card_type not in ['land','stickers']),
                                       outformat = outformat)
                    print('')
            print('')

def compare_with_hand_crafted_list(selection, list_file, title, cards):
    """Compares the selection against a hand crafted list of cards"""

    list_file_path = Path(list_file)
    if not list_file_path.is_file():
        print("DEBUG list file '"+list_file+"' not found", file=sys.stderr)
        return

    misses = []
    # bad_misses = []
    with open(list_file, 'r', encoding='utf-8') as f_read:
        for name in f_read:
            name = name.strip()
            card = get_card(name, cards, strict = True)
            # if not card:
            #     print('NOT FOUND', name)
            no_print = False
            if selection:
                for selected in selection:
                    if selected['name'] == name:
                        no_print = True
                        break
            if not no_print and card and not filter_lands(card):
                oracle_texts_low = list(map(str.lower, get_oracle_texts(card)))
                # if (bool(list(in_strings('graveyard', oracle_texts_low))) or
                #         bool(list(in_strings('counter', oracle_texts_low)))):
                #     bad_misses.append(card)
                #     continue
                misses.append(card)

    print('')
    print(title)
    print('')
    print_cards_list(sort_cards_by_cmc_and_name(misses))
    print('')
    # print(title+' (bad misses)')
    # print_cards_list(sort_cards_by_cmc_and_name(bad_misses))

def main():
    """Main program"""
    global COMMANDER_NAME
    global COMMANDER_COLOR_IDENTITY
    global COMMANDER_COLOR_IDENTITY_COUNT
    global XMAGE_COMMANDER_CARDS_BANNED
    global TERM_COLS
    global TERM_LINES
    global colored

    parser = ArgumentParser(
        prog='deck_builder_assistant.py',
        description='Generate a deck base, and make suggestion for an existing deck',
        epilog='Enjoy !')

    parser.add_argument('commander_name')
    parser.add_argument('deck_path', nargs='?', help='an existing deck')
    parser.add_argument('-c', '--combo', nargs='*',
                        help='filter combos that match the specified combo effect (regex friendly)')
    parser.add_argument('-l', '--list-combos-effects', action='store_true',
                        help='list combos effects')
    parser.add_argument('-m', '--max-list-items', type=int, default=10,
                        help='limit listing to that number of items (default to 10)')
    parser.add_argument('-o', '--output', default=sys.stdout,
                        help='output to this file (default to stdout)')
    parser.add_argument('-d', '--outdir', default='/tmp',
                        help='output to this directory (default to /tmp)')
    parser.add_argument('--html', action='store_true', help='output format to an HTML page')
    # TODO Add a parameter to exclude MTG sets by name or code
    # TODO Add a parameter to prevent cards comparison with hand crafted list
    args = parser.parse_args()

    if args.list_combos_effects and args.html:
        print("Error: option '--list-combos-effects' and '--html' are mutualy exclusive "
              "(choose only one)", file=sys.stderr)
        sys.exit(1)

    if args.output != sys.stdout:
        sys.stdout = open(args.output, 'wt', encoding='utf-8')  # pylint: disable=consider-using-with

    COMMANDER_NAME = args.commander_name

    if sys.stdout.isatty():  # in a terminal
        TERM_COLS, TERM_LINES = os.get_terminal_size()

    # combo
    combos = get_commanderspellbook_combos()
    print('', file=sys.stderr)
    print('DEBUG Combos database:', len(combos), 'combos', file=sys.stderr)
    print('', file=sys.stderr)

    commander_combos_regex = '|'.join(args.combo) if args.combo else None
    combos_effects = {}
    combos_effects_matches = []
    for combo in combos:
        if 'r' in combo and combo['r']:
            for line in combo['r'].replace('. ', '\n').replace('..', '.').split('\n'):
                line_normalized = combo_effect_normalize(line)
                if line_normalized:
                    if (commander_combos_regex
                            and re.search(commander_combos_regex, line_normalized)
                            and line_normalized not in combos_effects_matches):
                        combos_effects_matches.append(line_normalized)
                    if line_normalized not in combos_effects:
                        combos_effects[line_normalized] = 0
                    combos_effects[line_normalized] += 1

    if commander_combos_regex and not combos_effects_matches:
        print("Warning: no combo effect found matching specified argument '"+
              commander_combos_regex+"'",
              file=sys.stderr)
        print('', file=sys.stderr)
        print("Suggestion: look at the list of combos effect with option '-l' and try to identify "
              "few words that will match all combos your are interested in, or use more generic "
              "wording like 'win|damage|lifeloss|lose' (use '|' to express an 'or' expression)",
              file=sys.stderr)
        print('', file=sys.stderr)
        sys.exit(1)

    if args.list_combos_effects:
        combos_effects = dict(sorted(combos_effects.items(), key=lambda t: t[1], reverse = True))
        print('Combos effects:', len(combos_effects))
        print('')
        combos_to_print = combos_effects
        if commander_combos_regex and combos_effects_matches:
            print('Combos effects matched:', len(combos_effects_matches))
            print('')
            combos_to_print = {k: v for k, v in combos_effects.items()
                               if k in combos_effects_matches}
        for effect, count in combos_to_print.items():
            if not combos_effects_matches and count < 10:
                print('      ...')
                break
            print(f'   {count:>6}  {effect}')
        sys.exit(0)

    XMAGE_COMMANDER_CARDS_BANNED = get_xmage_commander_banned_list()

    # get scryfall cards database
    cards = None
    scryfall_bulk_data = get_scryfall_bulk_data()
    scryfall_cards_db_json_file = get_scryfall_cards_db(scryfall_bulk_data)
    with open(scryfall_cards_db_json_file, "r", encoding="utf8") as r_file:
        cards = json.load(r_file)

    # output format
    outformat = 'html' if args.html else 'console'

    # HTML specifics
    if args.html:
        def colored(text, color, *pos, **kwargs):  # pylint: disable=unused-variable,unused-argument,redefined-outer-name
            """Return the text colored"""
            return '<span class="'+color+'">'+text+'</span>'

        display_html_header()

    print_all_cards_stats(cards, outformat = outformat)

    # for name in ['War of the Last Alliance', 'Wall of Shards', 'Vexing Sphinx', 'Mistwalker',
    #              'Pixie Guide', 'Library of Lat-Nam', 'Time Beetle', "Mastermind's Acquisition",
    #              'Dark Petition', 'Sky Skiff', 'Bloodvial Purveyor', 'Battlefield Raptor',
    #              'Plumeveil', 'Sleep-Cursed Faerie', 'Path of Peril', 'Sadistic Sacrament',
    #              'Incisor Glider',]:
    #     card = get_card(name, cards, strict = True)
    #     print_card(card, print_type = False)
    # sys.exit(0)

    commander_card = list(filter(lambda c: c['name'] == COMMANDER_NAME, cards))[0]
    if not commander_card:
        print("Error: failed to find the commander card '", COMMANDER_NAME, "'",
                file=sys.stderr)
        sys.exit(1)

    if not COMMANDER_COLOR_IDENTITY:
        COMMANDER_COLOR_IDENTITY = set(commander_card['color_identity'])
    COMMANDER_COLOR_IDENTITY_COUNT = len(COMMANDER_COLOR_IDENTITY)

    display_commander_card(commander_card, commander_combos_regex, outformat = outformat,
                           outdir = args.outdir)

    compute_invalid_colors()

    valid_colors = list(filter(filter_colors, cards))
    valid_rules0 = list(filter(filter_all_at_once, valid_colors))
    cards_ok = valid_rules0

    print_deck_cards_stats(cards, valid_colors, valid_rules0, outformat = outformat)

    display_deck_building_header(outformat = outformat)

    commander_combos_no_filter = get_combos(combos, cards, name = COMMANDER_NAME, only_ok = False)
    commander_combos = get_combos(combos, cards_ok, name = COMMANDER_NAME)

    combos_rank_1, combos_rank_2 = assist_commander_combos(
            commander_combos_no_filter, commander_combos, commander_combos_regex, combos, cards_ok,
            outformat = outformat)

    if USE_NX:
        cards_excludes = (list(combos_rank_1.keys()) + list(combos_rank_2.keys()))
        if outformat == 'html':
            html = '  <section>'+'\n'
            html += '    <h3 id="combos-k-core">'
            html += 'Combos k-core <small>(not tied to the commander)</small></h3>'
            print(html)
        assist_k_core_combos(combos, cards_ok, commander_combos_regex, 2, cards_excludes,
                             outformat = outformat)
        assist_k_core_combos(combos, cards_ok, commander_combos_regex, 3, cards_excludes,
                             outformat = outformat)
        if outformat == 'html':
            html = '  </section>'+'\n'
            print(html)

    # one common keyword
    assist_commander_keywords_common(commander_card, cards_ok, limit = args.max_list_items,
                                     outformat = outformat)

    lands = list(filter(filter_lands, cards_ok))
    land_types_invalid = [COLOR_TO_LAND[c] for c in INVALID_COLORS]
    # print('Land types not matching commander:', land_types_invalid)
    # print('')
    land_types_invalid_regex = r'('+('|'.join(land_types_invalid)).lower()+')'
    assist_land_selection(lands, land_types_invalid_regex, max_list_items = args.max_list_items,
                          outformat = outformat)

    cards_ramp_cards_land_fetch = assist_land_fetch(
        cards_ok, land_types_invalid_regex, max_list_items = args.max_list_items,
        outformat = outformat)

    cards_ramp_cards = assist_ramp_cards(
        [c for c in cards_ok if c not in cards_ramp_cards_land_fetch],
        land_types_invalid_regex, max_list_items = args.max_list_items,
        outformat = outformat)

    if outformat == 'console':
        selection = cards_ramp_cards + cards_ramp_cards_land_fetch
        compare_with_hand_crafted_list(selection, 'ramp_cards.list.txt',
                                       'Ramp cards missing (VS ramp_cards.list.txt)',
                                       cards_ok)

    cards_draw_cards = assist_draw_cards(
        [c for c in cards_ok if c not in cards_ramp_cards_land_fetch],
        land_types_invalid_regex, max_list_items = args.max_list_items,
        outformat = outformat)

    if outformat == 'console':
        selection = cards_ramp_cards + cards_ramp_cards_land_fetch + cards_draw_cards
        compare_with_hand_crafted_list(selection, 'draw_cards.list.txt',
                                       'Draw cards missing (VS draw_cards.list.txt)',
                                       cards_ok)

    cards_tutor_cards = assist_tutor_cards(
        [c for c in cards_ok if c not in cards_ramp_cards_land_fetch],
        land_types_invalid_regex, max_list_items = args.max_list_items,
        outformat = outformat)

    if outformat == 'console':
        selection = (cards_ramp_cards + cards_ramp_cards_land_fetch + cards_draw_cards
                     + cards_tutor_cards)
        compare_with_hand_crafted_list(selection, 'tutor_cards.list.txt',
                                       'Tutor cards missing (VS tutor_cards.list.txt)',
                                       cards_ok)

    cards_removal = assist_removal_cards(
        [c for c in cards_ok if c not in cards_draw_cards and c not in cards_tutor_cards],
        max_list_items = args.max_list_items, outformat = outformat)

    cards_disabling = assist_disabling_cards(
        [c for c in cards_ok if c not in cards_draw_cards and c not in cards_tutor_cards
         and c not in cards_removal],
        max_list_items = args.max_list_items, outformat = outformat)

    if outformat == 'console':
        selection = cards_removal + cards_disabling
        compare_with_hand_crafted_list(selection, 'removal_cards.list.txt',
                                       'Removal/disabling cards missing (VS removal_cards.list.txt)',
                                       cards_ok)

    cards_wipe = assist_wipe_cards(
        [c for c in cards_ok if c not in cards_removal],
        max_list_items = args.max_list_items, outformat = outformat)

    if outformat == 'console':
        selection = cards_removal + cards_wipe
        compare_with_hand_crafted_list(selection, 'wipe_cards.list.txt',
                                       'Wipe cards missing (VS wipe_cards.list.txt)',
                                       cards_ok)

    cards_graveyard_recursion = assist_graveyard_recursion_cards(
        [c for c in cards_ok if c not in cards_removal and c not in cards_wipe],
        max_list_items = args.max_list_items, outformat = outformat)

    if outformat == 'console':
        selection = cards_graveyard_recursion
        compare_with_hand_crafted_list(
            selection, 'graveyard_recursion_cards.list.txt',
            'Graveyard recursion cards missing (VS graveyard_recursion_cards.list.txt)',
            cards_ok)

    cards_graveyard_hate = assist_graveyard_hate_cards(
        [c for c in cards_ok if c not in cards_removal and c not in cards_wipe],
        max_list_items = args.max_list_items, outformat = outformat)

    if outformat == 'console':
        selection = cards_graveyard_hate
        compare_with_hand_crafted_list(
            selection, 'graveyard_hate_cards.list.txt',
            'Graveyard hate cards missing (VS graveyard_hate_cards.list.txt)',
            cards_ok)

    cards_copy = assist_copy_cards(
        [c for c in cards_ok if c not in cards_draw_cards and c not in cards_tutor_cards
         and c not in cards_removal and c not in lands],
        max_list_items = args.max_list_items, outformat = outformat)

    cards_best = assist_best_cards(
        cards_ok, max_list_items = args.max_list_items, outformat = outformat)

    # TODO select 1 'I win' suprise card

    # TODO for each turn N present a list of possible N-drop cards

    if args.html:
        html = ''
        html += '    </div>'+'\n'
        html += '    <footer class="main-footer">Copyright © Michael Bideau '
        html += '(all images and text are the property of Wizard of the Coast)</footer>'+'\n'
        html += '  </div>'+'\n' # wrapper end
        # on page load, uncheck all checked checkboxes
        html += '  <script>'+'\n'
        html += '    function uncheck_all() {'+'\n'
        html += '      var checkedBoxes = document.querySelectorAll("input[name=cards]:checked");'+'\n'
        html += '      for (i = 0; i < checkedBoxes.length; i++) { checkedBoxes[i].checked = false; }'+'\n'
        html += '    };'
        html += '    window.onload = uncheck_all();'
        html += '  </script>'+'\n'
        html += '</body>'+'\n'
        html += '</html>'
        print(html)

if __name__ == '__main__':
    try:
        main()
    except BrokenPipeError:
        pass
    except KeyboardInterrupt:
        print('', file=sys.stderr)
        print('Ciao !', file=sys.stderr)
