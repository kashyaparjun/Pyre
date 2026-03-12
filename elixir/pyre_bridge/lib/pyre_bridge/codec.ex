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
    "error"
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

  @spec unpack_envelope(binary()) :: {:ok, map()} | {:error, term()}
  def unpack_envelope(payload) when is_binary(payload) do
    with {:ok, unpacked} <- unpack_payload(payload),
         true <- is_map(unpacked),
         normalized <- normalize_from_wire(unpacked),
         {:ok, validated} <- Envelope.validate(normalized) do
      {:ok, validated}
    else
      false -> {:error, :envelope_not_map}
      {:error, _} = err -> err
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
    Enum.reduce(envelope, %{}, fn {key, value}, acc ->
      case normalize_key(key) do
        nil -> acc
        normalized_key -> Map.put(acc, normalized_key, normalize_term(value))
      end
    end)
  end

  defp normalize_key(%Msgpax.Bin{data: data}) when is_binary(data), do: normalize_key(data)

  defp normalize_key(key) when is_binary(key) and key in @allowed_keys do
    String.to_existing_atom(key)
  end

  defp normalize_key(key) when is_atom(key), do: key
  defp normalize_key(_), do: nil

  defp normalize_term(%Msgpax.Bin{data: data}), do: data

  defp normalize_term(%{} = map) do
    Enum.reduce(map, %{}, fn {key, value}, acc ->
      case normalize_key(key) do
        nil -> acc
        normalized_key -> Map.put(acc, normalized_key, normalize_term(value))
      end
    end)
  end

  defp normalize_term(list) when is_list(list), do: Enum.map(list, &normalize_term/1)
  defp normalize_term(other), do: other
end
