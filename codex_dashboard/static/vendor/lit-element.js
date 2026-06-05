/**
 * Bundled by jsDelivr using Rollup v2.79.2 and Terser v5.39.0.
 * Original file: /npm/lit-element@4.2.2/lit-element.js
 *
 * Do NOT use SRI with dynamically generated files! More information: https://www.jsdelivr.com/using-sri-with-dynamic-files
 */
import{ReactiveElement as e}from"./reactive-element.js";export*from"./reactive-element.js";import{render as t,noChange as n}from"./lit-html.js";export*from"./lit-html.js";
/**
 * @license
 * Copyright 2017 Google LLC
 * SPDX-License-Identifier: BSD-3-Clause
 */const s=globalThis;class r extends e{constructor(){super(...arguments),this.renderOptions={host:this},this._$Do=void 0}createRenderRoot(){const e=super.createRenderRoot();return this.renderOptions.renderBefore??=e.firstChild,e}update(e){const n=this.render();this.hasUpdated||(this.renderOptions.isConnected=this.isConnected),super.update(e),this._$Do=t(n,this.renderRoot,this.renderOptions)}connectedCallback(){super.connectedCallback(),this._$Do?.setConnected(!0)}disconnectedCallback(){super.disconnectedCallback(),this._$Do?.setConnected(!1)}render(){return n}}r._$litElement$=!0,r.finalized=!0,s.litElementHydrateSupport?.({LitElement:r});const o=s.litElementPolyfillSupport;o?.({LitElement:r});const i={_$AK:(e,t,n)=>{e._$AK(t,n)},_$AL:e=>e._$AL};(s.litElementVersions??=[]).push("4.2.2");export{r as LitElement,i as _$LE};export default null;
//# sourceMappingURL=/static/vendor/sourcemap-disabled/4a71989762c965175e01b9c24a2d8271b6baa47f1a54d0276b9a0325197a6adb.map