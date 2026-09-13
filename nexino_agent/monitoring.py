"""Printer monitoring system for the Nexino PrintFlow agent.

Collects printer status periodically, detects paper/toner levels,
online/offline state, and errors using platform-appropriate methods.
"""

import logging
import time
from typing import Optional
from datetime import datetime

from .config import AgentConfig
from .printer_adapter import PrinterAdapter
from .models import (
    PrinterStatus,
    PrinterState,
    PaperStatus,
    TonerStatus,
)

logger = logging.getLogger(__name__)


class PrinterMonitor:
    """Monitors printer status and reports changes.

    Periodically checks printer status and maintains the latest known
    state for reporting to the backend.
    """

    def __init__(self, adapter: PrinterAdapter, config: AgentConfig) -> None:
        """Initialize the printer monitor.

        Args:
            adapter: Printer adapter to use for status checks.
            config: Agent configuration.
        """
        self.adapter = adapter
        self.config = config
        self.last_status: Optional[PrinterStatus] = None
        self._previous_state: Optional[PrinterState] = None

    def check_status(self) -> PrinterStatus:
        """Check the current printer status.

        Queries the printer adapter for current status and logs any
        significant state changes.

        Returns:
            Current PrinterStatus.
        """
        printer_name = self.config.printer_name
        if not printer_name:
            # Try to discover printers if none configured
            printers = self.adapter.discover()
            if printers:
                printer_name = printers[0]["name"]
                logger.info(f"Auto-discovered printer: {printer_name}")
            else:
                logger.debug("No printer configured or discovered.")
                return PrinterStatus(
                    name="unknown",
                    state=PrinterState.UNKNOWN,
                )

        try:
            status = self.adapter.get_status(printer_name)
        except Exception as e:
            logger.error(f"Error checking printer status: {e}")
            status = PrinterStatus(
                name=printer_name,
                state=PrinterState.UNKNOWN,
                error_message=str(e),
            )

        # Log state changes
        if self._previous_state != status.state:
            self._log_state_change(printer_name, self._previous_state, status.state)
            self._previous_state = status.state

        # Log paper/toner warnings
        self._check_paper_status(printer_name, status)
        self._check_toner_status(printer_name, status)

        # Log errors
        if status.error_message:
            logger.warning(f"Printer '{printer_name}' error: {status.error_message}")

        self.last_status = status
        return status

    def _log_state_change(
        self,
        printer_name: str,
        old_state: Optional[PrinterState],
        new_state: PrinterState,
    ) -> None:
        """Log printer state changes.

        Args:
            printer_name: Name of the printer.
            old_state: Previous state.
            new_state: New state.
        """
        if old_state is None:
            logger.info(f"Printer '{printer_name}' initial state: {new_state.value}")
        elif old_state != new_state:
            logger.info(
                f"Printer '{printer_name}' state changed: "
                f"{old_state.value} -> {new_state.value}"
            )

    def _check_paper_status(self, printer_name: str, status: PrinterStatus) -> None:
        """Check and log paper status warnings.

        Args:
            printer_name: Name of the printer.
            status: Current printer status.
        """
        if status.paper_status == PaperStatus.EMPTY:
            logger.warning(f"Printer '{printer_name}' is OUT OF PAPER!")
        elif status.paper_status == PaperStatus.LOW:
            logger.warning(f"Printer '{printer_name}' paper level is LOW.")
        elif status.paper_level is not None and status.paper_level < 0.1:
            logger.warning(
                f"Printer '{printer_name}' paper level critical: "
                f"{status.paper_level * 100:.0f}%"
            )

    def _check_toner_status(self, printer_name: str, status: PrinterStatus) -> None:
        """Check and log toner/ink status warnings.

        Args:
            printer_name: Name of the printer.
            status: Current printer status.
        """
        if status.toner_status == TonerStatus.EMPTY:
            logger.warning(f"Printer '{printer_name}' is OUT OF TONER/INK!")
        elif status.toner_status == TonerStatus.LOW:
            logger.warning(f"Printer '{printer_name}' toner/ink level is LOW.")
        elif status.toner_level is not None and status.toner_level < 0.1:
            logger.warning(
                f"Printer '{printer_name}' toner/ink level critical: "
                f"{status.toner_level * 100:.0f}%"
            )

    def is_printer_ready(self) -> bool:
        """Check if the printer is ready to accept jobs.

        Returns:
            True if printer is online and has no critical issues.
        """
        if self.last_status is None:
            return False

        status = self.last_status
        if status.state != PrinterState.IDLE:
            return False
        if status.paper_status == PaperStatus.EMPTY:
            return False
        if status.toner_status == TonerStatus.EMPTY:
            return False
        if status.error_message:
            return False

        return True

    def get_summary(self) -> str:
        """Get a human-readable summary of printer status.

        Returns:
            Status summary string.
        """
        if self.last_status is None:
            return "Printer status: Unknown (no checks performed yet)"

        status = self.last_status
        parts = [f"Printer: {status.name}"]
        parts.append(f"State: {status.state.value}")

        if status.paper_status != PaperStatus.UNKNOWN:
            paper_info = f"Paper: {status.paper_status.value}"
            if status.paper_level is not None:
                paper_info += f" ({status.paper_level * 100:.0f}%)"
            parts.append(paper_info)

        if status.toner_status != TonerStatus.UNKNOWN:
            toner_info = f"Toner: {status.toner_status.value}"
            if status.toner_level is not None:
                toner_info += f" ({status.toner_level * 100:.0f}%)"
            parts.append(toner_info)

        if status.error_message:
            parts.append(f"Error: {status.error_message}")

        if status.last_checked:
            parts.append(f"Last checked: {status.last_checked.strftime('%H:%M:%S')}")

        return " | ".join(parts)
