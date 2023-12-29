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

IFWHEN_REGEXP = '(if|when(ever)|every *time|each time)'
PLAYER_REGEXP = ("(you|they|("
                    "(an?|target|that|chosen|each|every|enchanted|its|'s|defending|attacking) "
                    '(player|opponent|owner|controller)'
                 ')|your opponents)')

# entries format is the following:
#   <feature_name>: {
#     <regex_checked_against_commander_oracle_text>: [
#        <regex_check_against_all_other_cards>
#        or tuple(<regex_check_against_all_other_cards>,
#                 [<exclude_regex_that_should_not_match>, ...])
#        ...
#     ],
#     ...
#   },
#   ...
COMMANDER_FEATURES_REGEXES = {
    'lifeloss': {
        PLAYER_REGEXP+'.*(lose|have lost).*life': [
            IFWHEN_REGEXP+' '+PLAYER_REGEXP+' loses? life']},
    'lifegain': {
        'lifelink|'+PLAYER_REGEXP+'.*(gain(ed)?|have gained).*life': [
            IFWHEN_REGEXP+' you gain(ed)? [^.]*life']},
    'draw': {
        PLAYER_REGEXP+'.*(draw|have draw)': [
            IFWHEN_REGEXP+' you draw']},
    'damage dealt to player': {
        # NOTE: 'shadow' and 'horsemanship' are not taken into account because they are dubious
        '(trample|fear( |[,.])|menace|skulk|intimidate|can be blocked only by' # add flying ?
        '|'+PLAYER_REGEXP+' (is|are) dealt damage)': [
            (IFWHEN_REGEXP+' ('+PLAYER_REGEXP+' is dealt damage'
             '|deals? (combat )?damage to '+PLAYER_REGEXP+')',
             ["if a player is dealt damage this way"])]},
    'poison': {
        '(toxic|poison|infect)': [
            ('(toxic|poison|infect)', ["if that creature has (toxic|infect)", "infection counter",
                                       "you can't get poison counters"]),
            IFWHEN_REGEXP+' '+PLAYER_REGEXP+' (gets? a poison counter|is poisoned)',
            '(^|\n|[,.] )corrupted']},
    'counters': {
        '((add|put) [^.]+ counter)' : [IFWHEN_REGEXP+' [^.]+ counter']},
    'tokens': {
        '(create [^.]*token)': [IFWHEN_REGEXP+' [^.]+ create [^.]*token']},
    'pay with life': {
        'can be paid with [^.]*life': [
            IFWHEN_REGEXP+' you pay with [^.]*life',
            '(may be paid with|pay|you lose) [^.]*life']},
    'force blocking': {
        # @see: https://boardgames.stackexchange.com/a/7311
        "must be blocked": [
            ("must be blocked", ["must be blocked by exactly [^.]+ creature",
                                 "must be blocked by an?"]),
            "all creatures able to block"]},
    'unblockable': {
        "unblockable|can't be blocked|creatures [^.]+ can't block creatures you control": [
            ("unblockable|can't be blocked|creatures [^.]+ can't block creatures you control", [
                "protection from",
                "can't be blocked by more than one creature",
                "can't be blocked by (walls|humans|knights|saprolings|vampires|artifacts?|enchanted|creature token)",
                "can't be blocked by creatures with (flying|horsemanship)",
                "can't be blocked (this turn )?except by",
                "can't be blocked by creatures with power",
                "can't be blocked by (blue|red|green|white|black) creatures",
                "can't be blocked as long as defending player controls an? [^.]+",
                "can't be blocked by creatures with greater power",
                "can block or be blocked by only creatures with shadow",
                "can't be blocked as long as defending player controls the most creatures",
                r"\(this spell works on creatures that can't be blocked\.\)",
                ])]},
    'evade blocking': {
        # NOTE: 'shadow' and 'horsemanship' are not taken into account because they are dubious
        "menace|intimidate|skulk|fear( |[,.])|can be blocked only by|can't be blocked except by": [
            "menace|intimidate|skulk|fear( |[,.])|can be blocked only by|can't be blocked except by"
            ]}, # add flying ?
    'proliferate': {
        'proliferate': ['proliferate']},
    'populate': {
        'populate': ['populate']},
    # TODO add ETB (Enter The Battlefield), LTB (Leave The Battlefield)
}
# list of associated features
FEATURE_MAP = {
    'feat:lifegain': [
        'feat:pay with life',
        'keyword:Lifelink'],
    'feat:force blocking': [
        'feat:poison',
        'feat:damage dealt to player'],
    'feat:poison': [
        'feat:proliferate',
        'feat:unblockable',
        'feat:evade blocking',
        'feat:force blocking'],
    'feat:proliferate': [
        'feat:poison',
        'feat:counters',
        'feat:tokens'],
    'feat:populate': [
        'feat:tokens'],
    'feat:tokens': [
        'feat:populate',
        'feat:proliferate'],
    'feat:counters': [
        'feat:proliferate']}

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
WIPE_CARDS_BY_FEATURE_REGEX = {
    'only affect opponent': [
        "(exile|destroy) (all|each) (artifacts|creatures) your opponents control"],
    'selective': [
        "destroy each (nonland permanent|artifact and creature) with mana value [^.]+ counters",
        "destroy all creatures that dealt damage to you this turn",
        "destroy all non-wall creatures that player controls that didn't attack",
        "destroy all untapped creatures that didn't attack this turn",
        "destroy all creatures of the creature type",
        "destroy all creatures with no counters on them"],
    'mana value': [
        "(destroy|exile) (each|all) (nonland permanent|artifacts?|creatures?) with mana value",
        r"destroy all creatures \[with mana value 2 or less\]",
        "destroy all permanents with that spell's mana value"],
    'strength value': ["(destroy|exile) all creatures with (power|toughness)"],
    'tapped / untapped': ["(exile|destroy) all (un)?tapped creatures"]
}
WIPE_CARDS_EXCLUDE_REGEX = r'('+('|'.join([
    'remove all damage',
    'exile all other cards revealed',
    "exile each opponent's (library|hand|graveyard)",
    r'remove all ((\w+|[+-]\d/[+-]\d) )?counter',
    "exile (all cards from )?(all|target player's) graveyard",
    r"exile all creature cards (with mana value \d or less )?from (target player's|your) "
        "(library|hand|graveyard)",
    r'destroy all (\w+ )?tokens',
    'remove all attackers (and blockers )?from combat',
    '(exile|remove) all attacking creatures',
    'exile all (the )?cards from your (library|hand|graveyard)',
    'if [^.]+ has [^.]+ counters on it, remove all of them',
    'exile all spells and abilities from the stack',
    'destroy all creatures that entered the battlefield this turn',
    'exile (all|every|each) (nontoken )?creatures? you control',
    "exile all hallow's eve",
    'exile all (warriors|zombies)',
    "exile all creature cards from all graveyards",
    "destroy all creatures that were blocked by that creature",
    "exile all creatures. at the beginning of the next end step, return those cards",
    "return to your hand all enchantments you both own and control",
    "destroy each of the chosen creatures that didn't attack",
    "destroy each of those creatures that didn't attack",
    "destroy all auras and equipment attached to target creature",
    "then if there are five or more hatchling counters on it, remove all of them and transform it",
    "destroy all nontoken permanents with a name originally printed in the homelands expansion",
    "then, destroy all other creatures if its power is exactly 20",
    "exile all cards that are black or red from all graveyards",
    "flip a coin",
    "while an opponent is searching their library, they exile each card they find",
    "whenever a player casts a creature spell, destroy all reflections",
    "exile each permanent with the most votes",
    "destroy all goblins",
    "destroy all merfolk tapped",
    "exile all creatures blocked by",
    "destroy each permanent with a doom counter on it",
    "exile each creature that crewed it",
    "destroy all curses attached to you",
    "destroy all creatures that share a creature type with the sacrificed creature",
    "destroy each permanent with the same name as another permanent",
    "then exile all other tokens created with",
    "exile all serf tokens",
    "then destroy all creatures except creatures chosen this way",
    "destroy each creature chosen this way",
    "destroy all auras attached to them",
    "exile all opponents' graveyards",
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
        # TODO add cards that 'explore'
        '(look for |search |play )[^.]+ land',
        ("(reveal|look at) the top card of your library.*if it's a land card, "+
        "(then |you may )?put (it|that card) onto the battlefield"),
        'put (a|up to \\w+) lands? cards? from your hand onto the battlefield',
        "gain control of a land you don't control"],
    # TODO improves categorisation (separate malus cards, etc.)
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
RAMP_CARDS_MALUS_REGEX = {
    'mana': [
        "Spend this mana only to",
        r"{\w+}, Pay \w+ life: Add [^.]+ mana",
        r"Sacrifice <name>: Add ({\w+}|[^.]+ mana)",
        "As an additional cost to cast this spell, (exile|sacrifice|tap|reveal|discard)",
        "When <name> dies, [^.]*create a Treasure token",
        "When <name> dies, choose one .*. Create a Treasure token",
        r"{[^T]+}: Add ({\w+}|[^.]+ mana)",
        "{T}, Sacrifice another creature",
        r"{T}, Tap an untapped [^.]+ you control: Add ({\w+}|[^.]+ mana)",
        r"When <name> dies, add ({\w+}|[^.]+ mana)",
        "Whenever equipped creature deals combat damage to a player, create a Treasure token",
        r"Sacrifice this land: Add ({\w+}|[^.]+ mana)",
        "You can't spend this mana to cast spells",
        r"Sacrifice this creature: Add ({\w+}|[^.]+ mana)",
        "Roll (a d6|the planar die)",
        r"{T}: Add ({\w+}|[^.]+ mana of any color). Activate only if",
        "When <name> enters the battlefield, create a Treasure token",
        "Exile <name> from your graveyard: Create a Treasure token",
        "Whenever <name> attacks, each player creates a Treasure token",
        r"{T}, Mill [^.]+ card: Add {\w+}",
        "When <name> enters the battlefield or is put into a graveyard from the battlefield, "
            "create a Treasure token",
        r"{T}: Add {\w+} or {\w+}. <name> deals 1 damage to you",
        "Whenever <name> becomes blocked, choose one [^.]+ Create a Treasure token",
        r"Whenever a creature enters the battlefield, you lose [^.]+ life and add {\w+}",
    ]}
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

NO_PAY_CARDS_REGEX = {
    'hand': [
        '(you may )?put (a|this|that|target) creature card from your hand (on)?to the battlefield'],
    'library': [
        'reveal.*library.*without paying its mana cost'],
    'exile, suspend': [
        'suspend.*when the last is removed, cast it without paying its mana cost',
        'exile it with [^.]+ time counters on it and it gains suspend'],
    'exile, cascade': [
        ('cascade.*when you cast this spell, exile cards from the top of your library until you '
         'exile a nonland card that costs less. you may cast it without paying its mana cost'),
        ('spells? you cast( from exile)?( (this|each) turn)?( that mana from a treasure was spent '
         'to cast)? (have|has) cascade')],
    'exile, discover': [
        ('discover.*exile cards from the top of your library until you exile a nonland card with '
         'mana value [0-9]?[0-9x] or less. cast it without paying its mana cost')],
    'exile, enlist': [
        ('enlist(\n)?.*look at the top [^.]+ cards of your library.*you may exile an instant or '
         'sorcery card with mana value [0-9]?[0-9x] or less from among them')],
    'exile, imprint': [
        'imprint.*you may exile an instant card with mana value [0-9]?[0-9x] or less from your hand',
        ("imprint.*whenever a player casts an instant or sorcery spell from their hand, exile it "
         "instead of putting it into a graveyard as it resolves"),
        ('imprint.*when [^.]+ enters the battlefield, you may exile [^.]+ cards? from '
         '(your hand|a( single)? graveyard)'),
        ('imprint.*when [^.]+ enters the battlefield, each player exiles the top [^.]+ cards of '
         'their library'),
        ],
    'exile, hideaway': [
        ('hideaway.*look at the top [^.]+ cards of your library, exile one face down, then put the '
         'rest on the bottom in a random order')],
    'exile, other': [
        'exile.*without paying its mana cost'],
    'graveyard': [
        ('(you may )?return (a|this|that|target) creature card from your graveyard '
         '(on)?to the battlefield')],
    # "opponent's": [
    #     "if a card would be put into an opponent's graveyard.*without paying its mana cost"],
    }

NO_PAY_CARDS_EXCLUDE_REGEX = r'('+('|'.join([
    'rebound.*cast this card from exile without paying its mana cost',
    # 'imprint.*you may cast the copy without paying its mana cost',
    ("if you control a creature with power [^.]+, you may play the exiled card without paying its "
     "mana cost"),
    'cipher.*its controller may cast a copy of the encoded card without paying its mana cost',
]))+')'

CREATURE_MALUS_REGEXES = [
    "As an additional cost to cast this spell, (exile|sacrifice|tap|reveal|discard)",
    "When <name> enters the battlefield, (sacrifice (it|a)|(exile|return) (it|[^.]+ you control))",
    "When <name> enters the battlefield, target opponent (creates|gains)",
    "When <name> enters the battlefield, each other player may",
    "When <name> enters the battlefield, each opponent creates",
    "When <name> enters the battlefield, exile all cards from your library",
    "When <name> enters the battlefield, you skip your [^.]+ turns?",
    "When <name> enters the battlefield from a graveyard, target opponent gains",
    "When <name> enters the battlefield, you lose [^.]+ life",
    "When <name> enters the battlefield, put [^.]*-[0-9X]/-[0-9X] counters on (target )?creatures? you control",
    "When <name> enters the battlefield, an opponent chooses a permanent you control other than <name> and exiles it",
    "When <name> leaves the battlefield, sacrifice [^.]+ creatures? you control",
    "When <name> leaves the battlefield, sacrifice a land",
    "At the beginning of your upkeep, (tap|sacrifice) <name>",
    "At the beginning of your upkeep, discard a card.",
    "At the beginning of your upkeep, you lose [^.]+ life",
    "At the beginning of your upkeep, if you have a card in hand, return <name>",
    "At the beginning of your upkeep, the player with the lowest life total gains control of <name>",
    "At the beginning of your upkeep, each opponent draws a card",
    "At the beginning of your upkeep, <name> deals [^.]+ damage to you",
    "At the beginning of your upkeep, this permanent deals [^.]+ damage to you",
    "At the beginning of your upkeep, sacrifice a permanent",
    "At the beginning of your end step, sacrifice ",
    "At the beginning of your end step, you lose [^.]+ life",
    "At the beginning of your end step, if <name> is untapped, you lose [^.]+ life",
    "At the beginning of your end step, if <name> didn't attack this turn, Erg Raiders deals [0-9X] damage to you",
    "When an opponent casts a creature spell, sacrifice <name>",
    "When you control no enchantments, sacrifice <name>",
    "<name> gets? -[0-9X]/-[0-9X]",
    "Whenever <name> blocks, put a -[0-9X]/-[0-9X] counter",
    "Whenever <name> attacks or blocks, put a -[0-9X]/-[0-9X] counter on it",
    "When <name> (attacks or )?blocks, (sacrifice|return) it",
    "When <name> (attacks or )?blocks, put it on top of its owner's library at end of combat",
    "Whenever <name> blocks or becomes blocked by a creature with power [0-9X]( or less)?, destroy <name>",
    "<name> can't (attack|block)",
    "<name> doesn't untap during your untap step",
    "spells you cast cost [^.]+ more to cast",
    "When <name> becomes the target of a spell or ability, sacrifice it",
    "Whenever <name> deals damage to a creature or opponent, <name> deals that much damage to you.",
    "Whenever <name> deals combat damage, sacrifice",
    "Whenever a player casts a spell, sacrifice a creature",
    "Whenever an opponent casts a spell, put a -[0-9X]/-[0-9X] counter on <name>",
    "<name> enters the battlefield tapped",
    "Spend only mana produced by creatures to cast this spell",
    "When <name> dies, target opponent creates",
    "<name> enters the battlefield tapped and doesn't untap",
    "As long as <name> has [^.]+ counter on it, prevent all combat damage",
    "When you control no permanents with [^.]+ counters on them, sacrifice <name>",
    "(^|\n|[,.] )Cumulative upkeep",
    "(^|\n|[,.] )Vanishing",
    "(^|\n|[,.] )Champion an?",
    "(^|\n|[,.] )Phasing",
    "(^|\n|[,.] )Echo",
    "You can't cast (creature )?spells",
    "Black creatures can't block",
    "If a player does, sacrifice <name>",
    "If a player does, <name> assigns no combat damage this turn",
    "You can't win the game",
    "Cast this spell only if you've cast another spell this turn",
    "When you control no permanents of the chosen color, sacrifice <name>",
    "When you cast a creature spell, sacrifice <name>",
    "Other creatures you control get -[0-9X]/-[0-9X]"
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

COLORIZE_KEYWORD_REGEX_PART = '('+('|'.join(KEYWORDS_ABILITIES + ABILITY_WORDS))+')'

# see https://mtg.fandom.com/wiki/Category:Miscellaneous_mechanics
# TODO: craft some regex to detect each

BASIC_LAND_NAMES = ['Forest', 'Mountain', 'Plains', 'Island', 'Swamp']

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

def get_oracle_texts(card, replace_name = None):
    """Return a list of 'oracle_text', one per card's faces"""
    texts = []
    if 'oracle_text' in card:
        if replace_name:
            texts.append(card['oracle_text'].replace(card['name'], replace_name))
        else:
            texts.append(card['oracle_text'])
    elif 'card_faces' in card and card['card_faces']:
        for face in card['card_faces']:
            if replace_name:
                texts.append(face['oracle_text'].replace(face['name'], replace_name))
            else:
                texts.append(face['oracle_text'])
    return texts

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

def filter_stickers(item):
    """Remove cards that are Stickers"""
    return 'type_line' not in item or item['type_line'] != 'Stickers'

def filter_rules0(item, preset):
    """Remove card if it doesn't pass all filters"""

    # xmage banned
    if 'with-xmage-banned' in preset and not filter_xmage_banned(item):
        return False

    # rarity: less rare than defined rarity
    if 'no-mythic' in preset and not filter_mythic_and_special(item):
        return False

    # price: not above a defined amount in EUR/USD
    if 'no-expensive' in preset and not filter_price(item):
        return False

    # no stickers or tickets
    if 'no-stickers' in preset and not filter_stickers(item):
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

def score_card_from_cmc_and_mana_cost_len(card):
    """Return a decimal score build on CMC value and length of mana cost value"""
    cmc = float(card['cmc']) if 'cmc' in card else 0.0
    mana_cost = float('0.'+(str(len(card['mana_cost'])) if 'mana_cost' in card else '0').zfill(2))
    integer, decimal = str(cmc + mana_cost).split('.')
    score = integer.zfill(2) + '.' + decimal.zfill(2)
    return score

def sort_cards_by_cmc_and_name(cards_list):
    """Return an ordered cards list by CMC + Mana cost length as a decimal, and Name"""
    return list(sorted(cards_list,
                       key=lambda c: score_card_from_cmc_and_mana_cost_len(c) + c['name']))

def print_all_cards_stats(cards, non_empty_cards, commander_legal, valid_rules0, preset,
                          outformat = 'console'):
    """Print statistics about all cards"""

    empty_cards_count = len(cards) - len(non_empty_cards)
    illegal_cards_count = len(non_empty_cards) - len(commander_legal)
    violate_rules0 = len(commander_legal) - len(valid_rules0)
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
        html += '  <section id="stats-all-cards">'+'\n'
        html += '    <h3>Stats: all cards</h3>'+'\n'
        html += '    <dl>'+'\n'
        html += '      <dt>Total cards</dt>'+'\n'
        html += '      <dd>'+str(len(cards))+'</dd>'+'\n'
        html += '      <dt>Empty cards</dt>'+'\n'
        html += '      <dd>'+str(empty_cards_count)+'</dd>'+'\n'
        html += '      <dt>Illegal or banned</dt>'+'\n'
        html += '      <dd>'+str(illegal_cards_count)+'</dd>'+'\n'
        html += '      <dt>Violate rules 0 <small>('+preset+')</small></dt>'+'\n'
        html += '      <dd>'+str(violate_rules0)+'</dd>'+'\n'
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
        print('Empty cards:', empty_cards_count)
        print('')
        print('Illegal or banned:', illegal_cards_count)
        print('')
        print('Violate rules 0 ('+preset+'):', violate_rules0)
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

    cards_lands_producers_non_basic = list(filter(
        lambda c: (bool(list(search_strings('gains?|loses?', get_oracle_texts(c))))
                   and not bool(list(search_strings('(gains?|loses?) [^.]*life',
                                                    get_oracle_texts(c))))),
        filter(
            lambda c: not c['type_line'].lower().startswith('basic land'),
            [c for c in lands if c not in cards_lands_multicolors_generic_enough
            and c not in cards_lands_converters
            and c not in cards_lands_tricolors
            and c not in cards_lands_bicolors
            and c not in cards_lands_sacrifice_search])))

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
    cards_lands_producers_non_basic_colorless_not_tapped = list(filter(
        filter_tapped, cards_lands_producers_non_basic_colorless))
    cards_lands_producers_non_basic_colorless_tapped = [
        c for c in cards_lands_producers_non_basic_colorless
        if c not in cards_lands_producers_non_basic_colorless_not_tapped]
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
    #     print_card(card, trunc_name = 25, print_mana = False, print_type = False, print_powr_tough = False, indent = 6)
    # print('')
    # print('   Lands producers of mana that are nonbasic (no colorless, tapped):',
    #        len(cards_lands_producers_non_basic_no_colorless_tapped))
    # print('')
    # print('   Lands producers of mana that are nonbasic (colorless):',
    #         len(cards_lands_producers_non_basic_colorless))
    # for card in cards_lands_producers_non_basic_colorless:
    #     print_card(card, trunc_name = 25, print_mana = False, print_type = False, print_powr_tough = False, indent = 6)
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
        'Non-basic lands doing some effects (total)': cards_lands_producers_non_basic,
        'Non-basic lands doing some effects (no colorless)':
            cards_lands_producers_non_basic_no_colorless,
        'Non-basic lands doing some effects (no colorless, not tapped)':
            cards_lands_producers_non_basic_no_colorless_not_tapped,
        'Non-basic lands doing some effects (no colorless, tapped)':
            cards_lands_producers_non_basic_no_colorless_tapped,
        'Non-basic lands doing some effects (colorless)':
            cards_lands_producers_non_basic_colorless,
        'Non-basic lands doing some effects (colorless, not tapped)':
            cards_lands_producers_non_basic_colorless_not_tapped,
        'Non-basic lands doing some effects (colorless, tapped)':
            cards_lands_producers_non_basic_colorless_tapped,
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
             cards_lands_sacrifice_search_no_tapped)],
        'Non-basic lands doing some effects': [
            ('Non-basic lands doing some effects (no colorless, not tapped)',
                cards_lands_producers_non_basic_no_colorless_not_tapped),
            ('Non-basic lands doing some effects (colorless, not tapped)',
                cards_lands_producers_non_basic_colorless_not_tapped)],
    }

    for section, data in land_output_data.items():
        for tup in data:
            cards_list = tup[1]
            selected_lands += cards_list[:max_list_items]

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
                print_cards_list(tup[1], limit = max_list_items, indent = 6, print_mana = False,
                                 print_type = False, print_powr_tough = False, outformat=outformat)

    # TODO select monocolor lands to match 37 lands cards (at the end)
    #      42 cards recommanded: @see https://www.channelfireball.com/article/What-s-an-Optimal-Mana-Curve-and-Land-Ramp-Count-for-Commander/e22caad1-b04b-4f8a-951b-a41e9f08da14/
    #      - 3 land for each 5 ramp cards
    #      - 2 land for each 5 draw cards

    return selected_lands

def assist_land_fetch(cards, land_types_invalid_regex, max_list_items = None, outformat = 'console'):
    """Show pre-selected land fetchers organised by features, for the user to select some"""

    cards_land_fetch_selected = []
    cards_land_fetch = []
    cards_land_fetch_channel = []
    cards_land_fetch_land_cycling = []

    for card in cards:
        card_oracle_texts = list(get_oracle_texts(card))
        card_oracle_texts_low = list(map(str.lower, card_oracle_texts))
        if not list(search_strings(land_types_invalid_regex, card_oracle_texts_low)):
            if card['name'] not in ["Strata Scythe", "Trench Gorger"]:
                if list(search_strings(LAND_CYCLING_REGEX, card_oracle_texts_low)):
                    cards_land_fetch_land_cycling.append(card['name'])
                    cards_land_fetch.append(card)
                elif (bool(list(search_strings(RAMP_CARDS_LAND_FETCH_REGEX, card_oracle_texts_low)))
                        #and not list(search_strings(r'(you|target player|opponent).*discard',
                        #                            card_oracle_texts_low))
                        and card['name'] not in ['Mana Severance', 'Settle the Wreckage']
                        and not filter_lands(card)):
                    if bool(list(in_strings('channel', card_oracle_texts_low))):
                        cards_land_fetch_channel.append(card['name'])
                    cards_land_fetch.append(card)

    cards_land_fetch_by_feature = {
        'to battlefield': [],
        'to battlefield, conditional': [],
        'to hand': [],
        'to hand, conditional': [],
        'to top of library': [],
        'to top of library, conditional': []}
    for card in cards_land_fetch:
        card_oracle_texts = list(get_oracle_texts(card))
        card_oracle_texts_low = list(map(str.lower, card_oracle_texts))
        conditional = (bool(list(in_strings('more lands', card_oracle_texts_low)))
                       or bool(list(in_strings('fewer lands', card_oracle_texts_low))))
        cond_text = ', conditional' if conditional else ''
        if list(search_strings(
                r'puts? '
                '(it|that card|one( of them)?|them|those cards|a card [^.]+|[^.]+ and the rest) '
                'in(to)? (your|their) hand', card_oracle_texts_low)):
            cards_land_fetch_by_feature['to hand'+cond_text].append(card)
        elif list(search_strings(
                r'puts? (it|that card|one( of them| of those cards)?|them|(those|both) cards) '
                'on(to)? the battlefield', card_oracle_texts_low)):
            cards_land_fetch_by_feature['to battlefield'+cond_text].append(card)
        elif list(search_strings('put (that card|them) on top', card_oracle_texts_low)):
            cards_land_fetch_by_feature['to top of library'+cond_text].append(card)
        else:
            print('UNKNOWN land fetch categorie',
                  print_card(card, return_str = True, trunc_text = False, outformat = 'console'),
                  file=sys.stderr)

    for feature, cards_list in cards_land_fetch_by_feature.items():
        organized = {}
        if cards_list:
            for card in cards_list:
                if card['name'] in cards_land_fetch_land_cycling:
                    if 'land cycling' not in organized:
                        organized['land cycling'] = []
                    organized['land cycling'].append(card)
                elif card['name'] in cards_land_fetch_channel:
                    if 'channel' not in organized:
                        organized['channel'] = []
                    organized['channel'].append(card)
                else:
                    card_type = get_card_type(card)
                    if card_type not in organized:
                        organized[card_type] = []
                    organized[card_type].append(card)
        cards_land_fetch_by_feature[feature] = organized

    for organized in cards_land_fetch_by_feature.values():
        for cards_list in organized.values():
            cards_land_fetch_selected += sort_cards_by_cmc_and_name(cards_list)[:max_list_items]

    if outformat == 'html':
        html = ''
        html += '  <section>'+'\n'
        html += '    <h3 id="land-fetchers">Land fetchers</h3>\n'
        html += '    <h4>Stats</h4>'+'\n'
        html += '    <dl>'+'\n'
        html += '      <dt>Land fetchers (total)</dt>'+'\n'
        html += '      <dd>'+str(len(cards_land_fetch))+'</dd>'+'\n'
        for feature, organized in cards_land_fetch_by_feature.items():
            for card_type, cards_list in organized.items():  # pylint: disable=no-member
                extra_text = '(Ramp cards) ' if feature.startswith('to battlefield') else ''
                title = extra_text+'Land fetchers ('+feature+') '+card_type
                html += '      <dt>'+title+'</dt>'+'\n'
                html += '      <dd>'+str(len(cards_list))+'</dd>'+'\n'
        html += '    </dl>'+'\n'
        html += '    <h4>Land fetchers by feature</h4>'+'\n'
        for feature, organized in cards_land_fetch_by_feature.items():
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
                                         outformat = outformat, return_str = True,
                                         card_feat = 'land-fetchers')
                html += '      </details>'+'\n'
                html += '    </article>'+'\n'
        html += '  </section>'+'\n'
        print(html)

    if outformat == 'console':
        print('Land fetch (total):', len(cards_land_fetch))
        print('')
        for feature, organized in cards_land_fetch_by_feature.items():
            for card_type, cards_list in organized.items():  # pylint: disable=no-member
                extra_text = '(Ramp cards) ' if feature.startswith('to battlefield') else ''
                title = extra_text+'Land fetch ('+card_type+')'+': '+str(len(cards_list))
                print('   '+title)
                print('')
                if ', conditional' in feature:
                    print('')
                    continue
                print_cards_list(sort_cards_by_cmc_and_name(cards_list),
                                 print_powr_tough = (card_type == 'creature'),
                                 print_type = (feature not in ['land cycling', 'channel']),
                                 indent = 6, limit = max_list_items,
                                 print_mana = (card_type not in ['land', 'stickers']),
                                 outformat = outformat)
            print('')

    return cards_land_fetch_selected

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

def get_card_css_class(card):
    """Return the CSS classname for the specified card"""
    return re.sub('[^a-z0-9_-]', '', card['name'].lower().replace(' ', '-'))

def print_card(card, indent = 0, print_mana = True, print_type = True, print_powr_tough = True,
               trunc_name = 25, trunc_type = 16, trunc_text = 'auto', trunc_mana = 10,
               merge_type_powr_tough = True, return_str = False, print_text = True,
               print_keywords = False, print_edhrank = True, print_price = True,
               trunc_powr_tough = 6, separator_color = 'dark_grey', rank_price_color = 'light_grey',
               rank_price_attrs = None, outformat = 'console', card_feat = None,
               print_rarity = False):
    """Display a card or return a string representing it"""

    merge_type_powr_tough = merge_type_powr_tough and print_type and print_powr_tough
    if merge_type_powr_tough and (not trunc_type or trunc_type > 10):
        trunc_type = 10  # default power/toughness length
    len_type = '16' if not trunc_type else str(trunc_type)

    line = ''

    if outformat == 'html':
        html = ''
        cardclass = get_card_css_class(card)
        html += '        <tr class="card-line '+cardclass+'">'+'\n'
        html += '          <td class="input">'
        card_type = get_card_type(card)
        card_feat_attr = ' data-cardfeat="'+card_feat+'"' if card_feat else ''
        html += '<input type="checkbox" name="cards" value="'+card['name']+'" '
        html += 'onchange="updateDeckList(this)" data-cardtype="'+f'{card_type}'+'"'
        html += card_feat_attr+'/></td>\n'
        if print_rarity:
            rarity_value = card['rarity'] if 'rarity' in card else ''
            html += '          <td class="rarity">'+str(rarity_value)+'</td>\n'
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
        # TODO display both faces
        imgurl = ''
        if 'image_uris' in card and 'normal' in card['image_uris']:
            imgurl = card['image_uris']['normal']
        elif ('card_faces' in card and card['card_faces'] and 'image_uris' in card['card_faces'][0]
              and 'normal' in card['card_faces'][0]['image_uris']):
            imgurl = card['card_faces'][0]['image_uris']['normal']
        img_element = '<img src="#" data-imgurl="'+imgurl+'" alt="image of card '+name+'" />'
        if not imgurl:
            img_element = '<span class="card-not-found">/<span>'
        name_and_link = ('<a class="'+get_card_colored(card)+'" href="#" onmouseover="loadImg(this);">'
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

        if print_rarity:
            rarity_fmt = '# {:>5}'
            rarity_part = rarity_fmt.format(card['rarity'] if 'rarity' in card else '')
            line += rarity_part + separator_colored
            line_visible_len += len(rarity_part + separator)

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
                    and not filter_lands(card)
                    and ('card_faces' not in card or not filter_lands(card['card_faces'][1]))):
                for feature, regexes in RAMP_CARDS_REGEX_BY_FEATURES.items():
                    regex = r'('+('|'.join(regexes))+')'
                    if list(search_strings(regex, oracle_texts_low)):
                        malus = 'no malus'
                        if feature in RAMP_CARDS_MALUS_REGEX:
                            for regexp in RAMP_CARDS_MALUS_REGEX[feature]:
                                reg = regexp.replace('<name>', card['name'])
                                if list(search_strings(reg, oracle_texts)):
                                    malus = 'malus'
                                    break
                        # special case for 'mana'
                        if feature == 'mana':
                            feature = 'mana colorless'
                            if list(search_strings(r'Add [^.]+ mana of any color', oracle_texts)):
                                feature = 'mana multicolored'
                            elif list(search_strings(r'Add \{[^C]\}', oracle_texts)):
                                feature = 'mana colored'
                        if feature not in cards_ramp_cards_by_features:
                            cards_ramp_cards_by_features[feature] = {}
                        if malus not in cards_ramp_cards_by_features[feature]:
                            cards_ramp_cards_by_features[feature][malus] = []
                        cards_ramp_cards_by_features[feature][malus].append(card)
                        cards_ramp_cards.append(card)

    for feature in cards_ramp_cards_by_features:
        cards_ramp_cards_by_features[feature] = dict(sorted(
            cards_ramp_cards_by_features[feature].items()))

    cards_ramp_cards_selected = []
    for cards_list_by_malus in cards_ramp_cards_by_features.values():
        for cards_list in cards_list_by_malus.values():
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
        for feature, cards_list_by_malus in cards_ramp_cards_by_features.items():
            for malus in ['no malus', 'malus']:
                if malus in cards_list_by_malus:
                    cards_list = cards_list_by_malus[malus]
                    cards_list_sorted = sort_cards_by_cmc_and_name(cards_list)
                    malus_text = ', with '+malus if malus == 'malus' else ''
                    title = 'Ramp cards ('+feature+malus_text+'): '+str(len(cards_list_sorted))
                    html += '    <article>'+'\n'
                    html += '      <details>'+'\n'
                    html += '        <summary>'+title+'</summary>'+'\n'
                    html += print_cards_list(cards_list_sorted, limit = max_list_items,
                                             outformat = outformat, return_str = True,
                                             card_feat = 'ramps')
                    html += '      </details>'+'\n'
                    html += '    </article>'+'\n'
        html += '  </section>'+'\n'
        print(html)

    if outformat == 'console':
        print('Ramp cards:', len(cards_ramp_cards))
        print('')
        for feature, cards_list_by_malus in cards_ramp_cards_by_features.items():
            for malus in ['no malus', 'malus']:
                if malus in cards_list_by_malus:
                    cards_list = cards_list_by_malus[malus]
                    cards_list_sorted = sort_cards_by_cmc_and_name(cards_list)
                    malus_text = ', with '+malus if malus == 'malus' else ''
                    print('   Ramp cards ('+feature+malus_text+'):', len(cards_list_sorted))
                    print('')
                    print_cards_list(cards_list_sorted, limit = max_list_items, indent = 6)
                    print('')

    return cards_ramp_cards_selected

def assist_draw_cards(cards, land_types_invalid_regex, max_list_items = None, outformat = 'console'):
    """Show pre-selected draw cards organised by features, for the user to select some"""

    cards_draw = []
    cards_draw_repeating = []
    cards_draw_multiple = []
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
                    cards_draw.append(card)

                    if (list(search_strings(r'(whenever|everytime|at begining|upkeep|\\{\w\\}:)',
                                           oracle_texts_low))
                            and not list(in_strings("next turn's upkeep", oracle_texts_low))
                            and not list(in_strings('Sacrifice '+card['name'], oracle_texts))
                            and not list(search_strings(
                                r'whenever [^.]+ deals combat damage to a player',
                                oracle_texts_low))):
                        cards_draw_repeating.append(card)

                    elif list(search_strings(r'draws? (two|three|four|five|six|seven|x) ',
                                             oracle_texts_low)):
                        cards_draw_multiple.append(card)
                    break
    cards_draw = list(sorted(cards_draw, key=lambda c: c['cmc']))

    cards_draw_not_repeating_cmc_3 = sort_cards_by_cmc_and_name(list(filter(
        lambda c: int(c['cmc']) <= 3,
        [c for c in cards_draw if c not in cards_draw_repeating
         and c not in cards_draw_multiple])))

    connives = list(filter(lambda c: bool(list(
        in_strings('connives', map(str.lower, get_oracle_texts(c))))), cards))

    draw_output_data = {
        'repeating': organize_by_type(cards_draw_repeating),
        'multiple': organize_by_type(cards_draw_multiple),
        'connives': organize_by_type(connives),
        'not repeating, CMC <= 3': organize_by_type(cards_draw_not_repeating_cmc_3)}

    draw_stat_data = {
        'Draw cards (total)': len(cards_draw)}
    for feature, cards_list_by_type in draw_output_data.items():
        for card_type, cards_list in cards_list_by_type.items():
            if cards_list:
                title = 'Draw cards ('+feature+', '+card_type+')'
                draw_stat_data[title] = len(cards_list)

    cards_draw_selected = []
    for cards_list_by_type in draw_output_data.values():
        for cards_list in cards_list_by_type.values():
            cards_draw_selected += sort_cards_by_cmc_and_name(cards_list)[:max_list_items]

    if outformat == 'html':
        html = ''
        html += '  <section>'+'\n'
        html += '    <h3 id="draw-cards">Draw cards</h3>\n'
        html += '    <h4>Stats</h4>'+'\n'
        html += '    <dl>'+'\n'
        for title, cards_count in draw_stat_data.items():
            html += '      <dt>'+title+'</dt>'+'\n'
            html += '      <dd>'+str(cards_count)+'</dd>'+'\n'
        html += '    </dl>'+'\n'
        html += '    <h4>Draw cards by feature</h4>'+'\n'
        for feature, cards_list_by_type in draw_output_data.items():
            title = 'Draw cards ('+feature+')'
            html += '    <article>'+'\n'
            html += '      <details>'+'\n'
            html += '        <summary>'+title+'</summary>'+'\n'
            for card_type, cards_list in cards_list_by_type.items():
                if cards_list:
                    title = 'Draw cards ('+feature+', '+card_type+'): '+str(len(cards_list))
                    html += '        <details>'+'\n'
                    html += '          <summary>'+title+'</summary>'+'\n'
                    html += print_cards_list(sort_cards_by_cmc_and_name(cards_list),
                                             limit = max_list_items, outformat = outformat,
                                             return_str = True, card_feat = 'draws')
                    html += '        </details>'+'\n'
            html += '      </details>'+'\n'
            html += '    </article>'+'\n'
        html += '  </section>'+'\n'
        print(html)

    if outformat == 'console':
        print('Draw cards:', len(cards_draw))
        print('')
        for feature, cards_list_by_type in draw_output_data.items():
            for card_type, cards_list in cards_list_by_type.items():
                if cards_list:
                    title = 'Draw cards ('+feature+', '+card_type+'): '+str(len(cards_list))
                    print(title)
                    print('')
                    print_cards_list(sort_cards_by_cmc_and_name(cards_list), limit = max_list_items,
                                    indent = 6, outformat = outformat)
                    print('')
        print('')

    return cards_draw_selected

def assist_tutor_cards(cards, land_types_invalid_regex, max_list_items = None, outformat='console'):
    """Show pre-selected tutor cards organised by features, for the user to select some"""

    cards_tutor = []
    for card in cards:
        if 'tutor' in card['name'].lower():
            cards_tutor.append(card)
        elif TUTOR_CARDS_REGEX:
            oracle_texts = list(get_oracle_texts(card))
            oracle_texts_low = list(map(str.lower, oracle_texts))
            card_found = False
            for regexp in TUTOR_CARDS_REGEX:
                if (list(search_strings(regexp, oracle_texts_low))
                        and not list(search_strings(TUTOR_CARDS_EXCLUDE_REGEX, oracle_texts_low))
                        and not list(search_strings(land_types_invalid_regex, oracle_texts_low))
                        and not filter_lands(card)):
                    cards_tutor.append(card)
                    card_found = True
                    break
            if not card_found and TUTOR_CARDS_JOIN_TEXTS_REGEX:
                for regexp in TUTOR_CARDS_JOIN_TEXTS_REGEX:
                    if (re.search(regexp, join_oracle_texts(card).lower())
                            and not list(search_strings(TUTOR_CARDS_EXCLUDE_REGEX, oracle_texts_low))
                            and not list(search_strings(land_types_invalid_regex, oracle_texts_low))
                            and not filter_lands(card)):
                        cards_tutor.append(card)
                        card_found = True
                        break

    # filter out not generic enough cards
    cards_tutor_generic = list(filter(
        lambda c: (not list(search_strings(TUTOR_GENERIC_EXCLUDE_REGEX,
                                          map(str.lower, get_oracle_texts(c))))
                   or (re.search(TUTOR_GENERIC_EXCLUDE_REGEX, c['name'].lower())
                       and list(in_strings('When '+c['name']+' enters the battlefield',
                                           get_oracle_texts(c))))),
        cards_tutor))

    # regroup some cards by theme
    cards_tutor_against = list(filter(
        lambda c: (list(in_strings_excludes(
                        'opponent',
                        ['opponent choose', 'choose an opponent', 'opponent gains control',
                         'opponent looks at'],
                        map(str.lower, get_oracle_texts(c))))
                   or list(in_strings('counter target', map(str.lower, get_oracle_texts(c))))
                   or list(in_strings('destroy', map(str.lower, get_oracle_texts(c))))),
        cards_tutor_generic))
    cards_tutor_aura = list(filter(
        lambda c: list(in_strings_exclude('Aura', 'Auramancers', get_oracle_texts(c))),
        cards_tutor_generic))
    cards_tutor_equipment = list(filter(
        lambda c: list(in_strings('Equipment', get_oracle_texts(c))),
        cards_tutor_generic))
    cards_tutor_artifact = list(filter(
        lambda c: list(in_strings_excludes(
            'artifact', ['artifact and/or', 'artifact or', 'artifact, creature'],
            map(str.lower, get_oracle_texts(c)))),
        [c for c in cards_tutor_generic if c not in cards_tutor_equipment]))
    cards_tutor_transmute = list(filter(
        lambda c: list(in_strings('transmute', map(str.lower, get_oracle_texts(c)))),
        [c for c in cards_tutor_generic if c not in cards_tutor_equipment]))
    cards_tutor_graveyard = list(filter(
        lambda c: c['name'] != 'Dark Petition' and list(in_strings_excludes(
            'graveyard', ["if you don't, put it into", 'graveyard from play',
                          'the other into your graveyard', 'cast from a graveyard'],
            map(str.lower, get_oracle_texts(c)))),
        cards_tutor_generic))

    cards_tutor_themed = (
            cards_tutor_against
            + cards_tutor_aura
            + cards_tutor_equipment
            + cards_tutor_artifact
            + cards_tutor_transmute
            + cards_tutor_graveyard)
    cards_tutor_not_themed = [
        c for c in cards_tutor_generic if c not in cards_tutor_themed]

    cards_tutor_to_battlefield = list(filter(
        lambda c: list(in_strings('onto the battlefield', map(str.lower, get_oracle_texts(c)))),
        cards_tutor_not_themed))
    cards_tutor_to_hand = list(filter(
        lambda c: list(in_strings('hand', map(str.lower, get_oracle_texts(c)))),
        [c for c in cards_tutor_not_themed if c not in cards_tutor_to_battlefield]))
    cards_tutor_to_top_library = list(filter(
        lambda c: (list(in_strings('that card on top', map(str.lower, get_oracle_texts(c))))
                   or list(in_strings('third from the top', map(str.lower, get_oracle_texts(c))))),
        [c for c in cards_tutor_not_themed if c not in cards_tutor_to_battlefield
         and c not in cards_tutor_to_hand]))
    cards_tutor_other = [
        c for c in cards_tutor_not_themed if c not in cards_tutor_to_battlefield
        and c not in cards_tutor_to_hand and c not in cards_tutor_to_top_library]

    tutor_stats_data = {
        'Tutor cards': len(cards_tutor),
        'Tutor cards (not generic enough)':
            len(cards_tutor) - len(cards_tutor_generic),
        'Tutor cards (not themed)': len(cards_tutor_not_themed),
        'Tutor cards (not themed, to battlefield)': len(cards_tutor_to_battlefield),
        'Tutor cards (not themed, to hand)': len(cards_tutor_to_hand),
        'Tutor cards (not themed, to top of library)': len(cards_tutor_to_top_library),
        'Tutor cards (not themed, other)': len(cards_tutor_other),
        'Tutor cards (themed)': len(cards_tutor_themed),
        'Tutor cards (themed, against)': len(cards_tutor_against),
        'Tutor cards (themed, transmute)': len(cards_tutor_transmute),
        'Tutor cards (themed, artifact)': len(cards_tutor_artifact),
        'Tutor cards (themed, graveyard)': len(cards_tutor_graveyard),
        'Tutor cards (themed, Equipment)': len(cards_tutor_equipment),
        'Tutor cards (themed, Aura)': len(cards_tutor_aura)}

    tutor_output_data = {
        'Tutor cards (not themed)': {
            'Tutor cards (not themed, to battlefield)': cards_tutor_to_battlefield,
            'Tutor cards (not themed, to hand)': cards_tutor_to_hand,
            'Tutor cards (not themed, to top of library)': cards_tutor_to_top_library,
            'Tutor cards (not themed, other)': cards_tutor_other},
        'Tutor cards (themed)': {
            'Tutor cards (themed, against)': cards_tutor_against,
            'Tutor cards (themed, transmute)': cards_tutor_transmute,
            'Tutor cards (themed, artifact)': cards_tutor_artifact,
            'Tutor cards (themed, graveyard)': cards_tutor_graveyard,
            'Tutor cards (themed, Equipment)': cards_tutor_equipment,
            'Tutor cards (themed, Aura)': cards_tutor_aura}}

    cards_tutor_selected = []
    for data in tutor_output_data.values():
        for cards_list in data.values():
            cards_tutor_selected += sort_cards_by_cmc_and_name(cards_list)[:max_list_items]

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
                                         limit = max_list_items, outformat = outformat,
                                         return_str = True, card_feat = 'tutors')
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
            print('')
            for title, cards_list in data.items():
                print('   '+title+':', len(cards_list))
                print('')
                print_cards_list(sort_cards_by_cmc_and_name(cards_list), limit = max_list_items,
                                 indent = 6, outformat = outformat)
                print('')
        print('')

    return cards_tutor_selected

def assist_removal_cards(cards, max_list_items = None, outformat = 'console'):
    """Show pre-selected removal cards organised by features, for the user to select some"""

    cards_removal_selected = []
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

    cards_removal_selected = []
    for data in removal_output_data.values():
        for cards_list in data.values():
            cards_removal_selected += sort_cards_by_cmc_and_name(cards_list)[:max_list_items]

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
                                         limit = max_list_items, outformat = outformat,
                                         return_str = True, card_feat = 'removal')
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
            print('')
            for title, cards_list in data.items():
                print('   '+title+':', len(cards_list))
                print('')
                print_cards_list(sort_cards_by_cmc_and_name(cards_list), limit = max_list_items,
                                 indent = 6, outformat = outformat)
                print('')
        print('')

    return cards_removal_selected

def assist_disabling_cards(cards, max_list_items = None, outformat = 'console'):
    """Show pre-selected disabling cards organised by features, for the user to select some"""

    cards_disabling_selected = []
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

    cards_disabling_selected = []
    for data in disabling_output_data.values():
        for cards_list in data.values():
            cards_disabling_selected += sort_cards_by_cmc_and_name(cards_list)[:max_list_items]

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
                                         limit = max_list_items, outformat = outformat,
                                         return_str = True, card_feat = 'disabling')
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
            print('')
            for title, cards_list in data.items():
                print('   '+title+':', len(cards_list))
                print('')
                print_cards_list(sort_cards_by_cmc_and_name(cards_list), limit = max_list_items,
                                 indent = 6, outformat = outformat)
                print('')
        print('')

    return cards_disabling_selected

def assist_wipe_cards(cards, max_list_items = None, outformat = 'console'):
    """Show pre-selected board wipe cards organised by features, for the user to select some"""

    no_feature = 'not selective'
    cards_wipe_by_feature = {}
    if WIPE_CARDS_REGEX:
        for card in cards:
            oracle_texts = list(get_oracle_texts(card))
            oracle_texts_low = list(map(str.lower, oracle_texts))
            for regexp in WIPE_CARDS_REGEX:
                if (list(search_strings(regexp, oracle_texts_low))
                        and not list(search_strings(WIPE_CARDS_EXCLUDE_REGEX,
                                                    oracle_texts_low))):
                    card_added = False
                    for feature, regexes in WIPE_CARDS_BY_FEATURE_REGEX.items():
                        for reg in regexes:
                            if list(search_strings(reg, oracle_texts_low)):
                                if feature not in cards_wipe_by_feature:
                                    cards_wipe_by_feature[feature] = []
                                cards_wipe_by_feature[feature].append(card)
                                card_added = True
                                break
                    if not card_added:
                        if no_feature not in cards_wipe_by_feature:
                            cards_wipe_by_feature[no_feature] = []
                        cards_wipe_by_feature[no_feature].append(card)
                    break

    cards_wipe_selected = []
    for feature in cards_wipe_by_feature:
        cards_wipe_by_feature[feature] = sort_cards_by_cmc_and_name(cards_wipe_by_feature[feature])
        cards_wipe_selected += cards_wipe_by_feature[feature][:max_list_items]

    features = cards_wipe_by_feature.keys()
    features_sorted = tuple(('only affect opponent', no_feature,
                             *(sorted(set(features) - {'only affect opponent', no_feature}))))

    if outformat == 'html':
        html = ''
        html += '  <section>'+'\n'
        html += '    <h3 id="wipe-cards">Board wipe cards</h3>\n'
        for feature in features_sorted:
            cards_list = cards_wipe_by_feature[feature]
            title = 'Board wipe cards ('+feature+'): '+str(len(cards_list))
            html += '    <article>'+'\n'
            html += '      <details>'+'\n'
            html += '        <summary>'+title+'</summary>'+'\n'
            html += print_cards_list(cards_list, limit = max_list_items,
                                     outformat = outformat, return_str = True, card_feat = 'wipe')
            html += '      </details>'+'\n'
            html += '    </article>'+'\n'
        html += '  </section>'+'\n'
        print(html)

    if outformat == 'console':
        for feature in features_sorted:
            cards_list = cards_wipe_by_feature[feature]
            title = 'Board wipe cards ('+feature+'): '+str(len(cards_list))
            print(title)
            print('')
            print_cards_list(cards_list, limit = max_list_items, indent = 3,
                             outformat = outformat)
            print('')

    return cards_wipe_selected

def assist_no_pay_cards(cards, max_list_items = None, outformat = 'console'):
    """Show pre-selected cards that allow to play without paying mana cost organised by features,
       for the user to select some"""

    cards_no_pay = {}
    if NO_PAY_CARDS_REGEX:
        print('DEBUG Analysing no pay card ...', file=sys.stderr)
        previous_exile = []
        for card in cards:
            oracle_texts = list(get_oracle_texts(card))
            oracle_texts_low = list(map(str.lower, oracle_texts))
            for source, regexes in NO_PAY_CARDS_REGEX.items():
                for regexp in regexes:
                    if (list(search_strings(regexp, oracle_texts_low))
                            and not list(search_strings(NO_PAY_CARDS_EXCLUDE_REGEX,
                                                        oracle_texts_low))):
                        if source == 'exile, other' and card in previous_exile:
                            continue
                        if source not in cards_no_pay:
                            cards_no_pay[source] = []
                        cards_no_pay[source].append(card)
                        if source != 'exile, other':
                            previous_exile.append(card)
                        break

    no_pay_stats_data = {'No pay cards (total)': sum(map(len, cards_no_pay.values()))}
    no_pay_output_data = {'No pay cards by source': {}}
    cards_no_pay_keys = list(NO_PAY_CARDS_REGEX.keys())
    for source in cards_no_pay_keys:
        if source in cards_no_pay:
            cards_list = cards_no_pay[source]
            title = 'No pay cards ('+source+')'
            no_pay_stats_data[title] = len(cards_list)
            no_pay_output_data['No pay cards by source'][title] = sort_cards_by_cmc_and_name(
                cards_list)
            if source == 'exile, suspend':
                no_pay_output_data['No pay cards by source'][title].reverse()

    cards_no_pay_selected = []
    for data in no_pay_output_data.values():
        for cards_list in data.values():
            cards_no_pay_selected += cards_list[:max_list_items]

    if outformat == 'html':
        html = ''
        html += '  <section>'+'\n'
        html += '    <h3 id="no-pay-cards">No pay cards</h3>\n'
        html += '    <h4>Stats</h4>'+'\n'
        html += '    <dl>'+'\n'
        for title, count in no_pay_stats_data.items():
            html += '      <dt>'+title+'</dt>'+'\n'
            html += '      <dd>'+str(count)+'</dd>'+'\n'
        html += '    </dl>'+'\n'
        for section, data in no_pay_output_data.items():
            html += '    <h4>'+section+'</h4>'+'\n'
            for title, cards_list in data.items():
                title += ': '+str(len(cards_list))
                html += '    <article>'+'\n'
                html += '      <details>'+'\n'
                html += '        <summary>'+title+'</summary>'+'\n'
                html += print_cards_list(cards_list, limit = max_list_items, outformat = outformat,
                                         return_str = True, card_feat = 'no-pay')
                html += '      </details>'+'\n'
                html += '    </article>'+'\n'
        html += '  </section>'+'\n'
        print(html)

    if outformat == 'console':
        for title, count in no_pay_stats_data.items():
            print(title+':', count)
        print('')
        for section, data in no_pay_output_data.items():
            print(section)
            print('')
            for title, cards_list in data.items():
                print('   '+title+':', len(cards_list))
                print('')
                print_cards_list(sort_cards_by_cmc_and_name(cards_list), limit = max_list_items,
                                 indent = 6, outformat = outformat)
                print('')
        print('')

    return cards_no_pay_selected

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

    cards_grav_recur_selected = []
    for data in grav_recur_output_data.values():
        for cards_list in data.values():
            cards_grav_recur_selected += sort_cards_by_cmc_and_name(cards_list)[:max_list_items]

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
                                         limit = max_list_items, outformat = outformat,
                                         return_str = True, card_feat = 'graveyard-recursion')
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
            print('')
            for title, cards_list in data.items():
                print('   '+title+':', len(cards_list))
                print('')
                print_cards_list(sort_cards_by_cmc_and_name(cards_list), limit = max_list_items,
                                 indent = 6, outformat = outformat)
                print('')
        print('')

    return cards_grav_recur_selected

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

    cards_grav_hate_selected = []
    for data in grav_hate_output_data.values():
        for cards_list in data.values():
            cards_grav_hate_selected += sort_cards_by_cmc_and_name(cards_list)[:max_list_items]

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
                                         limit = max_list_items, outformat = outformat,
                                         return_str = True, card_feat = 'graveyard-hate')
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
            print('')
            for title, cards_list in data.items():
                print('   '+title+':', len(cards_list))
                print('')
                print_cards_list(sort_cards_by_cmc_and_name(cards_list), limit = max_list_items,
                                 indent = 6, outformat = outformat)
                print('')
        print('')

    return cards_grav_hate_selected

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

    copy_cards_selected = []
    for data in copy_output_data.values():
        for cards_list in data.values():
            copy_cards_selected += sort_cards_by_cmc_and_name(cards_list)[:max_list_items]

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
                                         limit = max_list_items, outformat = outformat,
                                         return_str = True, card_feat = 'copy')
                html += '      </details>'+'\n'
                html += '    </article>'+'\n'
        html += '  </section>'+'\n'
        print(html)

    if outformat == 'console':
        for title, count in copy_stats_data.items():
            print(title+':', count)
        print('')
        print('')
        for section, data in copy_output_data.items():
            print(section)
            print('')
            for title, cards_list in data.items():
                print('   '+title+':', len(cards_list))
                print('')
                print_cards_list(sort_cards_by_cmc_and_name(cards_list), limit = max_list_items,
                                 indent = 6, outformat = outformat)
        print('')

    return copy_cards_selected

def assist_creature_effects(cards, max_list_items = None, outformat = 'console'):
    """Show pre-selected creature effects cards organised by features, for the user to select some"""

    features = {
        'Double strike': 'double strike',
        'First strike': 'first strike',
        'Indestructible': 'indestructible',
        'Deathtouch': 'deathtouch',
        'Trample': 'trample',
        'Flying': 'flying',
        'Reach': 'reach',
        'Vigilance': 'vigilance',
        'Haste': 'haste',
        '+X/+X': r'\+[0-9]?[0-9x]/\+[0-9]?[0-9x]',
        '-X/-X': '-[0-9]?[0-9x]/-[0-9]?[0-9x]',
        'Regenerate': (r'regenerate|"(\{\w+\}|remove [^.]+ counter( from this creature)?): '
                       r'regenerate this creature\."'),
        #'Evade blocking': "menace|intimidate|skulk|fear( |[,.])|can be blocked only by|can't be blocked except by",
        'Protection from spell': 'hexproof|ward|shroud',
        'Counters': '[^.]+ counter',
        'Prevent damage': 'prevent [^.]*damage',
        'Flanking': 'flanking',
        'Backup': 'backup',
        'other': '.+'}

    target_regexes = {
        'yours, improvments': (r'([:,.]\s*|''\n'r'\s*|(all|each|every|other|attacking|blocking) )'
                               'creatures you control (gains?|gets?|have|has)'),
        "opponent's, affections": (r'([:,.\s*]|''\n'r'\s*|(all|each|every|other|attacking|blocking) )'
                                   'creatures '+PLAYER_REGEXP.replace('you|', '')
                                   +' control (loses?|gets?|have|has)'),
        'target, improvments': '((this|that|enchanted|equipped|target( [^.]+)?) )?creature( [^.]+)? (gains?|gets?|have|has)',
        'target, affection': '(this|(that|enchanted|equipped|target( [^.]+)?) )?creature( [^.]+)? loses?'}

    exclude_prefixes = [
        r'enters the battlefield( under your control|, if it was kicked)?(,\s*)?',
        r'and at least two other creatures attack(,\s*)?',
        r'this ability has resolved this turn(,\s*)?',
        r'if creatures you control have [^.]+(,\s*)?',
        r'as long as you have [^.]+ life(,\s*)?',
        r'as long as [^.]+ has [^.]+ counters on it(,\s*)?',
        '(sacrifice|discard) [^.]+:',
        r'whenever you cast an? [^.]*spell [^.]*(,\s*)?',
        r'is dealt (noncombat|[^.]+) damage(,\s*)?',
        'attacks while you control a creature with power [^.]+',
        r'whenever [^.]+ blocks or becomes blocked by a creature this combat(,\s*)?',
        r'tap [^.]+ you control:',
        ]

    other_excludes = [
        r'becomes [^.]+ creature and loses?',
        'creature [^.]*('+PLAYER_REGEXP+'|and|player) loses? [^.]*life',
        'each opponent dealt combat damage this game by a creature named [^.]+ loses? [^.]*life',
        'loses? all other card types and creature types',
        'flip a coin until you lose a flip',
        ]

    target_excludes = [
        'whenever a creature an opponent controls dies, [^.]+ gets',
        'whenever you sacrifice a permanent, [^.]+ gets',
        "creature has first strike as long as it's blocking or blocked by",
        'target dwarf creature gets ',
        'target snow creature gains',
        'if that creature has power [^.]+, it gains',
        'whenever [^.]+ blocks a creature [^.]+, [^.]+ gets',
        'if you control [^.]+ snow permanents, the creature you control gets',
        "noncreature artifacts you control( can't be enchanted, they)? have indestructible",
        'target creature with power 5 or greater gains',
        'if mana from a treasure was spent to activate this ability, that creature also gains',
        'whenever equipped creature becomes blocked by one or more colorless creatures, it gains',
        'whenever you cast an artifact spell, you may have target creature get',
        'when [^.]+ enters the battlefield, another target creature you control gains',
        'whenever another creature enters the battlefield under your control, [^.]+ gains',
        'whenever a land enters the battlefield under your control, choose one',
        ('if there are [^.]+ creature cards in your graveyard, [^.]+ target creature you control'
            '( and it)? gains'),
        # 'creature has [^.]+ as long as you control [^.]+', # too broad
        'target goblin creature( you control)? (gains|gets|have|has)',
        "sacrifice [^.]+: up to one target creature you( don't)? control gets",
        'when [^.]+ dies, target creature( an opponent controls)? gets',
        'when [^.]+ enters the battlefield, you may have target creature get',
        'when [^.]+ dies, choose one',
        'target creature with flying gets',
        ("whenever this creature mutates, target creature( an opponent controls| you don't control)"
         '? gets'),
        'creature tokens get',
        'enchant creature card in a graveyard',
        'when you do, target creature( '+PLAYER_REGEXP+' controls)? gets',
        ]

    counters_excludes = [
        'shadow counter',
        'as long as a creature (have|has) [^.]+ counter on it',
        'players dealt combat damage by this creature also get [^.]+ poison counter',
        # infect
        ('this creature deals damage to creatures in the form of -1/-1 counters and to players in '
         'the form of poison counters'),
        # corrupted
        '(have|has) three or more poison counters',
        # ward
        ('whenever (this|equipped) creature becomes the target of a spell or ability an opponent '
         'controls, counter it unless that player pays'),
        # ('whenever a creature you control with deathtouch deals combat damage to a player, that '
        #  'player gets two poison counters'),
        ('whenever this creature deals damage to a player, that player gets a poison counter'),
        # evolve
        ('whenever a creature enters the battlefield under your control, if that creature has '
         r'greater power or toughness than this creature, put a \+1/\+1 counter on this creature'),
        # adapt
        (r'if this creature has no \+1/\+1 counters on it, put [^.]+ \+1/\+1 counters on it'),
        ]

    plus_x_counters_regex = '(this|that|enchanted|equipped|target) creature (gains?|gets?|have|has)'

    plus_x_excludes = [
        # bloodthirst
        ('if an opponent was dealt damage this turn, this creature enters the battlefield with a '
         r'\+1/\+1 counter on it\.'),
        ]

    minus_x_excludes = [
        # flanking
        ('whenever a creature without flanking blocks this creature, the blocking creature gets '
         r'-1/-1 until end of turn\.'),
        ]

    cards_creature_effects = {}
    for card in cards:

        # skip instants and sorceries
        # TODO only skip relevant face
        # TODO do not exclude instant or sorcery that puts counter on card ('Heightened Reflexes')
        skip = False
        if 'card_faces' in card:
            for face in card['card_faces']:
                if 'type_line' in face and face['type_line'] in ['Instant', 'Sorcery']:
                    skip = True
                    break
        elif 'type_line' in card and card['type_line'] in ['Instant', 'Sorcery']:
            skip = True
        if skip:
            continue

        oracle_texts = get_oracle_texts(card)
        oracle_texts_low = list(map(str.lower, oracle_texts))

        added = False
        skipped_for_target = {}
        for feature, feature_regex in features.items():
            for target, target_regex in target_regexes.items():
                if target not in skipped_for_target:
                    skipped_for_target[target] = False
                # TODO handle those with two features
                # obtain = '(gains?|gets?|have|has)'
                # if 'loses?' in target_regex:
                #     obtain = 'loses?'
                # regex = target_regex+' ([^.]+ and '+obtain+' )?('+feature_regex+')'
                regex = target_regex+' ('+feature_regex+')'
                exclude_regex = '('+('|'.join(exclude_prefixes))+r')\s*'+regex
                if (list(search_strings(regex, oracle_texts_low))
                        and not list(search_strings(exclude_regex, oracle_texts_low))):
                    skip = False
                    if target.startswith('target'):
                        for exc_regex in target_excludes:
                            if list(search_strings(exc_regex, oracle_texts_low)):
                                skip = True
                                break
                        if feature == '+X/+X':
                            if not list(search_strings(plus_x_counters_regex, oracle_texts_low)):
                                skip = True
                            else:
                                for exc_regex in plus_x_excludes:
                                    if list(search_strings(exc_regex, oracle_texts_low)):
                                        skip = True
                                        break
                        elif feature == '-X/-X':
                            for exc_regex in minus_x_excludes:
                                if list(search_strings(exc_regex, oracle_texts_low)):
                                    skip = True
                                    break
                        elif feature == 'Counters':
                            for exc_regex in counters_excludes:
                                if list(search_strings(exc_regex, oracle_texts_low)):
                                    skip = True
                                    break
                    if not skip and feature == 'other' and not skipped_for_target[target]:
                        for exc_regex in other_excludes:
                            if list(search_strings(exc_regex, oracle_texts_low)):
                                skip = True
                                break
                    if skip:
                        skipped_for_target[target] = True
                        continue
                    if target not in cards_creature_effects:
                        cards_creature_effects[target] = {}
                    if feature not in cards_creature_effects[target]:
                        cards_creature_effects[target][feature] = []
                    if not added or feature != 'other':
                        cards_creature_effects[target][feature].append(card)
                        added = True
                        break

    creature_effects_stats_data = {}
    creature_effects_output_data = {}
    cards_creature_effects_selected = []
    for target in target_regexes:
        if target in cards_creature_effects:
            cards_list_by_feature = cards_creature_effects[target]
            for feature in features:
                if feature in cards_list_by_feature:
                    cards_list = cards_list_by_feature[feature]
                    section = 'Creature effects ('+target+')'
                    title = 'Creature effects ('+target+', '+feature+')'
                    cards_list_sorted = sort_cards_by_cmc_and_name(cards_list)
                    if section not in creature_effects_output_data:
                        creature_effects_output_data[section] = {}
                    creature_effects_output_data[section][title] = cards_list_sorted
                    creature_effects_stats_data[title] = len(cards_list)
                    cards_creature_effects_selected += cards_list_sorted[:max_list_items]

    if outformat == 'html':
        html = ''
        html += '  <section>'+'\n'
        html += '    <h3 id="creature-effects-cards">Creature effects cards</h3>\n'
        html += '    <h4>Stats</h4>'+'\n'
        html += '    <dl>'+'\n'
        for title, count in creature_effects_stats_data.items():
            html += '      <dt>'+title+'</dt>'+'\n'
            html += '      <dd>'+str(count)+'</dd>'+'\n'
        html += '    </dl>'+'\n'
        for section, data in creature_effects_output_data.items():
            html += '    <h4>'+section+'</h4>'+'\n'
            for title, cards_list in data.items():
                title += ': '+str(len(cards_list))
                html += '    <article>'+'\n'
                html += '      <details>'+'\n'
                html += '        <summary>'+title+'</summary>'+'\n'
                html += print_cards_list(sort_cards_by_cmc_and_name(cards_list),
                                         limit = max_list_items, outformat = outformat,
                                         return_str = True, card_feat = 'creature-effects')
                html += '      </details>'+'\n'
                html += '    </article>'+'\n'
        html += '  </section>'+'\n'
        print(html)

    if outformat == 'console':
        for title, count in creature_effects_stats_data.items():
            print(title+':', count)
        print('')
        for section, data in creature_effects_output_data.items():
            print(section)
            print('')
            for title, cards_list in data.items():
                print('   '+title+':', len(cards_list))
                print('')
                print_cards_list(sort_cards_by_cmc_and_name(cards_list), limit = max_list_items,
                                 indent = 6, outformat = outformat)
                print('')
        print('')

    return cards_creature_effects_selected

def assist_best_creature_cards(cards, max_list_items = None, outformat = 'console'):
    """Show pre-selected best cards organised by features, for the user to select some"""

    print('DEBUG Analysing best creatures cards (power+toughness to CMC ratio, and more) ...',
          file=sys.stderr)
    best_creature_cards_selected = []

    # Best creature power and toughness to cmc
    powr_tough_to_cmc = {}
    for card in cards:
        faces = [card]
        if 'card_faces' in card:
            faces = card['card_faces']

        for face in faces:
            if ('toughness' in face and 'cmc' in face and '*' not in face['toughness']
                    and 'power' in face and 'cmc' in face and '*' not in face['power']
                    and 'type_line' in face and 'Vehicle' not in face['type_line']):
                power = float(face['power'])
                toughness = float(face['toughness'])
                cmc = float(face['cmc']) if float(face['cmc']) > 1 else 1.0
                ratio = round((power + toughness) / cmc, 3)

                face_text = face['oracle_text'] if 'oracle_text' in face else ''

                feature = 'no feature'
                if 'keywords' in face:
                    if 'Double strike' in face['keywords']:
                        feature = 'Double strike'
                    elif 'First strike' in face['keywords']:
                        feature = 'First strike'
                    elif 'Flying' in face['keywords']:
                        feature = 'Flying'
                    # TODO evasion cards (except flying)

                defender = ('Defender' if bool(re.search('(^|[,.] )Defender', face_text))
                            else 'not Defender')

                malus = 'no malus'
                if face_text:
                    for regexp in CREATURE_MALUS_REGEXES:
                        reg = regexp.replace('<name>', face['name'])
                        if bool(re.search(reg, face_text)):
                            malus = 'malus'
                            break

                if feature == 'no feature':
                    if defender != 'Defender':
                        if 'power' in face and float(face['power']) <= 3:
                            feature += ', (power <= 3)'
                        elif 'power' in face and float(face['power']) > 3:
                            feature += ', (power > 3)'
                    if defender == 'Defender':
                        if 'toughness' in face and float(face['toughness']) <= 3:
                            feature += ', (toughness <= 3)'
                        elif 'toughness' in face and float(face['toughness']) > 3:
                            feature += ', (toughness > 3)'

                if feature not in powr_tough_to_cmc:
                    powr_tough_to_cmc[feature] = {}

                if malus not in powr_tough_to_cmc[feature]:
                    powr_tough_to_cmc[feature][malus] = {}

                if defender not in powr_tough_to_cmc[feature][malus]:
                    powr_tough_to_cmc[feature][malus][defender] = {}

                if ratio not in powr_tough_to_cmc[feature][malus][defender]:
                    powr_tough_to_cmc[feature][malus][defender][ratio] = []

                if card not in powr_tough_to_cmc[feature][malus][defender][ratio]:
                    powr_tough_to_cmc[feature][malus][defender][ratio].append(card)

    powr_tough_to_cmc_ratio2 = {}
    features = powr_tough_to_cmc.keys()
    for feature in features:
        if ('no malus' in powr_tough_to_cmc[feature]
                and 'not Defender' in powr_tough_to_cmc[feature]['no malus']):
            for ratio, cards_list in powr_tough_to_cmc[feature]['no malus']['not Defender'].items():
                if ratio == 2.0:
                    for card in cards_list:
                        faces = [card]
                        if 'card_faces' in card:
                            faces = card['card_faces']
                        for face in faces:
                            power = float(face['power'])
                            if power == 0.0:
                                continue
                            keywords = len(face['keywords'])
                            if power not in powr_tough_to_cmc_ratio2:
                                powr_tough_to_cmc_ratio2[power] = {}
                            if keywords not in powr_tough_to_cmc_ratio2[power]:
                                powr_tough_to_cmc_ratio2[power][keywords] = []
                            if card not in powr_tough_to_cmc_ratio2[power][keywords]:
                                powr_tough_to_cmc_ratio2[power][keywords].append(card)

    powers = powr_tough_to_cmc_ratio2.keys()
    for power in powers:
        for keywords in powr_tough_to_cmc_ratio2[power]:
            powr_tough_to_cmc_ratio2[power][keywords] = sort_cards_by_cmc_and_name(
                powr_tough_to_cmc_ratio2[power][keywords])
        powr_tough_to_cmc_ratio2[power] = dict(sorted(
            powr_tough_to_cmc_ratio2[power].items(), reverse = True))
    powr_tough_to_cmc_ratio2 = dict(sorted(powr_tough_to_cmc_ratio2.items(), reverse = True))

    for feature in features:
        for malus in powr_tough_to_cmc[feature]:
            for defender in powr_tough_to_cmc[feature][malus]:
                for ratio in powr_tough_to_cmc[feature][malus][defender]:
                    powr_tough_to_cmc[feature][malus][defender][ratio] = sort_cards_by_cmc_and_name(
                        powr_tough_to_cmc[feature][malus][defender][ratio])
                powr_tough_to_cmc[feature][malus][defender] = dict(sorted(
                    powr_tough_to_cmc[feature][malus][defender].items(), reverse = True))
            powr_tough_to_cmc[feature][malus] = dict(sorted(
                powr_tough_to_cmc[feature][malus].items(), reverse = True))
        powr_tough_to_cmc[feature] = dict(sorted(
            powr_tough_to_cmc[feature].items(), reverse = True))
    powr_tough_to_cmc = dict(sorted(powr_tough_to_cmc.items()))

    # Best creature amount of (evergreen?) keywords by cmc
    keywords_to_cmc = {}
    for card in cards:
        if 'card_faces' in card:
            for face in card['card_faces']:
                if ('keywords' in face and face['keywords'] and 'cmc' in face
                        and 'type_line' in face and 'Vehicle' not in face['type_line']):
                    keywords = len(face['keywords'])
                    cmc = float(face['cmc']) if float(face['cmc']) > 1 else 1.0
                    ratio = round((keywords) / cmc, 3)
                    if ratio not in keywords_to_cmc:
                        keywords_to_cmc[ratio] = []
                    keywords_to_cmc[ratio].append(card)
        else:
            if ('keywords' in card and card['keywords'] and 'cmc' in card
                    and 'type_line' in card and 'Vehicle' not in card['type_line']):
                keywords = len(card['keywords'])
                cmc = float(card['cmc']) if float(card['cmc']) > 1 else 1.0
                ratio = round(keywords / cmc, 3)
                if ratio not in keywords_to_cmc:
                    keywords_to_cmc[ratio] = []
                keywords_to_cmc[ratio].append(card)
    keywords_to_cmc = dict(sorted(keywords_to_cmc.items(), reverse = True))

    # Best creature with first|double strike and deathtouch
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

    # Best creature with deathtouch
    deathtouch = []
    for card in cards:
        if 'card_faces' in card:
            for face in card['card_faces']:
                if 'keywords' in face and 'Deathtouch' in face['keywords']:
                    deathtouch.append(card)
        else:
            if 'keywords' in card and 'Deathtouch' in card['keywords']:
                deathtouch.append(card)

    best_creature_cards_output_data = {}
    for feature, cards_by_malus in powr_tough_to_cmc.items():
        for malus, cards_by_defender in cards_by_malus.items():
            for defender, cards_by_ratio in cards_by_defender.items():
                if not cards_by_ratio or (
                        feature in ['Double strike', 'First strike'] and defender == 'Defender'):
                    continue
                feat_text = feature.replace('no feature, ', '')+' '
                min_ratio = 2
                if feature in ['Double strike', 'First strike']:
                    min_ratio = 0.5
                title = ('Best '+feat_text+'power+toughness to CMC ratio '
                         '('+malus+', '+defender+', ratio > '+str(min_ratio)+')')
                best_creature_cards_output_data[title] = {'min_ratio': min_ratio,
                                                          'ratio:cards': cards_by_ratio}

    best_creature_cards_output_data |= {
        'Best power+toughness to CMC ratio (no malus, not Defender, ratio = 2)': {
            'strengh:cards': powr_tough_to_cmc_ratio2},
        'Best keywords count to CMC ratio (count ratio > 1)': {
            'min_ratio': 1,
            'ratio:cards': keywords_to_cmc},
        'Best Deathtouch + First strike/Double strike': {
            'cards': deathtouch_strike},
        'Best Deathtouch + Flying': {
            'cards': deathtouch_flying},
        'Best Deathtouch': {
            'cards': deathtouch},
    }

    for data in best_creature_cards_output_data.values():
        if 'ratio:cards' in data:
            min_ratio = data['min_ratio'] if 'min_ratio' in data else 0
            for ratio, cards_list in data['ratio:cards'].items():
                if ratio <= min_ratio:
                    break
                best_creature_cards_selected += sort_cards_by_cmc_and_name(cards_list)[:max_list_items]
        if 'cards' in data:
            best_creature_cards_selected += sort_cards_by_cmc_and_name(data['cards'])[:max_list_items]
        if 'strengh:cards' in data:
            for power, cards_list_by_keywords in data['strengh:cards'].items():
                for keywords, cards_list in cards_list_by_keywords.items():
                    best_creature_cards_selected += sort_cards_by_cmc_and_name(cards_list)[:max_list_items]

    if outformat == 'html':
        html = ''
        html += '  <section>'+'\n'
        html += '    <h3 id="best-creature-cards">Best creature cards</h3>\n'
        for title, data in best_creature_cards_output_data.items():
            html += '    <article>'+'\n'
            html += '      <details>'+'\n'
            html += '        <summary>'+title+'</summary>'+'\n'
            if 'ratio:cards' in data:
                min_ratio = data['min_ratio'] if 'min_ratio' in data else 0
                for ratio, cards_list in data['ratio:cards'].items():
                    if ratio <= min_ratio:
                        break
                    html += '      <h5 class="ratio">ratio '+str(ratio)+'</h5>'+'\n'
                    html += print_cards_list(sort_cards_by_cmc_and_name(cards_list),
                                             limit=max_list_items, outformat = outformat,
                                             return_str = True, card_feat = 'best-creature')
            if 'cards' in data:
                html += print_cards_list(sort_cards_by_cmc_and_name(data['cards']),
                                         limit = max_list_items, outformat = outformat,
                                         return_str = True, card_feat = 'best-creature')

            if 'strengh:cards' in data:
                for power, cards_list_by_keywords in data['strengh:cards'].items():
                    html += '        <details>'+'\n'
                    html += '          <summary>power '+str(power)+'</summary>'+'\n'
                    for keywords, cards_list in cards_list_by_keywords.items():
                        html += '          <h6 class="keywords">keywords: '+str(keywords)+'</h6>\n'
                        html += print_cards_list(sort_cards_by_cmc_and_name(cards_list),
                                                 limit=max_list_items, outformat = outformat,
                                                 return_str = True, card_feat = 'best-creature')
                    html += '        </details>'+'\n'

            html += '      </details>'+'\n'
            html += '    </article>'+'\n'
        html += '  </section>'+'\n'
        print(html)

    if outformat == 'console':
        for title, data in best_creature_cards_output_data.items():
            print(title)
            print('')
            if 'ratio:cards' in data:
                min_ratio = data['min_ratio'] if 'min_ratio' in data else 0
                for ratio, cards_list in data['ratio:cards'].items():
                    if ratio <= min_ratio:
                        break
                    print('  ratio', ratio)
                    print('')
                    print_cards_list(sort_cards_by_cmc_and_name(cards_list), limit=max_list_items,
                                    indent = 6, outformat = outformat)
                print('')
            if 'cards' in data:
                print_cards_list(sort_cards_by_cmc_and_name(data['cards']), limit = max_list_items,
                                 indent = 6, outformat = outformat)
                print('')
            if 'strengh:cards' in data:
                for power, cards_list_by_keywords in data['strengh:cards'].items():
                    print('  power', power)
                    print('')
                    for keywords, cards_list in cards_list_by_keywords.items():
                        print('     keywords', keywords)
                        print('')
                        print_cards_list(sort_cards_by_cmc_and_name(cards_list),
                                         limit=max_list_items,
                                         indent = 9, outformat = outformat)
                        print('')
                print('')
        print('')

    return best_creature_cards_selected

def assist_best_instant_or_sorcery_cards(cards, max_list_items = None, outformat = 'console'):
    """Show pre-selected best instant/sorcery cards organised by features,
       for the user to select some"""

    print('DEBUG Analysing best instant/sorcery (damage to CMC ratio, and more) ...',
          file=sys.stderr)
    best_instant_or_sorcery_cards_selected = []

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

    best_instant_or_sorcery_cards_output_data = {
        'Best damage to CMC ratio': {
            'min_ratio': 1.01,
            'ratio:cards': damage_to_cmc},
    }

    for data in best_instant_or_sorcery_cards_output_data.values():
        if 'ratio:cards' in data:
            min_ratio = data['min_ratio'] if 'min_ratio' in data else 0
            for ratio, cards_list in data['ratio:cards'].items():
                if ratio <= min_ratio:
                    break
                best_instant_or_sorcery_cards_selected += (
                    sort_cards_by_cmc_and_name(cards_list)[:max_list_items])

    if outformat == 'html':
        html = ''
        html += '  <section>'+'\n'
        html += '    <h3 id="best-instant-sorcery-cards">Best instant/sorcery cards</h3>\n'
        for title, data in best_instant_or_sorcery_cards_output_data.items():
            html += '    <article>'+'\n'
            html += '      <details>'+'\n'
            html += '        <summary>'+title+'</summary>'+'\n'
            if 'ratio:cards' in data:
                min_ratio = data['min_ratio'] if 'min_ratio' in data else 0
                for ratio, cards_list in data['ratio:cards'].items():
                    if ratio <= min_ratio:
                        break
                    html += '      <h5 class="ratio">ratio '+str(ratio)+'</h5>'+'\n'
                    html += print_cards_list(sort_cards_by_cmc_and_name(cards_list),
                                             limit=max_list_items, outformat = outformat,
                                             return_str = True, card_feat = 'best-instant-sorcery')
            html += '      </details>'+'\n'
            html += '    </article>'+'\n'
        html += '  </section>'+'\n'
        print(html)

    if outformat == 'console':
        for title, data in best_instant_or_sorcery_cards_output_data.items():
            print(title)
            print('')
            if 'ratio:cards' in data:
                min_ratio = data['min_ratio'] if 'min_ratio' in data else 0
                for ratio, cards_list in data['ratio:cards'].items():
                    if ratio <= min_ratio:
                        break
                    print('  ratio', ratio)
                    print('')
                    print_cards_list(sort_cards_by_cmc_and_name(cards_list), limit=max_list_items,
                                    indent = 6, outformat = outformat)
                print('')
        print('')

    return best_instant_or_sorcery_cards_selected

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

    # combo_id = tup_combo[0]
    combo_infos = tup_combo[1]
    combo_cards = combo_infos['infos']['c']

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
        html += '          <td class="cmc-total">'+str(int(combo_infos['cmc_total']))+'</td>'+'\n'
        html += '          <td class="cmc-max">'+str(int(combo_infos['cmc_max']))+'</td>'+'\n'
        html += '          <td class="cmc-min">'+str(int(combo_infos['cmc_min']))+'</td>'+'\n'
        for index, name in enumerate(combo_cards):
            name_and_link = ''
            # TODO get card from the combo card list
            card = get_card(name, cards, strict = True)
            # TODO display both faces
            imgurl = ''
            if 'image_uris' in card and 'normal' in card['image_uris']:
                imgurl = card['image_uris']['normal']
            elif ('card_faces' in card and card['card_faces'] and 'image_uris' in card['card_faces'][0]
                and 'normal' in card['card_faces'][0]['image_uris']):
                imgurl = card['card_faces'][0]['image_uris']['normal']
            img_element = '<img src="#" data-imgurl="'+imgurl+'" alt="image of card '+name+'" />'
            if not imgurl:
                img_element = '<span class="card-not-found">/<span>'
            cardclass = get_card_css_class(card)
            name_and_link = ('<a class="'+get_card_colored(card)+'" href="#" onmouseover="loadImg(this);">'
                                +'<span class="name">'+name+'</span>'
                                +'<span class="image">'+img_element+'</span>'
                             +'</a>')
            html += '          <td class="combo-card'+' '+cardclass+'">'+name_and_link+'</td>'+'\n'
        if len(combo_cards) < max_cards:
            for index in range(len(combo_cards), max_cards):
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
            ret = c_header+'\n'
        c_params = {
            'indent': '',
            'sep': separator_colored,
            'plus': plus_colored,
            'cmc_total': int(combo_infos['cmc_total']),
            'cmc_max': int(combo_infos['cmc_max']),
            'cmc_min': int(combo_infos['cmc_min'])}
        for index, name in enumerate(combo_cards):
            card = get_card(name, cards, strict = True)
            c_params['name_'+str(index + 1)] = colored(
                    ('{:^'+str(max_name_len)+'}').format(truncate_text(name, max_name_len)),
                    get_card_colored(card))
        if len(combo_cards) < max_cards:
            # print('Warning', 'too few cards combo:', combo_cards, file=sys.stderr)
            for index in range(len(combo_cards), max_cards):
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
        combo_id = card_names
        if not combo_id or (excludes and combo_id in excludes):
            continue
        add_combo = (not name or any(filter(lambda names: name in names, card_names))
                     and combo_id not in card_combos)
        if add_combo:
            if ((max_cards and len(card_names) > max_cards)
                    or (min_cards and len(card_names) < min_cards)):
                continue
            if len(card_names) <= 1:
                print('Warning: skipping following combo because it only has 1 card.',
                      card_names, file=sys.stderr)
                continue
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
            if name:
                combo['c'] = tuple((name, *(sorted(set(card_names) - {name}))))
            card_combos[combo_id] = {'infos': combo,
                                     'cards': sort_cards_by_cmc_and_name(combo_cards)}
            analyse_combo(card_combos[combo_id])
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
    """Print k_core combos that have exaclty 'num_cards' cards and matching regex
       ATTENTION: Only relevant with 2 cards combos ! Because it uses cards as nodes."""

    combos_k_core_cards_selected = []

    print('DEBUG Searching for all', num_cards, 'cards combos with', regex, "...",
          'Please wait up to '+str(num_cards - 1)+' minute(s) ...', flush=True, file=sys.stderr)
    new_combos = get_combos(combos, cards, max_cards = num_cards, min_cards = num_cards,
                            combo_res_regex = regex, excludes = excludes)

    # TODO use a graph of combos:
    #       - with weighted edges for percentage of shared cards
    #       - or multiple graph one for combos that share 1 card, then for 2 cards, etc.
    new_combos_relations = {}
    for combo_infos in new_combos.values():
        combo_cards = combo_infos['infos']['c']
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
    for combo_id, combo_infos in new_combos.items():
        combo_cards = combo_infos['infos']['c']
        add_combo = True
        for name in combo_cards:
            if name not in k_cards:
                add_combo = False
                break
        if add_combo and combo_id not in k_combos:
            k_combos[combo_id] = combo_infos

    k_combos_order_cmc_max = list(sorted(k_combos.items(), key=lambda t: t[1]['cmc_max']))

    for node in k_nodes:
        card_name = nx_graph.nodes[node]['card']
        card = get_card(card_name, cards, strict = True)
        if card not in combos_k_core_cards_selected:
            combos_k_core_cards_selected.append(card)

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
            html += print_card(get_card(card_name, cards, strict = True), outformat = outformat,
                               return_str = True, card_feat = 'combos-k-core')
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
            print_card(get_card(card_name, cards), indent = 3)
        print('')

        print('All', num_cards, 'cards combos with', regex, str(k_num)+'-core combos:',
                len(k_combos), 'combos')
        print('')
        for index, tup_combo in enumerate(k_combos_order_cmc_max):
            print_tup_combo(tup_combo, cards, indent = 3, max_cards = num_cards,
                            print_header = index == 0, outformat = outformat)
        print('')

    return combos_k_core_cards_selected

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
                ret += '      <p class="truncated-symbol">... '
                ret += '<small class="limit">(<em>--max-list-items</em> set to '+str(limit)+')'
                ret += '</small></p>'+'\n'

            if outformat == 'console':
                ret += ('{:>'+str(indent)+'}... {}').format(
                        '', '(--max-list-items set to '+str(limit)+')')+'\n'

    if not return_str:
        print(ret)

    return ret

def display_html_header(tab_title = 'MTG Deck Builder Assistant | made by Michael Bideau',
                        page_title = 'MTG Deck Builder Assistant '
                        '<small>| made by Michael Bideau</small>', cards_preselected = None):
    """Print an HTML header with title specified, and CSS and JS"""

    html = ''
    html += '<!DOCTYPE html>'+'\n'
    html += '<html lang="en">'+'\n'
    html += '<head>'+'\n'
    html += '  <meta charset="utf-8" />'+'\n'
    html += '  <title>'+tab_title+'</title>'+'\n'
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
    html += '    .main-head, .main-nav, .side { position: sticky; box-sizing: border-box; z-index: 1; }'+'\n'
    html += '    .main-head { top: 0; }'+'\n'
    html += '    .main-nav, .side { top: 150px; height: calc(100vh - 150px); }'+'\n'
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
    html += '      font-size: 0.8em;'+'\n'
    html += '    }'+'\n'
    html += '    .toc { color: grey; }'+'\n'
    html += '    .toc > ol > li > a { color: inherit; }'+'\n'
    html += '    .combos-list th, .combos-list td { padding: 0 10px; text-align: center; }'+'\n'
    html += '    .combos-list th { color: gray; }'+'\n'
    html += '    .cards-list td { padding: 0 10px; text-align: right; }'+'\n'
    html += '    .cards-list .combo-completed td { text-align: left; font-size: 0.8em; }'+'\n'
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
    html += '    tr.card-line.selected, td.selected { background: #ddd; }'+'\n'
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
    html += '    #deck-list { margin: 10px 0 0 10px; height: 320px; overflow: auto; }'+'\n'
    html += '    h1 small, h2 small, h3 small, h4 small { font-weight: normal; }'+'\n'
    html += '    #cards-not-suggested h4 a { color: inherit; }'+'\n'
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
    html += '      tr.card-line.selected, td.selected { background: #333; }'+'\n'
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
    html += '      .dark_grey, a.dark_grey { color: gray; }'+'\n'
    html += '      button.show { background-color: #31f231; }'+'\n'
    html += '      button.download { background-color: #51d1fb; }'+'\n'
    html += '    }'+'\n'
    html += '    .hidden { display: none; }'+'\n'
    html += '  </style>'+'\n'
    html += '  <script>'+'\n'
    html += '    var deckList = [];'+'\n'
    if cards_preselected:
        html += '    var inputDeckList = ['+'\n'
        cards_preselected_len = len(cards_preselected)
        for index, card in enumerate(cards_preselected):
            html += '      "'+card['name'].replace('"', "'")+'"'
            html += (',' if index != cards_preselected_len else '')+'\n'
        html += '    ];'+'\n'
    html += '    function getCardCssClass(name) {'+'\n'
    html += '      return name.toLowerCase().replaceAll(/ /g, "-").replaceAll(/[^a-z0-9_-]/g, "");'+'\n'
    html += '    };'+'\n'
    html += '    function updateDeckList(checkboxElement) {'+'\n'
    html += '      var featCountElement = null;'+'\n'
    html += '      if ("cardfeat" in checkboxElement.dataset) {'+'\n'
    html += '        let cardFeat = checkboxElement.dataset.cardfeat;'+'\n'
    html += '        featCountElement = document.getElementById(cardFeat+"-count");'+'\n'
    html += '      };'+'\n'
    html += '      let cardType = checkboxElement.dataset.cardtype;'+'\n'
    html += '      var typeCountElement = document.getElementById(cardType+"-count");'+'\n'
    html += '      let cardName = checkboxElement.value;'+'\n'
    html += '      let inDeckList = deckList.indexOf(cardName);'+'\n'
    html += '      var cssclass = getCardCssClass(cardName);'+'\n'
    html += '      var cardElements = document.querySelectorAll("."+cssclass);'+'\n'
    html += '      if(checkboxElement.checked && inDeckList < 0) {'+'\n'
    html += '        deckList.push(cardName);'+'\n'
    html += '        typeCountElement.innerHTML = Number(typeCountElement.innerHTML) + 1;'+'\n'
    html += '        if (featCountElement) {'+'\n'
    html += '          featCountElement.innerHTML = Number(featCountElement.innerHTML) + 1;'+'\n'
    html += '        }'+'\n'
    html += '        cardElements.forEach(function (item) { item.classList.add("selected") });'+'\n'
    html += '      }'+'\n'
    html += '      else if(! checkboxElement.checked && inDeckList > -1) {'+'\n'
    html += '        deckList.splice(inDeckList, 1);'+'\n'
    html += '        typeCountElement.innerHTML = Number(typeCountElement.innerHTML) - 1;'+'\n'
    html += '        if (featCountElement) {'+'\n'
    html += '          featCountElement.innerHTML = Number(featCountElement.innerHTML) - 1;'+'\n'
    html += '        }'+'\n'
    html += '        cardElements.forEach(function (item) { item.classList.remove("selected") });'+'\n'
    html += '      };'+'\n'
    html += '      var deck_size_elt = document.getElementById("deck-size");'+'\n'
    html += '      deck_size_elt.innerHTML = " ("+deckList.length+" cards)";'+'\n'
    html += '    };'+'\n'
    html += '    function getCommanderName(clean = false) {'+'\n'
    html += '      var nameElt = document.getElementById("commander-name");'+'\n'
    html += '      if (clean) { return nameElt.innerHTML.replaceAll(/\\W/g, ""); }'+'\n'
    html += '      return nameElt.innerHTML;'+'\n'
    html += '    };'+'\n'
    html += '    function generateDeckList() {'+'\n'
    html += '      var dekList = "";'+'\n'
    html += '      if (deckList.length > 0) {'+'\n'
    html += '        dekList = "1 "+deckList.join("\\n1 ")+"\\n\\n";'+'\n'
    html += '      }'+'\n'
    html += '      dekList += "1 "+getCommanderName();'+'\n'
    html += '      return dekList;'+'\n'
    html += '    };'+'\n'
    html += '    function showDeckList() {'+'\n'
    html += '      var div = document.getElementById("deck-list");'+'\n'
    html += '      div.innerHTML = "<p>"+generateDeckList().replaceAll("\\n", "<br/>")+"</p>";\n'
    html += '    };'+'\n'
    html += '    function downloadDeckList() {'+'\n'
    html += '      var mime_type = "text/plain";'+'\n'
    html += '      var blob = new Blob([generateDeckList()], {type: mime_type});'+'\n'
    html += '      var dlink = document.createElement("a");'+'\n'
    html += '      dlink.download = getCommanderName(true)+".dek";'+'\n'
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
    html += '    };'+'\n'
    html += '    function loadImg(element) {'+'\n'
    html += '      imgelt = element.querySelector("img[src='+"'#'"+']");'+'\n'
    html += '      if (imgelt && "imgurl" in imgelt.dataset) {'+'\n'
    html += '        imgelt.setAttribute("src", imgelt.dataset.imgurl);'+'\n'
    html += '      }'+'\n'
    html += '    };'+'\n'
    html += '    function uncheckAll() {'+'\n'
    html += '      var checkedBoxes = document.querySelectorAll("input[name=cards]:checked");'+'\n'
    html += '      for (i = 0; i < checkedBoxes.length; i++) { checkedBoxes[i].checked = false; }'+'\n'
    html += '    };'
    html += '    function selectCommander() {'+'\n'
    html += '      var commanderName = getCommanderName();'+'\n'
    html += '      var cssclass = getCardCssClass(commanderName);'+'\n'
    html += '      var cardElements = document.querySelectorAll("."+cssclass);'+'\n'
    html += '      cardElements.forEach(function (item) { item.classList.add("selected") });'+'\n'
    html += '    };'+'\n'
    if cards_preselected:
        html += '    function preselectCards() {'+'\n'
        html += '      for (i = 0; i < inputDeckList.length; i++) {'+'\n'
        html += '        var cardName = inputDeckList[i];'+'\n'
        html += '        var cssclass = getCardCssClass(cardName);'+'\n'
        html += '        var checkboxElement = document.querySelector("."+cssclass+" input");'+'\n'
        html += '        if (checkboxElement) {'+'\n'
        html += '          checkboxElement.checked = true;'+'\n'
        html += '          updateDeckList(checkboxElement);'+'\n'
        html += '        }'+'\n'
        html += '      };'+'\n'
        html += '    };'+'\n'
        html += '    function moveUpNotSuggestedDiv() {'+'\n'
        html += '      var notSuggestedDiv = document.getElementById("cards-not-suggested");'+'\n'
        html += '      if (notSuggestedDiv) {'+'\n'
        html += '        var inputDeckInfoSection = document.getElementById("input-deck-info");'+'\n'
        html += '        if (inputDeckInfoSection) {'+'\n'
        html += '          inputDeckInfoSection.appendChild(notSuggestedDiv);'+'\n'
        html += '        };'+'\n'
        html += '      };'+'\n'
        html += '    };'+'\n'
    html += '    function init() {'+'\n'
    html += '      uncheckAll();'+'\n'
    html += '      selectCommander();'+'\n'
    if cards_preselected:
        html += '      preselectCards();'+'\n'
        html += '      moveUpNotSuggestedDiv();'+'\n'
    html += '    };'+'\n'
    html += '  </script>'+'\n'
    html += '</head>'+'\n'
    html += '<body>'+'\n'
    html += '  <div class="wrapper">'+'\n'
    html += '    <header class="main-head">'+'\n'
    html += '      <h1>'+page_title+'</h1>'+'\n'
    html += '      <p class="subtitle">'
    html += 'Get the <a href="'+SOURCE_URL+'">source code on Github</a>'
    html += '</p>'+'\n'
    html += '    </header>'+'\n'
    html += get_html_toc(cssclass = 'main-nav', show_deck_info = bool(cards_preselected))
    html += '    <aside class="side">'+'\n'
    html += get_html_toc(cssclass = 'side-nav', show_deck_info = bool(cards_preselected))
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
    html += '        <dt>Unkown</dt>'+'\n'
    html += '        <dd id="unknown-count">0</dd>'+'\n'
    html += '      </dl>'+'\n'
    html += '      <dl>'+'\n'
    html += '        <dt>Commander combos</dt>'+'\n'
    html += '        <dd id="commander-combos-count">0</dd>'+'\n'
    html += '        <dt>Combos k-core</dt>'+'\n'
    html += '        <dd id="combos-k-core-count">0</dd>'+'\n'
    html += "        <dt>With commander's feature</dt>"+'\n'
    html += '        <dd id="common-feat-count">0</dd>'+'\n'
    html += '        <dt>Land fetchers</dt>'+'\n'
    html += '        <dd id="land-fetchers-count">0</dd>'+'\n'
    html += '        <dt>Ramps</dt>'+'\n'
    html += '        <dd id="ramps-count">0</dd>'+'\n'
    html += '        <dt>No pay</dt>'+'\n'
    html += '        <dd id="no-pay-count">0</dd>'+'\n'
    html += '        <dt>Draws</dt>'+'\n'
    html += '        <dd id="draws-count">0</dd>'+'\n'
    html += '        <dt>Tutors</dt>'+'\n'
    html += '        <dd id="tutors-count">0</dd>'+'\n'
    html += '        <dt>Removal</dt>'+'\n'
    html += '        <dd id="removal-count">0</dd>'+'\n'
    html += '        <dt>Disabling</dt>'+'\n'
    html += '        <dd id="disabling-count">0</dd>'+'\n'
    html += '        <dt>Board wipe</dt>'+'\n'
    html += '        <dd id="wipe-count">0</dd>'+'\n'
    html += '        <dt>Graveyard recursion</dt>'+'\n'
    html += '        <dd id="graveyard-recursion-count">0</dd>'+'\n'
    html += '        <dt>Graveyard hate</dt>'+'\n'
    html += '        <dd id="graveyard-hate-count">0</dd>'+'\n'
    html += '        <dt>Copy</dt>'+'\n'
    html += '        <dd id="copy-count">0</dd>'+'\n'
    html += '        <dt>Best creatures</dt>'+'\n'
    html += '        <dd id="best-creature-count">0</dd>'+'\n'
    html += '        <dt>Creatures effects</dt>'+'\n'
    html += '        <dd id="creature-effects-count">0</dd>'+'\n'
    html += '        <dt>Best instant/sorcery</dt>'+'\n'
    html += '        <dd id="best-instant-sorcery-count">0</dd>'+'\n'
    html += '      </dl>'+'\n'
    html += '      <button class="action show" onclick="showDeckList()">'
    html += 'Show <small>/update</small> deck list</button>'+'\n'
    html += '      <button class="action download" onclick="downloadDeckList()">'
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

def get_html_toc(cssclass = '', show_deck_info = False):
    """Return the HTML Table Of Content"""
    html = '  <nav class="toc'+((' '+cssclass) if cssclass else '')+'">'+'\n'
    html += '    <ol>'+'\n'
    if show_deck_info:
        html += '      <li><a href="#input-deck-info">Input deck info</a></li>'+'\n'
    html += '      <li><a href="#stats-all-cards">Stats all cards</a></li>'+'\n'
    html += '      <li><a href="#commander-card">Commander card</a></li>'+'\n'
    html += '      <li><a href="#commander-combos">Commander combos</a></li>'+'\n'
    if USE_NX:
        html += '      <li><a href="#combos-k-core">Combos k-core</a></li>'+'\n'
    html += '      <li><a href="#with-commanders-keyword">'+"With commander's keyword</a></li>"+'\n'
    html += '      <li><a href="#lands">Lands</a></li>'+'\n'
    html += '      <li><a href="#land-fetchers">Land fetchers</a></li>'+'\n'
    html += '      <li><a href="#ramp-cards">Ramp cards</a></li>'+'\n'
    html += '      <li><a href="#no-pay-cards">No pay cards</a></li>'+'\n'
    html += '      <li><a href="#draw-cards">Draw cards</a></li>'+'\n'
    html += '      <li><a href="#tutor-cards">Tutor cards</a></li>'+'\n'
    html += '      <li><a href="#removal-cards">Removal cards</a></li>'+'\n'
    html += '      <li><a href="#disabling-cards">Disabling cards</a></li>'+'\n'
    html += '      <li><a href="#wipe-cards">Board wipe cards</a></li>'+'\n'
    html += '      <li><a href="#graveyard-recursion-cards">Graveyard recursion cards</a></li>\n'
    html += '      <li><a href="#graveyard-hate-cards">Graveyard hate cards</a></li>'+'\n'
    html += '      <li><a href="#copy-cards">Copy cards</a></li>'+'\n'
    html += '      <li><a href="#best-creature-cards">Best creature cards</a></li>'+'\n'
    html += '      <li><a href="#creature-effects-cards">Creature effects cards</a></li>\n'
    html += '      <li><a href="#best-instant-sorcery-cards">Best instant/sorcery cards</a></li>\n'
    html += '    </ol>'+'\n'
    html += '  </nav>'+'\n'
    return html

def display_deck_building_header(outformat = 'console', show_deck_info = False):
    """Display the deck building header"""

    # html
    if outformat == 'html':
        html = '  <h2>Deck building</h2>'+'\n'
        html += get_html_toc(cssclass = 'content-nav', show_deck_info = show_deck_info)
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
    cards_rank_1 = []
    cards_rank_2 = []

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

            c_combos_rank_1_x_cards[key]['combos'] = {}
            c_combos_rank_1_x_cards[key]['cards names'] = []

            for combo_id, combo_infos in c_combos.items():
                combo_cards_names = combo_infos['infos']['c']
                if len(combo_cards_names) != count:
                    continue
                c_combos_rank_1_x_cards[key]['combos'][combo_id] = combo_infos

                combo_cards = combo_infos['cards']
                for name in combo_cards_names:
                    if (name != COMMANDER_NAME
                            and name not in c_combos_rank_1_x_cards[key]['cards names']):
                        c_combos_rank_1_x_cards[key]['cards names'].append(name)
                        for c_card in combo_cards:
                            if c_card['name'] == name:
                                if c_card not in cards_rank_1:
                                    cards_rank_1.append(c_card)
                                break

            c_combos_rank_1_x_cards[key]['combos'] = dict(sorted(
                c_combos_rank_1_x_cards[key]['combos'].items(),
                key=lambda t: t[1]['cmc_total']))

            combos_rank_1_names |= set(c_combos_rank_1_x_cards[key]['cards names'])

        # rank 2
        c_combos_cards = tuple(sorted(combos_rank_1_names))
        combos_rank_2_excludes = c_combos.keys()

        for card_name in c_combos_cards:
            print('DEBUG Searching for combos related to', card_name, '...', flush=True,
                file=sys.stderr)
            card_combos = get_combos(combos, cards, name = card_name,
                                     combo_res_regex = commander_combos_regex,
                                     excludes = combos_rank_2_excludes)
            if card_combos:
                for c_id, c_info in card_combos.items():
                    if c_id not in combos_rank_2:
                        combos_rank_2[c_id] = c_info

        for count in range(2, 5):
            key = '4+' if count == 4 else str(count)

            if key not in c_combos_rank_2_x_cards:
                c_combos_rank_2_x_cards[key] = {}

            c_combos_rank_2_x_cards[key]['combos'] = {}
            c_combos_rank_2_x_cards[key]['cards names'] = []

            for combo_id, combo_infos in combos_rank_2.items():
                combo_cards_names = combo_infos['infos']['c']
                if len(combo_cards_names) != count:
                    continue
                c_combos_rank_2_x_cards[key]['combos'][combo_id] = combo_infos

                combo_cards = combo_infos['cards']
                for name in combo_cards_names:
                    if (name != COMMANDER_NAME
                            and name not in c_combos_rank_2_x_cards[key]['cards names']
                            and name not in combos_rank_1_names):
                        c_combos_rank_2_x_cards[key]['cards names'].append(name)
                        for c_card in combo_cards:
                            if c_card['name'] == name:
                                if c_card not in cards_rank_2:
                                    cards_rank_2.append(c_card)
                                break

            c_combos_rank_2_x_cards[key]['combos'] = dict(sorted(
                c_combos_rank_2_x_cards[key]['combos'].items(),
                key=lambda t: t[1]['cmc_total']))

        # list cards that completes a 3 cards combo of rank 2 with cards preselected from rank 1 & 2
        rank_2_combos_missing_one_card = {}
        cards_able_to_complete_rank_2_combos = {}
        if '3' in c_combos_rank_2_x_cards:

            # preselect cards of rank 1 combo with lower than 4 cards, and rank 2 lower than 3 cards
            combos_cards_preselected = []
            for count in range(2, 4):
                key = str(count)
                if key in c_combos_rank_1_x_cards:
                    combos_cards_preselected += c_combos_rank_1_x_cards[key]['cards names']
            if '2' in c_combos_rank_2_x_cards:
                combos_cards_preselected += c_combos_rank_2_x_cards['2']['cards names']
            combos_cards_preselected = set(combos_cards_preselected)
            print('DEBUG Combo cards preselected:', file=sys.stderr)
            for name in combos_cards_preselected:
                print('DEBUG    ', name, file=sys.stderr)

            for combo_id, combo_infos in c_combos_rank_2_x_cards['3']['combos'].items():
                combo_cards_names = combo_infos['infos']['c']
                card_not_already_preselected = [
                    c for c in combo_cards_names if c not in combos_cards_preselected]
                if (len(card_not_already_preselected) == 1  # only miss one card
                        and combo_id not in rank_2_combos_missing_one_card):
                    rank_2_combos_missing_one_card[combo_id] = combo_infos
                    if card_not_already_preselected[0] not in cards_able_to_complete_rank_2_combos:
                        cards_able_to_complete_rank_2_combos[card_not_already_preselected[0]] = 0
                    cards_able_to_complete_rank_2_combos[card_not_already_preselected[0]] += 1
                    combo_cards = combo_infos['cards']
                    for c_card in combo_cards:
                        if c_card['name'] == card_not_already_preselected[0]:
                            if c_card not in cards_rank_2:
                                cards_rank_2.append(c_card)
                                print('DEBUG', 'rank 2 add', c_card['name'], file=sys.stderr)
                            break

            rank_2_combos_missing_one_card = dict(sorted(
                rank_2_combos_missing_one_card.items(),
                key=lambda t: t[1]['cmc_total']))

            cards_able_to_complete_rank_2_combos = dict(sorted(
                cards_able_to_complete_rank_2_combos.items(),
                key=lambda t: t[1], reverse=True))

        # TODO k-core applyed to 3 cards combos of rank 2

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
                                            print_header = index == 0, outformat = outformat,
                                            return_str = True)
                html += '      </table>'+'\n'
                html += '      <h5>Cards</h5>'+'\n'
                html += '      <table class="cards-list">'+'\n'
                for name in sorted(c_combos_rank_1_x_cards[key]['cards names']):
                    html += print_card(get_card(name, cards), outformat = outformat,
                                       return_str = True, card_feat = 'commander-combos')
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
                                            print_header = index == 0, outformat = outformat,
                                            return_str = True)
                html += '      </table>'+'\n'
                html += '      <h5>Cards</h5>'+'\n'
                html += '      <table class="cards-list">'+'\n'
                for name in sorted(c_combos_rank_2_x_cards[key]['cards names']):
                    html += print_card(get_card(name, cards), outformat = outformat,
                                       return_str = True, card_feat = 'commander-combos')
                html += '      </table>'+'\n'
                html += '    </details>'+'\n'

            if rank_2_combos_missing_one_card:
                html += '    <details>'+'\n'
                html += '      <summary>'
                html += ('Rank 2 combos with 3 cards, missing only one card: '
                         +str(len(rank_2_combos_missing_one_card))+' combos,'
                         +'+'+str(len(cards_able_to_complete_rank_2_combos))+' cards')
                html += '</summary>'+'\n'
                html += '      <h5>Combos</h5>'+'\n'
                html += '      <table class="combos-list">'+'\n'
                for index, tup_combo in enumerate(rank_2_combos_missing_one_card.items()):
                    html += print_tup_combo(tup_combo, cards, max_cards = count,
                                            print_header = index == 0, outformat = outformat, return_str = True)
                html += '      </table>'+'\n'
                html += '      <h5>Cards</h5>'+'\n'
                html += '      <table class="cards-list">'+'\n'
                combos_completed = 0
                for name, complete in cards_able_to_complete_rank_2_combos.items():
                    if complete != combos_completed:
                        combos_completed = complete
                        html += '        <tr class="combo-completed"><td colspan="7">Complete '+str(complete)+' combos</td></tr>'+'\n'
                    html += print_card(get_card(name, cards), outformat = outformat,
                                       return_str = True, card_feat = 'commander-combos')
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
                        print_tup_combo(tup_combo, cards, indent = 9, max_cards = count,
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
                                print_tup_combo(tup_combo, cards, indent = 9, max_cards = count,
                                                print_header = index == 0)
                            print('')

                if rank_2_combos_missing_one_card:
                    print('    Rank 2 combos with 3 cards, missing only one card:',
                          len(rank_2_combos_missing_one_card),
                          'combos,', '+'+str(len(cards_able_to_complete_rank_2_combos)),
                          'cards')
                    print('')
                    for index, tup_combo in enumerate(rank_2_combos_missing_one_card.items()):
                        print_tup_combo(tup_combo, cards, indent = 9, max_cards = 3,
                                        print_header = index == 0)
                    print('')

    return combos_rank_1, cards_rank_1, combos_rank_2, cards_rank_2

def assist_commander_keywords_common(commander_card, cards, limit = None, outformat = 'console'):
    """Show cards with at least one commander's keywords, for the user to select some"""

    cards_common_keywords_selected = []

    commander_keywords = set(commander_card['keywords'])
    cards_common_keyword = sort_cards_by_cmc_and_name(list(
        filter(lambda c: bool(commander_keywords & set(c['keywords'])), cards)))
    cards_common_keywords_selected += cards_common_keyword[:limit]

    commander_common_feature_organized = {}
    associated_feature_organized = {}
    if COMMANDER_FEATURES_REGEXES:
        commander_common_feature = {}
        commander_texts = get_oracle_texts(commander_card)
        commander_texts_low = list(map(str.lower, commander_texts))
        for feature, have_and_search in COMMANDER_FEATURES_REGEXES.items():
            for have_regexp, search_regexp in have_and_search.items():
                if list(search_strings(have_regexp, commander_texts_low)):
                    if feature not in commander_common_feature:
                        commander_common_feature[feature] = []
                    if not search_regexp:
                        continue
                    for card in cards:
                        oracle_texts = get_oracle_texts(card, replace_name = '<name>')
                        oracle_texts_low = list(map(str.lower, oracle_texts))
                        for regexp in search_regexp:
                            exclude_regexes = []
                            if isinstance(regexp, tuple):
                                exclude_regexes = regexp[1]
                                regexp = regexp[0]
                            if list(search_strings(regexp, oracle_texts_low)):
                                wont_add = False
                                if exclude_regexes:
                                    for exc_reg in exclude_regexes:
                                        if list(search_strings(exc_reg, oracle_texts_low)):
                                            wont_add = True
                                            break
                                if not wont_add:
                                    commander_common_feature[feature].append(card)
                                break

        for feature, cards_list in commander_common_feature.items():
            commander_common_feature_organized[feature] = organize_by_type(cards_list)

        if FEATURE_MAP:

            features_and_keywords_to_search = []
            features_and_keywords_to_search += list(map(
                lambda f: 'feat:'+f, commander_common_feature.keys()))
            features_and_keywords_to_search += list(map(
                lambda k: 'keyword:'+k, commander_keywords))
            associated_feature = {}

            # descend/loop once (depth 2)
            features_or_keywords_depth_2 = []
            for have in features_and_keywords_to_search:
                if have in FEATURE_MAP:
                    for feat_or_keyw in FEATURE_MAP[have]:
                        if feat_or_keyw in FEATURE_MAP:
                            features_or_keywords_depth_2.append(feat_or_keyw)

            if features_or_keywords_depth_2:
                for feat_or_keyw in features_or_keywords_depth_2:
                    if feat_or_keyw not in features_and_keywords_to_search:
                        features_and_keywords_to_search.append(feat_or_keyw)

            for have in features_and_keywords_to_search:
                if have in FEATURE_MAP:
                    for search in FEATURE_MAP[have]:
                        feature = None
                        keyword = None
                        if search.startswith('feat:'):
                            feature = search.replace('feat:', '')
                        elif search.startswith('keyword:'):
                            keyword = search.replace('keyword:', '')
                        if feature and feature in COMMANDER_FEATURES_REGEXES:
                            for search_regexp in COMMANDER_FEATURES_REGEXES[feature].values():
                                if not search_regexp:
                                    continue
                                for card in cards:
                                    oracle_texts = get_oracle_texts(card, replace_name = '<name>')
                                    oracle_texts_low = list(map(str.lower, oracle_texts))
                                    for regexp in search_regexp:
                                        exclude_regexes = []
                                        if isinstance(regexp, tuple):
                                            exclude_regexes = regexp[1]
                                            regexp = regexp[0]
                                        if list(search_strings(regexp, oracle_texts_low)):
                                            wont_add = False
                                            if exclude_regexes:
                                                for exc_reg in exclude_regexes:
                                                    if list(search_strings(exc_reg,
                                                                           oracle_texts_low)):
                                                        wont_add = True
                                                        break
                                            if not wont_add:
                                                if feature not in associated_feature:
                                                    associated_feature[feature] = []
                                                associated_feature[feature].append(card)
                                                break
                        elif keyword:
                            for card in cards:
                                keywords_list = get_keywords(card)
                                for keywords in keywords_list:
                                    if keyword in keywords:
                                        if keyword not in associated_feature:
                                            associated_feature[keyword] = []
                                        associated_feature[keyword].append(card)
                                        break

        for feature, cards_list in associated_feature.items():
            associated_feature_organized[feature] = organize_by_type(cards_list)

        feature_organized = commander_common_feature_organized | associated_feature_organized
        for feature, cards_organized in feature_organized.items():
            if cards_organized:
                for card_type, cards_list in cards_organized.items():
                    if cards_list:
                        cards_common_keywords_selected += (
                            sort_cards_by_cmc_and_name(cards_list)[:limit])

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
                                 outformat = outformat, return_str = True,
                                 card_feat = 'common-feat')
        html += '      </details>'+'\n'
        html += '    </article>'+'\n'

        if COMMANDER_FEATURES_REGEXES:
            html += '    <article>'+'\n'
            html += '      <h4>Cards matching specific features</h4>'+'\n'
            feature_organized = commander_common_feature_organized | associated_feature_organized
            for feature, cards_organized in feature_organized.items():
                title = "Cards matching feature '"+feature+"': "
                title += str(sum(map(len, cards_organized.values())))
                html += '      <details>'+'\n'
                html += '        <summary>'+title+'</summary>'+'\n'
                if cards_organized:
                    for card_type, cards_list in cards_organized.items():
                        if cards_list:
                            subtitle = card_type.capitalize()+" matching feature '"+feature+"': "
                            subtitle += str(len(cards_list))
                            html += '        <details>'+'\n'
                            html += '          <summary>'+subtitle+'</summary>'+'\n'
                            html += '          <table class="cards-list">'+'\n'
                            html += print_cards_list(sort_cards_by_cmc_and_name(cards_list),
                                                     limit = limit, outformat = outformat,
                                                     return_str = True, card_feat = 'common-feat')
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
        print_cards_list(cards_common_keyword, limit = limit, indent = 6, outformat = outformat)

        if COMMANDER_FEATURES_REGEXES:
            feature_organized = commander_common_feature_organized | associated_feature_organized
            for feature, cards_organized in feature_organized.items():
                if cards_organized:
                    title = "Cards matching feature '"+feature+"': "
                    title += str(sum(map(len, cards_organized.values())))
                    print(title)
                    print('')
                    for card_type, cards_list in cards_organized.items():
                        subtitle = card_type.capitalize()+" matching feature '"+feature+"': "
                        subtitle += str(len(cards_list))
                        print('   '+subtitle)
                        print('')
                        if cards_list:
                            print_cards_list(sort_cards_by_cmc_and_name(cards_list), limit = limit,
                                             indent = 6)
                            print('')
            print('')

    return cards_common_keywords_selected

def print_input_deck_info(cards, cards_names_not_found, cards_not_playable, outformat = 'console'):
    """Print the input deck informations (cards not found, not playable, etc)"""

    if outformat == 'html':
        html = ''
        html += '  <section id="input-deck-info">'+'\n'
        html += '    <h3>Input deck info</h3>'+'\n'
        html += '    <div class="ok">'+'\n'
        html += '      <h4>Cards ok: '+str(len(cards))+' '
        html += '<small>(basic lands excluded)</small></h4>\n'
        html += '    </div>'+'\n'

        if cards_names_not_found:
            html += '    <div class="not-found">'+'\n'
            html += '      <h4>Cards not found</h4>'+'\n'
            html += '      <ul class="cards-names-list">'+'\n'
            for card_name in cards_names_not_found:
                html += '        <li>'+card_name+'</li>'+'\n'
            html += '      </ul>'+'\n'
            html += '    </div>'+'\n'
        if cards_not_playable:
            html += '    <div class="not-playable">'+'\n'
            html += '      <h4>Cards not playable '
            html += '<small>(not rules 0 compatible, or wrong color)</small></h4>\n'
            html += print_cards_list(cards_not_playable, outformat = outformat, return_str = True,
                                     print_rarity = True)
            html += '    </div>'+'\n'

        html += '  </section>'+'\n'
        print(html)

    if outformat == 'console':
        print('')
        print('Input deck info')
        print('')
        if cards_names_not_found:
            print('   Cards not found')
            print('')
            for card_name in cards_names_not_found:
                print('     ', card_name)
            print('')
        if cards_not_playable:
            print('   Cards not playable (not rules 0 compatible, or wrong color)')
            print('')
            print_cards_list(cards_not_playable, outformat = outformat, indent = 6)
            print('')
        print('')
        print('   Cards ok:', len(cards), ' (basic lands excluded)')

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
    print_cards_list(sort_cards_by_cmc_and_name(misses), indent = 3)
    print('')
    # print(title+' (bad misses)')
    # print_cards_list(sort_cards_by_cmc_and_name(bad_misses))

def get_input_deck_cards(deck_file):
    """Return a list of cards names matching the lines in the specified deck file"""

    deck_cards_names = []
    deck_path = Path(deck_file)
    if not deck_path.is_file():
        print("Error: deck file '"+deck_file+"' not found", file=sys.stderr)
        sys.exit(1)
    with open(deck_file, 'r', encoding='utf-8') as f_read:
        for line in f_read:
            line = line.strip()
            if not line:
                continue
            # dck (Xmage format): sidebord and layout
            if (line.startswith('SB:') or line.startswith('LAYOUT MAIN:')
                    or line.startswith('LAYOUT SIDEBOARD:')):
                continue
            # dck_info: name and sidebord
            if line.startswith('NAME:') or line.startswith('SB:'):
                continue
            # dck (Xmage format)
            matches = re.match(r'^\s*\d+\s+\[[^]]+\]\s+([^)]+)\s*$', line)
            if not matches:
                # dck_info
                matches = re.match(r'^\s*\d+\s+\[[^]]+\]\s+([^;]+)\s*;;.*$', line)
                if not matches:
                    # mtga
                    matches = re.match(r'^\s*\d+\s+([^(]+)\s*\(.*$', line)
                    if not matches:
                        # dek
                        matches = re.match(r'^\s*\d+\s+(.+)$', line)
            if not matches:
                print("WARNING deck file contain a line that doesn't match any of the expected"
                    " formats (.dck, .dck_info, .mtga, .dek)",
                    file=sys.stderr)
                print("invalid line:", line, file=sys.stderr)
                continue
            card_name = matches.group(1).strip()
            if (card_name not in BASIC_LAND_NAMES and card_name != COMMANDER_NAME
                    and card_name not in deck_cards_names):
                deck_cards_names.append(card_name)

    return deck_cards_names

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
        description=('A Magic The Gathering deck builder assistant for Commander mode, suggesting '
                     'cards based on the commander'),
        epilog='Enjoy !')

    parser.add_argument('commander_name', nargs='?', help='the commnder name')
    parser.add_argument('deck_path', nargs='?', help='an existing deck')
    parser.add_argument('-i', '--input-deck-file',
                        help='path to a file containing an existing deck (format: dek)')
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
    parser.add_argument('-0', '--rules0', default='no-expensive with-xmage-banned no-stickers',
                        help="rules 0 preset (default to 'no-expensive with-xmage-banned no-stickers')")
    parser.add_argument('--list-rules0-preset', action='store_true', help="list rules 0 preset")
    parser.add_argument('--html', action='store_true', help='output format to an HTML page')
    # TODO Add a parameter to exclude MTG sets by name or code
    # TODO Add a parameter to prevent cards comparison with hand crafted list
    args = parser.parse_args()

    if len(sys.argv) == 1:
        parser.print_help(sys.stderr)
        sys.exit(0)

    if args.list_rules0_preset:
        print('')
        print("Use any combination of the following filter (separated by space ' '):")
        for preset in ['no-expensive', 'no-mythic', 'no-stickers', 'with-xmage-banned']:
            print('  ', preset)
        print('')
        print("Default is: 'no-expensive with-xmage-banned no-stickers'")
        print('')
        sys.exit(0)

    if args.list_combos_effects and args.html:
        print("Error: option '--list-combos-effects' and '--html' are mutualy exclusive "
              "(choose only one)", file=sys.stderr)
        sys.exit(1)

    if not args.list_combos_effects and not args.commander_name:
        print("Error: commander name empty (and not using option '--list-combos-effects' nor "
              "'--list-rules0-preset'", file=sys.stderr)
        sys.exit(1)

    if args.output != sys.stdout:
        sys.stdout = open(args.output, 'wt', encoding='utf-8')  # pylint: disable=consider-using-with

    if sys.stdout.isatty():  # in a terminal
        TERM_COLS, TERM_LINES = os.get_terminal_size()

    # combo
    combos = get_commanderspellbook_combos()
    print('DEBUG Loaded combos database:', len(combos), 'combos', file=sys.stderr)

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
                print('')
                break
            print(f'   {count:>6}  {effect}')
        sys.exit(0)

    COMMANDER_NAME = args.commander_name

    input_deck_cards_names = []
    if args.input_deck_file:
        input_deck_cards_names = get_input_deck_cards(args.input_deck_file)

    XMAGE_COMMANDER_CARDS_BANNED = get_xmage_commander_banned_list()

    # get scryfall cards database
    cards = None
    scryfall_bulk_data = get_scryfall_bulk_data()
    scryfall_cards_db_json_file = get_scryfall_cards_db(scryfall_bulk_data)
    with open(scryfall_cards_db_json_file, "r", encoding="utf8") as r_file:
        cards = json.load(r_file)

    # output format
    outformat = 'html' if args.html else 'console'

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

    compute_invalid_colors()

    non_empty_cards = list(filter(filter_empty, cards))
    commander_legal = list(filter(filter_not_legal_and_banned, non_empty_cards))
    valid_colors = list(filter(filter_colors, commander_legal))
    valid_rules0 = list(filter(lambda c: filter_rules0(c, args.rules0), valid_colors))
    cards_ok = valid_rules0

    input_deck_cards = []
    input_deck_cards_not_playable = []
    input_deck_cards_names_not_found = []
    if input_deck_cards_names:
        for card_name in input_deck_cards_names:
            card = get_card(card_name, cards_ok, strict = True)
            if not card:
                card = get_card(card_name, cards, strict = True)
                if card:
                    input_deck_cards_not_playable.append(card)
                    continue
            if not card:
                input_deck_cards_names_not_found.append(card_name)
                continue
            input_deck_cards.append(card)

    # HTML specifics
    if args.html:
        def colored(text, color, *pos, **kwargs):  # pylint: disable=unused-variable,unused-argument,redefined-outer-name
            """Return the text colored"""
            return '<span class="'+color+'">'+text+'</span>'

        display_html_header(cards_preselected = input_deck_cards)

    if args.input_deck_file:
        print_input_deck_info(input_deck_cards, input_deck_cards_names_not_found,
                              input_deck_cards_not_playable, outformat = outformat)

    print_all_cards_stats(cards, non_empty_cards, commander_legal, valid_rules0, args.rules0,
                          outformat = outformat)

    display_commander_card(commander_card, commander_combos_regex, outformat = outformat,
                           outdir = args.outdir)

    print_deck_cards_stats(cards, valid_colors, valid_rules0, outformat = outformat)

    display_deck_building_header(outformat = outformat, show_deck_info=bool(args.input_deck_file))

    commander_combos_no_filter = get_combos(combos, cards, name = COMMANDER_NAME, only_ok = False)
    commander_combos = get_combos(combos, cards_ok, name = COMMANDER_NAME)

    combos_rank_1, cards_rank_1, combos_rank_2, cards_rank_2 = assist_commander_combos(
            commander_combos_no_filter, commander_combos, commander_combos_regex, combos, cards_ok,
            outformat = outformat)

    cards_k_core = []
    if USE_NX:
        cards_excludes = (list(combos_rank_1.keys()) + list(combos_rank_2.keys()))
        if outformat == 'html':
            html = '  <section>'+'\n'
            html += '    <h3 id="combos-k-core">'
            html += 'Combos k-core <small>(not tied to the commander)</small></h3>'
            print(html)
        cards_k_core = assist_k_core_combos(combos, cards_ok, commander_combos_regex, 2,
                                            cards_excludes, outformat = outformat)
        # assist_k_core_combos(combos, cards_ok, commander_combos_regex, 3, cards_excludes,
        #                      outformat = outformat)
        if outformat == 'html':
            html = '  </section>'+'\n'
            print(html)

    # one common keyword
    cards_common_keywords = assist_commander_keywords_common(commander_card, cards_ok,
                                                             limit = args.max_list_items,
                                                             outformat = outformat)

    lands = list(filter(filter_lands, cards_ok))
    land_types_invalid = [COLOR_TO_LAND[c] for c in INVALID_COLORS]
    # print('Land types not matching commander:', land_types_invalid)
    # print('')
    land_types_invalid_regex = r'('+('|'.join(land_types_invalid)).lower()+')'
    cards_lands = assist_land_selection(lands, land_types_invalid_regex,
                                        max_list_items = args.max_list_items, outformat = outformat)

    cards_land_fetch = assist_land_fetch(
        cards_ok, land_types_invalid_regex, max_list_items = args.max_list_items,
        outformat = outformat)

    cards_ramp_cards = assist_ramp_cards(
        [c for c in cards_ok if c not in cards_land_fetch],
        land_types_invalid_regex, max_list_items = args.max_list_items,
        outformat = outformat)

    if outformat == 'console':
        selection = cards_ramp_cards + cards_land_fetch
        compare_with_hand_crafted_list(selection, 'ramp_cards.list.txt',
                                       'Ramp cards missing (VS ramp_cards.list.txt)',
                                       cards_ok)

    cards_no_pay_cards = assist_no_pay_cards(
        [c for c in cards_ok if c not in cards_land_fetch and c not in cards_ramp_cards],
        max_list_items = args.max_list_items,
        outformat = outformat)

    cards_draw = assist_draw_cards(
        [c for c in cards_ok if c not in cards_land_fetch],
        land_types_invalid_regex, max_list_items = args.max_list_items,
        outformat = outformat)

    if outformat == 'console':
        selection = cards_ramp_cards + cards_land_fetch + cards_draw
        compare_with_hand_crafted_list(selection, 'draw_cards.list.txt',
                                       'Draw cards missing (VS draw_cards.list.txt)',
                                       cards_ok)

    cards_tutor = assist_tutor_cards(
        [c for c in cards_ok if c not in cards_land_fetch],
        land_types_invalid_regex, max_list_items = args.max_list_items,
        outformat = outformat)

    if outformat == 'console':
        selection = (cards_ramp_cards + cards_land_fetch + cards_draw
                     + cards_tutor)
        compare_with_hand_crafted_list(selection, 'tutor_cards.list.txt',
                                       'Tutor cards missing (VS tutor_cards.list.txt)',
                                       cards_ok)

    cards_removal = assist_removal_cards(
        [c for c in cards_ok if c not in cards_draw and c not in cards_tutor],
        max_list_items = args.max_list_items, outformat = outformat)

    cards_disabling = assist_disabling_cards(
        [c for c in cards_ok if c not in cards_draw and c not in cards_tutor
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
        [c for c in cards_ok if c not in cards_draw and c not in cards_tutor
         and c not in cards_removal and c not in lands],
        max_list_items = args.max_list_items, outformat = outformat)

    cards_best_creatures = assist_best_creature_cards(
        cards_ok, max_list_items = args.max_list_items, outformat = outformat)

    cards_effects = assist_creature_effects(cards_ok, max_list_items = args.max_list_items,
                                                    outformat = outformat)

    cards_best_instant_or_sorcery = assist_best_instant_or_sorcery_cards(
        cards_ok, max_list_items = args.max_list_items, outformat = outformat)


    # TODO select 1 'I win' suprise card

    # TODO for each turn N present a list of possible N-drop cards

    print('DEBUG Cards selection:', file=sys.stderr)
    cards_selection = []
    cards_selection.append(commander_card)
    for title, cards_list in {
            'Combos rank 1 & 2': cards_rank_1 + cards_rank_2,
            'Combos k-core': cards_k_core,
            "With commander's keyword/feature": cards_common_keywords,
            'Lands': cards_lands,
            'Fetch land': cards_land_fetch,
            'Ramp': cards_ramp_cards,
            'No pay': cards_no_pay_cards,
            'Draw': cards_draw,
            'Tutor': cards_tutor,
            'Removal': cards_removal,
            'Disabling': cards_disabling,
            'Board wipe': cards_wipe,
            'Graveyard recursion': cards_graveyard_recursion,
            'Graveyard hate': cards_graveyard_hate,
            'Copy': cards_copy,
            'Best creatures': cards_best_creatures,
            'Creatures effects': cards_effects,
            'Best instant/sorcery': cards_best_instant_or_sorcery}.items():
        if cards_list:
            print('DEBUG   ', title+':', len(cards_list), file=sys.stderr)
            for card in cards_list:
                if card not in cards_selection:
                    cards_selection.append(card)
    print('DEBUG TOTAL (unique):', len(cards_selection), file=sys.stderr)

    if input_deck_cards:
        not_matching_selection = []
        for card in input_deck_cards:
            if card not in cards_selection:
                not_matching_selection.append(card)

        if not args.html:
            print('')
            print('Input deck card in the selection:',
                  len(input_deck_cards) - len(not_matching_selection))
            print('')

        if not_matching_selection:
            if args.html:
                html = ''
                html += '      <div id="cards-not-suggested">'+'\n'
                html += '        <h4>Cards not in the suggestion: '+str(len(not_matching_selection))
                html += ' <small>(try with a bigger <em>--max-list-items</em>, or if they should '
                html += 'have been suggested <a href="https://github.com/mbideau/MTG/issues">'
                html += 'open a issue</a>)</small></h4>'+'\n'
                html += print_cards_list(not_matching_selection, return_str = True,
                                         outformat = outformat)
                html += '      </div>'+'\n'
                print(html)

            if not args.html:
                print('Input deck cards not in the selection:', len(not_matching_selection))
                print('')
                print_cards_list(not_matching_selection, indent = 3)
                print('')

    if args.html:
        html = ''
        html += '    </div>'+'\n'
        html += '    <footer class="main-footer">Copyright © Michael Bideau '
        html += '(all images and text are the property of Wizard of the Coast)</footer>'+'\n'
        html += '  </div>'+'\n' # wrapper end
        # on page load, uncheck all checked checkboxes
        html += '  <script>'+'\n'
        html += '    window.onload = init();'
        html += '  </script>'+'\n'
        html += '</body>'+'\n'
        html += '</html>'
        print(html)

    if not args.html:
        print('')
        print('Cards selected:', len(cards_selection))
        print('')

if __name__ == '__main__':
    try:
        main()
    except BrokenPipeError:
        pass
    except KeyboardInterrupt:
        print('', file=sys.stderr)
        print('Ciao !', file=sys.stderr)
