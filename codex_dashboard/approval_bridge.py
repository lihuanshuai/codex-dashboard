from __future__ import annotations

import asyncio
import base64
import json
import os
import shutil
import struct
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field


class ApprovalBridgeUnavailable(RuntimeError):
    pass


class LiveApprovalNotFound(RuntimeError):
    pass


class LiveApprovalView(BaseModel):
    call_id: str
    thread_id: str | None = None
    turn_id: str | None = None
    command: str = ""
    cwd: str = ""
    reason: str = ""
    can_accept_for_session: bool = False


class ApprovalBridgeStatus(BaseModel):
    available: bool
    connected: bool
    pending: int
    pending_call_ids: list[str] = Field(default_factory=list)
    live_approvals: list[LiveApprovalView] = Field(default_factory=list)
    socket: str | None = None
    message: str


@dataclass
class LiveApprovalRequest:
    request_id: str | int
    call_id: str
    thread_id: str | None
    turn_id: str | None
    params: dict[str, Any]


class CodexApprovalBridge:
    """Best-effort JSON-RPC bridge to a running Codex app-server control socket."""

    APPROVAL_METHOD = "item/commandExecution/requestApproval"

    def __init__(self, codex_home: Path) -> None:
        self.codex_home = codex_home
        self._reader: asyncio.StreamReader | None = None
        self._writer: asyncio.StreamWriter | None = None
        self._lock = asyncio.Lock()
        self._next_request_id = 1
        self._response_waiters: dict[str | int, asyncio.Future[dict[str, Any]]] = {}
        self._pending_by_call_id: dict[str, LiveApprovalRequest] = {}
        self._last_error = ""
        self._last_start_message = ""
        self._last_start_attempt = 0.0
        self._start_lock = asyncio.Lock()
        self._starting = False

    @property
    def socket_path(self) -> Path:
        configured = os.environ.get("CODEX_DASHBOARD_APP_SERVER_SOCK")
        if configured:
            return Path(configured).expanduser()
        return self.codex_home / "app-server-control" / "app-server-control.sock"

    def status(self) -> ApprovalBridgeStatus:
        socket = self.socket_path
        connected = self._is_connected()
        if connected:
            return ApprovalBridgeStatus(
                available=True,
                connected=True,
                pending=len(self._pending_by_call_id),
                pending_call_ids=sorted(self._pending_by_call_id),
                live_approvals=self.live_approvals(),
                socket=str(socket),
                message="已连接 Codex app-server，网页可发送审批决定。",
            )
        if not shutil.which("codex"):
            return ApprovalBridgeStatus(
                available=False,
                connected=False,
                pending=0,
                socket=str(socket),
                message="找不到 codex CLI，无法连接审批桥。",
            )
        if not socket.exists():
            hint = "未发现 Codex app-server control socket；页面会尝试自动启动 Codex remote-control。"
            if self._starting:
                hint = "正在启动 Codex remote-control..."
            elif self._last_start_message:
                hint = f"{hint} 最近启动结果：{self._last_start_message}"
            if self._last_error and self._last_error != "control socket 不存在":
                hint = f"{hint} 最近错误：{self._last_error}"
            return ApprovalBridgeStatus(
                available=False,
                connected=False,
                pending=0,
                socket=str(socket),
                message=hint,
            )
        message = "发现 app-server control socket，点击审批时会自动连接。"
        if self._last_error:
            message = f"{message} 最近错误：{self._last_error}"
        return ApprovalBridgeStatus(
            available=True,
            connected=False,
            pending=0,
            socket=str(socket),
            message=message,
        )

    def live_approvals(self) -> list[LiveApprovalView]:
        return [
            self._live_approval_view(approval)
            for approval in sorted(self._pending_by_call_id.values(), key=lambda item: str(item.call_id))
        ]

    async def ensure_ready(self, *, start_if_missing: bool = False) -> None:
        if self._is_connected():
            return
        if start_if_missing and not self.socket_path.exists():
            await self._start_remote_control()
        await self._ensure_connected()

    async def decide(
        self,
        *,
        call_id: str,
        decision: str,
        thread_id: str | None = None,
        turn_id: str | None = None,
    ) -> None:
        if decision not in {"accept", "accept_for_session", "decline"}:
            raise ValueError("Unsupported approval decision")
        await self.ensure_ready(start_if_missing=True)
        approval = self._pending_by_call_id.get(call_id)
        if not approval:
            raise LiveApprovalNotFound(
                "已在 JSONL 中看到待审批请求，但当前网页没有捕获到 app-server 的实时审批回调；"
                "请保持 dashboard 打开并等下一次权限请求出现，或回到 Codex 客户端审批。"
            )
        if thread_id and approval.thread_id and approval.thread_id != thread_id:
            raise LiveApprovalNotFound("捕获到的审批请求与目标会话不一致。")
        if turn_id and approval.turn_id and approval.turn_id != turn_id:
            raise LiveApprovalNotFound("捕获到的审批请求与目标 turn 不一致。")

        result = self._approval_result(approval, decision)
        await self._write_json({"id": approval.request_id, "result": result})
        self._pending_by_call_id.pop(call_id, None)

    async def _ensure_connected(self) -> None:
        if self._is_connected():
            return
        async with self._lock:
            if self._is_connected():
                return
            socket = self.socket_path
            if not socket.exists():
                self._last_error = "control socket 不存在"
                raise ApprovalBridgeUnavailable(self.status().message)
            try:
                self._reader, self._writer = await asyncio.open_unix_connection(str(socket))
                await self._websocket_handshake()
            except OSError as exc:
                self._last_error = str(exc)
                raise ApprovalBridgeUnavailable(f"连接 Codex app-server control socket 失败：{exc}") from exc

            asyncio.create_task(self._read_websocket())
            try:
                await self._initialize()
            except Exception:
                await self._close_process()
                raise

    async def _start_remote_control(self) -> None:
        if not shutil.which("codex"):
            self._last_error = "找不到 codex CLI"
            raise ApprovalBridgeUnavailable(self.status().message)

        now = time.monotonic()
        if now - self._last_start_attempt < 30:
            if not self._last_start_message:
                self._last_start_message = "刚尝试过启动，等待下一次检查。"
            return

        async with self._start_lock:
            if self.socket_path.exists():
                return
            now = time.monotonic()
            if now - self._last_start_attempt < 30:
                if not self._last_start_message:
                    self._last_start_message = "刚尝试过启动，等待下一次检查。"
                return
            self._last_start_attempt = now
            self._starting = True
            self._last_start_message = ""
            env = dict(os.environ)
            env["CODEX_HOME"] = str(self.codex_home)
            try:
                await self._start_remote_control_with_current_cli(env)
            except OSError as exc:
                self._last_start_message = str(exc)
                raise ApprovalBridgeUnavailable(f"启动 Codex remote-control 失败：{exc}") from exc
            finally:
                self._starting = False

    async def _start_remote_control_with_current_cli(self, env: dict[str, str]) -> None:
        process = await asyncio.create_subprocess_exec(
            "codex",
            "remote-control",
            "start",
            "--json",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=env,
        )
        try:
            stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=20)
        except asyncio.TimeoutError as exc:
            process.kill()
            await process.communicate()
            self._last_start_message = "启动超时"
            raise ApprovalBridgeUnavailable("启动 Codex remote-control 超时。") from exc

        output = (stdout + stderr).decode("utf-8", errors="replace").strip()
        if process.returncode == 0:
            self._last_start_message = _compact_start_output(output)
            return
        self._last_start_message = output[:240] or f"退出码 {process.returncode}"
        raise ApprovalBridgeUnavailable(f"启动 Codex remote-control 失败：{self._last_start_message}")

    async def _initialize(self) -> None:
        response = await self._send_request(
            "initialize",
            {
                "clientInfo": {
                    "name": "codex-dashboard",
                    "title": "Codex Dashboard",
                    "version": "0.1.0",
                },
                "capabilities": {
                    "experimentalApi": True,
                    "requestAttestation": False,
                    "optOutNotificationMethods": [],
                },
            },
        )
        if "error" in response:
            raise ApprovalBridgeUnavailable(f"app-server initialize 失败：{response['error']}")
        await self._write_json({"method": "initialized"})

    async def _send_request(self, method: str, params: dict[str, Any] | None) -> dict[str, Any]:
        request_id = self._next_request_id
        self._next_request_id += 1
        loop = asyncio.get_running_loop()
        future: asyncio.Future[dict[str, Any]] = loop.create_future()
        self._response_waiters[request_id] = future
        await self._write_json({"id": request_id, "method": method, "params": params})
        try:
            return await asyncio.wait_for(future, timeout=5)
        except asyncio.TimeoutError as exc:
            self._response_waiters.pop(request_id, None)
            self._last_error = f"{method} 超时"
            raise ApprovalBridgeUnavailable(f"等待 app-server 响应超时：{method}") from exc

    async def _write_json(self, message: dict[str, Any]) -> None:
        writer = self._writer
        if not writer or writer.is_closing():
            raise ApprovalBridgeUnavailable("审批桥未连接。")
        payload = json.dumps(message, separators=(",", ":")).encode("utf-8")
        writer.write(_websocket_text_frame(payload))
        await writer.drain()

    async def _read_websocket(self) -> None:
        try:
            while True:
                payload = await self._read_websocket_payload()
                if payload is None:
                    break
                try:
                    message = json.loads(payload)
                except json.JSONDecodeError:
                    continue
                await self._handle_message(message)
        finally:
            await self._close_process()

    async def _websocket_handshake(self) -> None:
        reader = self._reader
        writer = self._writer
        if not reader or not writer:
            raise ApprovalBridgeUnavailable("审批桥未连接。")
        key = base64.b64encode(os.urandom(16)).decode("ascii")
        writer.write(
            (
                "GET / HTTP/1.1\r\n"
                "Host: localhost\r\n"
                "Upgrade: websocket\r\n"
                "Connection: Upgrade\r\n"
                f"Sec-WebSocket-Key: {key}\r\n"
                "Sec-WebSocket-Version: 13\r\n"
                "\r\n"
            ).encode("ascii")
        )
        await writer.drain()
        response = await asyncio.wait_for(reader.readuntil(b"\r\n\r\n"), timeout=5)
        if b"101 Switching Protocols" not in response:
            self._last_error = response.decode("utf-8", errors="replace")[:240]
            raise ApprovalBridgeUnavailable("Codex app-server control socket WebSocket 握手失败。")

    async def _read_websocket_payload(self) -> bytes | None:
        reader = self._reader
        writer = self._writer
        if not reader or not writer:
            return None
        header = await reader.readexactly(2)
        opcode = header[0] & 0x0F
        length = header[1] & 0x7F
        masked = bool(header[1] & 0x80)
        if length == 126:
            length = struct.unpack("!H", await reader.readexactly(2))[0]
        elif length == 127:
            length = struct.unpack("!Q", await reader.readexactly(8))[0]
        mask = await reader.readexactly(4) if masked else b""
        payload = await reader.readexactly(length) if length else b""
        if masked:
            payload = bytes(byte ^ mask[index % 4] for index, byte in enumerate(payload))
        if opcode == 0x8:
            return None
        if opcode == 0x9:
            writer.write(_websocket_control_frame(0xA, payload))
            await writer.drain()
            return await self._read_websocket_payload()
        if opcode != 0x1:
            return b""
        return payload

    async def _handle_message(self, message: dict[str, Any]) -> None:
        request_id = message.get("id")
        if request_id in self._response_waiters and ("result" in message or "error" in message):
            waiter = self._response_waiters.pop(request_id)
            if not waiter.done():
                waiter.set_result(message)
            return

        method = message.get("method")
        if request_id is None or not isinstance(method, str):
            return
        params = message.get("params")
        if not isinstance(params, dict):
            params = {}
        if method == self.APPROVAL_METHOD:
            approval = self._live_approval_from_message(request_id, params)
            if approval:
                self._pending_by_call_id[approval.call_id] = approval
            return

        await self._write_json(
            {
                "id": request_id,
                "error": {"code": -32601, "message": f"codex-dashboard does not handle {method}"},
            }
        )

    def _live_approval_from_message(
        self,
        request_id: str | int,
        params: dict[str, Any],
    ) -> LiveApprovalRequest | None:
        call_id = str(params.get("itemId") or "")
        thread_id = str(params.get("threadId") or "") or None
        turn_id = str(params.get("turnId") or "") or None
        if not call_id:
            return None
        return LiveApprovalRequest(
            request_id=request_id,
            call_id=call_id,
            thread_id=thread_id,
            turn_id=turn_id,
            params=params,
        )

    def _live_approval_view(self, approval: LiveApprovalRequest) -> LiveApprovalView:
        params = approval.params
        command = str(params.get("command") or "")
        cwd = str(params.get("cwd") or "")
        reason = str(params.get("reason") or "")
        return LiveApprovalView(
            call_id=approval.call_id,
            thread_id=approval.thread_id,
            turn_id=approval.turn_id,
            command=command,
            cwd=cwd,
            reason=reason,
            can_accept_for_session=bool(params.get("proposedExecpolicyAmendment")),
        )

    def _approval_result(self, approval: LiveApprovalRequest, decision: str) -> dict[str, Any]:
        if decision == "decline":
            return {"decision": "decline"}
        if decision == "accept_for_session":
            amendment = approval.params.get("proposedExecpolicyAmendment")
            if amendment:
                return {"decision": {"acceptWithExecpolicyAmendment": {"execpolicy_amendment": amendment}}}
            return {"decision": "acceptForSession"}
        return {"decision": "accept"}

    def _is_connected(self) -> bool:
        return self._writer is not None and not self._writer.is_closing()

    async def _close_process(self) -> None:
        writer = self._writer
        self._reader = None
        self._writer = None
        self._pending_by_call_id.clear()
        for waiter in self._response_waiters.values():
            if not waiter.done():
                waiter.set_result({"error": {"message": "app-server connection closed"}})
        self._response_waiters.clear()
        if writer and not writer.is_closing():
            writer.close()
            await writer.wait_closed()


def _compact_start_output(output: str) -> str:
    if not output:
        return "已启动"
    try:
        parsed = json.loads(output)
    except json.JSONDecodeError:
        return "已启动"
    if isinstance(parsed, dict) and parsed.get("status"):
        return str(parsed["status"])
    return "已启动"


def _websocket_text_frame(payload: bytes) -> bytes:
    return _websocket_frame(0x1, payload, masked=True)


def _websocket_control_frame(opcode: int, payload: bytes) -> bytes:
    return _websocket_frame(opcode, payload, masked=False)


def _websocket_frame(opcode: int, payload: bytes, *, masked: bool) -> bytes:
    header = bytearray([0x80 | opcode])
    length = len(payload)
    mask_bit = 0x80 if masked else 0
    if length < 126:
        header.append(mask_bit | length)
    elif length < 65536:
        header.append(mask_bit | 126)
        header.extend(struct.pack("!H", length))
    else:
        header.append(mask_bit | 127)
        header.extend(struct.pack("!Q", length))
    if not masked:
        return bytes(header) + payload
    mask = os.urandom(4)
    masked_payload = bytes(byte ^ mask[index % 4] for index, byte in enumerate(payload))
    return bytes(header) + mask + masked_payload
