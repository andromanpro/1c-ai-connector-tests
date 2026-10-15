"""Run the frozen suite with the synthetic expert-model fixture."""
from pathlib import Path
import sys,subprocess,json,collections
from expert_tools_fixture import local_expert_fixture
sys.stdout.reconfigure(encoding="utf-8",line_buffering=True)
if __name__=="__main__":
    assert "--run-folder" in sys.argv
    folder=Path(sys.argv[sys.argv.index("--run-folder")+1])
    with local_expert_fixture() as events:
        result=subprocess.run([sys.executable,str(Path(__file__).with_name("verified_yaxunit.py")),*sys.argv[1:]])
    output={"requests":len(events),"scenarios":dict(collections.Counter(x["scenario"] for x in events)),
            "events":events,"all_fixture_checks_passed":not any("fixture_error" in x for x in events),
            "runner_exit_code":result.returncode}
    path=folder/"expert-fixture.json"
    assert not path.exists()
    path.write_text(json.dumps(output,ensure_ascii=False,indent=2),encoding="utf-8")
    print("Expert fixture:",output["requests"],"requests",output["scenarios"],"checks:",output["all_fixture_checks_passed"])
    raise SystemExit(result.returncode or (0 if output["all_fixture_checks_passed"] else 1))

