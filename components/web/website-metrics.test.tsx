import { StrictMode } from 'react';
import { beforeEach, expect, it, vi } from 'vitest';
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { createMemoryWebsiteRepository } from '@/lib/web/memory-repository';
import { defaultProfile, goAnalysis } from '@/lib/mock-data';
import type { WebsiteApi } from '@/lib/web/api';
import { createHistoryEntry } from '@/lib/web/history';
import { WebsiteApp } from './website-app';
import type { WebsiteRepository } from '@/lib/web/types';
const metrics = vi.hoisted(() => ({ track: vi.fn(() => true), dispose: vi.fn(), deleteVisitor: vi.fn(async () => false), clients: [] as Array<{
        dispose: ReturnType<typeof vi.fn>;
    }> }));
vi.mock('@/lib/metrics/client', () => ({
    createMetricsClient: vi.fn(() => {
        const client = { track: metrics.track, dispose: vi.fn(), deleteVisitor: metrics.deleteVisitor };
        metrics.clients.push(client);
        return client;
    }),
    sendBrowserMetrics: vi.fn(), deleteBrowserVisitor: vi.fn(),
}));
vi.mock('./auth-screen', () => ({ AuthScreen: ({ onCreate, onSignIn }: {
        onCreate: (v: unknown) => Promise<void>;
        onSignIn: (v: unknown) => Promise<void>;
    }) => <><button onClick={() => void onCreate({ name: 'Private', email: 'secret@example.com', password: 'password123' })}>register</button><button onClick={() => void onSignIn({ email: 'secret@example.com', password: 'password123' })}>login</button></> }));
vi.mock('./profile-editor', () => ({ ProfileEditor: ({ onSave, onSuggestSkills, onSkillsAccepted }: {
        onSave: (p: unknown) => Promise<void>;
        onSuggestSkills: (p: unknown) => Promise<string[]>;
        onSkillsAccepted?: (n: number) => void;
    }) => <><button onClick={() => void onSave(defaultProfile).catch(() => { })}>save</button><button onClick={() => void onSuggestSkills({ specialization: 'private profile', locale: 'en' })}>suggest</button><button onClick={() => onSkillsAccepted?.(1)}>accept</button></> }));
const draft = { id: 'draft', sourceMode: 'text' as const, title: 'private task', description: 'private content', skills: [], updatedAt: '2026-10-14T00:00:00Z' };
vi.mock('./vacancy-source', () => ({ VacancySource: ({ onReview, onInputStarted, onLoadUrl }: {
        onReview: (v: unknown) => void;
        onInputStarted?: (m: string) => void;
        onLoadUrl: (s: string) => Promise<unknown>;
    }) => <><button onClick={() => {
            onInputStarted?.('text');
            onReview(draft);
        }}>review</button><button onClick={() => void onLoadUrl('https://example.com/private?q=secret')}>extract</button></> }));
vi.mock('./vacancy-review', () => ({ VacancyReview: ({ onAnalyze }: {
        onAnalyze: (v: unknown) => void;
    }) => <button onClick={() => onAnalyze(draft)}>analyze</button> }));
vi.mock('./analysis-result', () => ({ AnalysisResult: ({ entry, onSaveFeedback }: {
        entry: {
            analysis: {
                score: number;
            };
        };
        onSaveFeedback: (v: unknown) => void;
    }) => <><p>result {entry.analysis.score}</p><button onClick={() => onSaveFeedback({ correctedScore: 25, note: 'private note' })}>feedback</button></> }));
const operationId = '11111111-1111-4111-8111-111111111111';
const api = { analyzeVacancy: vi.fn(async () => goAnalysis), analyzeVacancyWithContext: vi.fn(async () => ({ analysis: goAnalysis, operationId })), extractVacancy: vi.fn(async () => draft), suggestSkills: vi.fn(async () => ['TypeScript']) };
const names = () => metrics.track.mock.calls.map(call => (call as unknown[])[0]);
async function seeded() {
    const repository = createMemoryWebsiteRepository();
    const u = await repository.createUser({ name: 'Private', email: 'secret@example.com', password: 'password123' });
    await repository.saveProfile(u.id, defaultProfile);
    return { repository, u };
}
beforeEach(() => {
    vi.clearAllMocks();
    metrics.clients.length = 0;
    window.localStorage.clear();
    window.history.replaceState({}, '', '/');
    metrics.track.mockReturnValue(true);
    metrics.deleteVisitor.mockResolvedValue(true);
});
it('test_ordered_local_registration_profile_analysis_view_events', async () => {
    const repository = createMemoryWebsiteRepository();
    render(<WebsiteApp repository={repository} api={api} metricsEnabled/>);
    fireEvent.click(await screen.findByText('register'));
    fireEvent.click(await screen.findByText('save'));
    fireEvent.click(await screen.findByText('review'));
    fireEvent.click(await screen.findByText('analyze'));
    await screen.findByText('result 82');
    expect(names().filter(n => ['page_viewed', 'local_registration_completed', 'profile_saved', 'analysis_requested', 'analysis_result_viewed'].includes(String(n)))).toEqual(['page_viewed', 'local_registration_completed', 'profile_saved', 'analysis_requested', 'analysis_result_viewed']);
    expect(metrics.track).toHaveBeenCalledWith('analysis_result_viewed', { resultId: operationId, predictedScore: 82 }, { operationId });
    expect(JSON.stringify(metrics.track.mock.calls)).not.toMatch(/secret|private|password|example.com/);
});
it('test_failed_profile_save_does_not_emit_saved', async () => {
    const { repository } = await seeded();
    repository.saveProfile = async () => {
        throw Error('offline');
    };
    render(<WebsiteApp repository={repository} api={api} metricsEnabled/>);
    fireEvent.click((await screen.findAllByRole('button', { name: 'Profile' }))[0]);
    fireEvent.click(await screen.findByText('save'));
    await act(async () => { });
    expect(names()).not.toContain('profile_saved');
});
it('test_result_first_view_not_recounted_by_rerender', async () => {
    const { repository } = await seeded();
    const view = render(<WebsiteApp repository={repository} api={api} metricsEnabled/>);
    fireEvent.click(await screen.findByText('review'));
    fireEvent.click(await screen.findByText('analyze'));
    await screen.findByText('result 82');
    view.rerender(<WebsiteApp repository={repository} api={api} metricsEnabled/>);
    fireEvent.click(screen.getByText('feedback'));
    expect(names().filter(n => n === 'analysis_result_viewed')).toHaveLength(1);
});
it('test_skills_requested_accepted_and_history_adoption', async () => {
    const { repository } = await seeded();
    render(<WebsiteApp repository={repository} api={api} metricsEnabled/>);
    fireEvent.click((await screen.findAllByRole('button', { name: 'Profile' }))[0]);
    fireEvent.click(await screen.findByText('suggest'));
    fireEvent.click(screen.getByText('accept'));
    fireEvent.click(screen.getAllByRole('button', { name: 'History' })[0]);
    expect(names()).toEqual(expect.arrayContaining(['skills_requested', 'skills_accepted', 'history_viewed']));
});
it('test_feedback_emits_scores_without_note', async () => {
    const { repository, u } = await seeded();
    const entry = createHistoryEntry({ userId: u.id, profile: defaultProfile, job: { id: 'job', title: 'private task', description: 'private description', skills: [] }, analysis: goAnalysis });
    entry.providerOperationId = operationId;
    await repository.addHistory(entry);
    render(<WebsiteApp repository={repository} api={api} metricsEnabled/>);
    fireEvent.click((await screen.findAllByRole('button', { name: 'History' }))[0]);
    fireEvent.click(screen.getByRole('button', { name: /private task, 82/ }));
    fireEvent.click(await screen.findByText('feedback'));
    await waitFor(() => expect(metrics.track).toHaveBeenCalledWith('feedback_saved', { resultId: operationId, predictedScore: 82, correctedScore: 25 }, { operationId }));
    expect(JSON.stringify(metrics.track.mock.calls)).not.toContain('private note');
});
it('test_local_delete_rotates_visitor_not_backend_identity', async () => {
    metrics.deleteVisitor.mockResolvedValue(false);
    const { repository } = await seeded();
    const status = vi.spyOn(console, 'info').mockImplementation(() => {});
    vi.spyOn(window, 'confirm').mockReturnValue(true);
    render(<WebsiteApp repository={repository} api={api} metricsEnabled/>);
    fireEvent.click((await screen.findAllByRole('button', { name: 'Profile' }))[0]);
    fireEvent.click(screen.getByRole('button', { name: 'Delete account' }));
    await screen.findByText('register');
    await waitFor(() => expect(metrics.deleteVisitor).toHaveBeenCalledOnce());
    await waitFor(() => expect(status).toHaveBeenCalledWith('FitCheck metrics: visitor deletion observation was not delivered'));
    status.mockRestore();
    expect((await repository.loadSnapshot()).user).toBeNull();
    expect(names()).toContain('local_account_deleted');
});
it('test_telemetry_failure_does_not_block_existing_flow', async () => {
    metrics.track.mockImplementation(() => {
        throw Error('collector');
    });
    const { repository } = await seeded();
    render(<WebsiteApp repository={repository} api={api} metricsEnabled/>);
    fireEvent.click(await screen.findByText('review'));
    fireEvent.click(await screen.findByText('analyze'));
    expect(await screen.findByText('result 82')).toBeVisible();
});
it.each([['', 'direct'], ['?utm_campaign=launch', 'launch'], ['?utm_campaign=private_email%40example.com&secret=password', 'other']])('maps campaign before queue and excludes route/query %s', async (query, campaign) => {
    window.history.replaceState({}, '', `/private-path${query}`);
    render(<WebsiteApp repository={createMemoryWebsiteRepository()} api={api} metricsEnabled knownCampaignCodes={['launch']}/>);
    await screen.findByText('register');
    expect(metrics.track).toHaveBeenCalledWith('page_viewed', { locale: 'en', campaign });
    expect(JSON.stringify(metrics.track.mock.calls)).not.toMatch(/private-path|private_email|password/);
});
it('strict mode disposes each mounted client and deletion cannot recreate after unmount', async () => {
    const { repository } = await seeded();
    let settle!: (v: boolean) => void;
    metrics.deleteVisitor.mockImplementation(() => new Promise(r => {
        settle = r;
    }));
    vi.spyOn(window, 'confirm').mockReturnValue(true);
    const view = render(<StrictMode><WebsiteApp repository={repository} api={api} metricsEnabled/></StrictMode>);
    fireEvent.click((await screen.findAllByRole('button', { name: 'Profile' }))[0]);
    fireEvent.click(screen.getByRole('button', { name: 'Delete account' }));
    await waitFor(() => expect(metrics.deleteVisitor).toHaveBeenCalledOnce());
    const count = metrics.clients.length;
    view.unmount();
    await act(async () => settle(false));
    expect(metrics.clients).toHaveLength(count);
    expect(metrics.clients.every(c => c.dispose.mock.calls.length === 1)).toBe(true);
});
it('registration counts committed creation even when preference save fails', async () => {
    const repository: WebsiteRepository = createMemoryWebsiteRepository();
    repository.saveLocale = async () => {
        throw Error('storage');
    };
    render(<WebsiteApp repository={repository} api={api} metricsEnabled/>);
    fireEvent.click(await screen.findByText('register'));
    await waitFor(() => expect(names()).toContain('local_registration_completed'));
});
it('legacy injected APIs remain unlinked and produce no fabricated server success', async () => {
    const { repository } = await seeded();
    const legacyApi: WebsiteApi = { analyzeVacancy: async () => goAnalysis, extractVacancy: api.extractVacancy, suggestSkills: api.suggestSkills };
    render(<WebsiteApp repository={repository} api={legacyApi} metricsEnabled/>);
    fireEvent.click(await screen.findByText('review'));
    fireEvent.click(await screen.findByText('analyze'));
    await screen.findByText('result 82');
    const [entry] = (await repository.loadSnapshot()).history;
    expect(entry.providerOperationId).toBeUndefined();
    expect(metrics.track).toHaveBeenCalledWith('analysis_result_viewed', { resultId: entry.id, predictedScore: 82 }, {});
    expect(names()).not.toContain('analysis_finished');
});
it('pending analysis after deletion cannot associate its result with the rotated visitor', async () => {
    const { repository } = await seeded();
    let complete!: (value: {
        analysis: typeof goAnalysis;
        operationId: string;
    }) => void;
    const pendingApi = { ...api, analyzeVacancyWithContext: () => new Promise<{
            analysis: typeof goAnalysis;
            operationId: string;
        }>(resolve => { complete = resolve; }) };
    vi.spyOn(window, 'confirm').mockReturnValue(true);
    render(<WebsiteApp repository={repository} api={pendingApi} metricsEnabled/>);
    fireEvent.click(await screen.findByText('review'));
    fireEvent.click(await screen.findByText('analyze'));
    fireEvent.click(screen.getAllByRole('button', { name: 'Profile' })[0]);
    fireEvent.click(screen.getByRole('button', { name: 'Delete account' }));
    await screen.findByText('register');
    await act(async () => complete({ analysis: goAnalysis, operationId }));
    expect(names()).not.toContain('analysis_result_viewed');
    expect((await repository.loadSnapshot()).history).toEqual([]);
});
it('login, extraction and committed history clearing emit safe observations', async () => {
    const { repository, u } = await seeded();
    const entry = createHistoryEntry({ userId: u.id, profile: defaultProfile, job: { id: 'job', title: 'Task', description: 'Content', skills: [] }, analysis: goAnalysis });
    await repository.addHistory(entry);
    await repository.signOut();
    vi.spyOn(window, 'confirm').mockReturnValue(true);
    render(<WebsiteApp repository={repository} api={api} metricsEnabled/>);
    fireEvent.click(await screen.findByText('login'));
    fireEvent.click((await screen.findAllByRole('button', { name: 'New analysis' }))[0]);
    fireEvent.click(await screen.findByText('extract'));
    await waitFor(() => expect(api.extractVacancy).toHaveBeenCalled());
    fireEvent.click(screen.getAllByRole('button', { name: 'History' })[0]);
    fireEvent.click(screen.getByRole('button', { name: 'Clear history' }));
    await waitFor(() => expect(names()).toContain('history_cleared'));
    expect(metrics.track).toHaveBeenCalledWith('local_login_completed', { locale: 'en' });
    expect(metrics.track).toHaveBeenCalledWith('extraction_requested', { locale: 'en', inputMode: 'url' });
    expect(JSON.stringify(metrics.track.mock.calls)).not.toMatch(/secret|private|example.com/);
});
it('pending history clearing cannot emit an old mutation for the rotated visitor', async () => {
  const { repository, u } = await seeded()
  const entry = createHistoryEntry({ userId: u.id, profile: defaultProfile, job: {id:'job',title:'Task',description:'Content',skills:[]}, analysis: goAnalysis })
  await repository.addHistory(entry)
  let complete!: () => void
  repository.clearHistory = () => new Promise<void>(resolve => { complete = resolve })
  vi.spyOn(window, 'confirm').mockReturnValue(true)
  render(<WebsiteApp repository={repository} api={api} metricsEnabled />)
  fireEvent.click((await screen.findAllByRole('button', {name:'History'}))[0])
  fireEvent.click(screen.getByRole('button', {name:'Clear history'}))
  fireEvent.click(screen.getAllByRole('button', {name:'Profile'})[0])
  fireEvent.click(screen.getByRole('button', {name:'Delete account'}))
  await screen.findByText('register')
  await act(async () => complete())
  expect(names()).not.toContain('history_cleared')
})
