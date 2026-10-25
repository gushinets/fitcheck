"""Conservative cross-clock proof for a browser observation, never a job view."""
from datetime import timedelta
from .identity_queries import Attribution

CLOCK_TOLERANCE = timedelta(minutes=5)
TIME_COVERAGE = {
    'observation_time_scope': 'confirmed_result_views_and_feedback_only',
    'observation_time_basis': 'server_receipt_upper_bound',
    'client_clock_tolerance_seconds': 300,
    'identity_time_policy': 'whole_bounded_observation_interval',
    'ttv_interpretation': 'upper_bound_including_delivery_delay',
}


def observation_window(event, ready_at):
    received = event.received_at
    raw = event.submitted_occurred_at
    if raw is None:
        if event.clock_adjusted:
            return None, None, 'missing_original_clock'
        raw = event.occurred_at
    if received is None:
        # Pure formula callers may supply exact, already aligned observations.
        # Persisted journal rows always have received_at (NOT NULL).
        if ready_at > raw:
            return None, None, 'unverified_result_job'
        return raw, raw, None
    if abs(raw-received) > CLOCK_TOLERANCE:
        return None, None, 'clock_out_of_bounds'
    if ready_at > received:
        return None, None, 'unverified_result_job'
    # A real result cannot be displayed before it exists. Receiving the event
    # bounds its latest possible observation, without assuming zero delivery lag.
    return max(raw-CLOCK_TOLERANCE, ready_at), received, None


def account_during(snapshot, start, end):
    """One confirmed owner must cover the entire closed uncertainty interval.

    Checking just its endpoints would miss a logout/login gap for the same owner.
    Never select the account active at delivery or choose a matching result owner
    from several overlapping sessions.
    """
    windows = sorted((window for window in snapshot.windows
        if window.start <= end and (window.end is None or window.end > start)), key=lambda window: window.start)
    if any(window.reason == 'erased_account' for window in windows):
        return Attribution(None, 'erased_account')
    if any(window.reason != 'confirmed' for window in windows):
        return Attribution(None, 'missing_session_evidence')
    owners = {window.account_owner_id for window in windows}
    if len(owners) != 1 or None in owners:
        return Attribution(None, 'clock_ambiguous_identity')
    cursor = start
    for window in windows:
        if window.start > cursor:
            return Attribution(None, 'clock_ambiguous_identity')
        if window.end is None:
            return Attribution(next(iter(owners)), 'confirmed')
        cursor = max(cursor, window.end)
    if cursor <= end:
        return Attribution(None, 'clock_ambiguous_identity')
    return Attribution(next(iter(owners)), 'confirmed')
