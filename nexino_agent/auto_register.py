"""Auto-registration module for the Nexino PrintFlow agent.

Detects all printers on the system and registers them with the backend,
creating stations automatically.
"""

import json
import logging
import platform
import socket
from pathlib import Path
from typing import Dict, List, Optional

from .adapters import get_adapter
from .api_client import AgentApiClient

logger = logging.getLogger(__name__)


class AutoRegistrar:
    """Detects printers and registers stations with the backend."""

    def __init__(
        self,
        agent_id: str,
        backend_url: str,
        agent_secret: str = "nexino-agent-secret-change-in-production",
        config_path: Optional[str] = None,
    ) -> None:
        self.agent_id = agent_id
        self.backend_url = backend_url
        self.api_client = AgentApiClient(backend_url, agent_id, agent_secret)
        self.hostname = socket.gethostname()
        self.platform_name = platform.system().lower()
        self.config_path = Path(config_path or Path(__file__).parent.parent / "agent_config.json")

    def detect_printers(self, adapter_types: Optional[List[str]] = None) -> List[Dict]:
        """Detect all printers on the system.

        Args:
            adapter_types: List of adapter types to try. Defaults to ["windows", "virtual"].

        Returns:
            List of detected printer info dicts.
        """
        if adapter_types is None:
            if self.platform_name == "windows":
                adapter_types = ["windows", "virtual"]
            elif self.platform_name == "linux":
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
                logger.info(f"Detected {len(printers)} printer(s) via {adapter_type} adapter.")
            except Exception as e:
                logger.warning(f"Failed to discover printers via {adapter_type}: {e}")

        if not all_printers:
            logger.warning("No printers detected. Creating a virtual printer station.")
            all_printers.append({
                "name": f"Virtual Printer ({self.hostname})",
                "driver": "Virtual",
                "port": "virtual://default",
                "adapterType": "VIRTUAL",
                "status": "normal",
            })

        return all_printers

    def register(self, printers: Optional[List[Dict]] = None) -> Dict:
        """Register detected printers with the backend.

        Args:
            printers: Optional pre-detected printer list. If None, auto-detects.

        Returns:
            Registration result with station IDs.
        """
        if printers is None:
            printers = self.detect_printers()

        logger.info(f"Registering {len(printers)} printer(s) with backend at {self.backend_url}...")

        try:
            result = self.api_client.auto_register(
                hostname=self.hostname,
                platform=self.platform_name,
                printers=printers,
            )

            if result.get("success"):
                data = result["data"]
                stations = data.get("stations", [])
                logger.info(f"Successfully registered {len(stations)} station(s).")

                self._save_config(stations, printers)

                return {
                    "success": True,
                    "agentId": self.agent_id,
                    "hostname": self.hostname,
                    "stations": stations,
                }
            else:
                logger.error(f"Registration failed: {result}")
                return {"success": False, "error": result}
        except Exception as e:
            logger.error(f"Registration error: {e}")
            return {"success": False, "error": str(e)}

    def _save_config(self, stations: List[Dict], printers: List[Dict]) -> None:
        """Save station configuration to a local file.

        Args:
            stations: List of station data from backend.
            printers: List of detected printers.
        """
        config = {
            "agentId": self.agent_id,
            "hostname": self.hostname,
            "platform": self.platform_name,
            "backendUrl": self.backend_url,
            "stations": [],
        }

        for i, station in enumerate(stations):
            printer_info = printers[i] if i < len(printers) else {}
            config["stations"].append({
                "stationId": station["stationId"],
                "stationCode": station["stationCode"],
                "name": station["name"],
                "printerName": station.get("printerName", printer_info.get("name", "")),
                "adapterType": printer_info.get("adapterType", "WINDOWS"),
            })

        self.config_path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.config_path, "w") as f:
            json.dump(config, f, indent=2)

        logger.info(f"Configuration saved to {self.config_path}")

    def load_config(self) -> Optional[Dict]:
        """Load saved configuration.

        Returns:
            Configuration dict or None if not found.
        """
        if not self.config_path.exists():
            return None

        try:
            with open(self.config_path) as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"Failed to load config: {e}")
            return None

    def get_station_ids(self) -> List[str]:
        """Get list of registered station IDs.

        Returns:
            List of station ID strings.
        """
        config = self.load_config()
        if config:
            return [s["stationId"] for s in config.get("stations", [])]
        return []
