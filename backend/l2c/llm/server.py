"""Local llama.cpp server client: many short questions answered in parallel.

`llama-server` (open source, run on 127.0.0.1 only) batches requests from several slots and keeps the
instruction prefix of each slot in memory, so a question after the first costs only its new tokens.
The same questions sent one at a time through the Python wrapper cost about 1 s each; here about
10 to 15 per second are answered on the development GPU.

Everything stays on this machine. No question or answer leaves it.
"""

from __future__ import annotations

import atexit
import json
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from urllib.error import URLError
from urllib.request import Request, urlopen

from l2c.llm.client import (
    MAX_PROMPT_TOKENS,
    Answer,
    Budget,
    Choice,
    first_token_certainty,
)

REPO = Path(__file__).resolve().parents[3]
SERVER_EXE = REPO / "data" / "bin" / "llama" / "llama-server.exe"
MODEL = REPO / "data" / "models" / "Qwen3-4B-Instruct-2507-Q4_K_M.gguf"
PORT = 8089
CHAT = "<|im_start|>system\n{system}<|im_end|>\n<|im_start|>user\n{user}<|im_end|>\n<|im_start|>assistant\n"


def _post(url: str, body: dict, timeout: float = 120.0) -> dict:
    req = Request(url, json.dumps(body).encode("utf-8"), {"Content-Type": "application/json"})
    return json.load(urlopen(req, timeout=timeout))


def server_up(port: int = PORT) -> bool:
    try:
        return (
            json.load(urlopen(f"http://127.0.0.1:{port}/health", timeout=1)).get("status") == "ok"
        )
    except (URLError, OSError, ValueError):
        return False


@dataclass
class ServerClient:
    port: int = PORT
    slots: int = 8
    ctx_per_slot: int = 1024
    seed: int = 7
    workers: int = 8
    budget: Budget = field(default_factory=Budget)
    model_id: str = "qwen3-4b-instruct-2507-q4_k_m"
    _proc: subprocess.Popen | None = None

    def start(self, exe: Path = SERVER_EXE, model: Path = MODEL, log: Path | None = None) -> None:
        """Start the server if none answers on the port, and wait until it is ready."""
        if server_up(self.port):
            return
        out = open(log, "wb") if log else subprocess.DEVNULL  # noqa: SIM115
        self._proc = subprocess.Popen(
            [
                str(exe),
                "-m",
                str(model),
                "-ngl",
                "99",
                "-c",
                str(self.slots * self.ctx_per_slot),
                "-np",
                str(self.slots),
                "--host",
                "127.0.0.1",
                "--port",
                str(self.port),
                "-fa",
                "on",
                "--no-webui",
                "--seed",
                str(self.seed),
            ],
            stdout=out,
            stderr=subprocess.STDOUT,
            cwd=str(exe.parent),
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        atexit.register(self.stop)
        for _ in range(240):
            if server_up(self.port):
                return
            if self._proc.poll() is not None:
                raise RuntimeError("llama-server exited while starting")
            time.sleep(0.5)
        raise RuntimeError("llama-server did not become ready")

    def stop(self) -> None:
        if self._proc is not None and self._proc.poll() is None:
            self._proc.terminate()
            try:
                self._proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                self._proc.kill()
        self._proc = None

    # ------------------------------------------------------------------ one question
    def _complete(self, system: str, user: str, extra: dict) -> dict:
        if (len(system) + len(user)) // 3 > MAX_PROMPT_TOKENS:
            from l2c.llm.client import PromptTooLong

            raise PromptTooLong(f"prompt is about {(len(system) + len(user)) // 3} tokens")
        body = {
            "prompt": CHAT.format(system=system, user=user),
            "temperature": 0,
            "seed": self.seed,
            "cache_prompt": True,
            **extra,
        }
        t = time.time()
        r = _post(f"http://127.0.0.1:{self.port}/completion", body)
        self.budget.charge(time.time() - t)
        return r

    def choose(self, system: str, user: str, options: list[str], *, version: str = "") -> Choice:
        r = self._complete(
            system,
            user,
            {
                "n_predict": 2,
                "n_probs": 8,
                "grammar": "root ::= " + " | ".join(f'"{o}"' for o in options),
            },
        )
        option = r["content"].strip().lower()
        probs = r.get("completion_probabilities") or []
        certainty = (
            first_token_certainty(probs[0]["top_logprobs"], option, options) if probs else None
        )
        return Choice(option, certainty)

    def ask(
        self,
        system: str,
        user: str,
        schema: dict,
        *,
        version: str = "",
        decision: str | None = None,
    ) -> Answer:
        r = self._complete(system, user, {"n_predict": 120, "json_schema": schema})
        return Answer(json.loads(r["content"]), None)

    # ------------------------------------------------------------------ many questions at once
    def choose_many(
        self, system: str, users: list[str], options: list[str], *, version: str = ""
    ) -> list[Choice]:
        """Answers in the order of `users`. The questions run in parallel slots of the server."""
        if not users:
            return []
        with ThreadPoolExecutor(min(self.workers, len(users))) as pool:
            return list(pool.map(lambda u: self.choose(system, u, options, version=version), users))

    def ask_many(
        self, system: str, users: list[str], schema: dict, *, version: str = ""
    ) -> list[Answer]:
        if not users:
            return []
        with ThreadPoolExecutor(min(self.workers, len(users))) as pool:
            return list(pool.map(lambda u: self.ask(system, u, schema, version=version), users))
