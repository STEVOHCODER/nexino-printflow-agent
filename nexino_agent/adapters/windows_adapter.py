"""Windows printer adapter using PowerShell and the .NET printing stack.

Real printing is attempted in priority order:

1. SumatraPDF (vector, best quality) when installed
2. pypdfium2 rasterization + .NET PrintDocument (works with no extra software)
3. Shell ``printto`` verb (last resort)

Status/queue information is read from the Windows print spooler.
"""

import subprocess
import logging
import json
import glob
import time
import uuid
import os
import re
import tempfile
from typing import Dict, List, Optional
from pathlib import Path

from ..printer_adapter import PrinterAdapter
from ..models import (
    PrinterStatus,
    PrinterState,
    PaperStatus,
    TonerStatus,
)

logger = logging.getLogger(__name__)

# Common SumatraPDF locations on Windows
SUMATRA_SEARCH_PATHS = [
    r"C:\Program Files\SumatraPDF\SumatraPDF.exe",
    r"C:\Program Files (x86)\SumatraPDF\SumatraPDF.exe",
    r"C:\Users\*\AppData\Local\SumatraPDF\SumatraPDF.exe",
    r"D:\Program Files\SumatraPDF\SumatraPDF.exe",
    r"D:\Program Files (x86)\SumatraPDF\SumatraPDF.exe",
]

# PrintDocument script: prints every PNG in a directory in name order.
_PS_PRINT_TEMPLATE = r'''
param($PrinterName, $Copies, $Duplex, $Color, $ImageDir)
Add-Type -AssemblyName System.Drawing
Add-Type -AssemblyName System.Drawing.Printing

$settings = New-Object System.Drawing.Printing.PrinterSettings
$settings.PrinterName = $PrinterName
if (-not $settings.IsValid) {
    Write-Error "Printer not found: $PrinterName"
    exit 2
}
$settings.Copies = [int]$Copies
if ($Duplex -eq "double") {
    $settings.Duplex = [System.Drawing.Printing.Duplex]::Vertical
} else {
    $settings.Duplex = [System.Drawing.Printing.Duplex]::Simplex
}
if ($Color -eq "monochrome") {
    $settings.Color = [System.Drawing.Printing.PrinterColor]::Monochrome
}

$images = @(Get-ChildItem -Path $ImageDir -Filter *.png | Sort-Object Name)
if ($images.Count -eq 0) {
    Write-Error "No rendered pages found"
    exit 4
}

$script:page = 0
$doc = New-Object System.Drawing.Printing.PrintDocument
$doc.PrinterSettings = $settings
$doc.DocumentName = "Nexino PrintJob"
$doc.add_PrintPage({
    param($sender, $e)
    if ($script:page -ge $images.Count) { $e.HasMorePages = $false; return }
    $img = [System.Drawing.Image]::FromFile($images[$script:page].FullName)
    try {
        $bounds = $e.MarginBounds
        $ratio = [Math]::Min($bounds.Width / $img.Width, $bounds.Height / $img.Height)
        $w = $img.Width * $ratio
        $h = $img.Height * $ratio
        $x = $bounds.X + ($bounds.Width - $w) / 2
        $y = $bounds.Y + ($bounds.Height - $h) / 2
        $e.Graphics.DrawImage($img, [float]$x, [float]$y, [float]$w, [float]$h)
    } finally {
        $img.Dispose()
    }
    $script:page++
    $e.HasMorePages = ($script:page -lt $images.Count)
})
$doc.Print()
Write-Output "PRINTED"
'''

_PS_PRINTTO_TEMPLATE = r'''
param($File, $Printer)
try {
    $p = Start-Process -FilePath $File -Verb printto -ArgumentList $Printer -PassThru -Wait
    if ($p -and $p.ExitCode -ne 0) {
        Write-Error "printto verb exit code $($p.ExitCode)"
        exit 3
    }
    Write-Output "PRINTED"
} catch {
    Write-Error $_.Exception.Message
    exit 3
}
'''


def _no_window_kwargs() -> Dict:
    """Keyword args to keep child processes from flashing a console window."""
    kwargs: Dict = {}
    if hasattr(subprocess, "CREATE_NO_WINDOW"):
        kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW
    return kwargs


class WindowsAdapter(PrinterAdapter):
    """Windows printer adapter with tiered, dependency-light printing."""

    def __init__(self, sumatra_pdf_path: Optional[str] = None) -> None:
        self.sumatra_pdf_path = sumatra_pdf_path or self._find_sumatra_pdf()
        self._jobs: Dict[str, Dict] = {}
        self._check_availability()

    # ------------------------------------------------------------------
    # Setup / helpers
    # ------------------------------------------------------------------
    def _find_sumatra_pdf(self) -> Optional[str]:
        """Auto-detect a SumatraPDF installation, if any."""
        for pattern in SUMATRA_SEARCH_PATHS:
            matches = glob.glob(pattern)
            if matches:
                path = matches[0]
                logger.info(f"Found SumatraPDF at: {path}")
                return path

        try:
            result = subprocess.run(
                "where SumatraPDF.exe",
                capture_output=True, text=True, timeout=5, shell=True,
                **_no_window_kwargs(),
            )
            if result.returncode == 0 and result.stdout.strip():
                path = result.stdout.strip().split("\n")[0]
                logger.info(f"Found SumatraPDF via 'where': {path}")
                return path
        except Exception:
            pass

        logger.info("SumatraPDF not found. Will use built-in rasterized printing.")
        return None

    def _check_availability(self) -> None:
        try:
            result = subprocess.run(
                ["powershell", "-NoProfile", "-Command", "Write-Output 'ok'"],
                capture_output=True, text=True, timeout=5,
                **_no_window_kwargs(),
            )
            if result.returncode == 0:
                logger.info("Windows adapter initialized. PowerShell available.")
            else:
                logger.warning("PowerShell may not be fully functional.")
        except FileNotFoundError:
            logger.error("PowerShell not found.")
        except Exception as e:
            logger.warning(f"Error checking PowerShell: {e}")

    @staticmethod
    def _ps_quote(value: str) -> str:
        """Make a string safe to embed inside a double-quoted PowerShell string."""
        return str(value).replace('"', "").replace("`", "").replace("$", "")

    def _run_powershell(self, command: str, timeout: int = 10) -> Dict:
        try:
            result = subprocess.run(
                ["powershell", "-NoProfile", "-Command", command],
                capture_output=True, text=True, timeout=timeout,
                **_no_window_kwargs(),
            )
            return {
                "success": result.returncode == 0,
                "output": result.stdout.strip(),
                "error": result.stderr.strip() if result.returncode != 0 else None,
            }
        except subprocess.TimeoutExpired:
            return {"success": False, "output": "", "error": "PowerShell command timed out"}
        except Exception as e:
            return {"success": False, "output": "", "error": str(e)}

    def _run_powershell_script(self, script_text: str, args: List[str], timeout: int = 120) -> Dict:
        """Run a PowerShell script from a temp file, passing args positionally.

        Avoids all the quoting pitfalls of inlining code into -Command.
        """
        tmp_dir = Path(tempfile.gettempdir()) / "nexino-ps"
        tmp_dir.mkdir(parents=True, exist_ok=True)
        script_path = tmp_dir / f"nexino_{uuid.uuid4().hex[:8]}.ps1"
        try:
            script_path.write_text(script_text, encoding="utf-8")
            cmd = [
                "powershell", "-NoProfile", "-ExecutionPolicy", "Bypass",
                "-File", str(script_path), *args,
            ]
            result = subprocess.run(
                cmd,
                capture_output=True, text=True, timeout=timeout,
                **_no_window_kwargs(),
            )
            return {
                "success": result.returncode == 0 and "PRINTED" in result.stdout,
                "output": result.stdout.strip(),
                "error": (result.stderr.strip() or result.stdout.strip())
                if result.returncode != 0 else None,
            }
        except subprocess.TimeoutExpired:
            return {"success": False, "output": "", "error": "Print command timed out"}
        except Exception as e:
            return {"success": False, "output": "", "error": str(e)}
        finally:
            try:
                script_path.unlink(missing_ok=True)
            except OSError:
                pass

    def _printer_exists(self, printer_name: str) -> bool:
        """Check a printer is installed and usable.

        Prefers the .NET PrinterSettings.IsValid check, but that assembly is
        not loadable in PowerShell Core, so fall back to Get-Printer.
        """
        result = self._run_powershell(
            "Add-Type -AssemblyName System.Drawing.Printing; "
            "$s = New-Object System.Drawing.Printing.PrinterSettings; "
            f'$s.PrinterName = "{self._ps_quote(printer_name)}"; '
            "Write-Output $s.IsValid"
        )
        if result["success"] and result["output"].strip().lower() == "true":
            return True
        if result["success"] and result["output"].strip().lower() == "false":
            return False
        # .NET Printing assembly unavailable (e.g. PowerShell Core): use Get-Printer
        result = self._run_powershell(
            f'Get-Printer -Name "{self._ps_quote(printer_name)}" | '
            "Select-Object -ExpandProperty Name"
        )
        return result["success"] and bool(result["output"].strip())

    # ------------------------------------------------------------------
    # Discovery & status
    # ------------------------------------------------------------------
    def discover(self) -> List[Dict]:
        command = (
            "Get-Printer | Select-Object Name, DriverName, PortName, "
            "PrinterStatus, Type | ConvertTo-Json"
        )
        result = self._run_powershell(command)

        if not result["success"]:
            logger.error(f"Failed to discover printers: {result['error']}")
            return []

        try:
            raw = result["output"]
            if not raw or raw.strip() == "":
                return []

            printers_data = json.loads(raw)
            if isinstance(printers_data, dict):
                printers_data = [printers_data]

            printers = []
            skip_names = {"Microsoft XPS Document Writer", "Microsoft Print to PDF",
                          "Fax", "OneNote", "AnyDesk Printer"}
            for p in printers_data:
                name = p.get("Name", "")
                if any(skip in name for skip in skip_names):
                    continue
                status_code = p.get("PrinterStatus", 8)
                status_map = {
                    0: "normal", 1: "paused", 2: "error", 3: "deleting",
                    4: "paper_jam", 5: "paper_out", 8: "offline",
                }
                printers.append({
                    "name": name,
                    "driver": p.get("DriverName", ""),
                    "port": p.get("PortName", ""),
                    "type": "windows",
                    "status": status_map.get(status_code, "unknown"),
                    "status_code": status_code,
                })

            logger.info(f"Discovered {len(printers)} printer(s).")
            return printers
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse printer list: {e}")
            return []

    def get_status(self, printer_name: str) -> PrinterStatus:
        command = (
            f'Get-Printer -Name "{self._ps_quote(printer_name)}" | '
            "Select-Object Name, PrinterStatus | ConvertTo-Json"
        )
        result = self._run_powershell(command)

        if not result["success"]:
            return PrinterStatus(
                name=printer_name,
                state=PrinterState.UNKNOWN,
                error_message=result.get("error"),
            )

        try:
            data = json.loads(result["output"])
            if isinstance(data, list):
                data = data[0] if data else {}
            status_code = data.get("PrinterStatus", 8)

            state_map = {
                0: PrinterState.IDLE, 1: PrinterState.IDLE,
                2: PrinterState.ERROR, 3: PrinterState.ERROR,
                4: PrinterState.ERROR, 5: PrinterState.ERROR,
                8: PrinterState.OFFLINE,
            }
            state = state_map.get(status_code, PrinterState.UNKNOWN)

            paper_status, paper_level = self._get_paper_level(printer_name)
            toner_status, toner_level = self._get_toner_level(printer_name)

            error_msg = None
            if status_code in (2, 4, 5):
                error_codes = {2: "Printer error", 4: "Paper jam", 5: "Paper out"}
                error_msg = error_codes.get(status_code, "Unknown error")

            return PrinterStatus(
                name=printer_name, state=state,
                paper_status=paper_status, paper_level=paper_level,
                toner_status=toner_status, toner_level=toner_level,
                error_message=error_msg,
            )
        except (json.JSONDecodeError, KeyError) as e:
            logger.error(f"Failed to parse printer status: {e}")
            return PrinterStatus(name=printer_name, state=PrinterState.UNKNOWN)

    def _get_paper_level(self, printer_name: str) -> tuple:
        command = (
            f"Get-CimInstance -ClassName Win32_Printer -Filter \"Name='{self._ps_quote(printer_name)}'\" | "
            "Select-Object DetectedErrorState, PrinterStatus | ConvertTo-Json"
        )
        result = self._run_powershell(command)
        if not result["success"]:
            return PaperStatus.UNKNOWN, None

        try:
            data = json.loads(result["output"])
            if isinstance(data, list):
                data = data[0] if data else {}
            error_state = data.get("DetectedErrorState", 0)
            if error_state == 4:
                return PaperStatus.EMPTY, 0.0
            elif error_state == 3:
                return PaperStatus.LOW, 0.2
            elif error_state == 2:
                return PaperStatus.OK, 0.8
            return PaperStatus.UNKNOWN, None
        except (json.JSONDecodeError, KeyError):
            return PaperStatus.UNKNOWN, None

    def _get_toner_level(self, printer_name: str) -> tuple:
        command = (
            f"Get-CimInstance -ClassName Win32_Printer -Filter \"Name='{self._ps_quote(printer_name)}'\" | "
            "Select-Object DetectedErrorState | ConvertTo-Json"
        )
        result = self._run_powershell(command)
        if not result["success"]:
            return TonerStatus.UNKNOWN, None

        try:
            data = json.loads(result["output"])
            if isinstance(data, list):
                data = data[0] if data else {}
            error_state = data.get("DetectedErrorState", 0)
            if error_state == 2:
                return TonerStatus.OK, None
            return TonerStatus.UNKNOWN, None
        except (json.JSONDecodeError, KeyError):
            return TonerStatus.UNKNOWN, None

    # ------------------------------------------------------------------
    # Printing
    # ------------------------------------------------------------------
    @staticmethod
    def _parse_page_range(page_range: Optional[str], total_pages: int) -> List[int]:
        """Return 0-based page indices to print."""
        if not page_range or str(page_range).strip().lower() in ("", "all"):
            return list(range(total_pages))
        indices = set()
        for part in str(page_range).split(","):
            part = part.strip()
            if not part:
                continue
            if "-" in part:
                start_s, end_s = part.split("-", 1)
                start = int(start_s) if start_s.strip() else 1
                end = int(end_s) if end_s.strip() else total_pages
                start = max(1, start)
                end = min(total_pages, end)
                for i in range(start, end + 1):
                    indices.add(i - 1)
            else:
                idx = int(part) - 1
                if 0 <= idx < total_pages:
                    indices.add(idx)
        return sorted(indices)

    def _count_queue(self, printer_name: str) -> int:
        """Number of jobs currently in the printer's spooler queue."""
        result = self._run_powershell(
            f'Get-PrintJob -PrinterName "{self._ps_quote(printer_name)}" '
            "| Measure-Object | Select-Object -ExpandProperty Count"
        )
        if not result["success"]:
            return 0
        try:
            return int(result["output"].strip() or 0)
        except ValueError:
            return 0

    def _print_with_sumatra(self, printer_name: str, file_path: str, options: Dict) -> None:
        """Tier 1: SumatraPDF invoked directly (no shell, so quoting is exact)."""
        settings_parts = []
        copies = int(options.get("copies", 1) or 1)
        if copies > 1:
            settings_parts.append(f"print-copies {copies}")

        duplex = options.get("duplex", "")
        if duplex in ("double", "duplex", "true", True, "DOUBLE"):
            settings_parts.append("print-duplex")
        elif duplex in ("single", "simplex", "false", False, "SINGLE"):
            settings_parts.append("print-no-duplex")

        color_mode = options.get("color_mode", "")
        if isinstance(color_mode, str) and color_mode.upper() in ("BW", "MONOCHROME"):
            settings_parts.append("print-color-mode 1")
        elif isinstance(color_mode, str) and color_mode.upper() == "COLOR":
            settings_parts.append("print-color-mode 2")

        paper_size = options.get("paper_size", "A4")
        if paper_size:
            paper_map = {"A3": "A3", "A4": "A4", "A5": "A5", "LETTER": "Letter"}
            mapped = paper_map.get(str(paper_size).upper(), paper_size)
            settings_parts.append(f"print-paper {mapped}")

        cmd = [self.sumatra_pdf_path]
        if settings_parts:
            cmd += ["-print-settings", ", ".join(settings_parts)]
        cmd += ["-print-to", printer_name, file_path]

        logger.info(f"SumatraPDF print: {' '.join(cmd[:6])} ...")
        result = subprocess.run(
            cmd,
            capture_output=True, text=True, timeout=180,
            **_no_window_kwargs(),
        )
        if result.returncode != 0:
            raise RuntimeError(
                f"SumatraPDF exited with code {result.returncode}: "
                f"{(result.stderr or '').strip()[:200]}"
            )

    def _print_with_dotnet(self, printer_name: str, file_path: str, options: Dict) -> None:
        """Tier 2: rasterize the PDF with pypdfium2 and print via .NET.

        Requires no third-party applications, only the pypdfium2 wheel.
        """
        try:
            import pypdfium2 as pdfium
        except ImportError as exc:
            raise RuntimeError("pypdfium2 not installed") from exc

        pdf = pdfium.PdfDocument(file_path)
        total_pages = len(pdf)
        if total_pages == 0:
            raise RuntimeError("PDF has no pages")

        wanted = self._parse_page_range(options.get("page_range"), total_pages)
        if not wanted:
            raise RuntimeError("Page range selected no pages")

        copies = int(options.get("copies", 1) or 1)
        duplex = options.get("duplex", "")
        duplex_arg = "double" if duplex in ("double", "duplex", "true", True, "DOUBLE") else "single"
        color_mode = options.get("color_mode", "")
        color_arg = "monochrome" if isinstance(color_mode, str) and color_mode.upper() in ("BW", "MONOCHROME") else "color"

        with tempfile.TemporaryDirectory(prefix="nexino-print-") as tmp_dir:
            tmp_path = Path(tmp_dir)
            for idx in wanted:
                page = pdf[idx]
                try:
                    bitmap = page.render(scale=2.0)
                    image = bitmap.to_pil()
                    image.save(tmp_path / f"{idx:05d}.png", "PNG")
                finally:
                    try:
                        page.close()
                    except Exception:
                        pass
            try:
                pdf.close()
            except Exception:
                pass

            result = self._run_powershell_script(
                _PS_PRINT_TEMPLATE,
                [printer_name, str(copies), duplex_arg, color_arg, str(tmp_path)],
                timeout=300,
            )
            if not result["success"]:
                raise RuntimeError(f".NET print failed: {result.get('error')}")

    def _print_with_shell_verb(self, printer_name: str, file_path: str) -> None:
        """Tier 3: the Windows 'printto' shell verb (uses the registered handler)."""
        result = self._run_powershell_script(
            _PS_PRINTTO_TEMPLATE,
            [file_path, printer_name],
            timeout=180,
        )
        if not result["success"]:
            raise RuntimeError(f"printto verb failed: {result.get('error')}")

    def submit_job(
        self, printer_name: str, file_path: str, options: Optional[Dict] = None,
    ) -> str:
        job_id = f"WIN-{uuid.uuid4().hex[:12].upper()}"
        options = options or {}
        file_path_str = str(file_path)

        if not Path(file_path_str).exists():
            raise RuntimeError(f"File not found: {file_path_str}")
        if not self._printer_exists(printer_name):
            raise RuntimeError(f"Printer not found: {printer_name}")

        attempts: List[str] = []

        # Tier 1: SumatraPDF
        if file_path_str.lower().endswith(".pdf") and self.sumatra_pdf_path \
                and Path(self.sumatra_pdf_path).exists():
            try:
                self._print_with_sumatra(printer_name, file_path_str, options)
                self._record_job(job_id, printer_name, file_path_str, "sumatra")
                return job_id
            except Exception as e:
                attempts.append(f"SumatraPDF: {e}")
                logger.warning(f"SumatraPDF print failed, falling back: {e}")

        # Tier 2: rasterize + .NET PrintDocument
        try:
            self._print_with_dotnet(printer_name, file_path_str, options)
            self._record_job(job_id, printer_name, file_path_str, "dotnet")
            return job_id
        except Exception as e:
            attempts.append(f"raster/.NET: {e}")
            logger.warning(f"Rasterized print failed, falling back: {e}")

        # Tier 3: shell printto verb
        try:
            self._print_with_shell_verb(printer_name, file_path_str)
            self._record_job(job_id, printer_name, file_path_str, "printto")
            return job_id
        except Exception as e:
            attempts.append(f"printto: {e}")
            logger.warning(f"printto verb failed: {e}")

        raise RuntimeError(
            f"All print methods failed for '{printer_name}': " + " | ".join(attempts)
        )

    def _record_job(self, job_id: str, printer_name: str, file_path: str, method: str) -> None:
        self._jobs[job_id] = {
            "id": job_id,
            "status": "submitted",
            "method": method,
            "printer": printer_name,
            "file": file_path,
            "submitted_at": time.time(),
        }
        logger.info(f"Print job {job_id} submitted to '{printer_name}' via {method}.")

    def cancel_job(self, job_id: str) -> bool:
        if job_id not in self._jobs:
            return False

        job = self._jobs[job_id]
        printer_name = job.get("printer", "")

        command = (
            f'Get-PrintJob -PrinterName "{self._ps_quote(printer_name)}" | '
            "Remove-PrintJob -Confirm:$false"
        )
        result = self._run_powershell(command)

        if result["success"]:
            job["status"] = "cancelled"
            logger.info(f"Windows job {job_id} cancelled.")
            return True

        return False

    def get_job_status(self, job_id: str) -> Dict:
        """Reflect the real state of the job via the printer and its queue."""
        if job_id not in self._jobs:
            return {"id": job_id, "status": "unknown", "message": "Job not found"}

        job = self._jobs[job_id]
        if job.get("status") == "cancelled":
            return {**job, "status": "cancelled"}

        printer_name = job.get("printer", "")
        try:
            status = self.get_status(printer_name)
        except Exception as e:
            return {**job, "status": "unknown", "message": str(e)}

        if status.state == PrinterState.ERROR:
            return {**job, "status": "error", "message": status.error_message or "Printer error"}
        if status.state == PrinterState.OFFLINE:
            return {**job, "status": "error", "message": "Printer offline"}

        queue_count = self._count_queue(printer_name)
        if queue_count > 0:
            return {**job, "status": "processing", "message": f"{queue_count} job(s) in queue"}

        return {**job, "status": "completed"}

    def get_capabilities(self, printer_name: str) -> Dict:
        command = (
            f'Get-Printer -Name "{self._ps_quote(printer_name)}" | '
            "Select-Object DriverName | ConvertTo-Json"
        )
        result = self._run_powershell(command)

        capabilities = {
            "supported_paper_sizes": ["A4", "Letter", "Legal", "A3"],
            "supports_color": True,
            "supports_duplex": True,
            "max_copies": 99,
            "supports_page_range": True,
            "driver_name": "Unknown",
        }

        if result["success"]:
            try:
                data = json.loads(result["output"])
                if isinstance(data, list):
                    data = data[0] if data else {}
                capabilities["driver_name"] = data.get("DriverName", "Unknown")
            except json.JSONDecodeError:
                pass

        return capabilities