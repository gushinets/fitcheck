# Profile Preferences and Skill Suggestions Design

> **Scope update — 2026-10-12:** The user chose FitCheck as a website-only product and authorized removal of the extension code, builds, and authentication. This document is a historical implementation record; completed steps, test results, and migration history remain evidence of the work at that time. Extension steps and compatibility requirements are superseded and must not be executed or restored. Future work uses website cookie sessions with web-origin CSRF, website IndexedDB as the legacy import source, independent same-account sessions across devices, and website/backend CI. See the current backend foundation, storage, and authentication specifications.

## Goal

Extend the FitCheck website profile so users can ask DeepSeek for specialization-specific skill suggestions, record realistic income expectations, and select acceptable work formats. These preferences must persist locally and influence vacancy analysis.

## Scope

This change applies only to the website UI. It does not add visible controls to the browser extension or add a remote database. Because the website and extension share `FreelancerProfile`, extension fixtures and save paths receive compatibility defaults for the new fields so the shared build remains valid. Existing local accounts and analysis history remain in IndexedDB.

The feature includes:

- on-demand DeepSeek skill suggestions;
- click-to-add skill suggestions without duplicates;
- hourly rates above the current 1,000 limit;
- desired monthly income;
- required remote, office, and hybrid work-format preferences;
- migration of profiles already stored in IndexedDB;
- inclusion of the new preferences in vacancy-analysis prompts;
- Russian and English interface copy and currencies.

## Profile Model

`FreelancerProfile` gains two required properties:

```ts
type WorkFormat = "remote" | "office" | "hybrid"

interface FreelancerProfile {
  specialization: string
  skills: string[]
  experienceYears: number
  preferredRate: number
  desiredMonthlyIncome: number
  workFormats: WorkFormat[]
  englishLevel: EnglishLevel
}
```

At least one work format is required. Duplicate work formats are not allowed. `preferredRate` and `desiredMonthlyIncome` accept non-negative finite numbers with a high defensive upper bound aligned with the application's other monetary fields. The existing artificial `preferredRate <= 1_000` rule is removed from both the UI and validation.

Currency is derived from the active interface locale and is not stored as a separate profile property:

- Russian: rubles, displayed as `₽`;
- English: US dollars, displayed as `$`.

The same locale-derived currency is used when the profile is sent for vacancy analysis.
Switching the interface language changes the currency interpretation and label but does not perform exchange-rate conversion; no exchange-rate service is in scope.

## Existing Profile Compatibility

Profiles stored before this change do not contain the new properties. The IndexedDB repository normalizes them when loading:

- `desiredMonthlyIncome` defaults to `0`;
- `workFormats` defaults to `["remote"]`.

All existing profile fields and history remain unchanged. The normalized profile is written in the new shape the next time the user saves it. No database deletion or account recreation is required.

## Skill Suggestions API

A new server-only endpoint, `POST /api/skill-suggestions`, accepts:

```json
{
  "specialization": "Backend Developer",
  "locale": "en"
}
```

The endpoint:

1. Applies the same-origin/CORS policy used by analysis.
2. Rejects malformed, oversized, or empty specialization input.
3. Calls the configured DeepSeek model with thinking explicitly disabled.
4. Requests JSON containing at most 10 concise, specialization-specific skill names. Generic competency names use the requested language, while established technology names retain their conventional spelling.
5. Trims values, removes case-insensitive duplicates, and validates lengths before returning them.

Successful response:

```json
{
  "skills": ["Python", "FastAPI", "PostgreSQL"]
}
```

The endpoint never exposes the DeepSeek key. Provider timeouts, rate limits, invalid output, and upstream failures map to stable public error codes that the web client can localize. No fallback mock suggestions are returned because the feature must exercise the real product behavior.

## Profile Editor Interaction

The profile editor keeps specialization as free text. A localized `Suggest skills` / `Подобрать навыки` button appears with the specialization field and is disabled while that field is blank.

When clicked:

1. The button enters a loading state and duplicate requests are blocked.
2. The client requests suggestions for the current specialization and locale.
3. Up to 10 suggestion chips appear below the skills input.
4. Skills already present in the input are excluded case-insensitively.

Clicking a suggestion chip appends the skill to the existing comma-separated skills input and removes that chip from the suggestion list. Existing manually entered skills remain unchanged. Changing the specialization clears visible suggestions but does not remove selected skills.

If the request fails, a localized inline error appears. The rest of the profile form stays usable and the user can retry by pressing the suggestion button again.

## Income and Work Format UI

The hourly-rate input keeps a minimum of zero and no longer has an HTML maximum of 1,000. Its label or adjacent suffix identifies the locale-derived currency.

A required desired-monthly-income numeric input appears alongside the rate. It uses the same minimum and defensive server-side maximum, with `₽/month` in Russian and `$/month` in English.

Three independent localized checkboxes are shown:

- Remote / Удалённо;
- Office / Офис;
- Hybrid / Гибрид.

Users may select any combination, but the profile cannot be saved unless at least one is selected. Profile save also continues to require a non-empty specialization and at least one skill.

## Vacancy Analysis

The analysis prompt adds explicit profile lines for:

- preferred hourly rate with locale-derived currency;
- desired monthly income with locale-derived currency;
- acceptable work formats.

The analysis task asks DeepSeek to consider income and work-format compatibility only when the vacancy provides relevant evidence. Missing vacancy salary or location-mode information must not be invented or treated as a mismatch.

Historical analysis entries continue to snapshot the full profile used for each analysis, including the new fields.

## Error Handling

- Empty specialization: suggestion button disabled; no request.
- Suggestion request in progress: button disabled and loading label displayed.
- Provider rate limit, timeout, invalid output, or upstream error: localized inline message with retry available.
- Empty valid suggestion list: localized no-suggestions message; manual skill entry remains available.
- Duplicate suggestion or manually entered skill: only one case-insensitive occurrence is kept when adding a chip.
- No work format selected: save button disabled and validation rejects the profile independently of the UI.
- Existing malformed profile: repository normalization preserves valid legacy fields and applies defaults only to missing new fields; other invalid data follows the existing repository failure behavior.

## Testing

Automated coverage includes:

- profile schema accepts rates above 1,000 and rejects negative/non-finite monetary values;
- profile schema requires at least one unique valid work format;
- old IndexedDB profiles load with the migration defaults;
- new profile fields persist and reload;
- analysis prompts include locale-specific currencies, desired monthly income, and work formats;
- DeepSeek suggestion transport sends thinking disabled and parses its JSON response;
- suggestion route validates requests and maps stable error responses;
- web API validates suggestion responses;
- profile editor disables suggestions for empty specialization, loads on button press, adds a chip without duplicates, clears stale suggestions after specialization changes, displays failures, accepts a large hourly rate, and requires a work format;
- Russian and English copy renders the correct currencies and labels;
- full unit test, typecheck, lint, and production build verification;
- after deployment, the public dev endpoint is exercised with at least one Russian and one English specialization.

## Deployment

Implementation is committed and pushed to the `dev` branch, deployed to `https://dev-fitcheck.dokploy.gcexp.ru/`, and verified through the public endpoint and profile interface. Existing DeepSeek and Dokploy secrets remain server-side and are never logged or returned.
