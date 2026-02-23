; --------------------------------------------------------------------------
; PokePoke Windows Installer - NSIS Script
; --------------------------------------------------------------------------

!include "MUI2.nsh"
!include "FileFunc.nsh"

; Product information
!define PRODUCT_NAME "PokePoke"
!define PRODUCT_VERSION "0.1.0"
!define PRODUCT_PUBLISHER "Amelia Payne"
!define PRODUCT_DESCRIPTION "Autonomous Beads + Copilot CLI Orchestrator"
!define PRODUCT_ICON "..\..\desktop\public\pokepoke.ico"
!define PRODUCT_EXE "PokePoke.exe"
!define DIST_DIR "..\..\dist\PokePoke"

; Registry keys
!define PRODUCT_UNINST_KEY "Software\Microsoft\Windows\CurrentVersion\Uninstall\${PRODUCT_NAME}"
!define PRODUCT_DIR_REGKEY "Software\${PRODUCT_NAME}"

; Installer attributes
Name "${PRODUCT_NAME}"
OutFile "..\..\dist\PokePokeInstaller-${PRODUCT_VERSION}.exe"
InstallDir "$PROGRAMFILES\${PRODUCT_NAME}"
InstallDirRegKey HKLM "${PRODUCT_DIR_REGKEY}" "InstallDir"
RequestExecutionLevel admin

; Version information
VIProductVersion "0.1.0.0"
VIAddVersionKey /LANG=1033 "ProductName" "${PRODUCT_NAME}"
VIAddVersionKey /LANG=1033 "CompanyName" "${PRODUCT_PUBLISHER}"
VIAddVersionKey /LANG=1033 "FileDescription" "${PRODUCT_DESCRIPTION}"
VIAddVersionKey /LANG=1033 "FileVersion" "${PRODUCT_VERSION}"
VIAddVersionKey /LANG=1033 "ProductVersion" "${PRODUCT_VERSION}"

; --------------------------------------------------------------------------
; Modern UI configuration
; --------------------------------------------------------------------------

!define MUI_ABORTWARNING
!define MUI_ICON "${PRODUCT_ICON}"
!define MUI_UNICON "${PRODUCT_ICON}"

; Installer pages
!insertmacro MUI_PAGE_WELCOME
!insertmacro MUI_PAGE_DIRECTORY
!insertmacro MUI_PAGE_INSTFILES
!insertmacro MUI_PAGE_FINISH

; Uninstaller pages
!insertmacro MUI_UNPAGE_CONFIRM
!insertmacro MUI_UNPAGE_INSTFILES

; Language
!insertmacro MUI_LANGUAGE "English"

; --------------------------------------------------------------------------
; Upgrade / existing-install detection
; --------------------------------------------------------------------------

Function .onInit
    ReadRegStr $0 HKLM "${PRODUCT_UNINST_KEY}" "UninstallString"
    StrCmp $0 "" done

    MessageBox MB_OKCANCEL|MB_ICONINFORMATION \
        "${PRODUCT_NAME} is already installed.$\r$\n$\r$\nClick OK to remove the previous version before installing, or Cancel to abort." \
        IDOK uninst
    Abort

uninst:
    ExecWait '$0 /S _?=$INSTDIR'

done:
FunctionEnd

; --------------------------------------------------------------------------
; Main install section
; --------------------------------------------------------------------------

Section "Install" SEC01
    SetOutPath "$INSTDIR"
    SetOverwrite on

    ; Copy all PyInstaller output files
    File /r "${DIST_DIR}\*.*"

    ; Bundle WebView2 bootstrapper if available at build time
    File /nonfatal "MicrosoftEdgeWebview2Setup.exe"

    ; Create uninstaller
    WriteUninstaller "$INSTDIR\uninstall.exe"

    ; --- Start Menu shortcuts ---
    CreateDirectory "$SMPROGRAMS\${PRODUCT_NAME}"
    CreateShortCut "$SMPROGRAMS\${PRODUCT_NAME}\${PRODUCT_NAME}.lnk" \
        "$INSTDIR\${PRODUCT_EXE}" "" "$INSTDIR\${PRODUCT_EXE}" 0
    CreateShortCut "$SMPROGRAMS\${PRODUCT_NAME}\Uninstall ${PRODUCT_NAME}.lnk" \
        "$INSTDIR\uninstall.exe" "" "$INSTDIR\uninstall.exe" 0

    ; --- Desktop shortcut ---
    CreateShortCut "$DESKTOP\${PRODUCT_NAME}.lnk" \
        "$INSTDIR\${PRODUCT_EXE}" "" "$INSTDIR\${PRODUCT_EXE}" 0

    ; --- Add/Remove Programs registry entries ---
    WriteRegStr HKLM "${PRODUCT_UNINST_KEY}" "DisplayName" "${PRODUCT_NAME}"
    WriteRegStr HKLM "${PRODUCT_UNINST_KEY}" "UninstallString" '"$INSTDIR\uninstall.exe"'
    WriteRegStr HKLM "${PRODUCT_UNINST_KEY}" "QuietUninstallString" '"$INSTDIR\uninstall.exe" /S'
    WriteRegStr HKLM "${PRODUCT_UNINST_KEY}" "InstallLocation" "$INSTDIR"
    WriteRegStr HKLM "${PRODUCT_UNINST_KEY}" "DisplayIcon" "$INSTDIR\${PRODUCT_EXE}"
    WriteRegStr HKLM "${PRODUCT_UNINST_KEY}" "Publisher" "${PRODUCT_PUBLISHER}"
    WriteRegStr HKLM "${PRODUCT_UNINST_KEY}" "DisplayVersion" "${PRODUCT_VERSION}"
    WriteRegDWORD HKLM "${PRODUCT_UNINST_KEY}" "NoModify" 1
    WriteRegDWORD HKLM "${PRODUCT_UNINST_KEY}" "NoRepair" 1

    ; Write estimated size
    ${GetSize} "$INSTDIR" "/S=0K" $0 $1 $2
    IntFmt $0 "0x%08X" $0
    WriteRegDWORD HKLM "${PRODUCT_UNINST_KEY}" "EstimatedSize" $0

    ; Store install directory
    WriteRegStr HKLM "${PRODUCT_DIR_REGKEY}" "InstallDir" "$INSTDIR"
SectionEnd

; --------------------------------------------------------------------------
; WebView2 runtime detection and silent install
; --------------------------------------------------------------------------

Section "WebView2 Runtime" SEC02
    ; Check all known registry locations for WebView2
    ReadRegStr $0 HKLM \
        "SOFTWARE\WOW6432Node\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}" "pv"
    StrCmp $0 "" 0 webview2_found

    ReadRegStr $0 HKLM \
        "SOFTWARE\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}" "pv"
    StrCmp $0 "" 0 webview2_found

    ReadRegStr $0 HKCU \
        "SOFTWARE\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}" "pv"
    StrCmp $0 "" 0 webview2_found

    ; WebView2 not found — try to install from bundled bootstrapper
    IfFileExists "$INSTDIR\MicrosoftEdgeWebview2Setup.exe" 0 webview2_missing

    DetailPrint "Installing WebView2 Runtime..."
    ExecWait '"$INSTDIR\MicrosoftEdgeWebview2Setup.exe" /silent /install' $0
    DetailPrint "WebView2 installer exited with code: $0"
    Delete "$INSTDIR\MicrosoftEdgeWebview2Setup.exe"
    Goto webview2_done

webview2_missing:
    DetailPrint "WebView2 Runtime not found and bootstrapper not bundled."
    DetailPrint "Install manually: https://developer.microsoft.com/microsoft-edge/webview2/"
    Goto webview2_done

webview2_found:
    DetailPrint "WebView2 Runtime already installed (version: $0)"
    Delete "$INSTDIR\MicrosoftEdgeWebview2Setup.exe"

webview2_done:
SectionEnd

; --------------------------------------------------------------------------
; Uninstaller
; --------------------------------------------------------------------------

Section "Uninstall"
    ; Remove application files
    RMDir /r "$INSTDIR"

    ; Remove Start Menu shortcuts
    RMDir /r "$SMPROGRAMS\${PRODUCT_NAME}"

    ; Remove Desktop shortcut
    Delete "$DESKTOP\${PRODUCT_NAME}.lnk"

    ; Remove registry entries
    DeleteRegKey HKLM "${PRODUCT_UNINST_KEY}"
    DeleteRegKey HKLM "${PRODUCT_DIR_REGKEY}"
SectionEnd
