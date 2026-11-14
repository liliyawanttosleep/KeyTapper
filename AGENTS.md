# AGENTS.md

Guidance for AI agents working on this repository. 给在本仓库工作的 AI agent 的说明。

## Read first / 先读这里

- Development log, current features, architecture, pitfalls and roadmap:
  [docs/DEVLOG.en.md](docs/DEVLOG.en.md) (English) · [docs/DEVLOG.zh-CN.md](docs/DEVLOG.zh-CN.md) (中文)
- User-facing documentation: [README.md](README.md)

## Essentials / 要点

- Windows only. Python 3.8+, tkinter, Pillow. All code is in `keytapper.py`.
- Run the app: `pythonw keytapper.py` (it asks for administrator rights; pass `--no-elevate` to skip).
- Verify a change: `python tests/selftest.py`. It sends real F13–F15 key events and briefly opens the window.
- The UI strings and the unit names stored in config files are Chinese. Do not translate the stored
  unit names (`毫秒`, `秒`, `分钟`, `小时`) without migrating existing config and preset files.
- Never commit `config.json` or `*.json` in the repository root: they are the user's personal data.
- After changing behaviour, update both development logs (sections 2, 3, 7, 8) and, if the UI
  changed, `docs/screenshot.png`.
