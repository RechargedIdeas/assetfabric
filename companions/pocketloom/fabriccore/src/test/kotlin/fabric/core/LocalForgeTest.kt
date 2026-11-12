package fabric.core

import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertTrue

class LocalForgeTest {
    private val cave = Palettes.colours("cave_stone")
    private val hero = Palettes.colours("hero_teal")

    @Test fun deterministic() {
        for (seed in 1L..8L) {
            assertEquals(LocalForge.cave(seed, palette = cave).sha256, LocalForge.cave(seed, palette = cave).sha256)
            assertEquals(LocalForge.sprite(seed, palette = hero).sha256, LocalForge.sprite(seed, palette = hero).sha256)
        }
    }

    @Test fun cavesPassGatesAcrossSeeds() {
        val ok = (1L..64L).count { LocalForge.cave(it, palette = cave).ok }
        assertTrue(ok >= 54, "raw cave gate pass rate $ok/64")
        // through the executor (gate → retry on derived sub-seeds) every seed yields a passing cave
        val ex = LocalExecutor(null) { Palettes.colours(it) }
        for (seed in 1L..64L) {
            val r = ex.execute(JobSpec("c$seed", "local.cave", mapOf("seed" to seed)))
            assertEquals(true, r["ok"], "seed $seed")
            assertEquals(r["sha256"], ex.execute(JobSpec("c$seed", "local.cave", mapOf("seed" to seed)))["sha256"])
        }
    }

    @Test fun spritesPassGatesAcrossSeeds() {
        val ok = (1L..64L).count { LocalForge.sprite(it, palette = hero).ok }
        assertTrue(ok >= 54, "sprite gate pass rate $ok/64")
        val s = LocalForge.sprite(5, palette = hero)
        assertTrue(s.gates.first { it.gate == "palette_locked" }.ok)
        assertTrue(s.gates.first { it.gate == "symmetric" }.ok)
    }

    @Test fun pngIsWellFormed() {
        val a = LocalForge.cave(2, palette = cave)
        assertEquals(listOf(0x89, 0x50, 0x4E, 0x47), a.png.take(4).map { it.toInt() and 0xff })
        assertEquals(48 to 32, Captures.dimensions(a.png))
    }

    @Test fun palettesBundled() {
        assertTrue("hero_teal" in Palettes.names() && "cave_stone" in Palettes.names())
    }
}
