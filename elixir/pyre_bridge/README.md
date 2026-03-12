# Pyre Bridge (Elixir)

Phase 1 Elixir bridge runtime scaffold.

## Current scope

- Length-prefixed framing (`PyreBridge.Framing`)
- MessagePack codec (`PyreBridge.Codec`) via `msgpax`
- Envelope validation (`PyreBridge.Envelope`)
- TCP loopback server spike (`PyreBridge.BridgeServer`)
- Per-connection request loop (`PyreBridge.BridgeConnection`)

## Notes

- This is a Phase 1 spike and currently uses TCP loopback (`127.0.0.1`).
- Target production transport remains Unix domain sockets as defined in the architecture docs.
- `mix` is required locally to build/run this project; it is not available in the current execution environment.
