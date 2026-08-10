import logging
import logging.handlers
import os
import queue
import threading
import traceback


class Debugger:
    """Centralized logger (ctx["DEBUGGER"], or passed explicitly). Calls enqueue
    onto a queue.Queue; a background thread does the blocking file write, so
    callers never stall on disk I/O."""

    def __init__(self, logPath: str = "Debug/debug.txt", maxBytes: int = 2_000_000, backupCount: int = 3) -> None:
        directory = os.path.dirname(logPath)
        if directory:
            os.makedirs(directory, exist_ok=True)

        self._logger = logging.getLogger(f"rotmg-ascii.{id(self)}")
        self._logger.setLevel(logging.DEBUG)
        self._logger.propagate = False

        handler = logging.handlers.RotatingFileHandler(
            logPath, maxBytes=maxBytes, backupCount=backupCount, encoding="utf-8"
        )
        handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))
        self._logger.addHandler(handler)
        self._handler = handler

        self._queue: "queue.Queue" = queue.Queue()
        self._caughtUp = threading.Event()
        self._active = True
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def debug(self, msg: str) -> None:
        self._enqueue(logging.DEBUG, msg)

    def info(self, msg: str) -> None:
        self._enqueue(logging.INFO, msg)

    def warning(self, msg: str) -> None:
        self._enqueue(logging.WARNING, msg)

    def error(self, msg: str) -> None:
        self._enqueue(logging.ERROR, msg)

    def exception(self, msg: str) -> None:
        # format_exc() only works on the thread still inside the except block -
        # must capture here, not on the worker thread later.
        self._enqueue(logging.ERROR, f"{msg}\n{traceback.format_exc()}")

    def flush(self, timeout: float = 2.0) -> None:
        """Blocks until every entry queued so far has been written to disk."""
        self._caughtUp.clear()
        self._queue.put(None)
        self._caughtUp.wait(timeout)

    def stop(self) -> None:
        self.flush()
        self._active = False
        self._handler.close()

    def _enqueue(self, level: int, msg: str) -> None:
        if self._active:
            self._queue.put((level, msg))

    def _run(self) -> None:
        while True:
            item = self._queue.get()
            if item is None:
                # flush() checkpoint: everything queued ahead is now written.
                self._caughtUp.set()
                continue
            level, msg = item
            self._logger.log(level, msg)
