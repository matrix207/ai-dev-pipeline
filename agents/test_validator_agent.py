"""Run local validation commands and return structured results."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from typing import Any, Mapping

from agents import BaseAgent


class TestValidatorAgent(BaseAgent):
    """Execute local validation commands without external services."""

    __test__ = False

    def __init__(self, name: str = "test-validator") -> None:
        super().__init__(name)

    def handle(self, payload: dict[str, Any]) -> Mapping[str, Any]:
        repo_root = Path(payload.get("repo_root", ".")).resolve()
        commands = payload.get("commands") or [[sys.executable, "-m", "pytest", "-q"]]
        timeout_seconds = int(payload.get("timeout_seconds", 120))

        results: list[dict[str, Any]] = []
        for command in commands:
            normalized = self._normalize_command(command)
            completed = subprocess.run(
                normalized,
                cwd=repo_root,
                text=True,
                capture_output=True,
                timeout=timeout_seconds,
                check=False,
            )
            results.append(
                {
                    "command": normalized,
                    "returncode": completed.returncode,
                    "passed": completed.returncode == 0,
                    "stdout": completed.stdout[-4000:],
                    "stderr": completed.stderr[-4000:],
                }
            )

        passed = all(result["passed"] for result in results)
        return {
            "status": "passed" if passed else "failed",
            "passed": passed,
            "results": results,
        }

    def _normalize_command(self, command: Any) -> list[str]:
        if isinstance(command, str):
            return command.split()
        if isinstance(command, list) and all(isinstance(part, str) for part in command):
            return command
        raise TypeError("Validation command must be a string or list of strings.")
