"""NVIDIA's reference GLiNER PII server, vendored verbatim for the
competitor adapter.

Source: https://github.com/NVIDIA/NeMo-Guardrails at commit
af242f0b47572b5fc8cf3817c0da326f26a99de8,
`examples/deployment/gliner_server/src/gliner_server/pii_utils.py`
(sha256 5dad89a0bedfd292...): `remove_subset_entities`,
`deduplicate_entities_by_score`, `adjust_entity_positions` and
`create_text_chunks`. The server (`server.py`, sha256 55ff9a8cdf2064fe...)
serves `nvidia/gliner-PII`; NeMo Guardrails' GLiNER rail sends it the
text with its defaults (`threshold` 0.5, `chunk_length` 384, `overlap`
128, `flat_ner` False) and masks the returned positions.

`extract_with_gliner` in `server.py` cuts the text with
`create_text_chunks`, runs `model.inference(texts=chunks, labels=...,
threshold=..., flat_ner=..., relations=[])`, shifts each chunk's entities
by its offset, then `process_raw_entities` applies
`remove_subset_entities` and `deduplicate_entities_by_score`. The adapter
in `adapters.py` reproduces that call order. The functions below are
unchanged; only this docstring and the import are added (the module's
other functions build the HTTP response and are not needed).
"""
# SPDX-FileCopyrightText: Copyright (c) 2025-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

from typing import Any

def remove_subset_entities(entities: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """
    Remove entities that are subsets of other entities (based on position).

    An entity is considered a subset if another entity fully contains its span.

    Args:
        entities: List of entity dictionaries with 'start' and 'end' keys

    Returns:
        List of entities with subset entities removed
    """
    if not entities:
        return []

    # Create a copy to avoid modifying the original
    entities = list(entities)
    entities_to_delete = []

    for idx, ent in enumerate(entities):
        has_superset = any(
            i != idx and i not in entities_to_delete and e["start"] <= ent["start"] and e["end"] >= ent["end"]
            for i, e in enumerate(entities)
        )
        if has_superset:
            entities_to_delete.append(idx)

    for idx in sorted(entities_to_delete, reverse=True):
        del entities[idx]

    return entities


def deduplicate_entities_by_score(entities: list[dict[str, Any]]) -> dict[tuple, dict[str, Any]]:
    """
    Deduplicate entities by keeping the highest scoring one for each (label, text) pair.

    Args:
        entities: List of entity dictionaries with 'label', 'text', 'start', 'end', 'score' keys

    Returns:
        Dictionary mapping (label, normalized_text) to entity span dictionaries
    """
    dedup_map = {}

    for ent in entities:
        label = ent.get("label")
        if not label:
            continue

        text_val = ent.get("text", "")
        score_val = float(ent.get("score", 0.0))
        key = (label, text_val.strip().lower())

        if key not in dedup_map or score_val > dedup_map[key]["score"]:
            dedup_map[key] = {
                "value": text_val,
                "suggested_label": label,
                "start_position": int(ent.get("start", 0)),
                "end_position": int(ent.get("end", 0)),
                "score": round(score_val, 3),
            }

    return dedup_map


def adjust_entity_positions(entities: list[dict[str, Any]], offset: int) -> list[dict[str, Any]]:
    """
    Adjust entity start/end positions by a given offset.

    Args:
        entities: List of entity dictionaries with 'start' and 'end' keys
        offset: The offset to add to start and end positions

    Returns:
        List of entities with adjusted positions
    """
    for entity in entities:
        entity["start"] += offset
        entity["end"] += offset
    return entities



def create_text_chunks(text: str, chunk_length: int = 384, overlap: int = 128) -> tuple:
    """
    Split text into overlapping chunks for processing.

    Args:
        text: The text to split into chunks
        chunk_length: Maximum length of each chunk
        overlap: Number of characters to overlap between consecutive chunks

    Returns:
        Tuple of (chunks, offsets) where:
        - chunks: List of text chunks
        - offsets: List of starting positions for each chunk in the original text
    """
    chunks = []
    offsets = []
    start = 0
    while start < len(text):
        chunks.append(text[start : start + chunk_length])
        offsets.append(start)
        start += chunk_length - overlap
    return chunks, offsets
