def normalize_skills(values: list[str]) -> list[str]:
    seen, result = set(), []
    for value in values:
        skill = value.strip()
        if not skill or skill.lower() in seen:
            continue
        if len(skill) > 80:
            raise ValueError('Skill name is too long')
        seen.add(skill.lower()); result.append(skill)
        if len(result) == 10:
            break
    return result
