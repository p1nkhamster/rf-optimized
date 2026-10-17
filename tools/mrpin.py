#!/usr/bin/env python3
"""Print sha512-pinned [[add]] entries for the newest Forge 1.19.2 version of Modrinth projects.

Usage: python3 -I tools/mrpin.py <slug> [<slug> ...]  >> changes.toml   (then fill in reason/side)
"""
from __future__ import annotations

import json
import sys
import urllib.parse
import urllib.request


def main() -> None:
    q = urllib.parse.urlencode({"loaders": '["forge"]', "game_versions": '["1.19.2"]'})
    for slug in sys.argv[1:]:
        with urllib.request.urlopen(f"https://api.modrinth.com/v2/project/{slug}/version?{q}", timeout=30) as r:
            versions = json.load(r)
        if not versions:
            print(f"# {slug}: no Forge 1.19.2 version", file=sys.stderr)
            continue
        v = versions[0]
        f = ([x for x in v["files"] if x["primary"]] or v["files"])[0]
        deps = [(d.get("project_id"), d["dependency_type"]) for d in v["dependencies"]]
        print(f'\n[[add]]  # https://modrinth.com/mod/{slug}  deps: {deps}\nslug = "{slug}"\n'
              f'version = "{v["version_number"]}"\nfilename = "{f["filename"]}"\nurl = "{f["url"]}"\n'
              f'sha512 = "{f["hashes"]["sha512"]}"\nreason = ""')


if __name__ == "__main__":
    main()
