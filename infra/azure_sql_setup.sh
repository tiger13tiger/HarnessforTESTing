#!/usr/bin/env bash
# Sets up one Azure SQL logical server with two databases (dev, uat) for
# HarnessforTESTing -- the minimum infra needed to stop promote-dev-to-uat.yml
# and uat-to-prd-gate.yml from failing on a placeholder connection string.
#
# Run this yourself, in your own Azure account (az login first). Nothing in
# this repo runs it for you. It is idempotent-ish: re-running `az sql db create`
# etc. on existing resources just reports them as already there.
#
# Usage:
#   export SQL_ADMIN_PASSWORD='<a strong password you choose>'
#   bash infra/azure_sql_setup.sh
set -euo pipefail

RESOURCE_GROUP="rg-harnessfortesting"
LOCATION="eastus"                        # change to your/your company's usual region
SERVER_NAME="sql-harnessfortesting"       # must be globally unique across all of Azure;
                                           # if `az sql server create` says it's taken,
                                           # append digits (e.g. sql-harnessfortesting01)
                                           # and reuse that name in every command below
ADMIN_USER="harnessadmin"
DEV_DB="dev"
UAT_DB="uat"
FIREWALL_RULE_NAME="AllowAllTemporary"

if [ -z "${SQL_ADMIN_PASSWORD:-}" ]; then
  echo "error: set SQL_ADMIN_PASSWORD first (export SQL_ADMIN_PASSWORD='...')" >&2
  exit 1
fi

az group create \
  --name "$RESOURCE_GROUP" \
  --location "$LOCATION"

az sql server create \
  --name "$SERVER_NAME" \
  --resource-group "$RESOURCE_GROUP" \
  --location "$LOCATION" \
  --admin-user "$ADMIN_USER" \
  --admin-password "$SQL_ADMIN_PASSWORD"

# General Purpose Serverless, 1 vCore ceiling, auto-pauses after 60 min idle --
# cheapest tier that still behaves like a real SQL Server for pyodbc/T-SQL.
for DB in "$DEV_DB" "$UAT_DB"; do
  az sql db create \
    --resource-group "$RESOURCE_GROUP" \
    --server "$SERVER_NAME" \
    --name "$DB" \
    --edition GeneralPurpose \
    --family Gen5 --capacity 1 \
    --compute-model Serverless \
    --auto-pause-delay 60
done

# GitHub-hosted runners have no fixed IP, so this allows all IPs through the
# server firewall. Test-only data belongs in these two databases because of
# that -- never anything real. Least-privilege comes from the login itself
# (see the note at the bottom), not from this firewall rule.
az sql server firewall-rule create \
  --resource-group "$RESOURCE_GROUP" \
  --server "$SERVER_NAME" \
  --name "$FIREWALL_RULE_NAME" \
  --start-ip-address 0.0.0.0 \
  --end-ip-address 255.255.255.255

echo ""
echo "Done. Connection strings for GitHub secrets:"
echo ""
echo "SYNAPSE_DEV_CONN_STR = Driver={ODBC Driver 18 for SQL Server};Server=tcp:${SERVER_NAME}.database.windows.net,1433;Database=${DEV_DB};Uid=${ADMIN_USER};Pwd=<your password>;Encrypt=yes;"
echo "SYNAPSE_UAT_CONN_STR = Driver={ODBC Driver 18 for SQL Server};Server=tcp:${SERVER_NAME}.database.windows.net,1433;Database=${UAT_DB};Uid=${ADMIN_USER};Pwd=<your password>;Encrypt=yes;"
echo ""
echo "Add both at: https://github.com/tiger13tiger/HarnessforTESTing/settings/secrets/actions"
echo "(paste your real password in place of <your password> -- never commit it anywhere)"

# NOTE on least privilege (do this once, manually, after the databases exist --
# not automated here since it needs a SQL connection, not az cli):
#   The admin login above can do anything. For day-to-day CI use, create a
#   second, scoped login per database instead and point the GitHub secrets at
#   that one -- e.g., connect as the admin once and run, in each database:
#     CREATE USER harness_ci WITH PASSWORD = '<a different strong password>';
#     ALTER ROLE db_datareader ADD MEMBER harness_ci;
#     ALTER ROLE db_datawriter ADD MEMBER harness_ci;
#     GRANT CREATE PROCEDURE TO harness_ci;
#     GRANT EXECUTE TO harness_ci;
#   This still can't DROP DATABASE/DROP SCHEMA/etc. if you skip db_owner,
#   which backs up harness/guardrails.py's text-level checks with a real
#   permission boundary instead of relying on them alone.
