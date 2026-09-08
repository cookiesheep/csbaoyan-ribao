from __future__ import annotations

import datetime as dt
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from csbaoyan_daily.app.generate import GenerateArtifacts
from csbaoyan_daily.app.xhs_export import XhsExportOptions, run_xhs_export


class XhsExportTests(unittest.TestCase):
    def _artifacts(
        self,
        repo_root: Path,
        payload: dict[str, object],
        pages_dir: Path | None = None,
    ) -> GenerateArtifacts:
        report_date = "2026-05-18"
        report_path = (pages_dir or repo_root / "pages") / "data" / "reports" / f"{report_date}.md"
        report_path.parent.mkdir(parents=True)
        report_path.write_text("# CS保研信息日报\n\n## 今日概览\n\n历史日报正文。\n", encoding="utf-8")

        export_file = repo_root / "exports" / f"{report_date}T06-30-00.json"
        export_file.parent.mkdir(parents=True)
        export_file.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

        return GenerateArtifacts(
            report_date=report_date,
            export_file=export_file,
            extracted_path=repo_root / "internal" / "extracted" / f"{report_date}.md",
            report_path=report_path,
            transcript_path=repo_root / "internal" / "transcripts" / f"{report_date}.txt",
            manifest_count=5,
            message_count=123,
            chunk_count=4,
        )

    def test_disabled_export_does_not_touch_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo_root = Path(tmpdir)
            options = XhsExportOptions(
                artifacts=GenerateArtifacts(
                    report_date="2026-05-18",
                    export_file=repo_root / "missing-export.json",
                    extracted_path=repo_root / "missing-extracted.md",
                    report_path=repo_root / "missing-report.md",
                    transcript_path=repo_root / "missing-transcript.txt",
                    manifest_count=0,
                    message_count=0,
                    chunk_count=0,
                ),
                pages_dir=repo_root / "pages",
                repo_root=repo_root,
                enabled=False,
            )

            result = run_xhs_export(options)

            self.assertIsNone(result)
            self.assertFalse((repo_root / "pages" / "data" / "xhs").exists())

    def test_export_writes_stable_contract(self) -> None:
        payload = {
            "group_display": "计算机保研交流群（脱敏）",
            "statistics": {
                "timeRange": {
                    "start": "2026-05-18T00:01:02+08:00",
                    "end": "2026-05-18T23:58:59+08:00",
                }
            },
            "messages": [],
        }

        with tempfile.TemporaryDirectory() as tmpdir:
            repo_root = Path(tmpdir)
            artifacts = self._artifacts(repo_root, payload)

            output_path = run_xhs_export(
                XhsExportOptions(
                    artifacts=artifacts,
                    pages_dir=repo_root / "pages",
                    repo_root=repo_root,
                    enabled=True,
                )
            )

            expected_path = repo_root / "pages" / "data" / "xhs" / "2026-05-18.json"
            self.assertEqual(output_path, expected_path)
            envelope = json.loads(expected_path.read_text(encoding="utf-8"))

            self.assertEqual(envelope["schema"], "csbaoyan-xhs-export/v1")
            self.assertEqual(envelope["date"], "2026-05-18")
            self.assertEqual(envelope["source"]["group_display"], "计算机保研交流群（脱敏）")
            self.assertEqual(envelope["source"]["message_count"], 123)
            self.assertEqual(envelope["source"]["chunk_count"], 4)
            self.assertEqual(envelope["source"]["time_range"], payload["statistics"]["timeRange"])
            self.assertEqual(envelope["report_markdown"], artifacts.report_path.read_text(encoding="utf-8"))
            self.assertEqual(envelope["report_path"], "pages/data/reports/2026-05-18.md")
            self.assertTrue(envelope["compliance"]["must_include_disclaimer"])
            self.assertEqual(
                envelope["compliance"]["prohibited"],
                ["external_links", "qr_codes", "watermarks", "personal_contact", "raw_user_identifiers"],
            )

            generated_at = dt.datetime.fromisoformat(envelope["generated_at"])
            self.assertEqual(generated_at.utcoffset(), dt.timedelta(0))

    def test_missing_optional_source_metadata_uses_empty_strings(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo_root = Path(tmpdir)
            artifacts = self._artifacts(repo_root, {"messages": []})

            output_path = run_xhs_export(
                XhsExportOptions(
                    artifacts=artifacts,
                    pages_dir=repo_root / "pages",
                    repo_root=repo_root,
                    enabled=True,
                )
            )
            envelope = json.loads(output_path.read_text(encoding="utf-8"))

            self.assertEqual(envelope["source"]["group_display"], "")
            self.assertEqual(envelope["source"]["time_range"], {"start": "", "end": ""})

    def test_external_pages_directory_uses_logical_report_path(self) -> None:
        with tempfile.TemporaryDirectory() as repo_tmp, tempfile.TemporaryDirectory() as pages_tmp:
            repo_root = Path(repo_tmp)
            pages_dir = Path(pages_tmp)
            payload = {
                "statistics": {"timeRange": {"start": "2026-05-18", "end": "2026-05-18"}},
                "messages": [],
            }
            artifacts = self._artifacts(repo_root, payload, pages_dir=pages_dir)

            output_path = run_xhs_export(
                XhsExportOptions(
                    artifacts=artifacts,
                    pages_dir=pages_dir,
                    repo_root=repo_root,
                    enabled=True,
                )
            )

            envelope = json.loads(output_path.read_text(encoding="utf-8"))
            self.assertEqual(envelope["report_path"], "pages/data/reports/2026-05-18.md")


if __name__ == "__main__":
    unittest.main()
