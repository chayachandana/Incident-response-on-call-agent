# Runbook: High Error Rate (General)

## Symptoms
- HTTP 5xx error rate above threshold
- Upstream services receiving errors
- User-facing impact possible

## Immediate Steps
1. Check deployment history for recent changes:
   kubectl rollout history deployment/<service>
2. Review error logs for common pattern
3. Check upstream dependencies health
4. Assess if rollback is safe

## Decision Tree
- Errors started after deployment → rollback_deployment()
- Errors correlate with traffic spike → scale_pods()
- Errors correlate with DB issues → check db_connection_pool runbook
- Errors correlate with Redis issues → check redis_connection_failure runbook
- Errors random / no clear pattern → page oncall for manual investigation

## Auto-Remediation Steps
- rollback_deployment() — if recent deployment is suspected
- scale_pods() — if traffic spike
- restart_service() — if memory leak suspected

## Escalation
Page: team owning the affected service