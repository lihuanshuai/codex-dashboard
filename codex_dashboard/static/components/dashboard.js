import { html, nothing } from '../vendor/lit.js';
import { LightDomElement } from './base.js';
import { clockFormat, groupTasksByProject, shortPath } from '../utils.js';
import './project-group.js';

class CodexDashboard extends LightDomElement {
  static properties = {
    tasks: { state: true },
    summary: { state: true },
    query: { state: true },
    statusFilter: { state: true },
    sourceFilter: { state: true },
    limit: { state: true },
    updatedLabel: { state: true },
    clock: { state: true },
    selectedSession: { state: true },
    dialogReady: { state: true },
  };

  constructor() {
    super();
    this.tasks = [];
    this.summary = null;
    this.query = '';
    this.statusFilter = 'all';
    this.sourceFilter = 'all';
    this.limit = '80';
    this.updatedLabel = '等待加载';
    this.clock = clockFormat.format(new Date());
    this.selectedSession = null;
    this.dialogReady = false;
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
    return groupTasksByProject(this.filteredTasks);
  }

  get sessionCount() {
    return this.groups.reduce((sum, group) => sum + group.sessions.length, 0);
  }

  async load() {
    const res = await fetch(`/api/tasks?limit=${encodeURIComponent(this.limit)}`);
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const data = await res.json();
    this.tasks = data.tasks;
    this.summary = data.summary;
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
            <div class="tasks" @open-session=${this.openSession}>
              ${groups.length
                ? groups.map((group) => html`<codex-project-group .group=${group}></codex-project-group>`)
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
