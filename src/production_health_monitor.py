"""
Production Health Monitor - Continuous monitoring for go-live readiness

Monitors for critical issues that would cause losses in production:
1. Immediate closure rate (risk cap conflicts between Alpha/Beta)
2. File corruption (JSON parse errors)
3. Cross-bot exposure conflicts
4. P&L degradation trends
5. Signal logging failures
6. Learning data staleness

Runs continuously and triggers alerts when thresholds are breached.
"""
import json
import os
import time
import threading
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, field, asdict
import pytz

ARIZONA_TZ = pytz.timezone('America/Phoenix')

POSITIONS_FILE = "logs/positions_futures.json"
HEALTH_LOG_FILE = "logs/production_health.jsonl"
HEALTH_STATE_FILE = "logs/production_health_state.json"
ENRICHED_DECISIONS_FILE = "logs/enriched_decisions.jsonl"
SIGNAL_UNIVERSE_FILE = "logs/signal_universe.jsonl"
SIGNAL_ACTIVITY_FILE = "logs/signal_activity.json"

@dataclass
class HealthAlert:
    """Single health alert"""
    severity: str  # CRITICAL, WARNING, INFO
    category: str  # immediate_closure, file_corruption, exposure_conflict, pnl_degradation, data_staleness
    message: str
    details: Dict = field(default_factory=dict)
    timestamp: str = ""
    
    def __post_init__(self):
        if not self.timestamp:
            self.timestamp = datetime.now(ARIZONA_TZ).isoformat()


@dataclass
class HealthCheckResult:
    """Result of a health check"""
    check_name: str
    passed: bool
    severity: str  # OK, WARNING, CRITICAL
    message: str
    details: Dict = field(default_factory=dict)
    timestamp: str = ""
    
    def __post_init__(self):
        if not self.timestamp:
            self.timestamp = datetime.now(ARIZONA_TZ).isoformat()


@dataclass
class HealthThresholds:
    """Configurable thresholds for health checks"""
    immediate_closure_rate_warning: float = 0.10  # 10% warning
    immediate_closure_rate_critical: float = 0.25  # 25% critical
    
    pnl_hourly_loss_warning: float = 50.0  # $50/hour warning
    pnl_hourly_loss_critical: float = 100.0  # $100/hour critical
    
    data_staleness_hours_warning: int = 6  # 6 hours stale warning
    data_staleness_hours_critical: int = 24  # 24 hours stale critical
    
    min_valid_trades_per_hour: int = 1  # Minimum trades to validate rates
    
    exposure_per_asset_cap: float = 0.25  # 25% max per asset
    max_positions_per_bot: int = 10  # Max 10 positions per bot
    
    check_interval_seconds: int = 300  # Run checks every 5 minutes


class ProductionHealthMonitor:
    """
    Continuous health monitoring for production readiness.
    
    Catches issues like:
    - Risk cap conflicts causing immediate closures
    - File corruption from concurrent writes
    - Data staleness in learning files
    - P&L degradation trends
    """
    
    def __init__(self, thresholds: Optional[HealthThresholds] = None):
        self.thresholds = thresholds or HealthThresholds()
        self.alerts: List[HealthAlert] = []
        self.check_results: List[HealthCheckResult] = []
        self.running = False
        self._thread: Optional[threading.Thread] = None
        self._lock = threading.Lock()
        
        Path("logs").mkdir(exist_ok=True)
        self._load_state()
    
    def _load_state(self):
        """Load previous health state"""
        try:
            if os.path.exists(HEALTH_STATE_FILE):
                with open(HEALTH_STATE_FILE, 'r') as f:
                    state = json.load(f)
                self.last_check_ts = state.get('last_check_ts', 0)
                self.consecutive_failures = state.get('consecutive_failures', 0)
                self.last_email_sent_at_failures = state.get('last_email_sent_at_failures', 0)
            else:
                self.last_check_ts = 0
                self.consecutive_failures = 0
                self.last_email_sent_at_failures = 0
        except:
            self.last_check_ts = 0
            self.consecutive_failures = 0
            self.last_email_sent_at_failures = 0
    
    def _save_state(self):
        """Persist health state"""
        state = {
            'last_check_ts': time.time(),
            'consecutive_failures': self.consecutive_failures,
            'last_email_sent_at_failures': getattr(self, 'last_email_sent_at_failures', 0),
            'last_updated': datetime.now(ARIZONA_TZ).isoformat()
        }
        try:
            with open(HEALTH_STATE_FILE, 'w') as f:
                json.dump(state, f, indent=2)
        except:
            pass
    
    def _log_result(self, result: HealthCheckResult):
        """Log health check result to JSONL"""
        try:
            with open(HEALTH_LOG_FILE, 'a') as f:
                f.write(json.dumps(asdict(result)) + '\n')
        except:
            pass
    
    def _add_alert(self, alert: HealthAlert):
        """Add alert to queue and log it"""
        with self._lock:
            self.alerts.append(alert)
            if len(self.alerts) > 100:
                self.alerts = self.alerts[-100:]
        
        try:
            with open(HEALTH_LOG_FILE, 'a') as f:
                f.write(json.dumps({"type": "alert", **asdict(alert)}) + '\n')
        except:
            pass
        
        prefix = "🚨" if alert.severity == "CRITICAL" else "⚠️" if alert.severity == "WARNING" else "ℹ️"
        print(f"{prefix} HEALTH-MONITOR [{alert.category}] {alert.message}")
    
    def check_immediate_closure_rate(self) -> HealthCheckResult:
        """
        Check for high immediate closure rate (entry=exit price).
        This indicates risk cap conflicts between Alpha and Beta.
        """
        try:
            with open(POSITIONS_FILE, 'r') as f:
                data = json.load(f)
            
            closed = data.get('closed_positions', [])
            
            one_hour_ago = time.time() - 3600
            recent = [p for p in closed if p.get('closed_at_ts', 0) > one_hour_ago]
            
            if len(recent) < self.thresholds.min_valid_trades_per_hour:
                return HealthCheckResult(
                    check_name="immediate_closure_rate",
                    passed=True,
                    severity="OK",
                    message=f"Insufficient recent trades ({len(recent)}) for analysis",
                    details={"recent_count": len(recent)}
                )
            
            immediate_closures = 0
            for p in recent:
                entry = p.get('entry_price', 0)
                exit_p = p.get('exit_price', 0)
                if entry > 0 and abs(entry - exit_p) < 0.0001:
                    immediate_closures += 1
            
            rate = immediate_closures / len(recent) if recent else 0
            
            if rate >= self.thresholds.immediate_closure_rate_critical:
                self._add_alert(HealthAlert(
                    severity="CRITICAL",
                    category="immediate_closure",
                    message=f"Immediate closure rate {rate*100:.1f}% exceeds critical threshold ({self.thresholds.immediate_closure_rate_critical*100}%)",
                    details={
                        "rate": rate,
                        "immediate_closures": immediate_closures,
                        "total_recent": len(recent),
                        "threshold": self.thresholds.immediate_closure_rate_critical
                    }
                ))
                return HealthCheckResult(
                    check_name="immediate_closure_rate",
                    passed=False,
                    severity="CRITICAL",
                    message=f"Immediate closure rate {rate*100:.1f}% is critically high",
                    details={"rate": rate, "immediate": immediate_closures, "total": len(recent)}
                )
            
            elif rate >= self.thresholds.immediate_closure_rate_warning:
                self._add_alert(HealthAlert(
                    severity="WARNING",
                    category="immediate_closure",
                    message=f"Immediate closure rate {rate*100:.1f}% elevated",
                    details={"rate": rate}
                ))
                return HealthCheckResult(
                    check_name="immediate_closure_rate",
                    passed=True,
                    severity="WARNING",
                    message=f"Immediate closure rate {rate*100:.1f}% is elevated",
                    details={"rate": rate, "immediate": immediate_closures, "total": len(recent)}
                )
            
            return HealthCheckResult(
                check_name="immediate_closure_rate",
                passed=True,
                severity="OK",
                message=f"Immediate closure rate {rate*100:.1f}% is healthy",
                details={"rate": rate, "immediate": immediate_closures, "total": len(recent)}
            )
            
        except Exception as e:
            return HealthCheckResult(
                check_name="immediate_closure_rate",
                passed=False,
                severity="CRITICAL",
                message=f"Failed to check immediate closure rate: {e}"
            )
    
    def check_file_integrity(self) -> HealthCheckResult:
        """
        Check that critical JSON files are readable and not corrupted.
        """
        critical_files = [
            POSITIONS_FILE,
            "logs/portfolio_futures.json",
            "feature_store/daily_learning_rules.json",
            SIGNAL_ACTIVITY_FILE
        ]
        
        errors = []
        for fpath in critical_files:
            if not os.path.exists(fpath):
                continue
            
            try:
                with open(fpath, 'r') as f:
                    content = f.read()
                    if content.strip():
                        json.loads(content)
            except json.JSONDecodeError as e:
                errors.append(f"{fpath}: JSON parse error - {e}")
            except Exception as e:
                errors.append(f"{fpath}: Read error - {e}")
        
        if errors:
            self._add_alert(HealthAlert(
                severity="CRITICAL",
                category="file_corruption",
                message=f"File corruption detected in {len(errors)} files",
                details={"errors": errors}
            ))
            return HealthCheckResult(
                check_name="file_integrity",
                passed=False,
                severity="CRITICAL",
                message=f"File corruption in {len(errors)} files",
                details={"errors": errors}
            )
        
        return HealthCheckResult(
            check_name="file_integrity",
            passed=True,
            severity="OK",
            message="All critical files are readable"
        )
    
    def check_risk_cap_isolation(self) -> HealthCheckResult:
        """
        Verify Alpha and Beta portfolios are calculated separately for risk caps.
        Detects if both bots have positions in the same asset exceeding limits.
        """
        try:
            with open(POSITIONS_FILE, 'r') as f:
                data = json.load(f)
            
            open_pos = data.get('open_positions', [])
            
            alpha_positions = {}
            beta_positions = {}
            
            for p in open_pos:
                symbol = p.get('symbol')
                bot_type = p.get('bot_type', 'alpha')
                margin = p.get('margin', p.get('size', 0)) or 0
                
                if bot_type == 'alpha':
                    alpha_positions[symbol] = alpha_positions.get(symbol, 0) + margin
                else:
                    beta_positions[symbol] = beta_positions.get(symbol, 0) + margin
            
            conflicts = []
            for symbol in set(alpha_positions.keys()) & set(beta_positions.keys()):
                alpha_exp = alpha_positions[symbol]
                beta_exp = beta_positions[symbol]
                conflicts.append({
                    "symbol": symbol,
                    "alpha_exposure": alpha_exp,
                    "beta_exposure": beta_exp
                })
            
            alpha_count = len([p for p in open_pos if p.get('bot_type', 'alpha') == 'alpha'])
            beta_count = len([p for p in open_pos if p.get('bot_type') == 'beta'])
            
            issues = []
            if alpha_count > self.thresholds.max_positions_per_bot:
                issues.append(f"Alpha has {alpha_count} positions (max {self.thresholds.max_positions_per_bot})")
            if beta_count > self.thresholds.max_positions_per_bot:
                issues.append(f"Beta has {beta_count} positions (max {self.thresholds.max_positions_per_bot})")
            
            if issues:
                self._add_alert(HealthAlert(
                    severity="WARNING",
                    category="exposure_conflict",
                    message=f"Position count issues: {'; '.join(issues)}",
                    details={"alpha_count": alpha_count, "beta_count": beta_count}
                ))
            
            return HealthCheckResult(
                check_name="risk_cap_isolation",
                passed=len(issues) == 0,
                severity="WARNING" if issues else "OK",
                message=f"Alpha: {alpha_count} pos, Beta: {beta_count} pos, {len(conflicts)} shared assets",
                details={
                    "alpha_count": alpha_count,
                    "beta_count": beta_count,
                    "shared_assets": conflicts,
                    "issues": issues
                }
            )
            
        except Exception as e:
            return HealthCheckResult(
                check_name="risk_cap_isolation",
                passed=False,
                severity="CRITICAL",
                message=f"Failed to check risk cap isolation: {e}"
            )
    
    def check_pnl_trend(self) -> HealthCheckResult:
        """
        Check P&L trend for degradation.
        Alerts if hourly loss exceeds thresholds.
        """
        try:
            with open(POSITIONS_FILE, 'r') as f:
                data = json.load(f)
            
            closed = data.get('closed_positions', [])
            
            one_hour_ago = time.time() - 3600
            recent = [p for p in closed if p.get('closed_at_ts', 0) > one_hour_ago]
            
            if len(recent) < 3:
                return HealthCheckResult(
                    check_name="pnl_trend",
                    passed=True,
                    severity="OK",
                    message=f"Insufficient recent trades ({len(recent)}) for P&L trend analysis"
                )
            
            hourly_pnl = sum(p.get('net_pnl', p.get('pnl', 0)) or 0 for p in recent)
            
            alpha_pnl = sum(p.get('net_pnl', 0) or 0 for p in recent if p.get('bot_type', 'alpha') == 'alpha')
            beta_pnl = sum(p.get('net_pnl', 0) or 0 for p in recent if p.get('bot_type') == 'beta')
            
            if hourly_pnl < -self.thresholds.pnl_hourly_loss_critical:
                self._add_alert(HealthAlert(
                    severity="CRITICAL",
                    category="pnl_degradation",
                    message=f"Hourly loss ${abs(hourly_pnl):.2f} exceeds critical threshold",
                    details={
                        "hourly_pnl": hourly_pnl,
                        "alpha_pnl": alpha_pnl,
                        "beta_pnl": beta_pnl,
                        "trade_count": len(recent)
                    }
                ))
                return HealthCheckResult(
                    check_name="pnl_trend",
                    passed=False,
                    severity="CRITICAL",
                    message=f"Hourly P&L ${hourly_pnl:.2f} (Alpha: ${alpha_pnl:.2f}, Beta: ${beta_pnl:.2f})"
                )
            
            elif hourly_pnl < -self.thresholds.pnl_hourly_loss_warning:
                self._add_alert(HealthAlert(
                    severity="WARNING",
                    category="pnl_degradation",
                    message=f"Hourly loss ${abs(hourly_pnl):.2f} elevated",
                    details={"hourly_pnl": hourly_pnl}
                ))
                return HealthCheckResult(
                    check_name="pnl_trend",
                    passed=True,
                    severity="WARNING",
                    message=f"Hourly P&L ${hourly_pnl:.2f} - elevated loss"
                )
            
            return HealthCheckResult(
                check_name="pnl_trend",
                passed=True,
                severity="OK",
                message=f"Hourly P&L ${hourly_pnl:.2f} (Alpha: ${alpha_pnl:.2f}, Beta: ${beta_pnl:.2f})"
            )
            
        except Exception as e:
            return HealthCheckResult(
                check_name="pnl_trend",
                passed=False,
                severity="CRITICAL",
                message=f"Failed to check P&L trend: {e}"
            )
    
    def check_data_staleness(self) -> HealthCheckResult:
        """
        Check that learning data files are being updated regularly.
        """
        stale_files = []
        now = time.time()
        
        files_to_check = [
            (ENRICHED_DECISIONS_FILE, "Enriched Decisions", self.thresholds.data_staleness_hours_warning * 3600),
            (SIGNAL_ACTIVITY_FILE, "Signal Activity", 3600),  # Should update every hour
            ("feature_store/daily_learning_rules.json", "Daily Rules", self.thresholds.data_staleness_hours_warning * 3600)
        ]
        
        for fpath, name, max_age in files_to_check:
            if not os.path.exists(fpath):
                stale_files.append(f"{name}: MISSING")
                continue
            
            mtime = os.path.getmtime(fpath)
            age_hours = (now - mtime) / 3600
            
            if now - mtime > max_age:
                stale_files.append(f"{name}: {age_hours:.1f}h old")
        
        if stale_files:
            severity = "CRITICAL" if any("MISSING" in f for f in stale_files) else "WARNING"
            self._add_alert(HealthAlert(
                severity=severity,
                category="data_staleness",
                message=f"Stale/missing data files: {', '.join(stale_files)}",
                details={"stale_files": stale_files}
            ))
            return HealthCheckResult(
                check_name="data_staleness",
                passed=severity != "CRITICAL",
                severity=severity,
                message=f"Data staleness issues: {len(stale_files)} files",
                details={"stale_files": stale_files}
            )
        
        return HealthCheckResult(
            check_name="data_staleness",
            passed=True,
            severity="OK",
            message="All learning data files are fresh"
        )
    
    def check_close_reason_distribution(self) -> HealthCheckResult:
        """
        Analyze close reasons for anomalies.
        High risk_cap closures indicate configuration issues.
        """
        try:
            with open(POSITIONS_FILE, 'r') as f:
                data = json.load(f)
            
            closed = data.get('closed_positions', [])
            
            one_hour_ago = time.time() - 3600
            recent = [p for p in closed if p.get('closed_at_ts', 0) > one_hour_ago]
            
            if len(recent) < 5:
                return HealthCheckResult(
                    check_name="close_reason_distribution",
                    passed=True,
                    severity="OK",
                    message=f"Insufficient recent trades ({len(recent)}) for reason analysis"
                )
            
            reasons = {}
            for p in recent:
                reason = p.get('reason', p.get('close_reason', 'unknown'))
                reasons[reason] = reasons.get(reason, 0) + 1
            
            risk_cap_closures = reasons.get('risk_cap_asset_exposure', 0) + reasons.get('risk_cap_max_positions', 0)
            risk_cap_rate = risk_cap_closures / len(recent) if recent else 0
            
            if risk_cap_rate > 0.5:
                self._add_alert(HealthAlert(
                    severity="CRITICAL",
                    category="close_reason_anomaly",
                    message=f"Risk cap closures at {risk_cap_rate*100:.1f}% of all closes",
                    details={"reasons": reasons, "risk_cap_closures": risk_cap_closures}
                ))
                return HealthCheckResult(
                    check_name="close_reason_distribution",
                    passed=False,
                    severity="CRITICAL",
                    message=f"Risk cap forcing {risk_cap_rate*100:.1f}% of closures"
                )
            
            return HealthCheckResult(
                check_name="close_reason_distribution",
                passed=True,
                severity="OK",
                message=f"Close reasons healthy: {len(reasons)} types",
                details={"reasons": reasons}
            )
            
        except Exception as e:
            return HealthCheckResult(
                check_name="close_reason_distribution",
                passed=False,
                severity="WARNING",
                message=f"Failed to analyze close reasons: {e}"
            )
    
    def run_all_checks(self) -> Dict:
        """
        Run all health checks and return consolidated report.
        """
        checks = [
            self.check_immediate_closure_rate,
            self.check_file_integrity,
            self.check_risk_cap_isolation,
            self.check_pnl_trend,
            self.check_data_staleness,
            self.check_close_reason_distribution
        ]
        
        results = []
        critical_count = 0
        warning_count = 0
        
        for check_func in checks:
            try:
                result = check_func()
                results.append(result)
                self._log_result(result)
                
                if result.severity == "CRITICAL":
                    critical_count += 1
                elif result.severity == "WARNING":
                    warning_count += 1
                    
            except Exception as e:
                result = HealthCheckResult(
                    check_name=check_func.__name__,
                    passed=False,
                    severity="CRITICAL",
                    message=f"Check crashed: {e}"
                )
                results.append(result)
                critical_count += 1
        
        if critical_count > 0:
            overall_status = "CRITICAL"
            self.consecutive_failures += 1
        elif warning_count > 0:
            overall_status = "WARNING"
            self.consecutive_failures = 0
        else:
            overall_status = "HEALTHY"
            self.consecutive_failures = 0
        
        self._save_state()
        
        report = {
            "timestamp": datetime.now(ARIZONA_TZ).isoformat(),
            "status": overall_status,
            "critical_count": critical_count,
            "warning_count": warning_count,
            "passed_count": len(results) - critical_count - warning_count,
            "consecutive_failures": self.consecutive_failures,
            "checks": [asdict(r) for r in results]
        }
        
        return report
    
    def get_recent_alerts(self, limit: int = 20) -> List[Dict]:
        """Get recent alerts"""
        with self._lock:
            return [asdict(a) for a in self.alerts[-limit:]]
    
    def start_monitoring(self):
        """Start continuous background monitoring"""
        if self.running:
            return
        
        self.running = True
        self._thread = threading.Thread(target=self._monitoring_loop, daemon=True)
        self._thread.start()
        print(f"🩺 Production Health Monitor started (interval: {self.thresholds.check_interval_seconds}s)")
    
    def stop_monitoring(self):
        """Stop background monitoring"""
        self.running = False
        if self._thread:
            self._thread.join(timeout=5)
    
    def _monitoring_loop(self):
        """Background monitoring loop"""
        while self.running:
            try:
                report = self.run_all_checks()
                
                status_icon = "✅" if report["status"] == "HEALTHY" else "⚠️" if report["status"] == "WARNING" else "🚨"
                print(f"{status_icon} HEALTH-CHECK: {report['status']} | Critical: {report['critical_count']} | Warning: {report['warning_count']}")
                
                # Only send email once when crossing threshold, not on every check
                # Send at 3 failures, then again at 10, 20, 30, etc. (not every 5 min)
                current_failures = report["consecutive_failures"]
                last_sent = getattr(self, 'last_email_sent_at_failures', 0)
                
                should_send = False
                if current_failures >= 3 and last_sent < 3:
                    should_send = True  # First alert at 3 failures
                elif current_failures >= 10 and (current_failures // 10) > (last_sent // 10):
                    should_send = True  # Subsequent alerts every 10 failures
                
                if should_send:
                    self._trigger_emergency_alert(report)
                    self.last_email_sent_at_failures = current_failures
                    self._save_state()
                    
            except Exception as e:
                print(f"🚨 Health monitor error: {e}")
            
            time.sleep(self.thresholds.check_interval_seconds)
    
    def _trigger_emergency_alert(self, report: Dict):
        """Trigger emergency alert - EMAIL DISABLED, console only"""
        pass
    
    def _send_emergency_email_DISABLED(self, report: Dict):
        """DISABLED - Email sending completely removed"""
        return
        
        try:
            pass  # All email code removed
            smtp_host = ""
            smtp_port = 0
            smtp_user = ""
            smtp_pass = ""
            report_to = ""
            
            if not all([smtp_user, smtp_pass, report_to]):
                print("   ⚠️ Email alert skipped - SMTP not configured")
                return
            
            msg = MIMEMultipart('alternative')
            msg['Subject'] = f"🚨 TRADING BOT EMERGENCY: {report['status']} - {report['consecutive_failures']} consecutive failures"
            msg['From'] = smtp_user
            msg['To'] = report_to
            
            html_body = f"""
            <html>
            <body style="font-family: Arial, sans-serif; padding: 20px;">
            <h1 style="color: #dc3545;">🚨 Production Health Alert</h1>
            <p><strong>Status:</strong> {report['status']}</p>
            <p><strong>Time:</strong> {report['timestamp']}</p>
            <p><strong>Consecutive Failures:</strong> {report['consecutive_failures']}</p>
            
            <h2>Health Check Results</h2>
            <table style="border-collapse: collapse; width: 100%;">
                <tr style="background: #f8f9fa;">
                    <th style="padding: 10px; border: 1px solid #ddd;">Check</th>
                    <th style="padding: 10px; border: 1px solid #ddd;">Status</th>
                    <th style="padding: 10px; border: 1px solid #ddd;">Message</th>
                </tr>
            """
            
            for check in report.get('checks', []):
                color = "#28a745" if check['severity'] == "OK" else "#ffc107" if check['severity'] == "WARNING" else "#dc3545"
                html_body += f"""
                <tr>
                    <td style="padding: 10px; border: 1px solid #ddd;">{check['check_name']}</td>
                    <td style="padding: 10px; border: 1px solid #ddd; color: {color};">{check['severity']}</td>
                    <td style="padding: 10px; border: 1px solid #ddd;">{check['message']}</td>
                </tr>
                """
            
            html_body += """
            </table>
            <p style="margin-top: 20px; color: #666;">
                This is an automated alert from the Trading Bot Production Health Monitor.
                Review the system immediately if multiple critical failures are detected.
            </p>
            </body>
            </html>
            """
            
            msg.attach(MIMEText(html_body, 'html'))
            
            with smtplib.SMTP(smtp_host, smtp_port) as server:
                server.starttls()
                server.login(smtp_user, smtp_pass)
                server.send_message(msg)
            
            print("   ✅ Emergency email sent successfully")
            
        except Exception as e:
            print(f"   ⚠️ Failed to send emergency email: {e}")


_monitor_instance: Optional[ProductionHealthMonitor] = None

def get_health_monitor() -> ProductionHealthMonitor:
    """Get or create the singleton health monitor"""
    global _monitor_instance
    if _monitor_instance is None:
        _monitor_instance = ProductionHealthMonitor()
    return _monitor_instance

def start_health_monitoring():
    """Start background health monitoring"""
    monitor = get_health_monitor()
    monitor.start_monitoring()
    return monitor

def run_health_check() -> Dict:
    """Run a single health check cycle"""
    monitor = get_health_monitor()
    return monitor.run_all_checks()

def get_health_status() -> str:
    """Get current health status (for API/dashboard)"""
    monitor = get_health_monitor()
    report = monitor.run_all_checks()
    return report["status"]


if __name__ == "__main__":
    import sys
    
    print("=" * 70)
    print("PRODUCTION HEALTH MONITOR")
    print("=" * 70)
    
    if len(sys.argv) > 1 and sys.argv[1] == "--daemon":
        print("\nStarting continuous monitoring daemon...")
        monitor = start_health_monitoring()
        try:
            while True:
                time.sleep(60)
        except KeyboardInterrupt:
            print("\nStopping health monitor...")
            monitor.stop_monitoring()
    else:
        print("\nRunning single health check...")
        report = run_health_check()
        
        print(f"\n{'=' * 70}")
        print(f"STATUS: {report['status']}")
        print(f"Critical: {report['critical_count']} | Warning: {report['warning_count']} | Passed: {report['passed_count']}")
        print(f"{'=' * 70}")
        
        for check in report["checks"]:
            icon = "✅" if check["severity"] == "OK" else "⚠️" if check["severity"] == "WARNING" else "🚨"
            print(f"{icon} {check['check_name']}: {check['message']}")
        
        print(f"\n{'=' * 70}")
        print("Run with --daemon for continuous monitoring")
