#!/bin/sh
# @@PACK_NAME@@ @@PACK_VERSION@@ - Prism Launcher installer (Linux).
#
# Usage:  ./install-client.sh            create the instance
#         ./install-client.sh --update   update an existing install (keeps saves, options, screenshots, servers)
#
# Put this script next to "@@CF_ZIP@@" and run it. It:
#   1. finds your Prism Launcher data folder (normal or Flatpak install; override with PRISM_DIR=/path),
#   2. downloads every mod / resource pack from CurseForge's CDN and checks each one's sha256,
#   3. unpacks the pack's configs and scripts,
#   4. creates the instance "@@PACK_NAME@@ @@PACK_VERSION@@" with memory and Java flags already set.
# Downloads are cached in ~/.cache/rf-optimized, so re-running or updating is quick.
# Needs: curl, unzip, sha256sum.
set -eu

INSTANCE_ID="@@INSTANCE_ID@@"
INSTANCE_NAME="@@PACK_NAME@@ @@PACK_VERSION@@"
CF_ZIP="@@CF_ZIP@@"
MIN_MB=@@MIN_MB@@
MAX_MB=@@MAX_MB@@
JVM_ARGS="@@JVM_ARGS@@"
CACHE="${XDG_CACHE_HOME:-$HOME/.cache}/rf-optimized/downloads"

die() { echo "error: $*" >&2; exit 1; }
for tool in curl unzip sha256sum; do
  command -v "$tool" >/dev/null 2>&1 || die "'$tool' is not installed"
done

update=0
case "${1:-}" in
  --update) update=1 ;;
  "") ;;
  *) die "unknown option '$1' (use --update or nothing)" ;;
esac

here="$(cd "$(dirname "$0")" && pwd)"
zip="$here/$CF_ZIP"
[ -f "$zip" ] || die "can't find '$CF_ZIP' next to this script"

# --- find Prism Launcher -------------------------------------------------------------------------
if [ -z "${PRISM_DIR:-}" ]; then
  for d in "${XDG_DATA_HOME:-$HOME/.local/share}/PrismLauncher" \
           "$HOME/.var/app/org.prismlauncher.PrismLauncher/data/PrismLauncher"; do
    if [ -f "$d/prismlauncher.cfg" ]; then PRISM_DIR="$d"; break; fi
  done
fi
[ -n "${PRISM_DIR:-}" ] && [ -f "$PRISM_DIR/prismlauncher.cfg" ] || die \
  "Prism Launcher not found. Install it (https://prismlauncher.org), start it once, then run this again.
       (Custom location? Run: PRISM_DIR=/path/to/PrismLauncher $0)"

inst_dir="$(sed -n 's/^InstanceDir=//p' "$PRISM_DIR/prismlauncher.cfg" | head -n 1)"
[ -n "$inst_dir" ] || inst_dir="instances"
case "$inst_dir" in /*) ;; *) inst_dir="$PRISM_DIR/$inst_dir" ;; esac
inst="$inst_dir/$INSTANCE_ID"
mc="$inst/minecraft"

if [ -d "$inst" ] && [ "$update" -eq 0 ]; then
  die "'$inst' already exists. Run with --update to update it (your worlds and settings are kept)."
fi
if [ ! -d "$inst" ] && [ "$update" -eq 1 ]; then
  die "nothing to update at '$inst'. Run without --update to install."
fi
if pgrep -x prismlauncher >/dev/null 2>&1; then
  echo "note: Prism Launcher is running. Close and reopen it after this finishes so it picks up the changes."
fi

# --- download mods and resource packs ------------------------------------------------------------
mkdir -p "$CACHE"
tab="$(printf '\t')"
total="$(sed -n '/^__LOCK__$/,$p' "$0" | grep -c "$tab")"
n=0
echo "Downloading $total files (cached in $CACHE)..."
sed -n '/^__LOCK__$/,$p' "$0" | grep "$tab" | while IFS="$tab" read -r path sha url; do
  n=$((n + 1))
  file="$CACHE/$sha"
  if [ -f "$file" ] && echo "$sha  $file" | sha256sum -c --status; then continue; fi
  printf '  [%d/%d] %s\n' "$n" "$total" "${path#*/}"
  curl -fsSL --retry 3 -o "$file.part" "$url" || die "download failed: $url"
  echo "$sha  $file.part" | sha256sum -c --status || die "checksum mismatch: $path"
  mv "$file.part" "$file"
done

# --- build the instance in a temp folder, then swap it in ----------------------------------------
mkdir -p "$inst_dir"  # a fresh Prism install has no instances folder until the first instance exists
work="$(mktemp -d "$inst_dir/.rf-optimized-install.XXXXXX")"
trap 'rm -rf "$work"' EXIT INT TERM
echo "Unpacking configs..."
unzip -q "$zip" 'overrides/*' -d "$work"
mv "$work/overrides" "$work/minecraft"
mkdir -p "$work/minecraft/mods" "$work/minecraft/resourcepacks"
sed -n '/^__LOCK__$/,$p' "$0" | grep "$tab" | while IFS="$tab" read -r path sha url; do
  ln "$CACHE/$sha" "$work/minecraft/$path" 2>/dev/null || cp "$CACHE/$sha" "$work/minecraft/$path"
done

if [ "$update" -eq 1 ]; then
  # Keep the player's own things; everything else comes fresh from the new version.
  for keep in saves options.txt screenshots servers.dat schematics; do
    if [ -e "$mc/$keep" ]; then rm -rf "$work/minecraft/$keep"; mv "$mc/$keep" "$work/minecraft/$keep"; fi
  done
fi

cat > "$work/instance.cfg" <<EOF
[General]
InstanceType=OneSix
name=$INSTANCE_NAME
iconKey=rf_optimized
OverrideMemory=true
MinMemAlloc=$MIN_MB
MaxMemAlloc=$MAX_MB
OverrideJavaArgs=true
JvmArgs=$JVM_ARGS
AutomaticJava=true
ManagedPack=false
EOF
cat > "$work/mmc-pack.json" <<'EOF'
@@MMC_PACK@@
EOF
mkdir -p "$PRISM_DIR/icons"
unzip -p "$zip" overrides/icon.png > "$PRISM_DIR/icons/rf_optimized.png" 2>/dev/null || rm -f "$PRISM_DIR/icons/rf_optimized.png"

rm -rf "$inst"
mv "$work" "$inst"
trap - EXIT INT TERM

echo
echo "Installed '$INSTANCE_NAME' to $inst"
echo "Open Prism Launcher and press Launch. The first start downloads Minecraft, Forge and Java 17."
echo "Memory is set to $MIN_MB-$MAX_MB MB. Keep it there on an 8 GB PC."
exit 0

# Files to download: path<TAB>sha256<TAB>url (generated by build.py). Kept in a quoted heredoc so the
# file stays valid shell even though some filenames contain quotes.
: <<'__END_LOCK__'
__LOCK__
@@LOCK@@
__END_LOCK__
