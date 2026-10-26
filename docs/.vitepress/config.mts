// SPDX-License-Identifier: Apache-2.0
//
// The documentation site (GitHub Pages). Most pages only include a file
// the repository already keeps up to date (README, the package READMEs,
// METHOD, SECURITY, CHANGELOG), so the site never holds a second copy.
// For those pages, "Edit this page" and "Last updated" refer to the
// included file, not to the wrapper under docs/.

import { execFileSync } from 'node:child_process';
import { readFileSync } from 'node:fs';
import { dirname, join, relative, resolve, sep } from 'node:path';
import { fileURLToPath } from 'node:url';
import { defineConfig } from 'vitepress';

const REPO = 'https://github.com/lBroth/nullpii';

/** The READMEs load their figures from GitHub's `main`, which only has them
 * once a release is merged. The site bundles the repository's own copy
 * instead, so its pages never wait on `main`. */
const RAW_MAIN = 'https://raw.githubusercontent.com/lBroth/nullpii/main/';
const REPO_ROOT = resolve(dirname(fileURLToPath(import.meta.url)), '..', '..');

/** `src` as a path from the page file `pagePath` to the repository's own
 * copy, when `src` is a `main` URL; else `src` unchanged. */
function localFigure(src: string, pagePath: string): string {
  if (!src.startsWith(RAW_MAIN)) return src;
  const rel = relative(dirname(pagePath), join(REPO_ROOT, src.slice(RAW_MAIN.length)));
  const posix = rel.split(sep).join('/');
  return posix.startsWith('.') ? posix : `./${posix}`;
}

/** A wrapper page: one `<!--@include: path-->`, optionally inside
 * `::: v-pre` … `:::`, and nothing else. Group 1 is the included path. */
const INCLUDE_ONLY_PAGE = /^\s*(?:::: v-pre\s+)?<!--\s*@include:\s*([^\s{#]+)\s*-->\s*(?::::\s*)?$/;

/** The repository file a page renders. */
interface PageSource {
  /** Relative to the repository root, with `/` separators. */
  readonly path: string;
  /** Whether the page is a wrapper that includes `path`. */
  readonly included: boolean;
}

/** The included file for a wrapper page, else the page's own source. The
 * docs directory (`srcDir`) sits at the repository root. */
function sourceOf(srcDir: string, filePath: string): PageSource {
  const page = join(srcDir, filePath);
  const include = INCLUDE_ONLY_PAGE.exec(readFileSync(page, 'utf8'));
  const source = include === null ? page : resolve(dirname(page), include[1]);
  return {
    path: relative(resolve(srcDir, '..'), source).split(sep).join('/'),
    included: include !== null,
  };
}

/** When `file` (relative to `repoRoot`) was last committed, in ms since
 * the epoch; `undefined` if it has no commit yet. */
function lastCommitMs(repoRoot: string, file: string): number | undefined {
  const seconds = execFileSync('git', ['log', '-1', '--format=%ct', '--', file], {
    cwd: repoRoot,
    encoding: 'utf8',
  }).trim();
  return seconds === '' ? undefined : Number(seconds) * 1000;
}

export default defineConfig({
  title: 'nullpii',
  description:
    'Mask personal data and secrets before they reach an LLM, and put them back on the way out. Local detection, reversible in-memory vault.',
  base: '/nullpii/',
  cleanUrls: true,
  lastUpdated: true,
  head: [
    ['link', { rel: 'icon', type: 'image/png', href: '/nullpii/logo.png' }],
    // The browser chrome follows the site's two background colors.
    ['meta', { name: 'theme-color', media: '(prefers-color-scheme: light)', content: '#ffffff' }],
    ['meta', { name: 'theme-color', media: '(prefers-color-scheme: dark)', content: '#1b1b1f' }],
  ],
  markdown: {
    config(md) {
      const image = md.renderer.rules.image;
      if (image === undefined) throw new Error('markdown-it has no image rule');
      md.renderer.rules.image = (tokens, idx, options, env, self) => {
        const src = tokens[idx].attrGet('src');
        if (src !== null) tokens[idx].attrSet('src', localFigure(src, env.path));
        return image(tokens, idx, options, env, self);
      };
    },
  },
  transformPageData(pageData, { siteConfig }) {
    if (pageData.filePath === '') return; // a virtual page, such as the 404
    const source = sourceOf(siteConfig.srcDir, pageData.filePath);
    pageData.frontmatter.sourcePath = source.path;
    if (!source.included || pageData.lastUpdated === undefined) return;
    const committed = lastCommitMs(resolve(siteConfig.srcDir, '..'), source.path);
    if (committed !== undefined) pageData.lastUpdated = committed;
  },
  themeConfig: {
    logo: '/logo.png',
    // One menu: every page is in the top bar (the phone menu on small
    // screens), so the docs pages carry no second, sidebar menu.
    nav: [
      {
        text: 'Guide',
        items: [
          { text: 'Get started', link: '/start' },
          { text: 'Overview and library', link: '/guide/' },
          { text: 'Gateway', link: '/guide/gateway' },
          { text: 'Claude Code mod', link: '/guide/claude-code' },
        ],
      },
      { text: 'Benchmark', link: '/method' },
      {
        text: 'About',
        items: [
          { text: 'Security', link: '/security' },
          { text: 'Weights provenance', link: '/WEIGHTS_PROVENANCE' },
          { text: 'Changelog', link: '/changelog' },
        ],
      },
    ],
    socialLinks: [{ icon: 'github', link: REPO }],
    editLink: {
      // VitePress serializes this function to the browser, so it can use
      // nothing but its argument: no constant from this file.
      // `sourcePath` comes from transformPageData above.
      pattern: ({ frontmatter, filePath }) =>
        `https://github.com/lBroth/nullpii/edit/main/${frontmatter.sourcePath ?? `docs/${filePath}`}`,
    },
    search: { provider: 'local' },
    footer: {
      message: 'Released under the Apache-2.0 License.',
      copyright: 'Copyright © 2026 nullpii contributors',
    },
  },
});
