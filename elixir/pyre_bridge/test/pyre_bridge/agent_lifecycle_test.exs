defmodule PyreBridge.AgentLifecycleTest do
  use ExUnit.Case, async: false

  # Some cases deliberately crash the handler to verify lifecycle semantics;
  # silence the expected :error logs to keep the output readable.
  @moduletag capture_log: true

  alias PyreBridge.AgentServer
  alias PyreBridge.AgentSupervisor
  alias PyreBridge.TestSupport.CounterHandler

  test "spawn call cast and restart semantics" do
    name = "counter-lifecycle-#{System.unique_integer([:positive])}"

    assert {:ok, _pid} =
             AgentSupervisor.start_agent(
               name: name,
               handler_module: CounterHandler,
               args: %{initial: 2}
             )

    assert {:ok, 2} = AgentServer.call(name, "get", %{})
    assert {:ok, 5} = AgentServer.call(name, "increment", %{"amount" => 3})
    assert :ok = AgentServer.cast(name, "increment", %{"amount" => 2})
    assert {:ok, 7} = AgentServer.call(name, "get", %{})

    assert {:error, :boom} = AgentServer.call(name, "boom", %{})

    # restart under transient strategy resets state via init args
    assert {:ok, 2} = wait_until_get(name, 10)
  end

  defp wait_until_get(name, remaining_attempts) when remaining_attempts > 0 do
    case AgentServer.call(name, "get", %{}) do
      {:ok, _value} = ok ->
        ok

      {:error, _reason} ->
        Process.sleep(10)
        wait_until_get(name, remaining_attempts - 1)
    end
  end

  defp wait_until_get(_name, 0), do: {:error, :timeout}
end
