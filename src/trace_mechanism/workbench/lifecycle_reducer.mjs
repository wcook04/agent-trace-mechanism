export function timestampMs(value) {
  if (value == null || value === '') return null;
  if (typeof value === 'number') {
    if (!Number.isFinite(value)) return null;
    return value > 10_000_000_000 ? Math.floor(value) : Math.floor(value * 1000);
  }
  const parsed = Date.parse(String(value));
  return Number.isFinite(parsed) ? parsed : null;
}

function firstText(values) {
  for (const value of values) {
    const text = String(value || '').trim();
    if (text) return text;
  }
  return '';
}

function shortSessionId(sessionId) {
  const text = String(sessionId || '');
  return text ? text.slice(0, 6) : '';
}

function titleAuthorityIsSource(source) {
  return [
    'codex_thread_name',
    'claude_desktop_title',
    'claude_desktop_user_title',
  ].includes(String(source || ''));
}

export function missionIdentityFacts(row = {}, displayTurn = {}) {
  const titleSource = row.title_source || '';
  const titleText = String(row.title || '').trim();
  const sourceTitle = firstText([
    row.source_title,
    titleAuthorityIsSource(titleSource) ? titleText : '',
  ]);
  const operatorAlias = firstText([
    row.operator_alias,
    titleSource === 'operator_alias' ? titleText : '',
  ]);
  const promptDerivedTitle = firstText([
    row.prompt_derived_title,
    displayTurn.prompt_title,
    row.latest_completed_turn?.prompt_title,
    row.preferred_trace_turn?.prompt_title,
  ]);
  const promptPreview = firstText([
    row.prompt_preview,
    displayTurn.prompt_preview,
    row.preferred_trace_turn?.prompt_preview,
    row.latest_completed_turn?.prompt_preview,
    row.active_turn?.prompt_preview,
  ]);
  const displayTitle = firstText([
    sourceTitle,
    operatorAlias,
    promptDerivedTitle,
    row.display_title,
    row.short_label,
    shortSessionId(row.session_id),
  ]) || 'Untitled mission';
  return {
    displayTitle,
    promptPreview,
    sourceTitle,
    operatorAlias,
    promptDerivedTitle,
    titleSource,
  };
}

export function missionDisplayTitle(row = {}, displayTurn = {}) {
  return missionIdentityFacts(row, displayTurn).displayTitle;
}

export function missionPromptPreview(row = {}, displayTurn = {}) {
  return missionIdentityFacts(row, displayTurn).promptPreview;
}

// A transcript records events. It cannot certify that a process is still running.
export function deriveMissionLifecycle({row = {}, copyEntry, now = Date.now(), copyAckMs = 15000} = {}) {
  let activity = 'idle', copy = 'none', text = 'UNKNOWN', cls = 'partial', glyph = '·';
  let reason = 'No observed record establishes the current state.';
  if (row.worker_state === 'finished') {
    text = 'FINISHED'; cls = 'finished'; glyph = '✓'; reason = 'A completed response is recorded.';
  } else if (row.worker_state === 'interrupted') {
    text = 'INTERRUPTED'; reason = 'A turn interruption is recorded.';
  } else if (['working', 'tool'].includes(row.worker_state)) {
    const recordedAt = timestampMs(row.last_activity_at);
    const recent = recordedAt != null && recordedAt <= now && now - recordedAt < 120000;
    activity = recent ? 'live' : 'idle';
    text = recent ? 'ACTIVE' : 'OPEN'; cls = recent ? 'running' : 'partial';
    reason = recent ? 'Recent activity is recorded on an open turn.' : 'The last observed turn has no recorded completion.';
  }
  if (copyEntry?.failureAt != null && now - copyEntry.failureAt < copyAckMs) {
    copy = 'copy_failed'; text = 'COPY FAILED'; cls = 'copy_failed'; glyph = '!'; reason = 'The clipboard operation failed.';
  } else if (copyEntry?.successAt != null && now - copyEntry.successAt < copyAckMs) {
    copy = 'just_copied'; text = 'COPIED'; cls = 'copied'; glyph = '✓'; reason = 'The selected capture was copied.';
  } else if (copyEntry?.startedAt != null && copyEntry.failureAt == null && copyEntry.successAt == null) {
    copy = 'copying'; text = 'COPYING'; cls = 'copying'; reason = 'Writing the selected capture to the clipboard.';
  }
  return {activity, copy, pill: {text, cls, title: reason}, glyph: {glyph, title: reason}, reason};
}
