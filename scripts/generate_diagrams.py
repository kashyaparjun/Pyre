"""Generate architectural diagrams for Pyre whitepaper."""

from pathlib import Path

import svgwrite

output_dir = Path("/Users/arjun/Documents/Pyre/docs/diagrams")
output_dir.mkdir(exist_ok=True)


def create_concurrency_comparison():
    """Diagram 1: Python concurrency options comparison."""
    dwg = svgwrite.Drawing(str(output_dir / "01-concurrency-comparison.svg"), size=(800, 500))

    # Title
    dwg.add(
        dwg.text(
            "Python Concurrency Options: Memory vs Failure Modes",
            insert=(400, 30),
            text_anchor="middle",
            font_size="20",
            font_weight="bold",
        )
    )

    # Three columns
    columns = [
        ("asyncio", "Cooperative", "~KB/coroutine", "Blocking call\nstalls ALL agents", "#FFE4E1"),
        ("Threading", "OS Threads", "1-8MB/thread", "GIL bound\n100+ threads degrade", "#FFF8DC"),
        (
            "Multiprocessing",
            "OS Processes",
            "10-50MB/process",
            "Serialization\noverhead dominates",
            "#F0F8FF",
        ),
    ]

    x_positions = [133, 400, 666]

    for i, (name, model, memory, failure, color) in enumerate(columns):
        x = x_positions[i]

        # Column background
        dwg.add(
            dwg.rect(
                insert=(x - 100, 60),
                size=(200, 400),
                fill=color,
                stroke="#333",
                stroke_width=2,
                rx=10,
            )
        )

        # Title
        dwg.add(
            dwg.text(name, insert=(x, 90), text_anchor="middle", font_size="18", font_weight="bold")
        )

        # Model
        dwg.add(
            dwg.text(
                "Model:", insert=(x, 130), text_anchor="middle", font_size="12", font_weight="bold"
            )
        )
        dwg.add(dwg.text(model, insert=(x, 150), text_anchor="middle", font_size="11"))

        # Memory
        dwg.add(
            dwg.text(
                "Memory:", insert=(x, 190), text_anchor="middle", font_size="12", font_weight="bold"
            )
        )
        dwg.add(dwg.text(memory, insert=(x, 210), text_anchor="middle", font_size="11"))

        # Visual representation
        if i == 0:  # asyncio - single event loop
            dwg.add(dwg.rect(insert=(x - 60, 240), size=(120, 30), fill="#FF6B6B", rx=5))
            dwg.add(
                dwg.text(
                    "Event Loop",
                    insert=(x, 260),
                    text_anchor="middle",
                    font_size="10",
                    fill="white",
                )
            )
            for j in range(5):
                dwg.add(
                    dwg.rect(insert=(x - 50 + j * 22, 280), size=(18, 20), fill="#4ECDC4", rx=3)
                )
            dwg.add(dwg.text("50 coroutines", insert=(x, 315), text_anchor="middle", font_size="9"))

        elif i == 1:  # threading - multiple threads
            for j in range(3):
                dwg.add(
                    dwg.rect(insert=(x - 40, 240 + j * 35), size=(80, 25), fill="#95E1D3", rx=5)
                )
                dwg.add(
                    dwg.text(
                        f"Thread {j + 1}",
                        insert=(x, 255 + j * 35),
                        text_anchor="middle",
                        font_size="9",
                    )
                )
            dwg.add(
                dwg.text("~100 threads max", insert=(x, 345), text_anchor="middle", font_size="9")
            )

        else:  # multiprocessing - separate processes
            for j in range(2):
                dwg.add(
                    dwg.rect(
                        insert=(x - 45, 240 + j * 50),
                        size=(90, 35),
                        fill="#FFA07A",
                        rx=5,
                        stroke="#333",
                    )
                )
                dwg.add(
                    dwg.text(
                        f"Process {j + 1}",
                        insert=(x, 262 + j * 50),
                        text_anchor="middle",
                        font_size="10",
                    )
                )
            dwg.add(
                dwg.text("High IPC overhead", insert=(x, 345), text_anchor="middle", font_size="9")
            )

        # Failure mode
        dwg.add(
            dwg.text(
                "Failure Mode:",
                insert=(x, 375),
                text_anchor="middle",
                font_size="12",
                font_weight="bold",
            )
        )
        dwg.add(dwg.text(failure, insert=(x, 400), text_anchor="middle", font_size="10"))

    # Red X on asyncio failure point
    dwg.add(dwg.text("❌", insert=(x_positions[0], 290), text_anchor="middle", font_size="24"))

    dwg.save()
    print(f"✓ Created: {output_dir / '01-concurrency-comparison.svg'}")


def create_beam_process_model():
    """Diagram 2: BEAM process memory model."""
    dwg = svgwrite.Drawing(str(output_dir / "02-beam-process-model.svg"), size=(700, 500))

    # Title
    dwg.add(
        dwg.text(
            "BEAM Process Model: Isolated Heaps & Mailboxes",
            insert=(350, 30),
            text_anchor="middle",
            font_size="20",
            font_weight="bold",
        )
    )

    # Draw multiple BEAM processes
    process_positions = [(150, 100), (350, 100), (550, 100)]

    for i, (px, py) in enumerate(process_positions):
        # Process box
        dwg.add(
            dwg.rect(
                insert=(px - 70, py),
                size=(140, 180),
                fill="#E8F5E9",
                stroke="#2E7D32",
                stroke_width=2,
                rx=10,
            )
        )

        # Process header
        dwg.add(dwg.rect(insert=(px - 70, py), size=(140, 30), fill="#2E7D32", rx=10))
        dwg.add(
            dwg.text(
                f"BEAM Process {i + 1}",
                insert=(px, py + 20),
                text_anchor="middle",
                font_size="12",
                fill="white",
                font_weight="bold",
            )
        )

        # Heap section
        dwg.add(
            dwg.rect(
                insert=(px - 60, py + 40), size=(120, 50), fill="#C8E6C9", stroke="#2E7D32", rx=5
            )
        )
        dwg.add(dwg.text("Heap (~2KB)", insert=(px, py + 70), text_anchor="middle", font_size="10"))

        # GC indicator
        dwg.add(
            dwg.text(
                "Own GC ✓",
                insert=(px, py + 87),
                text_anchor="middle",
                font_size="8",
                fill="#2E7D32",
            )
        )

        # Mailbox section
        dwg.add(
            dwg.rect(
                insert=(px - 60, py + 105), size=(120, 60), fill="#BBDEFB", stroke="#1976D2", rx=5
            )
        )
        dwg.add(
            dwg.text(
                "Mailbox",
                insert=(px, py + 125),
                text_anchor="middle",
                font_size="11",
                font_weight="bold",
            )
        )

        # Messages in mailbox
        for j in range(3):
            dwg.add(
                dwg.rect(
                    insert=(px - 50 + j * 35, py + 135),
                    size=(30, 20),
                    fill="#E3F2FD",
                    stroke="#1976D2",
                    rx=3,
                )
            )

        dwg.add(dwg.text("async msgs", insert=(px, py + 172), text_anchor="middle", font_size="8"))

    # Arrows showing message passing
    for i in range(len(process_positions) - 1):
        px1 = process_positions[i][0] + 70
        px2 = process_positions[i + 1][0] - 70
        y = process_positions[i][1] + 135

        dwg.add(
            dwg.line(
                start=(px1, y), end=(px2, y), stroke="#666", stroke_width=2, stroke_dasharray="5,3"
            )
        )
        dwg.add(dwg.polygon(points=[(px2 - 10, y - 5), (px2, y), (px2 - 10, y + 5)], fill="#666"))

    # Key stats
    stats_y = 320
    dwg.add(
        dwg.text(
            "Key Characteristics:",
            insert=(350, stats_y),
            text_anchor="middle",
            font_size="14",
            font_weight="bold",
        )
    )

    stats = [
        "✓ Millions of processes per node",
        "✓ Preemptive scheduling (no starvation)",
        "✓ Message passing (no shared memory)",
        "✓ Natural backpressure via mailboxes",
    ]

    for i, stat in enumerate(stats):
        dwg.add(
            dwg.text(
                stat, insert=(350, stats_y + 30 + i * 25), text_anchor="middle", font_size="11"
            )
        )

    # Scale comparison
    dwg.add(
        dwg.text(
            "10,000 agents = ~30MB total",
            insert=(350, 450),
            text_anchor="middle",
            font_size="14",
            font_weight="bold",
            fill="#2E7D32",
        )
    )

    dwg.save()
    print(f"✓ Created: {output_dir / '02-beam-process-model.svg'}")


def create_pyre_architecture():
    """Diagram 3: Pyre dual-runtime architecture."""
    dwg = svgwrite.Drawing(str(output_dir / "03-pyre-architecture.svg"), size=(800, 550))

    # Title
    dwg.add(
        dwg.text(
            "Pyre Dual-Runtime Architecture",
            insert=(400, 30),
            text_anchor="middle",
            font_size="22",
            font_weight="bold",
        )
    )

    # Python Process (left)
    dwg.add(
        dwg.rect(
            insert=(50, 80),
            size=(300, 400),
            fill="#FFF3E0",
            stroke="#E65100",
            stroke_width=3,
            rx=15,
        )
    )
    dwg.add(dwg.rect(insert=(50, 80), size=(300, 40), fill="#E65100", rx=15))
    dwg.add(
        dwg.text(
            "Python Process (CPython)",
            insert=(200, 105),
            text_anchor="middle",
            font_size="16",
            fill="white",
            font_weight="bold",
        )
    )

    # Python components
    py_components = [
        ("Agent Handler", "Your Python code:\nLLM calls, tools, logic"),
        ("Pydantic Models", "State validation &\nserialization"),
        ("Bridge Client", "MessagePack +\nUnix socket"),
    ]

    for i, (title, desc) in enumerate(py_components):
        y = 150 + i * 100
        dwg.add(
            dwg.rect(
                insert=(80, y), size=(240, 70), fill="white", stroke="#E65100", stroke_width=2, rx=8
            )
        )
        dwg.add(
            dwg.text(
                title,
                insert=(200, y + 20),
                text_anchor="middle",
                font_size="12",
                font_weight="bold",
            )
        )
        lines = desc.split("\n")
        for j, line in enumerate(lines):
            dwg.add(
                dwg.text(line, insert=(200, y + 40 + j * 15), text_anchor="middle", font_size="10")
            )

    # Bridge (center)
    dwg.add(
        dwg.rect(
            insert=(360, 200),
            size=(80, 160),
            fill="#E3F2FD",
            stroke="#1976D2",
            stroke_width=3,
            rx=10,
        )
    )
    dwg.add(
        dwg.text(
            "IPC",
            insert=(400, 260),
            text_anchor="middle",
            font_size="14",
            font_weight="bold",
            fill="#1976D2",
        )
    )
    dwg.add(
        dwg.text(
            "Bridge",
            insert=(400, 280),
            text_anchor="middle",
            font_size="14",
            font_weight="bold",
            fill="#1976D2",
        )
    )
    dwg.add(dwg.text("0.1-0.3ms", insert=(400, 330), text_anchor="middle", font_size="10"))

    # Double-headed arrow
    dwg.add(dwg.polygon(points=[(340, 250), (350, 245), (350, 255)], fill="#1976D2"))
    dwg.add(dwg.polygon(points=[(460, 250), (450, 245), (450, 255)], fill="#1976D2"))

    # Elixir Process (right)
    dwg.add(
        dwg.rect(
            insert=(450, 80),
            size=(300, 400),
            fill="#E8F5E9",
            stroke="#2E7D32",
            stroke_width=3,
            rx=15,
        )
    )
    dwg.add(dwg.rect(insert=(450, 80), size=(300, 40), fill="#2E7D32", rx=15))
    dwg.add(
        dwg.text(
            "Elixir Node (BEAM)",
            insert=(600, 105),
            text_anchor="middle",
            font_size="16",
            fill="white",
            font_weight="bold",
        )
    )

    # Elixir components
    ex_components = [
        ("GenServers", "One per agent\nStateful processes"),
        ("OTP Supervisors", "Automatic crash\nrecovery trees"),
        ("Bridge Server", "Message routing &\nconnection mgmt"),
    ]

    for i, (title, desc) in enumerate(ex_components):
        y = 150 + i * 100
        dwg.add(
            dwg.rect(
                insert=(480, y),
                size=(240, 70),
                fill="white",
                stroke="#2E7D32",
                stroke_width=2,
                rx=8,
            )
        )
        dwg.add(
            dwg.text(
                title,
                insert=(600, y + 20),
                text_anchor="middle",
                font_size="12",
                font_weight="bold",
            )
        )
        lines = desc.split("\n")
        for j, line in enumerate(lines):
            dwg.add(
                dwg.text(line, insert=(600, y + 40 + j * 15), text_anchor="middle", font_size="10")
            )

    # Bottom stats
    dwg.add(
        dwg.text(
            "Developer Experience: Write pure Python • Never touch Elixir",
            insert=(400, 510),
            text_anchor="middle",
            font_size="13",
            font_style="italic",
        )
    )

    dwg.add(
        dwg.text(
            "Protocol: Unix Domain Socket + MessagePack + Length-Prefixed Framing",
            insert=(400, 530),
            text_anchor="middle",
            font_size="11",
        )
    )

    dwg.save()
    print(f"✓ Created: {output_dir / '03-pyre-architecture.svg'}")


def create_supervision_tree():
    """Diagram 4: OTP Supervision tree."""
    dwg = svgwrite.Drawing(str(output_dir / "04-supervision-tree.svg"), size=(700, 550))

    # Title
    dwg.add(
        dwg.text(
            "OTP Supervision Tree",
            insert=(350, 30),
            text_anchor="middle",
            font_size="20",
            font_weight="bold",
        )
    )

    # Root supervisor
    dwg.add(
        dwg.ellipse(center=(350, 80), r=(100, 30), fill="#C62828", stroke="#8B0000", stroke_width=2)
    )
    dwg.add(
        dwg.text(
            "PyreSystem (Root)",
            insert=(350, 85),
            text_anchor="middle",
            font_size="12",
            fill="white",
            font_weight="bold",
        )
    )

    # Level 2 - Group supervisors
    level2_x = [150, 350, 550]
    level2_names = [
        "Group Sup 1\n(one_for_one)",
        "AgentSupervisor\n(application)",
        "Group Sup 2\n(rest_for_one)",
    ]

    for i, (x, name) in enumerate(zip(level2_x, level2_names)):
        dwg.add(
            dwg.ellipse(
                center=(x, 180), r=(70, 25), fill="#F57C00", stroke="#E65100", stroke_width=2
            )
        )
        lines = name.split("\n")
        for j, line in enumerate(lines):
            dwg.add(
                dwg.text(
                    line,
                    insert=(x, 175 + j * 14),
                    text_anchor="middle",
                    font_size="10",
                    fill="white",
                    font_weight="bold" if j == 0 else "normal",
                )
            )

        # Line from root
        dwg.add(dwg.line(start=(350, 110), end=(x, 155), stroke="#666", stroke_width=2))

    # Level 3 - Agents
    agents_level3 = [
        [(80, 300), (150, 300), (220, 300)],  # Under Group Sup 1
        [(280, 300), (350, 300), (420, 300)],  # Under AgentSupervisor
        [(480, 300), (550, 300), (620, 300)],  # Under Group Sup 2
    ]

    for group_idx, agents in enumerate(agents_level3):
        parent_x = level2_x[group_idx]
        for agent_x, agent_y in agents:
            dwg.add(
                dwg.rect(
                    insert=(agent_x - 30, agent_y - 20),
                    size=(60, 40),
                    fill="#2E7D32",
                    stroke="#1B5E20",
                    stroke_width=2,
                    rx=5,
                )
            )
            dwg.add(
                dwg.text(
                    "Agent",
                    insert=(agent_x, agent_y),
                    text_anchor="middle",
                    font_size="9",
                    fill="white",
                )
            )

            # Line to parent
            dwg.add(
                dwg.line(
                    start=(parent_x, 205),
                    end=(agent_x, agent_y - 20),
                    stroke="#666",
                    stroke_width=1,
                )
            )

    # Legend
    legend_y = 380
    dwg.add(
        dwg.text(
            "Restart Strategies:",
            insert=(350, legend_y),
            text_anchor="middle",
            font_size="14",
            font_weight="bold",
        )
    )

    strategies = [
        ("one_for_one", "Only crashed child restarts"),
        ("one_for_all", "All children restart together"),
        ("rest_for_one", "Crashed + all children after it restart"),
    ]

    for i, (name, desc) in enumerate(strategies):
        dwg.add(
            dwg.text(
                f"• {name}: {desc}",
                insert=(350, legend_y + 30 + i * 25),
                text_anchor="middle",
                font_size="11",
            )
        )

    # Crash recovery illustration
    crash_y = 480
    dwg.add(
        dwg.text(
            "Crash Recovery Flow:",
            insert=(350, crash_y),
            text_anchor="middle",
            font_size="14",
            font_weight="bold",
        )
    )

    flow_steps = [
        ("Handler Exception", 120),
        ("→", 220),
        ("Bridge Error Msg", 280),
        ("→", 380),
        ("Supervisor Detects", 440),
        ("→", 520),
        ("Auto-Restart", 580),
    ]

    for text, x in flow_steps:
        if text == "→":
            dwg.add(
                dwg.text(
                    text,
                    insert=(x, crash_y + 35),
                    text_anchor="middle",
                    font_size="16",
                    font_weight="bold",
                )
            )
        else:
            dwg.add(
                dwg.rect(
                    insert=(x - 55, crash_y + 15),
                    size=(110, 30),
                    fill="#E3F2FD",
                    stroke="#1976D2",
                    rx=5,
                )
            )
            dwg.add(dwg.text(text, insert=(x, crash_y + 35), text_anchor="middle", font_size="9"))

    dwg.save()
    print(f"✓ Created: {output_dir / '04-supervision-tree.svg'}")


def create_connection_lifecycle():
    """Diagram 5: Connection lifecycle."""
    dwg = svgwrite.Drawing(str(output_dir / "05-connection-lifecycle.svg"), size=(800, 450))

    # Title
    dwg.add(
        dwg.text(
            "Bridge Connection Lifecycle",
            insert=(400, 30),
            text_anchor="middle",
            font_size="20",
            font_weight="bold",
        )
    )

    # Timeline steps
    steps = [
        ("1. Connection", "Pool creates\n8 connections"),
        ("2. Multiplexing", "64 in-flight\nper connection"),
        ("3. Request", "correlation_id\nrouting"),
        ("4. Response", "Future resolved\nwith result"),
        ("5. Backpressure", "Reject when\nsaturated"),
        ("6. Recovery", "Auto-reconnect\non failure"),
    ]

    step_width = 120
    start_x = 80

    for i, (title, desc) in enumerate(steps):
        x = start_x + i * step_width

        # Step box
        dwg.add(
            dwg.rect(
                insert=(x, 80),
                size=(100, 280),
                fill="#F5F5F5" if i % 2 == 0 else "#FAFAFA",
                stroke="#333",
                stroke_width=2,
                rx=8,
            )
        )

        # Step number circle
        dwg.add(dwg.ellipse(center=(x + 50, 110), r=(20, 20), fill="#1976D2"))
        dwg.add(
            dwg.text(
                str(i + 1),
                insert=(x + 50, 115),
                text_anchor="middle",
                font_size="16",
                fill="white",
                font_weight="bold",
            )
        )

        # Title
        dwg.add(
            dwg.text(
                title,
                insert=(x + 50, 150),
                text_anchor="middle",
                font_size="11",
                font_weight="bold",
            )
        )

        # Description
        lines = desc.split("\n")
        for j, line in enumerate(lines):
            dwg.add(
                dwg.text(line, insert=(x + 50, 180 + j * 18), text_anchor="middle", font_size="9")
            )

        # Icon/visual
        if i == 0:  # Connection
            for j in range(3):
                dwg.add(
                    dwg.line(
                        start=(x + 20, 220 + j * 15),
                        end=(x + 80, 220 + j * 15),
                        stroke="#4CAF50",
                        stroke_width=3,
                    )
                )
        elif i == 1:  # Multiplexing
            for row in range(4):
                for col in range(4):
                    dwg.add(
                        dwg.rect(
                            insert=(x + 20 + col * 15, 215 + row * 12),
                            size=(10, 8),
                            fill="#FF9800",
                            rx=2,
                        )
                    )
        elif i == 2:  # Routing
            dwg.add(
                dwg.text(
                    "msg_123",
                    insert=(x + 50, 240),
                    text_anchor="middle",
                    font_size="10",
                    font_family="monospace",
                )
            )
            dwg.add(dwg.polygon(points=[(x + 35, 260), (x + 50, 270), (x + 65, 260)], fill="#666"))
        elif i == 3:  # Response
            dwg.add(dwg.text("Future", insert=(x + 50, 240), text_anchor="middle", font_size="10"))
            dwg.add(
                dwg.text(
                    "✓", insert=(x + 50, 270), text_anchor="middle", font_size="24", fill="#4CAF50"
                )
            )
        elif i == 4:  # Backpressure
            dwg.add(
                dwg.text(
                    "64/64",
                    insert=(x + 50, 250),
                    text_anchor="middle",
                    font_size="12",
                    fill="#F44336",
                    font_weight="bold",
                )
            )
            dwg.add(
                dwg.text(
                    "BUSY",
                    insert=(x + 50, 275),
                    text_anchor="middle",
                    font_size="10",
                    fill="#F44336",
                )
            )
        else:  # Recovery
            dwg.add(
                dwg.text(
                    "⟳", insert=(x + 50, 255), text_anchor="middle", font_size="30", fill="#4CAF50"
                )
            )

    # Arrows between steps
    for i in range(len(steps) - 1):
        x1 = start_x + i * step_width + 100
        x2 = start_x + (i + 1) * step_width
        dwg.add(
            dwg.line(
                start=(x1, 220),
                end=(x2, 220),
                stroke="#666",
                stroke_width=2,
                marker_end="url(#arrowhead)",
            )
        )

    # Define arrow marker
    arrow = dwg.marker(insert=(0, 3), size=(10, 6), orient="auto", id="arrowhead")
    arrow.add(dwg.polygon(points=[(0, 0), (10, 3), (0, 6)], fill="#666"))
    dwg.defs.add(arrow)

    # Stats at bottom
    dwg.add(
        dwg.text(
            "Pool Size: 8 connections × 64 in-flight = 512 concurrent requests",
            insert=(400, 400),
            text_anchor="middle",
            font_size="12",
        )
    )

    dwg.save()
    print(f"✓ Created: {output_dir / '05-connection-lifecycle.svg'}")


def create_comparison_table():
    """Diagram 6: Comparative architecture - shared vs message passing."""
    dwg = svgwrite.Drawing(str(output_dir / "06-architecture-comparison.svg"), size=(800, 500))

    # Title
    dwg.add(
        dwg.text(
            "Architecture Comparison: Shared Memory vs Message Passing",
            insert=(400, 30),
            text_anchor="middle",
            font_size="18",
            font_weight="bold",
        )
    )

    # Left side - Shared Memory (asyncio)
    dwg.add(
        dwg.rect(
            insert=(50, 60),
            size=(320, 400),
            fill="#FFEBEE",
            stroke="#C62828",
            stroke_width=2,
            rx=10,
        )
    )
    dwg.add(dwg.rect(insert=(50, 60), size=(320, 35), fill="#C62828", rx=10))
    dwg.add(
        dwg.text(
            "Shared Memory (asyncio)",
            insert=(210, 82),
            text_anchor="middle",
            font_size="14",
            fill="white",
            font_weight="bold",
        )
    )

    # Shared heap representation
    dwg.add(
        dwg.rect(
            insert=(80, 110), size=(260, 80), fill="#FFCDD2", stroke="#C62828", stroke_width=2, rx=5
        )
    )
    dwg.add(
        dwg.text(
            "SHARED HEAP",
            insert=(210, 140),
            text_anchor="middle",
            font_size="12",
            font_weight="bold",
            fill="#C62828",
        )
    )

    # Agents sharing heap
    for i in range(3):
        y = 210 + i * 70
        dwg.add(dwg.rect(insert=(100, y), size=(220, 50), fill="#EF9A9A", stroke="#C62828", rx=5))
        dwg.add(
            dwg.text(
                f"Agent {i + 1} (Coroutines)",
                insert=(210, y + 20),
                text_anchor="middle",
                font_size="11",
                font_weight="bold",
            )
        )
        dwg.add(
            dwg.text(
                "⚠ Can corrupt shared state",
                insert=(210, y + 40),
                text_anchor="middle",
                font_size="9",
                fill="#C62828",
            )
        )

    # Problems list
    problems = [
        "❌ Race conditions",
        "❌ Manual locking needed",
        "❌ No fault isolation",
        "❌ Crash affects all agents",
    ]

    for i, problem in enumerate(problems):
        dwg.add(dwg.text(problem, insert=(210, 420 + i * 20), text_anchor="middle", font_size="10"))

    # Right side - Message Passing (Pyre/BEAM)
    dwg.add(
        dwg.rect(
            insert=(430, 60),
            size=(320, 400),
            fill="#E8F5E9",
            stroke="#2E7D32",
            stroke_width=2,
            rx=10,
        )
    )
    dwg.add(dwg.rect(insert=(430, 60), size=(320, 35), fill="#2E7D32", rx=10))
    dwg.add(
        dwg.text(
            "Message Passing (Pyre/BEAM)",
            insert=(590, 82),
            text_anchor="middle",
            font_size="14",
            fill="white",
            font_weight="bold",
        )
    )

    # Isolated processes
    for i in range(3):
        y = 110 + i * 100

        # Process box
        dwg.add(
            dwg.rect(
                insert=(460, y),
                size=(130, 80),
                fill="#C8E6C9",
                stroke="#2E7D32",
                stroke_width=2,
                rx=8,
            )
        )
        dwg.add(
            dwg.text(
                f"Agent {i + 1}",
                insert=(525, y + 20),
                text_anchor="middle",
                font_size="11",
                font_weight="bold",
            )
        )
        dwg.add(dwg.text("~2.9KB heap", insert=(525, y + 40), text_anchor="middle", font_size="9"))
        dwg.add(dwg.text("Own mailbox", insert=(525, y + 55), text_anchor="middle", font_size="9"))

        # Mailbox
        dwg.add(
            dwg.rect(insert=(610, y + 20), size=(110, 50), fill="#BBDEFB", stroke="#1976D2", rx=5)
        )
        dwg.add(
            dwg.text(
                "Mailbox",
                insert=(665, y + 35),
                text_anchor="middle",
                font_size="10",
                font_weight="bold",
            )
        )

        # Message arrows between agents
        if i < 2:
            dwg.add(
                dwg.line(
                    start=(595, y + 50),
                    end=(595, y + 100),
                    stroke="#1976D2",
                    stroke_width=2,
                    marker_end="url(#arrowblue)",
                )
            )

    # Blue arrow marker
    arrow_blue = dwg.marker(insert=(0, 3), size=(8, 6), orient="auto", id="arrowblue")
    arrow_blue.add(dwg.polygon(points=[(0, 0), (8, 3), (0, 6)], fill="#1976D2"))
    dwg.defs.add(arrow_blue)

    # Benefits list
    benefits = [
        "✓ No race conditions",
        "✓ No locks needed",
        "✓ Complete fault isolation",
        "✓ Crash affects only one agent",
    ]

    for i, benefit in enumerate(benefits):
        dwg.add(dwg.text(benefit, insert=(590, 420 + i * 20), text_anchor="middle", font_size="10"))

    dwg.save()
    print(f"✓ Created: {output_dir / '06-architecture-comparison.svg'}")


if __name__ == "__main__":
    print("Generating Pyre architectural diagrams...\n")

    create_concurrency_comparison()
    create_beam_process_model()
    create_pyre_architecture()
    create_supervision_tree()
    create_connection_lifecycle()
    create_comparison_table()

    print(f"\n✅ All 6 diagrams created in: {output_dir}")
    print("\nDiagrams:")
    print("  1. 01-concurrency-comparison.svg - Python concurrency options")
    print("  2. 02-beam-process-model.svg - BEAM process memory model")
    print("  3. 03-pyre-architecture.svg - Dual-runtime architecture")
    print("  4. 04-supervision-tree.svg - OTP supervision hierarchy")
    print("  5. 05-connection-lifecycle.svg - Bridge connection flow")
    print("  6. 06-architecture-comparison.svg - Shared vs message passing")
