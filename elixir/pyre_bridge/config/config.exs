import Config

config :pyre_bridge,
  transport: :tcp,
  host: {127, 0, 0, 1},
  port: 4100,
  recv_timeout_ms: 5_000
