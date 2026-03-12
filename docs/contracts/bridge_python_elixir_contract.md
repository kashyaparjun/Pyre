# Python <-> Elixir Bridge Contract (Phase 1)

This contract defines the first cross-runtime integration target between:

- Python client: `src/pyre_agents/bridge/transport.py`
- Elixir server: `elixir/pyre_bridge/lib/pyre_bridge/bridge_server.ex`

## Transport and framing

- Transport (Phase 1 spike): TCP loopback (`127.0.0.1:<port>`)
- Framing: 4-byte unsigned big-endian payload length + raw MessagePack payload

Frame format:

```text
[4 bytes length][N bytes msgpack envelope]
```

## Envelope schema

Required common fields:

- `correlation_id` (string UUID)
- `type` (string enum)

Supported `type` values:

- `execute`, `result`, `error`, `register`, `deregister`, `spawn`, `stop`, `ping`, `pong`

Type-specific required fields:

- `execute`: `agent_id`, `handler`, `state`, `message`
- `result`: `agent_id`, `state`
- `error`: `agent_id`, `error`
- `register|deregister|spawn|stop`: `agent_id`

## Phase 1 compatibility behaviors

1. `ping` request -> `pong` response with same `correlation_id`.
2. `execute` request -> `result` response with:
   - same `correlation_id`
   - same `agent_id`
   - `state` echoed
   - `reply` = input `message`
3. Malformed frame or invalid envelope:
   - connection is closed by server
   - no response frame is guaranteed

## Cross-runtime integration test contract

Initial integration test cases to implement (Python test suite against running Elixir server):

1. `test_elixir_ping_pong_roundtrip`
2. `test_elixir_execute_result_roundtrip`
3. `test_elixir_rejects_unknown_message_type`
4. `test_elixir_rejects_malformed_msgpack`

## Startup contract

The Elixir runtime must expose the listen port via one of:

- stdout structured line (recommended): `PYRE_BRIDGE_PORT=<port>`
- or file output to a known path

Python integration harness will:

1. spawn Elixir runtime process
2. discover port
3. run roundtrip tests
4. terminate process
