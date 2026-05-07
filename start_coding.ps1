$judge0Key = Read-Host "Paste your Judge0 RapidAPI key" -AsSecureString

$judge0KeyPointer = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($judge0Key)
$plainJudge0Key = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($judge0KeyPointer)
[Runtime.InteropServices.Marshal]::ZeroFreeBSTR($judge0KeyPointer)

if ([string]::IsNullOrWhiteSpace($plainJudge0Key)) {
    Write-Host "No Judge0 API key entered. App not started." -ForegroundColor Yellow
    exit 1
}

$env:JUDGE0_URL = "https://judge0-ce.p.rapidapi.com"
$env:JUDGE0_API_HOST = "judge0-ce.p.rapidapi.com"
$env:JUDGE0_API_KEY = $plainJudge0Key

Write-Host "Judge0 RapidAPI settings are set for this app session." -ForegroundColor Green
Write-Host "Starting GMTech Assessment..." -ForegroundColor Green

python app.py
