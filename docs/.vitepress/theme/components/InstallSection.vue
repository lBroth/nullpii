<!-- SPDX-License-Identifier: Apache-2.0 -->

<!-- The home page's install snippet: the README's first command, with the two notes a first run needs. -->
<script setup lang="ts">
import { withBase } from 'vitepress';

/** Links into the guide's two deployment pages. */
const CLAUDE_CODE_LINK = withBase('/guide/claude-code');
const GATEWAY_LINK = withBase('/guide/gateway');
</script>

<template>
  <section class="np-section" aria-labelledby="install-title">
    <div class="np-section-inner">
      <header class="np-section-head">
        <p class="np-kicker">Install</p>
        <h2 id="install-title" class="np-section-title">One npm install</h2>
      </header>

      <div class="np-install">
        <div class="np-install-card">
          <span class="np-install-prompt" aria-hidden="true">$</span>
          <code class="np-install-cmd">npm install nullpii onnxruntime-node</code>
        </div>
        <p class="np-install-note">
          You need Node 22 or later. On first use, nullpii downloads the model (1.2 GB) into
          <code>~/.cache/nullpii/</code>.
        </p>
        <p class="np-install-note">
          For Claude Code, use the
          <a :href="CLAUDE_CODE_LINK">mod</a> or run the
          <a :href="GATEWAY_LINK">gateway</a> in front of the API.
        </p>
      </div>
    </div>
  </section>
</template>
