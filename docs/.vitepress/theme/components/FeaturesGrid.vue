<!-- SPDX-License-Identifier: Apache-2.0 -->

<!--
  The home page's features. The frontmatter's `features` field cannot
  carry SVG icons, so the grid renders here instead; every claim below
  is a rewording of a README statement. The `.np-*` classes live in
  custom.css, next to the rest of the visual identity.
-->
<script setup lang="ts">
import { withBase } from 'vitepress';

/** Link to the site's copy of the README's benchmark section. */
const METHOD_LINK = withBase('/method');
</script>

<template>
  <section class="np-section" aria-labelledby="features-title">
    <div class="np-section-inner">
      <header class="np-section-head">
        <p class="np-kicker">What you get</p>
        <h2 id="features-title" class="np-section-title">A local gate in front of the model</h2>
      </header>

      <div class="np-features">
        <article class="np-feature">
          <span class="np-feature-icon" aria-hidden="true">
            <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">
              <path d="M12 3l7 3v5c0 4.6-3 7.7-7 9.2-4-1.5-7-4.6-7-9.2V6l7-3z" />
              <path d="M9 11.5l2 2 4-4.5" />
            </svg>
          </span>
          <h3 class="np-feature-title">Local detection</h3>
          <p class="np-feature-details">
            A fine-tuned GLiNER model plus a set of pattern recognizers, on your CPU or GPU.
            Your text goes nowhere, and the vault lives in memory only.
          </p>
        </article>

        <article class="np-feature">
          <span class="np-feature-icon" aria-hidden="true">
            <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">
              <rect x="3" y="4" width="18" height="16" rx="2" />
              <path d="M7 9l3 3-3 3" />
              <path d="M13 15h4" />
            </svg>
          </span>
          <h3 class="np-feature-title">Built for coding agents</h3>
          <p class="np-feature-details">
            Masks tool output — files, logs, command output — not only prompts, and keeps
            links to code hosts and documentation readable. Built and tested with Claude Code,
            through the mod or the gateway.
          </p>
        </article>

        <article class="np-feature">
          <span class="np-feature-icon" aria-hidden="true">
            <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">
              <path d="M4 7h13" />
              <path d="M14 4l3 3-3 3" />
              <path d="M20 17H7" />
              <path d="M10 14l-3 3 3 3" />
            </svg>
          </span>
          <h3 class="np-feature-title">Works with any model</h3>
          <p class="np-feature-details">
            Mask before your LLM call and restore after it. Or point your client at the
            gateway, in front of the Anthropic Messages API or the OpenAI Chat Completions
            API.
          </p>
        </article>

        <article class="np-feature">
          <span class="np-feature-icon" aria-hidden="true">
            <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">
              <path d="M4 7h4" />
              <circle cx="10" cy="7" r="2" />
              <path d="M12 7h8" />
              <path d="M4 15h8" />
              <circle cx="14" cy="15" r="2" />
              <path d="M16 15h4" />
            </svg>
          </span>
          <h3 class="np-feature-title">One policy for everything</h3>
          <p class="np-feature-details">
            One JSON file decides what gets masked, for the library, the CLI, the gateway and
            the Claude Code mod: per category, mask it, ask first, or leave it readable.
          </p>
        </article>

        <article class="np-feature">
          <span class="np-feature-icon" aria-hidden="true">
            <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">
              <path d="M20 12a8 8 0 1 1-2.34-5.66" />
              <path d="M20 4v4h-4" />
            </svg>
          </span>
          <h3 class="np-feature-title">Reversible by design</h3>
          <p class="np-feature-details">
            A placeholder belongs to its session, and one value always gets the same
            placeholder. Streaming restore puts the real values back into chunked replies.
          </p>
        </article>

        <article class="np-feature">
          <span class="np-feature-icon" aria-hidden="true">
            <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">
              <circle cx="10.5" cy="10.5" r="6.5" />
              <path d="M15.5 15.5L20.5 20.5" />
              <path d="M8 13.5v-3" />
              <path d="M10.5 13.5v-6" />
              <path d="M13 13.5v-4.5" />
            </svg>
          </span>
          <h3 class="np-feature-title">Measured, every result published</h3>
          <p class="np-feature-details">
            Benchmarked on coding-agent traffic and held-out document sets, with every result
            published. See
            <a :href="METHOD_LINK">the benchmark</a>.
          </p>
        </article>
      </div>
    </div>
  </section>
</template>
