"""Abstract base classes and exceptions for printer operators."""

from abc import ABC, abstractmethod


class PrinterConnectionError(Exception):
    """Exception raised for unrecoverable errors connecting to the printer."""
    pass

class BasePrinterOperator(ABC):
    """Abstract base class defining the contract for interacting with a 3D printer.

    Subclasses must implement these methods to support specific printer firmwares
    (e.g., OctoPrint, Moonraker).
    """

    @abstractmethod
    def connect(self) -> bool:
        """Establish a connection to the printer.

        Returns:
            bool: True if connection is successful, False otherwise.

        Raises:
            PrinterConnectionError: If connection fails unrecoverably.
        """
        pass

    @abstractmethod
    def upload_file(self, local_path: str, remote_name: str) -> bool:
        """Upload a G-code file to the printer's storage.

        Args:
            local_path: The local filesystem path to the G-code file.
            remote_name: The target filename on the printer.

        Returns:
            bool: True if upload is successful, False otherwise.
        """
        pass

    @abstractmethod
    def start_print(self, filename: str) -> bool:
        """Start a print job for a previously uploaded file.

        Args:
            filename: The name of the file to print.

        Returns:
            bool: True if the print started successfully, False otherwise.
        """
        pass

    @abstractmethod
    def cancel_print(self) -> bool:
        """Cancel the currently active print job.

        Returns:
            bool: True if the print was cancelled, False otherwise.
        """
        pass

    @abstractmethod
    def pause_print(self) -> bool:
        """Pause the currently active print job.

        Returns:
            bool: True if the print was paused, False otherwise.
        """
        pass

    @abstractmethod
    def resume_print(self) -> bool:
        """Resume a paused print job.

        Returns:
            bool: True if the print was resumed, False otherwise.
        """
        pass

    @abstractmethod
    def get_printer_state(self) -> dict:
        """Retrieve the current state of the printer.

        Returns:
            dict: A dictionary containing printer state information, such as temperatures and status.
        """
        pass
