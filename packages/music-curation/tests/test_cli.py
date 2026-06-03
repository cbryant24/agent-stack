from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from click.testing import CliRunner

from music_curation.cli import cli
from music_curation.models import MusicResult, SunoPrompt


def _make_result(**kwargs) -> MusicResult:
    defaults = dict(
        prompts=[SunoPrompt(style_field="lo-fi, 80 BPM, jazz piano, vinyl crackle")],
        theory_reasoning="Warm analog texture creates contemplative mood.",
        run_id="test-run-001",
        status="completed",
        cost_usd=0.02,
        items_processed=1,
        wall_time_sec=3.5,
        generation_ids=["gen-001"],
    )
    defaults.update(kwargs)
    return MusicResult(**defaults)


@pytest.fixture
def runner():
    return CliRunner()


class TestGenerateCommand:
    def test_help(self, runner):
        result = runner.invoke(cli, ["generate", "--help"])
        assert result.exit_code == 0
        assert "Generate" in result.output

    def test_dry_run(self, runner):
        with patch("music_curation.cli.curate_sync") as mock_curate:
            mock_curate.return_value = _make_result(
                prompts=[SunoPrompt(style_field="(dry run — no generation performed)")],
                theory_reasoning="Dry run: would have generated prompts for: lo-fi",
            )
            result = runner.invoke(cli, ["generate", "lo-fi vibes", "--dry-run"])
            assert result.exit_code == 0
            call_kwargs = mock_curate.call_args[1]
            assert call_kwargs["dry_run"] is True

    def test_output_shows_style_field(self, runner):
        with patch("music_curation.cli.curate_sync") as mock_curate:
            mock_curate.return_value = _make_result()
            result = runner.invoke(cli, ["generate", "lo-fi chill", "--skip-question"])
            assert result.exit_code == 0
            assert "lo-fi" in result.output

    def test_output_shows_generation_id(self, runner):
        with patch("music_curation.cli.curate_sync") as mock_curate:
            mock_curate.return_value = _make_result()
            result = runner.invoke(cli, ["generate", "test", "--skip-question"])
            assert result.exit_code == 0
            assert "gen-001" in result.output


class TestReportCommand:
    def test_help(self, runner):
        result = runner.invoke(cli, ["report", "--help"])
        assert result.exit_code == 0

    def test_report_requires_reaction(self, runner):
        result = runner.invoke(cli, ["report", "gen-001"])
        assert result.exit_code != 0

    def test_report_valid_reaction(self, runner):
        mock_store = MagicMock()
        mock_store.ensure_collection = AsyncMock()
        mock_store.get_generation = AsyncMock(
            return_value=MagicMock(suggested_track_title="Test Track")
        )
        mock_store.update_generation_reaction = AsyncMock()

        with patch("music_curation.cli._get_stores") as mock_get:
            mock_get.return_value = (mock_store, MagicMock(), MagicMock())
            result = runner.invoke(cli, ["report", "gen-001", "--reaction", "loved"])
            assert result.exit_code == 0
            assert "loved" in result.output

    def test_report_not_found(self, runner):
        mock_store = MagicMock()
        mock_store.ensure_collection = AsyncMock()
        mock_store.get_generation = AsyncMock(return_value=None)

        with patch("music_curation.cli._get_stores") as mock_get:
            mock_get.return_value = (mock_store, MagicMock(), MagicMock())
            result = runner.invoke(cli, ["report", "nonexistent", "--reaction", "loved"])
            assert result.exit_code == 1

    def _report_store(self):
        mock_store = MagicMock()
        mock_store.ensure_collection = AsyncMock()
        mock_store.get_generation = AsyncMock(
            return_value=MagicMock(suggested_track_title="Test Track")
        )
        mock_store.update_generation_reaction = AsyncMock()
        return mock_store

    def test_report_liked_replaces_approved(self, runner):
        # Change 1: `approved` is no longer a valid choice; `liked` is.
        mock_store = self._report_store()
        with patch("music_curation.cli._get_stores") as mock_get:
            mock_get.return_value = (mock_store, MagicMock(), MagicMock())
            ok = runner.invoke(cli, ["report", "g1", "--reaction", "liked"])
            assert ok.exit_code == 0
            bad = runner.invoke(cli, ["report", "g1", "--reaction", "approved"])
            assert bad.exit_code != 0  # rejected at parse time

    def test_report_prompt_failed_valid(self, runner):
        # Change 2: prompt_failed is a valid reaction.
        mock_store = self._report_store()
        with patch("music_curation.cli._get_stores") as mock_get:
            mock_get.return_value = (mock_store, MagicMock(), MagicMock())
            result = runner.invoke(cli, ["report", "g1", "--reaction", "prompt_failed"])
            assert result.exit_code == 0
            assert mock_store.update_generation_reaction.await_args[0][1] == "prompt_failed"

    def test_rating_valid_accepted(self, runner):
        mock_store = self._report_store()
        with patch("music_curation.cli._get_stores") as mock_get:
            mock_get.return_value = (mock_store, MagicMock(), MagicMock())
            result = runner.invoke(cli, ["report", "g1", "--reaction", "loved", "--rating", "4"])
            assert result.exit_code == 0
            assert mock_store.update_generation_reaction.await_args.kwargs["rating"] == 4

    def test_rating_out_of_range_rejected(self, runner):
        mock_store = self._report_store()
        with patch("music_curation.cli._get_stores") as mock_get:
            mock_get.return_value = (mock_store, MagicMock(), MagicMock())
            for bad in ("0", "6", "-1"):
                result = runner.invoke(cli, ["report", "g1", "--reaction", "loved", "--rating", bad])
                assert result.exit_code != 0  # IntRange validates at parse time

    def test_rating_optional_none_when_omitted(self, runner):
        mock_store = self._report_store()
        with patch("music_curation.cli._get_stores") as mock_get:
            mock_get.return_value = (mock_store, MagicMock(), MagicMock())
            result = runner.invoke(cli, ["report", "g1", "--reaction", "loved"])
            assert result.exit_code == 0
            assert mock_store.update_generation_reaction.await_args.kwargs["rating"] is None

    def test_rating_with_negative_reaction_warns_but_succeeds(self, runner):
        mock_store = self._report_store()
        with patch("music_curation.cli._get_stores") as mock_get:
            mock_get.return_value = (mock_store, MagicMock(), MagicMock())
            result = runner.invoke(cli, ["report", "g1", "--reaction", "disliked", "--rating", "3"])
            assert result.exit_code == 0  # warn, don't reject
            assert "unusual" in result.output.lower()
            assert mock_store.update_generation_reaction.await_args.kwargs["rating"] == 3

    def test_notes_and_context_passed_through(self, runner):
        mock_store = self._report_store()
        with patch("music_curation.cli._get_stores") as mock_get:
            mock_get.return_value = (mock_store, MagicMock(), MagicMock())
            result = runner.invoke(cli, [
                "report", "g1", "--reaction", "loved",
                "--notes", "slow it down next time",
                "--context", "cowbell placement is exactly right",
            ])
            assert result.exit_code == 0
            kwargs = mock_store.update_generation_reaction.await_args.kwargs
            assert kwargs["notes"] == "slow it down next time"
            assert kwargs["context"] == "cowbell placement is exactly right"


class TestReviewPendingCommand:
    def test_no_pending(self, runner):
        mock_store = MagicMock()
        mock_store.ensure_collection = AsyncMock()
        mock_store.list_pending = AsyncMock(return_value=[])

        with patch("music_curation.cli._get_stores") as mock_get:
            mock_get.return_value = (mock_store, MagicMock(), MagicMock())
            result = runner.invoke(cli, ["review-pending"])
            assert result.exit_code == 0
            assert "No pending" in result.output

    def test_shows_pending(self, runner):
        gen = MagicMock()
        gen.entry_id = "gen-123"
        gen.suggested_track_title = "Midnight Phonk"
        gen.style_field = "lo-fi phonk, 80 BPM, Memphis cowbell"
        gen.created_at = "2026-05-29T12:00:00+00:00"

        mock_store = MagicMock()
        mock_store.ensure_collection = AsyncMock()
        mock_store.list_pending = AsyncMock(return_value=[gen])

        with patch("music_curation.cli._get_stores") as mock_get:
            mock_get.return_value = (mock_store, MagicMock(), MagicMock())
            result = runner.invoke(cli, ["review-pending"])
            assert result.exit_code == 0
            assert "Midnight Phonk" in result.output
            assert "gen-123" in result.output


class TestRecallCommand:
    def test_no_results(self, runner):
        with (
            patch("music_curation.cli._get_stores") as mock_get,
            patch("music_curation.cli.retrieve_context") as mock_retrieve,
        ):
            from music_curation.retrieval import RetrievedContext
            mock_store = MagicMock()
            mock_store.ensure_collection = AsyncMock()
            mock_get.return_value = (mock_store, MagicMock(), MagicMock())
            mock_retrieve.return_value = RetrievedContext()
            result = runner.invoke(cli, ["recall", "lo-fi vibes"])
            assert result.exit_code == 0
            assert "No results" in result.output


class TestSeedGroup:
    def test_seed_help(self, runner):
        result = runner.invoke(cli, ["seed", "--help"])
        assert result.exit_code == 0
        assert "ingest" in result.output
        assert "review-taste" in result.output

    def test_seed_ingest_help(self, runner):
        result = runner.invoke(cli, ["seed", "ingest", "--help"])
        assert result.exit_code == 0
        assert "PATH" in result.output

    def test_seed_dry_run(self, runner, tmp_path):
        md = tmp_path / "test.md"
        md.write_text("# Test\n\n## Prompts\n\n```\nlo-fi, 80 BPM, jazz piano, vinyl\n```\n")

        with patch("music_curation.cli.ingest_seed") as mock_ingest:
            from unittest.mock import AsyncMock as AM
            mock_ingest.side_effect = lambda p, **kw: None
            result = runner.invoke(cli, ["seed", "ingest", str(md), "--dry-run"])
            # Verify the dry_run flag was passed


class TestTasteGroup:
    def test_taste_add_help(self, runner):
        result = runner.invoke(cli, ["taste", "add", "--help"])
        assert result.exit_code == 0
        assert "--valence" in result.output


class TestChainGroup:
    def test_chain_show_help(self, runner):
        result = runner.invoke(cli, ["chain", "show", "--help"])
        assert result.exit_code == 0
        assert "CHAIN_ROOT_ID" in result.output
