#!/usr/bin/env python3
"""
Deck builder using the Scryfall JSON cards collection
"""

# pylint: disable=line-too-long

import sys
import json
import re
from urllib.request import urlopen
from pathlib import Path
from math import comb, prod
# import pprint

XMAGE_COMMANDER_BANNED_LIST_URL = 'https://github.com/magefree/mage/raw/master/Mage.Server.Plugins/Mage.Deck.Constructed/src/mage/deck/Commander.java'
XMAGE_DUELCOMMANDER_BANNED_LIST_URL = 'https://github.com/magefree/mage/raw/master/Mage.Server.Plugins/Mage.Deck.Constructed/src/mage/deck/DuelCommander.java'
XMAGE_BANNED_LINE_REGEX = r'^\s*banned(Commander)?\.add\("(?P<name>[^"]+)"\);\s*$'
XMAGE_COMMANDER_BANNED_LIST_FILE = "/tmp/xmage-Commander-banned-list.txt"
XMAGE_DUELCOMMANDER_BANNED_LIST_FILE = "/tmp/xmage-DuelCommander-banned-list.txt"
XMAGE_COMMANDER_CARDS_BANNED = []

ALL_COLORS = set(['R', 'G', 'U', 'B', 'W'])
ALL_COLORS_COUNT = len(ALL_COLORS)
COLOR_TO_LAND = {
    'G': 'Forest',
    'R': 'Mountain',
    'W': 'Plains',
    'U': 'Island',
    'B': 'Swamp'}
COMMANDER_NAME = 'Queza, Augur of Agonies'
COMMANDER_KEYWORDS = []  # ['Draw', 'Lifegain', 'Lifeloss'] doesn't work, not an evergreen ability ?
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

COMMANDER_FEATURES_REGEXES = [
#    r'(opponent|target player|owner).*(lose|have lost).*life',
#    r'(you|target player|owner).*(gain|have gained).*life',
#    r'(you|target player|owner).*(draw|have draw)',
]
COMMANDER_FEATURES_EXCLUDE_REGEX = r'('+('|'.join([
    '[Ss]acrifice|[Ee]xile|[Tt]ransform|[Dd]iscard',
#    '^\\s*((First strike|Flying|Skulk|Deathtouch)( \\([^)]+\\))?)?\\s*Lifelink \\([^)]+\\)\\s*$'
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


# Add a parameter to express if a 1-drop at turn 1 is important,
# that will exclude land that are not usable at turn 1 or colorless at turn 1
TURN_1_WANTS_1_DROP = False

# Add a parameter to express if you expect to fill your graveyard pretty fast (mill),
# that will include card that relies on other cards being in the graveyard
FILL_GRAVEYARD_FAST = False

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
#     print("[hypergeometric_draw]", 'comb(',deck_size - sum(map(lambda t: t[0], tuples)),',',draw_count - sum(map(lambda t: t[1], tuples)) ,')')
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

def get_xmage_commander_banned_list(include_duel = True, update = False):
    """Return a list of banned card for Commander format in XMage

       Options:

       include_duel  bool  If 'True' include DuelCommander format banned list
       update        bool  If 'True' force updating banned list files
    """
    commander_banned_file_path = Path(XMAGE_COMMANDER_BANNED_LIST_FILE)
    commander_banned_cards = []
    if not commander_banned_file_path.is_file() or update:
        print("Getting Commander banned list from remote Xmage file ...")
        with open(XMAGE_COMMANDER_BANNED_LIST_FILE, 'w', encoding="utf8") as f_write:
            with urlopen(XMAGE_COMMANDER_BANNED_LIST_URL) as webpage:
                for line in webpage:
                    matches = re.search(XMAGE_BANNED_LINE_REGEX, line.decode('utf-8'))
                    if matches:
                        card = matches.group('name')
                        commander_banned_cards.append(card)
                        f_write.write(card+'\n')
    else:
        print("Getting Commander banned list from local file ...")
        with open(XMAGE_COMMANDER_BANNED_LIST_FILE, 'r', encoding="utf8") as f_read:
            commander_banned_cards = list(map(str.strip, list(f_read)))

    if include_duel:
        commanderduel_banned_file_path = Path(XMAGE_DUELCOMMANDER_BANNED_LIST_FILE)
        if not commanderduel_banned_file_path.is_file() or update:
            print("Getting DuelCommander banned list from remote Xmage file ...")
            with open(XMAGE_DUELCOMMANDER_BANNED_LIST_FILE, 'w', encoding="utf8") as f_write:
                with urlopen(XMAGE_DUELCOMMANDER_BANNED_LIST_URL) as webpage:
                    for line in webpage:
                        matches = re.search(XMAGE_BANNED_LINE_REGEX, line.decode('utf-8'))
                        if matches:
                            card = matches.group('name')
                            commander_banned_cards.append(card)
                            f_write.write(card+'\n')
        else:
            print("Getting DuelCommander banned list from local file ...")
            with open(XMAGE_DUELCOMMANDER_BANNED_LIST_FILE, 'r', encoding="utf8") as f_read:
                commander_banned_cards += list(map(str.strip, list(f_read)))

    return sorted(set(commander_banned_cards))

def get_oracle_texts(card):
    """Return a list of 'oracle_text', one per card's faces"""
    return ([card['oracle_text']] if 'oracle_text' in card
            else ([face['oracle_text'] for face in card['card_faces']]
                  if 'card_faces' in card and card['card_faces'] else ''))

def get_mana_cost(card):
    """Return a list of 'mana_cost', one per card's faces"""
    return ([card['mana_cost']] if 'mana_cost' in card
            else ([face['mana_cost'] for face in card['card_faces']]
                  if 'card_faces' in card and card['card_faces'] else ''))

def get_type_lines(card):
    """Return a list of 'type_line', one per card's faces"""
    return ([card['type_line']] if 'type_line' in card
            else ([face['type_line'] for face in card['card_faces']]
                  if 'card_faces' in card and card['card_faces'] else ''))

def get_power_defenses(card):
    """Return a list of 'power' and 'toughness', one per card's faces"""
    return ([card['power']+'/'+card['toughness']] if 'power' in card and 'toughness' in card
            else ([face['power']+'/'+face['toughness'] for face in card['card_faces']
                   if 'power' in face and 'toughness' in face]
                  if 'card_faces' in card and card['card_faces'] else ''))

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

def join_oracle_texts(card, truncate = False):
    """Return a string with card's oracle text joined"""
    return ' // '.join(map(
        lambda c: truncate_text(c, ((int(truncate / 2) - 2) if int(truncate) > 4
                                    and 'card_faces' in card else truncate)),
        get_oracle_texts(card))).replace('\n', ' ')

def order_cards_by_cmc_and_name(cards_list):
    """Return an ordered cards list by CMC + Mana cost length as a decimal, and Name"""
    return list(sorted(cards_list, key=lambda c: (
        str(c['cmc'] + float('0.'+str(len(c['mana_cost']) if 'mana_cost' in c else '0')))
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
        print_card(card, trunc_name = 25, trunc_text = 150, print_mana = False, print_type = False, print_power_def = False, indent = 5)
    print('')
    print('   Multicolors lands producers (not tapped or untappable):',
            len(cards_lands_multicolors_producers_not_tapped))
    print('')
    print('   Multicolors lands producers (not tapped or untappable, not selective):',
            len(cards_lands_multicolors_producers_not_tapped_not_selective))
    for card in cards_lands_multicolors_producers_not_tapped_not_selective:
        print_card(card, trunc_name = 25, trunc_text = 150, print_mana = False, print_type = False, print_power_def = False, indent = 5)
    print('')
    print('   Multicolors lands producers (not tapped or untappable, selective):',
            len(cards_lands_multicolors_producers_not_tapped_selective))
    for card in cards_lands_multicolors_producers_not_tapped_selective:
        print_card(card, trunc_name = 25, trunc_text = 150, print_mana = False, print_type = False, print_power_def = False, indent = 5)
    print('')
    print('   Multicolors lands producers (tapped):',
            len(cards_lands_multicolors_producers_tapped))
    print('')
    print('   Multicolors lands producers (tapped, no color selection, no charge counter, no pay {1}):',
            len(cards_lands_multicolors_producers_tapped_filtered))
    for card in cards_lands_multicolors_producers_tapped_filtered:
        print_card(card, trunc_name = 25, trunc_text = 150, print_mana = False, print_type = False, print_power_def = False, indent = 5)
    print('')

    print('Lands converters (total):', len(cards_lands_converters))
    print('')
    print('   Lands converters colorless producers (total):',
            len(cards_lands_converters_colorless_producers))
    print('')
    print('   Lands converters colorless producers (not tapped or untappable):',
            len(cards_lands_converters_colorless_producers_not_tapped))
    for card in cards_lands_converters_colorless_producers_not_tapped:
        print_card(card, trunc_name = 25, trunc_text = 150, print_mana = False, print_type = False, print_power_def = False, indent = 5)
    print('')
    print('   Lands converters colorless producers (tapped):',
            len(cards_lands_converters_colorless_producers_tapped))
    for card in cards_lands_converters_colorless_producers_tapped:
        print_card(card, trunc_name = 25, trunc_text = 150, print_mana = False, print_type = False, print_power_def = False, indent = 5)
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
        print_card(card, trunc_name = 25, trunc_text = 150, print_mana = False, print_type = False, print_power_def = False, indent = 5)
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
        print_card(card, trunc_name = 25, trunc_text = 150, print_mana = False, print_type = False, print_power_def = False, indent = 5)
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
    #     print_card(card, trunc_name = 25, trunc_text = 150, print_mana = False, print_type = False, print_power_def = False, indent = 5)
    # print('')
    # print('   Lands producers of mana that are nonbasic (no colorless, tapped):',
    #        len(cards_lands_producers_non_basic_no_colorless_tapped))
    # print('')
    # print('   Lands producers of mana that are nonbasic (colorless):',
    #         len(cards_lands_producers_non_basic_colorless))
    # for card in cards_lands_producers_non_basic_colorless:
    #     print_card(card, trunc_name = 25, trunc_text = 150, print_mana = False, print_type = False, print_power_def = False, indent = 5)
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
                            print_card(card, print_power_def = False, indent = 8,
                                       trunc_mana = 15, merge_type_power_def = False)
                        else:
                            print_card(card, print_power_def = (card_type == 'creature'),
                                       print_type = False, indent = 8, trunc_mana = 15,
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

def print_card(card, indent = 0, print_mana = True, print_type = True, print_power_def = True,
               trunc_name = 25, trunc_type = 16, trunc_text = 115, trunc_mana = 21,
               merge_type_power_def = True, return_str = False):
    """Display a card or return a string representing it"""
    if merge_type_power_def and (not trunc_type or trunc_type > 10):
        trunc_type = 10  # default power/defense length
    len_type = '16' if not trunc_type else str(trunc_type)

    card_line_format  = '{indent:<'+str(indent)+'}'
    card_line_format += ('{mana_cost:>'+('21' if not trunc_mana else str(trunc_mana))+'} | '
                         if print_mana else '{mana_cost}')
    if merge_type_power_def:
        if print_power_def or print_type:
            if is_creature(card) and print_power_def:
                card_line_format += '{power_defenses:>'+len_type+'} | '
            elif print_type:
                card_line_format += '{type_lines:>'+len_type+'} | '
            else:
                card_line_format += '{power_defenses:<'+len_type+'} | '
        else:
            card_line_format += '{power_defenses}{type_lines}'  # will print nothing
    else:
        card_line_format += '{power_defenses:>10} | ' if print_power_def else '{power_defenses}'
        card_line_format += '{type_lines:<'+len_type+'} | ' if print_type else '{type_lines}'
    card_line_format += '{name:<'+('40' if not trunc_name else str(trunc_name))+'} | '
    card_line_format += '{oracle_texts}'

    card_line_params = {
        'indent': ' ',
        'mana_cost': truncate_text((' // '.join(get_mana_cost(card)) if print_mana else ''),
                                   trunc_mana),
        'type_lines': truncate_text((' // '.join(get_type_lines(card)) if print_type else ''),
                                    trunc_type),
        'name': truncate_text(card['name'], trunc_name),
        'power_defenses': '',
        'oracle_texts': join_oracle_texts(card, trunc_text)}
    if print_power_def and is_creature(card):
        card_line_params['power_defenses'] = ' // '.join(get_power_defenses(card))
    card_line = card_line_format.format(**card_line_params)
    if not return_str:
        print(card_line)
    return card_line

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

def main():
    """Main program"""
    global COMMANDER_COLOR_IDENTITY
    global COMMANDER_COLOR_IDENTITY_COUNT
    global XMAGE_COMMANDER_CARDS_BANNED

    XMAGE_COMMANDER_CARDS_BANNED = get_xmage_commander_banned_list()

    with open("oracle-cards-20231026090142.json", "r", encoding="utf8") as r_file:
        cards = json.load(r_file)

        # TODO Add a parameter to exclude MTG sets by name or code

        total_cards = len(cards)
        #print_all_cards_stats(cards, total_cards)

        print('')
        print('')
        print('### Commander card ###')
        print('')

        print('Commander:', COMMANDER_NAME)

        commander_card = list(filter(lambda c: c['name'] == COMMANDER_NAME, cards))[0]
        if not commander_card:
            print("Error: failed to find the commander card '", COMMANDER_NAME, "'")
            sys.exit(1)
        commander_color_identity = commander_card['color_identity']
        print('Identity:', commander_color_identity)
        if not COMMANDER_COLOR_IDENTITY:
            COMMANDER_COLOR_IDENTITY = set(commander_card['color_identity'])
        COMMANDER_COLOR_IDENTITY_COUNT = len(COMMANDER_COLOR_IDENTITY)
        commander_colors = commander_card['colors']
        print('Colors:', commander_colors)
        commander_mana_cost = commander_card['mana_cost']
        commander_mana_cmc = commander_card['cmc']
        print('Mana:', commander_mana_cost, '(CMC:', commander_mana_cmc, ')')
        commander_type = commander_card['type_line']
        print('Type:', commander_type)
        commander_keywords = commander_card['keywords']
        print('Keywords:', commander_keywords, '+', COMMANDER_KEYWORDS)
        if not commander_keywords:
            commander_keywords = COMMANDER_KEYWORDS
        commander_keywords = set(commander_keywords)
        commander_text = commander_card['oracle_text']
        print('Text:', commander_text)

        print('')
        print('')
        print('### Stats for this deck ###')
        print('')

        # invalid colors
        compute_invalid_colors()
        prev_total_cards = total_cards
        cards_valid_colors = list(filter(filter_colors, cards))
        new_total_cards = len(cards_valid_colors)
        print('Invalid colors', INVALID_COLORS, ':', prev_total_cards - new_total_cards)
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

        # one common keyword
        # TODO use a regex to also include cards that have no keywords but a text that could match
        #      the keywords
        cards_common_keyword = list(
            filter(lambda c: bool(commander_keywords & set(c['keywords'])), cards_ok))
        new_total_cards = len(cards_common_keyword)
        print('One common keyword', commander_keywords, ':', new_total_cards)
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
                            print_card(card, print_power_def = False, indent = 5,
                                    trunc_mana = 15, merge_type_power_def = False)
                        else:
                            print_card(card, print_power_def = (card_type == 'creature'),
                                    print_type = False, indent = 5, trunc_mana = 15,
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

        # TODO select 7 removal cards (3 creatures, 4 artifacts/enchantments)
        cards_removal = assist_removal_cards([
            c for c in cards_ok if c not in cards_ramp_cards
            and c not in cards_draw_cards and c not in cards_tutor_cards])

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
    main()
