"""Abstract base classes and exceptions for printer operators."""

from abc import ABC, abstractmethod


class PrinterConnectionError(Exception):
    """Exception raised for unrecoverable errors connecting to the printer."""
    pass


class UnsupportedDispatchError(PrinterConnectionError):
    """This firmware is reachable, but this repository will not drive that step of it.

    Distinct from `PrinterConnectionError` in meaning and deliberately a *subclass* of
    it: the dispatch path already stops on that exception, so raising this one changes
    no caller, while a caller that wants to tell "I could not reach the printer" from
    "I reached it and declined" can catch this first.

    Raised today only by `BambuOperator.start_print`. See #73: printing a raw
    `gcode_file` on a Bambu runs our start block instead of the machine's, and the
    machine's cannot be reproduced here without copying Bambu's own macros. The
    dispatch route for that firmware is the 3MF handoff.
    """
    pass

class BasePrinterOperator(ABC):
    """Abstract base class defining the contract for interacting with a 3D printer.

    Subclasses must implement these methods to support specific printer firmwares
    (e.g., OctoPrint, Moonraker).
    """

    #: Which firmware this operator speaks, in `PrinterFactory.create`'s vocabulary —
    #: so `klipper` rather than `moonraker`, and `canonical_firmware` folds the alias.
    #:
    #: It exists because callers were asking with `isinstance`. `AnomalyDetector`
    #: imported two operator classes to decide how to read a state dict, which made a
    #: telemetry module depend on the operator *classes* to answer a question about
    #: their *data*, and left the third firmware silently unhandled. An attribute the
    #: operator declares about itself is the same answer without the import.
    firmware: str = ""

    #: Whether this repository will start a print on this firmware. False is a decision,
    #: not a missing feature — see `UnsupportedDispatchError`.
    #:
    #: Declared on the *class*, so the dispatch gate can ask before it has an operator,
    #: an address or a credential, and that is the whole point of it being here.
    #: `start_print` raising is too late to be the only answer: by then `upload_file`
    #: has already put a file on the printer's storage. Whatever refuses must refuse
    #: before the first side effect.
    starts_prints: bool = True

    #: What to tell a person when `starts_prints` is False, in their words rather than
    #: an exception's. Empty when the operator does start prints. It sits beside the
    #: flag so the refusal and its reason cannot drift apart, and so the same sentence
    #: reaches the HTTP response and the operator's own log.
    dispatch_refusal: str = ""

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
