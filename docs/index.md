---
layout: home
hero:
  name: nullpii
  text: Mask PII before it reaches an LLM
  tagline: Personal data and secrets become placeholders on your machine, and come back on the way out.
  image:
    src: /logo.png
    alt: nullpii
  actions:
    - theme: brand
      text: Get started
      link: /guide/
    - theme: alt
      text: How it is measured
      link: /method
    - theme: alt
      text: GitHub
      link: https://github.com/lBroth/nullpii
features:
  - title: Local detection
    details: A fine-tuned GLiNER model plus validated recognizers run on your CPU or GPU. Your text is sent nowhere; the vault lives in memory only.
  - title: Built for coding agents
    details: A gateway for the Anthropic and OpenAI APIs and a Claude Code mod mask prompts and tool output, and put real values back only into tools that run on your machine.
  - title: Measured on held-out data
    details: Scored on four public datasets and a synthetic trace set, chosen before any tool ran on them, against 14 open-source detectors run through their authors' pipelines (departures listed), with where it is not ahead.
---
