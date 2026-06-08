"""Factory pattern for instantiating printer operators."""

from pythonsrc.operators.base import BasePrinterOperator

class PrinterFactory:
    """Factory for instantiating the appropriate printer operator based on firmware type."""

    @staticmethod
    def create(firmware: str, base_url: str, api_key: str | None = None) -> BasePrinterOperator:
        """Create a printer operator instance for the given firmware.

        Args:
            firmware: The type of firmware (e.g., 'klipper', 'octoprint', 'bambu').
            base_url: The base URL of the printer's API.
            api_key: The optional API key for authentication.

        Returns:
            An instance of a subclass of BasePrinterOperator.

        Raises:
            ValueError: If the requested firmware type is unknown.
        """
        firmware = firmware.lower()
        if firmware == "klipper":
            from pythonsrc.operators.moonraker_operator import MoonrakerOperator
            return MoonrakerOperator(base_url, api_key)
        elif firmware == "octoprint":
            from pythonsrc.operators.octoprint_operator import OctoPrintOperator
            return OctoPrintOperator(base_url, api_key)
        elif firmware == "bambu":
            from pythonsrc.operators.bambu_operator import BambuOperator
            return BambuOperator(base_url, api_key)
        else:
            raise ValueError(f"Unknown firmware type: {firmware}")
