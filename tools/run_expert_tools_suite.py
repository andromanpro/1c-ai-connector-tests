"""Run the frozen suite; verified_yaxunit owns all synthetic HTTP fixtures."""
from pathlib import Path
import sys
import subprocess
import json
import collections

sys.stdout.reconfigure(encoding="utf-8", line_buffering=True)

if __name__ == "__main__":
    result = subprocess.run([
        sys.executable, str(Path(__file__).with_name("verified_yaxunit.py")), *sys.argv[1:]
    ])
    if "--run-folder" not in sys.argv:
        raise SystemExit(result.returncode)
    folder = Path(sys.argv[sys.argv.index("--run-folder") + 1])
    recorded = folder / "expert-fixture-events.json"
    if not recorded.exists():
        print("Verified runner did not produce expert-fixture events; see its diagnostic above.")
        raise SystemExit(result.returncode or 1)
    events = json.loads(recorded.read_text(encoding="utf-8"))
    checks_passed = (
        not any("fixture_error" in event for event in events)
        and all(check["passed"] for event in events for check in event.get("checks", []))
    )
    output = {
        "requests": len(events),
        "scenarios": dict(collections.Counter(event["scenario"] for event in events)),
        "events": events,
        "all_fixture_checks_passed": checks_passed,
        "runner_exit_code": result.returncode,
    }
    path = folder / "expert-fixture.json"
    assert not path.exists()
    path.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
    print("Expert fixture:", output["requests"], "requests", output["scenarios"],
          "checks:", checks_passed)
    raise SystemExit(result.returncode or (0 if checks_passed else 1))

