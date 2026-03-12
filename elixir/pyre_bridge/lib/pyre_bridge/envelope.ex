defmodule PyreBridge.Envelope do
  @moduledoc """
  Envelope validation helpers for bridge protocol messages.
  """

  @message_types [
    "execute",
    "result",
    "error",
    "register",
    "deregister",
    "spawn",
    "stop",
    "ping",
    "pong"
  ]

  @required_fields_by_type %{
    "execute" => [:correlation_id, :type, :agent_id, :handler, :state, :message],
    "result" => [:correlation_id, :type, :agent_id, :state],
    "error" => [:correlation_id, :type, :agent_id, :error],
    "register" => [:correlation_id, :type, :agent_id],
    "deregister" => [:correlation_id, :type, :agent_id],
    "spawn" => [:correlation_id, :type, :agent_id],
    "stop" => [:correlation_id, :type, :agent_id],
    "ping" => [:correlation_id, :type],
    "pong" => [:correlation_id, :type]
  }

  @spec validate(map()) :: {:ok, map()} | {:error, term()}
  def validate(%{} = envelope) do
    with :ok <- validate_type(envelope),
         :ok <- validate_required_fields(envelope) do
      {:ok, envelope}
    end
  end

  defp validate_type(%{type: type}) when type in @message_types, do: :ok
  defp validate_type(%{"type" => type}) when type in @message_types, do: :ok
  defp validate_type(_), do: {:error, :invalid_message_type}

  defp validate_required_fields(envelope) do
    type = Map.get(envelope, :type) || Map.get(envelope, "type")
    required_fields = Map.fetch!(@required_fields_by_type, type)

    missing =
      Enum.filter(required_fields, fn key ->
        is_nil(Map.get(envelope, key)) and is_nil(Map.get(envelope, Atom.to_string(key)))
      end)

    case missing do
      [] -> :ok
      _ -> {:error, {:missing_fields, missing}}
    end
  end
end
