from abc import ABC, abstractmethod

class PrinterConnectionError(Exception):
    """Exception raised for unrecoverable errors connecting to the printer."""
    pass

class BasePrinterOperator(ABC):
    @abstractmethod
    def connect(self) -> bool:
        pass

    @abstractmethod
    def upload_file(self, local_path: str, remote_name: str) -> bool:
        pass

    @abstractmethod
    def start_print(self, filename: str) -> bool:
        pass

    @abstractmethod
    def cancel_print(self) -> bool:
        pass

    @abstractmethod
    def pause_print(self) -> bool:
        pass

    @abstractmethod
    def resume_print(self) -> bool:
        pass

    @abstractmethod
    def get_printer_state(self) -> dict:
        pass
