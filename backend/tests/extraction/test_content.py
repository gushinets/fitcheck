import json
from pathlib import Path

import pytest

from fitcheck_backend.extraction.content import extract_content

FIXTURES = Path(__file__).resolve().parents[3] / 'lib/extraction/__fixtures__'


def html(body, url='https://jobs.example/42'):
    return extract_content(body, content_type='text/html', source_url=url)


def test_plain_text():
    result = extract_content('\nBackend API Developer\n\nBuild reliable APIs.\nOwn database performance.\n', content_type='text/plain')
    assert result == {'title': 'Backend API Developer', 'description': 'Build reliable APIs.\nOwn database performance.', 'skills': [], 'provenance': {'title': 'text', 'description': 'text'}}


def test_structured_fixture():
    result = html((FIXTURES / 'job-page.html').read_text())
    assert result['title'] == 'Senior TypeScript Engineer'
    assert result['description'] == 'Build and maintain a multi-tenant SaaS platform.\nWork with a distributed product team.'
    assert result['skills'] == ['TypeScript', 'React', 'PostgreSQL']
    assert result['hourlyRateMin'] == 40
    assert result['hourlyRateMax'] == 60
    assert result['budgetCurrency'] == 'USD'
    assert result['provenance']['description'] == 'json_ld'
    assert result['url'] == 'https://jobs.example/42'
    assert 'proposalCount' not in result


@pytest.mark.parametrize(('name', 'title', 'snippet'), [
    ('n8n', 'n8n Automation Developer Needed', 'Hiring: n8n Automation Developer'),
    ('whatsapp', 'Configuración Closer Ventas WhatsApp', 'Necesito convertir mi línea de WhatsApp Business'),
    ('lead-generation', 'B2B Lead Generation Specialist Needed', 'CRITICAL REQUIREMENTS FOR APPLICANTS'),
    ('shopify', 'Shopify and Foxway API Bridge Development', 'bridge integration between Foxway'),
])
def test_freelancer(name, title, snippet):
    result = html((FIXTURES / f'freelancer-{name}.html').read_text(), f'https://www.freelancer.com/projects/test/{name}')
    assert result['title'] == title
    assert snippet in result['description']
    assert 'Unrelated bidder proposal' not in result['description']
    assert 'Hire freelancers' not in result['description']
    assert result['fixedBudget'] == 250
    assert result['fixedBudgetMax'] == 750
    assert result['budgetCurrency'] == ('EUR' if name == 'lead-generation' else 'USD')
    assert result['skills']


def test_structured_coherent_money_and_fallback():
    body = (FIXTURES / 'job-page.html').read_text().replace('Build and maintain', 'Budget: €250–750<br>Build and maintain')
    assert html(body)['budgetCurrency'] == 'USD'
    job = {'@type': 'JobPosting', 'title': 'Lead Generation', 'description': 'Budget: €250–750', 'baseSalary': {'value': {'minValue': 250}}}
    result = html('<script type="application/ld+json">' + json.dumps(job) + '</script>')
    assert {key: result[key] for key in ['fixedBudget', 'fixedBudgetMax', 'budgetCurrency']} == {'fixedBudget': 250, 'fixedBudgetMax': 750, 'budgetCurrency': 'EUR'}
    assert result['provenance']['fixedBudgetMax'] == 'json_ld'


def test_cleanup_and_first_dom_match():
    result = html('<title>Task</title><nav>Login</nav><article><h1>Heading</h1><p>Build APIs with Python.</p><script>Bad</script><style>Bad</style><p hidden>Secret</p><form>Submit</form></article><main>Wrong fallback</main>')
    assert result['title'] == 'Heading'
    assert result['description'] == 'Build APIs with Python.'


def test_description_container_wins_over_page_chrome_and_keeps_requirement_headings():
    result = html('''<html><head><title>API project</title></head><body>
        <div>Hire freelancers Log In Post a Project</div>
        <main><div>Recommended projects: Budget: $9000</div>
        <article><h1>API project</h1><h2>Requirements</h2>
        <p>Implement the “Log In” and “Post a Project” screens with Python.</p>
        <h3>Budget: €250–750</h3><h4>Delivery in two weeks</h4></article></main>
        <div>Related projects: Proposals: 999</div></body></html>''')
    assert result['description'] == ('Requirements\n'
        'Implement the “Log In” and “Post a Project” screens with Python.\n'
        'Budget: €250–750\nDelivery in two weeks')
    assert result['fixedBudget'] == 250 and result['fixedBudgetMax'] == 750
    assert result['budgetCurrency'] == 'EUR'
    assert 'proposalCount' not in result


@pytest.mark.parametrize('structured', [False, True])
def test_navigation_roles_are_removed_before_description_fields(structured):
    description = '''<div role="navigation">Hire freelancers Log In Post a Project
        <ul class="skills"><li>Docker</li></ul><p>Budget: $9000</p>
        <p>Proposals: 999</p></div><h2>Requirements</h2>
        <p>Build reliable Python workflows.</p><h3>Budget: €250–750</h3>
        <div role="contentinfo">Help Center</div>'''
    if structured:
        job = {'@type': 'JobPosting', 'title': 'API project', 'description': description}
        body = '<script type="application/ld+json">' + json.dumps(job) + '</script>'
    else:
        body = '<h1>API project</h1><article>' + description + '</article>'
    result = html(body)
    assert result['description'] == 'Requirements\nBuild reliable Python workflows.\nBudget: €250–750'
    assert result['skills'] == ['Python']
    assert result['fixedBudget'] == 250 and result['fixedBudgetMax'] == 750
    assert 'proposalCount' not in result


@pytest.mark.parametrize('name', ['n8n', 'whatsapp', 'lead-generation', 'shopify'])
def test_parent_report_pages_keep_every_requirement_and_budget_without_site_chrome(name):
    body = (FIXTURES / f'freelancer-{name}.html').read_text()
    url = f'https://www.freelancer.com/projects/test/{name}'
    baseline = html(body, url)
    # The same task pages with alternate accessible site navigation wrappers.
    noisy = body.replace('<nav>', '<div role="navigation">').replace('</nav>', '</div>')
    noisy = noisy.replace('</body>', '<div role="contentinfo">Log In Post a Project</div></body>')
    result = html(noisy, url)
    assert result == baseline
    assert all(label not in result['description'] for label in ('Hire freelancers', 'Log In', 'Post a Project'))


def test_freelancer_competition_ignores_bidder_labels():
    body = '<h1>Task</h1><div class="Project-heading"><h2>$250-750 USD</h2><span>Proposals: 18</span><span>Average bid: $330 USD</span></div><p class="Project-description">Build workflows with Python.</p><div class="User-bid-text">Proposals: 999\nAverage bid: €1000</div>'
    result = html(body, 'https://freelancer.com/projects/python/task')
    assert result['proposalCount'] == 18
    assert result['averageBid'] == 330
    assert result['averageBidCurrency'] == 'USD'


@pytest.mark.parametrize('text', ['Proposals: 1.5\nAverage bid: $300 €400', 'Proposals: -1\nAverage bid: -$30', 'Proposals: 10000001\nAverage bid: $100000001'])
def test_invalid_competition_omitted(text):
    result = extract_content('Task\n' + text, content_type='text/plain')
    assert 'proposalCount' not in result
    assert 'averageBid' not in result


def test_malformed_and_deep_json_fallback():
    body = '<script type="application/ld+json">' + '[' * 1500 + '0' + ']' * 1500 + '</script><script type="application/ld+json">{</script><h1>Visible task</h1><article>Build a real backend API for our team.</article>'
    assert html(body)['title'] == 'Visible task'


def test_monthly_structured_salary_omitted():
    job = {'@type': 'JobPosting', 'title': 'Engineer', 'description': 'Build workflows for a team.', 'baseSalary': {'currency': 'USD', 'value': {'value': 3000, 'unitText': 'MONTH'}}}
    result = html('<script type="application/ld+json">' + json.dumps(job) + '</script>')
    assert 'fixedBudget' not in result


@pytest.mark.parametrize(('code', 'expected'), [('EUR', 'EUR'), ('RUB', 'RUB'), (' eur ', 'EUR'), ('CHF', None), ('', None)])
def test_structured_currency(code, expected):
    body = (FIXTURES / 'job-page.html').read_text().replace('"currency": "USD"', f'"currency": "{code}"')
    result = html(body)
    assert result['hourlyRateMin'] == 40
    assert result.get('budgetCurrency') == expected


def test_missing_freelancer_description_never_uses_bids():
    result = html('<h1>Task</h1><div class="User-bid-text">I can build this project with Python.</div>', 'https://freelancer.com/projects/python/task')
    assert result['description'] == ''
    assert result['skills'] == []


def test_graph_job_and_structured_html_cleanup():
    job = {'@graph': [{'@type': ['Thing', 'JobPosting'], 'title': 'Actual title', 'description': '<p>Build Python workflows.</p><script>Bad</script><p hidden>Bad</p>'}]}
    result = html('<script type="application/ld+json">' + json.dumps(job).replace('</', '<\\/') + '</script><h1>Fallback</h1>')
    assert result['title'] == 'Actual title'
    assert result['description'] == 'Build Python workflows.'


def test_empty_input_has_no_evidence():
    assert extract_content('', content_type='text/plain') == {'title': '', 'description': '', 'skills': [], 'provenance': {}}


def test_structured_competition_provenance():
    job = {'@type': 'JobPosting', 'title': 'Task', 'description': 'Build workflows.\nProposals: 18\nAverage bid: $330'}
    result = html('<script type="application/ld+json">' + json.dumps(job) + '</script>')
    assert result['proposalCount'] == 18
    assert result['provenance']['proposalCount'] == 'json_ld'


def test_very_long_proposal_number_ignored():
    result = extract_content('Task\nProposals: ' + '9' * 5000, content_type='text/plain')
    assert 'proposalCount' not in result


def test_split_freelancer_statistics_keep_project_evidence_and_ignore_bidders():
    body = ('<h1>Shopify bridge</h1><div class="Project-heading"><h2>$250-750 USD</h2></div>'
        '<div class="Project-statistics"><span>248</span><span>proposals</span>'
        '<span>$500 USD</span><span>Average bid</span></div>'
        '<p class="Project-description">Build a Shopify bridge.</p>'
        '<div class="User-bid-text">Proposals: 999\nAverage bid: €1000</div>')
    result = html(body, 'https://www.freelancer.com/projects/shopify/bridge')
    assert result['proposalCount'] == 248 and result['averageBid'] == 500
    assert result['averageBidCurrency'] == 'USD' and result['fixedBudget'] == 250
    assert result['provenance']['proposalCount'] == result['provenance']['averageBid'] == 'html'


@pytest.mark.parametrize('statistics', ['Proposals\n10\nProposals\n248', 'Average bid\n$300\nAverage bid\n$500'])
@pytest.mark.parametrize('content_type', ['text/plain', 'text/html'])
def test_repeated_split_labels_do_not_hide_conflicting_statistics(statistics, content_type):
    body = 'Task\nBuild a React dashboard.\n' + statistics
    if content_type == 'text/html':
        body = '<h1>Task</h1><article>' + body.replace('\n', '<br>') + '</article>'
    result = extract_content(body, content_type=content_type)
    assert 'proposalCount' not in result and 'averageBid' not in result
    assert 'fixedBudget' not in result
