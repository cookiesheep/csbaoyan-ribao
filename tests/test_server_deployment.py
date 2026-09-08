from __future__ import annotations

from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]


def test_edge_collector_never_runs_llm_pipeline() -> None:
    script = (ROOT / "scripts" / "daily_auto.production.ps1").read_text(encoding="utf-8-sig")
    assert "edge_python_bootstrap.py\" ingest --date $Date" in script
    assert 'Get-ChildItem -LiteralPath "D:\\code\\csbaoyan\\chat_exports"' in script
    assert "csbaoyan_daily.cli pipeline" not in script
    assert "Tedge.json.part" in script
    assert "HANDOFF_COMPLETE" in script
    assert '& "C:\\Users\\wqf18\\miniconda3\\python.exe" "D:\\code\\csbaoyan\\scripts\\edge_python_bootstrap.py"' in script
    assert "& .venv\\Scripts\\python.exe" not in script
    assert "& .\\.venv\\Scripts\\python.exe" not in script


def test_server_pipeline_is_resource_bounded() -> None:
    unit = (ROOT / "deploy" / "systemd" / "csbaoyan-daily@.service").read_text(encoding="utf-8")
    script = (ROOT / "scripts" / "server_process_daily.sh").read_text(encoding="utf-8")
    assert "MemoryMax=4G" in unit
    assert "CPUQuota=400%" in unit
    assert "--skip-commit" in script
    assert "--xhs-export" in script
    assert 'rm -f -- "$input_file"' in script


def test_edge_python_bootstrap_loads_the_source_tree() -> None:
    result = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "edge_python_bootstrap.py"), "--help"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert "pipeline" in result.stdout
