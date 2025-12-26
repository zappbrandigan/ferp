from multiprocessing.connection import Connection

from ferp.fscp.scripts.runtime.io import configure_connection
from ferp.fscp.scripts.runtime.script import ScriptRuntime


def run_runtime(conn: Connection) -> None:
    """
    Entry point for running ScriptRuntime under multiprocessing.Pipe transport.
    """
    configure_connection(conn)
    runtime = ScriptRuntime()
    runtime.run()
