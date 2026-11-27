# Hostile fixture: passes the static policy but hides mutable state, so two exports of the same scene differ.
# The sandboxed contract suite must refuse it (determinism gate).
import json

from forge.universal.exporters.base import Adapter, Pack


class Hostile(Adapter):
    id = "nondeterministic"
    name = "hostile fixture nondeterministic"
    dims = ("3d",)
    formats = ("hostile-nondeterministic",)
    calls = [0]

    def export(self, scene, out):
        self.calls[0] += 1
        pack = Pack(out)
        pack.add("scene.json", json.dumps({"digest": scene.digest(), "call": self.calls[0]}))
        return pack.finish(self, scene)
