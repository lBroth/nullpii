// SPDX-License-Identifier: Apache-2.0
import { defineConfig } from 'vitepress';

export default defineConfig({
  title: 'nullpii',
  description:
    'A study comparing openai/privacy-filter (1.5B) and a fine-tuned GLiNER (278M) for local PII detection. npm library + HuggingFace model. Apache 2.0.',
  base: '/nullpii/',
  cleanUrls: true,
  head: [['link', { rel: 'icon', type: 'image/png', href: '/nullpii/favicon.png' }]],
  themeConfig: {
    logo: { src: '/logo-128.png', width: 24, height: 24 },
    siteTitle: 'nullpii',
    nav: [
      { text: 'Guide', link: '/guide/getting-started' },
      { text: 'Comparisons', link: '/guide/comparisons' },
      { text: 'API', link: '/api/' },
      { text: 'GitHub', link: 'https://github.com/lBroth/nullpii' },
    ],
    sidebar: {
      '/guide/': [
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
