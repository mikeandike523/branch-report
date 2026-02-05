# Get the directory of this script with correct casing
$scriptDir = (Get-Item $PSScriptRoot).FullName

# Add to user PATH if not already present
$userPath = [Environment]::GetEnvironmentVariable("PATH", "User")
if ($userPath -notlike "*$scriptDir*") {
    [Environment]::SetEnvironmentVariable("PATH", "$userPath;$scriptDir", "User")
    Write-Host "Added $scriptDir to user PATH."
} else {
    Write-Host "$scriptDir is already in user PATH."
}

# Add to system PATH if not already present (requires elevated privileges)
$systemPath = [Environment]::GetEnvironmentVariable("PATH", "Machine")
if ($systemPath -notlike "*$scriptDir*") {
    [Environment]::SetEnvironmentVariable("PATH", "$systemPath;$scriptDir", "Machine")
    Write-Host "Added $scriptDir to system PATH."
} else {
    Write-Host "$scriptDir is already in system PATH."
}