$ErrorActionPreference = 'Continue'
cd C:\Users\ameliapayne\PokePoke

Write-Output "=== STEP 1: git add src/pokepoke/orchestrator.py ==="
git add src/pokepoke/orchestrator.py
Write-Output ""

Write-Output "=== STEP 2: Check for _fix_indent.py ==="
if (Test-Path "_fix_indent.py") {
    Write-Output "Found _fix_indent.py, deleting..."
    Remove-Item "_fix_indent.py" -Force
    Write-Output "Deleted _fix_indent.py"
    Write-Output "Running git reset HEAD _fix_indent.py..."
    git reset HEAD _fix_indent.py
} else {
    Write-Output "_fix_indent.py does not exist"
}
Write-Output ""

Write-Output "=== STEP 3: git --no-pager status ==="
git --no-pager status
Write-Output ""

Write-Output "=== STEP 4: Python compile check ==="
python -c "import py_compile; py_compile.compile('src/pokepoke/orchestrator.py', doraise=True); print('OK')"
Write-Output ""

Write-Output "=== STEP 5: git commit ==="
git commit -m "fix: restore orchestrator indentation and add agent_type to status updates`n`nCo-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
