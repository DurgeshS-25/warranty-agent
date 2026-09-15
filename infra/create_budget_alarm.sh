#!/usr/bin/env bash
# Creates a $10/month AWS Budget with email alerts at 50%, 80%, and 100%
# of actual spend. Run this FIRST — before enabling Bedrock, before
# creating the IAM user, before anything else touches your AWS account.
#
# Requires: AWS CLI installed and `aws configure` already run with an
# account that has budgets:* permission (your root/admin user, one time,
# is fine for this — this script does not run again after Day 1).
#
# Usage:
#   export ALERT_EMAIL="you@example.com"
#   export AWS_ACCOUNT_ID="123456789012"   # aws sts get-caller-identity
#   ./infra/create_budget_alarm.sh

set -euo pipefail

: "${ALERT_EMAIL:?Set ALERT_EMAIL to your email address first}"
: "${AWS_ACCOUNT_ID:?Set AWS_ACCOUNT_ID first (run: aws sts get-caller-identity)}"

BUDGET_NAME="warranty-agent-10usd-cap"

echo "Creating budget '$BUDGET_NAME' — \$10/month, alerts at 50/80/100%..."

aws budgets create-budget \
  --account-id "$AWS_ACCOUNT_ID" \
  --budget "{
    \"BudgetName\": \"$BUDGET_NAME\",
    \"BudgetLimit\": {\"Amount\": \"10\", \"Unit\": \"USD\"},
    \"TimeUnit\": \"MONTHLY\",
    \"BudgetType\": \"COST\"
  }" \
  --notifications-with-subscribers "[
    {
      \"Notification\": {
        \"NotificationType\": \"ACTUAL\",
        \"ComparisonOperator\": \"GREATER_THAN\",
        \"Threshold\": 50
      },
      \"Subscribers\": [{\"SubscriptionType\": \"EMAIL\", \"Address\": \"$ALERT_EMAIL\"}]
    },
    {
      \"Notification\": {
        \"NotificationType\": \"ACTUAL\",
        \"ComparisonOperator\": \"GREATER_THAN\",
        \"Threshold\": 80
      },
      \"Subscribers\": [{\"SubscriptionType\": \"EMAIL\", \"Address\": \"$ALERT_EMAIL\"}]
    },
    {
      \"Notification\": {
        \"NotificationType\": \"ACTUAL\",
        \"ComparisonOperator\": \"GREATER_THAN\",
        \"Threshold\": 100
      },
      \"Subscribers\": [{\"SubscriptionType\": \"EMAIL\", \"Address\": \"$ALERT_EMAIL\"}]
    }
  ]"

echo "Done. Verify at: https://console.aws.amazon.com/billing/home#/budgets"
echo "NOTE: AWS Budgets checks spend ~once every 8 hours, not real-time."
echo "It will NOT stop a runaway process mid-spend — it's a smoke detector,"
echo "not a fire suppression system. Combine with the loop-iteration caps"
echo "in the agent code (Stage 2+) for actual runaway-cost prevention."
