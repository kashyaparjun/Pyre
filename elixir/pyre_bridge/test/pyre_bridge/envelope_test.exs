defmodule PyreBridge.EnvelopeTest do
  use ExUnit.Case, async: true

  alias PyreBridge.Envelope

  test "validates execute envelope with required fields" do
    envelope = %{
      correlation_id: "123e4567-e89b-12d3-a456-426614174000",
      type: "execute",
      agent_id: "agent-1",
      handler: "handle_call",
      state: <<1, 2, 3>>,
      message: <<4, 5, 6>>
    }

    assert {:ok, ^envelope} = Envelope.validate(envelope)
  end

  test "returns error for unknown type" do
    envelope = %{correlation_id: "123e4567-e89b-12d3-a456-426614174000", type: "bad"}
    assert {:error, :invalid_message_type} = Envelope.validate(envelope)
  end

  test "returns missing fields for execute without handler" do
    envelope = %{
      correlation_id: "123e4567-e89b-12d3-a456-426614174000",
      type: "execute",
      agent_id: "agent-1",
      state: <<1>>,
      message: <<2>>
    }

    assert {:error, {:missing_fields, [:handler]}} = Envelope.validate(envelope)
  end
end
