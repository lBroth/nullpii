<!-- SPDX-License-Identifier: Apache-2.0 -->

<!--
  The home page's animated backdrop: four decorative layers on the
  theme of masking data, behind the content and out of its way — fixed
  to the viewport, pointer-events none, aria-hidden, and below
  everything else in the stacking order. Each layer reads the VitePress
  color tokens directly, so light and dark mode work without a second
  copy of anything.

  The layers drift at different speeds as the page scrolls, driven by
  CSS scroll-driven animations only (animation-timeline: scroll(root)):
  no JavaScript, no scroll listeners, and nothing but transform and
  opacity animated. Browsers without animation-timeline support, and
  users who prefer no motion, get the same layers standing still.
-->

<template>
  <div class="np-bg" aria-hidden="true">
    <!-- Layer 1, the farthest: a faint dot grid over the whole page. -->
    <div class="np-bg-layer np-bg-dots">
      <svg class="np-bg-dots-svg" focusable="false">
        <defs>
          <pattern id="np-bg-dot-grid" width="26" height="26" patternUnits="userSpaceOnUse">
            <circle class="np-bg-dot" cx="1.5" cy="1.5" r="1.5" />
          </pattern>
        </defs>
        <rect class="np-bg-dots-field" width="100%" height="100%" fill="url(#np-bg-dot-grid)" />
      </svg>
    </div>

    <!-- Layer 2: a document with its lines redacted, upper right. -->
    <div class="np-bg-layer np-bg-doc">
      <svg class="np-bg-doc-svg" viewBox="0 0 300 220" focusable="false">
        <g class="np-bg-doc-rows">
          <rect x="0" y="6" width="88" height="12" rx="6" />
          <rect x="96" y="6" width="126" height="12" rx="6" />
          <rect x="230" y="6" width="62" height="12" rx="6" />
          <rect x="0" y="34" width="150" height="12" rx="6" />
          <rect x="158" y="34" width="88" height="12" rx="6" />
          <rect x="26" y="62" width="204" height="12" rx="6" />
          <rect x="0" y="90" width="112" height="12" rx="6" />
          <rect x="120" y="90" width="134" height="12" rx="6" />
          <rect x="0" y="118" width="64" height="12" rx="6" />
          <rect x="72" y="118" width="98" height="12" rx="6" />
          <rect x="178" y="118" width="52" height="12" rx="6" />
          <rect x="38" y="146" width="170" height="12" rx="6" />
          <rect x="0" y="174" width="86" height="12" rx="6" />
          <rect x="94" y="174" width="142" height="12" rx="6" />
          <rect x="0" y="202" width="54" height="12" rx="6" />
          <rect x="62" y="202" width="80" height="12" rx="6" />
        </g>
      </svg>
    </div>

    <!-- Layer 3: a few scattered placeholder glyphs, in the mono font. -->
    <div class="np-bg-layer np-bg-glyphs">
      <svg class="np-bg-glyph np-bg-glyph-a" viewBox="0 0 78 30" focusable="false">
        <text
          v-pre
          class="np-bg-glyph-text"
          x="3"
          y="23"
          transform="rotate(-5 39 15)"
        >{{…}}</text>
      </svg>
      <svg class="np-bg-glyph np-bg-glyph-b" viewBox="0 0 44 22" focusable="false">
        <text
          v-pre
          class="np-bg-glyph-text"
          x="2"
          y="17"
          transform="rotate(4 22 11)"
        >{…}</text>
      </svg>
      <svg class="np-bg-glyph np-bg-glyph-c" viewBox="0 0 60 26" focusable="false">
        <text
          v-pre
          class="np-bg-glyph-text"
          x="2"
          y="19"
          transform="rotate(-3 30 13)"
        >{{…}}</text>
      </svg>
    </div>

    <!-- Layer 4, the nearest: a soft brand glow behind the hero. -->
    <div class="np-bg-layer np-bg-glow" />
  </div>
</template>

<style scoped>
/* The stack is fixed behind the whole home page: it never takes a
 * pointer event (so no link, button or the search can sit behind it
 * blocked), and it is clipped to the viewport, so nothing in it can
 * widen the page — fixed boxes never create scrollbars either way. */
.np-bg {
  position: fixed;
  inset: 0;
  z-index: -1;
  overflow: clip;
  pointer-events: none;
  user-select: none;
}

.np-bg-layer {
  position: absolute;
}

/* ---------------------------------------------------------------------
 * Layer 1: the dot grid
 * ------------------------------------------------------------------- */

.np-bg-dots {
  inset: 0;
}

.np-bg-dots-svg {
  position: absolute;
  top: 0;
  left: 0;
  display: block;
  /* 8vh of slack below the fold, so the layer's slow drift can never
   * uncover the bottom edge. */
  width: 100%;
  height: calc(100% + 8vh);
  opacity: 0.4;
  /* The grid dissolves towards the bottom of the fold. */
  -webkit-mask-image: linear-gradient(to bottom, #000 30%, transparent 78%);
  mask-image: linear-gradient(to bottom, #000 30%, transparent 78%);
}

.np-bg-dot {
  fill: var(--vp-c-text-3);
}

/* ---------------------------------------------------------------------
 * Layer 2: the redacted lines
 * ------------------------------------------------------------------- */

/* Below the hero's lock, which owns the upper right. */
.np-bg-doc {
  top: 64%;
  right: 3%;
  width: clamp(200px, 24vw, 330px);
  opacity: 0.3;
}

.np-bg-doc-svg {
  display: block;
  width: 100%;
  height: auto;
}

.np-bg-doc-rows {
  fill: var(--vp-c-text-3);
}

/* ---------------------------------------------------------------------
 * Layer 3: the placeholder glyphs
 * ------------------------------------------------------------------- */

.np-bg-glyphs {
  inset: 0;
}

.np-bg-glyph {
  position: absolute;
  display: block;
  opacity: 0.35;
}

.np-bg-glyph-a {
  left: 6%;
  top: 13%;
  width: 78px;
}

.np-bg-glyph-b {
  right: 7%;
  top: 35%;
  width: 44px;
}

/* Clear of the hero text's column, under the lock. */
.np-bg-glyph-c {
  right: 26%;
  top: 80%;
  width: 60px;
}

.np-bg-glyph-text {
  fill: var(--vp-c-brand-1);
  font-family: var(--vp-font-family-mono);
}

.np-bg-glyph-a .np-bg-glyph-text {
  font-size: 22px;
}

.np-bg-glyph-b .np-bg-glyph-text {
  font-size: 15px;
}

.np-bg-glyph-c .np-bg-glyph-text {
  font-size: 18px;
}

/* ---------------------------------------------------------------------
 * Layer 4: the glow
 * ------------------------------------------------------------------- */

.np-bg-glow {
  left: 0;
  right: 0;
  top: -22vh;
  height: 60vh;
  /* Off the hero's own gradient's center, so the two read as one wash
   * rather than stacking into a hotspot. */
  background: radial-gradient(58% 62% at 62% 38%, var(--vp-c-brand-soft), transparent 72%);
}

/* On a phone the two object layers would sit under the single text
 * column; keep the two quiet, full-width layers only. */
@media (max-width: 639px) {
  .np-bg-doc,
  .np-bg-glyphs {
    display: none;
  }
}

/* ---------------------------------------------------------------------
 * The parallax
 * ------------------------------------------------------------------- */

/* Each layer rides the page scroll at its own speed, on the root
 * scroll timeline — CSS only. The common timing longhands first,
 * then each layer's keyframes and timeline; a duration is required
 * syntactically but ignored for a progress-based timeline. */
@media (prefers-reduced-motion: no-preference) {
  @supports (animation-timeline: scroll(root)) {
    .np-bg-dots,
    .np-bg-doc,
    .np-bg-glyphs,
    .np-bg-glow {
      animation-duration: 1s;
      animation-timing-function: linear;
      animation-iteration-count: 1;
      animation-fill-mode: both;
    }

    .np-bg-dots {
      animation-name: np-bg-drift-dots;
      animation-timeline: scroll(root);
    }

    .np-bg-doc {
      animation-name: np-bg-drift-doc;
      animation-timeline: scroll(root);
    }

    .np-bg-glyphs {
      animation-name: np-bg-drift-glyphs;
      animation-timeline: scroll(root);
    }

    .np-bg-glow {
      animation-name: np-bg-drift-glow;
      animation-timeline: scroll(root);
    }
  }
}

/* Belt and braces: nothing in the backdrop ever moves for a user who
 * asked for reduced motion. */
@media (prefers-reduced-motion: reduce) {
  .np-bg-layer {
    animation: none;
  }
}

/* The farther a layer reads, the less it travels: the grid crawls, the
 * document and the glyphs drift up like content in the distance, and
 * the glow sinks behind the fold. Only transform (and the glow's
 * opacity) is animated. */
@keyframes np-bg-drift-dots {
  from {
    transform: translateY(0);
  }

  to {
    transform: translateY(-5vh);
  }
}

@keyframes np-bg-drift-doc {
  from {
    transform: translateY(0);
  }

  to {
    transform: translateY(-12vh);
  }
}

@keyframes np-bg-drift-glyphs {
  from {
    transform: translateY(0);
  }

  to {
    transform: translateY(-22vh);
  }
}

@keyframes np-bg-drift-glow {
  from {
    transform: translateY(0);
    opacity: 1;
  }

  to {
    transform: translateY(6vh);
    opacity: 0.5;
  }
}
</style>