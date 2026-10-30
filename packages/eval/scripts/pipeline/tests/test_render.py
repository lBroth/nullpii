# SPDX-License-Identifier: Apache-2.0
"""`render` writes published-bench and every marked region from the
outputs, and `check` proves the docs say what the outputs hold; a claim
the data stops supporting is reworded by the data or refused, never
left as written."""
import functools
import hashlib
import json

import pytest

import bench_pipeline
from pipeline import blocks_ab1, blocks_r3, compare, docs, render, views
from pipeline.prose import RenderError
from pipeline.tests import outputs
from pipeline.tests import render_outputs as ro
from pipeline.tests.outputs import DEFAULT, EVERYTHING

A, B1, B2, R3, R3_EN = ro.A, ro.B1, ro.B2, ro.R3, ro.R3_EN


def _bench(tmp_path, edit=None, name="run"):
    return views.load(ro.write_run(tmp_path / name, edit))


def _digest(root):
    return {p.relative_to(root): hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(root.rglob("*")) if p.is_file()}


# The acceptance test ------------------------------------------------------------

def test_the_tracked_docs_and_figures_say_what_published_bench_holds():
    # What CI runs: no frozen input, only the tracked published-bench.
    assert render.check(render.PUBLISHED_BENCH) == []


def test_published_bench_holds_the_published_runs_names_and_lists_its_files():
    marker = json.loads((render.PUBLISHED_BENCH / views.OUTPUTS_MARKER).read_text())
    assert marker["names"] == views.PUBLISHED_NAMES
    assert all((render.PUBLISHED_BENCH / rel).is_file() for rel in marker["files"])
    # The core regime's own reports are not published.
    assert not any(rel in marker["files"] for rel in compare.published_dropped_files())


# render and check ----------------------------------------------------------------

def test_a_render_then_checks_clean_and_copies_every_output_byte_for_byte(tmp_path):
    run, root, published = ro.write_run(tmp_path / "run"), ro.docs_root(tmp_path), tmp_path / "pb"
    render.render(run, published, root)
    assert render.check(run, published, root) == []
    assert render.check(published, published, root) == []
    for rel in compare.expected_files():
        assert (published / rel).read_bytes() == (run / rel).read_bytes()
    assert json.loads((published / views.OUTPUTS_MARKER).read_text())["names"] == views.RUN_NAMES
    assert sorted(p.name for p in (root / docs.FIGURES).iterdir()) == sorted(render.figures(views.load(run)))


def test_check_writes_nothing_and_lists_each_region_that_differs(tmp_path):
    run, root, published = ro.write_run(tmp_path / "run"), ro.docs_root(tmp_path), tmp_path / "pb"
    render.render(run, published, root)
    moved = ro.write_run(tmp_path / "moved", lambda f: f[A][DEFAULT].update(leak_rate=0.07))
    before = _digest(tmp_path)
    diffs = [str(d) for d in render.check(moved, published, root)]
    assert _digest(tmp_path) == before
    assert "published-bench/ab1/scores-ab1-a.json: differs" in diffs
    assert "README.md <!-- summary -->: differs" in diffs
    assert "README.md <!-- ab1-a -->: differs" in diffs
    assert "MODEL_CARD.md <!-- card-limits -->: differs" in diffs
    assert f"{docs.FIGURES}/ab1-agent-traffic.svg: differs" in diffs
    # R3 did not move.
    assert not any("matrix" in d or "r3-documents" in d for d in diffs)


def test_a_region_edited_by_hand_is_listed_and_rendered_back(tmp_path):
    run, root, published = ro.write_run(tmp_path / "run"), ro.docs_root(tmp_path), tmp_path / "pb"
    render.render(run, published, root)
    method = root / docs.METHOD
    method.write_text(method.read_text().replace("No dataset has a tool", "No dataset has any tool"))
    assert [str(d) for d in render.check(run, published, root)] == ["packages/eval/METHOD.md <!-- r3-comparisons -->: differs"]
    render.render(run, published, root)
    assert render.check(run, published, root) == []


def test_an_edit_outside_the_regions_is_not_the_renderers(tmp_path):
    run, root, published = ro.write_run(tmp_path / "run"), ro.docs_root(tmp_path), tmp_path / "pb"
    render.render(run, published, root)
    readme = root / docs.README
    readme.write_text(readme.read_text().replace("## Install", "## Installing"))
    assert render.check(run, published, root) == []


def test_the_cli_check_exits_5_listing_what_differs_and_0_when_clean(tmp_path, monkeypatch, capsys):
    run, root, published = ro.write_run(tmp_path / "run"), ro.docs_root(tmp_path), tmp_path / "pb"
    render.render(run, published, root)
    monkeypatch.setattr(render, "check", functools.partial(render.check, published=published, root=root))
    assert bench_pipeline.main(["render", "--run", str(run), "--check"]) == 0
    moved = ro.write_run(tmp_path / "moved", lambda f: f[R3]["_macro"][DEFAULT].update(f2=0.79))
    assert bench_pipeline.main(["render", "--run", str(moved), "--check"]) == bench_pipeline.EXIT_RENDER_DIFFERS
    assert "README.md <!-- matrix -->: differs" in capsys.readouterr().out


def test_a_previous_renders_file_that_is_no_output_now_is_removed_and_nothing_else(tmp_path):
    run, root, published = ro.write_run(tmp_path / "run"), ro.docs_root(tmp_path), tmp_path / "pb"
    render.render(run, published, root)
    (published / "r3" / "operating-points.json").write_text("{}")
    without = ro.write_reference(tmp_path / "ref")  # no PIIMB report of the default
    assert "published-bench/piimb/piimb-default.json: no longer an output" in [
        str(d) for d in render.check(without, published, root)]
    render.render(without, published, root)
    assert not (published / "piimb" / "piimb-default.json").exists()
    assert (published / "r3" / "operating-points.json").read_text() == "{}"
    assert json.loads((published / views.OUTPUTS_MARKER).read_text())["names"] == views.PUBLISHED_NAMES


def test_a_run_inside_published_bench_is_refused(tmp_path):
    published = tmp_path / "pb"
    inside = ro.write_run(published / "nested")
    with pytest.raises(RenderError, match="inside"):
        render.render(inside, published, ro.docs_root(tmp_path))


# Markers ---------------------------------------------------------------------------

BODIES = {"a": "A"}


@pytest.mark.parametrize("text, match", [
    ("<!-- a:begin -->\nx\n<!-- a:end -->\n<!-- b:begin -->\ny\n<!-- b:end -->\n", "without a renderer: \\['b'\\]"),
    ("nothing marked\n", "renderers without a region: \\['a'\\]"),
    ("<!-- a:begin -->\nx\n<!-- a:end -->\n<!-- a:begin -->\nx\n<!-- a:end -->\n", "marked twice"),
    ("<!-- a:begin -->\nx\n", "never closes"),
    ("<!-- a:begin -->\n<!-- b:begin -->\n<!-- b:end -->\n<!-- a:end -->\n", "opens inside"),
    ("<!-- a:end -->\n", "closes, but None is open"),
    ("text <!-- a:begin -->\nx\n<!-- a:end -->\n", "not on a line of its own"),
])
def test_markers_that_are_not_one_well_formed_region_per_block_are_refused(tmp_path, text, match):
    with pytest.raises(render.DocError, match=match):
        render.fill(text, tmp_path / "doc.md", BODIES)


def test_a_region_is_replaced_whole_and_nothing_around_it(tmp_path):
    text = "before\n<!-- a:begin -->\nold\nlines\n<!-- a:end -->\nafter\n"
    assert render.fill(text, tmp_path / "d.md", BODIES) == "before\n<!-- a:begin -->\nA\n<!-- a:end -->\nafter\n"


def test_a_hand_kept_region_is_left_as_it_is(tmp_path):
    text = "<!-- latency:begin -->\nby hand\n<!-- latency:end -->\n<!-- a:begin -->\nx\n<!-- a:end -->\n"
    assert "by hand" in render.fill(text, tmp_path / "d.md", BODIES)


def test_every_tracked_doc_has_exactly_its_renderers_regions():
    for rel, blocks in docs.BLOCKS.items():
        names = render.regions((views.ROOT / rel).read_text(), views.ROOT / rel)
        assert set(names) - docs.KEPT == set(blocks), rel


# Claims: worded from the data, or refused --------------------------------------------

def _a(tmp_path, edit=None):
    return blocks_ab1.readme_bullets(_bench(tmp_path, edit))


def test_the_tool_that_lets_fewer_through_is_named_from_the_data(tmp_path):
    text = _a(tmp_path)
    assert text.startswith("- **Only rizzo-pii lets fewer through** (8.1%; the gap is within the margin of error),"
                           " and it masks more than half of what the agent needs to read.")


def test_when_no_tool_lets_fewer_through_the_claim_says_so(tmp_path):
    text = _a(tmp_path, lambda f: f[A][DEFAULT].update(leak_rate=0.05))
    assert text.startswith("- **No other tool lets fewer through.** Every other tool lets 3 to 36 points more through.")


def test_two_tools_that_let_fewer_through_are_counted_and_named(tmp_path):
    def worse(f):
        f[A][DEFAULT].update(leak_rate=0.5)
        f[A][ro.PRESIDIO]["ci"].update(baseline_minus_tool_leak=[0.05, 0.12])
    text = _a(tmp_path, worse)
    assert text.startswith("- **Two other tools let fewer through:** rizzo-pii (8.1%; the gap is within the margin of"
                           " error) and Presidio (40.6%; the gap is significant).")


def test_a_gap_that_becomes_significant_is_worded_so(tmp_path):
    text = _a(tmp_path, lambda f: f[A][ro.RIZZO]["ci"].update(baseline_minus_tool_leak=[0.004, 0.026]))
    assert "(8.1%; the gap is significant)" in text


def test_a_tie_with_nullpii_is_refused(tmp_path):
    with pytest.raises(RenderError, match="refused: a leak_rate tied"):
        _a(tmp_path, lambda f: f[A][ro.RIZZO].update(leak_rate=0.0945))


def test_a_lead_the_interval_contradicts_is_refused(tmp_path):
    with pytest.raises(RenderError, match="refused: a tool that lets fewer through"):
        _a(tmp_path, lambda f: f[A][ro.RIZZO]["ci"].update(baseline_minus_tool_leak=[-0.03, -0.01]))


def test_a_tool_that_keeps_more_readable_is_named(tmp_path):
    def keeps(f):
        f[A][ro.PRESIDIO].update(keep_rate=0.9)
        f[A][ro.PRESIDIO]["ci"].update(baseline_minus_tool_keep=[-0.06, 0.01])
    text = _a(tmp_path, keeps)
    assert "Only Presidio keeps as much readable (90.0%, too close to call), and it lets 40.6% through." in text


def test_a_keep_rate_the_interval_contradicts_is_refused(tmp_path):
    with pytest.raises(RenderError, match="refused: a tool that keeps as much readable"):
        _a(tmp_path, lambda f: f[A][ro.PRESIDIO].update(keep_rate=0.9))


def test_the_weakest_categories_and_their_counts_follow_the_data(tmp_path):
    assert "- **Weakest categories:** person names (24% let through) and URLs (30%). On names, 1 of the 2 other tools" \
           " lets fewer through; on URLs, 1 does." in _a(tmp_path)

    def emails_leak(f):
        f[A][DEFAULT]["leak_by_category"]["email"] = [0.6, 536]
    # The two highest leak rates, the category with more items first.
    assert "- **Weakest categories:** emails (60% let through) and URLs (30%)." in _a(tmp_path, emails_leak)


def test_on_secrets_nullpii_leads_only_when_no_tool_lets_fewer_through(tmp_path):
    assert "**On secrets alone, nullpii does not lead.**" in _a(tmp_path)

    def leads(f):
        for rel in (B1, B2):
            f[rel][DEFAULT].update(leak_rate=0.05)
    text = _a(tmp_path, leads)
    assert "**On secrets alone, no other tool lets fewer through.**" in text
    assert "On CredData it lets 5.0% through, and no other tool lets fewer through." in text


SPLIT = compare.ab1_file(compare.KIND_SPLIT, "ab1-b1")


def _split(edit):
    def apply(f):
        edit(f[SPLIT]["tools"])
    return apply


def test_the_uuid_split_is_rendered_from_any_run(tmp_path):
    text = _a(tmp_path)
    assert ("More than half of nullpii's leaks there (268 of 490) are UUIDs: CredData counts 294 UUIDs as credentials,"
            in text)
    assert "Without them nullpii lets 13.0% through, the fewest of all tools (an analysis made" in text
    published = views.load(ro.write_reference(tmp_path / "ref"))
    assert "(268 of 490)" in blocks_ab1.readme_bullets(published)


def test_the_uuid_share_and_the_place_without_uuids_follow_the_data(tmp_path):
    def fewer_uuids(tools):
        tools[DEFAULT].update(outputs.split_row(100, 222))
    text = _a(tmp_path, _split(fewer_uuids))
    assert "100 of nullpii's 322 leaks there are UUIDs: CredData counts 294" in text
    assert "More than half" not in text
    aside = blocks_ab1.card_weak_bullet(_bench(tmp_path, _split(fewer_uuids), "aside"))
    assert ", 100 of its 322 leaks UUIDs that CredData counts as credentials" in aside

    def rizzo_fewer(tools):
        tools[ro.RIZZO].update(outputs.split_row(280, 100))
    text = _a(tmp_path, _split(rizzo_fewer))
    assert "Without them nullpii lets 13.0% through, and 1 of the 2 other tools lets fewer through (an analysis" in text
    method = blocks_ab1.uuid_method(_bench(tmp_path, _split(rizzo_fewer), "method"))
    assert "and 1 of the 2 other tools lets fewer through (rizzo-pii 5.9%, Presidio 76.2%)." in method


def test_a_tie_without_uuids_is_refused(tmp_path):
    with pytest.raises(RenderError, match="refused: a leak rate without UUIDs tied"):
        _a(tmp_path, _split(lambda tools: tools[ro.RIZZO].update(outputs.split_row(280, 222))))


def test_a_split_by_another_kind_has_no_wording_and_is_refused(tmp_path):
    with pytest.raises(RenderError, match="the prose is about UUID"):
        _a(tmp_path, lambda f: f[SPLIT].update(kind="Password"))


def _r3(tmp_path, block, edit=None):
    return block(_bench(tmp_path, edit))


def test_nullpiis_place_on_r3_is_counted_from_the_data(tmp_path):
    assert _r3(tmp_path, blocks_r3.readme_bullets).startswith(
        "- **Second of 2** by macro char-F2 in its agent default (0.758;")

    def first(f):
        f[R3]["_macro"][DEFAULT].update(f2=0.8)
    text = _r3(tmp_path, blocks_r3.readme_bullets, first)
    assert text.startswith("- **First of 2** by macro char-F2 in its agent default (0.800;")
    assert "No other tool scores higher." in text


def test_the_recall_heading_follows_the_ranks(tmp_path):
    assert "- **It favours recall.**" in _r3(tmp_path, blocks_r3.recall_bullet)

    def precise(f):
        for dataset, rows in f[R3].items():
            if dataset != "_macro":
                rows[DEFAULT].update(recall=0.5, precision=0.9)
    assert "- **It favours precision.**" in _r3(tmp_path, blocks_r3.recall_bullet, precise)


S2_NONE = "No dataset has a tool with significantly higher recall at matched or better precision."


def _breach(recall_ci, precision_ci, dataset="r3-piilo"):
    def edit(f):
        f[R3][dataset]["rizzo-pii"].update(baseline_minus_tool_recall_ci=recall_ci,
                                           baseline_minus_tool_precision_ci=precision_ci)
    return edit


def test_the_s2_sentence_holds_only_while_no_tool_breaches_it(tmp_path):
    assert S2_NONE in _r3(tmp_path, blocks_r3.comparisons)
    text = _r3(tmp_path, blocks_r3.comparisons, _breach([-0.05, -0.01], [-0.02, 0.01]))
    assert S2_NONE not in text
    assert "A tool has significantly higher recall at a precision not significantly lower (S2): on PIILO, rizzo-pii." in text


@pytest.mark.parametrize("recall_ci, precision_ci, breach", [
    ([-0.05, -0.01], [0.0, 0.02], True),     # precision interval touching 0: matched
    ([-0.05, -0.01], [0.001, 0.02], False),  # nullpii's precision significantly higher
    ([-0.05, 0.0], [-0.02, 0.01], False),    # recall interval touching 0: not significant
])
def test_s2_reads_the_verdicts_rule_at_its_boundaries(tmp_path, recall_ci, precision_ci, breach):
    text = _r3(tmp_path, blocks_r3.s2_sentence, _breach(recall_ci, precision_ci))
    assert (S2_NONE not in text) is breach


def test_the_published_outputs_render_no_interval_against_the_core_regime(tmp_path):
    b = views.load(ro.write_reference(tmp_path / "ref"))
    assert blocks_r3.s2_sentence(b) == ""
    assert blocks_r3.NO_INTERVALS in blocks_r3.comparisons(b)
    assert "[" not in blocks_r3.matrix(b).split("\n", 2)[2]
    assert all(r.nullpii == EVERYTHING for r in b.r3_nullpii(views.R3_MAIN))


def test_a_runs_intervals_are_against_its_default(tmp_path):
    b = _bench(tmp_path)
    assert "| rizzo-pii (default) | **0.770** | **0.630** | 0.920 | **0.580** | [−0.020, −0.003] |" in blocks_r3.matrix(b)
    assert blocks_r3.matrix_note(b).endswith("The intervals are of nullpii 0.5 (agent default) minus each tool.")
    assert "significantly behind 1, rizzo-pii at its default," in blocks_r3.comparisons(b)


def test_a_lead_that_becomes_too_close_to_call_is_reworded(tmp_path):
    def close(f):
        f[R3]["_macro"]["rizzo-pii@default"]["baseline_minus_tool_f2_ci"] = [-0.02, 0.003]
    assert "too close to call with 1, rizzo-pii at its default," in _r3(tmp_path, blocks_r3.comparisons, close)


def test_bold_marks_the_best_printed_value_of_each_column(tmp_path):
    table = _r3(tmp_path, blocks_r3.method_table(views.R3_MAIN))
    assert "| rizzo-pii (default) | **0.810** | **0.810** | **0.810** | **0.810** | **0.810** | **0.770** | 0.750–0.800 |" in table
    # A cell with no value is never the best one.
    assert "| mask everything | — | — | — | — | — | 0.260 | 0.200–0.300 |" in table
    assert "| **nullpii 0.5 (agent default)** | 0.758 |" in table


@pytest.mark.parametrize("rank, words", [(1, "above the 35 listed tools"), (3, "third of 36 on the leaderboard")])
def test_the_piimb_place_is_worded_from_the_leaderboard_rank(tmp_path, rank, words):
    def place(f):
        f["piimb/piimb-everything.json"]["leaderboard"]["rank"] = rank
    text = _r3(tmp_path, blocks_r3.readme_bullets, place)
    assert f"with every category masked: average F2 0.851, {words}." in text


def test_a_category_the_prose_cannot_name_is_refused(tmp_path):
    def unnamed(f):
        f[A][DEFAULT]["leak_by_category"]["telepathy"] = [0.9, 3]
    with pytest.raises(RenderError, match="no prose name for telepathy"):
        _a(tmp_path, unnamed)


def test_outputs_without_a_configuration_measured_now_are_refused(tmp_path):
    with pytest.raises(views.ViewError):
        views.preset_of("nullpii-core")


def _nemotron(raw_f2, nemo_f2):
    def edit(f):
        for rel in (R3, R3_EN):
            for dataset, rows in f[rel].items():
                for tool, f2 in (("nemotron-pii-raw", raw_f2), ("nemotron-pii-nemo", nemo_f2)):
                    rows[tool] = {**rows["rizzo-pii"], "f2": f2}
    return edit


def test_the_matrix_counts_nvidias_two_pipelines_as_one_tool_at_the_better_one(tmp_path):
    b = _bench(tmp_path, _nemotron(0.70, 0.72))
    matrix = blocks_r3.matrix(b)
    assert "| nemotron-pii (NVIDIA server pipeline) | 0.720 |" in matrix
    assert "library" not in matrix
    assert blocks_r3.readme_bullets(b).startswith("- **Second of 3** by macro char-F2 in its agent default")
    # METHOD's tables show both.
    gated = blocks_r3.method_table(views.R3_MAIN)(b)
    assert "| nvidia/gliner-PII (library) |" in gated and "| nvidia/gliner-PII (NVIDIA server) |" in gated
    library = _bench(tmp_path, _nemotron(0.72, 0.70), "library")
    assert "| nemotron-pii (`nvidia/gliner-PII`, library) | 0.720 |" in blocks_r3.matrix(library)


def test_the_measured_version_labels_the_rows_and_survives_a_version_bump(tmp_path, monkeypatch):
    run, root, published = ro.write_run(tmp_path / "run"), ro.docs_root(tmp_path), tmp_path / "pb"
    render.render(run, published, root)
    assert json.loads((published / views.OUTPUTS_MARKER).read_text())[views.VERSION_KEY] == views.package_version()
    monkeypatch.setattr(views, "package_version", lambda: "9.9")
    assert render.check(published, published, root) == []
    assert views.load(ro.write_reference(tmp_path / "ref")).version == views.PUBLISHED_VERSION
    assert "| **nullpii 9.9 (agent default)** |" in blocks_ab1.readme_table(_bench(tmp_path, name="bumped"))


def test_leading_on_one_secrets_set_is_not_leading_on_secrets(tmp_path):
    text = _a(tmp_path, lambda f: f[B1][DEFAULT].update(leak_rate=0.05))
    assert "**On secrets alone, nullpii does not lead.**" in text
    assert "On CredData it lets 5.0% through, and no other tool lets fewer through." in text


def test_a_tool_with_the_same_category_rate_does_not_let_fewer_through(tmp_path):
    def same(f):
        f[A][ro.RIZZO]["leak_by_category"]["person"] = [0.235, 969]
    assert "On names, none of the 2 other tools lets fewer through" in _a(tmp_path, same)


def test_a_tool_tied_with_nullpii_on_r3_is_not_ahead_of_it(tmp_path):
    def tied(f):
        f[R3]["_macro"]["rizzo-pii@default"].update(f2=0.758)
    text = _r3(tmp_path, blocks_r3.readme_bullets, tied)
    assert text.startswith("- **First of 2** by macro char-F2 in its agent default (0.758;")
