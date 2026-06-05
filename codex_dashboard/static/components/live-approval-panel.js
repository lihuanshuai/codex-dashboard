import { html, nothing } from '../vendor/lit.js';
import { LightDomElement } from './base.js';
import { shortPath } from '../utils.js';

class CodexLiveApprovalPanel extends LightDomElement {
  static properties = {
    approvals: { type: Array },
    desktopApprovals: { type: Array },
  };

  constructor() {
    super();
    this.approvals = [];
    this.desktopApprovals = [];
  }

  emitDecision(approval, decision) {
    this.dispatchEvent(new CustomEvent('approval-decision', {
      detail: { approval, decision },
      bubbles: true,
      composed: true,
    }));
  }

  emitOpenDesktopThread(approval) {
    this.dispatchEvent(new CustomEvent('desktop-open-thread', {
      detail: { threadId: approval.thread_id },
      bubbles: true,
      composed: true,
    }));
  }

  renderApproval(approval) {
    const title = approval.command || approval.reason || approval.call_id;
    return html`
      <div class="live-approval">
        <div class="live-approval-command" title=${title}>${title}</div>
        ${approval.cwd ? html`<div class="live-approval-meta" title=${approval.cwd}>${shortPath(approval.cwd)}</div>` : nothing}
        ${approval.reason ? html`<div class="live-approval-reason">${approval.reason}</div>` : nothing}
        <div class="approval-actions">
          <button class="approval-button primary" type="button" @click=${() => this.emitDecision(approval, 'accept')}>批准本次</button>
          ${approval.can_accept_for_session ? html`
            <button class="approval-button" type="button" @click=${() => this.emitDecision(approval, 'accept_for_session')}>本会话批准</button>
          ` : nothing}
          <button class="approval-button danger" type="button" @click=${() => this.emitDecision(approval, 'decline')}>拒绝</button>
        </div>
      </div>
    `;
  }

  renderDesktopApproval(approval) {
    const title = approval.command || approval.reason || approval.title || approval.call_id;
    return html`
      <div class="live-approval stale">
        <div class="live-approval-command" title=${title}>${title}</div>
        ${approval.cwd ? html`<div class="live-approval-meta" title=${approval.cwd}>${shortPath(approval.cwd)}</div>` : nothing}
        ${approval.title ? html`<div class="live-approval-reason" title=${approval.title}>${approval.title}</div>` : nothing}
        <div class="approval-stale">来自 Codex Desktop / JSONL；当前 Desktop 未暴露可安全注入的网页审批通道。</div>
        ${approval.thread_id ? html`
          <button class="approval-open-link" type="button" @click=${() => this.emitOpenDesktopThread(approval)}>
            打开 Desktop 原会话审批
          </button>
        ` : nothing}
      </div>
    `;
  }

  render() {
    return html`
      <div class="live-approvals">
        <div class="approval-section-title">实时可审批</div>
        ${this.approvals.length
          ? this.approvals.map((approval) => this.renderApproval(approval))
          : html`<div class="empty compact">暂无实时审批请求</div>`}
        <div class="approval-section-title">Desktop 待审批监控</div>
        ${this.desktopApprovals.length
          ? this.desktopApprovals.map((approval) => this.renderDesktopApproval(approval))
          : html`<div class="empty compact">暂无 Desktop 待审批</div>`}
      </div>
    `;
  }
}

customElements.define('codex-live-approval-panel', CodexLiveApprovalPanel);
