<!-- SPDX-License-Identifier: Apache-2.0 -->

<!--
  The home page's "how it works" section: one inline SVG of the
  pipeline, drawn twice — a wide flow for desktop, a stacked one for
  phones. Both show the same README example: a prompt with real values
  goes into nullpii, the LLM provider sees only placeholders, and the
  reply's values come back only into the local tools the policy allows.
-->
<script setup lang="ts">
/** The placeholders the README's example prompt turns into, verbatim. */
const PERSON_TOKEN = '{{PII_PRIVATE_PERSON_0_…}}';
const EMAIL_TOKEN = '{{PII_PRIVATE_EMAIL_0_…}}';
</script>

<template>
  <section class="np-section" aria-labelledby="how-it-works-title">
    <div class="np-section-inner">
      <header class="np-section-head">
        <p class="np-kicker">How it works</p>
        <h2 id="how-it-works-title" class="np-section-title">
          Masked on the way in, restored on the way out
        </h2>
        <p class="np-section-lead">
          A fine-tuned GLiNER model and a set of pattern recognizers find the values, and an
          in-memory vault swaps each one for a placeholder and back. The model you call sees
          only placeholders; the real values return only into the local tools you allow —
          never into a shell command.
        </p>
      </header>

      <!-- Wide flow: the dashed rect is your machine, and nothing real
           crosses its border. -->
      <svg
        class="np-flow-desktop"
        viewBox="0 0 880 400"
        role="img"
        aria-labelledby="np-flow-d-title"
      >
        <title id="np-flow-d-title">
          Your machine holds the prompt "Email John Smith at john@acme.io". nullpii masks the
          person and the email into placeholders kept in an in-memory vault, and only the
          placeholders cross to the LLM provider. The reply crosses back still masked, and
          nullpii restores the real values only into the file tools; shell commands keep the
          placeholders.
        </title>

        <defs>
          <marker
            id="np-arrow-d"
            viewBox="0 0 8 8"
            refX="7"
            refY="4"
            markerWidth="7"
            markerHeight="7"
            orient="auto-start-reverse"
          >
            <path d="M0 0 L8 4 L0 8 Z" class="np-arrowhead" />
          </marker>
        </defs>

        <!-- your machine -->
        <rect class="np-zone" x="12" y="34" width="508" height="352" rx="16" />
        <text class="np-zone-label" x="28" y="58">YOUR MACHINE</text>

        <!-- the LLM provider, outside it -->
        <rect class="np-provider-zone" x="664" y="58" width="204" height="132" rx="12" />
        <text class="np-card-title" x="766" y="92">LLM provider</text>
        <text class="np-card-sub" x="766" y="112">sees only placeholders</text>
        <rect class="np-token-chip" x="682" y="124" width="168" height="20" rx="5" />
        <text class="np-token" x="766" y="138">{{ PERSON_TOKEN }}</text>
        <rect class="np-token-chip" x="682" y="150" width="168" height="20" rx="5" />
        <text class="np-token" x="766" y="164">{{ EMAIL_TOKEN }}</text>

        <!-- your prompt -->
        <rect class="np-card" x="40" y="84" width="176" height="96" rx="10" />
        <text class="np-card-label" x="54" y="106">YOUR PROMPT</text>
        <text class="np-text" x="54" y="130">
          Email <tspan class="np-pii">John Smith</tspan>
        </text>
        <text class="np-text" x="54" y="148">
          at <tspan class="np-pii">john@acme.io</tspan>
        </text>

        <!-- nullpii, masking -->
        <rect class="np-brand-box" x="276" y="76" width="168" height="112" rx="12" />
        <text class="np-box-title" x="360" y="106">nullpii</text>
        <text class="np-box-sub" x="360" y="126">GLiNER model</text>
        <text class="np-box-sub" x="360" y="142">+ pattern recognizers</text>
        <rect class="np-vault-chip" x="298" y="154" width="124" height="22" rx="11" />
        <text class="np-chip-text np-brand-text" x="360" y="169">in-memory vault</text>

        <!-- nullpii, restoring -->
        <rect class="np-brand-box" x="276" y="252" width="168" height="112" rx="12" />
        <text class="np-box-title" x="360" y="282">nullpii</text>
        <text class="np-box-sub" x="360" y="302">restores the values</text>
        <text class="np-box-sub" x="360" y="318">only the tools in the policy</text>

        <!-- local tools -->
        <rect class="np-card" x="40" y="256" width="176" height="56" rx="10" />
        <text class="np-card-label" x="54" y="278">FILE TOOLS</text>
        <rect class="np-chip-ok" x="54" y="288" width="112" height="20" rx="10" />
        <text class="np-chip-text np-ok-text" x="110" y="302">real values back</text>
        <rect class="np-card" x="40" y="328" width="176" height="56" rx="10" />
        <text class="np-card-label" x="54" y="350">SHELL COMMANDS</text>
        <rect class="np-chip-keep" x="54" y="360" width="112" height="20" rx="10" />
        <text class="np-chip-text np-keep-text" x="110" y="374">placeholders stay</text>

        <!-- the arrows -->
        <line class="np-arrow" x1="216" y1="132" x2="276" y2="132" marker-end="url(#np-arrow-d)" />
        <line
          class="np-arrow"
          x1="444"
          y1="132"
          x2="664"
          y2="132"
          marker-end="url(#np-arrow-d)"
        />
        <text class="np-key-label" x="554" y="118">placeholders only</text>
        <polyline
          class="np-arrow"
          points="766,190 766,308 444,308"
          marker-end="url(#np-arrow-d)"
        />
        <text class="np-arrow-label" x="605" y="296">reply with placeholders</text>
        <line class="np-arrow" x1="276" y1="284" x2="216" y2="284" marker-end="url(#np-arrow-d)" />
        <line class="np-arrow" x1="276" y1="356" x2="216" y2="356" marker-end="url(#np-arrow-d)" />
      </svg>

      <!-- Stacked flow for phones. -->
      <svg
        class="np-flow-mobile"
        viewBox="0 0 340 538"
        role="img"
        aria-labelledby="np-flow-m-title"
      >
        <title id="np-flow-m-title">
          Your prompt is masked into placeholders by nullpii, the LLM provider sees only the
          placeholders, and the reply's values are restored by nullpii only into the file
          tools; shell commands keep the placeholders.
        </title>

        <defs>
          <marker
            id="np-arrow-m"
            viewBox="0 0 8 8"
            refX="7"
            refY="4"
            markerWidth="7"
            markerHeight="7"
            orient="auto-start-reverse"
          >
            <path d="M0 0 L8 4 L0 8 Z" class="np-arrowhead" />
          </marker>
        </defs>

        <rect class="np-card" x="40" y="16" width="260" height="76" rx="10" />
        <text class="np-card-label" x="54" y="34">YOUR PROMPT</text>
        <text class="np-text" x="54" y="54">
          Email <tspan class="np-pii">John Smith</tspan>
        </text>
        <text class="np-text" x="54" y="72">
          at <tspan class="np-pii">john@acme.io</tspan>
        </text>

        <line class="np-arrow" x1="170" y1="92" x2="170" y2="124" marker-end="url(#np-arrow-m)" />
        <text class="np-key-label-side" x="180" y="112">placeholders only</text>

        <rect class="np-brand-box" x="40" y="124" width="260" height="92" rx="12" />
        <text class="np-box-title" x="170" y="148">nullpii</text>
        <text class="np-box-sub" x="170" y="168">GLiNER model + pattern recognizers</text>
        <rect class="np-vault-chip" x="115" y="180" width="110" height="22" rx="11" />
        <text class="np-chip-text np-brand-text" x="170" y="195">in-memory vault</text>

        <line class="np-arrow" x1="170" y1="216" x2="170" y2="248" marker-end="url(#np-arrow-m)" />

        <rect class="np-provider-zone" x="40" y="248" width="260" height="88" rx="10" />
        <text class="np-card-title" x="170" y="272">LLM provider</text>
        <text class="np-card-sub" x="170" y="290">sees only placeholders</text>
        <rect class="np-token-chip" x="55" y="302" width="230" height="20" rx="5" />
        <text class="np-token" x="170" y="316">{{ PERSON_TOKEN }}</text>

        <line class="np-arrow" x1="170" y1="336" x2="170" y2="368" marker-end="url(#np-arrow-m)" />
        <text class="np-arrow-label-side" x="180" y="357">reply with placeholders</text>

        <rect class="np-brand-box" x="40" y="368" width="260" height="64" rx="12" />
        <text class="np-box-title" x="170" y="392">nullpii</text>
        <text class="np-box-sub" x="170" y="412">restores the values</text>

        <line class="np-arrow" x1="170" y1="432" x2="170" y2="458" marker-end="url(#np-arrow-m)" />

        <rect class="np-card" x="20" y="458" width="145" height="72" rx="10" />
        <text class="np-tool-title" x="92" y="480">file tools</text>
        <rect class="np-chip-ok" x="44" y="492" width="97" height="20" rx="10" />
        <text class="np-chip-text np-ok-text" x="92" y="506">real values back</text>
        <rect class="np-card" x="175" y="458" width="145" height="72" rx="10" />
        <text class="np-tool-title" x="247" y="480">shell commands</text>
        <rect class="np-chip-keep" x="199" y="492" width="97" height="20" rx="10" />
        <text class="np-chip-text np-keep-text" x="247" y="506">placeholders stay</text>
      </svg>
    </div>
  </section>
</template>

<style scoped>
/* The two flows swap at the same width the feature grid goes 2-up. */
.np-flow-desktop {
  display: none;
}

.np-flow-mobile {
  display: block;
  width: 100%;
  max-width: 420px;
  height: auto;
  margin: 0 auto;
}

@media (min-width: 720px) {
  .np-flow-desktop {
    display: block;
    width: 100%;
    max-width: 880px;
    height: auto;
    margin: 0 auto;
  }

  .np-flow-mobile {
    display: none;
  }
}

/* Boxes and zones. */
.np-zone {
  fill: none;
  stroke: var(--vp-c-divider);
  stroke-width: 1.2;
  stroke-dasharray: 5 7;
}

.np-provider-zone {
  fill: none;
  stroke: var(--vp-c-divider);
  stroke-width: 1.2;
}

.np-card {
  fill: var(--vp-c-bg-alt);
  stroke: var(--vp-c-divider);
  stroke-width: 1;
}

.np-brand-box {
  fill: var(--vp-c-brand-soft);
}

/* Text. */
.np-zone-label {
  fill: var(--vp-c-text-3);
  font-size: 10px;
  font-weight: 600;
  letter-spacing: 1.2px;
}

.np-card-label {
  fill: var(--vp-c-text-3);
  font-size: 10px;
  font-weight: 600;
  letter-spacing: 1px;
}

.np-card-title {
  fill: var(--vp-c-text-1);
  font-size: 13px;
  font-weight: 600;
  text-anchor: middle;
}

.np-card-sub {
  fill: var(--vp-c-text-2);
  font-size: 11px;
  text-anchor: middle;
}

.np-tool-title {
  fill: var(--vp-c-text-1);
  font-size: 12px;
  font-weight: 600;
  text-anchor: middle;
}

.np-box-title {
  fill: var(--vp-c-brand-1);
  font-size: 14px;
  font-weight: 700;
  text-anchor: middle;
}

.np-box-sub {
  fill: var(--vp-c-text-2);
  font-size: 11.5px;
  text-anchor: middle;
}

.np-text {
  fill: var(--vp-c-text-1);
  font-size: 12px;
}

/* The real values in the prompt, and the note that they are real. */
.np-pii {
  fill: var(--vp-c-brand-1);
  font-weight: 600;
  text-decoration: underline;
  text-decoration-thickness: 1px;
  text-underline-offset: 2px;
}

/* Arrows and their labels. */
.np-arrow {
  stroke: var(--vp-c-text-2);
  stroke-width: 1.5;
  fill: none;
}

.np-arrowhead {
  fill: var(--vp-c-text-2);
}

.np-arrow-label {
  fill: var(--vp-c-text-2);
  font-size: 10.5px;
  text-anchor: middle;
}

.np-arrow-label-side {
  fill: var(--vp-c-text-2);
  font-size: 10.5px;
}

.np-key-label {
  fill: var(--vp-c-brand-1);
  font-size: 11.5px;
  font-weight: 600;
  text-anchor: middle;
}

.np-key-label-side {
  fill: var(--vp-c-brand-1);
  font-size: 10.5px;
  font-weight: 600;
}

/* Chips. */
.np-vault-chip {
  fill: var(--vp-c-bg);
  stroke: var(--vp-c-brand-2);
  stroke-width: 1;
}

.np-brand-text {
  fill: var(--vp-c-brand-1);
}

.np-token-chip {
  fill: var(--vp-c-brand-soft);
}

.np-token {
  fill: var(--vp-c-brand-1);
  font-family: var(--vp-font-family-mono);
  font-size: 9.5px;
  text-anchor: middle;
}

.np-chip-ok {
  fill: var(--vp-c-green-soft);
}

.np-ok-text {
  fill: var(--vp-c-green-1);
}

.np-chip-keep {
  fill: var(--vp-c-default-soft);
}

.np-keep-text {
  fill: var(--vp-c-text-2);
}

.np-chip-text {
  font-size: 9.5px;
  font-weight: 600;
  text-anchor: middle;
}
</style>
