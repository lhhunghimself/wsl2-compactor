# WSL Compact Headless Test Script
# This script tests the core compaction functionality without the GUI

param(
    [string]$Distro = "Ubuntu",
    [string]$User = "ubuntu",
    [string]$VhdPath = "",
    [switch]$SkipPython = $false
)

Write-Host "=== WSL Compact Headless Test ===" -ForegroundColor Cyan
Write-Host "Testing with Distro: $Distro, User: $User" -ForegroundColor Yellow

# Test 1: Check if Python module can be imported
if (-not $SkipPython) {
    Write-Host "`n[Test 1] Checking Python module import..." -ForegroundColor Green
    try {
        $importTest = python -c "import wsl_compact.core; print('Import successful')" 2>&1
        if ($LASTEXITCODE -eq 0) {
            Write-Host "✅ Python module import: PASS" -ForegroundColor Green
        } else {
            Write-Host "❌ Python module import: FAIL" -ForegroundColor Red
            Write-Host "Error: $importTest" -ForegroundColor Red
            exit 1
        }
    }
    catch {
        Write-Host "❌ Python module import: FAIL - $($_.Exception.Message)" -ForegroundColor Red
        exit 1
    }
}

# Test 2: CLI help test
Write-Host "`n[Test 2] Testing CLI help..." -ForegroundColor Green
try {
    $helpOutput = python -m wsl_compact.cli --help 2>&1
    if ($LASTEXITCODE -eq 0 -and $helpOutput -match "WSL Compact CLI") {
        Write-Host "✅ CLI help: PASS" -ForegroundColor Green
    } else {
        Write-Host "❌ CLI help: FAIL" -ForegroundColor Red
        Write-Host "Output: $helpOutput" -ForegroundColor Red
        exit 1
    }
}
catch {
    Write-Host "❌ CLI help: FAIL - $($_.Exception.Message)" -ForegroundColor Red
    exit 1
}

# Test 3: Dry run test (the main functionality test)
Write-Host "`n[Test 3] Testing dry-run compaction..." -ForegroundColor Green
try {
    $dummyPath = "C:\\dummy\\ext4.vhdx"
    $dryRunArgs = @(
        "-m", "wsl_compact.cli",
        "--distro", $Distro,
        "--user", $User,
        "--vhd", $dummyPath,
        "--dry-run"
    )
    
    if ($VhdPath) {
        $dryRunArgs += "--vhd", $VhdPath
    }
    
    $dryRunOutputLines = python @dryRunArgs 2>&1
    $dryRunOutput = [string]::Join("`n", $dryRunOutputLines)
    $exitCode = $LASTEXITCODE
    
    Write-Host "Dry-run output:" -ForegroundColor Cyan
    Write-Host $dryRunOutput -ForegroundColor Gray
    
    # Check for expected dry-run indicators (case-insensitive)
    $expectedPatterns = @(
        "DRY-RUN MODE",
        "Target distro: $Distro",
        "Target user: $User",
        "DiskPart compact simulation completed"
    )

    $allPatternsFound = $true
    foreach ($pattern in $expectedPatterns) {
        if (-not ($dryRunOutput -imatch $pattern)) {
            Write-Host "❌ Missing expected pattern: '$pattern'" -ForegroundColor Red
            $allPatternsFound = $false
        }
    }
    
    if ($exitCode -eq 0 -and $allPatternsFound) {
        Write-Host "✅ Dry-run compaction: PASS" -ForegroundColor Green
    } else {
        Write-Host "❌ Dry-run compaction: FAIL (exit code: $exitCode)" -ForegroundColor Red
        exit 1
    }
}
catch {
    Write-Host "❌ Dry-run compaction: FAIL - $($_.Exception.Message)" -ForegroundColor Red
    exit 1
}

# Test 4: Invalid distro handling
Write-Host "`n[Test 4] Testing invalid distro handling..." -ForegroundColor Green
try {
    $invalidOutput = python -m wsl_compact.cli --distro "NonExistentDistro" --user $User --dry-run 2>&1
    $exitCode = $LASTEXITCODE
    
    if ($exitCode -ne 0 -or $invalidOutput -match "Could not auto-detect VHD") {
        Write-Host "✅ Invalid distro handling: PASS" -ForegroundColor Green
    } else {
        Write-Host "❌ Invalid distro handling: FAIL - should have failed" -ForegroundColor Red
        Write-Host "Output: $invalidOutput" -ForegroundColor Red
        exit 1
    }
}
catch {
    Write-Host "❌ Invalid distro handling: FAIL - $($_.Exception.Message)" -ForegroundColor Red
    exit 1
}

Write-Host "`n=== All Tests Passed! ===" -ForegroundColor Green
Write-Host "WSL Compact headless functionality is working correctly." -ForegroundColor Cyan
exit 0
