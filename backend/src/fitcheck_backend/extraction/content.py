"""Pure HTML/plain text extraction; fetching and validation live elsewhere."""
import json
import math
import re
from urllib.parse import urlsplit

from bs4 import BeautifulSoup

from .fields import currency, extract_competition, extract_description_fields, unique_skills


SITE_CHROME = (
    'script, style, noscript, nav, header, footer, form, [hidden], [aria-hidden="true"], '
    '[role~="navigation" i], [role~="banner" i], [role~="contentinfo" i]'
)


def remove_site_chrome(soup: BeautifulSoup) -> None:
    for node in soup.select(SITE_CHROME):
        node.decompose()


def normalized_lines(value: str) -> str:
    # Repeated labels may belong to different statistics; keep every occurrence
    # so downstream conflict detection sees all supplied evidence.
    return '\n'.join(line for raw in value.splitlines() if (line := re.sub(r'\s+', ' ', raw).strip()))


def fragment_text(value: str) -> str:
    value = re.sub(r'</(p|div|li|section|article|h[1-6])>', r'</\1>\n', value, flags=re.I)
    soup = BeautifulSoup(value, 'html.parser')
    remove_site_chrome(soup)
    for node in soup.find_all('br'):
        node.replace_with('\n')
    return normalized_lines(soup.get_text())


def structured_job(soup: BeautifulSoup) -> dict | None:
    for script in soup.select('script[type="application/ld+json"]'):
        try:
            value = json.loads(script.get_text())
        except (ValueError, RecursionError):
            continue
        pending = [(value, 0)]
        visited = 0
        while pending and visited < 10_000:
            candidate, depth = pending.pop()
            visited += 1
            if depth > 64:
                continue
            if isinstance(candidate, list):
                pending.extend((item, depth + 1) for item in reversed(candidate))
            elif isinstance(candidate, dict):
                types = candidate.get('@type')
                if types == 'JobPosting' or isinstance(types, list) and 'JobPosting' in types:
                    return candidate
                graph = candidate.get('@graph')
                if isinstance(graph, (list, dict)):
                    pending.append((graph, depth + 1))
    return None


def salary_fields(job: dict | None) -> dict:
    salary = (job or {}).get('baseSalary')
    if not isinstance(salary, dict) or not isinstance(salary.get('value'), dict):
        return {}
    value = salary['value']
    unit = str(value.get('unitText', '')).upper()
    if any(period in unit for period in ('MONTH', 'YEAR', 'ANNUAL', 'WEEK', 'DAY')):
        return {}
    hourly = 'HOUR' in unit
    def number(raw):
        if isinstance(raw, bool) or raw is None:
            return None
        try:
            result = float(raw)
            return result if math.isfinite(result) and 0 <= result <= (100_000 if hourly else 100_000_000) else None
        except (TypeError, ValueError, OverflowError):
            return None
    minimum = number(value.get('minValue', value.get('value')))
    maximum = number(value.get('maxValue', value.get('value')))
    if minimum is None or maximum is not None and maximum < minimum:
        return {}
    result = {'hourlyRateMin' if hourly else 'fixedBudget': minimum}
    if maximum is not None and (hourly or maximum != minimum):
        result['hourlyRateMax' if hourly else 'fixedBudgetMax'] = maximum
    code = currency(salary.get('currency')) if isinstance(salary.get('currency'), str) else None
    if code:
        result['budgetCurrency'] = code
    return result


def extract_content(body: str, *, content_type: str, source_url: str | None = None) -> dict:
    provenance = {}
    if content_type.split(';', 1)[0].strip().lower() == 'text/plain':
        lines = normalized_lines(body).split('\n')
        title, description = lines[0], '\n'.join(lines[1:])
        fields = extract_description_fields(description)
        fields.update(extract_competition(description))
        for field, value in {'title': title, 'description': description, **fields}.items():
            if value != [] and value != '':
                provenance[field] = 'text'
    else:
        soup = BeautifulSoup(body, 'html.parser')
        job = structured_job(soup) or {}
        remove_site_chrome(soup)
        def text(value):
            return value.strip() if isinstance(value, str) else ''
        meta = soup.select_one('meta[property="og:title"]')
        h1 = soup.find('h1')
        page_title = soup.find('title')
        title = text(job.get('title')) or text(meta.get('content') if meta else None) or (h1.get_text().strip() if h1 else '') or (page_title.get_text().strip() if page_title else '')
        if title:
            provenance['title'] = 'json_ld' if text(job.get('title')) else 'html'
        parsed_url = urlsplit(source_url or '')
        freelancer = parsed_url.hostname in ('freelancer.com', 'www.freelancer.com') and bool(re.match(r'^/projects/[^/]+/[^/]+', parsed_url.path))
        structured_description = text(job.get('description'))
        # Selector lists return the first DOM match, so a surrounding body/main
        # would otherwise win over the actual description nested inside it.
        selection = soup.select_one('.Project-description') if freelancer else next(
            (node for selector in ('[class*="job-description"], [data-test*="description"]', 'article', 'main', 'body')
             if (node := soup.select_one(selector)) is not None), None)
        if not selection and not freelancer:
            selection = soup
        if structured_description:
            description = fragment_text(structured_description)
        elif selection:
            copy = BeautifulSoup(str(selection), 'html.parser')
            # Only omit a duplicated task title; section headings can contain
            # requirements, delivery constraints and the only budget evidence.
            for heading in copy.select('h1'):
                if normalized_lines(heading.get_text()) == normalized_lines(title):
                    heading.decompose()
            description = fragment_text(str(copy))
        else:
            description = ''
        if description:
            provenance['description'] = 'json_ld' if structured_description else 'html'
        description_fields = extract_description_fields(description)
        headings = '\n'.join(node.get_text() for node in soup.select('.Project-heading h2')) if freelancer else ''
        heading_fields = extract_description_fields(headings)
        heading_money = {key: value for key, value in heading_fields.items() if key != 'skills'}
        fallback = heading_money or {key: value for key, value in description_fields.items() if key != 'skills'}
        salary = salary_fields(job)
        compatible = any(key in salary and salary[key] == fallback.get(key) for key in ('fixedBudget', 'hourlyRateMin')) and (not salary.get('budgetCurrency') or not fallback.get('budgetCurrency') or salary['budgetCurrency'] == fallback['budgetCurrency'])
        fields = {**(fallback if not salary or compatible else {}), **salary}
        for key in fields:
            provenance[key] = 'json_ld' if key in salary or structured_description and not heading_money else 'html'
        raw_skills = job.get('skills')
        structured_skills = [value for value in raw_skills if isinstance(value, str)] if isinstance(raw_skills, list) else re.split(r'[,;|]', raw_skills) if isinstance(raw_skills, str) else []
        visible_skills = [node.get_text() for node in soup.select('[class*="skill"] li, [data-test*="skill"]') if not freelancer or not node.find_parent(class_=re.compile(r'User-bid|proposal', re.I))]
        page_skills = unique_skills(structured_skills + visible_skills)
        fields['skills'] = page_skills or unique_skills(description_fields['skills'] + heading_fields['skills'])
        if fields['skills']:
            provenance['skills'] = 'json_ld' if structured_skills or structured_description and not page_skills else 'html'
        if freelancer:
            stats_nodes = soup.select('.Project-heading, .Project-stats, .Project-statistics')
            statistics = '\n'.join(BeautifulSoup(str(node), 'html.parser').get_text('\n') for node in stats_nodes)
        else:
            statistics = description
        competition = extract_competition(normalized_lines(statistics))
        fields.update(competition)
        provenance.update({key: 'json_ld' if structured_description and not freelancer else 'html' for key in competition})
    result = {'title': title[:300], 'description': description[:20_000], **fields, 'provenance': provenance}
    if source_url:
        result['url'] = source_url
        provenance['url'] = 'text' if content_type.split(';', 1)[0].strip().lower() == 'text/plain' else 'html'
    return result
