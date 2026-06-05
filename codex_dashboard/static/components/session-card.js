import { html, nothing } from '../vendor/lit.js';
import { LightDomElement } from './base.js';
import { duration, shortPath, timeAgo } from '../utils.js';

class CodexSessionCard extends LightDomElement {
  static properties = {
    session: { type: Object },
    liveApprovalCallIds: { type: Array },
  };

  constructor() {
    super();
    this.liveApprovalCallIds = [];
  }

  emitOpen() {
    this.dispatchEvent(new CustomEvent('open-session', {
      detail: { session: this.session },
      bubbles: true,
      composed: true,
    }));
  }

  handleKeydown(event) {
    if (event.key !== 'Enter' && event.key !== ' ') return;
    event.preventDefault();
    this.emitOpen();
  }

  emitApprovalDecision(event, approval, decision) {
    event.stopPropagation();
    this.dispatchEvent(new CustomEvent('approval-decision', {
      detail: { session: this.session, approval, decision },
      bubbles: true,
      composed: true,
    }));
  }

  emitOpenDesktopThread(event) {
    event.stopPropagation();
    this.dispatchEvent(new CustomEvent('desktop-open-thread', {
      detail: { threadId: this.session?.session_id },
      bubbles: true,
      composed: true,
    }));
  }

  render() {
    const session = this.session;
    if (!session) return nothing;
    const latest = session.turns[0] || {};
    const pendingApproval = session.approval_requests?.find((request) => request.status === 'pending');
    const liveApproval = pendingApproval && this.liveApprovalCallIds.includes(pendingApproval.call_id);
    return html`
      <article class="task session-card" role="button" tabindex="0" aria-label="查看会话记录" @click=${this.emitOpen} @keydown=${this.handleKeydown}>
        <div>
          <span class="badge ${session.status}">${session.status}</span>
          ${session.approval_pending ? html`<span class="badge approval-pending">${session.approval_pending} 待审批</span>` : nothing}
          ${!session.approval_pending && session.approval_denied ? html`<span class="badge approval-denied">${session.approval_denied} 已拒绝</span>` : nothing}
          <div class="meta">${session.source_label} · ${timeAgo(latest.updated_at || latest.completed_at || latest.started_at)}</div>
        </div>
        <div>
          <div class="session-title" title=${session.title}>${session.title}</div>
          <div class="meta">
            <span title=${session.cwd || ''}>${shortPath(session.cwd)}</span>
            <span>${session.originator || ''}</span>
            <span>${session.turns.length} turns</span>
            <span>${session.function_calls || 0} tools</span>
            ${session.approval_total ? html`<span>${session.approval_total} approvals</span>` : nothing}
            <span>${(session.session_id || '').slice(0, 8)}</span>
          </div>
          ${pendingApproval ? html`
            <div class="approval-note" title=${pendingApproval.command || ''} @click=${(event) => event.stopPropagation()}>
              <div class="approval-text">${pendingApproval.justification || '等待权限审批'}</div>
              ${pendingApproval.command ? html`<div class="approval-command">${pendingApproval.command}</div>` : nothing}
              ${liveApproval ? html`
                <div class="approval-actions">
                  <button class="approval-button primary" type="button" @click=${(event) => this.emitApprovalDecision(event, pendingApproval, 'accept')}>批准本次</button>
                  ${pendingApproval.prefix_rule?.length ? html`
                    <button class="approval-button" type="button" @click=${(event) => this.emitApprovalDecision(event, pendingApproval, 'accept_for_session')}>本会话批准</button>
                  ` : nothing}
                  <button class="approval-button danger" type="button" @click=${(event) => this.emitApprovalDecision(event, pendingApproval, 'decline')}>拒绝</button>
                </div>
              ` : html`
                <div class="approval-stale">Desktop / 历史待审批：当前 app-server 未捕获实时回调，网页不能安全代批。</div>
                ${session.session_id ? html`
                  <button class="approval-open-link" type="button" @click=${this.emitOpenDesktopThread}>
                    打开 Desktop 原会话审批
                  </button>
                ` : nothing}
              `}
            </div>
          ` : nothing}
          ${session.last_agent_message ? html`<div class="reply">${session.last_agent_message}</div>` : nothing}
        </div>
        <div class="meta duration">
          <span>${duration(latest.duration_ms)}</span>
          <span>${session.token_total ? `${session.token_total.toLocaleString()} tokens` : 'tokens -'}</span>
        </div>
      </article>
    `;
  }
}

customElements.define('codex-session-card', CodexSessionCard);
