defmodule PyreBridge.AgentHandler do
  @moduledoc """
  Behavior contract for Phase 2 agent handlers.
  """

  @callback init(map()) :: {:ok, term()} | {:error, term()}
  @callback handle_call(term(), String.t(), map()) :: {:ok, term(), term()} | {:error, term()}
  @callback handle_cast(term(), String.t(), map()) :: {:ok, term()} | {:error, term()}
end
