export const clockFormat = new Intl.DateTimeFormat('zh-CN', {
  hour: '2-digit',
  minute: '2-digit',
  second: '2-digit',
});

export function shortPath(path) {
  if (!path) return '未知目录';
  return path.replace(/^\/Users\/[^/]+/, '~');
}

export function projectName(task) {
  if (task.project) return task.project;
  if (!task.cwd) return '未知项目';
  const parts = task.cwd.split('/').filter(Boolean);
  return parts[parts.length - 1] || task.cwd;
}

export function extractTitle(message) {
  let text = String(message || '').trim();
  const marker = '## My request for Codex:';
  const markerIndex = text.lastIndexOf(marker);
  if (markerIndex >= 0) text = text.slice(markerIndex + marker.length);
  return text.split('\n')
    .map((line) => line.trim())
    .filter((line) => line
      && !line.startsWith('# In app browser:')
      && !line.startsWith('# Diff comments:')
      && !line.startsWith('## Comment ')
      && !line.startsWith('File: ')
      && !line.startsWith('Side: ')
      && !line.startsWith('Lines: ')
      && !line.startsWith('Comment:'))
    .join(' ')
    .replace(/!?\[([^\]]*)\]\([^)]*\)/g, '$1')
    .replace(/\s+/g, ' ')
    .trim();
}

export function timeAgo(value) {
  if (!value) return '未知时间';
  const ms = Date.now() - new Date(value).getTime();
  if (!Number.isFinite(ms)) return value;
  const min = Math.max(0, Math.floor(ms / 60000));
  if (min < 1) return '刚刚';
  if (min < 60) return `${min} 分钟前`;
  const hour = Math.floor(min / 60);
  if (hour < 24) return `${hour} 小时前`;
  return `${Math.floor(hour / 24)} 天前`;
}

export function duration(ms) {
  if (!ms) return '进行中';
  const sec = Math.round(ms / 1000);
  if (sec < 60) return `${sec}s`;
  const min = Math.floor(sec / 60);
  return `${min}m ${sec % 60}s`;
}

function taskTime(task) {
  return new Date(task.updated_at || task.completed_at || task.started_at || 0).getTime() || 0;
}

function sessionKey(task) {
  return task.session_id || task.file || task.id;
}

function priorityScore(item) {
  return (item.approval_pending || item.running) ? 1 : 0;
}

function compareBySortMode(a, b, sortMode) {
  if (sortMode === 'priority') {
    const priorityDiff = priorityScore(b) - priorityScore(a);
    if (priorityDiff !== 0) return priorityDiff;
  }
  return (b.last_at || 0) - (a.last_at || 0);
}

export function buildSessions(tasks, sortMode = 'priority') {
  const sessions = new Map();
  for (const task of tasks) {
    const key = sessionKey(task);
    if (!sessions.has(key)) {
      sessions.set(key, {
        key,
        session_id: task.session_id,
        file: task.file,
        project: projectName(task),
        cwd: task.cwd,
        source: new Set(),
        turns: [],
        running: 0,
        completed: 0,
        error: 0,
        function_calls: 0,
        shell_calls: 0,
        approval_requests: [],
        approval_total: 0,
        approval_pending: 0,
        approval_denied: 0,
        token_total: 0,
        last_at: 0,
        originator: task.originator || '',
        session_title: task.session_title || '',
        title: '',
        last_agent_message: '',
      });
    }
    const session = sessions.get(key);
    session.turns.push(task);
    session.source.add(task.source);
    session.running += task.status === 'running' ? 1 : 0;
    session.completed += task.status === 'completed' ? 1 : 0;
    session.error += task.status === 'error' ? 1 : 0;
    session.function_calls += task.function_calls || 0;
    session.shell_calls += task.shell_calls || 0;
    const approvals = task.approval_requests || [];
    session.approval_requests.push(...approvals.map((request) => ({ ...request, turn_id: task.id })));
    session.approval_total += approvals.length;
    session.approval_pending += task.approval_pending_count || approvals.filter((request) => request.status === 'pending').length;
    session.approval_denied += task.approval_denied_count || approvals.filter((request) => request.status === 'denied').length;
    session.token_total += task.token_total || 0;
    session.session_title ||= task.session_title || '';
    const updatedAt = taskTime(task);
    session.last_at = Math.max(session.last_at, updatedAt);
    if (updatedAt >= session.last_at) {
      session.project = projectName(task);
      session.cwd = task.cwd || session.cwd;
      session.originator = task.originator || session.originator;
    }
  }

  return Array.from(sessions.values()).map((session) => {
    session.turns.sort((a, b) => taskTime(b) - taskTime(a));
    const oldestWithPrompt = [...session.turns].reverse().find((task) => task.user_message);
    const latestWithReply = session.turns.find((task) => task.last_agent_message);
    session.title = session.session_title
      || extractTitle(oldestWithPrompt?.user_message)
      || latestWithReply?.last_agent_message
      || '(无会话标题)';
    session.last_agent_message = latestWithReply?.last_agent_message || '';
    session.status = session.running ? 'running' : (session.error ? 'error' : 'completed');
    session.approval_status = session.approval_pending ? 'pending' : (session.approval_denied ? 'denied' : (session.approval_total ? 'resolved' : 'none'));
    session.source_label = Array.from(session.source).sort().join(' + ');
    return session;
  }).sort((a, b) => compareBySortMode(a, b, sortMode));
}

export function groupTasksByProject(tasks, sortMode = 'priority') {
  const groups = new Map();
  for (const session of buildSessions(tasks, sortMode)) {
    const project = session.project;
    if (!groups.has(project)) {
      groups.set(project, {
        project,
        cwd: session.cwd,
        sessions: [],
        running: 0,
        completed: 0,
        error: 0,
        approval_pending: 0,
        approval_denied: 0,
        last_at: 0,
      });
    }
    const group = groups.get(project);
    group.sessions.push(session);
    group.cwd ||= session.cwd;
    group[session.status] = (group[session.status] || 0) + 1;
    group.approval_pending += session.approval_pending || 0;
    group.approval_denied += session.approval_denied || 0;
    group.last_at = Math.max(group.last_at, session.last_at || 0);
  }
  return Array.from(groups.values()).sort((a, b) => compareBySortMode(a, b, sortMode));
}
