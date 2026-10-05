<#
.SYNOPSIS
    Envia os extratos PDF da pasta "entrada" para a API de conciliacao bancaria.

.DESCRIPTION
    Para cada PDF em <Pasta>\entrada:
      - sucesso (HTTP 2xx): move o PDF para <Pasta>\lidos e salva a resposta da API em .json ao lado
      - arquivo rejeitado (HTTP 400/413): move para <Pasta>\erro com o motivo em .erro.txt
      - falha temporaria (sem conexao, 401, 5xx...): deixa o PDF na entrada para a proxima execucao

    Compativel com Windows PowerShell 5.1 (padrao do Windows Server). Feito para rodar
    pelo Agendador de Tarefas (veja instalar_tarefa.ps1).

.EXAMPLE
    .\enviar_extratos.ps1 -ApiUrl "http://localhost:5000/extratos" -Token "meu-token"

.EXAMPLE
    # Token pela variavel de ambiente (recomendado: nao fica visivel na configuracao da tarefa)
    $env:CONCILIACAO_TOKEN = "meu-token"; .\enviar_extratos.ps1
#>
param(
    [string]$ApiUrl = "http://localhost:5000/extratos",
    [string]$Token = $env:CONCILIACAO_TOKEN,
    [string]$Pasta = $PSScriptRoot,
    # Um arquivo modificado ha menos tempo que isso pode ainda estar sendo copiado
    [int]$SegundosEstabilidade = 10
)

$ErrorActionPreference = "Stop"
Add-Type -AssemblyName System.Net.Http
# Windows Server mais antigo nao habilita TLS 1.2 por padrao (necessario para HTTPS)
[Net.ServicePointManager]::SecurityProtocol = [Net.ServicePointManager]::SecurityProtocol -bor [Net.SecurityProtocolType]::Tls12

$entrada = Join-Path $Pasta "entrada"
$lidos = Join-Path $Pasta "lidos"
$erro = Join-Path $Pasta "erro"
$arquivoLog = Join-Path $Pasta "enviar_extratos.log"
$utf8 = New-Object System.Text.UTF8Encoding($false)

function Escrever-Log([string]$mensagem) {
    $linha = "{0:yyyy-MM-dd HH:mm:ss} {1}" -f (Get-Date), $mensagem
    [IO.File]::AppendAllText($arquivoLog, $linha + [Environment]::NewLine, $utf8)
    Write-Host $linha
}

function Test-ArquivoPronto([IO.FileInfo]$arquivo) {
    # Ainda sendo copiado: modificado ha pouco tempo ou aberto por outro processo
    if ($arquivo.LastWriteTime -gt (Get-Date).AddSeconds(-$SegundosEstabilidade)) { return $false }
    try {
        $stream = [IO.File]::Open($arquivo.FullName, 'Open', 'Read', 'None')
        $stream.Close()
        return $true
    } catch {
        return $false
    }
}

function Get-DestinoLivre([string]$pastaDestino, [string]$nome) {
    # Nao sobrescreve: se ja existe um arquivo com o mesmo nome, acrescenta data/hora
    $destino = Join-Path $pastaDestino $nome
    if (Test-Path -LiteralPath $destino) {
        $base = [IO.Path]::GetFileNameWithoutExtension($nome)
        $extensao = [IO.Path]::GetExtension($nome)
        $destino = Join-Path $pastaDestino ("{0}_{1:yyyyMMdd_HHmmss}{2}" -f $base, (Get-Date), $extensao)
    }
    return $destino
}

function Escrever-Resumo([string]$json) {
    try {
        $dados = $json | ConvertFrom-Json
        foreach ($banco in $dados.PSObject.Properties) {
            foreach ($extrato in $banco.Value) {
                $ok = $extrato.conferencia.ok
                if ($null -eq $ok) { $ok = "sem saldo" }
                $resumo = "    {0} | conta {1} | {2} lancamentos | conferencia ok={3}" -f `
                    $banco.Name, $extrato.conta, @($extrato.lancamentos).Count, $ok
                if ($extrato.aviso) { $resumo += " | AVISO: " + $extrato.aviso }
                Escrever-Log $resumo
            }
        }
    } catch {
        Escrever-Log "    (nao foi possivel ler o resumo da resposta)"
    }
}

# ---------------------------------------------------------------------------

if (-not $Token) {
    Escrever-Log "ERRO: token nao informado. Use -Token ou a variavel de ambiente CONCILIACAO_TOKEN."
    exit 1
}
foreach ($p in @($entrada, $lidos, $erro)) {
    if (-not (Test-Path -LiteralPath $p)) { New-Item -ItemType Directory -Path $p | Out-Null }
}

$pdfs = @(Get-ChildItem -LiteralPath $entrada -Filter *.pdf -File)
if ($pdfs.Count -eq 0) { exit 0 }

$http = New-Object System.Net.Http.HttpClient
$http.Timeout = [TimeSpan]::FromMinutes(10)   # o fallback com IA pode demorar
$http.DefaultRequestHeaders.Authorization = New-Object System.Net.Http.Headers.AuthenticationHeaderValue("Bearer", $Token)

$falhas = 0
foreach ($pdf in $pdfs) {
    if (-not (Test-ArquivoPronto $pdf)) {
        Escrever-Log "AGUARDANDO $($pdf.Name): arquivo ainda sendo copiado, fica para a proxima execucao."
        continue
    }

    $formulario = New-Object System.Net.Http.MultipartFormDataContent
    try {
        $conteudo = [System.Net.Http.ByteArrayContent]::new([IO.File]::ReadAllBytes($pdf.FullName))
        $conteudo.Headers.ContentType = [System.Net.Http.Headers.MediaTypeHeaderValue]::Parse("application/pdf")
        $formulario.Add($conteudo, "arquivos", $pdf.Name)

        $resposta = $http.PostAsync($ApiUrl, $formulario).GetAwaiter().GetResult()
        $corpo = $resposta.Content.ReadAsStringAsync().GetAwaiter().GetResult()
        $codigo = [int]$resposta.StatusCode
    } catch {
        Escrever-Log "FALHA $($pdf.Name): nao foi possivel enviar ($($_.Exception.Message)). Tenta de novo na proxima execucao."
        $falhas++
        continue
    } finally {
        $formulario.Dispose()
    }

    if ($codigo -ge 200 -and $codigo -lt 300) {
        $destino = Get-DestinoLivre $lidos $pdf.Name
        Move-Item -LiteralPath $pdf.FullName -Destination $destino
        [IO.File]::WriteAllText([IO.Path]::ChangeExtension($destino, ".json"), $corpo, $utf8)
        Escrever-Log "OK $($pdf.Name) -> lidos"
        Escrever-Resumo $corpo
    } elseif ($codigo -eq 400 -or $codigo -eq 413) {
        # Rejeitado pela API (nao e PDF, muito grande...): reenviar nao resolve
        $destino = Get-DestinoLivre $erro $pdf.Name
        Move-Item -LiteralPath $pdf.FullName -Destination $destino
        [IO.File]::WriteAllText([IO.Path]::ChangeExtension($destino, ".erro.txt"), "HTTP $codigo`r`n$corpo", $utf8)
        Escrever-Log "REJEITADO $($pdf.Name) (HTTP $codigo) -> erro: $corpo"
        $falhas++
    } else {
        # 401 (token), 5xx (API fora do ar, IA indisponivel...): problema temporario ou de configuracao
        Escrever-Log "FALHA $($pdf.Name) (HTTP $codigo): $corpo. Tenta de novo na proxima execucao."
        $falhas++
    }
}

$http.Dispose()
if ($falhas -gt 0) { exit 1 }
exit 0
