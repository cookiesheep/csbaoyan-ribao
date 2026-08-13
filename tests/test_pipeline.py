import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from csbaoyan_daily.app.pipeline import PipelineOptions, run_pipeline
from csbaoyan_daily.app.generate import GenerateArtifacts
from csbaoyan_daily.infra.git_publish import PublishResult


class PipelineTests(unittest.TestCase):
    def _artifacts(self, root: Path) -> GenerateArtifacts:
        return GenerateArtifacts(
            report_date="2026-05-18",
            export_file=root / "export.json",
            extracted_path=root / "extracted.md",
            report_path=root / "report.md",
            transcript_path=root / "transcript.txt",
            manifest_count=1,
            message_count=10,
            chunk_count=2,
        )

    def test_skip_commit_avoids_publish_and_broadcast(self) -> None:
        options = PipelineOptions(
            repo_root=Path.cwd(),
            date="2026-05-18",
            skip_generate=True,
            skip_release_check=True,
            skip_commit=True,
        )

        with patch("csbaoyan_daily.app.pipeline.run_publish") as mocked_publish, patch(
            "csbaoyan_daily.app.pipeline.broadcast_report"
        ) as mocked_broadcast:
            resolved_date = run_pipeline(options)

        self.assertEqual(resolved_date, "2026-05-18")
        mocked_publish.assert_not_called()
        mocked_broadcast.assert_not_called()

    def test_no_changes_skips_broadcast(self) -> None:
        options = PipelineOptions(
            repo_root=Path.cwd(),
            date="2026-05-18",
            skip_generate=True,
            skip_release_check=True,
            skip_push=False,
        )

        with patch(
            "csbaoyan_daily.app.pipeline.run_publish",
            return_value=PublishResult(changes_detected=False, committed=False, pushed=False),
        ) as mocked_publish, patch("csbaoyan_daily.app.pipeline.broadcast_report") as mocked_broadcast, patch(
            "csbaoyan_daily.app.pipeline.run_publish_preflight",
            return_value="main",
        ):
            resolved_date = run_pipeline(options)

        self.assertEqual(resolved_date, "2026-05-18")
        mocked_publish.assert_called_once()
        mocked_broadcast.assert_not_called()

    def test_successful_publish_triggers_broadcast(self) -> None:
        options = PipelineOptions(
            repo_root=Path.cwd(),
            date="2026-05-18",
            skip_generate=True,
            skip_release_check=True,
        )

        with patch(
            "csbaoyan_daily.app.pipeline.run_publish",
            return_value=PublishResult(changes_detected=True, committed=True, pushed=True, branch="main"),
        ) as mocked_publish, patch(
            "csbaoyan_daily.app.pipeline.broadcast_report",
            return_value=True,
        ) as mocked_broadcast, patch(
            "csbaoyan_daily.app.pipeline.run_publish_preflight",
            return_value="main",
        ):
            resolved_date = run_pipeline(options)

        self.assertEqual(resolved_date, "2026-05-18")
        mocked_publish.assert_called_once()
        mocked_broadcast.assert_called_once()

    def test_xhs_export_runs_after_generation_when_enabled(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            options = PipelineOptions(
                repo_root=root,
                pages_dir=root / "pages",
                date="2026-05-18",
                xhs_export=True,
                skip_release_check=True,
                skip_commit=True,
            )

            with patch(
                "csbaoyan_daily.app.pipeline.run_generate_report",
                return_value=self._artifacts(root),
            ), patch("csbaoyan_daily.app.xhs_export.run_xhs_export", return_value=root / "xhs.json") as export:
                resolved_date = run_pipeline(options)

            self.assertEqual(resolved_date, "2026-05-18")
            export.assert_called_once()
            export_options = export.call_args.args[0]
            self.assertTrue(export_options.enabled)
            self.assertEqual(export_options.pages_dir, root / "pages")
            self.assertEqual(export_options.repo_root, root.resolve())

    def test_xhs_export_failure_does_not_interrupt_pipeline(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            options = PipelineOptions(
                repo_root=root,
                pages_dir=root / "pages",
                date="2026-05-18",
                xhs_export=True,
                skip_release_check=True,
                skip_commit=True,
            )

            with patch(
                "csbaoyan_daily.app.pipeline.run_generate_report",
                return_value=self._artifacts(root),
            ), patch(
                "csbaoyan_daily.app.xhs_export.run_xhs_export",
                side_effect=FileNotFoundError("missing report"),
            ), self.assertLogs(level="WARNING") as logs:
                resolved_date = run_pipeline(options)

            self.assertEqual(resolved_date, "2026-05-18")
            self.assertIn("小红书导出失败，不影响每日日报", "\n".join(logs.output))

    def test_xhs_export_is_skipped_without_generate_artifacts(self) -> None:
        options = PipelineOptions(
            repo_root=Path.cwd(),
            date="2026-05-18",
            xhs_export=True,
            skip_generate=True,
            skip_release_check=True,
            skip_commit=True,
        )

        with patch("csbaoyan_daily.app.xhs_export.run_xhs_export") as export, self.assertLogs(level="INFO") as logs:
            resolved_date = run_pipeline(options)

        self.assertEqual(resolved_date, "2026-05-18")
        export.assert_not_called()
        self.assertIn("跳过小红书导出", "\n".join(logs.output))


if __name__ == "__main__":
    unittest.main()
