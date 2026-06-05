import { html, nothing } from '../vendor/lit.js';
import { LightDomElement } from './base.js';
import { clockFormat, groupTasksByProject, shortPath } from '../utils.js';
import './project-group.js?v=20260605b';
import './live-approval-panel.js?v=20260605b';

class CodexDashboard extends LightDomElement {
  static properties = {
    tasks: { state: true },
    summary: { state: true },
    query: { state: true },
    statusFilter: { state: true },
    sourceFilter: { state: true },
    sortMode: { state: true },
    limit: { state: true },
    updatedLabel: { state: true },
    clock: { state: true },
    selectedSession: { state: true },
    dialogReady: { state: true },
    approvalBridge: { state: true },
    approvalMessage: { state: true },
  };

  constructor() {
    super();
    this.tasks = [];
    this.summary = null;
    this.query = '';
    this.statusFilter = 'all';
    this.sourceFilter = 'all';
    this.sortMode = 'priority';
    this.limit = '80';
    this.updatedLabel = '等待加载';
    this.clock = clockFormat.format(new Date());
    this.selectedSession = null;
    this.dialogReady = false;
    this.approvalBridge = null;
    this.approvalMessage = '';
    this.clockTimer = null;
    this.refreshTimer = null;
  }

  connectedCallback() {
    super.connectedCallback();
    this.clockTimer = window.setInterval(() => {
      this.clock = clockFormat.format(new Date());
    }, 1000);
    this.refreshTimer = window.setInterval(() => this.load().catch(console.error), 15000);
    this.load().catch((error) => {
      this.updatedLabel = `加载失败：${error.message}`;
    });
  }

  disconnectedCallback() {
    window.clearInterval(this.clockTimer);
    window.clearInterval(this.refreshTimer);
    super.disconnectedCallback();
  }

  get filteredTasks() {
    const query = this.query.trim().toLowerCase();
    return this.tasks.filter((task) => {
      if (this.statusFilter === 'approval_pending' && !(task.approval_pending_count > 0)) return false;
      if (this.statusFilter === 'approval_denied' && !(task.approval_denied_count > 0)) return false;
      if (!['all', 'approval_pending', 'approval_denied'].includes(this.statusFilter) && task.status !== this.statusFilter) return false;
      if (this.sourceFilter !== 'all' && task.source !== this.sourceFilter) return false;
      if (!query) return true;
      const approvalText = (task.approval_requests || [])
        .map((request) => [request.command, request.justification, request.status].filter(Boolean).join(' '))
        .join('\n');
      return [task.user_message, task.cwd, task.project, task.last_agent_message, task.session_id, approvalText]
        .filter(Boolean).join('\n').toLowerCase().includes(query);
    });
  }

  get groups() {
    return groupTasksByProject(this.filteredTasks, this.sortMode);
  }

  get sessionCount() {
    return this.groups.reduce((sum, group) => sum + group.sessions.length, 0);
  }

  get liveApprovalCallIds() {
    return this.approvalBridge?.pending_call_ids || [];
  }

  get desktopPendingApprovals() {
    const liveIds = new Set(this.liveApprovalCallIds);
    return this.tasks.flatMap((task) => (task.approval_requests || [])
      .filter((approval) => approval.status === 'pending' && !liveIds.has(approval.call_id))
      .map((approval) => ({
        call_id: approval.call_id,
        command: approval.command,
        reason: approval.justification,
        cwd: task.cwd,
        thread_id: task.session_id,
        turn_id: task.id,
        title: task.session_title || task.user_message || task.session_id,
      })));
  }

  async load() {
    const [res, bridgeRes] = await Promise.all([
      fetch(`/api/tasks?limit=${encodeURIComponent(this.limit)}`),
      fetch('/api/approval-bridge/status?connect=true'),
    ]);
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const data = await res.json();
    this.tasks = data.tasks;
    this.summary = data.summary;
    if (bridgeRes.ok) this.approvalBridge = await bridgeRes.json();
    this.updatedLabel = `更新于 ${clockFormat.format(new Date())}`;
  }

  async openSession(event) {
    await import('./session-dialog.js');
    this.dialogReady = true;
    this.selectedSession = event.detail.session;
  }

  closeSession() {
    this.selectedSession = null;
  }

  async handleApprovalDecision(event) {
    event.stopPropagation();
    const { session, approval, decision } = event.detail;
    const label = decision === 'decline' ? '拒绝' : (decision === 'accept_for_session' ? '本会话批准' : '批准本次');
    const command = approval.command || approval.justification || approval.call_id;
    if (!window.confirm(`${label}这个权限请求？\n\n${command}`)) return;

    this.approvalMessage = `${label}中...`;
    try {
      const res = await fetch('/api/approval/decision', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          file: session?.file,
          session_id: session?.session_id,
          turn_id: approval.turn_id,
          call_id: approval.call_id,
          decision,
        }),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(data.detail || `HTTP ${res.status}`);
      this.approvalMessage = data.message || '审批决定已发送，等待 Codex 写回结果。';
      window.setTimeout(() => this.load().catch(console.error), 1200);
    } catch (error) {
      this.approvalMessage = `审批失败：${error.message}`;
      await this.refreshApprovalBridge();
    }
  }

  async handleDesktopOpenThread(event) {
    event.stopPropagation();
    const threadId = event.detail?.threadId;
    if (!threadId) return;
    this.approvalMessage = '正在打开 Codex Desktop 原会话...';
    try {
      const res = await fetch('/api/desktop/open-thread', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ thread_id: threadId }),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(data.detail || `HTTP ${res.status}`);
      this.approvalMessage = data.message || '已请求 Codex Desktop 打开原会话。';
    } catch (error) {
      this.approvalMessage = `打开 Desktop 会话失败：${error.message}`;
    }
  }

  async refreshApprovalBridge() {
    const res = await fetch('/api/approval-bridge/status?connect=true');
    if (res.ok) this.approvalBridge = await res.json();
  }

  render() {
    const groups = this.groups;
    return html`
      <main class="shell">
        <section class="hero">
          <div>
            <p class="eyebrow">Local Codex Observatory</p>
            <h1>任务状态<br />一眼看清</h1>
            <p class="subtitle">读取本机 <code>~/.codex/sessions</code> 与归档会话，按项目与会话组织状态；同一个会话只展示一次。</p>
          </div>
          <div class="refresh-card">
            <div class="time">${this.clock}</div>
            <div class="label">${this.updatedLabel}</div>
            <button @click=${() => this.load().catch((error) => { this.updatedLabel = `加载失败：${error.message}`; })}>立即刷新</button>
          </div>
        </section>

        <section class="toolbar">
          <input class="field" .value=${this.query} @input=${(event) => { this.query = event.target.value; }} placeholder="搜索 prompt / cwd / 回复" />
          <select class="select" .value=${this.statusFilter} @change=${(event) => { this.statusFilter = event.target.value; }}>
            <option value="all">全部状态</option>
            <option value="running">运行中</option>
            <option value="approval_pending">待审批</option>
            <option value="approval_denied">审批拒绝</option>
            <option value="completed">已完成</option>
            <option value="error">错误</option>
          </select>
          <select class="select" .value=${this.sourceFilter} @change=${(event) => { this.sourceFilter = event.target.value; }}>
            <option value="all">全部来源</option>
            <option value="active">当前会话</option>
            <option value="archived">归档</option>
          </select>
          <select class="select" .value=${this.sortMode} @change=${(event) => { this.sortMode = event.target.value; }}>
            <option value="priority">运行中 / 待审批优先</option>
            <option value="updated">仅按最近更新</option>
          </select>
          <select class="select" .value=${this.limit} @change=${(event) => { this.limit = event.target.value; this.load().catch(console.error); }}>
            <option value="80">最近 80 个</option>
            <option value="160">最近 160 个</option>
            <option value="320">最近 320 个</option>
          </select>
        </section>

        <section class="metrics">
          <div class="metric"><div class="value">${this.summary?.total ?? this.tasks.length}</div><div class="name">已扫描任务</div></div>
          <div class="metric"><div class="value">${this.summary?.by_status?.running ?? 0}</div><div class="name">运行中</div></div>
          <div class="metric"><div class="value">${this.summary?.approvals?.pending ?? 0}</div><div class="name">权限待审批</div></div>
          <div class="metric"><div class="value">${this.summary?.by_source?.archived ?? 0}</div><div class="name">归档任务</div></div>
        </section>

        <section class="layout">
          <div class="panel">
            <div class="panel-head">
              <div class="panel-title">按项目 / 会话组织</div>
              <div class="meta">${this.sessionCount} 个会话 / ${this.filteredTasks.length} 个 turn</div>
            </div>
            <div
              class="tasks"
              @open-session=${this.openSession}
              @approval-decision=${this.handleApprovalDecision}
              @desktop-open-thread=${this.handleDesktopOpenThread}
            >
              ${groups.length
                ? groups.map((group) => html`<codex-project-group .group=${group} .liveApprovalCallIds=${this.liveApprovalCallIds}></codex-project-group>`)
                : html`<div class="empty">没有匹配任务</div>`}
            </div>
          </div>
          <aside class="side">
            <div class="panel">
              <div class="panel-title">活跃工作区</div>
              <div class="cwd-list">
                ${(this.summary?.top_cwds || []).length
                  ? this.summary.top_cwds.map(([cwd, count]) => html`
                    <div class="cwd-item"><span class="cwd-path" title=${cwd}>${shortPath(cwd)}</span><strong>${count}</strong></div>
                  `)
                  : html`<div class="empty">暂无工作区数据</div>`}
              </div>
            </div>
            <div class="panel">
              <div class="panel-title">网页审批</div>
              <div class="bridge-card ${this.approvalBridge?.connected ? 'connected' : ''}">
                <span class="badge ${this.approvalBridge?.connected ? 'completed' : 'approval-pending'}">
                  ${this.approvalBridge?.connected ? 'connected' : 'bridge'}
                </span>
                ${this.approvalBridge?.pending ? html`<span class="badge approval-pending">${this.approvalBridge.pending} 实时待审批</span>` : nothing}
                <p>${this.approvalMessage || this.approvalBridge?.message || '正在检查审批桥状态...'}</p>
                ${this.approvalBridge?.socket ? html`<code title=${this.approvalBridge.socket}>${shortPath(this.approvalBridge.socket)}</code>` : nothing}
              </div>
              <codex-live-approval-panel
                .approvals=${this.approvalBridge?.live_approvals || []}
                .desktopApprovals=${this.desktopPendingApprovals}
                @desktop-open-thread=${this.handleDesktopOpenThread}
              ></codex-live-approval-panel>
            </div>
            <div class="panel">
              <div class="panel-title">状态说明</div>
              <div class="legend">
                <span class="badge running">running</span>
                <span class="badge approval-pending">待审批</span>
                <span class="badge completed">completed</span>
                <span class="badge error">error</span>
                <span class="badge approval-denied">denied</span>
              </div>
            </div>
          </aside>
        </section>
      </main>
      ${this.dialogReady ? html`
        <codex-session-dialog
          .session=${this.selectedSession}
          .open=${Boolean(this.selectedSession)}
          @close-session=${this.closeSession}
        ></codex-session-dialog>
      ` : nothing}
    `;
  }
}

customElements.define('codex-dashboard', CodexDashboard);
