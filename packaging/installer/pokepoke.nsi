!define PRODUCT_NAME "PokePoke"
!define PRODUCT_VERSION "0.1.0"
!define PRODUCT_PUBLISHER "Amelia Payne"
!define PRODUCT_DESCRIPTION "Autonomous Beads + Copilot CLI Orchestrator"
!define PRODUCT_ICON "..\..\desktop\public\pokepoke.ico"

Name "${PRODUCT_NAME}"
OutFile "PokePokeInstaller.exe"
InstallDir "$PROGRAMFILES\${PRODUCT_NAME}"
RequestExecutionLevel admin

Icon "${PRODUCT_ICON}"
UninstallIcon "${PRODUCT_ICON}"

VIProductVersion "0.1.0.0"
VIAddVersionKey /LANG=1033 "ProductName" "${PRODUCT_NAME}"
VIAddVersionKey /LANG=1033 "CompanyName" "${PRODUCT_PUBLISHER}"
VIAddVersionKey /LANG=1033 "FileDescription" "${PRODUCT_DESCRIPTION}"
VIAddVersionKey /LANG=1033 "FileVersion" "${PRODUCT_VERSION}"
VIAddVersionKey /LANG=1033 "ProductVersion" "${PRODUCT_VERSION}"

Section "MainSection" SEC01
    SetOutPath "$INSTDIR"
SectionEnd
