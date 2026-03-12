defmodule PyreBridge.Application do
  @moduledoc false
  use Application

  @impl true
  def start(_type, _args) do
    children = [
      {Registry, keys: :unique, name: PyreBridge.AgentRegistry},
      {Registry, keys: :unique, name: PyreBridge.SupervisorRegistry},
      {PyreBridge.AgentSupervisor, []},
      {PyreBridge.BridgeServer, []}
    ]

    Supervisor.start_link(children, strategy: :one_for_one, name: PyreBridge.Supervisor)
  end
end
