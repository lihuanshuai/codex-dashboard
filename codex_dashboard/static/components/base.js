import { LitElement } from '../vendor/lit.js';

export class LightDomElement extends LitElement {
  createRenderRoot() {
    return this;
  }
}
