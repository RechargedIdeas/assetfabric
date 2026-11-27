# Hostile fixture: violates the static policy (dynamic import, open) AND, when run directly in the sandbox with the static
# gate bypassed, tries a network connection and a write outside the scratch dir. Both must fail at runtime.
from forge.universal.exporters.base import Adapter


class Hostile(Adapter):
    id = "sandbox-escape"
    name = "hostile fixture sandbox-escape"
    dims = ("3d",)
    formats = ("hostile-sandbox-escape",)

    def export(self, scene, out):
        sock = __import__("socket")
        try:
            sock.create_connection(("1.1.1.1", 80), timeout=2)
            net = "open"
        except Exception as e:
            net = type(e).__name__
        try:
            with open("/var/tmp/assetfabric_sandbox_escape_probe", "w") as f:
                f.write("escaped")
            fs = "written"
        except Exception as e:
            fs = type(e).__name__
        raise RuntimeError(f"net={net} fs={fs}")
