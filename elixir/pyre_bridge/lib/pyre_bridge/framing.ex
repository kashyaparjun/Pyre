defmodule PyreBridge.Framing do
  @moduledoc """
  4-byte big-endian length-prefixed framing for bridge messages.
  """

  @header_size 4
  @max_uint32 4_294_967_295

  @spec write_frame(port(), iodata()) :: :ok | {:error, term()}
  def write_frame(socket, payload) do
    binary_payload = IO.iodata_to_binary(payload)
    length = byte_size(binary_payload)

    if length > @max_uint32 do
      {:error, :frame_too_large}
    else
      header = <<length::unsigned-big-32>>
      :gen_tcp.send(socket, header <> binary_payload)
    end
  end

  @spec read_frame(port(), timeout()) :: {:ok, binary()} | {:error, term()}
  def read_frame(socket, timeout_ms \\ 5_000) do
    with {:ok, <<payload_size::unsigned-big-32>>} <- :gen_tcp.recv(socket, @header_size, timeout_ms),
         {:ok, payload} <- :gen_tcp.recv(socket, payload_size, timeout_ms) do
      {:ok, payload}
    end
  end
end
