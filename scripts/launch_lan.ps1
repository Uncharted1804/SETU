<#
.SYNOPSIS
    Launch SETU on one explicitly selected private LAN address.

.DESCRIPTION
    The LAN boundary is the selected local bind address plus a Windows Firewall
    inbound rule limited to the Private profile and one trusted RFC1918 subnet.
    CORS is deliberately disabled here: CORS is a browser policy, not a network
    access-control boundary, and it does not constrain curl or Postman.

    This script never binds 0.0.0.0, opens the Public profile, exposes Ollama,
    changes Docker networking, or changes global firewall state.

.PARAMETER BindAddress
    An IPv4 address assigned to an active local adapter. It must be RFC1918 and
    belong to TrustedSubnet.

.PARAMETER TrustedSubnet
    The explicitly observed RFC1918 IPv4 subnet, for example 192.168.50.0/24.

.PARAMETER Port
    SETU's TCP listen port. Defaults to 8001 so an unrelated process on 8000 is
    left alone.

.PARAMETER ConfigureFirewall
    Explicitly create or replace only this script's named, exact scoped rule.
    Requires an elevated PowerShell session. Do not use it until the displayed
    address, subnet, and port have been checked against the demo network.

.EXAMPLE
    .\scripts\launch_lan.ps1 -BindAddress 192.168.50.10 -TrustedSubnet 192.168.50.0/24

.EXAMPLE
    .\scripts\launch_lan.ps1 -BindAddress 192.168.50.10 -TrustedSubnet 192.168.50.0/24 -ConfigureFirewall
#>
[CmdletBinding(SupportsShouldProcess = $true)]
param(
    [Parameter(Mandatory)]
    [string]$BindAddress,

    [Parameter(Mandatory)]
    [string]$TrustedSubnet,

    [ValidateRange(1, 65535)]
    [int]$Port = 8001,

    [switch]$ConfigureFirewall
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function Get-IPv4Number {
    param([Parameter(Mandatory)][System.Net.IPAddress]$Address)

    [uint64]$number = 0
    foreach ($octet in $Address.GetAddressBytes()) {
        $number = ($number -shl 8) -bor [uint64]$octet
    }
    return $number
}

function Test-Rfc1918Number {
    param([Parameter(Mandatory)][uint64]$Address)

    return (
        ($Address -ge 0x0A000000 -and $Address -le 0x0AFFFFFF) -or
        ($Address -ge 0xAC100000 -and $Address -le 0xAC1FFFFF) -or
        ($Address -ge 0xC0A80000 -and $Address -le 0xC0A8FFFF)
    )
}

function Get-TrustedSubnet {
    param([Parameter(Mandatory)][string]$Cidr)

    $parts = $Cidr.Trim().Split("/")
    if ($parts.Count -ne 2) {
        throw "TrustedSubnet must be an IPv4 CIDR such as 192.168.50.0/24."
    }

    [System.Net.IPAddress]$address = $null
    if (-not [System.Net.IPAddress]::TryParse($parts[0], [ref]$address) -or
        $address.AddressFamily -ne [System.Net.Sockets.AddressFamily]::InterNetwork) {
        throw "TrustedSubnet must contain an IPv4 address, not '$($parts[0])'."
    }

    [int]$prefix = 0
    if (-not [int]::TryParse($parts[1], [ref]$prefix) -or $prefix -lt 0 -or $prefix -gt 32) {
        throw "TrustedSubnet prefix must be between 0 and 32."
    }

    [uint64]$thirtyTwoOnes = [uint64]"0xFFFFFFFF"
    [uint64]$mask = if ($prefix -eq 0) { 0 } else { ($thirtyTwoOnes -shl (32 - $prefix)) -band $thirtyTwoOnes }
    [uint64]$network = (Get-IPv4Number $address) -band $mask
    [uint64]$broadcast = $network -bor ($thirtyTwoOnes -bxor $mask)
    if (-not (Test-Rfc1918Number $network) -or -not (Test-Rfc1918Number $broadcast)) {
        throw "TrustedSubnet must be wholly inside one RFC1918 range; '$Cidr' is not."
    }

    $networkBytes = [byte[]]@(
        (($network -shr 24) -band 0xFF), (($network -shr 16) -band 0xFF),
        (($network -shr 8) -band 0xFF), ($network -band 0xFF)
    )
    $maskBytes = [byte[]]@(
        (($mask -shr 24) -band 0xFF), (($mask -shr 16) -band 0xFF),
        (($mask -shr 8) -band 0xFF), ($mask -band 0xFF)
    )
    $normalised = ([System.Net.IPAddress]::new($networkBytes)).ToString() + "/$prefix"
    $firewallRemote = ([System.Net.IPAddress]::new($networkBytes)).ToString() + "/" + ([System.Net.IPAddress]::new($maskBytes)).ToString()
    return [pscustomobject]@{ Network = $network; Broadcast = $broadcast; Cidr = $normalised; FirewallRemote = $firewallRemote }
}

function Assert-Administrator {
    $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
    $principal = [Security.Principal.WindowsPrincipal]::new($identity)
    if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
        throw "-ConfigureFirewall requires an elevated PowerShell session. No firewall change was made."
    }
}

function Get-RuleName {
    param([string]$Address, [int]$ListenPort)
    return "SETU-LAN-$Address-$ListenPort"
}

function Test-ScopedFirewallRule {
    param(
        [Parameter(Mandatory)][string]$RuleName,
        [Parameter(Mandatory)][string]$Address,
        [Parameter(Mandatory)][string]$Subnet,
        [Parameter(Mandatory)][string]$FirewallRemote,
        [Parameter(Mandatory)][int]$ListenPort
    )

    $rules = @(Get-NetFirewallRule -Name $RuleName -ErrorAction SilentlyContinue)
    foreach ($rule in $rules) {
        if ($rule.Enabled -ne "True" -or $rule.Direction -ne "Inbound" -or
            $rule.Action -ne "Allow" -or $rule.Profile.ToString() -ne "Private") {
            continue
        }
        $ports = @(Get-NetFirewallPortFilter -AssociatedNetFirewallRule $rule)
        $addresses = @(Get-NetFirewallAddressFilter -AssociatedNetFirewallRule $rule)
        $portMatches = $ports | Where-Object {
            $_.Protocol -eq "TCP" -and $_.LocalPort.ToString() -eq $ListenPort.ToString()
        }
        $addressMatches = $addresses | Where-Object {
            @($_.LocalAddress) -contains $Address -and (@($_.RemoteAddress) -contains $Subnet -or @($_.RemoteAddress) -contains $FirewallRemote)
        }
        if ($portMatches -and $addressMatches) {
            return $true
        }
    }
    return $false
}

function Set-ScopedFirewallRule {
    param(
        [Parameter(Mandatory)][string]$RuleName,
        [Parameter(Mandatory)][string]$Address,
        [Parameter(Mandatory)][string]$Subnet,
        [Parameter(Mandatory)][int]$ListenPort
    )

    Write-Host "Will create/update only Windows Firewall rule '$RuleName':" -ForegroundColor Yellow
    Write-Host "  inbound TCP local $Address`:$ListenPort; remote $Subnet; profile Private; action Allow"
    Assert-Administrator

    if ($PSCmdlet.ShouldProcess($RuleName, "replace this exact scoped inbound firewall rule")) {
        # This removes only the deterministic SETU rule name for this exact
        # bind address and port. It never enumerates, prunes, or changes other rules.
        Get-NetFirewallRule -Name $RuleName -ErrorAction SilentlyContinue |
            Remove-NetFirewallRule -ErrorAction Stop
        New-NetFirewallRule -Name $RuleName -DisplayName $RuleName -Direction Inbound `
            -Action Allow -Enabled True -Profile Private -Protocol TCP -LocalAddress $Address `
            -LocalPort $ListenPort -RemoteAddress $Subnet | Out-Null
    }
}

[System.Net.IPAddress]$bindIp = $null
if (-not [System.Net.IPAddress]::TryParse($BindAddress, [ref]$bindIp) -or
    $bindIp.AddressFamily -ne [System.Net.Sockets.AddressFamily]::InterNetwork) {
    throw "BindAddress must be a concrete IPv4 address; wildcard binding is forbidden."
}
[uint64]$bindNumber = Get-IPv4Number $bindIp
if (-not (Test-Rfc1918Number $bindNumber)) {
    throw "BindAddress must be RFC1918 private IPv4; '$BindAddress' was refused."
}

$subnet = Get-TrustedSubnet $TrustedSubnet
if ($bindNumber -lt $subnet.Network -or $bindNumber -gt $subnet.Broadcast) {
    throw "BindAddress $BindAddress is not inside TrustedSubnet $($subnet.Cidr)."
}

$assigned = @(Get-NetIPAddress -AddressFamily IPv4 -ErrorAction Stop | Where-Object {
    $_.IPAddress -eq $BindAddress -and $_.AddressState -ne "Invalid"
})
if (-not $assigned) {
    throw "BindAddress $BindAddress is not assigned to a local IPv4 adapter."
}
$active = @($assigned | Where-Object {
    $adapter = Get-NetAdapter -InterfaceIndex $_.InterfaceIndex -ErrorAction SilentlyContinue
    $adapter -and $adapter.Status -eq "Up"
})
if (-not $active) {
    throw "BindAddress $BindAddress is not assigned to an active local adapter."
}

$ruleName = Get-RuleName $BindAddress $Port
if ($ConfigureFirewall) {
    Set-ScopedFirewallRule $ruleName $BindAddress $subnet.Cidr $Port
}
if (-not (Test-ScopedFirewallRule $ruleName $BindAddress $subnet.Cidr $subnet.FirewallRemote $Port)) {
    throw @"
Refusing LAN launch: no exact enabled firewall rule was found.
Required: inbound TCP local $BindAddress`:$Port; remote $($subnet.Cidr); Private profile only; Allow.
Review the values above, then run this script once from an elevated PowerShell session with -ConfigureFirewall.
"@
}

$repo = Split-Path -Parent $PSScriptRoot
$python = Join-Path $repo ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $python -PathType Leaf)) {
    throw "Project Python was not found at $python. Run the repository environment setup first."
}

$env:SETU_TRUSTED_SUBNET = $subnet.Cidr
$env:SETU_MOCK_MODE = "0"
$env:OLLAMA_HOST = "127.0.0.1:11434"
Remove-Item Env:SETU_DEV_MODE -ErrorAction SilentlyContinue
Remove-Item Env:SETU_DEV_ORIGINS -ErrorAction SilentlyContinue

Write-Host "LAN boundary enforced: bind $BindAddress`:$Port; Private-profile firewall remote scope $($subnet.Cidr)." -ForegroundColor Green
Write-Host "CORS remains disabled. It controls browser JavaScript only; the bind address and firewall are the LAN boundary."
Write-Host "Ollama remains configured on 127.0.0.1:11434 and is not exposed by this launcher."
Write-Host ""
Write-Host "After launch, verify:"
Write-Host "  Invoke-RestMethod http://$BindAddress`:$Port/api/health"
Write-Host "  # From a second device on $($subnet.Cidr): curl.exe -m 3 http://$BindAddress`:$Port/api/health"
Write-Host "  # From that device, Ollama must refuse/time out: curl.exe -m 3 http://$BindAddress`:11434/api/tags"
Write-Host "  Get-NetTCPConnection -State Listen -LocalPort $Port | Format-Table LocalAddress,LocalPort,OwningProcess"
Write-Host "  Get-NetFirewallRule -Name '$ruleName' | Format-List Name,Enabled,Direction,Action,Profile"
Write-Host "  Get-NetFirewallRule -Name '$ruleName' | Get-NetFirewallPortFilter | Format-List Protocol,LocalPort"
Write-Host "  Get-NetFirewallRule -Name '$ruleName' | Get-NetFirewallAddressFilter | Format-List LocalAddress,RemoteAddress"
Write-Host "  Invoke-RestMethod http://$BindAddress`:$Port/api/network-status"
Write-Host "  .\.venv\Scripts\python.exe scripts\offline_check.py  # separate air-gap rehearsal; LAN adapter must be down for a pass"
Write-Host ""

& $python -m uvicorn app.main:app --app-dir backend --host $BindAddress --port $Port
