# Raspberry Flavoured Optimized

An **unofficial** low-RAM build of [Raspberry Flavoured](https://www.curseforge.com/minecraft/modpacks/raspberry-flavoured)
3.3.1 by **raspmary**, tuned to run on a PC with **8 GB of RAM in total**. Gameplay content is unchanged:
every content mod, recipe, worldgen and resource pack of the original is kept, so 3.3.1 worlds are compatible.

Minecraft 1.19.2 · Forge 43.5.1 · Java 17

This repository holds the **build script**, not the modpack itself. The pack contains raspmary's configs,
scripts and bundled resource packs, which aren't mine to re-host, so you build it locally from the official
upstream download. The build is fully scripted and takes a few minutes.

## Results

Same PC, same world seed and the same scripted 5-minute route (spawn, two fresh areas 3000 blocks away,
then back). Heap capped at 4 GB for stock and 3.5 GB for the optimized build.

| | Stock 3.3.1 | Optimized | Change |
|---|---|---|---|
| Peak process memory | 4.7 GB | 3.6 GB | −1.1 GB (−24 %) |
| Main menu, process memory | 4.1 GB | 2.5 GB | −1.6 GB (−39 %) |
| In world, process memory | 4.6–4.7 GB | 3.4–3.5 GB | −1.2 GB (−25 %) |
| In world, live heap | 1.73–1.77 GB | 1.25–1.31 GB | −0.47 GB (−27 %) |
| Time to title screen | 46 s | 40 s | −6 s |
| Time into the world | 108 s | 100 s | −8 s |
| Longest GC pause | 64 ms | 40 ms | −24 ms |
| FPS (120 cap) | 119 | 119 | same |

Stock defaults to render distance 12 and this build to 8, which accounts for part of the in-world saving
(the main-menu saving has no world loaded). Both runs logged the same errors, and in-game screenshots were
checked at every stop. Raw summaries are in [`results/`](results/) (`baseline*` = stock, `final` = this build).

The server boots in about 32 s and settles at about 820 MB of heap after pre-generation (cap 4 GB).

See [`changes.toml`](changes.toml) for every change and its reason. The short version:

- **Memory:** ModernFix dynamic resources and the other memory options, FerriteCore compact maps,
  JEI prefix-only tooltip search, and a JVM heap of 1–3.5 GB that shrinks back after use.
- **Performance:** added Clumps, AI-Improvements, Structure Layout Optimizer, Smooth Boot (Reloaded) and
  Dynamic FPS; updated Embeddium and MemoryLeakFix; fewer weather particles; baked lantern and sign models.
- **Defaults:** render distance 8, simulation distance 6, mipmaps 2, biome blend 1, entity distance 75 %,
  decreased particles, 120 FPS cap.
- **Server pack:** 54 client-only mods left out, spark and Chunky added.

## Build

Needs Python 3.11+, network access (about 4 GB of downloads, cached in `.cache/`) and Java 17 for the
Forge server installer.

```sh
git clone https://github.com/p1nkhamster/rf-optimized.git
cd rf-optimized
python3 -I build.py build --java /path/to/java17/bin/java
```

`--no-server` skips the server pack, and then Java isn't needed. Every download is checked against its
CurseForge size or Modrinth sha512.

The release files land in `dist/release/`:

| File | What it is |
|---|---|
| `install-client.sh` | One-step installer for Prism Launcher on Linux. |
| `Raspberry Flavoured Optimized-3.3.1-opt1.zip` | The modpack in CurseForge format, importable into any launcher. |
| `Raspberry Flavoured Optimized-3.3.1-opt1-server.zip` | Server pack; its `install.sh` downloads Forge and the mods. |
| `README.md`, `CHANGES.md`, `SHA256SUMS` | Player instructions, change list, checksums. |

`dist/instance/` (a ready Prism instance folder) and `dist/server/` (an installed server) are also produced.

## Install

**Linux + Prism Launcher:** install [Prism](https://prismlauncher.org) and start it once, then:

```sh
cd dist/release
./install-client.sh            # creates the instance with memory and Java flags set
./install-client.sh --update   # later: update, keeping worlds, settings, screenshots and servers
```

**Any other launcher:** import the `.zip` as a CurseForge modpack, then set the memory to 1024–3584 MB
and add the Java arguments listed in `dist/release/README.md`. The zip format can't carry those settings.

**Server:**

```sh
unzip "dist/release/Raspberry Flavoured Optimized-3.3.1-opt1-server.zip" -d ~/rf-server
cd ~/rf-server/"Raspberry Flavoured Optimized-3.3.1-opt1-server"
JAVA=/path/to/java17 ./install.sh
# read the Minecraft EULA (https://aka.ms/MinecraftEULA), then: echo eula=true > eula.txt
JAVA=/path/to/java17 ./start.sh
```

## Repository layout

| Path | Contents |
|---|---|
| `build.py` | Fetches upstream and mods, applies changes, writes all outputs. |
| `changes.toml` | The build definition: mods added/removed, config edits, JVM args, client-only list, server settings. |
| `baseline.toml` | Stock pack (plus server-side spark/Chunky), used for the comparison runs. |
| `rfopt/patches.py` | Config editing (TOML/JSON/INI/properties/text) and optional jar patches. |
| `overrides/` | Files laid over the upstream overrides (`options.txt`, Dynamic FPS config). |
| `release/` | Player README and the client installer template. |
| `testkit/` | Measurement harness: a small Forge mod and a KubeJS route script, only in `--test` builds. |
| `tools/` | Measurement and analysis scripts (`measure.py`, `servertest.py`, `compare.py`, …). |
| `results/` | Measurement summaries. |

To change the pack, edit `changes.toml` and rebuild. To measure a build, run
`python3 -I build.py build --test` and then `python3 -I tools/measure.py dist <label>`. Measuring needs a local
Prism Launcher install and creates a separate `rfopt-<label>` instance.

## Credits and licence

Raspberry Flavoured is made by **raspmary**; all credit for the pack goes to them. Please report problems
with this build here, not to them. The mods are downloaded from their authors' CurseForge and Modrinth pages.

The files in this repository are released under the [Unlicense](LICENSE). That covers only this repository,
not Raspberry Flavoured or the mods and resource packs the build downloads.
