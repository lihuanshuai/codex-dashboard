import { html, nothing } from 'lit';
import { LightDomElement } from './base.js';
import { timeAgo } from '../utils.js';

class CodexConversationMessage extends LightDomElement {
  static properties = { message: { type: Object } };

  render() {
    const message = this.message;
    if (!message) return nothing;
    return html`
      <article class="message ${message.role}">
        <div class="message-role">${message.role} · ${timeAgo(message.timestamp)}</div>
        <div class="message-text">${message.text}</div>
      </article>
    `;
  }
}

customElements.define('codex-conversation-message', CodexConversationMessage);
