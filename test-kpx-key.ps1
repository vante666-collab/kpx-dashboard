# data.go.kr 키/데이터셋 호출 테스트 — 전파(승인) 확인용
# 실행:  powershell -ExecutionPolicy Bypass -File .\test-kpx-key.ps1
$key = $env:KPX_SERVICE_KEY
if (-not $key) {
  Write-Host "환경변수 KPX_SERVICE_KEY 가 설정되지 않았습니다. 먼저:  \$env:KPX_SERVICE_KEY='<발급키>'" -ForegroundColor Yellow
  exit 1
}
$ua  = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124.0 Safari/537.36'

# 활용신청한 데이터셋: 발전설비 정보 (15099767)
$url = "https://apis.data.go.kr/B552115/PowerMarketGenInfo/getPowerMarketGenInfo?serviceKey=$key&pageNo=1&numOfRows=3&dataType=JSON"

try {
  $r = Invoke-WebRequest -Uri $url -TimeoutSec 25 -UseBasicParsing -UserAgent $ua
  Write-Host "STATUS: $($r.StatusCode)  (성공 — 키 정상 동작)" -ForegroundColor Green
  Write-Host $r.Content
} catch {
  $code = if ($_.Exception.Response) { [int]$_.Exception.Response.StatusCode } else { 'N/A' }
  Write-Host "실패 HTTP $code : $($_.Exception.Message)" -ForegroundColor Yellow
  Write-Host "→ 403 이면: 활용신청 직후 전파 지연(최대 1~2h) 또는 키 값 확인 필요" -ForegroundColor Yellow
}
