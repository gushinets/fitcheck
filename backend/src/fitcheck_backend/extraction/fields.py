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


def extract_description_fields(text: str) -> dict:
    explicit = []
    for match in re.finditer(r'^[ \t]*(?:required\s+skills|skills(?:\s+required)?|навыки|стек|технологии)[ \t]*:[ \t]*(?:\n[ \t]*)?([^\n]+)', text, re.I | re.M):
        explicit.extend(re.split(r'[,;|]', match[1]))
    mentioned = [skill for skill in KNOWN_SKILLS if re.search(r'(?<![^\W_])' + re.escape(skill) + r'(?![^\W_])', text, re.I)]
    candidates = []
    for line in text.splitlines():
        if UNSUPPORTED_PERIOD.search(line) or re.search(r'client\s+spend|average\s+bid', line, re.I):
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
    for line in text.splitlines():
        match = re.fullmatch(r'\s*(?:proposals?|bids?|total\s+bids?|number\s+of\s+bids?)\s*:?\s*(\d+(?:[, ]\d{3})*)\s*', line, re.I)
        if not match:
            match = re.fullmatch(r'\s*(\d+(?:[, ]\d{3})*)\s+(?:proposals?|bids?)\s*', line, re.I)
        if match:
            digits = re.sub(r'[, ]', '', match[1]).lstrip('0') or '0'
            if len(digits) <= 8:
                count = int(digits)
                if count <= 10_000_000:
                    counts.append(count)
        bid_label = re.fullmatch(r'\s*average\s+bid\s*:?\s*(.+?)\s*', line, re.I)
        if bid_label:
            bid = MONEY.fullmatch(bid_label[1])
            if not bid or bid['max']:
                continue
            tokens = [bid[key] for key in ('prefix', 'suffix') if bid[key]]
            currencies = [currency(token) for token in tokens]
            if any(value is None or value != currencies[0] for value in currencies):
                continue
            number = amount(bid['min'])
            if math.isfinite(number) and 0 <= number <= 100_000_000:
                fields = {'averageBid': number}
                if currencies:
                    fields['averageBidCurrency'] = currencies[0]
                bids.append(fields)
    result = {}
    if counts and len(set(counts)) == 1:
        result['proposalCount'] = counts[0]
    if bids and all(bid == bids[0] for bid in bids):
        result.update(bids[0])
    return result
