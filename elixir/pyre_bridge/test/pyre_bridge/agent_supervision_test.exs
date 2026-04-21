defmodule PyreBridge.AgentSupervisionTest do
  use ExUnit.Case, async: false

  # Supervision tests deliberately crash agents to exercise restart semantics;
  # GenServer logs those crashes at :error level. Capture them so the test
  # output stays readable instead of flooding the terminal with expected noise.
  @moduletag capture_log: true

  alias PyreBridge.AgentServer
  alias PyreBridge.AgentSupervisor
  alias PyreBridge.TestSupport.CounterHandler

  test "one_for_one restarts only crashed child" do
    group = unique("one-for-one")
    assert {:ok, _pid} = AgentSupervisor.create_group(group, strategy: :one_for_one)

    a = unique("a")
    b = unique("b")

    spawn_counter(a, 1, group)
    spawn_counter(b, 10, group)
    assert {:ok, 6} = AgentServer.call(a, "increment", %{"amount" => 5})
    assert {:ok, 12} = AgentServer.call(b, "increment", %{"amount" => 2})

    assert {:error, :boom} = AgentServer.call(a, "boom", %{})

    assert {:ok, 1} = wait_until_get(a, 20)
    assert {:ok, 12} = wait_until_get(b, 20)
  end

  test "one_for_all restarts all siblings" do
    group = unique("one-for-all")
    assert {:ok, _pid} = AgentSupervisor.create_group(group, strategy: :one_for_all)

    a = unique("a")
    b = unique("b")

    spawn_counter(a, 1, group)
    spawn_counter(b, 10, group)
    assert {:ok, 6} = AgentServer.call(a, "increment", %{"amount" => 5})
    assert {:ok, 12} = AgentServer.call(b, "increment", %{"amount" => 2})

    assert {:error, :boom} = AgentServer.call(a, "boom", %{})

    assert {:ok, 1} = wait_until_get(a, 20)
    assert {:ok, 10} = wait_until_get(b, 20)
  end

  test "rest_for_one restarts crashed child and younger siblings only" do
    group = unique("rest-for-one")
    assert {:ok, _pid} = AgentSupervisor.create_group(group, strategy: :rest_for_one)

    first = unique("first")
    second = unique("second")
    third = unique("third")

    spawn_counter(first, 1, group)
    spawn_counter(second, 10, group)
    spawn_counter(third, 100, group)
    assert {:ok, 6} = AgentServer.call(first, "increment", %{"amount" => 5})
    assert {:ok, 15} = AgentServer.call(second, "increment", %{"amount" => 5})
    assert {:ok, 105} = AgentServer.call(third, "increment", %{"amount" => 5})

    assert {:error, :boom} = AgentServer.call(second, "boom", %{})

    assert {:ok, 6} = wait_until_get(first, 20)
    assert {:ok, 10} = wait_until_get(second, 20)
    assert {:ok, 100} = wait_until_get(third, 20)
  end

  test "nested group restart does not escape to parent group" do
    parent = unique("parent")
    child = unique("child")

    assert {:ok, _pid} = AgentSupervisor.create_group(parent, strategy: :one_for_all)
    assert {:ok, _pid} = AgentSupervisor.create_group(child, strategy: :rest_for_one, parent: parent)

    parent_agent = unique("parent-agent")
    child_one = unique("child-one")
    child_two = unique("child-two")

    spawn_counter(parent_agent, 50, parent)
    spawn_counter(child_one, 1, child)
    spawn_counter(child_two, 10, child)
    assert {:ok, 52} = AgentServer.call(parent_agent, "increment", %{"amount" => 2})
    assert {:ok, 4} = AgentServer.call(child_one, "increment", %{"amount" => 3})
    assert {:ok, 14} = AgentServer.call(child_two, "increment", %{"amount" => 4})

    assert {:error, :boom} = AgentServer.call(child_one, "boom", %{})

    assert {:ok, 52} = wait_until_get(parent_agent, 20)
    assert {:ok, 1} = wait_until_get(child_one, 20)
    assert {:ok, 10} = wait_until_get(child_two, 20)
  end

  test "group restart intensity eventually tears down all group members" do
    group = unique("intensity")

    assert {:ok, _pid} =
             AgentSupervisor.create_group(
               group,
               strategy: :one_for_all,
               max_restarts: 1,
               max_seconds: 60
             )

    first = unique("first")
    second = unique("second")
    spawn_counter(first, 1, group)
    spawn_counter(second, 10, group)

    assert {:error, :boom} = AgentServer.call(first, "boom", %{})
    assert {:ok, 1} = wait_until_get(first, 20)
    assert {:error, :boom} = AgentServer.call(first, "boom", %{})

    assert :ok = wait_until_group_down(group, 20)

    assert {:error, :noproc} = AgentServer.call(first, "get", %{})
    assert {:error, :noproc} = AgentServer.call(second, "get", %{})
  end

  defp spawn_counter(name, initial, group) do
    assert {:ok, _pid} =
             AgentSupervisor.start_agent(
               name: name,
               handler_module: CounterHandler,
               args: %{initial: initial},
               group: group
             )
  end

  defp unique(prefix), do: "#{prefix}-#{System.unique_integer([:positive])}"

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

  defp wait_until_group_down(group, remaining_attempts) when remaining_attempts > 0 do
    case Registry.lookup(PyreBridge.SupervisorRegistry, group) do
      [] ->
        :ok

      [{_pid, _value}] ->
        Process.sleep(10)
        wait_until_group_down(group, remaining_attempts - 1)
    end
  end

  defp wait_until_group_down(_group, 0), do: {:error, :timeout}
end
