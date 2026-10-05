from __future__ import annotations

import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Optional
from pathlib import Path


class AlertSeverity(str, Enum):
    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"


class AlertChannel(str, Enum):
    SLACK = "slack"
    PAGERDUTY = "pagerduty"
    EMAIL = "email"
    WEBHOOK = "webhook"


@dataclass(frozen=True, slots=True)
class AlertRule:
    name: str
    condition: str
    severity: AlertSeverity
    channels: list[AlertChannel]
    cooldown_seconds: int = 300
    description: str = ""


@dataclass(frozen=True, slots=True)
class MonitoringConfig:
    prometheus_url: str = "http://localhost:9090"
    grafana_url: str = "http://localhost:3000"
    alertmanager_url: str = "http://localhost:9093"
    scrape_interval_seconds: int = 15
    evaluation_interval_seconds: int = 15
    retention_days: int = 30

    # Key metrics to monitor
    latency_p50_threshold_ms: float = 100.0
    latency_p95_threshold_ms: float = 500.0
    latency_p99_threshold_ms: float = 1000.0
    error_rate_threshold: float = 0.01
    fill_rate_threshold: float = 0.95
    queue_depth_threshold: int = 1000
    risk_utilization_threshold: float = 0.85
    broker_api_latency_threshold_ms: float = 2000.0
    broker_rate_limit_remaining_threshold: int = 10


@dataclass(frozen=True, slots=True)
class BackupConfig:
    db_pitr_enabled: bool = True
    db_backup_retention_days: int = 30
    audit_log_replication_enabled: bool = True
    audit_log_s3_bucket: str = ""
    audit_log_glacier_vault: str = ""
    rto_seconds: int = 3600
    rpo_seconds: int = 300
    backup_schedule_cron: str = "0 2 * * *"
    verify_backups: bool = True


@dataclass(frozen=True, slots=True)
class SecurityConfig:
    mtls_enabled: bool = False
    mtls_ca_cert_path: str = ""
    mtls_cert_path: str = ""
    mtls_key_path: str = ""
    secrets_backend: str = "env"
    vault_addr: str = ""
    vault_token: str = ""
    sealed_secrets_enabled: bool = False
    dependency_scanning_enabled: bool = True
    trivy_severity_threshold: str = "HIGH"
    dependabot_enabled: bool = True
    pen_test_completed: bool = False
    pen_test_date: Optional[str] = None


@dataclass(frozen=True, slots=True)
class PrivacyLegalConfig:
    privacy_policy_url: str = ""
    terms_of_service_url: str = ""
    data_retention_days: int = 2555
    data_deletion_on_request: bool = True
    jurisdiction: str = "US"
    regulation_nms_compliance: bool = False
    best_execution_docs_url: str = ""
    cookies_consent: bool = False
    gdpr_compliance: bool = False
    ccpa_compliance: bool = False


@dataclass(frozen=True, slots=True)
class ProductionConfig:
    monitoring: MonitoringConfig = field(default_factory=MonitoringConfig)
    backup: BackupConfig = field(default_factory=BackupConfig)
    security: SecurityConfig = field(default_factory=SecurityConfig)
    privacy_legal: PrivacyLegalConfig = field(default_factory=PrivacyLegalConfig)

    environment: str = "production"
    log_level: str = "INFO"
    debug_mode: bool = False

    @classmethod
    def from_env(cls) -> "ProductionConfig":
        return cls(
            monitoring=MonitoringConfig(
                prometheus_url=os.getenv("PROMETHEUS_URL", "http://localhost:9090"),
                grafana_url=os.getenv("GRAFANA_URL", "http://localhost:3000"),
                alertmanager_url=os.getenv("ALERTMANAGER_URL", "http://localhost:9093"),
                scrape_interval_seconds=int(os.getenv("SCRAPE_INTERVAL", "15")),
                evaluation_interval_seconds=int(os.getenv("EVALUATION_INTERVAL", "15")),
                retention_days=int(os.getenv("METRICS_RETENTION_DAYS", "30")),
            ),
            backup=BackupConfig(
                db_pitr_enabled=os.getenv("DB_PITR_ENABLED", "true").lower() == "true",
                db_backup_retention_days=int(os.getenv("DB_BACKUP_RETENTION_DAYS", "30")),
                audit_log_replication_enabled=os.getenv("AUDIT_LOG_REPLICATION", "true").lower() == "true",
                audit_log_s3_bucket=os.getenv("AUDIT_LOG_S3_BUCKET", ""),
                audit_log_glacier_vault=os.getenv("AUDIT_LOG_GLACIER_VAULT", ""),
                rto_seconds=int(os.getenv("RTO_SECONDS", "3600")),
                rpo_seconds=int(os.getenv("RPO_SECONDS", "300")),
                backup_schedule_cron=os.getenv("BACKUP_SCHEDULE", "0 2 * * *"),
                verify_backups=os.getenv("VERIFY_BACKUPS", "true").lower() == "true",
            ),
            security=SecurityConfig(
                mtls_enabled=os.getenv("MTLS_ENABLED", "false").lower() == "true",
                mtls_ca_cert_path=os.getenv("MTLS_CA_CERT", ""),
                mtls_cert_path=os.getenv("MTLS_CERT", ""),
                mtls_key_path=os.getenv("MTLS_KEY", ""),
                secrets_backend=os.getenv("SECRETS_BACKEND", "env"),
                vault_addr=os.getenv("VAULT_ADDR", ""),
                vault_token=os.getenv("VAULT_TOKEN", ""),
                sealed_secrets_enabled=os.getenv("SEALED_SECRETS", "false").lower() == "true",
                dependency_scanning_enabled=os.getenv("DEPENDENCY_SCANNING", "true").lower() == "true",
                trivy_severity_threshold=os.getenv("TRIVY_THRESHOLD", "HIGH"),
                dependabot_enabled=os.getenv("DEPENDABOT_ENABLED", "true").lower() == "true",
                pen_test_completed=os.getenv("PEN_TEST_COMPLETED", "false").lower() == "true",
                pen_test_date=os.getenv("PEN_TEST_DATE"),
            ),
            privacy_legal=PrivacyLegalConfig(
                privacy_policy_url=os.getenv("PRIVACY_POLICY_URL", ""),
                terms_of_service_url=os.getenv("TERMS_OF_SERVICE_URL", ""),
                data_retention_days=int(os.getenv("DATA_RETENTION_DAYS", "2555")),
                data_deletion_on_request=os.getenv("DATA_DELETION_ON_REQUEST", "true").lower() == "true",
                jurisdiction=os.getenv("JURISDICTION", "US"),
                regulation_nms_compliance=os.getenv("REG_NMS_COMPLIANCE", "false").lower() == "true",
                best_execution_docs_url=os.getenv("BEST_EXECUTION_DOCS_URL", ""),
                cookies_consent=os.getenv("COOKIES_CONSENT", "false").lower() == "true",
                gdpr_compliance=os.getenv("GDPR_COMPLIANCE", "false").lower() == "true",
                ccpa_compliance=os.getenv("CCPA_COMPLIANCE", "false").lower() == "true",
            ),
            environment=os.getenv("ENVIRONMENT", "production"),
            log_level=os.getenv("LOG_LEVEL", "INFO"),
            debug_mode=os.getenv("DEBUG_MODE", "false").lower() == "true",
        )


DEFAULT_ALERT_RULES = [
    AlertRule(
        name="kill_switch_activated",
        condition="kill_switch_active == true",
        severity=AlertSeverity.CRITICAL,
        channels=[AlertChannel.PAGERDUTY, AlertChannel.SLACK],
        cooldown_seconds=60,
        description="Kill switch has been activated - all live trading halted",
    ),
    AlertRule(
        name="risk_breach_daily_loss",
        condition="daily_pnl_pct <= -3.0",
        severity=AlertSeverity.CRITICAL,
        channels=[AlertChannel.PAGERDUTY, AlertChannel.SLACK],
        cooldown_seconds=300,
        description="Daily loss limit breached",
    ),
    AlertRule(
        name="risk_breach_concentration",
        condition="concentration_pct >= 20.0",
        severity=AlertSeverity.WARNING,
        channels=[AlertChannel.SLACK],
        cooldown_seconds=600,
        description="Position concentration exceeds 20%",
    ),
    AlertRule(
        name="risk_breach_buying_power",
        condition="buying_power_used_pct >= 85.0",
        severity=AlertSeverity.WARNING,
        channels=[AlertChannel.SLACK],
        cooldown_seconds=600,
        description="Buying power utilization above 85%",
    ),
    AlertRule(
        name="reconciliation_drift_position",
        condition="position_drift_alerts > 0",
        severity=AlertSeverity.CRITICAL,
        channels=[AlertChannel.PAGERDUTY, AlertChannel.SLACK],
        cooldown_seconds=60,
        description="Position reconciliation drift detected",
    ),
    AlertRule(
        name="reconciliation_drift_equity",
        condition="equity_drift_alerts > 0",
        severity=AlertSeverity.CRITICAL,
        channels=[AlertChannel.PAGERDUTY, AlertChannel.SLACK],
        cooldown_seconds=60,
        description="Equity reconciliation drift detected",
    ),
    AlertRule(
        name="broker_api_down",
        condition="broker_api_health == false",
        severity=AlertSeverity.CRITICAL,
        channels=[AlertChannel.PAGERDUTY, AlertChannel.SLACK],
        cooldown_seconds=60,
        description="Broker API unreachable",
    ),
    AlertRule(
        name="broker_api_high_latency",
        condition="broker_latency_p99_ms > 2000",
        severity=AlertSeverity.WARNING,
        channels=[AlertChannel.SLACK],
        cooldown_seconds=300,
        description="Broker API latency above 2 seconds p99",
    ),
    AlertRule(
        name="broker_rate_limit_low",
        condition="broker_rate_limit_remaining < 10",
        severity=AlertSeverity.WARNING,
        channels=[AlertChannel.SLACK],
        cooldown_seconds=300,
        description="Broker rate limit running low",
    ),
    AlertRule(
        name="high_latency_p99",
        condition="latency_p99_ms > 1000",
        severity=AlertSeverity.WARNING,
        channels=[AlertChannel.SLACK],
        cooldown_seconds=300,
        description="API latency p99 above 1 second",
    ),
    AlertRule(
        name="high_error_rate",
        condition="error_rate > 0.01",
        severity=AlertSeverity.WARNING,
        channels=[AlertChannel.SLACK],
        cooldown_seconds=300,
        description="Error rate above 1%",
    ),
    AlertRule(
        name="low_fill_rate",
        condition="fill_rate < 0.95",
        severity=AlertSeverity.WARNING,
        channels=[AlertChannel.SLACK],
        cooldown_seconds=300,
        description="Fill rate below 95%",
    ),
]


def generate_prometheus_rules() -> str:
    """Generate Prometheus alerting rules YAML."""
    rules = []
    for rule in DEFAULT_ALERT_RULES:
        rule_yaml = f"""
  - alert: {rule.name}
    expr: {rule.condition}
    for: {rule.cooldown_seconds}s
    labels:
      severity: {rule.severity.value}
    annotations:
      summary: "{rule.name.replace('_', ' ').title()}"
      description: "{rule.description}"
      runbook: "docs/runbooks/{rule.name}.md"
"""
        rules.append(rule_yaml)

    return f"""groups:
- name: gateway_live_trading
  rules:
{''.join(rules)}
"""


def generate_grafana_dashboard() -> dict:
    """Generate Grafana dashboard JSON for live trading monitoring."""
    return {
        "dashboard": {
            "title": "Gateway Live Trading",
            "tags": ["gateway", "live", "trading"],
            "timezone": "utc",
            "panels": [
                {
                    "title": "Order Latency (p50/p95/p99)",
                    "type": "graph",
                    "targets": [
                        {"expr": "histogram_quantile(0.50, rate(gateway_order_latency_seconds_bucket[5m]))", "legendFormat": "p50"},
                        {"expr": "histogram_quantile(0.95, rate(gateway_order_latency_seconds_bucket[5m]))", "legendFormat": "p95"},
                        {"expr": "histogram_quantile(0.99, rate(gateway_order_latency_seconds_bucket[5m]))", "legendFormat": "p99"},
                    ],
                    "gridPos": {"x": 0, "y": 0, "w": 12, "h": 8},
                },
                {
                    "title": "Error Rate",
                    "type": "graph",
                    "targets": [
                        {"expr": "rate(gateway_errors_total[5m])", "legendFormat": "errors/sec"},
                    ],
                    "gridPos": {"x": 12, "y": 0, "w": 12, "h": 8},
                },
                {
                    "title": "Fill Rate",
                    "type": "graph",
                    "targets": [
                        {"expr": "gateway_fills_total / gateway_orders_total", "legendFormat": "fill_rate"},
                    ],
                    "gridPos": {"x": 0, "y": 8, "w": 12, "h": 8},
                },
                {
                    "title": "Queue Depth",
                    "type": "graph",
                    "targets": [
                        {"expr": "gateway_queue_depth", "legendFormat": "queue_depth"},
                    ],
                    "gridPos": {"x": 12, "y": 8, "w": 12, "h": 8},
                },
                {
                    "title": "Risk Utilization",
                    "type": "graph",
                    "targets": [
                        {"expr": "gateway_buying_power_used_pct / 100", "legendFormat": "buying_power_pct"},
                        {"expr": "gateway_concentration_pct / 100", "legendFormat": "concentration_pct"},
                        {"expr": "gateway_daily_pnl_pct / 100", "legendFormat": "daily_pnl_pct"},
                    ],
                    "gridPos": {"x": 0, "y": 16, "w": 12, "h": 8},
                },
                {
                    "title": "Broker API Health",
                    "type": "graph",
                    "targets": [
                        {"expr": "gateway_broker_latency_seconds", "legendFormat": "latency"},
                        {"expr": "gateway_broker_rate_limit_remaining", "legendFormat": "rate_limit_remaining"},
                    ],
                    "gridPos": {"x": 12, "y": 16, "w": 12, "h": 8},
                },
                {
                    "title": "Kill Switch Status",
                    "type": "stat",
                    "targets": [
                        {"expr": "gateway_kill_switch_active", "legendFormat": "active"},
                    ],
                    "gridPos": {"x": 0, "y": 24, "w": 6, "h": 4},
                },
                {
                    "title": "Open Orders / Positions",
                    "type": "stat",
                    "targets": [
                        {"expr": "gateway_open_orders", "legendFormat": "open_orders"},
                        {"expr": "gateway_positions_count", "legendFormat": "positions"},
                    ],
                    "gridPos": {"x": 6, "y": 24, "w": 6, "h": 4},
                },
                {
                    "title": "Equity / Cash / Buying Power",
                    "type": "graph",
                    "targets": [
                        {"expr": "gateway_equity", "legendFormat": "equity"},
                        {"expr": "gateway_cash", "legendFormat": "cash"},
                        {"expr": "gateway_buying_power", "legendFormat": "buying_power"},
                    ],
                    "gridPos": {"x": 12, "y": 24, "w": 12, "h": 8},
                },
            ],
        },
    }


def generate_docker_compose_monitoring() -> str:
    """Generate docker-compose for monitoring stack."""
    return """version: '3.8'

services:
  prometheus:
    image: prom/prometheus:v2.47.0
    ports:
      - "9090:9090"
    volumes:
      - ./prometheus.yml:/etc/prometheus/prometheus.yml
      - ./alerts.yml:/etc/prometheus/alerts.yml
      - prometheus_data:/prometheus
    command:
      - '--config.file=/etc/prometheus/prometheus.yml'
      - '--storage.tsdb.path=/prometheus'
      - '--storage.tsdb.retention.time=30d'
      - '--web.enable-lifecycle'

  alertmanager:
    image: prom/alertmanager:v0.26.0
    ports:
      - "9093:9093"
    volumes:
      - ./alertmanager.yml:/etc/alertmanager/alertmanager.yml
      - alertmanager_data:/alertmanager

  grafana:
    image: grafana/grafana:10.1.0
    ports:
      - "3000:3000"
    environment:
      - GF_SECURITY_ADMIN_USER=admin
      - GF_SECURITY_ADMIN_PASSWORD=${GRAFANA_PASSWORD}
      - GF_USERS_ALLOW_SIGN_UP=false
    volumes:
      - grafana_data:/var/lib/grafana
      - ./dashboards:/etc/grafana/provisioning/dashboards
      - ./datasources.yml:/etc/grafana/provisioning/datasources/datasources.yml

  node-exporter:
    image: prom/node-exporter:v1.6.1
    ports:
      - "9100:9100"
    volumes:
      - /proc:/host/proc:ro
      - /sys:/host/sys:ro
      - /:/rootfs:ro

volumes:
  prometheus_data:
  alertmanager_data:
  grafana_data:
"""


def generate_prometheus_config() -> str:
    return """global:
  scrape_interval: 15s
  evaluation_interval: 15s

alerting:
  alertmanagers:
    - static_configs:
        - targets:
          - alertmanager:9093

rule_files:
  - "alerts.yml"

scrape_configs:
  - job_name: 'gateway'
    static_configs:
      - targets: ['gateway:8000']
    metrics_path: '/metrics'

  - job_name: 'prometheus'
    static_configs:
      - targets: ['localhost:9090']

  - job_name: 'node-exporter'
    static_configs:
      - targets: ['node-exporter:9100']
"""


def generate_alertmanager_config() -> str:
    return """global:
  resolve_timeout: 5m

route:
  group_by: ['alertname']
  group_wait: 10s
  group_interval: 10s
  repeat_interval: 1h
  receiver: 'default'

receivers:
  - name: 'default'
    slack_configs:
      - api_url: '${SLACK_WEBHOOK_URL}'
        channel: '#gateway-alerts'
        title: 'Gateway Alert: {{ .GroupLabels.alertname }}'
        text: '{{ range .Alerts }}{{ .Annotations.summary }}{{ end }}'
    pagerduty_configs:
      - service_key: '${PAGERDUTY_KEY}'
        severity: '{{ .Labels.severity }}'
        description: '{{ .Annotations.summary }}'

inhibit_rules:
  - source_match:
      severity: 'critical'
    target_match:
      severity: 'warning'
    equal: ['alertname']
"""


def generate_runbooks() -> dict[str, str]:
    """Generate incident runbooks as markdown."""
    return {
        "broker_disconnect.md": """# Broker Disconnect Runbook

## Symptoms
- Broker API health check failing
- Orders timing out or returning connection errors
- `broker_api_health` metric = false

## Immediate Actions
1. Check broker status page (status.alpaca.markets)
2. Verify network connectivity from gateway to broker
3. Check API credentials haven't rotated
4. Review broker rate limit status

## Escalation
- If broker reports outage: activate kill switch, notify users
- If network issue: engage infrastructure team
- If credential issue: rotate and redeploy

## Recovery
1. Wait for broker to restore service
2. Verify API connectivity restored
3. Run reconciliation job to sync state
4. Deactivate kill switch if manually activated
5. Resume normal trading
""",
        "risk_breach.md": """# Risk Breach Runbook

## Types of Risk Breaches
1. **Daily Loss Limit**: Portfolio P&L exceeds configured threshold
2. **Concentration Limit**: Single position exceeds max concentration
3. **Buying Power**: Utilization exceeds threshold
4. **Exposure Limits**: Gross/net exposure breached

## Immediate Actions
1. Kill switch auto-activates on daily loss limit
2. New orders blocked by risk engine
3. Alert fires to PagerDuty/Slack

## Investigation
1. Identify which risk limit was breached
2. Check if breach is due to market move or new position
3. Review recent fills and position changes

## Resolution
- For market-move breaches: wait for recovery or reduce positions
- For new-position breaches: reject or reduce order size
- Document incident and update risk parameters if needed

## Recovery
1. Verify risk metrics back within limits
2. Deactivate kill switch (if daily loss was cause)
3. Resume trading with adjusted limits if needed
""",
        "reconciliation_drift.md": """# Reconciliation Drift Runbook

## Symptoms
- Position drift alert: local position ≠ broker position (>1 share)
- Equity drift alert: local equity ≠ broker equity (>10 bps)

## Immediate Actions
1. Pause new order submission
2. Run manual reconciliation: `POST /api/v1/live/reconcile/run`
3. Review drift details in alert

## Investigation
1. Identify affected symbols
2. Check for missed fills, partial fills, or corporate actions
3. Compare local fills vs broker activities
4. Check for timestamp mismatches

## Resolution
1. If missed fill: replay from audit log, update local state
2. If corporate action: adjust positions per broker
3. If timestamp issue: correct and re-reconcile
4. If bug: fix root cause, replay affected events

## Recovery
1. Verify reconciliation clean (0 alerts)
2. Resume normal trading
3. Document root cause and prevention
""",
        "data_feed_failure.md": """# Data Feed Failure Runbook

## Symptoms
- Market data feed stopped updating
- Stale quotes in risk engine
- Fill simulator using stale prices

## Immediate Actions
1. Check data provider status (Alpaca, Finnhub, etc.)
2. Verify WebSocket connections healthy
3. Check for rate limiting on data APIs

## Investigation
1. Identify which feed(s) affected
2. Check gateway logs for connection errors
3. Verify fallback feeds operational

## Resolution
1. Restart data feed connections
2. Switch to backup provider if available
3. Alert users of potential stale data

## Recovery
1. Verify real-time data flowing
2. Re-sync any missed candles
3. Resume normal operations
""",
    }


def generate_env_template() -> str:
    """Generate .env.template for production."""
    return """# Gateway Production Environment Variables

# --- Environment ---
ENVIRONMENT=production
LOG_LEVEL=INFO
DEBUG_MODE=false

# --- Alpaca Live Trading ---
ALPACA_API_KEY=your_live_api_key
ALPACA_API_SECRET=your_live_api_secret
ALPACA_BASE_URL=https://api.alpaca.markets
ALPACA_PAPER=false

# --- Database ---
DATABASE_URL=postgresql://user:pass@host:5432/gateway
DB_PITR_ENABLED=true
DB_BACKUP_RETENTION_DAYS=30

# --- Monitoring ---
PROMETHEUS_URL=http://prometheus:9090
GRAFANA_URL=http://grafana:3000
ALERTMANAGER_URL=http://alertmanager:9093
SCRAPE_INTERVAL=15
EVALUATION_INTERVAL=15
METRICS_RETENTION_DAYS=30

# --- Alerting ---
SLACK_WEBHOOK_URL=https://hooks.slack.com/services/xxx
PAGERDUTY_KEY=your_pagerduty_integration_key

# --- Backup ---
AUDIT_LOG_REPLICATION=true
AUDIT_LOG_S3_BUCKET=gateway-audit-logs-prod
AUDIT_LOG_GLACIER_VAULT=gateway-audit-archive
RTO_SECONDS=3600
RPO_SECONDS=300
BACKUP_SCHEDULE="0 2 * * *"
VERIFY_BACKUPS=true

# --- Security ---
MTLS_ENABLED=false
MTLS_CA_CERT=/etc/certs/ca.pem
MTLS_CERT=/etc/certs/server.pem
MTLS_KEY=/etc/certs/server.key
SECRETS_BACKEND=vault
VAULT_ADDR=https://vault.example.com
VAULT_TOKEN=your_vault_token
SEALED_SECRETS=true
DEPENDENCY_SCANNING=true
TRIVY_THRESHOLD=HIGH
DEPENDABOT_ENABLED=true
PEN_TEST_COMPLETED=false
PEN_TEST_DATE=2024-01-15

# --- Privacy/Legal ---
PRIVACY_POLICY_URL=https://gateway.example.com/privacy
TERMS_OF_SERVICE_URL=https://gateway.example.com/terms
DATA_RETENTION_DAYS=2555
DATA_DELETION_ON_REQUEST=true
JURISDICTION=US
REG_NMS_COMPLIANCE=false
BEST_EXECUTION_DOCS_URL=https://gateway.example.com/best-execution
COOKIES_CONSENT=false
GDPR_COMPLIANCE=false
CCPA_COMPLIANCE=false
"""


_production_config: ProductionConfig | None = None


def get_production_config() -> ProductionConfig:
    global _production_config
    if _production_config is None:
        _production_config = ProductionConfig.from_env()
    return _production_config


def validate_production_readiness() -> dict:
    """Validate all production readiness checks."""
    config = get_production_config()
    checks = {
        "monitoring": {
            "prometheus_configured": bool(config.monitoring.prometheus_url),
            "grafana_configured": bool(config.monitoring.grafana_url),
            "alertmanager_configured": bool(config.monitoring.alertmanager_url),
        },
        "backup": {
            "db_pitr_enabled": config.backup.db_pitr_enabled,
            "audit_log_replication": config.backup.audit_log_replication_enabled,
            "s3_bucket_configured": bool(config.backup.audit_log_s3_bucket),
            "rto_rpo_documented": config.backup.rto_seconds > 0 and config.backup.rpo_seconds > 0,
        },
        "security": {
            "secrets_not_in_env": config.security.secrets_backend != "env",
            "vault_configured": bool(config.security.vault_addr),
            "dependency_scanning": config.security.dependency_scanning_enabled,
            "pen_test_completed": config.security.pen_test_completed,
        },
        "privacy_legal": {
            "privacy_policy": bool(config.privacy_legal.privacy_policy_url),
            "terms_of_service": bool(config.privacy_legal.terms_of_service_url),
            "data_retention_defined": config.privacy_legal.data_retention_days > 0,
        },
    }

    all_passed = all(
        all(v for v in category.values())
        for category in checks.values()
    )

    return {
        "ready": all_passed,
        "checks": checks,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }