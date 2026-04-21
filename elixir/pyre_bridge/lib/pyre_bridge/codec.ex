defmodule PyreBridge.Codec do
  @moduledoc """
  MessagePack codec helpers for bridge payloads.
  """

  alias PyreBridge.Envelope

  @allowed_keys [
    "correlation_id",
    "type",
    "agent_id",
    "handler",
    "state",
    "message",
    "reply",
    "error",
    "queue_depth",
    "retry_after_ms",
    "busy_reason"
  ]

  @spec pack_payload(term()) :: {:ok, binary()} | {:error, term()}
  def pack_payload(payload) do
    Msgpax.pack(payload)
  end

  @spec unpack_payload(binary()) :: {:ok, term()} | {:error, term()}
  def unpack_payload(payload) when is_binary(payload) do
    Msgpax.unpack(payload)
  end

  @spec pack_envelope(map()) :: {:ok, binary()} | {:error, term()}
  def pack_envelope(envelope) when is_map(envelope) do
    with {:ok, normalized} <- normalize_for_wire(envelope) do
      pack_payload(normalized)
    end
  end

  @known_message_types ~w(execute result error register deregister spawn stop ping pong)

  @spec unpack_envelope(binary()) :: {:ok, map()} | {:error, term()}
  def unpack_envelope(payload) when is_binary(payload) do
    # Cheap validation on the hot path: ensure the payload is a map with a
    # known message type. Full required-field validation stays off the hot
    # path (callers that need it can still call Envelope.validate/1).
    with {:ok, unpacked} <- unpack_payload(payload),
         {:ok, envelope_map} <- ensure_map(unpacked),
         normalized = normalize_from_wire(envelope_map),
         {:ok, _} <- ensure_known_type(normalized) do
      {:ok, normalized}
    end
  end

  defp ensure_map(value) when is_map(value), do: {:ok, value}
  defp ensure_map(_), do: {:error, :envelope_not_map}

  defp ensure_known_type(envelope) do
    case Map.get(envelope, :type) || Map.get(envelope, "type") do
      type when type in @known_message_types -> {:ok, type}
      _ -> {:error, :unknown_message_type}
    end
  end

  defp normalize_for_wire(envelope) do
    atom_keys_map =
      Enum.reduce(envelope, %{}, fn {key, value}, acc ->
        string_key = if is_atom(key), do: Atom.to_string(key), else: key

        normalized_value =
          if string_key in ["state", "message", "reply"] and is_binary(value) do
            %Msgpax.Bin{data: value}
          else
            value
          end

        Map.put(acc, string_key, normalized_value)
      end)

    {:ok, atom_keys_map}
  end

  defp normalize_from_wire(%{} = envelope) do
    # Optimized: Remove allowed_keys filtering for better throughput
    Enum.reduce(envelope, %{}, fn {key, value}, acc ->
      normalized_key = normalize_key_fast(key)
      Map.put(acc, normalized_key, normalize_term(value))
    end)
  end

  defp normalize_key_fast(%Msgpax.Bin{data: data}) when is_binary(data),
    do: normalize_key_fast(data)

  defp normalize_key_fast(key) when is_binary(key) do
    # Optimized: Use String.to_atom instead of to_existing_atom for speed
    String.to_atom(key)
  end

  defp normalize_key_fast(key) when is_atom(key), do: key
  defp normalize_key_fast(other), do: other

  defp normalize_term(%Msgpax.Bin{data: data}), do: data

  defp normalize_term(%{} = map) do
    Enum.reduce(map, %{}, fn {key, value}, acc ->
      Map.put(acc, normalize_nested_key(key), normalize_term(value))
    end)
  end

  defp normalize_term(list) when is_list(list), do: Enum.map(list, &normalize_term/1)
  defp normalize_term(other), do: other

  defp normalize_nested_key(%Msgpax.Bin{data: data}) when is_binary(data), do: data
  defp normalize_nested_key(key) when is_binary(key), do: key
  defp normalize_nested_key(key) when is_atom(key), do: Atom.to_string(key)
  defp normalize_nested_key(other), do: other
end
