# Contributing to Antigravity Smart Skill Vault 🤝

Welcome! **The door is completely open** for developers, AI engineers, and community members who want to improve this architecture, build new features, or adapt it to more agent ecosystems.

## Ways to Contribute
- **Semantic / Embedding Search:** Upgrade `--search` with optional BM25 or local embeddings while keeping zero-dependency fallback.
- **Tech-Stack Auto-Detection:** Add an `--auto-scope --project .` mode that detects `next.config.ts`, `pubspec.yaml`, `sf.jsonc`, `firebase.json`, etc., and automatically scopes matching skills into `.agents/skills/`.
- **Cross-Harness Support:** Extend support to **Gemini CLI**, **Claude Code**, **Cursor**, and **Windsurf**.
- **Bug Reports & Ideas:** Open an Issue on GitHub with your IDE version, OS, and token budget breakdown.

## Pull Request Guidelines
1. Fork the repository and create a descriptive feature branch (`git checkout -b feat/your-improvement`).
2. Keep the core `smart_vault.py` script dependency-free (Python 3.8+ standard library) so any user can run it out of the box.
3. Retain the [`NOTICE`](./NOTICE) and [`LICENSE`](./LICENSE) attribution notices in all derivative works per Apache License 2.0.
4. Open a Pull Request describing the problem solved and before/after token measurements.

---

## المساهمة في تطوير المشروع (بالعربية)
الباب مفتوح بالكامل لكل مطور ومهندس ذكاء اصطناعي يرغب في تطوير هذه الفكرة أو المشاركة في تحسينها:
1. اعمل **Fork** للمستودع وأنشئ فرعاً جديداً (`Branch`) للميزة أو التحسين الذي تقترحه.
2. افتح **Pull Request** أو **Issue** مع شرح واضح لفكرتك وأثرها في توفير التوكنات أو تحسين تجربة المستخدم.
3. يُرجى الحفاظ على ملفّي الإشعار والرخصة (`NOTICE` و`LICENSE`) وفق رخصة Apache 2.0.
