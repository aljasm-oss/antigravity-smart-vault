#!/usr/bin/env python3
"""
Antigravity Smart Skill Vault & Lifecycle Manager (v2.0.1 — Option A: Opt-In & Auto-Prune)
Architected & Designed by: Elgasem (https://github.com/aljasm-oss)
License: Apache License 2.0 (Attribution Required - see NOTICE)

Key guarantees:
1. NEVER touches Google core/protected plugins or Antigravity built-in capabilities.
2. NEVER auto-vaults newly installed cloud Marketplace plugins without explicit opt-in
   (--vault-plugin <name> or one-time --vault-all-plugins).
3. Automatically prunes vaulted skills when a plugin is uninstalled from Antigravity.
4. Automatically refreshes vaulted skills (additions, updates, removals) when an opted-in
   plugin receives a Marketplace update.
5. Distinguishes temporary Disable (enabled: false in config.json, read-only) from Uninstall:
   hides disabled plugins from smart-skill-catalog without deleting their vaulted files, and
   restores them automatically when re-enabled.
6. Supports zero-git-pollution direct reading (--read), permanent skill removal (--remove),
   project scoping (--use), clean rollback (--restore), and silent background sync (--quiet).
"""

import argparse
import datetime
import glob
import json
import os
import re
import shutil
import sys
import tempfile
from pathlib import Path

AUTHOR_SIGNATURE = "Elgasem (https://github.com/aljasm-oss)"
VERSION = "2.0.1"

DEFAULT_CONFIG_DIR = Path.home() / ".gemini" / "config"

PROTECTED_GLOBAL_SKILLS = {
    "firecrawl",
    "reverse-engineer-anything",
    "smart-skill-catalog",
}

# Google Workspace, Gemini API, SDK, and user-critical plugins — strictly NEVER touched.
PROTECTED_PLUGINS = {
    "gcalendar",
    "gdocs",
    "gdrive",
    "gemini-api",
    "gmail",
    "google-antigravity-sdk",
    "gsheets",
    "gslides",
    "telegram-assistant",
}


def atomic_write_text(path: Path, content: str) -> bool:
    """Write file atomically only if content actually changed. Returns True if written."""
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        try:
            if path.read_text(encoding="utf-8") == content:
                return False
        except Exception:
            pass
    fd, tmp_name = tempfile.mkstemp(dir=str(path.parent), prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as f:
            f.write(content)
        os.replace(tmp_name, str(path))
    except Exception:
        if os.path.exists(tmp_name):
            os.remove(tmp_name)
        raise
    return True


def append_sync_log(vault_dir: Path, message: str):
    log_path = vault_dir / "auto_sync.log"
    ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    lines = []
    if log_path.exists():
        try:
            lines = log_path.read_text(encoding="utf-8", errors="ignore").splitlines()[-199:]
        except Exception:
            lines = []
    lines.append(f"[{ts}] {message}")
    atomic_write_text(log_path, "\n".join(lines) + "\n")


def extract_frontmatter(md_path: Path) -> dict:
    try:
        txt = md_path.read_text(encoding="utf-8", errors="ignore")
        m = re.match(r"^---\s*\n(.*?)\n---", txt, re.S)
        if not m:
            return {"name": md_path.parent.name, "description": "", "raw_len": 200}
        fm = m.group(1)
        name_m = re.search(r"^name:\s*(.+)$", fm, re.M)
        desc_m = re.search(r"description:\s*(?:>-\s*\n)?(.+)", fm, re.S)
        desc = desc_m.group(1).strip() if desc_m else ""
        desc = re.sub(r"\s+", " ", desc)
        return {
            "name": name_m.group(1).strip().strip("'\"") if name_m else md_path.parent.name,
            "description": desc,
            "raw_len": len(fm),
        }
    except Exception:
        return {"name": md_path.parent.name, "description": "", "raw_len": 0}


def get_disabled_plugins(config_dir: Path) -> set[str]:
    """Read-only check of config.json to identify temporarily disabled plugins (enabled == False)."""
    cfg_path = config_dir / "config.json"
    if not cfg_path.is_file():
        return set()
    try:
        data = json.loads(cfg_path.read_text(encoding="utf-8"))
        plugins_cfg = data.get("plugins", {})
        if not isinstance(plugins_cfg, dict):
            return set()
        return {
            pname for pname, pcfg in plugins_cfg.items()
            if isinstance(pcfg, dict) and pcfg.get("enabled") is False
        }
    except Exception:
        return set()


def load_policy(config_dir: Path) -> dict:
    vault_dir = config_dir / "smart_vault"
    policy_path = vault_dir / "vault_policy.json"
    plugins_dir = config_dir / "plugins"
    p_vault_root = vault_dir / "plugins"

    if policy_path.exists():
        try:
            data = json.loads(policy_path.read_text(encoding="utf-8"))
            opted = sorted(
                {p for p in data.get("opted_in_plugins", []) if p not in PROTECTED_PLUGINS}
            )
            return {
                "version": VERSION,
                "mode": "option_a_opt_in",
                "opted_in_plugins": opted,
            }
        except Exception:
            pass

    # First-time migration from v1: seed opted_in_plugins ONLY from existing active vaulted plugins
    opted = []
    if p_vault_root.exists():
        for p_dir in sorted(p_vault_root.iterdir()):
            if not p_dir.is_dir():
                continue
            name = p_dir.name
            if name in PROTECTED_PLUGINS:
                continue
            if (plugins_dir / name).is_dir() and any(p_dir.rglob("SKILL.md")):
                opted.append(name)

    return {
        "version": VERSION,
        "mode": "option_a_opt_in",
        "opted_in_plugins": sorted(set(opted)),
    }


def save_policy(config_dir: Path, policy: dict) -> bool:
    policy_path = config_dir / "smart_vault" / "vault_policy.json"
    payload = {
        "version": VERSION,
        "mode": "option_a_opt_in",
        "protected_plugins": sorted(PROTECTED_PLUGINS),
        "opted_in_plugins": sorted(set(policy.get("opted_in_plugins", [])) - PROTECTED_PLUGINS),
    }
    return atomic_write_text(policy_path, json.dumps(payload, ensure_ascii=False, indent=2) + "\n")


def collect_plugin_incoming_skills(plugin_dir: Path) -> list[Path]:
    """Return list of top-level skill directories currently sitting inside an active plugin folder."""
    incoming: list[Path] = []
    p_skills_dir = plugin_dir / "skills"
    if p_skills_dir.is_dir():
        for item in sorted(p_skills_dir.iterdir()):
            if item.is_dir() and any(item.rglob("SKILL.md")):
                incoming.append(item)

    # Support root-level *-skill folders (e.g., neo4j)
    for item in sorted(plugin_dir.iterdir()):
        if item.is_dir() and item.name.endswith("-skill") and (item / "SKILL.md").exists():
            incoming.append(item)
    return incoming


def sync_single_opted_in_plugin(plugin_dir: Path, p_vault_dir: Path) -> int:
    """
    If an opted-in plugin received an upstream Marketplace update (fresh skills present
    in plugin_dir), cleanly replace p_vault_dir with the new set so additions, edits,
    and removed skills all stay in sync.
    """
    incoming = collect_plugin_incoming_skills(plugin_dir)
    if not incoming:
        return 0

    staging_dir = p_vault_dir.parent / f".{p_vault_dir.name}.staging"
    if staging_dir.exists():
        shutil.rmtree(staging_dir)
    staging_dir.mkdir(parents=True, exist_ok=True)

    moved = 0
    try:
        for item in incoming:
            dst = staging_dir / item.name
            if dst.exists():
                shutil.rmtree(dst)
            shutil.move(str(item), str(dst))
            moved += 1

        if p_vault_dir.exists():
            shutil.rmtree(p_vault_dir)
        os.replace(str(staging_dir), str(p_vault_dir))
    except Exception:
        if staging_dir.exists():
            shutil.rmtree(staging_dir, ignore_errors=True)
        raise

    # Safe handling for plugins like neo4j whose plugin.json uses "skills": ["."]
    pjson_path = plugin_dir / "plugin.json"
    if pjson_path.is_file():
        try:
            pjson = json.loads(pjson_path.read_text(encoding="utf-8"))
            if pjson.get("skills") == ["."]:
                (plugin_dir / "skills").mkdir(exist_ok=True)
                pjson["skills"] = ["./skills"]
                atomic_write_text(pjson_path, json.dumps(pjson, indent=2) + "\n")
        except Exception:
            pass

    return moved


def build_vault_index(config_dir: Path, disabled_plugins: set[str] | None = None) -> list:
    vault_dir = config_dir / "smart_vault"
    entries = []
    if not vault_dir.exists():
        return entries

    if disabled_plugins is None:
        disabled_plugins = get_disabled_plugins(config_dir)

    for md_file in sorted(vault_dir.rglob("SKILL.md")):
        rel = md_file.relative_to(vault_dir)
        if any(part.startswith(".") for part in rel.parts):
            continue
        parts = rel.parts
        category = parts[0] if len(parts) > 1 else "general"
        source = parts[1] if category == "plugins" and len(parts) > 2 else category
        fm = extract_frontmatter(md_file)
        is_disabled = (category == "plugins" and source in disabled_plugins)
        entries.append({
            "name": md_file.parent.name,
            "skill_id": fm["name"],
            "category": category,
            "source": source,
            "disabled": is_disabled,
            "description": fm["description"],
            "path": str(md_file),
            "dir": str(md_file.parent),
            "tokens_est": max(1, int(fm["raw_len"] / 3.5)),
        })
    return entries


def format_domain_label(source: str, count: int) -> str:
    pretty = {
        "canva": "Canva",
        "egm": "EGM",
        "figma": "Figma",
        "firebase": "Firebase",
        "firecrawl": f"Firecrawl ({count} workflows)",
        "flutter": "Flutter/Dart",
        "incident-io": "incident.io",
        "invideo": "invideo",
        "mobbin": "Mobbin",
        "monday": "monday.com",
        "n8n-skills": f"n8n ({count} skills)",
        "neo4j": f"Neo4j ({count} skills)",
        "standalone": f"UI/Design & Presentations ({count} local skills)",
        "tavily": "Tavily",
    }
    return pretty.get(source, f"{source} ({count})")


def rebuild_catalog_and_index(config_dir: Path, disabled_plugins: set[str] | None = None) -> tuple[list, bool, bool]:
    """Atomically rebuild vault_index.json and smart-skill-catalog/SKILL.md without moving any files."""
    skills_dir = config_dir / "skills"
    vault_dir = config_dir / "smart_vault"
    if disabled_plugins is None:
        disabled_plugins = get_disabled_plugins(config_dir)

    entries = build_vault_index(config_dir, disabled_plugins=disabled_plugins)
    active_entries = [e for e in entries if not e.get("disabled")]
    disabled_sources = sorted({e["source"] for e in entries if e.get("disabled")})

    index_json_path = vault_dir / "vault_index.json"
    index_payload = json.dumps(
        {
            "architect": AUTHOR_SIGNATURE,
            "version": VERSION,
            "mode": "option_a_opt_in",
            "total_vaulted_skills": len(entries),
            "active_vaulted_skills": len(active_entries),
            "disabled_plugins": disabled_sources,
            "skills": entries,
        },
        ensure_ascii=False,
        indent=2,
    ) + "\n"
    idx_changed = atomic_write_text(index_json_path, index_payload)

    catalog_skill_dir = skills_dir / "smart-skill-catalog"
    catalog_skill_dir.mkdir(parents=True, exist_ok=True)

    sources_summary: dict[str, list[str]] = {}
    for e in active_entries:
        sources_summary.setdefault(e["source"], []).append(e["name"])

    domain_labels = [
        format_domain_label(src, len(s_list))
        for src, s_list in sorted(sources_summary.items())
    ]
    dynamic_desc_domains = ", ".join(domain_labels) if domain_labels else "local vaulted skills"

    cli_script_path = Path(__file__).resolve()
    catalog_md = f"""---
name: smart-skill-catalog
description: >-
  Master On-Demand Skill Router and Vault Index (by Elgasem) for {dynamic_desc_domains}.
  Activate whenever a task touches these domains.
---

# Smart Skill Catalog & On-Demand Vault (`الفهرس الذكي للمهارات`)
> **Architected by:** {AUTHOR_SIGNATURE} | **Active Vaulted Skills:** `{len(active_entries)}` | **Active MCP & Subagents:** `100%` | **Policy:** `Opt-In + Auto-Prune (Google Core Protected)`

## Fast On-Demand CLI Commands (Preferred — Zero Context Waste)
1. **Search for any skill by keyword or domain (<20ms):**
   ```bash
   python "{cli_script_path}" --search "<keyword>"
   ```
2. **Direct ephemeral read in the same turn (Preferred — zero git pollution):**
   ```bash
   python "{cli_script_path}" --read "<skill-name>"
   ```
3. **Scope a skill or plugin pack into a project's `.agents/skills/` (only when requested):**
   ```bash
   python "{cli_script_path}" --use "<skill-or-plugin-name>" --project "<WorkspaceRoot>"
   ```
4. **Sync updates, local skills & auto-prune uninstalled plugins:**
   ```bash
   python "{cli_script_path}" --sync
   ```
5. **Opt a newly installed non-Google plugin into the vault (explicit only):**
   ```bash
   python "{cli_script_path}" --vault-plugin "<plugin-name>"
   ```
6. **Permanently remove a skill from active folders & Smart Vault:**
   ```bash
   python "{cli_script_path}" --remove "<skill-name>"
   ```

---

## Isolated Domains in `smart_vault` (`{vault_dir}`)
"""
    for src_name, s_list in sorted(sources_summary.items()):
        preview = ", ".join(f"`{x}`" for x in s_list[:8])
        more = f" (+{len(s_list) - 8} more)" if len(s_list) > 8 else ""
        catalog_md += f"- **`{src_name}` ({len(s_list)} skills):** {preview}{more}\n"

    cat_changed = atomic_write_text(catalog_skill_dir / "SKILL.md", catalog_md)
    return entries, idx_changed, cat_changed


def cmd_sync(config_dir: Path, quiet: bool = False):
    skills_dir = config_dir / "skills"
    plugins_dir = config_dir / "plugins"
    vault_dir = config_dir / "smart_vault"
    p_vault_root = vault_dir / "plugins"

    (vault_dir / "standalone").mkdir(parents=True, exist_ok=True)
    (vault_dir / "firecrawl").mkdir(parents=True, exist_ok=True)
    p_vault_root.mkdir(parents=True, exist_ok=True)

    policy = load_policy(config_dir)
    opted_set = set(policy["opted_in_plugins"])

    moved_local = 0
    updated_plugins: list[str] = []
    pruned_plugins: list[str] = []

    # 1. Auto-prune uninstalled or empty plugin folders from smart_vault/plugins/
    if p_vault_root.exists():
        for vp_dir in sorted(p_vault_root.iterdir()):
            if not vp_dir.is_dir() or vp_dir.name.startswith("."):
                continue
            pname = vp_dir.name
            active_p_dir = plugins_dir / pname
            has_skills = any(vp_dir.rglob("SKILL.md"))
            if pname in PROTECTED_PLUGINS or not active_p_dir.is_dir() or not has_skills:
                shutil.rmtree(vp_dir)
                opted_set.discard(pname)
                pruned_plugins.append(pname)

    for pname in list(opted_set):
        if not (plugins_dir / pname).is_dir():
            opted_set.discard(pname)
            if pname not in pruned_plugins:
                pruned_plugins.append(pname)

    # 2. Local standalone skills (~/.gemini/config/skills/) -> auto-vault non-protected skills
    if skills_dir.exists():
        for item in sorted(skills_dir.iterdir()):
            if not item.is_dir() or item.name in PROTECTED_GLOBAL_SKILLS:
                continue
            if not any(item.rglob("SKILL.md")):
                continue
            target_group = "firecrawl" if item.name.startswith("firecrawl-") else "standalone"
            dst = vault_dir / target_group / item.name
            if dst.exists():
                shutil.rmtree(dst)
            shutil.move(str(item), str(dst))
            moved_local += 1

    # 3. Sync upstream updates ONLY for explicitly opted-in non-Google plugins
    # (Brand-new cloud plugins are NEVER touched automatically!)
    for pname in sorted(opted_set):
        if pname in PROTECTED_PLUGINS:
            continue
        active_p_dir = plugins_dir / pname
        if not active_p_dir.is_dir():
            continue
        p_vault_dir = p_vault_root / pname
        moved = sync_single_opted_in_plugin(active_p_dir, p_vault_dir)
        if moved > 0:
            updated_plugins.append(f"{pname} ({moved})")

    policy["opted_in_plugins"] = sorted(opted_set)
    save_policy(config_dir, policy)

    # 4 & 5. Rebuild JSON index and dynamic smart-skill-catalog atomically
    disabled_plugins = get_disabled_plugins(config_dir)
    entries, idx_changed, cat_changed = rebuild_catalog_and_index(config_dir, disabled_plugins=disabled_plugins)
    disabled_vaulted = sorted({e["source"] for e in entries if e.get("disabled")})

    any_change = bool(moved_local or updated_plugins or pruned_plugins or idx_changed or cat_changed)
    summary_msg = (
        f"sync ok | vaulted={len(entries)} | local_moved={moved_local} | "
        f"plugins_updated={updated_plugins or 'none'} | pruned={pruned_plugins or 'none'} | "
        f"disabled_hidden={disabled_vaulted or 'none'}"
    )
    if any_change:
        append_sync_log(vault_dir, summary_msg)

    if not quiet or any_change:
        print(f"[Smart Vault v{VERSION}] {summary_msg}")


def cmd_vault_plugin(config_dir: Path, plugin_name: str):
    """Explicitly opt a non-Google plugin into smart_vault."""
    pname = plugin_name.strip()
    if pname in PROTECTED_PLUGINS:
        print(f"[Smart Vault] REFUSED: '{pname}' is a protected Google/core plugin and must never be modified.")
        sys.exit(1)
    plugin_dir = config_dir / "plugins" / pname
    if not plugin_dir.is_dir():
        print(f"[Smart Vault] Plugin '{pname}' not found in {config_dir / 'plugins'}.")
        sys.exit(1)

    policy = load_policy(config_dir)
    if pname not in policy["opted_in_plugins"]:
        policy["opted_in_plugins"].append(pname)
        save_policy(config_dir, policy)

    cmd_sync(config_dir, quiet=False)


def cmd_vault_all_plugins(config_dir: Path):
    """Explicitly opt all currently installed non-Google plugins (that contain skills) into smart_vault."""
    plugins_dir = config_dir / "plugins"
    policy = load_policy(config_dir)
    opted = set(policy["opted_in_plugins"])
    added = []
    if plugins_dir.is_dir():
        for p_dir in sorted(plugins_dir.iterdir()):
            if not p_dir.is_dir() or p_dir.name in PROTECTED_PLUGINS:
                continue
            if collect_plugin_incoming_skills(p_dir):
                if p_dir.name not in opted:
                    opted.add(p_dir.name)
                    added.append(p_dir.name)
    policy["opted_in_plugins"] = sorted(opted)
    save_policy(config_dir, policy)
    print(f"[Smart Vault v{VERSION}] Explicitly opted in {len(added)} non-Google plugin(s): {added or 'none'}")
    cmd_sync(config_dir, quiet=False)


def cmd_unvault_plugin(config_dir: Path, plugin_name: str):
    """Restore a single plugin's skills back to plugins/<name>/skills/ and remove from opt-in list."""
    pname = plugin_name.strip()
    vault_p_dir = config_dir / "smart_vault" / "plugins" / pname
    target_skills_dir = config_dir / "plugins" / pname / "skills"

    if not vault_p_dir.is_dir():
        print(f"[Smart Vault] Plugin '{pname}' is not currently in smart_vault.")
        sys.exit(1)
    if not (config_dir / "plugins" / pname).is_dir():
        print(f"[Smart Vault] Plugin '{pname}' is not installed in plugins/. Use --sync to prune it.")
        sys.exit(1)

    target_skills_dir.mkdir(parents=True, exist_ok=True)
    restored = 0
    for item in sorted(vault_p_dir.iterdir()):
        if item.is_dir():
            dst = target_skills_dir / item.name
            if dst.exists():
                shutil.rmtree(dst)
            shutil.move(str(item), str(dst))
            restored += 1
    shutil.rmtree(vault_p_dir, ignore_errors=True)

    policy = load_policy(config_dir)
    policy["opted_in_plugins"] = [p for p in policy["opted_in_plugins"] if p != pname]
    save_policy(config_dir, policy)
    cmd_sync(config_dir, quiet=False)
    print(f"[Smart Vault] Restored {restored} skill folder(s) for '{pname}' back to native plugin discovery.")


def cmd_search(config_dir: Path, query: str):
    index_path = config_dir / "smart_vault" / "vault_index.json"
    if not index_path.exists():
        cmd_sync(config_dir)
    data = json.loads(index_path.read_text(encoding="utf-8"))
    terms = [t.lower() for t in query.split() if t.strip()]

    scored = []
    for item in data.get("skills", []):
        hay_name = f"{item['name']} {item['source']}".lower()
        hay_desc = item["description"].lower()
        score = 0
        for t in terms:
            if t in hay_name:
                score += 10
            if t in hay_desc:
                score += 3
        if score > 0:
            scored.append((score, item))

    scored.sort(key=lambda x: (-x[0], x[1]["name"]))
    print(f"Found {len(scored)} matching skills in Smart Vault for '{query}':")
    for score, item in scored[:15]:
        tag = " [DISABLED]" if item.get("disabled") else ""
        print(f"  - [{item['source']}]{tag} {item['name']}")
        print(f"    Path: {item['path']}")
        if item["description"]:
            print(f"    Info: {item['description'][:140]}...")


def cmd_read(config_dir: Path, target: str):
    """Direct ephemeral read of a vaulted skill's SKILL.md (same-turn, zero git pollution)."""
    index_path = config_dir / "smart_vault" / "vault_index.json"
    if not index_path.exists():
        cmd_sync(config_dir)
    data = json.loads(index_path.read_text(encoding="utf-8"))
    target_low = target.lower()
    matches = [
        s for s in data.get("skills", [])
        if s["name"].lower() == target_low or s["skill_id"].lower() == target_low
    ]
    if not matches:
        matches = [s for s in data.get("skills", []) if target_low in s["name"].lower()]
    if not matches:
        print(f"[Smart Vault] No skill matching '{target}' found. Try --search <keyword>.")
        sys.exit(1)
    m = matches[0]
    md_path = Path(m["path"])
    status_note = " | Status: DISABLED in config.json" if m.get("disabled") else ""
    print(f"# [Direct Read] Skill: {m['name']} | Source: {m['source']}{status_note} | Folder: {m['dir']}\n")
    print(md_path.read_text(encoding="utf-8", errors="ignore"))


def cmd_remove(config_dir: Path, target: str):
    """Permanently delete a skill from BOTH active locations AND smart_vault, then rebuild the index."""
    target_low = target.lower().strip()
    removed_paths = []

    skills_dir = config_dir / "skills"
    if skills_dir.exists():
        for item in list(skills_dir.iterdir()):
            if item.is_dir() and item.name.lower() == target_low and item.name != "smart-skill-catalog":
                shutil.rmtree(item)
                removed_paths.append(str(item))

    vault_dir = config_dir / "smart_vault"
    if vault_dir.exists():
        for md_file in list(vault_dir.rglob("SKILL.md")):
            sdir = md_file.parent
            fm = extract_frontmatter(md_file)
            if sdir.name.lower() == target_low or fm["name"].lower() == target_low:
                if sdir.exists():
                    shutil.rmtree(sdir)
                    removed_paths.append(str(sdir))

    if not removed_paths:
        print(f"[Smart Vault] No skill named '{target}' found in active skills or smart_vault.")
        sys.exit(1)

    cmd_sync(config_dir)
    print(f"[Smart Vault] Permanently removed '{target}' from {len(removed_paths)} location(s) and updated catalog:")
    for rp in removed_paths:
        print(f"  - Deleted: {rp}")


def cmd_use(config_dir: Path, target: str, project_root: Path):
    index_path = config_dir / "smart_vault" / "vault_index.json"
    if not index_path.exists():
        cmd_sync(config_dir)
    data = json.loads(index_path.read_text(encoding="utf-8"))

    target_low = target.lower()
    matches = [
        s for s in data.get("skills", [])
        if s["name"].lower() == target_low
        or s["skill_id"].lower() == target_low
        or s["source"].lower() == target_low
    ]
    if not matches:
        matches = [s for s in data.get("skills", []) if target_low in s["name"].lower()]

    if not matches:
        print(f"[Smart Vault] No skill matching '{target}' found. Try --search <keyword>.")
        sys.exit(1)

    dest_root = project_root.resolve() / ".agents" / "skills"
    dest_root.mkdir(parents=True, exist_ok=True)

    installed = []
    for m in matches:
        src_dir = Path(m["dir"])
        dst_dir = dest_root / src_dir.name
        if src_dir.exists():
            if dst_dir.exists():
                shutil.rmtree(dst_dir)
            shutil.copytree(src_dir, dst_dir)
            installed.append((m["name"], str(dst_dir / "SKILL.md")))

    print(f"[Smart Vault] Scoped {len(installed)} skill(s) into project '{dest_root}':")
    for name, md_path in installed:
        print(f"  + {name} -> {md_path}")


def cmd_status(config_dir: Path):
    skills_dir = config_dir / "skills"
    plugins_dir = config_dir / "plugins"
    active_skills = []
    for p in glob.glob(str(skills_dir / "*" / "SKILL.md")):
        fm = extract_frontmatter(Path(p))
        active_skills.append((Path(p).parent.name, max(1, int(fm["raw_len"] / 3.5))))
    for p in glob.glob(str(plugins_dir / "*" / "skills" / "**" / "SKILL.md"), recursive=True):
        fm = extract_frontmatter(Path(p))
        active_skills.append((Path(p).parent.name, max(1, int(fm["raw_len"] / 3.5))))

    vault_entries = build_vault_index(config_dir)
    disabled_vaulted = sorted({e["source"] for e in vault_entries if e.get("disabled")})
    policy = load_policy(config_dir)
    active_tokens = sum(x[1] for x in active_skills)
    vaulted_tokens = sum(x["tokens_est"] for x in vault_entries)
    total_if_unvaulted = active_tokens + vaulted_tokens
    pct_saved = (vaulted_tokens / total_if_unvaulted * 100) if total_if_unvaulted else 0

    print("=" * 70)
    print(f" Antigravity Smart Skill Vault v{VERSION} | By {AUTHOR_SIGNATURE}")
    print("=" * 70)
    print(f" Active Global Skills  : {len(active_skills):3d} skills (~{active_tokens:,} tokens)")
    print(f" Vaulted On-Demand     : {len(vault_entries):3d} skills (~{vaulted_tokens:,} tokens saved per turn)")
    print(f" Skill Token Reduction : {pct_saved:.1f}% reduction")
    print(f" Opted-In Plugins ({len(policy['opted_in_plugins']):2d}) : {', '.join(policy['opted_in_plugins']) or 'none'}")
    print(f" Disabled (Hidden)     : {', '.join(disabled_vaulted) or 'none'}")
    print(f" Protected Google Core : {len(PROTECTED_PLUGINS)} plugins (untouched)")
    print("=" * 70)


def cmd_restore(config_dir: Path):
    vault_dir = config_dir / "smart_vault"
    skills_dir = config_dir / "skills"
    plugins_dir = config_dir / "plugins"
    restored = 0

    for grp in ("firecrawl", "standalone"):
        g_dir = vault_dir / grp
        if g_dir.exists():
            for item in sorted(g_dir.iterdir()):
                if item.is_dir():
                    dst = skills_dir / item.name
                    if dst.exists():
                        shutil.rmtree(dst)
                    shutil.move(str(item), str(dst))
                    restored += 1

    p_vault_root = vault_dir / "plugins"
    if p_vault_root.exists():
        for p_dir in sorted(p_vault_root.iterdir()):
            if not p_dir.is_dir() or not (plugins_dir / p_dir.name).is_dir():
                continue
            target_plugin_skills = plugins_dir / p_dir.name / "skills"
            target_plugin_skills.mkdir(parents=True, exist_ok=True)
            for item in sorted(p_dir.iterdir()):
                if item.is_dir():
                    dst = target_plugin_skills / item.name
                    if dst.exists():
                        shutil.rmtree(dst)
                    shutil.move(str(item), str(dst))
                    restored += 1
            shutil.rmtree(p_dir, ignore_errors=True)

    # Clear opted_in_plugins so scheduled auto-sync will NOT re-vault restored plugins
    policy = load_policy(config_dir)
    policy["opted_in_plugins"] = []
    save_policy(config_dir, policy)

    rebuild_catalog_and_index(config_dir)
    append_sync_log(vault_dir, f"restore ok | restored={restored} | opted_in_plugins cleared")
    print(f"[Smart Vault v{VERSION}] Restored {restored} skill folder(s) and cleared opted_in_plugins.")
    print("Note: If you set up a scheduled auto-sync task (e.g. Task Scheduler / cron), disable it to keep standalone skills unvaulted.")


def main():
    parser = argparse.ArgumentParser(
        description=f"Antigravity Smart Skill Vault v{VERSION} (by {AUTHOR_SIGNATURE})"
    )
    parser.add_argument("--config-dir", default=str(DEFAULT_CONFIG_DIR), help="Path to ~/.gemini/config")
    parser.add_argument("--sync", action="store_true", help="Sync local skills, opted-in plugin updates & auto-prune ghosts")
    parser.add_argument("--quiet", action="store_true", help="Only print output when changes occur (for scheduled sync)")
    parser.add_argument("--vault-plugin", metavar="PLUGIN", help="Explicitly opt a non-Google plugin into Smart Vault")
    parser.add_argument("--vault-all-plugins", action="store_true", help="Explicitly opt all installed non-Google plugins into Smart Vault")
    parser.add_argument("--unvault-plugin", metavar="PLUGIN", help="Restore a single plugin's skills back to native discovery")
    parser.add_argument("--search", metavar="QUERY", help="Fast keyword search across all vaulted skills")
    parser.add_argument("--read", metavar="SKILL", help="Direct read a vaulted skill's SKILL.md without copying to project")
    parser.add_argument("--remove", metavar="SKILL", help="Permanently delete a skill from disk & Smart Vault index")
    parser.add_argument("--use", metavar="SKILL_OR_PLUGIN", help="Copy skill(s) from vault into project .agents/skills/")
    parser.add_argument("--project", default=".", help="Target project root for --use (default: current directory)")
    parser.add_argument("--status", action="store_true", help="Display live token savings and vault status")
    parser.add_argument("--restore", action="store_true", help="Restore all vaulted skills back to global directories")
    args = parser.parse_args()

    cfg_dir = Path(args.config_dir)
    if args.sync:
        cmd_sync(cfg_dir, quiet=args.quiet)
    elif args.vault_plugin:
        cmd_vault_plugin(cfg_dir, args.vault_plugin)
    elif args.vault_all_plugins:
        cmd_vault_all_plugins(cfg_dir)
    elif args.unvault_plugin:
        cmd_unvault_plugin(cfg_dir, args.unvault_plugin)
    elif args.search:
        cmd_search(cfg_dir, args.search)
    elif args.read:
        cmd_read(cfg_dir, args.read)
    elif args.remove:
        cmd_remove(cfg_dir, args.remove)
    elif args.use:
        cmd_use(cfg_dir, args.use, Path(args.project))
    elif args.restore:
        cmd_restore(cfg_dir)
    else:
        cmd_status(cfg_dir)


if __name__ == "__main__":
    main()
