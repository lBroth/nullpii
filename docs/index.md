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
    details: A fine-tuned GLiNER model plus validated recognizers, on your CPU or GPU. Your text goes nowhere; the vault lives in memory only.
  - title: Built for coding agents
    details: Masks prompts and tool output, keeps code and documentation links readable, and never puts a real value into a shell command. Through the Claude Code mod, or a gateway for the Anthropic and OpenAI APIs.
  - title: Measured, losses included
    details: On coding-agent traffic it lets 9.5% of what must be hidden through and keeps 85.4% of what must stay readable; only rizzo-pii lets fewer through, keeping 44.5%. On held-out document sets it is second of 15.
---
