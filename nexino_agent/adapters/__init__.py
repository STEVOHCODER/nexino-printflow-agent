"""Printer adapter implementations.

This package contains adapters for different printing systems:
- VirtualAdapter: For testing and virtual printing
- WindowsAdapter: For Windows printers via PowerShell
- CupsAdapter: For Linux/Unix printers via CUPS
- IPPAdapter: For direct IPP protocol communication
"""

from ..printer_adapter import PrinterAdapter
from .virtual_adapter import VirtualAdapter
from .windows_adapter import WindowsAdapter
from .cups_adapter import CupsAdapter
from .ipp_adapter import IPPAdapter

__all__ = ["VirtualAdapter", "WindowsAdapter", "CupsAdapter", "IPPAdapter", "PrinterAdapter", "get_adapter"]


def get_adapter(adapter_type: str, **kwargs) -> PrinterAdapter:
    """Get a printer adapter by type.

    Args:
        adapter_type: Type of adapter ('virtual', 'windows', 'cups', 'ipp').
        **kwargs: Additional arguments to pass to the adapter constructor.

    Returns:
        PrinterAdapter instance.

    Raises:
        ValueError: If adapter type is unknown.
    """
    adapters = {
        "virtual": VirtualAdapter,
        "windows": WindowsAdapter,
        "cups": CupsAdapter,
        "ipp": IPPAdapter,
    }
    
    adapter_class = adapters.get(adapter_type.lower())
    if not adapter_class:
        raise ValueError(f"Unknown adapter type: {adapter_type}. Available: {list(adapters.keys())}")
    
    return adapter_class(**kwargs)
