#!/usr/bin/env python3
"""
Antigravity Smart Skill Vault & Project-Scoped Router (agy-smart-vault)
Architected & Designed by: Elgasem (https://github.com/aljasm-oss)
License: Apache License 2.0 (Attribution Required - see NOTICE)

Solves the Antigravity IDE 'Customization token budget exceeded' (20,000-token limit)
by decoupling bulky plugin/standalone skills into an on-demand local vault while
keeping 100% of MCP servers, OAuth accounts, Subagents (browser, research), and
Google Workspace integrations active.
"""

import argparse
import glob
import json
import os
import re
import shutil
import sys
from pathlib import Path

AUTHOR_SIGNATURE = "Elgasem (https://github.com/aljasm-oss)"
VERSION = "1.0.0"

DEFAULT_CONFIG_DIR = Path.home() / ".gemini" / "config"

PROTECTED_GLOBAL_SKILLS = {
    "banner-design",
    "brand",
    "cinematic-ui",
    "design-system",
    "firecrawl",
    "presentation-design-prompts",
    "reverse-engineer-anything",
    "slides",
    "smart-skill-catalog",
    "ui-styling",
    "ui-ux-pro-max",
}

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


def build_vault_index(config_dir: Path) -> list:
    vault_dir = config_dir / "smart_vault"
    entries = []
    if not vault_dir.exists():
        return entries

    for md_file in sorted(vault_dir.rglob("SKILL.md")):
        rel = md_file.relative_to(vault_dir)
        parts = rel.parts
        category = parts[0] if len(parts) > 1 else "general"
        source = parts[1] if category == "plugins" and len(parts) > 2 else category
        fm = extract_frontmatter(md_file)
        entries.append({
            "name": md_file.parent.name,
            "skill_id": fm["name"],
            "category": category,
            "source": source,
            "description": fm["description"],
            "path": str(md_file),
            "dir": str(md_file.parent),
            "tokens_est": max(1, int(fm["raw_len"] / 3.5)),
        })
    return entries


def cmd_sync(config_dir: Path):
    skills_dir = config_dir / "skills"
    plugins_dir = config_dir / "plugins"
    vault_dir = config_dir / "smart_vault"

    (vault_dir / "standalone").mkdir(parents=True, exist_ok=True)
    (vault_dir / "firecrawl").mkdir(parents=True, exist_ok=True)
    (vault_dir / "plugins").mkdir(parents=True, exist_ok=True)

    moved_count = 0

    # 1. Standalone skills
    if skills_dir.exists():
        for item in sorted(skills_dir.iterdir()):
            if not item.is_dir() or item.name in PROTECTED_GLOBAL_SKILLS:
                continue
            target_group = "firecrawl" if item.name.startswith("firecrawl-") else "standalone"
            dst = vault_dir / target_group / item.name
            if dst.exists():
                shutil.rmtree(dst)
            shutil.move(str(item), str(dst))
            moved_count += 1

    # 2. Non-Google Plugin skills (preserving MCP, OAuth, Subagents, and Rules)
    if plugins_dir.exists():
        for p_dir in sorted(plugins_dir.iterdir()):
            if not p_dir.is_dir() or p_dir.name in PROTECTED_PLUGINS:
                continue
            p_vault_dir = vault_dir / "plugins" / p_dir.name
            p_vault_dir.mkdir(parents=True, exist_ok=True)

            # Standard ./skills subfolder
            p_skills_dir = p_dir / "skills"
            if p_skills_dir.exists():
                for item in sorted(p_skills_dir.iterdir()):
                    if item.is_dir():
                        dst = p_vault_dir / item.name
                        if dst.exists():
                            shutil.rmtree(dst)
                        shutil.move(str(item), str(dst))
                        moved_count += 1

            # Root-level *-skill folders (e.g., neo4j)
            for item in sorted(p_dir.iterdir()):
                if item.is_dir() and item.name.endswith("-skill") and (item / "SKILL.md").exists():
                    dst = p_vault_dir / item.name
                    if dst.exists():
                        shutil.rmtree(dst)
                    shutil.move(str(item), str(dst))
                    moved_count += 1

            pjson_path = p_dir / "plugin.json"
            if pjson_path.exists():
                try:
                    pjson = json.loads(pjson_path.read_text(encoding="utf-8"))
                    if pjson.get("skills") == ["."]:
                        p_skills_dir.mkdir(exist_ok=True)
                        pjson["skills"] = ["./skills"]
                        pjson_path.write_text(json.dumps(pjson, indent=2), encoding="utf-8")
                except Exception:
                    pass

    # 3. Save JSON index for ultra-fast <20ms CLI search
    entries = build_vault_index(config_dir)
    index_json_path = vault_dir / "vault_index.json"
    index_json_path.write_text(
        json.dumps(
            {
                "architect": AUTHOR_SIGNATURE,
                "version": VERSION,
                "total_vaulted_skills": len(entries),
                "skills": entries,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    # 4. Generate compact smart-skill-catalog/SKILL.md
    catalog_skill_dir = skills_dir / "smart-skill-catalog"
    catalog_skill_dir.mkdir(parents=True, exist_ok=True)

    sources_summary = {}
    for e in entries:
        sources_summary.setdefault(e["source"], []).append(e["name"])

    cli_script_path = vault_dir / "smart_vault_cli.py"
    catalog_md = f"""---
name: smart-skill-catalog
description: >-
  Master On-Demand Skill Router and Vault Index (by Elgasem) for Canva, Figma,
  Spacefast, Flutter/Dart, Firebase, Firecrawl (36 workflows), invideo, Notion, monday.com,
  EGM, Mobbin, Tavily, incident.io, and Neo4j (30 skills). Activate whenever a task touches these domains.
---

# Smart Skill Catalog & On-Demand Vault (`الفهرس الذكي للمهارات`)
> **Architected by:** {AUTHOR_SIGNATURE} | **Vaulted Skills:** `{len(entries)}` | **Active MCP & Subagents:** `100%`

## Fast On-Demand CLI Commands (Preferred — Zero Context Waste)
Instead of scanning hundreds of paths manually, run the Smart Vault CLI:

1. **Search for any skill by keyword or domain (<20ms):**
   ```powershell
   python "{cli_script_path}" --search "<keyword>"
   ```
2. **Install/Scope a skill or plugin pack into the current project's `.agents/skills/`:**
   ```powershell
   python "{cli_script_path}" --use "<skill-or-plugin-name>" --project "<WorkspaceRoot>"
   ```
3. **Sync newly installed Marketplace plugins into the vault:**
   ```powershell
   python "{cli_script_path}" --sync
   ```
4. **Check live token savings & vault status:**
   ```powershell
   python "{cli_script_path}" --status
   ```

---

## Domain Summary in `smart_vault` (`{vault_dir}`)
"""
    for src_name, s_list in sorted(sources_summary.items()):
        preview = ", ".join(f"`{x}`" for x in s_list[:8])
        more = f" (+{len(s_list) - 8} more)" if len(s_list) > 8 else ""
        catalog_md += f"- **`{src_name}` ({len(s_list)} skills):** {preview}{more}\n"

    (catalog_skill_dir / "SKILL.md").write_text(catalog_md, encoding="utf-8")
    print(f"[Smart Vault] Sync complete! Newly archived: {moved_count} | Total vaulted skills: {len(entries)}")


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
        print(f"  - [{item['source']}] {item['name']}")
        print(f"    Path: {item['path']}")
        if item["description"]:
            print(f"    Info: {item['description'][:140]}...")


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

    print(f"[Smart Vault] Scoped {len(installed)} skill(s) into project '{project_root.resolve()}\\.agents\\skills\\':")
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
    active_tokens = sum(x[1] for x in active_skills)
    vaulted_tokens = sum(x["tokens_est"] for x in vault_entries)
    total_if_unvaulted = active_tokens + vaulted_tokens
    pct_saved = (vaulted_tokens / total_if_unvaulted * 100) if total_if_unvaulted else 0

    print("=" * 68)
    print(f" Antigravity Smart Skill Vault v{VERSION} | By {AUTHOR_SIGNATURE}")
    print("=" * 68)
    print(f" Active Global Skills : {len(active_skills):3d} skills (~{active_tokens:,} tokens)")
    print(f" Vaulted On-Demand    : {len(vault_entries):3d} skills (~{vaulted_tokens:,} tokens saved per turn)")
    print(f" Skill Token Reduction: {pct_saved:.1f}% reduction")
    print("=" * 68)


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
            if not p_dir.is_dir():
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

    print(f"[Smart Vault] Restored {restored} skills back to global discovery.")


def main():
    parser = argparse.ArgumentParser(
        description=f"Antigravity Smart Skill Vault & Project Scoper (by {AUTHOR_SIGNATURE})"
    )
    parser.add_argument("--config-dir", default=str(DEFAULT_CONFIG_DIR), help="Path to ~/.gemini/config")
    parser.add_argument("--sync", action="store_true", help="Sync bulky skills to vault & rebuild index")
    parser.add_argument("--search", metavar="QUERY", help="Fast keyword search across all vaulted skills")
    parser.add_argument("--use", metavar="SKILL_OR_PLUGIN", help="Copy skill(s) from vault into project .agents/skills/")
    parser.add_argument("--project", default=".", help="Target project root for --use (default: current directory)")
    parser.add_argument("--status", action="store_true", help="Display live token savings and vault status")
    parser.add_argument("--restore", action="store_true", help="Restore all vaulted skills back to global directories")
    args = parser.parse_args()

    cfg_dir = Path(args.config_dir)
    if args.sync:
        cmd_sync(cfg_dir)
    elif args.search:
        cmd_search(cfg_dir, args.search)
    elif args.use:
        cmd_use(cfg_dir, args.use, Path(args.project))
    elif args.restore:
        cmd_restore(cfg_dir)
    else:
        cmd_status(cfg_dir)


if __name__ == "__main__":
    main()
