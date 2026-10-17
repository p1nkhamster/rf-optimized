package rfopt.testkit;

import com.mojang.logging.LogUtils;
import net.minecraft.client.Minecraft;
import net.minecraft.client.Screenshot;
import net.minecraft.client.gui.screens.Screen;
import net.minecraft.client.gui.screens.TitleScreen;
import net.minecraftforge.api.distmarker.Dist;
import net.minecraftforge.common.MinecraftForge;
import net.minecraftforge.event.TickEvent;
import net.minecraftforge.fml.common.Mod;
import net.minecraftforge.fml.loading.FMLEnvironment;
import org.slf4j.Logger;

/**
 * Test-only harness (never shipped): waits 45 s on the title screen, opens saves/rftest, then logs FPS
 * and takes a screenshot at each stop of the scripted flight path.
 * Done in Java because a blocking loadLevel call from a KubeJS handler holds Rhino's global lock and
 * deadlocks the server thread (EntityJS runs script hooks for every entity it creates).
 * Minecraft is referenced by SRG names since this compiles against the SRG-named client jar.
 */
@Mod("rftestkit")
public class RfTestKit {
    private static final Logger LOG = LogUtils.getLogger();
    private int titleTicks;
    private int worldTicks;
    private boolean opened;

    public RfTestKit() {
        if (FMLEnvironment.dist == Dist.CLIENT) {
            MinecraftForge.EVENT_BUS.addListener(this::onClientTick);
        }
    }

    private void onClientTick(TickEvent.ClientTickEvent event) {
        if (event.phase != TickEvent.Phase.END) {
            return;
        }
        Minecraft mc = Minecraft.m_91087_();              // getInstance()
        Screen screen = mc.f_91080_;                       // screen
        if (!opened && screen instanceof TitleScreen) {
            if (++titleTicks == 1) {
                LOG.info("RFTEST title");
            }
            if (titleTicks == 20 * 45) {
                opened = true;
                LOG.info("RFTEST loading");
                mc.m_231466_().m_233133_(screen, "rftest");  // createWorldOpenFlows().loadLevel(...)
            }
        }
        if (mc.f_91073_ != null) {                              // level
            ++worldTicks;
            if (worldTicks % 100 == 0) {
                LOG.info("RFTEST fps " + mc.f_90977_);         // fpsString
            }
            // One screenshot per stop of the server-side flight path (stops change every 75 s), taken
            // just before each measurement marker so rendering (models/textures) can be checked by eye.
            if (worldTicks % (20 * 75) == 20 * 55) {
                String name = "rftest-" + (worldTicks / (20 * 75)) + ".png";
                Screenshot.m_92295_(mc.f_91069_, name, mc.m_91385_(), msg -> { });  // grab(gameDir, name, mainRenderTarget, ..)
                LOG.info("RFTEST screenshot " + name);
            }
        }
    }
}
