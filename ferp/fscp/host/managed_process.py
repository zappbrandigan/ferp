from __future__ import annotations

import time
from dataclasses import dataclass, field
from multiprocessing import Pipe, Process
from multiprocessing.connection import Connection
from typing import Callable, Optional

WorkerFn = Callable[[Connection], None]


@dataclass
class ManagedProcess:
    worker: WorkerFn

    process: Optional[Process] = field(init=False, default=None)
    connection: Optional[Connection] = field(init=False, default=None)
    start_time: Optional[float] = field(init=False, default=None)
    exit_code: Optional[int] = field(init=False, default=None)

    def start(self) -> None:
        """
        Spawn the worker inside a multiprocessing.Process with a duplex Pipe.
        """
        if self.process is not None:
            raise RuntimeError("Process already started")

        parent_conn, child_conn = Pipe()

        proc = Process(
            target=self._bootstrap_worker,
            args=(self.worker, child_conn),
            daemon=False,
        )
        proc.start()

        # Parent keeps the parent-side connection only.
        child_conn.close()

        self.process = proc
        self.connection = parent_conn
        self.start_time = time.time()

    def terminate(self) -> None:
        """
        Attempt graceful termination of the worker.
        """
        if self.process is None:
            return

        self.process.terminate()
        if not self._wait_for_exit(timeout=1.0):
            # Process refused to exit, escalate to a kill.
            self.kill()
            return
        self._cleanup_connection()

    def kill(self) -> None:
        """
        Forcefully kill the worker.
        """
        if self.process is None:
            return

        self.process.kill()
        self._wait_for_exit(timeout=1.0)
        self._cleanup_connection()

    def poll_exit(self) -> Optional[int]:
        """
        Return the worker's exit code if it has finished.
        """
        if self.process is None:
            return None

        if self.process.exitcode is None:
            self.process.join(timeout=0)

        self.exit_code = self.process.exitcode
        return self.exit_code

    def _wait_for_exit(self, *, timeout: Optional[float]) -> bool:
        """
        Wait for the subprocess to exit. Returns True if it exited.
        """
        if self.process is None:
            return True

        self.process.join(timeout=timeout)
        if self.process.exitcode is not None:
            self.exit_code = self.process.exitcode
            return True

        return False

    def _cleanup_connection(self) -> None:
        if self.connection is not None:
            try:
                self.connection.close()
            except Exception:
                pass
            finally:
                self.connection = None

    @staticmethod
    def _bootstrap_worker(worker: WorkerFn, conn: Connection) -> None:
        try:
            worker(conn)
        finally:
            try:
                conn.close()
            except Exception:
                pass
