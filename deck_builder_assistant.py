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
COMMANDER_KEYWORDS_REGEXES = [
    r'(opponent|target player|owner).*(lose|have lost).*life',
    r'(you|target player|owner).*(gain|have gained).*life',
    r'(you|target player|owner).*(draw|have draw)']
COMMANDER_COLOR_IDENTITY = set([])
COMMANDER_COLOR_IDENTITY_COUNT = 0
INVALID_COLORS = set([])
LAND_MULTICOLORS_EXCLUDE_REGEX = r'('+('|'.join([
    'you may', 'reveal', 'only', 'gains', 'return', 'create']))+')'
LAND_MULTICOLORS_GENERIC_EXCLUDE_REGEX = r'('+('|'.join([
    'dragon', 'elemental', 'phyrexian', 'time lord', 'alien', 'gates', 'devoid', 'ally', 'pilot',
    'vehicule', 'sliver', 'vampire', 'cleric', 'rogue', 'warrior', 'wizard']))+')'
LAND_BICOLORS_EXCLUDE_REGEX = r'('+('|'.join([
    'you may reveal',
    'this turn',
    'more opponents',
    'depletion',
    'two or (more|fewer) other lands',
    'basic lands']))+')'
LAND_SACRIFICE_SEARCH_REGEX = r'sacrifice.*search.*land'
RAMP_CARDS_REGEX = r'('+('|'.join([
    '(look for|search|play).* land',
    'add \\{[CRGBUW0-9]',
    'add .* to your mana pool',
    'add .* of any color',
]))+')'
RAMP_CARDS_LAND_FETCH_REGEX = r'search(es)? (your|their) library for .* ' \
        '(land|'+('|'.join(map(lambda c: c.lower()+'s?', COLOR_TO_LAND.values())))+') card'
LAND_CYCLING_REGEX = r'(land ?|'+('|'.join(map(str.lower, COLOR_TO_LAND.values())))+')cycling'

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
    """Return the percentage of drawing multiples (k cards of a certain type which exist in a quantity m in the
       deck of size U), for a draw size of n (typically first hand is 7).
       see: https://en.wikipedia.org/wiki/Hypergeometric_distribution#Multivariate_hypergeometric_distribution
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
        if re.match(r'^{\w}$', item['mana_cost']):
            return 19
    if item['cmc'] == 2:
        if re.match(r'^{1}{\w}$', item['mana_cost']):
            return 19
        if re.match(r'^{\w}{\w}$', item['mana_cost']):
            return 30
    if item['cmc'] == 3:
        if re.match(r'^{2}{\w}$', item['mana_cost']):
            return 18
        if re.match(r'^{1}{\w}{\w}$', item['mana_cost']):
            return 28
        if re.match(r'^{\w}{\w}{\w}$', item['mana_cost']):
            return 36
    if item['cmc'] == 4:
        if re.match(r'^{3}{\w}$', item['mana_cost']):
            return 16
        if re.match(r'^{2}{\w}{\w}$', item['mana_cost']):
            return 26
        if re.match(r'^{1}{\w}{\w}{\w}$', item['mana_cost']):
            return 33
        if re.match(r'^{\w}{\w}{\w}{\w}$', item['mana_cost']):
            return 39
    if item['cmc'] == 5:
        if re.match(r'^{4}{\w}$', item['mana_cost']):
            return 15
        if re.match(r'^{3}{\w}{\w}$', item['mana_cost']):
            return 23
        if re.match(r'^{2}{\w}{\w}{\w}$', item['mana_cost']):
            return 30
        if re.match(r'^{1}{\w}{\w}{\w}{\w}$', item['mana_cost']):
            return 36
    if item['cmc'] == 6:
        if re.match(r'^{5}{\w}$', item['mana_cost']):
            return 14
        if re.match(r'^{4}{\w}{\w}$', item['mana_cost']):
            return 22
        if re.match(r'^{3}{\w}{\w}{\w}$', item['mana_cost']):
            return 28
    if item['cmc'] == 7:
        if re.match(r'^{5}{\w}{\w}$', item['mana_cost']):
            return 20
        if re.match(r'^{4}{\w}{\w}{\w}$', item['mana_cost']):
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
            else [face['oracle_text'] for face in card['card_faces']])

def in_strings(string, texts):
    """Search a string in a list of strings"""
    return filter(lambda t: string in t, texts)

def in_strings_exclude(string, exclude, texts):
    """Search for absence of a string in a list of strings or without the exclude string"""
    return filter(lambda t: string not in t or exclude in t, texts)

def not_in_strings_excludes(string, excludes, texts):
    """Search a string in a list of strings without the excludes strings"""
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
    return item['type_line'].startswith('Land') or item['type_line'].startswith('Legendary Land')

def filter_sacrifice(item):
    """Remove card if its text contains 'sacrifice' without containing 'unless'"""
    return bool(list(in_strings_exclude('sacrifice', 'unless',
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

def join_oracle_texts(card):
    """Return a string with card's oracle text joined"""
    return ' // '.join(get_oracle_texts(card)).replace('\n', ' ')

def order_cards_by_cmc_and_name(cards_list):
    """Return an ordered cards list by CMC and Name"""
    return list(sorted(cards_list, key=lambda c: str(c['cmc'])+c['name']))

def main():
    """Main program"""
    global COMMANDER_COLOR_IDENTITY
    global COMMANDER_COLOR_IDENTITY_COUNT
    global XMAGE_COMMANDER_CARDS_BANNED

    XMAGE_COMMANDER_CARDS_BANNED = get_xmage_commander_banned_list()

    with open("oracle-cards-20231026090142.json", "r", encoding="utf8") as r_file:
        cards = json.load(r_file)

        # TODO Add a parameter to exclude MTG sets by name or code

        # for card in cards:
        #     if card['name'].lower().startswith('chalice of life'):
        #         print(card['name'], ':')
        #         pp = pprint.PrettyPrinter(indent=4)
        #         pp.pprint(card)
        #         print('')

        print('')
        print('### All Cards Stats ###')
        print('')

        total_cards = len(cards)
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

        # lands selection
        selected_lands = []
        lands = list(filter(filter_lands, cards_ok))
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
        land_types_invalid = [COLOR_TO_LAND[c] for c in INVALID_COLORS]
        land_types_invalid_regex = r'('+('|'.join(land_types_invalid)).lower()+')'
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

        # non-basic lands that are producers
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
        cards_lands_producers_non_basic_fetchable = list(filter(
            lambda c: re.search(
                r'('+('|'.join(map(str.lower, COLOR_TO_LAND.values())))+')',
                c['type_line'].lower()),
            cards_lands_producers_non_basic))

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
            print('      ', card['name'], ' ', join_oracle_texts(card))
        print('')
        print('   Multicolors lands producers (not tapped or untappable):',
              len(cards_lands_multicolors_producers_not_tapped))
        print('')
        print('   Multicolors lands producers (not tapped or untappable, not selective):',
              len(cards_lands_multicolors_producers_not_tapped_not_selective))
        for card in cards_lands_multicolors_producers_not_tapped_not_selective:
            print('      ', card['name'], ' ', join_oracle_texts(card))
        print('')
        print('   Multicolors lands producers (not tapped or untappable, selective):',
              len(cards_lands_multicolors_producers_not_tapped_selective))
        for card in cards_lands_multicolors_producers_not_tapped_selective:
            print('      ', card['name'], ' ', join_oracle_texts(card))
        print('')
        print('   Multicolors lands producers (tapped):',
              len(cards_lands_multicolors_producers_tapped))
        print('')
        print('   Multicolors lands producers (tapped, no color selection, no charge counter, no pay {1}):',
              len(cards_lands_multicolors_producers_tapped_filtered))
        for card in cards_lands_multicolors_producers_tapped_filtered:
            print('      ', card['name'], ' ', join_oracle_texts(card))
        print('')

        print('Lands converters (total):', len(cards_lands_converters))
        print('')
        print('   Lands converters colorless producers (total):',
              len(cards_lands_converters_colorless_producers))
        print('')
        print('   Lands converters colorless producers (not tapped or untappable):',
              len(cards_lands_converters_colorless_producers_not_tapped))
        for card in cards_lands_converters_colorless_producers_not_tapped:
            print('      ', card['name'], ' ', join_oracle_texts(card))
        print('')
        print('   Lands converters colorless producers (tapped):',
              len(cards_lands_converters_colorless_producers_tapped))
        for card in cards_lands_converters_colorless_producers_tapped:
            print('      ', card['name'], ' ', join_oracle_texts(card))
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
            print('   ', card['produced_mana'], ' ', card['name'], ' ', join_oracle_texts(card))
        print('')
        print('Bicolors lands (filtered, tapped):',
              len(cards_lands_bicolors_filtered_tapped))
        # for card in cards_lands_bicolors_filtered_tapped:
        #     print('   ', card['produced_mana'], ' ', card['name'], ' ', join_oracle_texts(card))
        print('')

        print('Land types not matching commander:', land_types_invalid)
        print('Sacrifice/Search lands:', len(cards_lands_sacrifice_search))
        print('Sacrifice/Search lands (not tapped or untappable):',
              len(cards_lands_sacrifice_search_no_tapped))
        for card in cards_lands_sacrifice_search_no_tapped:
            print('   ', card['name'], ' ', join_oracle_texts(card))
        print('')

        print('Lands producers of mana that are non-basic:', len(cards_lands_producers_non_basic))
        print('')
        # NOTE: those fetchable lands are useless
        # print('   Lands producers of mana that are non-basic (fetchable):',
        #       len(cards_lands_producers_non_basic_fetchable))
        # for card in cards_lands_producers_non_basic_fetchable:
        #     print('      ', card['name'], ' ', join_oracle_texts(card))
        # print('')
        print('   Lands producers of mana that are non-basic (no colorless):',
              len(cards_lands_producers_non_basic_no_colorless))
        for card in cards_lands_producers_non_basic_no_colorless:
            print('      ', card['name'], ' ', join_oracle_texts(card))
        print('')
        print('   Lands producers of mana that are non-basic (colorless):',
              len(cards_lands_producers_non_basic_colorless))
        for card in cards_lands_producers_non_basic_colorless:
            print('      ', card['name'], ' ', join_oracle_texts(card))
        print('')
        print('')

        # TODO select monocolor lands to match 37 lands cards (at the end)
        #      42 cards recommanded: @see https://www.channelfireball.com/article/What-s-an-Optimal-Mana-Curve-and-Land-Ramp-Count-for-Commander/e22caad1-b04b-4f8a-951b-a41e9f08da14/
        #      - 3 land for each 5 ramp cards
        #      - 2 land for each 5 draw cards

        # # TODO select 5 ramp cards that are land related (search or play)
        cards_ramp_cards_land_fetch = []
        cards_ramp_cards_land_fetch_rest = []
        cards_ramp_cards_land_fetch_artifacts = []
        cards_ramp_cards_land_fetch_instants = []
        cards_ramp_cards_land_fetch_sorcery = []
        cards_ramp_cards_land_fetch_enchantments = []
        cards_ramp_cards_land_fetch_creatures = []
        cards_ramp_cards_land_fetch_channel = []
        for card in cards_ok:
            card_oracle_texts = list(get_oracle_texts(card))
            card_oracle_texts_low = list(map(str.lower, card_oracle_texts))
            if (bool(list(search_strings(RAMP_CARDS_LAND_FETCH_REGEX, card_oracle_texts_low)))
                    and not list(search_strings(land_types_invalid_regex, card_oracle_texts_low))
                    and not list(search_strings(r'(you|target player|opponent).*discard',
                                                card_oracle_texts_low))
                    and card['name'] not in ['Mana Severance', 'Settle the Wreckage']
                    and not filter_lands(card)):
                if bool(list(in_strings('channel', card_oracle_texts_low))):
                    cards_ramp_cards_land_fetch_channel.append(card)
                elif ('creature' in card['type_line'].lower()
                        or 'vehicle' in card['type_line'].lower()):
                    cards_ramp_cards_land_fetch_creatures.append(card)
                elif 'instant' in card['type_line'].lower():
                    cards_ramp_cards_land_fetch_instants.append(card)
                elif 'sorcery' in card['type_line'].lower():
                    cards_ramp_cards_land_fetch_sorcery.append(card)
                elif 'enchantment' in card['type_line'].lower():
                    cards_ramp_cards_land_fetch_enchantments.append(card)
                elif 'artifact' in card['type_line'].lower():
                    cards_ramp_cards_land_fetch_artifacts.append(card)
                else:
                    cards_ramp_cards_land_fetch_rest.append(card)
           #elif card['name'] == "Archaeomancer's Map":
           #    print('DEBUG', RAMP_CARDS_LAND_FETCH_REGEX)
           #    print('DEBUG', card['name'], 'text:', '|'.join(card_oracle_texts_low))
           #    print('DEBUG', card['name'], 'match?:', bool(list(search_strings(RAMP_CARDS_LAND_FETCH_REGEX, card_oracle_texts_low))))
           #    print('DEBUG', card['name'], 'invalid land?:', not list(search_strings(land_types_invalid_regex, card_oracle_texts_low)))
           #    print('DEBUG', card['name'], 'discard?:', not list(search_strings(r'(you|target player|opponent).*discard', card_oracle_texts_low)))
           #    print('DEBUG', card['name'], 'land?:', not filter_lands(card))
        cards_ramp_cards_land_fetch_rest = order_cards_by_cmc_and_name(cards_ramp_cards_land_fetch_rest)
        cards_ramp_cards_land_fetch_enchantments = order_cards_by_cmc_and_name(cards_ramp_cards_land_fetch_enchantments)
        cards_ramp_cards_land_fetch_artifacts = order_cards_by_cmc_and_name(cards_ramp_cards_land_fetch_artifacts)
        cards_ramp_cards_land_fetch_creatures = order_cards_by_cmc_and_name(cards_ramp_cards_land_fetch_creatures)
        cards_ramp_cards_land_fetch_channel = order_cards_by_cmc_and_name(cards_ramp_cards_land_fetch_channel)
        cards_ramp_cards_land_fetch_instants = order_cards_by_cmc_and_name(cards_ramp_cards_land_fetch_instants)
        cards_ramp_cards_land_fetch_sorcery = order_cards_by_cmc_and_name(cards_ramp_cards_land_fetch_sorcery)
        cards_ramp_cards_land_fetch = order_cards_by_cmc_and_name(
            cards_ramp_cards_land_fetch_rest +
            cards_ramp_cards_land_fetch_enchantments +
            cards_ramp_cards_land_fetch_artifacts +
            cards_ramp_cards_land_fetch_creatures +
            cards_ramp_cards_land_fetch_channel +
            cards_ramp_cards_land_fetch_instants +
            cards_ramp_cards_land_fetch_sorcery)
        print('Ramp cards land fetch (total):', len(cards_ramp_cards_land_fetch))
        print('')
        print('   Ramp cards land fetch (enchantments):', len(cards_ramp_cards_land_fetch_enchantments))
        for card in cards_ramp_cards_land_fetch_enchantments:
            print('      ', card['mana_cost'] if 'mana_cost' in card else '  ?  ', ' ', card['name'], ' ', join_oracle_texts(card))
        print('')
        print('   Ramp cards land fetch (artifacts):', len(cards_ramp_cards_land_fetch_artifacts))
        for card in cards_ramp_cards_land_fetch_artifacts:
            print('      ', card['mana_cost'] if 'mana_cost' in card else '  ?  ', ' ', card['name'], ' ', join_oracle_texts(card))
        print('')
        print('   Ramp cards land fetch (creature):', len(cards_ramp_cards_land_fetch_creatures))
        for card in cards_ramp_cards_land_fetch_creatures:
            print('      ', card['mana_cost'] if 'mana_cost' in card else '  ?  ', ' ', card['name'], ' ', join_oracle_texts(card))
        print('')
        cards_ramp_cards_land_fetch_land_cycling = order_cards_by_cmc_and_name(list(
            filter(
                lambda c: not list(search_strings(land_types_invalid_regex,
                                                  map(str.lower, get_oracle_texts(c)))),
                filter(
                    lambda c: list(search_strings(LAND_CYCLING_REGEX,
                                                  map(str.lower, get_oracle_texts(c)))),
                    cards_ok))))
        print('')
        print('   Ramp cards land fetch (land cycling):', len(cards_ramp_cards_land_fetch_land_cycling))
        for card in cards_ramp_cards_land_fetch_land_cycling:
            print('      ', card['mana_cost'] if 'mana_cost' in card else '  ?  ', ' ', card['name'], ' ', join_oracle_texts(card))
        print('')
        print('   Ramp cards land fetch (channel):', len(cards_ramp_cards_land_fetch_channel))
        for card in cards_ramp_cards_land_fetch_channel:
            print('      ', card['mana_cost'] if 'mana_cost' in card else '  ?  ', ' ', card['name'], ' ', join_oracle_texts(card))
        print('')
        print('   Ramp cards land fetch (instants):', len(cards_ramp_cards_land_fetch_instants))
        for card in cards_ramp_cards_land_fetch_instants:
            print('      ', card['mana_cost'] if 'mana_cost' in card else '  ?  ', ' ', card['name'], ' ', join_oracle_texts(card))
        print('')
        print('   Ramp cards land fetch (sorcery):', len(cards_ramp_cards_land_fetch_sorcery))
        for card in cards_ramp_cards_land_fetch_sorcery:
            print('      ', card['mana_cost'] if 'mana_cost' in card else '  ?  ', ' ', card['name'], ' ', join_oracle_texts(card))
        print('')
        print('   Ramp cards land fetch (rest):', len(cards_ramp_cards_land_fetch_rest))
        for card in cards_ramp_cards_land_fetch_rest:
            print('      ', card['mana_cost'] if 'mana_cost' in card else '  ?  ', ' ', card['name'], ' ', join_oracle_texts(card))
        print('')


        # cards_ramp_cards = []
        # for card in cards_ok:
        #     card_oracle_texts = list(get_oracle_texts(card))
        #     card_oracle_texts_low = list(map(str.lower, card_oracle_texts))
        #     if (bool(list(search_strings(RAMP_CARDS_REGEX, card_oracle_texts_low)))
        #             and not list(search_strings(land_types_invalid_regex, card_oracle_texts_low))
        #             and not list(search_strings(r'(you|target player|opponent).*discard',
        #                                         card_oracle_texts_low))
        #             and not list(search_strings(
        #                             r'\{T\}, Sacrifice [A-Za-z\' ]+: Add one mana of any color\.',
        #                             get_oracle_texts(card)))
        #             and not list(in_strings('graveyard', card_oracle_texts_low))
        #             and not list(in_strings('{T}: Add one mana of any color', card_oracle_texts))
        #             and not filter_lands(card)):
        #         cards_ramp_cards.append(card)
        # cards_ramp_cards = list(sorted(cards_ramp_cards, key=lambda c: c['cmc']))
        # new_total_cards = len(cards_ramp_cards)
        # print('Ramp cards:', new_total_cards)
        # for card in cards_ramp_cards:
        #     print('   ', card['mana_cost'] if 'mana_cost' in card else ' ? ', ' ', card['type_line'] ,' ', card['name'], ' ', join_oracle_texts(card))
        # print('')

        # TODO include the cards below ?
        # allow tapped lands
        #    {1}     "Amulet of Vigor": permanents entering the game are untapped
        #    {2} 1/3 "Tiller Engine": lands entering the game are untapped or tap an opponent's nonland permanent
        # combo with anything that produces 2 or more mana
        #    {2}{U} 2/3 "Clever Conjurer": {T} untap target permanent
        #    {2}{U} 1/3 "Vizier of Tumbling Sand's": {T} untap target permanent
        #    {2}{U} 2/2 "Kelpie Guide": {T} untap target permanent
        #    {2}{U} 1/4 "Ioreth of the Healing House": {T} untap target permanent or two legd-creatures

        # TODO select 5 multicolor ramp cards (artifacts ?)

        # TODO select 5 colorless ramp cards (artifacts ?)

        # TODO select 10 draw cards

        # TODO select 7 tutors

        # TODO select 25 cards combos (starting with the commander and the selected cards)

        # TODO select 7 removal cards (3 creatures, 4 artifacts/enchantments)

        # TODO select 3 board wipe cards

        # TODO select 1 graveyard hate

        # TODO select 1 'I win' suprise card

        # for index, card in enumerate(deck_cards):
            # print(card['name'])

if __name__ == '__main__':
    main()
