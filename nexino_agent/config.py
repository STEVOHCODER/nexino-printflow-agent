"""Configuration management for the Nexino PrintFlow agent."""

import os
import logging
from pathlib import Path
from typing import Optional
from dataclasses import dataclass, field

from dotenv import load_dotenv

logger = logging.getLogger(__name__)

DEFAULT_ENV_FILE = Path(__file__).parent.parent / ".env"


@dataclass
class AgentConfig:
    """Configuration for the Nexino PrintFlow agent.

    All configuration is loaded from environment variables, with sensible defaults
    where appropriate.
    """

    backend_url: str = "http://localhost:3000"
    agent_id: str = ""
    agent_secret: str = ""
    station_id: str = ""
    poll_interval_seconds: int = 3
    printer_name: str = ""
    virtual_mode: bool = False  # Disabled by default; use --virtual flag to enable
    log_level: str = "INFO"
    output_directory: str = ""
    heartbeat_interval_seconds: int = 30
    status_check_interval_seconds: int = 15
    max_retries: int = 5
    retry_base_delay: float = 1.0
    retry_max_delay: float = 60.0
    download_timeout: int = 30
    api_timeout: int = 10

    @classmethod
    def load(cls, env_file: Optional[str] = None) -> "AgentConfig":
        """Load configuration from environment variables.

        Args:
            env_file: Optional path to a .env file. If not provided, looks for
                      .env in the project root.

        Returns:
            AgentConfig instance with loaded values.
        """
        if env_file:
            load_dotenv(env_file)
        elif Path(DEFAULT_ENV_FILE).exists():
            load_dotenv(DEFAULT_ENV_FILE)
        else:
            load_dotenv()

        config = cls(
            backend_url=os.getenv("NEXINO_BACKEND_URL", cls.backend_url),
            agent_id=os.getenv("AGENT_ID", cls.agent_id),
            agent_secret=os.getenv("AGENT_SECRET", cls.agent_secret),
            station_id=os.getenv("STATION_ID", cls.station_id),
            poll_interval_seconds=int(os.getenv("POLL_INTERVAL_SECONDS", cls.poll_interval_seconds)),
            printer_name=os.getenv("PRINTER_NAME", cls.printer_name),
            virtual_mode=os.getenv("VIRTUAL_MODE", "false").lower() in ("true", "1", "yes"),
            log_level=os.getenv("LOG_LEVEL", cls.log_level).upper(),
            output_directory=os.getenv("OUTPUT_DIRECTORY", cls.output_directory),
            heartbeat_interval_seconds=int(os.getenv("HEARTBEAT_INTERVAL_SECONDS", cls.heartbeat_interval_seconds)),
            status_check_interval_seconds=int(os.getenv("STATUS_CHECK_INTERVAL_SECONDS", cls.status_check_interval_seconds)),
            max_retries=int(os.getenv("MAX_RETRIES", cls.max_retries)),
            retry_base_delay=float(os.getenv("RETRY_BASE_DELAY", cls.retry_base_delay)),
            retry_max_delay=float(os.getenv("RETRY_MAX_DELAY", cls.retry_max_delay)),
            download_timeout=int(os.getenv("DOWNLOAD_TIMEOUT", cls.download_timeout)),
            api_timeout=int(os.getenv("API_TIMEOUT", cls.api_timeout)),
        )

        config._setup_logging()
        config._validate()
        return config

    def _setup_logging(self) -> None:
        """Configure logging based on the log level setting."""
        numeric_level = getattr(logging, self.log_level, logging.INFO)
        logging.basicConfig(
            level=numeric_level,
            format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )

    def _validate(self) -> None:
        """Validate configuration values."""
        if not self.agent_id:
            logger.warning("AGENT_ID is not set. Agent must be registered before use.")
        if self.poll_interval_seconds < 1:
            raise ValueError("POLL_INTERVAL_SECONDS must be at least 1.")
        if self.output_directory and not Path(self.output_directory).exists():
            try:
                Path(self.output_directory).mkdir(parents=True, exist_ok=True)
                logger.info(f"Created output directory: {self.output_directory}")
            except OSError as e:
                logger.warning(f"Could not create output directory {self.output_directory}: {e}")

    def save(self, env_file: Optional[str] = None) -> None:
        """Save current configuration to a .env file.

        Args:
            env_file: Path to write the .env file. Defaults to project root .env.
        """
        path = Path(env_file) if env_file else DEFAULT_ENV_FILE
        lines = [
            f"NEXINO_BACKEND_URL={self.backend_url}",
            f"AGENT_ID={self.agent_id}",
            f"AGENT_SECRET={self.agent_secret}",
            f"STATION_ID={self.station_id}",
            f"POLL_INTERVAL_SECONDS={self.poll_interval_seconds}",
            f"PRINTER_NAME={self.printer_name}",
            f"VIRTUAL_MODE={str(self.virtual_mode).lower()}",
            f"LOG_LEVEL={self.log_level}",
            f"OUTPUT_DIRECTORY={self.output_directory}",
            f"HEARTBEAT_INTERVAL_SECONDS={self.heartbeat_interval_seconds}",
            f"STATUS_CHECK_INTERVAL_SECONDS={self.status_check_interval_seconds}",
        ]
        path.write_text("\n".join(lines) + "\n")
        logger.info(f"Configuration saved to {path}")
