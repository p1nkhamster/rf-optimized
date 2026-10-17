# Raspberry Flavoured Optimized 3.3.1-opt1

An **unofficial** low-RAM build of [Raspberry Flavoured](https://www.curseforge.com/minecraft/modpacks/raspberry-flavoured)
3.3.1 by **raspmary**, tuned to run on a PC with **8 GB of RAM in total**. All gameplay content is unchanged:
every content mod, recipe, worldgen and resource pack of the original is still there, so worlds from
Raspberry Flavoured 3.3.1 are compatible (back them up first anyway). Please report problems with this build at <https://github.com/p1nkhamster/rf-optimized/issues>, not to raspmary.

Minecraft 1.19.2 · Forge 43.5.1 · Java 17

## Files

| File | What it is |
|---|---|
| `install-client.sh` | One-step installer for **Prism Launcher on Linux** (uses the zip below). |
| `Raspberry Flavoured Optimized-3.3.1-opt1.zip` | The modpack (CurseForge format). Mods are downloaded by your launcher. |
| `Raspberry Flavoured Optimized-3.3.1-opt1-server.zip` | Server pack. `install.sh` downloads Forge and the mods. |
| `CHANGES.md` | Every mod that was added, updated or left out of the server, with the reason. |
| `SHA256SUMS` | Checksums of the two zips and `install-client.sh`. |

## Install (client)

### Linux + Prism Launcher: one command

Install [Prism Launcher](https://prismlauncher.org) and start it once. Put `install-client.sh` and the
modpack `.zip` in the same folder, then:

```sh
./install-client.sh
```

It downloads every mod (sha256-checked), unpacks the configs and creates the instance
**"Raspberry Flavoured Optimized 3.3.1-opt1"**, with memory and Java settings already set. Open Prism and
press *Launch*. The first start downloads Minecraft, Forge and Java 17 by itself.
Needs `curl`, `unzip` and `sha256sum`. Flatpak Prism is detected; for a custom location, run
`PRISM_DIR=/path/to/PrismLauncher ./install-client.sh`.

To update to a newer release later, run `./install-client.sh --update`. It keeps your worlds,
settings, screenshots and server list, and replaces mods, configs and scripts with the new version
(mods you added yourself are removed).

### Any other launcher / OS: import the zip

- **Prism Launcher / MultiMC:** *Add Instance → Import → choose the .zip*.
- **CurseForge app:** *Create Custom Profile → Import → choose the .zip*.
- **ATLauncher, etc.:** use the launcher's "import CurseForge modpack" option.

Some mod authors block third-party downloads. If your launcher lists mods to download by hand,
follow its links. That's normal for this pack and the original.

**Then set memory and Java arguments** (the modpack format can't carry these, so launchers won't set them):

- Memory: **minimum 1024 MB, maximum 3584 MB**. Don't give it more on an 8 GB PC: the rest is needed
  by the system and the graphics driver.
- Java arguments (Prism: *Edit Instance → Settings → Java*; CurseForge app: *Settings → Minecraft → Java settings*):

  ```
  -XX:+UseG1GC -XX:MaxGCPauseMillis=50 -XX:+UnlockExperimentalVMOptions -XX:G1NewSizePercent=20 -XX:G1ReservePercent=20 -XX:G1HeapRegionSize=16M -XX:+ParallelRefProcEnabled -XX:+UseStringDeduplication -XX:G1PeriodicGCInterval=30000 -XX:MinHeapFreeRatio=10 -XX:MaxHeapFreeRatio=30 -XX:ReservedCodeCacheSize=256M
  ```

- Java version: **17**.

## Install (server)

```sh
unzip "Raspberry Flavoured Optimized-3.3.1-opt1-server.zip"
cd "Raspberry Flavoured Optimized-3.3.1-opt1-server"
./install.sh          # needs curl, sha256sum and Java 17 (JAVA=/path/to/java17 ./install.sh otherwise)
# read the Minecraft EULA (https://aka.ms/MinecraftEULA), then: echo eula=true > eula.txt
./start.sh            # same JAVA=... override applies
```

Server heap is set in `user_jvm_args.txt` (`-Xmx4G`, enough for a handful of players).
Pre-generate the world once to avoid worldgen lag spikes: `chunky radius 2000` then `chunky start` in the console.
`spark` is included for diagnostics (`/spark tps`, `/spark health`).
Players should use the client pack above.

## What changed

**Memory / startup**
- ModernFix: models are built on demand instead of all at load (`dynamic_resources`).
  Mixin class data is freed after startup. Duplicate resource IDs and climate data are shared,
  entity renderers are created lazily, and spawn chunks are not kept loaded.
- FerriteCore: compact blockstate maps.
- JEI no longer indexes every tooltip into its search tree (search tooltips with `#`).
- JVM: 1 GB → 3.5 GB heap that grows and **shrinks back** (heap free-ratio tuning and periodic GC),
  so the game only holds what it uses.
- Dynamic FPS: low FPS when the window is in the background, and a GC when minimised.
  Its native-library download is switched off.

**Performance**
- Added Clumps, AI-Improvements, Structure Layout Optimizer and Smooth Boot (Reloaded).
- Updated Embeddium (0.3.18 → 0.3.18.1) and MemoryLeakFix (1.0.0 → 1.1.5).
- Fewer rain, splash and waterfall particles (Pretty Rain, Effective).
- Lanterns and hanging signs use baked models (Supplementaries).
- Embeddium uses 2 chunk-builder threads.

**Default video settings** (new installs; change freely in-game)
- Render distance 8, simulation distance 6, mipmaps 2, biome blend 1.
- Entity distance 75 %, decreased particles, 120 FPS cap.

## Measured results

Same PC, same world seed and the same scripted 5-minute route (spawn, then two fresh areas
3000 blocks away, then back). Heap is capped at 4 GB in the stock run and 3.5 GB in the optimized run.

| | Stock 3.3.1 | Optimized |
|---|---|---|
| Time to title screen | 46 s | 40 s |
| Time into the world | 108 s | 100 s |
| Main menu, process memory | 4.1 GB | 2.5 GB |
| In world, live heap | 1.73–1.77 GB | 1.25–1.31 GB |
| In world, process memory | 4.6–4.7 GB | 3.4–3.5 GB |
| Peak process memory | 4.7 GB | 3.6 GB |
| Longest GC pause | 64 ms | 40 ms |

Note on the numbers: stock defaults to render distance 12 and this build to 8, which accounts for
part of the in-world saving. No rendering or log differences showed up between the two: the same
error lines appear in both logs, and in-game screenshots were checked at every stop.

## Credits and licences

- **Raspberry Flavoured** is made by raspmary. This is a derivative made only to lower its memory use.
  All credit for the pack goes to them.
- Mods are downloaded from their authors' CurseForge / Modrinth pages. This release only bundles
  jars whose licences allow it:
  - Clumps, Dynamic FPS, Smooth Boot (Reloaded), Structure Layout Optimizer: MIT
  - Embeddium: LGPL-3.0
  - MemoryLeakFix: LGPL-2.1
  - spark, Chunky: GPL-3.0 (server pack downloads only)
  - Frame Changer, Onion Onion: MIT, already bundled by the original pack
- Source of the build (config changes, scripts, measurements) is reproducible with `build.py`.
