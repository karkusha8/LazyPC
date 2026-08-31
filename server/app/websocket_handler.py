import json
import time

from fastapi import WebSocket, WebSocketDisconnect

from app.models import PeerRole
from app.registry import registry
from app.relay import safe_close, safe_send_text


# Short-lived pairing-token routing table.
# The signaling server only routes the token; Windows validates it.
_pairing_targets: dict[str, tuple[str, float]] = {}


def _register_pairing_target(
    pairing_token: str,
    pc_id: str,
    ttl_seconds: int,
) -> None:
    now = time.monotonic()

    for token, (_, expires_at) in list(_pairing_targets.items()):
        if expires_at <= now:
            _pairing_targets.pop(token, None)

    _pairing_targets[pairing_token] = (
        pc_id,
        now + max(1, min(ttl_seconds, 300)),
    )


def _resolve_pairing_target(
    pairing_token: str,
) -> str | None:
    entry = _pairing_targets.get(pairing_token)

    if entry is None:
        return None

    pc_id, expires_at = entry

    if time.monotonic() >= expires_at:
        _pairing_targets.pop(pairing_token, None)
        return None

    return pc_id


def _remove_pairing_targets_for_pc(pc_id: str) -> None:
    for token, (target_pc, _) in list(_pairing_targets.items()):
        if target_pc == pc_id:
            _pairing_targets.pop(token, None)


def _pairing_message(text: str) -> bool:
    try:
        message = json.loads(text)
    except Exception:
        return False

    return (
        message.get("type") == "create_session"
        and bool(message.get("pairing_token"))
    )


def _is_pairing_hello(text: str) -> bool:
    return text.strip() == "HELLO_CLIENT_PAIRING"


def _parse_json(text: str) -> dict | None:
    try:
        value = json.loads(text)
    except Exception:
        return None

    return value if isinstance(value, dict) else None


async def _handle_agent_handshake(
    ws: WebSocket,
) -> str | None:
    """
    Existing HELLO_AGENT is preserved.

    The next frame must register the persistent PC ID:
        {"type":"register_pc","pc_id":"lazypc-..."}
    """
    try:
        raw = (await ws.receive_text()).strip()
    except WebSocketDisconnect:
        return None

    message = _parse_json(raw)

    if (
        message is None
        or message.get("type") != "register_pc"
    ):
        await safe_send_text(
            ws,
            json.dumps({
                "type": "register_pc_rejected",
                "version": 1,
                "reason": "register_pc_required",
            }),
        )
        await safe_close(ws)
        return None

    pc_id = message.get("pc_id")

    if (
        not isinstance(pc_id, str)
        or not pc_id.startswith("lazypc-")
        or len(pc_id) > 128
    ):
        await safe_send_text(
            ws,
            json.dumps({
                "type": "register_pc_rejected",
                "version": 1,
                "reason": "invalid_pc_id",
            }),
        )
        await safe_close(ws)
        return None

    previous = await registry.register_agent(
        pc_id,
        ws,
    )

    if previous is not None and previous is not ws:
        await safe_close(previous)

    public_code = registry.public_pc_code(pc_id)

    await safe_send_text(
        ws,
        json.dumps({
            "type": "pc_registered",
            "version": 1,
            "pc_code": public_code,
        }),
    )

    print(
        f"🖥️ Agent registered: "
        f"{public_code[:3]} {public_code[3:6]} {public_code[6:]}"
    )

    return pc_id


async def _handle_client_handshake(
    ws: WebSocket,
    first: str,
) -> tuple[bool, str | None]:
    pairing_mode = False

    if first == "HELLO_CLIENT":
        pairing_mode = False

    elif _is_pairing_hello(first):
        pairing_mode = True

    elif _pairing_message(first):
        pairing_mode = True

    else:
        await safe_close(ws)
        return False, None

    await registry.register_client(
        ws,
        pairing_mode=pairing_mode,
    )

    return True, None


async def _handle_find_pc(
    ws: WebSocket,
    message: dict,
) -> None:
    requested_id = message.get("pc_id")

    if (
        not isinstance(requested_id, str)
        or not requested_id.strip()
    ):
        await safe_send_text(
            ws,
            json.dumps({
                "type": "pc_not_found",
                "version": 1,
                "reason": "invalid_pc_code",
                "pc_code": "",
                "pc_id": "",
            }),
        )
        return

    requested_id = requested_id.strip()

    # Android sends the public PC code in display form ("944 971 631").
    # The registry resolves the canonical 9-digit form, so normalize here
    # before lookup. Keep the original display value for the response.
    lookup_code = "".join(
        character
        for character in requested_id
        if character.isdigit()
    )

    resolved_pc_id = await registry.resolve_pc_id(lookup_code)

    if resolved_pc_id is None:
        await safe_send_text(
            ws,
            json.dumps({
                "type": "pc_not_found",
                "version": 1,
                "pc_code": requested_id,
                "pc_id": requested_id,
            }),
        )
        return

    device = message.get("device")

    if not isinstance(device, dict):
        device = None

    if not await registry.set_client_pc(
        ws,
        resolved_pc_id,
        device=device,
    ):
        await safe_send_text(
            ws,
            json.dumps({
                "type": "pc_not_found",
                "version": 1,
                "pc_code": requested_id,
                "pc_id": requested_id,
            }),
        )
        return

    await safe_send_text(
        ws,
        json.dumps({
            "type": "pc_found",
            "version": 1,
            "pc_code": requested_id,
            "pc_id": requested_id,
        }),
    )

    # Normal mode starts only after a concrete PC was selected.
    # Forward the Android device metadata to the Windows Agent.
    create_sent = await registry.send_create_session(
        resolved_pc_id,
        device=device,
    )

    if not create_sent:
        print(
            "❌ Failed to send create_session to selected Agent"
        )
    else:
        print(
            "📤 create_session sent to selected Agent"
        )

    print(
        f"📱 Client selected PC: "
        f"{requested_id[:3]} {requested_id[3:6]} {requested_id[6:]}"
    )


async def _handle_pc_status(
    ws: WebSocket,
    message: dict,
) -> None:
    """Return the current online/offline state for a public PC code."""
    requested_code = message.get("pc_code")

    if (
        not isinstance(requested_code, str)
        or not requested_code.strip()
    ):
        await safe_send_text(
            ws,
            json.dumps({
                "type": "pc_status",
                "version": 1,
                "pc_code": "",
                "online": False,
                "reason": "invalid_pc_code",
            }),
        )
        return

    requested_code = requested_code.strip()
    lookup_code = "".join(
        character
        for character in requested_code
        if character.isdigit()
    )

    online = await registry.is_pc_online(lookup_code)

    await safe_send_text(
        ws,
        json.dumps({
            "type": "pc_status",
            "version": 1,
            "pc_code": lookup_code,
            "online": online,
        }),
    )

    print(
        f"📡 PC status: {lookup_code} -> "
        f"{'ONLINE' if online else 'OFFLINE'}"
    )


async def _handle_connect_trusted(
    ws: WebSocket,
    message: dict,
) -> None:
    """
    Route an already-paired/trusted Android client to a specific PC.

    Signaling only resolves the public PC code and binds the client socket
    to that Agent. It does NOT decide whether the device is actually trusted.
    Windows remains responsible for cryptographic authentication.
    """
    requested_code = message.get("pc_code")

    if (
        not isinstance(requested_code, str)
        or not requested_code.strip()
    ):
        await safe_send_text(
            ws,
            json.dumps({
                "type": "trusted_route_failed",
                "version": 1,
                "reason": "invalid_pc_code",
                "pc_code": "",
            }),
        )
        return

    requested_code = requested_code.strip()

    # Android may send the user-facing PC code either as
    # "944971631" or the UI-formatted "944 971 631".
    # Keep both Trusted and ordinary PC routing consistent.
    lookup_code = "".join(
        character
        for character in requested_code
        if character.isdigit()
    )

    resolved_pc_id = await registry.resolve_pc_id(lookup_code)

    if resolved_pc_id is None:
        await safe_send_text(
            ws,
            json.dumps({
                "type": "trusted_route_failed",
                "version": 1,
                "reason": "pc_not_found",
                "pc_code": requested_code,
            }),
        )
        print(
            f"⚠️ Trusted route: PC not found [{requested_code}]"
        )
        return

    if not await registry.set_client_pc(
        ws,
        resolved_pc_id,
        connection_mode="trusted",
    ):
        await safe_send_text(
            ws,
            json.dumps({
                "type": "trusted_route_failed",
                "version": 1,
                "reason": "agent_not_found",
                "pc_code": requested_code,
            }),
        )
        return

    await safe_send_text(
        ws,
        json.dumps({
            "type": "trusted_pc_selected",
            "version": 1,
            "pc_code": requested_code,
            "pc_id": requested_code,
        }),
    )

    # Start the same WebRTC session bootstrap used by the existing Agent,
    # but explicitly mark this session as Trusted. Signaling does not
    # authenticate the device; Windows must perform the Trusted auth flow.
    agent = await registry.get_agent(resolved_pc_id)
    if agent is None:
        return

    create_sent = await safe_send_text(
        agent,
        json.dumps({
            "type": "create_session",
            "connection_mode": "trusted",
        }),
    )

    if create_sent:
        print(
            "📤 trusted create_session -> agent "
            f"[{resolved_pc_id}]"
        )
    else:
        print(
            "⚠️ Failed to send trusted create_session -> agent "
            f"[{resolved_pc_id}]"
        )


async def handle_connection(ws: WebSocket):
    await ws.accept()

    role: PeerRole | None = None
    pc_id: str | None = None

    try:
        try:
            first = (
                await ws.receive_text()
            ).strip()
        except WebSocketDisconnect:
            print(
                "🔌 socket disconnected during handshake"
            )
            return

        if first == "HELLO_AGENT":
            role = PeerRole.AGENT

            pc_id = (
                await _handle_agent_handshake(ws)
            )

            if pc_id is None:
                return

        elif (
            first == "HELLO_CLIENT"
            or _is_pairing_hello(first)
            or _pairing_message(first)
            or (
                _parse_json(first) is not None
                and _parse_json(first).get("type") in {
                    "find_pc",
                    "connect_trusted",
                    "get_pc_status",
                }
            )
        ):
            role = PeerRole.CLIENT

            handshake_first = first
            first_json = _parse_json(first)
            if (
                first_json is not None
                and first_json.get("type") in {
                    "find_pc",
                    "connect_trusted",
                    "get_pc_status",
                }
            ):
                handshake_first = "HELLO_CLIENT"

            ok, _ = await _handle_client_handshake(
                ws,
                handshake_first,
            )

            if not ok:
                return

            if _pairing_message(first):
                # Preserve existing pairing compatibility.
                # If pairing is explicitly targeted, use pc_id.
                message = _parse_json(first)
                target_pc = (
                    message.get("pc_id")
                    if message
                    else None
                )

                if (
                    isinstance(target_pc, str)
                    and await registry.find_pc(target_pc)
                ):
                    await registry.set_client_pc(
                        ws,
                        target_pc,
                    )

                    await registry.forward_client_to_agent(
                        ws,
                        first,
                    )

            first_message = _parse_json(first)
            if isinstance(first_message, dict):
                if first_message.get("type") == "find_pc":
                    await _handle_find_pc(
                        ws,
                        first_message,
                    )
                elif first_message.get("type") == "connect_trusted":
                    await _handle_connect_trusted(
                        ws,
                        first_message,
                    )

        else:
            print(
                "❌ Unknown role:",
                first,
            )
            await safe_close(ws)
            return

        print(
            f"✅ {role.value} connected"
        )

        while True:
            msg = await ws.receive_text()

            if (
                role == PeerRole.CLIENT
                and _is_pairing_hello(msg)
            ):
                continue

            message = _parse_json(msg)

            # ---------------------------------------------------------
            # Client-side signaling commands consumed by the server.
            # ---------------------------------------------------------
            if role == PeerRole.CLIENT and message:
                message_type = message.get("type")

                if message_type == "find_pc":
                    await _handle_find_pc(
                        ws,
                        message,
                    )
                    continue

                if message_type == "connect_trusted":
                    await _handle_connect_trusted(
                        ws,
                        message,
                    )
                    continue

                if message_type == "get_pc_status":
                    await _handle_pc_status(
                        ws,
                        message,
                    )
                    continue

                if message_type == "disconnect_pc":
                    await registry.detach_client(ws)

                    await safe_send_text(
                        ws,
                        json.dumps({
                            "type": "pc_disconnected",
                            "version": 1,
                        }),
                    )
                    continue

                if message_type == "create_session":
                    pairing_token = message.get("pairing_token")

                    if isinstance(pairing_token, str) and pairing_token:
                        target_pc = _resolve_pairing_target(
                            pairing_token
                        )

                        if target_pc is None:
                            await safe_send_text(
                                ws,
                                json.dumps({
                                    "type": "pairing_route_failed",
                                    "version": 1,
                                    "reason": "pairing_token_unknown_or_expired",
                                }),
                            )

                            print(
                                "⚠️ Pairing token has no active Agent"
                            )
                            continue

                        if not await registry.set_client_pc(
                            ws,
                            target_pc,
                        ):
                            await safe_send_text(
                                ws,
                                json.dumps({
                                    "type": "pairing_route_failed",
                                    "version": 1,
                                    "reason": "agent_not_found",
                                }),
                            )

                            print(
                                "⚠️ Pairing target Agent is offline"
                            )
                            continue

                        ok = await registry.forward_client_to_agent(
                            ws,
                            msg,
                        )

                        # The token is only needed to locate the Agent for
                        # the first create_session.
                        _pairing_targets.pop(
                            pairing_token,
                            None,
                        )

                        if ok:
                            print(
                                "📤 pairing create_session -> agent "
                                f"[{target_pc}]"
                            )
                        else:
                            print(
                                "⚠️ Failed to forward pairing create_session"
                            )

                        continue

            # ---------------------------------------------------------
            # Agent-side control messages consumed by the server.
            # ---------------------------------------------------------
            if role == PeerRole.AGENT and message:
                message_type = message.get("type")

                if message_type == "register_pairing":
                    pairing_token = message.get("pairing_token")
                    ttl_seconds = message.get(
                        "ttl_seconds",
                        120,
                    )

                    if (
                        not isinstance(pairing_token, str)
                        or not pairing_token
                    ):
                        print(
                            "⚠️ Agent sent invalid pairing token registration"
                        )
                        continue

                    try:
                        ttl_seconds = int(ttl_seconds)
                    except (TypeError, ValueError):
                        ttl_seconds = 120

                    _register_pairing_target(
                        pairing_token,
                        pc_id,
                        ttl_seconds,
                    )

                    print(
                        "🔐 Pairing token registered for Agent "
                        f"[{pc_id}]"
                    )
                    continue

            # ---------------------------------------------------------
            # Normal relay.
            # ---------------------------------------------------------
            if role == PeerRole.CLIENT:
                ok = await registry.forward_client_to_agent(
                    ws,
                    msg,
                )
            else:
                if pc_id is None:
                    continue

                ok = await registry.forward_agent_to_client(
                    pc_id,
                    msg,
                )

            if not ok:
                if role == PeerRole.CLIENT:
                    connection_mode = await registry.get_client_connection_mode(ws)
                    print(
                        "⚠️ No signaling peer for client "
                        f"(mode={connection_mode})"
                    )
                else:
                    print(
                        f"⚠️ No signaling peer for {role.value}"
                    )

    except WebSocketDisconnect:
        print(
            f"🔌 {role.value if role else 'unknown'} disconnected"
        )

    finally:
        if role == PeerRole.AGENT and pc_id:
            _remove_pairing_targets_for_pc(pc_id)

            unregister_agent = getattr(
                registry,
                "unregister_agent",
                None,
            )

            if callable(unregister_agent):
                await unregister_agent(
                    pc_id,
                    ws,
                )
            else:
                unregister = getattr(
                    registry,
                    "unregister",
                    None,
                )

                if callable(unregister):
                    await unregister(
                        role,
                        ws,
                    )

        elif role == PeerRole.CLIENT:
            unregister_client = getattr(
                registry,
                "unregister_client",
                None,
            )

            if callable(unregister_client):
                await unregister_client(ws)
            else:
                detach_client = getattr(
                    registry,
                    "detach_client",
                    None,
                )

                if callable(detach_client):
                    await detach_client(ws)

                unregister = getattr(
                    registry,
                    "unregister",
                    None,
                )

                if callable(unregister):
                    await unregister(
                        role,
                        ws,
                    )