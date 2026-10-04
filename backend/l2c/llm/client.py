"""Local model client: one small question in, one validated JSON answer out.

Design rules (see docs/llm-pipeline-implementation.md):
- the model answers one tightly scoped question at a time (one or two elements);
- the answer is constrained by a JSON schema grammar, so it always parses;
- temperature 0, fixed seed, cache reset before each call: the same prompt gives the same answer;
- certainty is the model's own probability on its decision token, not a number it writes;
- every answer is cached on disk by a hash of (model, template version, prompt, schema).
"""

from __future__ import annotations

import glob
import hashlib
import json
import math
import os
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_MODEL = REPO_ROOT / "data/models/qwen2.5-7b-instruct-q4_k_m-00001-of-00002.gguf"
DEFAULT_CACHE = REPO_ROOT / "data/cache/llm"
TARGET_PROMPT_TOKENS = 400  # prompt builders aim below this
MAX_PROMPT_TOKENS = 600  # a prompt above this is a bug: the caller put too much in


class PromptTooLong(ValueError):
    pass


class BudgetExceeded(RuntimeError):
    pass


@dataclass(frozen=True)
class Answer:
    data: dict[str, Any]
    certainty: float | None  # probability the model gave its chosen decision token, 0..1
    cached: bool = False
    seconds: float = 0.0


@dataclass(frozen=True)
class Choice:
    """One option out of a fixed list, with the model's probability for it (renormalised over the
    options, from the raw first-token probabilities)."""

    option: str
    certainty: float | None
    cached: bool = False
    seconds: float = 0.0


def first_token_certainty(top: list[dict], chosen: str, options: list[str]) -> float | None:
    """P(chosen) / sum P(option) from the first generated token's raw alternatives. An option is
    credited with the alternatives that are a prefix of it (`uns` for `unsure`)."""
    mass: dict[str, float] = {}
    for alt in top:
        tok = alt["token"].strip().strip('"').lower()
        if not tok:
            continue
        for o in options:
            if o.startswith(tok):
                mass[o] = mass.get(o, 0.0) + math.exp(alt["logprob"])
    total = sum(mass.values())
    if total <= 0 or chosen not in mass:
        return None
    return round(mass[chosen] / total, 4)


class LlmClient(Protocol):
    model_id: str

    def ask(
        self, system: str, user: str, schema: dict, *, version: str, decision: str | None = None
    ) -> Answer: ...

    def choose(self, system: str, user: str, options: list[str], *, version: str) -> Choice: ...


@dataclass
class Budget:
    """Per-step limits so a slow model cannot stall a run. Callers catch BudgetExceeded and fall
    back to the rule result, flagged as unchecked."""

    max_calls: int | None = None
    max_seconds: float | None = None
    calls: int = 0
    seconds: float = 0.0

    def check(self) -> None:
        if self.max_calls is not None and self.calls >= self.max_calls:
            raise BudgetExceeded(f"call budget {self.max_calls} reached")
        if self.max_seconds is not None and self.seconds >= self.max_seconds:
            raise BudgetExceeded(f"time budget {self.max_seconds}s reached")

    def charge(self, seconds: float) -> None:
        self.calls += 1
        self.seconds += seconds


def prompt_key(model_id: str, version: str, system: str, user: str, schema: dict) -> str:
    raw = json.dumps([model_id, version, system, user, schema], sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


class DiskCache:
    def __init__(self, root: Path | None) -> None:
        self.root = root
        if root is not None:
            root.mkdir(parents=True, exist_ok=True)

    def get(self, key: str) -> dict | None:
        if self.root is None:
            return None
        path = self.root / f"{key}.json"
        if not path.exists():
            return None
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None

    def put(self, key: str, value: dict) -> None:
        if self.root is not None:
            (self.root / f"{key}.json").write_text(
                json.dumps(value, ensure_ascii=False), encoding="utf-8"
            )


def _add_cuda_to_path() -> None:
    """On Windows the CUDA libraries from the `nvidia-*` pip packages must be on PATH before
    llama_cpp is imported (os.add_dll_directory alone is not enough for its loader)."""
    base = os.path.join(sys.prefix, "Lib", "site-packages", "nvidia")
    for d in glob.glob(os.path.join(base, "*", "bin")):
        os.environ["PATH"] = d + os.pathsep + os.environ.get("PATH", "")
        if hasattr(os, "add_dll_directory"):
            os.add_dll_directory(d)


def _decision_certainty(choice: dict, options: list[str]) -> float | None:
    """Probability of the chosen option among the options, from the token log-probabilities of
    the answer token. None when the runtime gave no probabilities."""
    content = (choice.get("logprobs") or {}).get("content") or []
    for tok in content:
        text = tok.get("token", "").strip().strip('"').lower()
        if not text or text in {"{", "}", ":", "answer"}:
            continue
        alts = {
            a["token"].strip().strip('"').lower(): a["logprob"] for a in tok.get("top_logprobs", [])
        }
        alts[text] = tok["logprob"]
        probs = {
            o: math.exp(lp) for t, lp in alts.items() for o in options if o.startswith(t) and t
        }
        if text in {o for o in options} or any(o.startswith(text) for o in options):
            total = sum(probs.values())
            own = math.exp(tok["logprob"])
            return round(own / total, 4) if total > 0 else None
    return None


@dataclass
class LlamaClient:
    model_path: Path = DEFAULT_MODEL
    n_gpu_layers: int = 24
    n_ctx: int = 1536
    n_threads: int = 8
    seed: int = 7
    cache_dir: Path | None = DEFAULT_CACHE
    budget: Budget = field(default_factory=Budget)
    _llm: Any = None
    _cache: DiskCache | None = None

    def __post_init__(self) -> None:
        size = self.model_path.stat().st_size if self.model_path.exists() else 0
        self.model_id = f"{self.model_path.name}:{size}:gpu{self.n_gpu_layers}"
        self._cache = DiskCache(self.cache_dir)

    def _load(self):
        if self._llm is None:
            _add_cuda_to_path()
            from llama_cpp import Llama

            self._llm = Llama(
                model_path=str(self.model_path),
                n_ctx=self.n_ctx,
                n_gpu_layers=self.n_gpu_layers,
                n_threads=self.n_threads,
                seed=self.seed,
                verbose=False,
                logits_all=True,
            )
        return self._llm

    def choose(self, system: str, user: str, options: list[str], *, version: str) -> Choice:
        schema = {"options": options}
        key = prompt_key(self.model_id, version, system, user, schema)
        hit = self._cache.get(key) if self._cache else None
        if hit is not None:
            return Choice(hit["option"], hit.get("certainty"), cached=True)
        self.budget.check()
        llm = self._load()
        n = len(llm.tokenize((system + user).encode("utf-8")))
        if n > MAX_PROMPT_TOKENS:
            raise PromptTooLong(f"prompt is {n} tokens, limit {MAX_PROMPT_TOKENS}")
        from llama_cpp import LlamaGrammar

        grammar = LlamaGrammar.from_string("root ::= " + " | ".join(f'"{o}"' for o in options))
        llm.reset()
        t0 = time.time()
        r = llm.create_chat_completion(
            messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
            temperature=0,
            seed=self.seed,
            max_tokens=6,
            grammar=grammar,
            logprobs=True,
            top_logprobs=10,
        )
        dt = time.time() - t0
        self.budget.charge(dt)
        choice = r["choices"][0]
        option = choice["message"]["content"].strip().lower()
        content = (choice.get("logprobs") or {}).get("content") or []
        certainty = (
            first_token_certainty(content[0]["top_logprobs"], option, options) if content else None
        )
        if self._cache:
            self._cache.put(key, {"option": option, "certainty": certainty})
        return Choice(option, certainty, cached=False, seconds=dt)

    def token_count(self, text: str) -> int:
        return len(self._load().tokenize(text.encode("utf-8")))

    def ask(
        self, system: str, user: str, schema: dict, *, version: str, decision: str | None = None
    ) -> Answer:
        key = prompt_key(self.model_id, version, system, user, schema)
        hit = self._cache.get(key) if self._cache else None
        if hit is not None:
            return Answer(hit["data"], hit.get("certainty"), cached=True)
        self.budget.check()
        llm = self._load()
        n = len(llm.tokenize((system + user).encode("utf-8")))
        if n > MAX_PROMPT_TOKENS:
            raise PromptTooLong(f"prompt is {n} tokens, limit {MAX_PROMPT_TOKENS}")
        from llama_cpp import LlamaGrammar

        grammar = LlamaGrammar.from_json_schema(json.dumps(schema))
        llm.reset()
        t0 = time.time()
        r = llm.create_chat_completion(
            messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
            temperature=0,
            seed=self.seed,
            max_tokens=120,
            grammar=grammar,
            logprobs=True,
            top_logprobs=5,
        )
        dt = time.time() - t0
        self.budget.charge(dt)
        choice = r["choices"][0]
        data = json.loads(choice["message"]["content"])
        options = []
        if decision:
            prop = schema.get("properties", {}).get(decision, {})
            options = [str(o).lower() for o in prop.get("enum", [])]
        certainty = _decision_certainty(choice, options) if options else None
        if self._cache:
            self._cache.put(key, {"data": data, "certainty": certainty})
        return Answer(data, certainty, cached=False, seconds=dt)


@dataclass
class FakeClient:
    """Deterministic stand-in for tests and for runs without a model. `rule` receives the user
    prompt and returns the answer dict; certainty is fixed."""

    rule: Any = None
    certainty: float = 0.5
    model_id: str = "fake"
    calls: list[str] = field(default_factory=list)
    budget: Budget = field(default_factory=Budget)

    def ask(
        self, system: str, user: str, schema: dict, *, version: str, decision: str | None = None
    ) -> Answer:
        self.budget.check()
        self.calls.append(user)
        self.budget.charge(0.0)
        if len(user) // 3 > MAX_PROMPT_TOKENS:
            raise PromptTooLong(f"prompt is about {len(user) // 3} tokens")
        data = (
            self.rule(user)
            if self.rule
            else {k: _default(v) for k, v in schema.get("properties", {}).items()}
        )
        return Answer(data, self.certainty)

    def choose(self, system: str, user: str, options: list[str], *, version: str) -> Choice:
        self.budget.check()
        self.calls.append(user)
        self.budget.charge(0.0)
        if len(user) // 3 > MAX_PROMPT_TOKENS:
            raise PromptTooLong(f"prompt is about {len(user) // 3} tokens")
        pick = self.rule(user) if self.rule else options[-1]
        return Choice(pick, self.certainty)


def _default(prop: dict) -> Any:
    if "enum" in prop:
        return prop["enum"][-1]
    return {"string": "", "boolean": False, "number": 0, "integer": 0}.get(prop.get("type"), None)


@dataclass
class NeutralClient:
    """No model and no opinion: every question goes unanswered, so no cost moves, no pair is confirmed
    and no sentence is written. The baseline for measuring what the model adds."""

    model_id: str = "none"

    def choose(self, system: str, user: str, options: list[str], *, version: str) -> Choice:
        return Choice(None, None)  # type: ignore[arg-type]

    def ask(
        self, system: str, user: str, schema: dict, *, version: str, decision: str | None = None
    ) -> Answer:
        return Answer({}, None)


def make_client(kind: str = "auto", **kw) -> LlmClient:
    """`server` runs the local llama.cpp server (parallel questions); `llama` loads the model in this
    process (one question at a time); `fake` never calls a model; `none` answers nothing (see
    NeutralClient). `auto` picks the server when its binary and model are installed, else the
    in-process model, else the fake."""
    if kind == "fake":
        return FakeClient(**kw)
    if kind == "none":
        return NeutralClient()
    from l2c.llm import server as S

    if kind == "server" or (kind == "auto" and S.SERVER_EXE.exists() and S.MODEL.exists()):
        c = S.ServerClient()
        c.start(log=REPO_ROOT / "data" / "scratch" / "server.log")
        return c
    path = Path(kw.get("model_path", DEFAULT_MODEL))
    if kind == "llama" or path.exists():
        return LlamaClient(**kw)
    return FakeClient()


def choose_many(
    client, system: str, users: list[str], options: list[str], *, version: str
) -> list[Choice]:
    """Answers to many one-element questions. A client that can run them in parallel (the llama.cpp
    server) does; any other client answers them one after another."""
    if not users:
        return []
    many = getattr(client, "choose_many", None)
    if many is not None:
        return many(system, users, options, version=version)
    return [client.choose(system, u, options, version=version) for u in users]


def ask_many(client, system: str, users: list[str], schema: dict, *, version: str) -> list[Answer]:
    if not users:
        return []
    many = getattr(client, "ask_many", None)
    if many is not None:
        return many(system, users, schema, version=version)
    return [client.ask(system, u, schema, version=version) for u in users]
