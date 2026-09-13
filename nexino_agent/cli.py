"""Command-line interface for the Nexino PrintFlow agent.

Provides commands for starting, configuring, and managing the print agent.
"""

import sys
import argparse
import logging
from pathlib import Path

from . import __version__
from .config import AgentConfig
from .agent import NexinoAgent
from .adapters import VirtualAdapter, WindowsAdapter, CupsAdapter, IPPAdapter
from .auto_register import AutoRegistrar

logger = logging.getLogger(__name__)


def create_parser() -> argparse.ArgumentParser:
    """Create the argument parser for the CLI.

    Returns:
        Configured ArgumentParser.
    """
    parser = argparse.ArgumentParser(
        prog="nexino-agent",
        description="Nexino PrintFlow Print Agent - Manages authorized print jobs.",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {__version__}",
    )
    parser.add_argument(
        "--config",
        type=str,
        default=None,
        help="Path to .env configuration file.",
    )

    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # start command
    start_parser = subparsers.add_parser("start", help="Start the print agent")
    start_parser.add_argument(
        "--virtual",
        action="store_true",
        help="Start in virtual mode (for testing).",
    )
    start_parser.add_argument("--station-id", type=str, help="Station ID")
    start_parser.add_argument("--agent-id", type=str, help="Agent ID")
    start_parser.add_argument("--backend-url", type=str, help="Backend URL")
    start_parser.add_argument("--agent-secret", type=str, help="Agent secret")

    # configure command
    subparsers.add_parser("configure", help="Interactive printer configuration")

    # configure-printer command
    printer_parser = subparsers.add_parser(
        "configure-printer", help="Discover and select a printer"
    )
    printer_parser.add_argument(
        "--list",
        action="store_true",
        help="List available printers without selecting.",
    )

    # status command
    subparsers.add_parser("status", help="Show current agent/printer status")

    # test command
    subparsers.add_parser("test", help="Test connection to backend")

    # register command (auto-detect printers and register stations)
    register_parser = subparsers.add_parser("register", help="Auto-detect printers and register stations")
    register_parser.add_argument("--agent-id", type=str, required=True, help="Agent ID")
    register_parser.add_argument("--backend-url", type=str, help="Backend URL")
    register_parser.add_argument("--agent-secret", type=str, help="Agent secret")
    register_parser.add_argument("--config", type=str, default=None, help="Path to .env config file")
    register_parser.add_argument("--yes", action="store_true", help="Skip confirmation prompt")

    # detect command (output printers as JSON for Electron)
    subparsers.add_parser("detect", help="Detect printers and output as JSON")

    return parser


def cmd_start(args: argparse.Namespace) -> None:
    """Start the print agent.

    Args:
        args: Parsed command-line arguments.
    """
    config = AgentConfig.load(args.config)

    if args.virtual:
        config.virtual_mode = True
    if args.station_id:
        config.station_id = args.station_id
    if args.agent_id:
        config.agent_id = args.agent_id
    if args.backend_url:
        config.backend_url = args.backend_url
    if args.agent_secret:
        config.agent_secret = args.agent_secret

    if not config.station_id and config.agent_id:
        registrar = AutoRegistrar(
            agent_id=config.agent_id,
            backend_url=config.backend_url,
            agent_secret=config.agent_secret,
        )
        saved_config = registrar.load_config()
        if saved_config:
            stations = saved_config.get("stations", [])
            if stations:
                config.station_id = stations[0]["stationId"]
                print(f"Using saved station: {stations[0]['name']}")
        else:
            print("No saved configuration found. Auto-registering...")
            result = registrar.register()
            if result.get("success"):
                stations = result.get("stations", [])
                if stations:
                    config.station_id = stations[0]["stationId"]
                    print(f"Registered station: {stations[0]['name']}")
            else:
                print(f"Auto-registration failed: {result.get('error')}")
                print("Please provide a --station-id manually.")
                sys.exit(1)

    agent = NexinoAgent(config)
    agent.start()


def cmd_configure(args: argparse.Namespace) -> None:
    """Interactive printer configuration.

    Prompts the user for configuration values and saves them to .env.

    Args:
        args: Parsed command-line arguments.
    """
    print("Nexino PrintFlow Agent Configuration")
    print("=" * 40)

    config = AgentConfig.load(args.config)

    # Get configuration values
    backend_url = input(f"Backend URL [{config.backend_url}]: ").strip()
    if backend_url:
        config.backend_url = backend_url

    agent_id = input(f"Agent ID [{config.agent_id}]: ").strip()
    if agent_id:
        config.agent_id = agent_id

    agent_secret = input(f"Agent Secret [{config.agent_secret}]: ").strip()
    if agent_secret:
        config.agent_secret = agent_secret

    station_id = input(f"Station ID [{config.station_id}]: ").strip()
    if station_id:
        config.station_id = station_id

    poll_interval = input(f"Poll Interval (seconds) [{config.poll_interval_seconds}]: ").strip()
    if poll_interval:
        config.poll_interval_seconds = int(poll_interval)

    virtual_mode = input(f"Virtual Mode (true/false) [{str(config.virtual_mode).lower()}]: ").strip()
    if virtual_mode:
        config.virtual_mode = virtual_mode.lower() in ("true", "1", "yes")

    log_level = input(f"Log Level (DEBUG/INFO/WARNING/ERROR) [{config.log_level}]: ").strip()
    if log_level:
        config.log_level = log_level.upper()

    # Save configuration
    config.save(args.config)
    print("\nConfiguration saved successfully!")


def cmd_configure_printer(args: argparse.Namespace) -> None:
    """Discover and select a printer.

    Lists available printers and lets the user select one.

    Args:
        args: Parsed command-line arguments.
    """
    config = AgentConfig.load(args.config)

    print("Discovering printers...")
    print()

    # Select adapter based on platform
    if sys.platform == "win32":
        adapter = WindowsAdapter()
    else:
        try:
            adapter = CupsAdapter()
        except Exception:
            adapter = IPPAdapter()

    printers = adapter.discover()

    if not printers:
        print("No printers found.")
        print("Make sure your printer is connected and drivers are installed.")
        return

    print(f"Found {len(printers)} printer(s):")
    print()

    for i, printer in enumerate(printers, 1):
        status = printer.get("status", "unknown")
        name = printer.get("name", "Unknown")
        printer_type = printer.get("type", "unknown")
        print(f"  {i}. {name}")
        print(f"     Status: {status}")
        print(f"     Type: {printer_type}")
        print()

    if args.list:
        return

    # Select printer
    while True:
        try:
            choice = input("Select printer number (or 'q' to quit): ").strip()
            if choice.lower() == "q":
                return

            idx = int(choice) - 1
            if 0 <= idx < len(printers):
                selected = printers[idx]
                config.printer_name = selected["name"]
                config.virtual_mode = False
                config.save(args.config)
                print(f"\nPrinter '{selected['name']}' configured successfully!")
                return
            else:
                print("Invalid selection. Please try again.")
        except ValueError:
            print("Please enter a valid number.")
        except KeyboardInterrupt:
            print("\nCancelled.")
            return


def cmd_status(args: argparse.Namespace) -> None:
    """Show current agent and printer status.

    Args:
        args: Parsed command-line arguments.
    """
    config = AgentConfig.load(args.config)
    agent = NexinoAgent(config)

    print("Nexino PrintFlow Agent Status")
    print("=" * 40)
    print(f"Agent ID:       {config.agent_id or '(not registered)'}")
    print(f"Station ID:     {config.station_id}")
    print(f"Virtual Mode:   {config.virtual_mode}")
    print(f"Backend URL:    {config.backend_url}")
    print(f"Printer:        {config.printer_name or '(not configured)'}")
    print()

    # Check printer status
    if config.printer_name or config.virtual_mode:
        print("Checking printer status...")
        try:
            status = agent.monitor.check_status()
            summary = agent.monitor.get_summary()
            print(summary)
            print()
        except Exception as e:
            print(f"Error checking printer status: {e}")
    else:
        print("No printer configured. Run 'nexino-agent configure-printer' first.")


def cmd_test(args: argparse.Namespace) -> None:
    """Test connection to the backend.

    Args:
        args: Parsed command-line arguments.
    """
    config = AgentConfig.load(args.config)
    agent = NexinoAgent(config)

    print(f"Testing connection to {config.backend_url}...")
    success = agent.test_connection()

    if success:
        print("Connection successful!")
        sys.exit(0)
    else:
        print("Connection failed!")
        sys.exit(1)


def cmd_detect(args: argparse.Namespace) -> None:
    """Detect printers and output as JSON for the Electron app.

    Args:
        args: Parsed command-line arguments.
    """
    import json
    import platform
    import socket

    hostname = socket.gethostname()
    platform_name = platform.system().lower()

    if platform_name == "windows":
        adapter_types = ["windows", "virtual"]
    elif platform_name == "linux":
        adapter_types = ["cups", "ipp", "virtual"]
    else:
        adapter_types = ["virtual"]

    all_printers = []
    for adapter_type in adapter_types:
        try:
            adapter = get_adapter(adapter_type)
            printers = adapter.discover()
            for printer in printers:
                printer["adapterType"] = adapter_type.upper()
            all_printers.extend(printers)
        except Exception:
            pass

    if not all_printers:
        all_printers.append({
            "name": f"Virtual Printer ({hostname})",
            "driver": "Virtual",
            "port": "virtual://default",
            "adapterType": "VIRTUAL",
            "status": "normal",
        })

    print(json.dumps(all_printers))


def cmd_register(args: argparse.Namespace) -> None:
    """Auto-detect printers and register stations with the backend.

    Args:
        args: Parsed command-line arguments.
    """
    config = AgentConfig.load(args.config)

    if args.backend_url:
        config.backend_url = args.backend_url
    if args.agent_secret:
        config.agent_secret = args.agent_secret

    registrar = AutoRegistrar(
        agent_id=args.agent_id,
        backend_url=config.backend_url,
        agent_secret=config.agent_secret,
    )

    print("Nexino PrintFlow Agent Auto-Registration")
    print("=" * 45)
    print(f"Agent ID:    {args.agent_id}")
    print(f"Backend URL: {config.backend_url}")
    print(f"Hostname:    {registrar.hostname}")
    print(f"Platform:    {registrar.platform_name}")
    print()

    print("Detecting printers...")
    printers = registrar.detect_printers()

    print(f"\nFound {len(printers)} printer(s):")
    for i, p in enumerate(printers, 1):
        print(f"  {i}. {p['name']} ({p['adapterType']})")
    print()

    if not args.yes:
        confirm = input("Register these printers as stations? [Y/n]: ").strip().lower()
        if confirm and confirm != "y" and confirm != "yes":
            print("Registration cancelled.")
            return

    print("\nRegistering with backend...")
    result = registrar.register(printers)

    if result.get("success"):
        stations = result.get("stations", [])
        print(f"\nSuccessfully registered {len(stations)} station(s)!")
        print()
        for s in stations:
            print(f"  Station: {s['name']}")
            print(f"  Code:    {s['stationCode']}")
            print(f"  ID:      {s['stationId']}")
            print(f"  Printer: {s.get('printerName', 'N/A')}")
            print()

        # Output JSON for Electron to parse
        import json
        print("JSON_RESULT:" + json.dumps({"success": True, "stations": stations}))
        print("\nConfiguration saved to agent_config.json")
        print("\nStart the agent with:")
        print(f"  python -m nexino_agent start --agent-id {args.agent_id}")
    else:
        print(f"\nRegistration failed: {result.get('error', 'Unknown error')}")
        import json
        print("JSON_RESULT:" + json.dumps({"success": False, "error": result.get('error', 'Unknown error')}))
        sys.exit(1)


def main(argv=None) -> None:
    """Main entry point for the CLI.

    Args:
        argv: Command-line arguments. Defaults to sys.argv.
    """
    parser = create_parser()
    args = parser.parse_args(argv)

    if not args.command:
        parser.print_help()
        sys.exit(1)

    commands = {
        "start": cmd_start,
        "configure": cmd_configure,
        "configure-printer": cmd_configure_printer,
        "status": cmd_status,
        "test": cmd_test,
        "register": cmd_register,
        "detect": cmd_detect,
    }

    command_func = commands.get(args.command)
    if command_func:
        try:
            command_func(args)
        except KeyboardInterrupt:
            print("\nOperation cancelled.")
            sys.exit(130)
        except Exception as e:
            logger.error(f"Error: {e}")
            print(f"Error: {e}", file=sys.stderr)
            sys.exit(1)
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
