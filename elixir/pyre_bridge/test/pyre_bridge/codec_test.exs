defmodule PyreBridge.CodecTest do
  use ExUnit.Case, async: true

  alias PyreBridge.Codec

  test "round trips additive busy fields and nested error payload" do
    envelope = %{
      correlation_id: "123e4567-e89b-12d3-a456-426614174000",
      type: "error",
      agent_id: "agent-1",
      error: %{type: "busy", message: "bridge saturated", stack: "trace"},
      queue_depth: 42,
      retry_after_ms: 15,
      busy_reason: "execution_pool_limit"
    }

    assert {:ok, payload} = Codec.pack_envelope(envelope)
    assert {:ok, decoded} = Codec.unpack_envelope(IO.iodata_to_binary(payload))

    assert decoded.correlation_id == envelope.correlation_id
    assert decoded.type == "error"
    assert decoded.agent_id == envelope.agent_id
    assert decoded.queue_depth == 42
    assert decoded.retry_after_ms == 15
    assert decoded.busy_reason == "execution_pool_limit"
    assert decoded.error["type"] == "busy"
    assert decoded.error["message"] == "bridge saturated"
    assert decoded.error["stack"] == "trace"
  end
end
