# Skills trong repo

Chỉ commit thư mục skill THẬT (có `SKILL.md` bên trong, vd
`tom-tat-luot-chat/`).

KHÔNG commit symlink tới kho skill trên máy cá nhân
(`~/.agents/skills`, `~/.openclaw/skills`, `~/.hermes/skills`):
`SkillCatalog.load()` đã tự quét 3 kho đó trên máy đang chạy, và
symlink tuyệt đối (vd `/Users/<user>/.agents/skills/...`) sang máy
khác là gãy toàn bộ. (Dọn 2026-10-26: 93 symlink kiểu này đã bị gỡ
khỏi repo sau audit hardcode.)
