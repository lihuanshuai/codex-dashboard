import { LitElement } from 'lit';

export class LightDomElement extends LitElement {
  createRenderRoot() {
    return this;
  }
}
