from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_edge_collector_never_runs_llm_pipeline() -> None:
    script = (ROOT / "scripts" / "daily_auto.production.ps1").read_text(encoding="utf-8-sig")
    assert "csbaoyan_daily.cli ingest" in script
    assert "csbaoyan_daily.cli pipeline" not in script
    assert "Tedge.json.part" in script
    assert "HANDOFF_COMPLETE" in script
    assert "& C:\\Users\\wqf18\\miniconda3\\python.exe" in script
    assert '$env:PYTHONPATH = "D:\\code\\csbaoyan\\src;D:\\code\\csbaoyan\\.venv\\Lib\\site-packages"' in script
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
