from pythonsrc.operators.base import BasePrinterOperator

class PrinterFactory:
    @staticmethod
    def create(firmware: str, base_url: str, api_key: str | None = None) -> BasePrinterOperator:
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
