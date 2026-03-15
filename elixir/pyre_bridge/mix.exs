defmodule PyreBridge.MixProject do
  use Mix.Project

  def project do
    [
      app: :pyre_bridge,
      version: "0.1.0",
      description: "Elixir bridge runtime for the Pyre Python agent framework.",
      elixir: "~> 1.16",
      elixirc_paths: elixirc_paths(Mix.env()),
      start_permanent: Mix.env() == :prod,
      deps: deps(),
      package: package()
    ]
  end

  def application do
    [
      extra_applications: [:logger],
      mod: {PyreBridge.Application, []}
    ]
  end

  defp deps do
    [
      {:msgpax, "~> 2.4"}
    ]
  end

  defp package do
    [
      files: ~w(lib config mix.exs README.md),
      licenses: ["MIT"]
    ]
  end

  defp elixirc_paths(:test), do: ["lib", "test/support"]
  defp elixirc_paths(_), do: ["lib"]
end
