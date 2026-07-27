# Создаёт ярлык «Local AI Organizer» на рабочем столе.
# Запуск: правый клик по файлу -> «Выполнить с помощью PowerShell»
#   или в PowerShell:  powershell -ExecutionPolicy Bypass -File create_shortcut.ps1

$root = $PSScriptRoot
$desktop = [Environment]::GetFolderPath('Desktop')
$linkPath = Join-Path $desktop 'Local AI Organizer.lnk'

# Предпочитаем pythonw из venv (без окна консоли), иначе системный
$pythonw = Join-Path $root '.venv\Scripts\pythonw.exe'
if (-not (Test-Path $pythonw)) { $pythonw = 'pythonw.exe' }

$shell = New-Object -ComObject WScript.Shell
$shortcut = $shell.CreateShortcut($linkPath)
$shortcut.TargetPath = $pythonw
$shortcut.Arguments = '"' + (Join-Path $root 'main.py') + '"'
$shortcut.WorkingDirectory = $root
$shortcut.Description = 'Local AI Organizer'

$icon = Join-Path $root 'assets\icon.ico'
if (Test-Path $icon) { $shortcut.IconLocation = $icon }

$shortcut.Save()
Write-Host "Ярлык создан на рабочем столе: $linkPath"
