$pasta = $PSScriptRoot
if ((Split-Path -Leaf $pasta) -eq 'src') {
    $pasta = Split-Path -Parent $pasta
}

if ($args.Count -gt 0) {
    [Console]::Error.WriteLine('Este comando não aceita argumentos. Não há arquivo de teste, CSV nem --confirmar-creditos.')
    exit 2
}

Set-Location -LiteralPath $pasta

$python = 'C:\Users\andre\AppData\Local\Programs\Python\Python311\python.exe'
if (-not (Test-Path -LiteralPath $python)) {
    [Console]::Error.WriteLine("Interpretador não encontrado: $python. Este comando não usa producao/venv.")
    exit 1
}

$env:PYTHONIOENCODING = 'utf-8'
& $python 'src/verificar.py'
exit $LASTEXITCODE
