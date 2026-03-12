defmodule PyreBridge.AgentGroupSupervisor do
  @moduledoc """
  Named supervisor group for Phase 3 strategy semantics.
  """

  use Supervisor

  @type strategy :: :one_for_one | :one_for_all | :rest_for_one

  @spec start_link(keyword()) :: Supervisor.on_start()
  def start_link(opts) do
    name = Keyword.fetch!(opts, :name)
    config = %{
      strategy: Keyword.get(opts, :strategy, :one_for_one),
      max_restarts: Keyword.get(opts, :max_restarts, 3),
      max_seconds: Keyword.get(opts, :max_seconds, 5)
    }

    Supervisor.start_link(__MODULE__, config, name: via(name))
  end

  @spec via(String.t()) :: {:via, Registry, {module(), String.t()}}
  def via(name) do
    {:via, Registry, {PyreBridge.SupervisorRegistry, name}}
  end

  @impl true
  def init(%{strategy: strategy, max_restarts: max_restarts, max_seconds: max_seconds})
      when strategy in [:one_for_one, :one_for_all, :rest_for_one] and
             is_integer(max_restarts) and max_restarts > 0 and
             is_integer(max_seconds) and max_seconds > 0 do
    Supervisor.init(
      [],
      strategy: strategy,
      max_restarts: max_restarts,
      max_seconds: max_seconds
    )
  end
end
