"""
Detects the TCP port a managed app's process is listening on.

Uses psutil to inspect the process's (and its children's) open sockets rather
than relying on the app to declare a port itself — this works for apps we
didn't author and requires no changes to how they're packaged or started.
"""

import psutil

from mantyx.config import get_settings
from mantyx.logging import get_logger

logger = get_logger("port_detector")

# Ports Mantyx itself might be bound to; never report these as an app's web port.
_RESERVED_PORTS = {get_settings().port}


def detect_listening_port(pid: int) -> int | None:
    """Return a TCP port the given process (or a direct child) is listening on.

    Looks at the target process and its immediate children (e.g. a launcher
    script that execs a server, or a dev-server parent with worker children)
    for sockets in LISTEN state. If multiple candidates are found, the lowest
    port number is preferred as a simple, deterministic heuristic.

    Returns None if the process is gone, permissions are insufficient, or no
    listening socket is found.
    """
    try:
        process = psutil.Process(pid)
    except psutil.NoSuchProcess:
        return None

    candidates: set[int] = set()

    for proc in [process, *_safe_children(process)]:
        candidates.update(_listening_ports(proc))

    candidates -= _RESERVED_PORTS

    if not candidates:
        return None

    return min(candidates)


def _safe_children(process: psutil.Process) -> list[psutil.Process]:
    try:
        return process.children(recursive=True)
    except psutil.Error:
        return []


def _listening_ports(process: psutil.Process) -> set[int]:
    try:
        connections = process.net_connections(kind="inet")
    except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
        return set()
    except Exception as e:
        # net_connections is best-effort; never let detection crash the caller.
        logger.debug(f"Failed to read connections for PID {process.pid}: {e}")
        return set()

    return {
        conn.laddr.port for conn in connections if conn.status == psutil.CONN_LISTEN and conn.laddr
    }
