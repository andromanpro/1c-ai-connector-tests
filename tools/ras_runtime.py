"""Restore an explicitly configured local 1C RAS endpoint without elevation.

No infobase operations, credentials, desktop automation or foreign process stops.
The runtime is persistent across verifier invocations and restored on demand
after a reboot. Existing reachable endpoints must expose the expected cluster.
"""
from contextlib import contextmanager
import json
from pathlib import Path
import re
import socket
import subprocess
import time
import uuid


class RasRuntimeError(RuntimeError):
    pass


def local_endpoint(value):
    match = re.fullmatch(r"(localhost|127\.0\.0\.1|\[::1\]):([0-9]+)", str(value), re.I)
    if not match or not 1 <= int(match[2]) <= 65535:
        raise RasRuntimeError("RAS bootstrap requires an explicit loopback host and valid port")
    host = match[1].strip("[]").lower()
    return host, int(match[2])


def _listening(endpoint):
    try:
        with socket.create_connection(endpoint, timeout=1):
            return True
    except OSError:
        return False


def _probe(rac, address):
    try:
        result = subprocess.run([str(rac), "cluster", "list", address], capture_output=True,
                                timeout=10, creationflags=subprocess.CREATE_NO_WINDOW)
    except (OSError, subprocess.TimeoutExpired) as error:
        raise RasRuntimeError("Cannot verify local RAS cluster inventory") from error
    if result.returncode:
        raise RasRuntimeError("Local RAS is reachable but cluster inventory failed")
    text = result.stdout.decode("utf-8-sig", errors="replace")
    return set(re.findall(r"(?im)^cluster\s*:\s*([0-9a-f-]{36})\s*$", text))


def _verified(rac, address, cluster):
    if cluster not in _probe(rac, address):
        raise RasRuntimeError("RAS exposes a different cluster; refusing to continue")


@contextmanager
def _mutex(port):
    import win32api
    import win32event
    handle = win32event.CreateMutex(None, False, "Local\\1CVerifiedRAS_" + str(port))
    acquired = False
    try:
        status = win32event.WaitForSingleObject(handle, 30000)
        if status not in (win32event.WAIT_OBJECT_0, win32event.WAIT_ABANDONED):
            raise RasRuntimeError("Timed out waiting for local RAS startup ownership")
        acquired = True
        yield
    finally:
        if acquired:
            win32event.ReleaseMutex(handle)
        win32api.CloseHandle(handle)


def _spawn(binary, port, agent, log):
    return subprocess.Popen([str(binary), "cluster", "--port=" + str(port), agent],
                            stdout=log, stderr=log, creationflags=subprocess.CREATE_NO_WINDOW)


def _atomic(path, value):
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


def ensure_ras(config, timeout=15):
    """Validate or restore the opt-in local endpoint; return non-secret evidence.

    ras_bootstrap must contain exactly agent and runtime_dir. Other configurations
    keep their existing externally managed endpoint and are never auto-started.
    """
    bootstrap = config.get("ras_bootstrap")
    if bootstrap is None:
        return None
    if not isinstance(bootstrap, dict) or set(bootstrap) != {"agent", "runtime_dir"}:
        raise RasRuntimeError("ras_bootstrap requires exactly agent and runtime_dir")
    if timeout <= 0:
        raise RasRuntimeError("RAS startup timeout must be positive")
    address = config.get("rac_address", "localhost:1545")
    endpoint = local_endpoint(address)
    agent_endpoint = local_endpoint(bootstrap["agent"])
    if endpoint[1] == agent_endpoint[1]:
        raise RasRuntimeError("RAS and server-agent endpoints must differ")
    try:
        cluster = str(uuid.UUID(config["cluster"]))
    except (KeyError, ValueError, TypeError) as error:
        raise RasRuntimeError("An explicit expected cluster UUID is required") from error
    platform = Path(config["platform_bin"]).resolve()
    rac, binary = platform / "rac.exe", platform / "ras.exe"
    if not rac.is_file() or not binary.is_file():
        raise RasRuntimeError("RAS and RAC must exist in the configured platform directory")
    runtime = Path(bootstrap["runtime_dir"])
    if not runtime.is_absolute():
        raise RasRuntimeError("RAS runtime directory must be absolute")
    if _listening(endpoint):
        _verified(rac, address, cluster)
        return {"started": False, "address": address, "cluster": cluster, "verified": True}
    with _mutex(endpoint[1]):
        if _listening(endpoint):
            _verified(rac, address, cluster)
            return {"started": False, "address": address, "cluster": cluster, "verified": True}
        if not _listening(agent_endpoint):
            raise RasRuntimeError("The configured local server agent is unavailable")
        runtime.mkdir(parents=True, exist_ok=True)
        attempt = uuid.uuid4().hex
        log_path = runtime / ("ras-" + attempt + ".log")
        with log_path.open("xb") as log:
            process = _spawn(binary, endpoint[1], bootstrap["agent"], log)
        try:
            deadline = time.monotonic() + timeout
            while not _listening(endpoint):
                if process.poll() is not None:
                    raise RasRuntimeError("Owned RAS exited during startup; inspect its retained runtime log")
                if time.monotonic() >= deadline:
                    raise RasRuntimeError("Owned RAS did not become ready before the deadline")
                time.sleep(0.1)
            _verified(rac, address, cluster)
        except Exception:
            # This Popen handle belongs only to the process created above.
            if process.poll() is None:
                process.terminate()
                process.wait(timeout=10)
            raise
        result = {"started": True, "pid": process.pid, "address": address,
                  "agent": bootstrap["agent"], "cluster": cluster, "verified": True,
                  "binary": str(binary), "log": str(log_path)}
        _atomic(runtime / ("proof-" + attempt + ".json"), result)
        _atomic(runtime / "current.json", result)
        return result
