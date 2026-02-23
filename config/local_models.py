"""Local model management via Ollama.

Handles model availability checks, automatic pulling, GPU health,
and warm-up to avoid cold-start latency on the first coding ticket.

Usage::

    from config.local_models import get_local_model_manager

    mgr = get_local_model_manager()
    ready = await mgr.ensure_model_available("qwen2.5-coder:32b")
    if ready:
        await mgr.warm_up_model("qwen2.5-coder:32b")
"""

from __future__ import annotations

import asyncio
import os
import shutil
import time

import structlog

log = structlog.get_logger().bind(component="local_models")

_DEFAULT_MODEL = "qwen2.5-coder:32b"


class LocalModelManager:
    """Manage local LLM models served by Ollama.

    Provides helpers to check availability, pull models, inspect metadata,
    probe GPU health, and warm up the model into VRAM before the first
    real inference request.
    """

    def __init__(
        self,
        ollama_url: str | None = None,
    ) -> None:
        self._url = ollama_url or os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434")

    # ------------------------------------------------------------------
    # Model availability
    # ------------------------------------------------------------------

    async def ensure_model_available(
        self,
        model_name: str = _DEFAULT_MODEL,
    ) -> bool:
        """Check whether *model_name* is pulled; pull it if not.

        Returns ``True`` when the model is ready for inference,
        ``False`` if Ollama is unreachable or the pull failed.
        """
        import httpx

        try:
            async with httpx.AsyncClient(
                base_url=self._url,
                timeout=10.0,
            ) as client:
                # 1. Check if already available
                resp = await client.get("/api/tags")
                if resp.status_code != 200:
                    log.warning(
                        "ollama /api/tags returned non-200",
                        status=resp.status_code,
                    )
                    return False

                models = resp.json().get("models", [])
                names = [m.get("name", "") for m in models]
                if any(model_name in n for n in names):
                    log.info("local model already available", model=model_name)
                    return True

                # 2. Trigger a pull
                log.info("pulling local model", model=model_name)
                return await self._pull_model(client, model_name)

        except Exception as exc:
            log.warning(
                "ollama unreachable",
                url=self._url,
                error=str(exc)[:200],
            )
            return False

    async def _pull_model(
        self,
        client: object,
        model_name: str,
    ) -> bool:
        """Stream a model pull and log progress."""
        import httpx

        assert isinstance(client, httpx.AsyncClient)
        try:
            async with client.stream(
                "POST",
                "/api/pull",
                json={"name": model_name},
                timeout=httpx.Timeout(connect=30.0, read=600.0, write=30.0, pool=30.0),
            ) as resp:
                if resp.status_code != 200:
                    log.error("pull request failed", status=resp.status_code)
                    return False

                last_log_time = time.monotonic()
                async for line in resp.aiter_lines():
                    # Ollama streams JSON objects, one per line
                    import json

                    try:
                        data = json.loads(line)
                    except (json.JSONDecodeError, ValueError):
                        continue

                    status = data.get("status", "")
                    completed = data.get("completed", 0)
                    total = data.get("total", 0)

                    # Log progress at most every 5 seconds
                    now = time.monotonic()
                    if now - last_log_time >= 5.0 or status == "success":
                        pct = f"{completed / total * 100:.0f}%" if total > 0 else "..."
                        log.info(
                            "pull progress",
                            model=model_name,
                            status=status,
                            progress=pct,
                        )
                        last_log_time = now

                    if status == "success":
                        log.info("model pull complete", model=model_name)
                        return True

        except Exception as exc:
            log.error("model pull failed", model=model_name, error=str(exc)[:200])

        return False

    # ------------------------------------------------------------------
    # Model metadata
    # ------------------------------------------------------------------

    async def get_model_info(self, model_name: str = _DEFAULT_MODEL) -> dict:
        """Return model metadata from Ollama.

        Keys include ``parameter_count``, ``quantization``,
        ``context_window``, and ``size_bytes``.
        Returns an empty dict on failure.
        """
        import httpx

        try:
            async with httpx.AsyncClient(
                base_url=self._url,
                timeout=10.0,
            ) as client:
                resp = await client.post(
                    "/api/show",
                    json={"name": model_name},
                )
                if resp.status_code != 200:
                    return {}

                data = resp.json()
                details = data.get("details", {})
                model_info = data.get("model_info", {})

                # Extract relevant fields
                param_count = details.get("parameter_size", "")
                quant = details.get("quantization_level", "")
                family = details.get("family", "")
                ctx_length = 0
                for key, val in model_info.items():
                    if "context_length" in key:
                        ctx_length = val
                        break

                return {
                    "name": model_name,
                    "parameter_count": param_count,
                    "quantization": quant,
                    "family": family,
                    "context_window": ctx_length,
                    "size_bytes": data.get("size", 0),
                    "format": details.get("format", ""),
                }

        except Exception as exc:
            log.debug("get_model_info failed", error=str(exc)[:200])
            return {}

    # ------------------------------------------------------------------
    # Health check
    # ------------------------------------------------------------------

    async def health_check(self) -> dict:
        """Probe Ollama and GPU status.

        Returns a status dict suitable for the dashboard::

            {
                "ollama_running": bool,
                "ollama_url": str,
                "gpu_available": bool,
                "gpu_name": str,
                "vram_total_mb": int,
                "vram_used_mb": int,
                "vram_free_mb": int,
                "models_loaded": list[str],
            }
        """
        result: dict = {
            "ollama_running": False,
            "ollama_url": self._url,
            "gpu_available": False,
            "gpu_name": "",
            "vram_total_mb": 0,
            "vram_used_mb": 0,
            "vram_free_mb": 0,
            "models_loaded": [],
        }

        # Check Ollama
        import httpx

        try:
            async with httpx.AsyncClient(
                base_url=self._url,
                timeout=5.0,
            ) as client:
                resp = await client.get("/api/tags")
                if resp.status_code == 200:
                    result["ollama_running"] = True
                    models = resp.json().get("models", [])
                    result["models_loaded"] = [m.get("name", "") for m in models]
        except Exception:
            pass

        # Check GPU via nvidia-smi
        gpu_info = await self._check_gpu()
        result.update(gpu_info)

        return result

    @staticmethod
    async def _check_gpu() -> dict:
        """Query nvidia-smi for GPU info. Returns empty fields on failure."""
        info: dict = {
            "gpu_available": False,
            "gpu_name": "",
            "vram_total_mb": 0,
            "vram_used_mb": 0,
            "vram_free_mb": 0,
        }

        if not shutil.which("nvidia-smi"):
            return info

        try:
            proc = await asyncio.create_subprocess_exec(
                "nvidia-smi",
                "--query-gpu=name,memory.total,memory.used,memory.free",
                "--format=csv,noheader,nounits",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=10)
            line = stdout.decode().strip().split("\n")[0]
            parts = [p.strip() for p in line.split(",")]
            if len(parts) >= 4:
                info["gpu_available"] = True
                info["gpu_name"] = parts[0]
                info["vram_total_mb"] = int(float(parts[1]))
                info["vram_used_mb"] = int(float(parts[2]))
                info["vram_free_mb"] = int(float(parts[3]))
        except Exception:
            pass

        return info

    # ------------------------------------------------------------------
    # Warm-up
    # ------------------------------------------------------------------

    async def warm_up_model(self, model_name: str = _DEFAULT_MODEL) -> None:
        """Send a small prompt to load the model into VRAM.

        The first real inference is slow because Ollama must load model
        weights from disk.  Calling this at startup eliminates that
        cold-start penalty for the first coding ticket.
        """
        import httpx

        log.info("warming up local model", model=model_name)
        start = time.monotonic()

        try:
            async with httpx.AsyncClient(
                base_url=self._url,
                timeout=httpx.Timeout(connect=10.0, read=120.0, write=10.0, pool=10.0),
            ) as client:
                resp = await client.post(
                    "/api/generate",
                    json={
                        "model": model_name,
                        "prompt": "Hello",
                        "stream": False,
                        "options": {"num_predict": 1},
                    },
                )
                elapsed = time.monotonic() - start

                if resp.status_code == 200:
                    log.info(
                        "model warm-up complete",
                        model=model_name,
                        elapsed_s=round(elapsed, 1),
                    )
                else:
                    log.warning(
                        "model warm-up returned non-200",
                        model=model_name,
                        status=resp.status_code,
                    )
        except Exception as exc:
            elapsed = time.monotonic() - start
            log.warning(
                "model warm-up failed",
                model=model_name,
                elapsed_s=round(elapsed, 1),
                error=str(exc)[:200],
            )


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

_manager: LocalModelManager | None = None


def get_local_model_manager(
    ollama_url: str | None = None,
) -> LocalModelManager:
    """Return the process-wide LocalModelManager singleton."""
    global _manager
    if _manager is None:
        _manager = LocalModelManager(ollama_url)
    return _manager
