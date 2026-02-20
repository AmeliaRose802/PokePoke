# App icon and branding

**Status:** Implemented  
**Version:** 0.1.0  
**Scope:** Desktop packaging assets

## Overview

PokePoke desktop packaging uses a multi-size .ico file for the window, taskbar,
executable, and installer. The PyInstaller bundle also embeds standard Windows
version metadata for display in file properties.

## Purpose

Provide consistent branding across the packaged desktop app so users see the
correct icon and metadata in Windows UI surfaces.

## User-Facing Behavior

- The pywebview window uses the PokePoke icon for the title bar and taskbar.
- The packaged executable shows company, product, and version metadata.
- The installer uses the same icon and metadata for Add/Remove Programs.

## Assets and Configuration

- `desktop/public/pokepoke.ico` - Source icon (included in desktop build output).
- `src/pokepoke/static/pokepoke.ico` - Packaged static asset for runtime.
- `packaging/pyinstaller/pokepoke.spec` - PyInstaller spec referencing icon.
- `packaging/pyinstaller/version_info.txt` - Executable version metadata.
- `packaging/installer/pokepoke.nsi` - Installer icon and version keys.

## Implementation Details

- `DesktopUI` passes the icon path from the frontend dist directory to
  `webview.create_window`.
- PyInstaller uses the icon and version info file for the executable.
- The installer script sets the icon and version keys for Windows metadata.

## Testing

```bash
pytest --timeout=300
```

## Changelog

- **0.1.0** (2026-02-19) - Added desktop icon assets and branding metadata.

---

**Last Updated:** 2026-02-19
