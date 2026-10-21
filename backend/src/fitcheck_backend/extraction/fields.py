"""Conservative field extraction from task text, without inferred budgets."""
import math
import re

KNOWN_SKILLS = ('n8n', 'Make.com', 'Google Sheets', 'Shopify', 'TypeScript', 'JavaScript', 'Python', 'React', 'PostgreSQL', 'Docker', 'C#', 'ESP32', 'LoRa', 'Rhino', 'Grasshopper', 'Lead Generation', 'LinkedIn', 'WhatsApp', 'API', 'JSON', 'Webhooks')
NUMBER = r'\d+(?:[ ,.\u00a0]\d{3})*(?:[.,]\d{1,2})?'
CURRENCY = r'USD|EUR|RUB|руб\.?|₽|€|\$|(?-i:[A-Z]{3})\b'
MONEY = re.compile(rf'(?P<prefix>{CURRENCY})?\s*(?P<min>{NUMBER})(?:\s*[-–—]\s*(?P<second>{CURRENCY})?\s*(?P<max>{NUMBER}))?\s*(?P<suffix>{CURRENCY})?', re.I)
LABEL = re.compile(r'\bbudget\b|бюджет|\brate\b|\bhourly\b|ставка|оплата', re.I)
UNSUPPORTED_PERIOD = re.compile(
    r'per\s+(?:day|week|month|year|annum)\b|/\s*(?:day|week|month|year|annum)\b'
    r'|\b(?:daily|weekly|monthly|yearly|annual|annually)\b'
    r'|в\s+(?:день|неделю|месяц|год)\b'
    r'|\b(?:дневн|недельн|месячн|годов|ежедневн|еженедельн|ежемесячн|ежегодн)\w*\b',
    re.I,
)
HOURLY = re.compile(r'\bhourly\b|\brate\b|ставка|per\s+hour|/\s*(?:h\b|hr\b|hour\b|час)|в\s+час', re.I)
PROPOSAL_LABEL = r'(?:proposals?|bids?|total\s+bids?|number\s+of\s+bids?|отклик(?:и|ов|а)?|предложени(?:е|я|й))'
BID_LABEL = r'(?:average\s+bid|avg\.?\s+bid|средн(?:ий|яя|ее)\s+(?:бид|ставка|предложение))'
PROPOSAL_NUMBER = r'\d+(?:[, ]\d{3})*'


def currency(value: str | None) -> str | None:
    if not value:
        return None
    return {'USD': 'USD', '$': 'USD', 'EUR': 'EUR', '€': 'EUR', 'RUB': 'RUB', '₽': 'RUB', 'РУБ': 'RUB', 'РУБ.': 'RUB'}.get(value.strip().upper())


def amount(value: str) -> float:
    value = re.sub(r'[ \u00a0]', '', value)
    if re.fullmatch(r'\d{1,3}(,\d{3})+(\.\d+)?', value):
        value = value.replace(',', '')
    elif re.fullmatch(r'\d{1,3}(\.\d{3})+(,\d+)?', value):
        value = value.replace('.', '').replace(',', '.')
    elif ',' in value:
        value = value.replace('.', '').replace(',', '.')
    return float(value)


def unique_skills(values: list[str]) -> list[str]:
    result, seen = [], set()
    for value in values:
        skill = re.sub(r'\s+', ' ', value).strip()[:80]
        key = skill.casefold()
        if skill and key not in seen:
            seen.add(key)
            result.append(skill)
    return result[:100]


def competition_lines(text: str) -> list[str]:
    """Join an isolated statistic label with its adjacent value, in either order."""
    lines = [line for raw in text.splitlines() if (line := re.sub(r'\s+', ' ', raw).strip())]
    count_label = re.compile(PROPOSAL_LABEL + r'\s*:?$', re.I).fullmatch
    bid_label = re.compile(BID_LABEL + r'\s*:?$', re.I).fullmatch
    count = re.compile(r'[+−-]?\d').match
    result, index = [], 0
    while index < len(lines):
        line = lines[index]
        if index + 1 < len(lines):
            following = lines[index + 1]
            reverse_value = (count_label(following) and count(line)) or (bid_label(following) and MONEY.fullmatch(line))
            if reverse_value and index + 2 < len(lines):
                after = lines[index + 2]
                if (count_label(following) and count(after)) or (bid_label(following) and MONEY.fullmatch(after)):
                    # Both neighbours could belong to this label. Keep both as
                    # candidates, excluding both from budgets, and detect conflict.
                    result.extend([following + ' ' + line, following + ' ' + after])
                    index += 3
                    continue
            if ((count_label(line) and count(following)) or
                    (bid_label(line) and MONEY.fullmatch(following)) or
                    reverse_value):
                line += ' ' + following
                index += 1
        result.append(line)
        index += 1
    return result


def extract_description_fields(text: str) -> dict:
    explicit = []
    for match in re.finditer(r'^[ \t]*(?:required\s+skills|skills(?:\s+required)?|навыки|стек|технологии)[ \t]*:[ \t]*(?:\n[ \t]*)?([^\n]+)', text, re.I | re.M):
        explicit.extend(re.split(r'[,;|]', match[1]))
    mentioned = [skill for skill in KNOWN_SKILLS if re.search(r'(?<![^\W_])' + re.escape(skill) + r'(?![^\W_])', text, re.I)]
    candidates = []
    for line in competition_lines(text):
        if UNSUPPORTED_PERIOD.search(line) or re.search(r'client\s+spend|' + BID_LABEL, line, re.I):
            continue
        labelled = LABEL.search(line)
        for match in MONEY.finditer(line):
            if not labelled and re.sub(r'/\s*(?:h|hr|hour|час)\b', '', line[:match.start()] + line[match.end():], flags=re.I).strip():
                continue
            before = line[:match.start()]
            if before.rstrip().endswith(('-', '−')):
                continue
            tokens = [match[name] for name in ('prefix', 'second', 'suffix') if match[name]]
            currencies = [currency(token) for token in tokens]
            if (not tokens and not labelled) or any(entry is None or entry != currencies[0] for entry in currencies):
                continue
            if not tokens and not LABEL.search(before):
                continue
            minimum = amount(match['min'])
            maximum = amount(match['max']) if match['max'] else minimum
            hourly = bool(HOURLY.search(line))
            if minimum < 0 or maximum < minimum or not math.isfinite(maximum) or maximum > (100_000 if hourly else 100_000_000):
                continue
            fields = {'budgetCurrency': currencies[0]} if currencies else {}
            minimum_only = not match['max'] and re.search(r'(?:\bfrom|\bstarting\s+at|от)\s*$', before, re.I)
            maximum_only = not match['max'] and re.search(r'(?:\bup\s+to|до)\s*$', before, re.I)
            if hourly:
                if not maximum_only:
                    fields['hourlyRateMin'] = minimum
                if not minimum_only:
                    fields['hourlyRateMax'] = maximum
            else:
                fields['fixedBudget'] = minimum
                if match['max']:
                    fields['fixedBudgetMax'] = maximum
            if fields not in candidates:
                candidates.append(fields)
    return {'skills': unique_skills(explicit + mentioned), **(candidates[0] if len(candidates) == 1 else {})}


def extract_competition(text: str) -> dict:
    """Only labelled, unambiguous project statistics are evidence."""
    counts, bids = [], []
    ambiguous_count = ambiguous_bid = False
    for line in competition_lines(text):
        # An isolated label whose value could not be paired is unresolved
        # evidence, not permission to select a different occurrence of the field.
        if re.fullmatch(PROPOSAL_LABEL + r'\s*:?', line, re.I):
            ambiguous_count = True
        if re.fullmatch(BID_LABEL + r'\s*:?', line, re.I):
            ambiguous_bid = True
        count_stat = re.fullmatch(rf'{PROPOSAL_LABEL}\s*:?\s*(.+)', line, re.I)
        if not count_stat:
            count_stat = re.fullmatch(rf'(.+?)\s+{PROPOSAL_LABEL}', line, re.I)
        if re.search(BID_LABEL, line, re.I):
            count_stat = None  # "Average bid" is not a proposal-count label.
        match = re.fullmatch(rf'{PROPOSAL_LABEL}\s*:?\s*({PROPOSAL_NUMBER})', line, re.I)
        if not match:
            match = re.fullmatch(rf'({PROPOSAL_NUMBER})\s+{PROPOSAL_LABEL}', line, re.I)
        if match:
            digits = re.sub(r'[, ]', '', match[1]).lstrip('0') or '0'
            if len(digits) <= 8 and int(digits) <= 10_000_000:
                counts.append(int(digits))
            else:
                ambiguous_count = True
        elif count_stat and re.search(r'\d', count_stat[1]):
            ambiguous_count = True
        bid_label = re.fullmatch(rf'{BID_LABEL}\s*:?\s*(.+)', line, re.I)
        if not bid_label:
            bid_label = re.fullmatch(rf'(.+?)\s+{BID_LABEL}', line, re.I)
        if bid_label:
            bid = MONEY.fullmatch(bid_label[1])
            if not bid or bid['max']:
                ambiguous_bid = True
                continue
            tokens = [bid[key] for key in ('prefix', 'suffix') if bid[key]]
            currencies = [currency(token) for token in tokens]
            if any(value is None or value != currencies[0] for value in currencies):
                ambiguous_bid = True
                continue
            number = amount(bid['min'])
            if math.isfinite(number) and 0 <= number <= 100_000_000:
                fields = {'averageBid': number}
                if currencies:
                    fields['averageBidCurrency'] = currencies[0]
                bids.append(fields)
            else:
                ambiguous_bid = True
    result = {}
    if counts and not ambiguous_count and len(set(counts)) == 1:
        result['proposalCount'] = counts[0]
    if bids and not ambiguous_bid and all(bid == bids[0] for bid in bids):
        result.update(bids[0])
    return result
