import { html } from 'lit';
import { LightDomElement } from './base.js';
import { shortPath } from '../utils.js';
import './conversation-message.js';

class CodexSessionDialog extends LightDomElement {
  static properties = {
    session: { type: Object },
    open: { type: Boolean },
    messages: { state: true },
    loading: { state: true },
    error: { state: true },
  };

  constructor() {
    super();
    this.session = null;
    this.open = false;
    this.messages = [];
    this.loading = false;
    this.error = '';
  }

  updated(changed) {
    if (changed.has('session') && this.session) {
      this.loadMessages();
    }
  }

  async loadMessages() {
    this.loading = true;
    this.error = '';
    this.messages = [];
    try {
      const params = new URLSearchParams({ file: this.session.file });
      const res = await fetch(`/api/session?${params.toString()}`);
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();
      this.messages = data.messages || [];
    } catch (error) {
      this.error = error.message;
    } finally {
      this.loading = false;
    }
  }

  close() {
    this.dispatchEvent(new CustomEvent('close-session', { bubbles: true, composed: true }));
  }

  handleBackdropClick(event) {
    if (event.target === event.currentTarget) this.close();
  }

  handleKeydown(event) {
    if (event.key === 'Escape') this.close();
  }

  scrollToBottom() {
    const conversation = this.querySelector('.conversation');
    conversation?.scrollTo({ top: conversation.scrollHeight, behavior: 'auto' });
  }

  renderConversation() {
    if (this.loading) return html`<div class="empty">加载会话记录...</div>`;
    if (this.error) return html`<div class="empty">加载失败：${this.error}</div>`;
    if (!this.messages.length) return html`<div class="empty">这个会话还没有可展示的对话记录</div>`;
    return this.messages.map((message) => html`<codex-conversation-message .message=${message}></codex-conversation-message>`);
  }

  render() {
    const session = this.session;
    return html`
      <div class="dialog-backdrop ${this.open ? 'open' : ''}" aria-hidden=${String(!this.open)} @click=${this.handleBackdropClick} @keydown=${this.handleKeydown}>
        <section class="dialog" role="dialog" aria-modal="true" aria-labelledby="dialog-title">
          <header class="dialog-head">
            <div>
              <div class="dialog-title" id="dialog-title" title=${session?.title || '会话记录'}>${session?.title || '会话记录'}</div>
              <div class="meta">${session ? `${session.project} · ${shortPath(session.cwd)} · ${session.turns.length} turns · ${(session.session_id || '').slice(0, 8)}` : ''}</div>
            </div>
            <div class="dialog-actions">
              <button class="dialog-bottom" type="button" ?disabled=${this.loading || !this.messages.length} @click=${this.scrollToBottom}>跳到底部</button>
              <button class="dialog-close" aria-label="关闭" @click=${this.close}>×</button>
            </div>
          </header>
          <div class="conversation">${this.renderConversation()}</div>
        </section>
      </div>
    `;
  }
}

customElements.define('codex-session-dialog', CodexSessionDialog);
