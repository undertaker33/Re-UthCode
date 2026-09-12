"""Cancellable private workers for bounded PDFium operations.

The normal Application process owns the Tool contract and Session assets.  A
short-lived worker owns only one PDF operation, so cancelling a native PDFium
call can terminate the worker instead of waiting for an asyncio task or a
thread that is still inside the native library.  In development the worker is
started through this Integration module; a frozen PyInstaller runtime is
started directly with its own flag and never receives ``-m`` or ``-c``
arguments.
"""

from __future__ import annotations

import asyncio
import base64
import binascii
import contextlib
import io
import json
import sys
from collections.abc import Mapping
from typing import Any

from uthcode.core.provider import CancellationToken


PDF_WORKER_FLAG = "--uthcode-pdf-worker"
_WORKER_TIMEOUT_SECONDS = 30.0
_WORKER_MAX_PROTOCOL_BYTES = 64 * 1024 * 1024
_worker_lock: asyncio.Lock | None = None


class PdfWorkerError(RuntimeError):
    """Controlled failure returned by the private PDF worker boundary."""

    def __init__(self, message: str, *, kind: str = "unavailable") -> None:
        self.kind = kind
        super().__init__(message)


class _WorkerOutputLimitExceeded(RuntimeError):
    """Internal signal raised while a worker is still writing too much data."""


def pdf_worker_command() -> tuple[str, ...]:
    """Return a launch command valid in both source and frozen runtimes."""

    executable = sys.executable
    if getattr(sys, "frozen", False):
        # A PyInstaller executable is an application entry point, not a
        # generic Python interpreter.  Its own flag is the private worker
        # entry, so the bundled path never relies on ``-m`` or ``-c``.
        return (executable, PDF_WORKER_FLAG)
    return (executable, "-m", "uthcode.integrations.pdf_worker", PDF_WORKER_FLAG)


def _lock() -> asyncio.Lock:
    global _worker_lock
    if _worker_lock is None:
        _worker_lock = asyncio.Lock()
    return _worker_lock


async def run_pdf_worker(
    request: Mapping[str, object],
    *,
    cancellation: CancellationToken,
    max_output_bytes: int,
) -> dict[str, object]:
    """Run one bounded PDF operation and terminate it on cancellation."""

    if cancellation.cancelled:
        raise PdfWorkerError("Error: document read cancelled", kind="cancelled")
    try:
        request_payload = dict(request)
        request_payload["max_output_bytes"] = max_output_bytes
        payload = (json.dumps(request_payload, ensure_ascii=False, separators=(",", ":")) + "\n").encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise PdfWorkerError("Error: PDF worker request is invalid", kind="invalid_input") from exc

    async with _lock():
        if cancellation.cancelled:
            raise PdfWorkerError("Error: document read cancelled", kind="cancelled")
        try:
            process = await asyncio.create_subprocess_exec(
                *pdf_worker_command(),
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
        except (OSError, ValueError) as exc:
            raise PdfWorkerError("Error: PDF reader worker is unavailable") from exc

        protocol_limit = _protocol_limit(max_output_bytes)
        stdout_task = asyncio.create_task(
            _read_limited(process.stdout, protocol_limit)
        )
        stderr_task = asyncio.create_task(
            _read_limited(process.stderr, min(_WORKER_MAX_PROTOCOL_BYTES, 1 * 1024 * 1024))
        )
        wait_task = asyncio.create_task(process.wait())
        started = asyncio.get_running_loop().time()
        drain_task: asyncio.Task[None] | None = None
        try:
            if process.stdin is None:
                raise PdfWorkerError("Error: PDF worker stdin is unavailable")
            process.stdin.write(payload)
            drain_task = asyncio.create_task(process.stdin.drain())
            while not drain_task.done():
                if cancellation.cancelled:
                    await _terminate(process)
                    raise PdfWorkerError("Error: document read cancelled", kind="cancelled")
                remaining = _WORKER_TIMEOUT_SECONDS - (
                    asyncio.get_running_loop().time() - started
                )
                if remaining <= 0:
                    await _terminate(process)
                    raise PdfWorkerError("Error: PDF read timed out", kind="resource_limit")
                try:
                    await asyncio.wait_for(
                        asyncio.shield(drain_task),
                        min(0.05, remaining),
                    )
                except asyncio.TimeoutError:
                    continue
            drain_task.result()
            process.stdin.close()
            while True:
                if cancellation.cancelled:
                    await _terminate(process)
                    raise PdfWorkerError("Error: document read cancelled", kind="cancelled")
                if asyncio.get_running_loop().time() - started > _WORKER_TIMEOUT_SECONDS:
                    await _terminate(process)
                    raise PdfWorkerError("Error: PDF read timed out", kind="resource_limit")
                done, _pending = await asyncio.wait(
                    (stdout_task, stderr_task, wait_task),
                    timeout=0.05,
                    return_when=asyncio.FIRST_COMPLETED,
                )
                for task in done:
                    if task in (stdout_task, stderr_task):
                        task.result()
                if wait_task.done() and stdout_task.done() and stderr_task.done():
                    break
        except _WorkerOutputLimitExceeded as exc:
            await _terminate(process)
            raise PdfWorkerError(
                "Error: PDF worker output exceeded the byte limit",
                kind="resource_limit",
            ) from exc
        except asyncio.CancelledError:
            await _terminate(process)
            raise
        finally:
            tasks = (stdout_task, stderr_task, wait_task)
            if process.returncode is None:
                await _terminate(process)
            if drain_task is not None and not drain_task.done():
                drain_task.cancel()
                with contextlib.suppress(asyncio.CancelledError, Exception):
                    await drain_task
            for task in tasks:
                if not task.done():
                    task.cancel()
            with contextlib.suppress(Exception):
                await asyncio.wait_for(asyncio.gather(*tasks, return_exceptions=True), 2.0)

        stdout = stdout_task.result()
    if process.returncode != 0:
        raise PdfWorkerError("Error: PDF reader worker failed")
    try:
        response = json.loads(stdout.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise PdfWorkerError("Error: PDF reader worker returned invalid output") from exc
    if not isinstance(response, dict):
        raise PdfWorkerError("Error: PDF reader worker returned invalid output")
    if response.get("ok") is not True:
        message = response.get("message")
        kind = response.get("kind")
        raise PdfWorkerError(
            message if isinstance(message, str) else "Error: PDF operation failed",
            kind=kind if isinstance(kind, str) else "unavailable",
        )
    return response


def _protocol_limit(max_output_bytes: int) -> int:
    if (
        isinstance(max_output_bytes, bool)
        or not isinstance(max_output_bytes, int)
        or max_output_bytes <= 0
    ):
        raise PdfWorkerError("Error: PDF worker output limit is invalid", kind="invalid_input")
    # PNG output is base64 encoded in the JSON protocol.  Include that
    # expansion plus a bounded object envelope, then clamp to the absolute
    # protocol cap used by both parent and worker.
    expanded = (max_output_bytes * 4 + 2) // 3 + 16 * 1024
    return min(_WORKER_MAX_PROTOCOL_BYTES, max(64 * 1024, expanded))


async def _read_limited(reader: asyncio.StreamReader | None, limit: int) -> bytes:
    if reader is None:
        return b""
    chunks: list[bytes] = []
    total = 0
    while True:
        chunk = await reader.read(min(64 * 1024, limit - total + 1))
        if not chunk:
            return b"".join(chunks)
        total += len(chunk)
        if total > limit:
            raise _WorkerOutputLimitExceeded()
        chunks.append(chunk)


async def _terminate(process: asyncio.subprocess.Process) -> None:
    if process.returncode is not None:
        return
    try:
        process.terminate()
    except ProcessLookupError:
        return
    try:
        await asyncio.wait_for(process.wait(), timeout=2.0)
        return
    except (asyncio.TimeoutError, ProcessLookupError):
        pass
    try:
        process.kill()
    except ProcessLookupError:
        return
    with contextlib.suppress(asyncio.TimeoutError, ProcessLookupError):
        await asyncio.wait_for(process.wait(), timeout=2.0)


def pdf_worker_main() -> None:
    """Serve exactly one private PDF request on stdin/stdout."""

    try:
        line = sys.stdin.buffer.readline(_WORKER_MAX_PROTOCOL_BYTES + 1)
        if not line or len(line) > _WORKER_MAX_PROTOCOL_BYTES:
            raise PdfWorkerError("Error: PDF worker request exceeded the byte limit", kind="resource_limit")
        request = json.loads(line.decode("utf-8"))
        if not isinstance(request, dict):
            raise PdfWorkerError("Error: PDF worker request is invalid", kind="invalid_input")
        response = _run_pdf_request(request)
    except PdfWorkerError as exc:
        response = {"ok": False, "kind": exc.kind, "message": str(exc)}
    except Exception:
        response = {"ok": False, "kind": "unavailable", "message": "Error: PDF operation failed"}
    try:
        encoded_response = _encode_worker_response(response, request if "request" in locals() and isinstance(request, Mapping) else {})
    except PdfWorkerError as exc:
        encoded_response = json.dumps(
            {"ok": False, "kind": exc.kind, "message": str(exc)},
            ensure_ascii=False,
            separators=(",", ":"),
        )
    sys.stdout.write(encoded_response + "\n")
    sys.stdout.flush()


def _encode_worker_response(
    response: Mapping[str, object],
    request: Mapping[str, object],
) -> str:
    try:
        encoded = json.dumps(response, ensure_ascii=False, separators=(",", ":"))
    except (TypeError, ValueError) as exc:
        raise PdfWorkerError("Error: PDF worker returned invalid output") from exc
    max_output = request.get("max_output_bytes", _WORKER_MAX_PROTOCOL_BYTES)
    limit = _protocol_limit(max_output) if isinstance(max_output, int) else _WORKER_MAX_PROTOCOL_BYTES
    if len(encoded.encode("utf-8")) > limit:
        raise PdfWorkerError("Error: PDF worker output exceeded the byte limit", kind="resource_limit")
    return encoded


def _run_pdf_request(request: Mapping[str, object]) -> dict[str, object]:
    operation = request.get("operation")
    encoded = request.get("data_b64")
    if operation not in {"text", "image"} or not isinstance(encoded, str):
        raise PdfWorkerError("Error: PDF worker request is invalid", kind="invalid_input")
    _protocol_limit(request.get("max_output_bytes", _WORKER_MAX_PROTOCOL_BYTES))
    try:
        data = base64.b64decode(encoded.encode("ascii"), validate=True)
    except (UnicodeEncodeError, binascii.Error) as exc:
        raise PdfWorkerError("Error: PDF worker request is invalid", kind="invalid_input") from exc
    if operation == "text":
        return _run_pdf_text(data, request)
    return _run_pdf_image(data, request)


def _open_pdf(data: bytes) -> Any:
    try:
        import pypdfium2 as pdfium

        return pdfium.PdfDocument(data)
    except Exception as exc:
        raise PdfWorkerError("Error: PDF is damaged or encrypted", kind="invalid_input") from exc


def _run_pdf_text(data: bytes, request: Mapping[str, object]) -> dict[str, object]:
    document = _open_pdf(data)
    try:
        page_number = request.get("page")
        if page_number is not None and (isinstance(page_number, bool) or not isinstance(page_number, int) or page_number < 1):
            raise PdfWorkerError("Error: page must be a positive integer", kind="invalid_input")
        page_count = len(document)
        pages = [page_number] if page_number is not None else list(range(1, min(page_count, 200) + 1))
        max_chars = request.get("max_chars", 64 * 1024)
        if isinstance(max_chars, bool) or not isinstance(max_chars, int) or not 1 <= max_chars <= 262144:
            raise PdfWorkerError("Error: max_chars is invalid", kind="invalid_input")
        chunks: list[str] = []
        for page in pages:
            if page > page_count:
                raise PdfWorkerError(f"Error: PDF page {page} does not exist", kind="not_found")
            pdf_page = None
            try:
                pdf_page = document[page - 1]
                text_page = pdf_page.get_textpage()
                text = text_page.get_text_range()
            except PdfWorkerError:
                raise
            except Exception as exc:
                raise PdfWorkerError(f"Error: PDF page {page} could not be read") from exc
            finally:
                if pdf_page is not None:
                    with contextlib.suppress(Exception):
                        pdf_page.close()
            chunks.append(f"[page {page}]\n{text.strip()}".rstrip())
        value = "\n\n".join(chunks)
        encoded_value = value.encode("utf-8")
        truncated = len(encoded_value) > max_chars
        if truncated:
            encoded_value = encoded_value[:max_chars]
            while True:
                try:
                    value = encoded_value.decode("utf-8")
                    break
                except UnicodeDecodeError:
                    encoded_value = encoded_value[:-1]
            value += "\n[truncated]"
        if len(value.encode("utf-8")) > int(request.get("max_output_bytes", _WORKER_MAX_PROTOCOL_BYTES)):
            raise PdfWorkerError("Error: PDF text exceeds the byte limit", kind="resource_limit")
        return {"ok": True, "operation": "text", "text": value, "page": pages[0] if len(pages) == 1 else None}
    finally:
        with contextlib.suppress(Exception):
            document.close()


def _run_pdf_image(data: bytes, request: Mapping[str, object]) -> dict[str, object]:
    document = _open_pdf(data)
    try:
        page_number = request.get("page")
        if isinstance(page_number, bool) or not isinstance(page_number, int) or page_number < 1:
            raise PdfWorkerError("Error: page must be a positive integer", kind="invalid_input")
        if page_number > len(document):
            raise PdfWorkerError(f"Error: PDF page {page_number} does not exist", kind="not_found")
        max_width = request.get("max_width", 2048)
        max_height = request.get("max_height", 2048)
        max_pixels = request.get("max_pixels", 16_000_000)
        if any(isinstance(value, bool) or not isinstance(value, int) for value in (max_width, max_height, max_pixels)):
            raise PdfWorkerError("Error: image dimensions are invalid", kind="invalid_input")
        if not 1 <= max_width <= 8192 or not 1 <= max_height <= 8192 or max_pixels <= 0:
            raise PdfWorkerError("Error: image dimensions are invalid", kind="invalid_input")
        try:
            from PIL import Image

            page = document[page_number - 1]
            try:
                bitmap = page.render(scale=2.0)
                image = bitmap.to_pil()
                image.thumbnail((max_width, max_height), Image.Resampling.LANCZOS)
                if image.width * image.height > max_pixels:
                    raise PdfWorkerError("Error: rendered page exceeds the pixel limit", kind="resource_limit")
                output = io.BytesIO()
                image.save(output, format="PNG", optimize=True)
                data = output.getvalue()
                max_output = request.get("max_output_bytes", _WORKER_MAX_PROTOCOL_BYTES)
                if isinstance(max_output, bool) or not isinstance(max_output, int) or len(data) > max_output:
                    raise PdfWorkerError("Error: rendered image exceeds the byte limit", kind="resource_limit")
            finally:
                with contextlib.suppress(Exception):
                    page.close()
        except PdfWorkerError:
            raise
        except Exception as exc:
            raise PdfWorkerError("Error: PDF page could not be rendered") from exc
        return {
            "ok": True,
            "operation": "image",
            "png_b64": base64.b64encode(data).decode("ascii"),
            "width": image.width,
            "height": image.height,
        }
    finally:
        with contextlib.suppress(Exception):
            document.close()


__all__ = ["PDF_WORKER_FLAG", "PdfWorkerError", "pdf_worker_command", "pdf_worker_main", "run_pdf_worker"]


if __name__ == "__main__":  # pragma: no cover - exercised by the parent process
    if PDF_WORKER_FLAG not in sys.argv[1:]:
        raise SystemExit(f"{PDF_WORKER_FLAG} is required")
    pdf_worker_main()
