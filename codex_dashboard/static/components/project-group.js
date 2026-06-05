import { html, nothing } from '../vendor/lit.js';
import { LightDomElement } from './base.js';
import { shortPath } from '../utils.js';
import './session-card.js';

class CodexProjectGroup extends LightDomElement {
  static properties = { group: { type: Object } };

  render() {
    const group = this.group;
    if (!group) return nothing;
    return html`
      <section class="project-group">
        <header class="project-head">
          <div>
            <div class="project-title" title=${group.project}>${group.project}</div>
            <div class="project-path" title=${group.cwd || ''}>${shortPath(group.cwd)}</div>
          </div>
          <div class="project-count">
            <span class="badge">${group.sessions.length} sessions</span>
            ${group.approval_pending ? html`<span class="badge approval-pending">${group.approval_pending} 待审批</span>` : nothing}
            ${group.running ? html`<span class="badge running">${group.running} running</span>` : nothing}
            ${group.completed ? html`<span class="badge completed">${group.completed} done</span>` : nothing}
            ${group.error ? html`<span class="badge error">${group.error} error</span>` : nothing}
            ${group.approval_denied ? html`<span class="badge approval-denied">${group.approval_denied} denied</span>` : nothing}
          </div>
        </header>
        ${group.sessions.map((session) => html`<codex-session-card .session=${session}></codex-session-card>`)}
      </section>
    `;
  }
}

customElements.define('codex-project-group', CodexProjectGroup);
