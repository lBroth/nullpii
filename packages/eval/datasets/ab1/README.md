# AB-1 component A — agent traffic

Canary: `AB1-CANARY-6f3a1c9e-nullpii-agentbench-2026-10-23`. This is benchmark data: please keep it out of training sets.

Component A of AB-1, nullpii's pre-registered benchmark for coding-agent traffic: 1,200 documents a coding agent sees (prompts, file reads, shell output, logs, tool-call arguments, tickets; dev 200, test 1,000), with fictional values injected and every item annotated MUST_MASK, MUST_KEEP or AMBIGUOUS. It was built from [`SPEC.md`](SPEC.md) alone by an agent working outside every nullpii repository. How it was audited, frozen and scored, and the results, are in [`METHOD.md`](https://github.com/lBroth/nullpii/blob/main/packages/eval/METHOD.md#agent-traffic-benchmark-ab-1); the scorer is [`scripts/ab1/agent_metrics.py`](https://github.com/lBroth/nullpii/blob/main/packages/eval/scripts/ab1/agent_metrics.py).

**Every value is fictional.** The keys have real providers' formats (each drawn from a [gitleaks](https://github.com/gitleaks/gitleaks) rule) so that a detector has something real-shaped to find, and secret scanners flag them; none is a working credential. The data file is gzip-compressed so that scanners do not report several hundred fake keys on every push; read it with `gzip`.

## Files

| Path | Content |
|---|---|
| `data/ab1-public.jsonl.gz` | The gold, in its publishable form. Uncompressed it is `ab1-public.jsonl`, sha256 `69f8ee893ac125338bec89c1a99d0281c02f640227da03d3c3c7a6d131aef9b7`. All 1,200 rows; the 72 documents whose carrier is a GitHub issue carry `segments` instead of `text`, because GitHub issue text is not redistributed (see Rebuilding). |
| `data/ab1-public.meta.json` | sha256 of the full gold and of the public file, and their character counts. |
| `data/leak_dropped_test.txt` | The 34 test documents the leak check dropped (METHOD.md, "Leak check"). |
| `data/stats.json`, `data/CANARY` | Counts per split, kind, language, origin, class and category; the canary string. |
| `gen/`, `lists/`, `checks/` | The generator, its value lists (`lists/SOURCES.md` gives the source, licence and date of each) and the validator. |
| `SPEC.md` | The specification, as pre-registered on 2026-10-23. |
| `BUILD.md` | The builder's README, unchanged since the freeze: layout, schema, seeds, carriers and their licences, every generation rule, and the validator's output. Its layout table names `data/ab1.jsonl`, the full gold, which is not shipped here; rebuild it as below. |
| `FREEZE.sha256` | sha256 of every file at the freeze (25 October 2026). `BUILD.md` is listed there as `README.md` and the data file uncompressed; `data/ab1.jsonl` and `cache/` (downloads and intermediate files) are not shipped. |

## Reading it

```python
import gzip, json

rows = [json.loads(line) for line in gzip.open("data/ab1-public.jsonl.gz", "rt", encoding="utf-8")]
```

The schema is in `BUILD.md`. Offsets are Python code-point offsets into `text`, end exclusive.

## Rebuilding the full gold and the scored set

```bash
gunzip -k data/ab1-public.jsonl.gz
python3.12 -m venv .venv && .venv/bin/pip install -r gen/requirements.txt
GITHUB_TOKEN=... .venv/bin/python gen/real/rebuild_public.py --out ab1.jsonl --in data/ab1-public.jsonl
```

`rebuild_public.py` fetches the 72 issues back from GitHub and checks every document against its sha256; an issue edited or deleted after 2026-10-24 rebuilds differently and is reported (`BUILD.md`, "Publishing"). An exact rebuild has the sha256 `54ee48c3248b13c1845e510d531402f0c06873e0509503fb9bceaafb156d7a44`.

The scored set is the test split of `ab1.jsonl` without the 34 dropped documents, rows kept in file order (966 documents, sha256 `baa5305f7999d1ef04c63831ef51408522b3d2ca6de2818d9947f76c03be7a26`):

```python
import json

drop = set(open("data/leak_dropped_test.txt").read().split())
lines = [line for line in open("ab1.jsonl", encoding="utf-8").read().split("\n") if line.strip()]
test = [line for line in lines if (row := json.loads(line))["split"] == "test" and row["id"] not in drop]
open("ab1-test.jsonl", "w", encoding="utf-8").write("\n".join(test) + "\n")
```

## Licences

The generator, the lists the builder wrote and the gold are Apache-2.0, like the rest of this repository. `lists/gitleaks/` is gitleaks' rule file, MIT (`lists/gitleaks/LICENSE`). Name and street lists come from Wikidata (CC0 1.0); postal codes from GeoNames (CC BY 4.0, © GeoNames, https://www.geonames.org/). Carrier text keeps its dataset's licence: [nebius/SWE-rebench-openhands-trajectories](https://huggingface.co/datasets/nebius/SWE-rebench-openhands-trajectories) (CC BY 4.0), [OpenHands/openhands-feedback](https://huggingface.co/datasets/OpenHands/openhands-feedback) (MIT), [allenai/WildChat-1M](https://huggingface.co/datasets/allenai/WildChat-1M) (ODC-BY 1.0; please cite *WildChat: 1M ChatGPT Interaction Logs in the Wild*, Zhao et al., ICLR 2024). GitHub issue text is not included; each such document records its issue's URL and its repository's licence at fetch time.
