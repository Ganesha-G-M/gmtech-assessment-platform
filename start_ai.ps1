$secureApiKey = Read-Host "Paste your Gemini API key" -AsSecureString

$apiKeyPointer = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secureApiKey)
$apiKey = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($apiKeyPointer)
[Runtime.InteropServices.Marshal]::ZeroFreeBSTR($apiKeyPointer)

if ([string]::IsNullOrWhiteSpace($apiKey)) {
    Write-Host "No API key entered. App not started." -ForegroundColor Yellow
    exit 1
}

$env:AI_PROVIDER = "gemini"
$env:GEMINI_API_KEY = $apiKey
$env:GEMINI_MODEL = "gemini-1.5-flash"
Remove-Item Env:JUDGE0_URL -ErrorAction SilentlyContinue
Remove-Item Env:JUDGE0_API_HOST -ErrorAction SilentlyContinue
Remove-Item Env:JUDGE0_API_KEY -ErrorAction SilentlyContinue
$env:LOCAL_CODE_RUNNER = "1"

Write-Host "GEMINI_API_KEY is set for this app session." -ForegroundColor Green
Write-Host "AI_PROVIDER is set to Gemini." -ForegroundColor Green
Write-Host "Local Python/Java compiler is enabled for coding questions." -ForegroundColor Green
Write-Host "Starting GMTech Assessment..." -ForegroundColor Green

python app.py
