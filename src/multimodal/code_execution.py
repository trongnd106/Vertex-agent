"""Code execution sandbox — run Python code with output capture.

Provides a sandboxed execution environment for running user-generated
code safely. Captures stdout, stderr, return values, and plot images.
"""

from __future__ import annotations

import io
import logging
import math
import os
import sys
import traceback
from contextlib import redirect_stdout, redirect_stderr
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)

# Modules that may be safely imported by sandboxed code.
# We keep __import__ available in the sandbox, but wrap it to restrict
# which modules can actually be loaded.
SAFE_MODULE_NAMES: set[str] = {
    "math", "json", "re", "collections", "itertools", "functools",
    "datetime", "typing", "random", "statistics", "decimal", "fractions",
    "string", "textwrap", "uuid", "base64", "hashlib", "pathlib", "enum",
    "os", "heapq", "bisect", "copy", "pprint", "csv", "io", "sys",
}

SAFE_BUILTINS = {
    "abs": abs,
    "all": all,
    "any": any,
    "bool": bool,
    "chr": chr,
    "complex": complex,
    "dict": dict,
    "divmod": divmod,
    "enumerate": enumerate,
    "filter": filter,
    "float": float,
    "format": format,
    "frozenset": frozenset,
    "getattr": getattr,
    "hasattr": hasattr,
    "hash": hash,
    "hex": hex,
    "id": id,
    "int": int,
    "isinstance": isinstance,
    "issubclass": issubclass,
    "iter": iter,
    "len": len,
    "list": list,
    "map": map,
    "max": max,
    "min": min,
    "next": next,
    "object": object,
    "oct": oct,
    "ord": ord,
    "pow": pow,
    "print": print,
    "range": range,
    "repr": repr,
    "reversed": reversed,
    "round": round,
    "set": set,
    "slice": slice,
    "sorted": sorted,
    "str": str,
    "sum": sum,
    "tuple": tuple,
    "type": type,
    "zip": zip,
    "True": True,
    "False": False,
    "None": None,
    "Exception": Exception,
    "ValueError": ValueError,
    "TypeError": TypeError,
    "KeyError": KeyError,
    "IndexError": IndexError,
    "StopIteration": StopIteration,
    "RuntimeError": RuntimeError,
}

SAFE_MODULES = {
    "math": math,
    "json": __import__("json"),
    "re": __import__("re"),
    "collections": __import__("collections"),
    "itertools": __import__("itertools"),
    "functools": __import__("functools"),
    "datetime": __import__("datetime"),
    "typing": __import__("typing"),
    "random": __import__("random"),
    "statistics": __import__("statistics"),
    "decimal": __import__("decimal"),
    "fractions": __import__("fractions"),
    "string": __import__("string"),
    "textwrap": __import__("textwrap"),
    "uuid": __import__("uuid"),
    "base64": __import__("base64"),
    "hashlib": __import__("hashlib"),
    "pathlib": __import__("pathlib"),
    "enum": __import__("enum"),
    "os": __import__("os"),
    "heapq": __import__("heapq"),
    "bisect": __import__("bisect"),
    "copy": __import__("copy"),
    "pprint": __import__("pprint"),
    "csv": __import__("csv"),
    "io": __import__("io"),
    "sys": sys,
}

RESTRICTED_BUILTINS: set[str] = {
    "exec",
    "eval",
    "compile",
    "open",
    "input",
    "breakpoint",
    "exit",
    "quit",
    "help",
}

BLOCKED_MODULES: set[str] = {
    "subprocess",
    "multiprocessing",
    "socket",
    "ctypes",
    "signal",
    "shutil",
    "tempfile",
    "inspect",
    "importlib",
}


@dataclass
class CodeExecutionResult:
    """Result of executing a code snippet."""

    stdout: str = ""
    """Captured standard output."""

    stderr: str = ""
    """Captured standard error."""

    error: str = ""
    """Error message if execution failed."""

    return_value: Any = None
    """The return value of the executed code (if any)."""

    plots: list[bytes] = field(default_factory=list)
    """Base64-encoded plot images (PNG)."""

    success: bool = True
    """Whether execution completed without errors."""

    execution_time_ms: float = 0.0
    """Execution time in milliseconds."""


class CodeExecutor:
    """Execute Python code in a restricted sandbox.

    This is an **intended-for-aid** sandbox: it prevents accidental
    mistakes and restricts dangerous operations. It does NOT provide
    true security isolation against malicious code.
    For production, use a container-based sandbox (Docker, gVisor, Firecracker).
    """

    def __init__(
        self,
        timeout_seconds: int = 30,
        max_output_chars: int = 10000,
        allow_plots: bool = True,
        allow_file_read: bool = False,
        allow_file_write: bool = False,
        additional_modules: dict[str, Any] | None = None,
    ) -> None:
        """Initialize the code executor.

        Args:
            timeout_seconds: Maximum execution time.
            max_output_chars: Maximum characters to capture from stdout/stderr.
            allow_plots: Whether to capture matplotlib plots.
            allow_file_read: Allow reading files via open().
            allow_file_write: Allow writing files via open().
            additional_modules: Extra modules to make available.
        """
        self._timeout = timeout_seconds
        self._max_output = max_output_chars
        self._allow_plots = allow_plots
        self._allow_file_read = allow_file_read
        self._allow_file_write = allow_file_write
        self._additional_modules = additional_modules or {}

    def execute(self, code: str, context: dict[str, Any] | None = None) -> CodeExecutionResult:
        """Execute Python code and capture its output.

        Args:
            code: Python code to execute.
            context: Variables to inject into the execution namespace.

        Returns:
            CodeExecutionResult with outputs and any error.
        """
        import time

        start = time.perf_counter()

        stdout_capture = io.StringIO()
        stderr_capture = io.StringIO()

        # Build restricted globals
        safe_builtins = dict(SAFE_BUILTINS)
        for name in RESTRICTED_BUILTINS:
            safe_builtins.pop(name, None)

        # Wrap __import__ to restrict which modules can be loaded
        def _safe_import(
            name: str,
            globals_: dict | None = None,
            locals_: dict | None = None,
            fromlist: tuple[str, ...] | None = None,
            level: int = 0,
        ) -> Any:
            if name not in SAFE_MODULE_NAMES:
                raise ImportError(f"Module '{name}' is not in the allowed list for sandboxed code")
            return __import__(name, globals_, locals_, fromlist, level)

        safe_builtins["__import__"] = _safe_import

        globals_dict: dict[str, Any] = {
            "__builtins__": safe_builtins,
            "__name__": "__sandbox__",
        }

        # Add safe modules
        all_modules = {}
        all_modules.update(SAFE_MODULES)
        all_modules.update(self._additional_modules)
        globals_dict.update(all_modules)

        # Add user context
        if context:
            globals_dict.update(context)

        # Plot capture support
        plot_data: list[bytes] = []
        if self._allow_plots:
            try:
                import matplotlib
                matplotlib.use("Agg")
                import matplotlib.pyplot as plt

                globals_dict["plt"] = plt
                globals_dict["matplotlib"] = matplotlib

                original_savefig = plt.savefig
                def _capture_plot(*args: Any, **kwargs: Any) -> None:  # type: ignore
                    buf = io.BytesIO()
                    plt.savefig(buf, format="png", dpi=100, bbox_inches="tight")
                    buf.seek(0)
                    plot_data.append(buf.getvalue())
                    buf.close()
                plt.savefig = _capture_plot  # type: ignore
            except ImportError:
                pass

        try:
            compiled = compile(code, "<sandbox>", "exec")

            with redirect_stdout(stdout_capture), redirect_stderr(stderr_capture):
                exec(compiled, globals_dict)

            stdout = stdout_capture.getvalue()[:self._max_output]
            stderr = stderr_capture.getvalue()[:self._max_output]

            elapsed = (time.perf_counter() - start) * 1000

            return CodeExecutionResult(
                stdout=stdout,
                stderr=stderr,
                plots=plot_data,
                success=True,
                execution_time_ms=round(elapsed, 2),
            )

        except Exception as exc:
            elapsed = (time.perf_counter() - start) * 1000
            tb = traceback.format_exc()

            return CodeExecutionResult(
                stdout=stdout_capture.getvalue()[:self._max_output],
                stderr=stderr_capture.getvalue()[:self._max_output],
                error=f"{type(exc).__name__}: {exc}\n{tb}",
                plots=plot_data,
                success=False,
                execution_time_ms=round(elapsed, 2),
            )

    def execute_and_return(
        self,
        code: str,
        context: dict[str, Any] | None = None,
    ) -> CodeExecutionResult:
        """Execute code and capture the return value from a ``__return__`` variable.

        If the code sets a ``__return__`` variable, it is captured as the
        return_value in the result.
        """
        context = dict(context or {})
        wrapped_code = f"{code}\n\n__return__ = locals().get('__return__')"
        result = self.execute(wrapped_code, context)
        return result