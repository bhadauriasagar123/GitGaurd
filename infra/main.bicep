// RegGuard Shield - minimal-cost Azure footprint
//   App Service Linux (F1 free tier)  +  Azure Database for PostgreSQL Flexible Server (Burstable B1ms)
//   Redis: supplied via `redisUrl` (free Upstash/Redis Cloud tier, or Azure Managed Redis when you scale up)
// Deploy:  az deployment group create -g <rg> -f infra/main.bicep -p appName=<unique> pgAdminPassword=<...> redisUrl=<...> apiKeys=<...> encKey=<...>
targetScope = 'resourceGroup'

@description('Globally unique web app name (becomes <name>.azurewebsites.net)')
param appName string
param location string = resourceGroup().location
@allowed(['F1', 'B1', 'P0v3'])
@description('F1 = free. Use B1+ for Always On / custom containers.')
param skuName string = 'F1'

@secure()
@description('Letters and digits only (it is embedded in a connection URL).')
param pgAdminPassword string
param pgAdminUser string = 'regguardadmin'
@secure()
param redisUrl string
@secure()
@description('key:role:tenant,key2:role:tenant  (keys >= 24 chars)')
param apiKeys string
@secure()
@description('64 hex chars')
param encKey string
param foundryEndpoint string = ''
@secure()
param foundryKey string = ''
param foundryDeployment string = 'gpt-4o-mini'

var pgName = toLower('${appName}-pg')
var dbName = 'regguard'
var databaseUrl = 'postgresql+asyncpg://${pgAdminUser}:${uriComponent(pgAdminPassword)}@${pg.properties.fullyQualifiedDomainName}:5432/${dbName}?ssl=require'

resource plan 'Microsoft.Web/serverfarms@2023-12-01' = {
  name: '${appName}-plan'
  location: location
  kind: 'linux'
  sku: { name: skuName }
  properties: { reserved: true }
}

resource pg 'Microsoft.DBforPostgreSQL/flexibleServers@2022-12-01' = {
  name: pgName
  location: location
  sku: { name: 'Standard_B1ms', tier: 'Burstable' }
  properties: {
    version: '16'
    administratorLogin: pgAdminUser
    administratorLoginPassword: pgAdminPassword
    storage: { storageSizeGB: 32 }
    backup: { backupRetentionDays: 7, geoRedundantBackup: 'Disabled' }
    highAvailability: { mode: 'Disabled' }
    network: { publicNetworkAccess: 'Enabled' }
  }
}

resource db 'Microsoft.DBforPostgreSQL/flexibleServers/databases@2022-12-01' = {
  parent: pg
  name: dbName
  properties: { charset: 'UTF8', collation: 'en_US.utf8' }
}

// 0.0.0.0 -> 0.0.0.0 means "allow Azure services". For production prefer VNet integration + private endpoint.
resource allowAzure 'Microsoft.DBforPostgreSQL/flexibleServers/firewallRules@2022-12-01' = {
  parent: pg
  name: 'AllowAzureServices'
  properties: { startIpAddress: '0.0.0.0', endIpAddress: '0.0.0.0' }
}

resource web 'Microsoft.Web/sites@2023-12-01' = {
  name: appName
  location: location
  kind: 'app,linux'
  identity: { type: 'SystemAssigned' }
  properties: {
    serverFarmId: plan.id
    httpsOnly: true
    clientAffinityEnabled: false
    siteConfig: {
      linuxFxVersion: 'PYTHON|3.12'
      appCommandLine: 'python -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 1 --no-server-header --proxy-headers --forwarded-allow-ips "*" --timeout-keep-alive 30 --timeout-graceful-shutdown 20'
      ftpsState: 'Disabled'
      minTlsVersion: '1.2'
      http20Enabled: true
      alwaysOn: skuName == 'F1' ? false : true
      healthCheckPath: '/healthz'
      appSettings: [
        { name: 'ENV', value: 'production' }
        { name: 'WEBSITES_PORT', value: '8000' }
        { name: 'SCM_DO_BUILD_DURING_DEPLOYMENT', value: 'true' }
        { name: 'DATABASE_URL', value: databaseUrl }
        { name: 'REDIS_URL', value: redisUrl }
        { name: 'API_KEYS', value: apiKeys }
        { name: 'ENC_KEY', value: encKey }
        { name: 'DOCS_ENABLED', value: 'false' }
        { name: 'FOUNDRY_ENDPOINT', value: foundryEndpoint }
        { name: 'FOUNDRY_KEY', value: foundryKey }
        { name: 'FOUNDRY_DEPLOYMENT', value: foundryDeployment }
      ]
    }
  }
}

output url string = 'https://${web.properties.defaultHostName}'
output postgresHost string = pg.properties.fullyQualifiedDomainName
