# docs: the website's source

This folder builds the website, [lbroth.github.io/nullpii](https://lbroth.github.io/nullpii/), with [VitePress](https://vitepress.dev/): `npm run docs:build`, deployed by [`.github/workflows/docs.yml`](../.github/workflows/docs.yml) on every push to `main`.

Most pages here hold one line, `<!--@include: …-->`, that pulls in a file the repository already keeps, so the site never carries a second copy. GitHub does not run that include, so those pages look empty here. Read the file they include:

| Site page | File in this folder | Shows |
|---|---|---|
| Home | [`index.md`](index.md) | the hero and layout only; its sections are in [`.vitepress/theme/components/`](.vitepress/theme/components/) |
| Get started | [`start.md`](start.md) | written for the site |
| Guide: overview and library | [`guide/index.md`](guide/index.md) | [`README.md`](../README.md) |
| Guide: gateway | [`guide/gateway.md`](guide/gateway.md) | [`packages/gateway/README.md`](../packages/gateway/README.md) |
| Guide: Claude Code mod | [`guide/claude-code.md`](guide/claude-code.md) | [`packages/claude-code-mod/README.md`](../packages/claude-code-mod/README.md) |
| Benchmark | [`method.md`](method.md) | [`packages/eval/METHOD.md`](../packages/eval/METHOD.md) |
| Security | [`security.md`](security.md) | [`SECURITY.md`](../SECURITY.md) |
| Weights provenance | [`WEIGHTS_PROVENANCE.md`](WEIGHTS_PROVENANCE.md) | written here; the README and the model card link to it |
| Changelog | [`changelog.md`](changelog.md) | [`CHANGELOG.md`](../CHANGELOG.md) |

The site's configuration, menu and theme are in [`.vitepress/`](.vitepress/). This file is left out of the site.
