import re
from .types import AnalysisInput, StrengthFact
from .currency import compare_hourly_rate, format_money


def build_strength_evidence(value: AnalysisInput) -> list[StrengthFact]:
    p, job, ru = value.profile, value.vacancy, value.locale == 'ru'
    facts = []
    def matching(pattern):
        return [name for name, text in [('title', job.title), ('description', job.description)] if re.search(pattern, text, re.I)]
    for index, skill in enumerate(p.skills):
        key = skill.strip().lower()
        level = (p.skill_levels or {}).get(key)
        if level == 'basic':
            continue
        fields = (['skills'] if any(entry.strip().lower() == key for entry in job.skills) else []) + matching(r'(?<![^\W_])' + re.escape(skill) + r'(?![^\W_])')
        if not fields:
            continue
        proficiency = {'primary': 'Основной навык.' if ru else 'Primary skill.',
            'confident': 'Уровень: уверенно.' if ru else 'Proficiency: confident.'}.get(level,
            'Уровень владения не указан.' if ru else 'Proficiency is not specified.')
        text = f'В профиле указан {skill}; этот навык упоминается в задаче. {proficiency}' if ru else f'Your profile lists {skill}; this skill appears in the task. {proficiency}'
        facts.append(StrengthFact(f'skill:{index}', text, [f'skills.{index}'] + ([f'skillLevels.{key}'] if level else []), fields))
    experience = matching(r'experienc|опыт')
    if p.experience_years > 0 and (job.experience_level or experience):
        years = f'{p.experience_years:g}'
        facts.append(StrengthFact('experience', f'В профиле указан общий опыт: {years} лет. Опыт именно в этой задаче не подтверждён.' if ru else f'Your profile reports {years} years of overall experience; task-specific experience is not established.', ['experienceYears'], ['experienceLevel'] if job.experience_level else experience))
    english = matching(r'\bEnglish\b|английск')
    if english:
        facts.append(StrengthFact('english', f'Указанный в профиле уровень английского: {p.english_level}.' if ru else f'Your reported English level is {p.english_level}.', ['englishLevel'], english))
    remote = matching(r'\b(?:work(?:ing)?\s+remotely|remote\s+(?:work|job|role|position)|work\s*(?:format|mode|location)\s*:\s*remote)\b|удал[её]нн[^\W_]*\s+(?:работ|формат)')
    if 'remote' in p.work_formats and remote:
        facts.append(StrengthFact('workFormat:remote', 'Удалённый формат упоминается в задаче и выбран в профиле.' if ru else 'Remote work is mentioned in the task and selected in your profile.', ['workFormats'], remote))
    if compare_hourly_rate(p, job) == 'within_budget':
        money = format_money(p.preferred_rate, p.rate_currency)
        facts.append(StrengthFact('rate', f'Ставка из профиля {money}/час не превышает указанный почасовой максимум задачи.' if ru else f"Your profile rate of {money}/hour does not exceed the task's stated hourly maximum.", ['preferredRate', 'rateCurrency'], ['hourlyRateMax', 'budgetCurrency']))
    return facts
