"""Factory pattern for instantiating printer operators."""

from pythonsrc.operators.base import BasePrinterOperator


class PrinterFactory:
    """Factory for instantiating the appropriate printer operator based on firmware type."""

    @staticmethod
    def operator_class(firmware: str) -> type[BasePrinterOperator]:
        """The operator *class* for a firmware, without constructing one.

        The dispatch gate needs to know whether a firmware can be printed to before it
        has an address or a credential to build an operator with, and long before it
        spawns a subprocess — `BambuOperator.starts_prints` is False, and the only
        refusal worth having is one that arrives before the first side effect.

        Args:
            firmware: The firmware name, in `create`'s vocabulary and equally
                case-insensitive.

        Returns:
            The `BasePrinterOperator` subclass that speaks it.

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
            return MoonrakerOperator
        elif firmware == "octoprint":
            from pythonsrc.operators.octoprint_operator import OctoPrintOperator
            return OctoPrintOperator
        elif firmware == "bambu":
            from pythonsrc.operators.bambu_operator import BambuOperator
            return BambuOperator
        else:
            raise ValueError(f"Unknown firmware type: {firmware}")

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
        cls = PrinterFactory.operator_class(firmware)
        # `serial` is Bambu's alone. Passed by name to the one constructor that takes it
        # rather than to all three, so the other two keep their two-argument shape.
        if cls.firmware == "bambu":
            return cls(base_url, api_key, serial=serial)
        return cls(base_url, api_key)
