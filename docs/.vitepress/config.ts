// SPDX-License-Identifier: Apache-2.0
import { defineConfig } from 'vitepress';

export default defineConfig({
  title: 'nullpii',
  description: 'Stop leaking PII to LLMs. Local detection, reversible vault, Apache 2.0.',
  base: '/nullpii/',
  cleanUrls: true,
  head: [['link', { rel: 'icon', type: 'image/png', href: '/nullpii/favicon.png' }]],
  themeConfig: {
    logo: { src: '/logo-128.png', width: 24, height: 24 },
    siteTitle: 'nullpii',
    nav: [
      { text: 'Claude Code', link: '/guide/middleware/claude-code' },
      { text: 'Guide', link: '/guide/getting-started' },
      { text: 'API', link: '/api/' },
      { text: 'GitHub', link: 'https://github.com/lBroth/nullpii' },
    ],
    sidebar: {
      '/guide/': [
        {
          text: 'Integrations',
          items: [
            { text: 'Claude Code', link: '/guide/middleware/claude-code' },
            { text: 'Anthropic SDK', link: '/guide/middleware/anthropic' },
          ],
        },
        {
          text: 'Guide',
          items: [
            { text: 'Getting Started', link: '/guide/getting-started' },
            { text: 'How it works', link: '/guide/how-it-works' },
            { text: 'Backends', link: '/guide/backends' },
            { text: 'Security model', link: '/guide/security' },
            { text: 'Comparisons', link: '/guide/comparisons' },
            { text: 'Eval results', link: '/guide/eval-results' },
            { text: 'Contributing', link: '/guide/contributing' },
          ],
        },
      ],
      '/api/': [
        {
          text: 'API Reference',
          items: [
            { text: 'NullPii', link: '/api/' },
            { text: 'Types', link: '/api/types' },
            { text: 'Errors', link: '/api/errors' },
          ],
        },
      ],
    },
    socialLinks: [{ icon: 'github', link: 'https://github.com/lBroth/nullpii' }],
    footer: {
      message: 'Released under the Apache 2.0 License.',
      copyright: 'Copyright © 2026 nullpii contributors',
    },
  },
});
