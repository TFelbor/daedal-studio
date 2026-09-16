"""Factory pattern for instantiating printer operators."""

from pythonsrc.operators.base import BasePrinterOperator


class PrinterFactory:
    """Factory for instantiating the appropriate printer operator based on firmware type."""

    @staticmethod
    def create(
        firmware: str, base_url: str, api_key: str | None = None, serial: str | None = None
    ) -> BasePrinterOperator:
        """Create a printer operator instance for the given firmware.

        Args:
            firmware: The type of firmware ('klipper' (alias: 'moonraker'),
                'octoprint', or 'bambu'). Case-insensitive.
            base_url: The base URL of the printer's API.
            api_key: The optional API key for authentication.
            serial: The printer's serial number. Bambu only, and Bambu genuinely needs
                it — every MQTT topic is `device/<serial>/...`, so a Bambu printer can
                be reached and not addressed. Ignored by the other two rather than
                rejected, so a caller that has one need not know which firmwares care.

        Returns:
            An instance of a subclass of BasePrinterOperator.

        Raises:
            ValueError: If the requested firmware type is unknown.
        """
        firmware = firmware.lower()
        # The UI and config store persist "moonraker" (the API's name) while printer
        # profiles use "klipper" (the firmware's name). Both mean the same operator;
        # without this alias a UI-configured Klipper printer raises ValueError here.
        if firmware == "moonraker":
            firmware = "klipper"
        if firmware == "klipper":
            from pythonsrc.operators.moonraker_operator import MoonrakerOperator
            return MoonrakerOperator(base_url, api_key)
        elif firmware == "octoprint":
            from pythonsrc.operators.octoprint_operator import OctoPrintOperator
            return OctoPrintOperator(base_url, api_key)
        elif firmware == "bambu":
            from pythonsrc.operators.bambu_operator import BambuOperator
            return BambuOperator(base_url, api_key, serial=serial)
        else:
            raise ValueError(f"Unknown firmware type: {firmware}")
