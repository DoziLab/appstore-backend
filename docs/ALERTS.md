# Example Alert Rules for Grafana

This file contains example alert configurations that can be imported into Grafana.

## Alert: High Error Rate

**Condition**: More than 10 errors per minute

**Query**:
```logql
sum(rate({job="api"} | json | level="ERROR" [1m]))
```

**Threshold**: > 10

**Duration**: 5 minutes

**Severity**: Critical

**Action**: 
- Send notification to operations team
- Check error logs in Grafana
- Investigate root cause

---

## Alert: Slow API Responses

**Condition**: 95th percentile response time > 2000ms

**Query**:
```logql
quantile_over_time(0.95, {job="api"} | json | duration_ms != "" | unwrap duration_ms [5m])
```

**Threshold**: > 2000

**Duration**: 10 minutes

**Severity**: Warning

**Action**:
- Review slow endpoints in dashboard
- Check database query performance
- Consider scaling resources

---

## Alert: Authentication Failures Spike

**Condition**: More than 5 authentication failures per minute

**Query**:
```logql
sum(rate({job="api"} | json | event="authentication_failed" [1m]))
```

**Threshold**: > 5

**Duration**: 3 minutes

**Severity**: Warning

**Action**:
- Check for brute force attack
- Review failed login IPs
- Consider rate limiting

---

## Alert: OpenStack API Failures

**Condition**: Any OpenStack API call failure

**Query**:
```logql
count_over_time({job="api"} | json | event=~"openstack_.*_failed" [5m])
```

**Threshold**: > 0

**Duration**: 5 minutes

**Severity**: High

**Action**:
- Check OpenStack service status
- Review error messages
- Verify credentials and connectivity

---

## Alert: Deployment Failures

**Condition**: More than 3 deployment failures in 10 minutes

**Query**:
```logql
sum(count_over_time({job="api"} | json | event="deployment_create_failed" [10m]))
```

**Threshold**: > 3

**Duration**: Immediate

**Severity**: High

**Action**:
- Check deployment logs
- Review template configurations
- Verify OpenStack quota

---

## Alert: Celery Worker Down

**Condition**: No Celery worker logs in last 5 minutes

**Query**:
```logql
count_over_time({job="celery-worker"} [5m])
```

**Threshold**: == 0

**Duration**: 5 minutes

**Severity**: Critical

**Action**:
- Restart Celery worker
- Check Redis connectivity
- Review worker logs

---

## Alert: Database Connection Issues

**Condition**: Database connection errors detected

**Query**:
```logql
count_over_time({job="api"} | json | event="db_connection_error" [5m])
```

**Threshold**: > 0

**Duration**: Immediate

**Severity**: Critical

**Action**:
- Check PostgreSQL status
- Verify database credentials
- Review connection pool settings

---

## Alert: High Request Rate (DoS Protection)

**Condition**: More than 1000 requests per minute

**Query**:
```logql
sum(rate({job="api"} | json | event="request_started" [1m]))
```

**Threshold**: > 1000

**Duration**: 2 minutes

**Severity**: Warning

**Action**:
- Check if legitimate traffic or attack
- Consider enabling rate limiting
- Review client IPs

---

## How to Configure Alerts in Grafana

### Option 1: Using the UI

1. Open the dashboard panel you want to alert on
2. Click **Edit** → **Alert** tab
3. Click **Create alert rule from this panel**
4. Configure:
   - Query: (already set from panel)
   - Condition: Set threshold
   - Evaluate every: `1m`
   - For: `5m` (duration)
5. Add notification channel
6. Save

### Option 2: Using Alert Rules File

Create `config/grafana/provisioning/alerting/alerts.yml`:

```yaml
apiVersion: 1

groups:
  - name: api_alerts
    folder: App Store
    interval: 1m
    rules:
      - uid: high_error_rate
        title: High Error Rate
        condition: A
        data:
          - refId: A
            datasourceUid: loki
            model:
              expr: 'sum(rate({job="api"} | json | level="ERROR" [1m]))'
        for: 5m
        annotations:
          description: 'Error rate is {{ $value }} errors/min'
          summary: 'High error rate detected'
        labels:
          severity: critical
```

### Option 3: Using Terraform (Production)

```hcl
resource "grafana_alert_rule" "high_error_rate" {
  folder_uid      = grafana_folder.app_store.uid
  name            = "High Error Rate"
  interval_seconds = 60

  condition = "A"
  
  data {
    ref_id = "A"
    datasource_uid = grafana_data_source.loki.uid
    
    model = jsonencode({
      expr = "sum(rate({job=\"api\"} | json | level=\"ERROR\" [1m]))"
    })
  }
  
  for = "5m"
  
  annotations = {
    description = "Error rate is {{ $value }} errors/min"
    summary     = "High error rate detected"
  }
  
  labels = {
    severity = "critical"
  }
}
```

## Notification Channels

Configure notification channels in Grafana:

### Email
Settings → Alerting → Contact points → New contact point
- Type: Email
- Addresses: ops-team@example.com

### Slack
- Type: Slack
- Webhook URL: https://hooks.slack.com/services/...
- Channel: #alerts

### PagerDuty
- Type: PagerDuty
- Integration Key: (from PagerDuty)

## Testing Alerts

Generate test conditions:

```bash
# Generate errors
for i in {1..20}; do
  curl http://localhost:8000/api/deployments/invalid-id
  sleep 1
done

# Generate slow requests
curl "http://localhost:8000/api/deployments?sleep=3000"

# Generate high load
for i in {1..100}; do
  curl http://localhost:8000/health &
done
wait
```

## Best Practices

1. **Start conservative**: Set thresholds higher, then tune down
2. **Avoid alert fatigue**: Don't alert on every issue
3. **Document response**: Each alert should have clear action items
4. **Test regularly**: Ensure alerts fire correctly
5. **Group related alerts**: Prevent notification spam
6. **Set appropriate severity**:
   - Info: Informational only
   - Warning: Should investigate soon
   - High: Investigate now
   - Critical: Wake someone up
