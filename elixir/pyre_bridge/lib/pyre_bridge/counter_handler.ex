defmodule PyreBridge.CounterHandler do
  @moduledoc """
  Minimal built-in counter handler used by bridge spawn/execute flows.
  """

  @behaviour PyreBridge.AgentHandler

  @impl true
  def init(args) do
    {:ok, %{count: Map.get(args, :initial, 0)}}
  end

  @impl true
  def handle_call(state, "get", _payload) do
    {:ok, state.count, state}
  end

  def handle_call(state, "increment", payload) do
    amount = Map.get(payload, "amount", 1)
    next_state = %{state | count: state.count + amount}
    {:ok, next_state.count, next_state}
  end

  def handle_call(_state, "boom", _payload) do
    {:error, :boom}
  end

  def handle_call(_state, _type, _payload) do
    {:error, :unknown_call}
  end

  @impl true
  def handle_cast(state, "increment", payload) do
    amount = Map.get(payload, "amount", 1)
    {:ok, %{state | count: state.count + amount}}
  end

  def handle_cast(state, _type, _payload) do
    {:ok, state}
  end
end
