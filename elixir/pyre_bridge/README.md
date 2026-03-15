# Pyre Bridge (Elixir)

Elixir bridge runtime for Pyre cross-runtime lifecycle and supervision tests.

## Current scope

- Length-prefixed framing (`PyreBridge.Framing`)
- MessagePack codec (`PyreBridge.Codec`) via `msgpax`
- Envelope validation (`PyreBridge.Envelope`)
- TCP loopback bridge server (`PyreBridge.BridgeServer`)
- Per-connection request loop (`PyreBridge.BridgeConnection`)
- Agent lifecycle operations (`spawn`, `execute`, `stop`)
- Group supervision strategies (`one_for_one`, `one_for_all`, `rest_for_one`)
- Environment-driven runtime configuration for host/port/timeouts

## Runtime configuration

The bridge reads these environment variables at startup:

- `PYRE_BRIDGE_HOST` (default `127.0.0.1`)
- `PYRE_BRIDGE_PORT` (default `4100`; `0` requests an ephemeral port)
- `PYRE_BRIDGE_RECV_TIMEOUT_MS` (default `5000`)
- `PYRE_BRIDGE_GROUP_MAX_RESTARTS` (default `3`)
- `PYRE_BRIDGE_GROUP_MAX_SECONDS` (default `5`)

The integration launcher at `scripts/start_bridge.exs` overrides `PYRE_BRIDGE_PORT` to `0`
and prints `PYRE_BRIDGE_PORT=<port>` after boot so Python tests can discover the listener.

## Verification

```bash
mix test
mix run --no-start scripts/start_bridge.exs
```

## Notes

- The bridge currently uses TCP loopback (`127.0.0.1`).
- Target production transport remains Unix domain sockets as defined in the architecture docs.
