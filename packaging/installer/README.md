# PokePoke Windows Installer

This directory contains the NSIS installer script for PokePoke.

## Prerequisites

1. **NSIS (Nullsoft Scriptable Install System)**
   - Download from: https://nsis.sourceforge.io/
   - Add to PATH or install to default location

2. **PyInstaller Build**
   - The installer packages the PyInstaller output
   - Run PyInstaller first: `pyinstaller packaging/pyinstaller/pokepoke.spec`

3. **WebView2 Bootstrapper** (optional but recommended)
   - Download from: https://developer.microsoft.com/en-us/microsoft-edge/webview2/
   - Save as `MicrosoftEdgeWebview2Setup.exe` in this directory
   - The installer will silently install WebView2 for users who don't have it

## Building the Installer

### Using the Build Script (Recommended)

```powershell
.\build_installer.ps1
```

### Manual Build

```powershell
# From project root
pyinstaller packaging/pyinstaller/pokepoke.spec

# From this directory
makensis pokepoke.nsi
```

## Installer Features

- **Start Menu shortcuts**: Creates PokePoke folder with app and uninstall shortcuts
- **Desktop shortcut**: Optional, user can choose during installation
- **Install location selection**: Users can choose where to install
- **Registry entries**: Adds to Add/Remove Programs for easy uninstallation
- **WebView2 Runtime**: Checks for and installs WebView2 if missing
- **Upgrade handling**: Detects existing installation and offers to uninstall first

## Output

The installer is created at: `dist/PokePokeInstaller-{version}.exe`

## Files

- `pokepoke.nsi` - NSIS installer script
- `build_installer.ps1` - PowerShell build script
- `MicrosoftEdgeWebview2Setup.exe` - WebView2 bootstrapper (not in repo, download separately)

## Customization

Edit `pokepoke.nsi` to change:
- `PRODUCT_VERSION` - Version number
- `PRODUCT_PUBLISHER` - Publisher name
- `PRODUCT_WEB_SITE` - Website URL
- `PRODUCT_DESCRIPTION` - Application description
