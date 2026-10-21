// SPDX-License-Identifier: Apache-2.0
//
// The documentation site (GitHub Pages). Every page includes a file the
// repository already keeps up to date (README, the package READMEs,
// METHOD, SECURITY, CHANGELOG), so the site never holds a second copy.

import { defineConfig } from 'vitepress';

const REPO = 'https://github.com/lBroth/nullpii';

export default defineConfig({
  title: 'nullpii',
  description:
    'Mask personal data and secrets before they reach an LLM, and put them back on the way out. Local detection, reversible in-memory vault.',
  base: '/nullpii/',
  cleanUrls: true,
  lastUpdated: true,
  head: [['link', { rel: 'icon', type: 'image/png', href: '/nullpii/logo.png' }]],
  themeConfig: {
    logo: '/logo.png',
    nav: [
      { text: 'Guide', link: '/guide/' },
      { text: 'Benchmark', link: '/method' },
      { text: 'Changelog', link: '/changelog' },
    ],
    sidebar: [
      {
        text: 'Use it',
        items: [
          { text: 'Overview and library', link: '/guide/' },
          { text: 'Gateway', link: '/guide/gateway' },
          { text: 'Claude Code mod', link: '/guide/claude-code' },
        ],
      },
      {
        text: 'Trust it',
        items: [
          { text: 'How it is measured', link: '/method' },
          { text: 'Security', link: '/security' },
          { text: 'Weights provenance', link: '/WEIGHTS_PROVENANCE' },
          { text: 'Changelog', link: '/changelog' },
        ],
      },
    ],
    socialLinks: [{ icon: 'github', link: REPO }],
    editLink: { pattern: `${REPO}/edit/main/docs/:path` },
    search: { provider: 'local' },
    footer: {
      message: 'Released under the Apache-2.0 License.',
      copyright: 'Copyright © 2026 nullpii contributors',
    },
  },
});
