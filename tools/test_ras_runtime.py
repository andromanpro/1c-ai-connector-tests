from contextlib import nullcontext
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

import ras_runtime as runtime


class LocalRasTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.root = Path(self.folder.name)
        self.addCleanup(self.folder.cleanup)
        self.platform = self.root / "platform"
        self.platform.mkdir()
        for name in ("ras.exe", "rac.exe"):
            (self.platform / name).touch()
        self.cluster = "439b49db-1f52-4c6b-b7f9-3969db2381b2"
        self.config = {"platform_bin": str(self.platform), "cluster": self.cluster,
                       "rac_address": "localhost:1545", "ras_bootstrap": {
                           "agent": "localhost:1540", "runtime_dir": str(self.root / "runtime")}}

    def test_no_bootstrap_never_probes_or_launches(self):
        with patch.object(runtime, "_listening") as probe, patch.object(runtime, "_spawn") as spawn:
            self.assertIsNone(runtime.ensure_ras({}))
            probe.assert_not_called()
            spawn.assert_not_called()

    def test_rejects_remote_target_even_when_reachable(self):
        self.config["rac_address"] = "192.168.1.130:1545"
        with patch.object(runtime, "_spawn") as spawn:
            with self.assertRaises(runtime.RasRuntimeError):
                runtime.ensure_ras(self.config)
            spawn.assert_not_called()

    def test_rejects_remote_agent(self):
        self.config["ras_bootstrap"]["agent"] = "example.org:1540"
        with self.assertRaises(runtime.RasRuntimeError):
            runtime.ensure_ras(self.config)

    def test_rejects_invalid_port_and_extra_parameters(self):
        for value in ("localhost", "localhost:0", "localhost:65536", "localhost:1545 extra"):
            with self.subTest(value=value), self.assertRaises(runtime.RasRuntimeError):
                runtime.local_endpoint(value)
        self.config["ras_bootstrap"]["typo"] = "ignored?"
        with self.assertRaises(runtime.RasRuntimeError):
            runtime.ensure_ras(self.config)

    def test_rejects_same_agent_and_endpoint(self):
        self.config["ras_bootstrap"]["agent"] = "localhost:1545"
        with self.assertRaises(runtime.RasRuntimeError):
            runtime.ensure_ras(self.config)

    def test_loopback_alias_does_not_hide_same_port(self):
        self.config["ras_bootstrap"]["agent"] = "127.0.0.1:1545"
        with self.assertRaises(runtime.RasRuntimeError):
            runtime.ensure_ras(self.config)

    def test_rejects_missing_cluster_and_binary(self):
        self.config["cluster"] = "wrong"
        with self.assertRaises(runtime.RasRuntimeError):
            runtime.ensure_ras(self.config)
        self.config["cluster"] = self.cluster
        (self.platform / "ras.exe").unlink()
        with self.assertRaises(runtime.RasRuntimeError):
            runtime.ensure_ras(self.config)

    def test_rejects_relative_runtime_directory(self):
        self.config["ras_bootstrap"]["runtime_dir"] = "relative"
        with self.assertRaises(runtime.RasRuntimeError):
            runtime.ensure_ras(self.config)

    def test_existing_endpoint_requires_same_cluster_without_spawning(self):
        with patch.object(runtime, "_listening", return_value=True), \
                patch.object(runtime, "_probe", return_value={self.cluster}), \
                patch.object(runtime, "_spawn") as spawn:
            self.assertFalse(runtime.ensure_ras(self.config)["started"])
            spawn.assert_not_called()

    def test_existing_wrong_cluster_is_not_replaced(self):
        with patch.object(runtime, "_listening", return_value=True), \
                patch.object(runtime, "_probe", return_value={"different"}), \
                patch.object(runtime, "_spawn") as spawn:
            with self.assertRaises(runtime.RasRuntimeError):
                runtime.ensure_ras(self.config)
            spawn.assert_not_called()

    def test_competing_start_is_reused_after_mutex(self):
        with patch.object(runtime, "_listening", side_effect=[False, True]), \
                patch.object(runtime, "_mutex", return_value=nullcontext()), \
                patch.object(runtime, "_probe", return_value={self.cluster}), \
                patch.object(runtime, "_spawn") as spawn:
            self.assertFalse(runtime.ensure_ras(self.config)["started"])
            spawn.assert_not_called()

    def test_missing_agent_does_not_start_ras(self):
        with patch.object(runtime, "_listening", return_value=False), \
                patch.object(runtime, "_mutex", return_value=nullcontext()), \
                patch.object(runtime, "_spawn") as spawn:
            with self.assertRaises(runtime.RasRuntimeError):
                runtime.ensure_ras(self.config)
            spawn.assert_not_called()

    def test_success_retains_process_and_verified_proof(self):
        process = Mock(pid=12345)
        with patch.object(runtime, "_listening", side_effect=[False, False, True, True]), \
                patch.object(runtime, "_mutex", return_value=nullcontext()), \
                patch.object(runtime, "_probe", return_value={self.cluster}), \
                patch.object(runtime, "_spawn", return_value=process):
            result = runtime.ensure_ras(self.config)
        self.assertTrue(result["started"])
        saved = json.loads((self.root / "runtime/current.json").read_text(encoding="utf-8"))
        self.assertEqual(saved["pid"], 12345)
        self.assertEqual(saved["cluster"], self.cluster)
        process.terminate.assert_not_called()

    def test_started_wrong_cluster_stops_only_owned_handle(self):
        process = Mock(pid=12345)
        process.poll.return_value = None
        with patch.object(runtime, "_listening", side_effect=[False, False, True, True]), \
                patch.object(runtime, "_mutex", return_value=nullcontext()), \
                patch.object(runtime, "_probe", return_value={"different"}), \
                patch.object(runtime, "_spawn", return_value=process):
            with self.assertRaises(runtime.RasRuntimeError):
                runtime.ensure_ras(self.config)
        process.terminate.assert_called_once_with()
        self.assertFalse((self.root / "runtime/current.json").exists())

    def test_startup_exit_retains_failure_without_claiming_ready(self):
        process = Mock(pid=12345)
        process.poll.return_value = 1
        with patch.object(runtime, "_listening", side_effect=[False, False, True, False]), \
                patch.object(runtime, "_mutex", return_value=nullcontext()), \
                patch.object(runtime, "_spawn", return_value=process):
            with self.assertRaises(runtime.RasRuntimeError):
                runtime.ensure_ras(self.config)
        self.assertFalse((self.root / "runtime/current.json").exists())

    def test_startup_timeout_stops_only_owned_process(self):
        process = Mock(pid=12345)
        process.poll.return_value = None
        with patch.object(runtime, "_listening", side_effect=[False, False, True, False]), \
                patch.object(runtime, "_mutex", return_value=nullcontext()), \
                patch.object(runtime.time, "monotonic", side_effect=[0, 100]), \
                patch.object(runtime, "_spawn", return_value=process):
            with self.assertRaises(runtime.RasRuntimeError):
                runtime.ensure_ras(self.config, timeout=1)
        process.terminate.assert_called_once_with()

    def test_spawn_is_hidden_and_does_not_involve_shell(self):
        with patch.object(runtime.subprocess, "Popen") as launch:
            runtime._spawn(Path("ras.exe"), 1545, "localhost:1540", None)
        self.assertEqual(launch.call_args.args[0], ["ras.exe", "cluster", "--port=1545", "localhost:1540"])
        self.assertEqual(launch.call_args.kwargs["creationflags"], runtime.subprocess.CREATE_NO_WINDOW)
        self.assertNotIn("shell", launch.call_args.kwargs)


if __name__ == "__main__":
    unittest.main()
