;-------------------------------------------------------------------------------
; PokePoke Windows Installer (NSIS)
; 
; Packages the PyInstaller output into a proper Windows install experience.
; Features:
;   - Start Menu shortcuts
;   - Optional Desktop shortcut
;   - Install location selection
;   - Uninstaller with registry cleanup
;   - WebView2 bootstrapper for systems without it
;-------------------------------------------------------------------------------

!include "MUI2.nsh"
!include "FileFunc.nsh"
!include "LogicLib.nsh"

;-------------------------------------------------------------------------------
; Product Information
;-------------------------------------------------------------------------------
!define PRODUCT_NAME "PokePoke"
!define PRODUCT_VERSION "0.1.0"
!define PRODUCT_PUBLISHER "Amelia Payne"
!define PRODUCT_DESCRIPTION "Autonomous Beads + Copilot CLI Orchestrator"
!define PRODUCT_WEB_SITE "https://github.com/AmeliaRose802/PokePoke"
!define PRODUCT_UNINST_KEY "Software\Microsoft\Windows\CurrentVersion\Uninstall\${PRODUCT_NAME}"
!define PRODUCT_UNINST_ROOT_KEY "HKLM"

; Paths relative to this .nsi file location (packaging/installer/)
!define PRODUCT_ICON "..\..\desktop\public\pokepoke.ico"
!define DIST_DIR "..\..\dist\PokePoke"
!define WEBVIEW2_BOOTSTRAPPER "MicrosoftEdgeWebview2Setup.exe"

;-------------------------------------------------------------------------------
; General Installer Settings
;-------------------------------------------------------------------------------
Name "${PRODUCT_NAME} ${PRODUCT_VERSION}"
OutFile "..\..\dist\PokePokeInstaller-${PRODUCT_VERSION}.exe"
InstallDir "$PROGRAMFILES\${PRODUCT_NAME}"
InstallDirRegKey ${PRODUCT_UNINST_ROOT_KEY} "${PRODUCT_UNINST_KEY}" "InstallLocation"
ShowInstDetails show
ShowUnInstDetails show
RequestExecutionLevel admin

;-------------------------------------------------------------------------------
; Version Information
;-------------------------------------------------------------------------------
VIProductVersion "0.1.0.0"
VIAddVersionKey /LANG=1033 "ProductName" "${PRODUCT_NAME}"
VIAddVersionKey /LANG=1033 "CompanyName" "${PRODUCT_PUBLISHER}"
VIAddVersionKey /LANG=1033 "FileDescription" "${PRODUCT_DESCRIPTION} Installer"
VIAddVersionKey /LANG=1033 "FileVersion" "${PRODUCT_VERSION}"
VIAddVersionKey /LANG=1033 "ProductVersion" "${PRODUCT_VERSION}"
VIAddVersionKey /LANG=1033 "LegalCopyright" "Copyright (c) 2026 ${PRODUCT_PUBLISHER}"

;-------------------------------------------------------------------------------
; Modern UI Settings
;-------------------------------------------------------------------------------
!define MUI_ABORTWARNING
!define MUI_ICON "${PRODUCT_ICON}"
!define MUI_UNICON "${PRODUCT_ICON}"

; Welcome page
!define MUI_WELCOMEPAGE_TITLE "Welcome to ${PRODUCT_NAME} Setup"
!define MUI_WELCOMEPAGE_TEXT "This wizard will guide you through the installation of ${PRODUCT_NAME}.$\r$\n$\r$\n${PRODUCT_DESCRIPTION}$\r$\n$\r$\nClick Next to continue."

; Finish page
!define MUI_FINISHPAGE_RUN "$INSTDIR\PokePoke.exe"
!define MUI_FINISHPAGE_RUN_TEXT "Launch ${PRODUCT_NAME}"
!define MUI_FINISHPAGE_SHOWREADME ""
!define MUI_FINISHPAGE_SHOWREADME_NOTCHECKED

;-------------------------------------------------------------------------------
; Installer Pages
;-------------------------------------------------------------------------------
!insertmacro MUI_PAGE_WELCOME
!insertmacro MUI_PAGE_LICENSE "..\..\LICENSE"
!insertmacro MUI_PAGE_DIRECTORY
!insertmacro MUI_PAGE_COMPONENTS
!insertmacro MUI_PAGE_INSTFILES
!insertmacro MUI_PAGE_FINISH

;-------------------------------------------------------------------------------
; Uninstaller Pages
;-------------------------------------------------------------------------------
!insertmacro MUI_UNPAGE_CONFIRM
!insertmacro MUI_UNPAGE_INSTFILES

;-------------------------------------------------------------------------------
; Languages
;-------------------------------------------------------------------------------
!insertmacro MUI_LANGUAGE "English"

;-------------------------------------------------------------------------------
; Variables
;-------------------------------------------------------------------------------
Var StartMenuGroup

;-------------------------------------------------------------------------------
; Installer Sections
;-------------------------------------------------------------------------------

Section "!${PRODUCT_NAME} Core Files" SEC_CORE
    SectionIn RO  ; Required section, cannot be deselected
    
    SetOutPath "$INSTDIR"
    SetOverwrite on
    
    ; Copy all files from PyInstaller dist directory
    File /r "${DIST_DIR}\*.*"
    
    ; Store installation folder in registry for uninstaller
    WriteRegStr ${PRODUCT_UNINST_ROOT_KEY} "${PRODUCT_UNINST_KEY}" "InstallLocation" "$INSTDIR"
    
    ; Create uninstaller
    WriteUninstaller "$INSTDIR\Uninstall.exe"
    
    ; Write Add/Remove Programs registry entries
    WriteRegStr ${PRODUCT_UNINST_ROOT_KEY} "${PRODUCT_UNINST_KEY}" "DisplayName" "${PRODUCT_NAME}"
    WriteRegStr ${PRODUCT_UNINST_ROOT_KEY} "${PRODUCT_UNINST_KEY}" "DisplayVersion" "${PRODUCT_VERSION}"
    WriteRegStr ${PRODUCT_UNINST_ROOT_KEY} "${PRODUCT_UNINST_KEY}" "Publisher" "${PRODUCT_PUBLISHER}"
    WriteRegStr ${PRODUCT_UNINST_ROOT_KEY} "${PRODUCT_UNINST_KEY}" "URLInfoAbout" "${PRODUCT_WEB_SITE}"
    WriteRegStr ${PRODUCT_UNINST_ROOT_KEY} "${PRODUCT_UNINST_KEY}" "DisplayIcon" "$INSTDIR\PokePoke.exe"
    WriteRegStr ${PRODUCT_UNINST_ROOT_KEY} "${PRODUCT_UNINST_KEY}" "UninstallString" "$INSTDIR\Uninstall.exe"
    WriteRegStr ${PRODUCT_UNINST_ROOT_KEY} "${PRODUCT_UNINST_KEY}" "QuietUninstallString" '"$INSTDIR\Uninstall.exe" /S'
    WriteRegDWORD ${PRODUCT_UNINST_ROOT_KEY} "${PRODUCT_UNINST_KEY}" "NoModify" 1
    WriteRegDWORD ${PRODUCT_UNINST_ROOT_KEY} "${PRODUCT_UNINST_KEY}" "NoRepair" 1
    
    ; Calculate and write estimated size
    ${GetSize} "$INSTDIR" "/S=0K" $0 $1 $2
    IntFmt $0 "0x%08X" $0
    WriteRegDWORD ${PRODUCT_UNINST_ROOT_KEY} "${PRODUCT_UNINST_KEY}" "EstimatedSize" "$0"
SectionEnd

Section "Start Menu Shortcuts" SEC_STARTMENU
    StrCpy $StartMenuGroup "${PRODUCT_NAME}"
    
    SetShellVarContext all
    CreateDirectory "$SMPROGRAMS\$StartMenuGroup"
    CreateShortCut "$SMPROGRAMS\$StartMenuGroup\${PRODUCT_NAME}.lnk" "$INSTDIR\PokePoke.exe" "" "$INSTDIR\PokePoke.exe" 0
    CreateShortCut "$SMPROGRAMS\$StartMenuGroup\Uninstall ${PRODUCT_NAME}.lnk" "$INSTDIR\Uninstall.exe" "" "$INSTDIR\Uninstall.exe" 0
SectionEnd

Section /o "Desktop Shortcut" SEC_DESKTOP
    SetShellVarContext all
    CreateShortCut "$DESKTOP\${PRODUCT_NAME}.lnk" "$INSTDIR\PokePoke.exe" "" "$INSTDIR\PokePoke.exe" 0
SectionEnd

Section "WebView2 Runtime" SEC_WEBVIEW2
    ; Check if WebView2 is already installed
    SetRegView 64
    ReadRegStr $0 HKLM "SOFTWARE\WOW6432Node\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}" "pv"
    ${If} $0 == ""
        ReadRegStr $0 HKCU "Software\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}" "pv"
    ${EndIf}
    
    ${If} $0 == ""
        ; WebView2 not found, install it
        DetailPrint "Installing Microsoft Edge WebView2 Runtime..."
        SetOutPath "$TEMP"
        File "${WEBVIEW2_BOOTSTRAPPER}"
        ExecWait '"$TEMP\${WEBVIEW2_BOOTSTRAPPER}" /silent /install' $1
        Delete "$TEMP\${WEBVIEW2_BOOTSTRAPPER}"
        
        ${If} $1 != 0
            MessageBox MB_ICONEXCLAMATION|MB_OK "WebView2 installation may have failed. ${PRODUCT_NAME} requires WebView2 to run. You can download it from Microsoft's website."
        ${EndIf}
    ${Else}
        DetailPrint "WebView2 Runtime is already installed (version: $0)"
    ${EndIf}
SectionEnd

;-------------------------------------------------------------------------------
; Section Descriptions
;-------------------------------------------------------------------------------
!insertmacro MUI_FUNCTION_DESCRIPTION_BEGIN
    !insertmacro MUI_DESCRIPTION_TEXT ${SEC_CORE} "Core application files required to run ${PRODUCT_NAME}."
    !insertmacro MUI_DESCRIPTION_TEXT ${SEC_STARTMENU} "Create shortcuts in the Start Menu."
    !insertmacro MUI_DESCRIPTION_TEXT ${SEC_DESKTOP} "Create a shortcut on the Desktop."
    !insertmacro MUI_DESCRIPTION_TEXT ${SEC_WEBVIEW2} "Install Microsoft Edge WebView2 Runtime if not present. Required for the application UI."
!insertmacro MUI_FUNCTION_DESCRIPTION_END

;-------------------------------------------------------------------------------
; Uninstaller Section
;-------------------------------------------------------------------------------
Section "Uninstall"
    ; Remove Start Menu shortcuts
    SetShellVarContext all
    RMDir /r "$SMPROGRAMS\${PRODUCT_NAME}"
    
    ; Remove Desktop shortcut
    Delete "$DESKTOP\${PRODUCT_NAME}.lnk"
    
    ; Remove installation directory and all contents
    RMDir /r "$INSTDIR"
    
    ; Remove registry entries
    DeleteRegKey ${PRODUCT_UNINST_ROOT_KEY} "${PRODUCT_UNINST_KEY}"
    
    ; Clean up any user data in AppData (optional - ask user first)
    MessageBox MB_YESNO|MB_ICONQUESTION "Do you want to remove your ${PRODUCT_NAME} configuration and data?$\r$\n$\r$\nThis will delete settings in %APPDATA%\${PRODUCT_NAME}" IDNO +2
    RMDir /r "$APPDATA\${PRODUCT_NAME}"
SectionEnd

;-------------------------------------------------------------------------------
; Installer Functions
;-------------------------------------------------------------------------------
Function .onInit
    ; Check for existing installation
    ReadRegStr $0 ${PRODUCT_UNINST_ROOT_KEY} "${PRODUCT_UNINST_KEY}" "InstallLocation"
    ${If} $0 != ""
        MessageBox MB_YESNO|MB_ICONQUESTION "${PRODUCT_NAME} is already installed in:$\r$\n$0$\r$\n$\r$\nDo you want to uninstall the previous version first?" IDNO continue_install
        ExecWait '"$0\Uninstall.exe" /S _?=$0'
        continue_install:
    ${EndIf}
FunctionEnd

Function .onInstSuccess
    ; Installation completed successfully
FunctionEnd

;-------------------------------------------------------------------------------
; Uninstaller Functions
;-------------------------------------------------------------------------------
Function un.onInit
    MessageBox MB_YESNO|MB_ICONQUESTION "Are you sure you want to completely remove ${PRODUCT_NAME} and all of its components?" IDYES +2
    Abort
FunctionEnd

Function un.onUninstSuccess
    MessageBox MB_ICONINFORMATION|MB_OK "${PRODUCT_NAME} was successfully removed from your computer."
FunctionEnd
