# src/governance_digest.py
#
# v5.6 Governance Digest Module + Email Summary + Trend Arrows
# Adds human-readable summary tables with ↑/↓ trend indicators compared to previous digest

import os, json, time, smtplib
from email.mime.text import MIMEText
from collections import defaultdict
import numpy as np
from src.exploitation_overlays import LeadLagValidator, CommunityRiskManager, PCAOverlay

DIGEST_LOG = "logs/operator_digest.jsonl"
os.makedirs("logs", exist_ok=True)

class GovernanceDigest:
    def __init__(self, llv: LeadLagValidator, crm: CommunityRiskManager, pca: PCAOverlay,
                 smtp_user=None, smtp_pass=None, smtp_host="smtp.gmail.com", smtp_port=587,
                 email_to=None):
        self.llv = llv
        self.crm = crm
        self.pca = pca
        self.smtp_user = smtp_user
        self.smtp_pass = smtp_pass
        self.smtp_host = smtp_host
        self.smtp_port = smtp_port
        self.email_to = email_to

    def _load_last_digest(self):
        if not os.path.exists(DIGEST_LOG):
            return None
        try:
            with open(DIGEST_LOG, "r") as f:
                lines = f.readlines()
            if not lines:
                return None
            return json.loads(lines[-1])
        except:
            return None

    def snapshot(self, positions, returns_matrix=None):
        ts = int(time.time())
        digest = {"ts": ts, "components": {}}

        # Lead-Lag Validator summary
        ll_summary = {}
        for (leader, follower), rec in self.llv.lag_conf.items():
            ll_summary[f"{leader}->{follower}"] = {
                "peak_lag": rec["peak_lag"],
                "confidence": round(rec["confidence"], 3),
                "false_followers": rec["false_followers"]
            }
        digest["components"]["lead_lag"] = ll_summary

        # Community Risk Manager summary
        comms = self.crm.communities
        exposures = defaultdict(float)
        for p in positions:
            exposures[p["symbol"]] += abs(p.get("size_usd", 0))
        digest["components"]["communities"] = {
            "count": len(comms),
            "details": [list(c) for c in comms],
            "exposures": dict(exposures)
        }

        # PCA Overlay summary
        if returns_matrix is not None:
            dominant, variance = self.pca.check_dominance(returns_matrix)
            digest["components"]["pca"] = {
                "dominant": dominant,
                "variance": round(float(variance), 3)
            }
        else:
            digest["components"]["pca"] = {"dominant": False, "variance": 0.0}

        # Write to log
        with open(DIGEST_LOG, "a") as f:
            f.write(json.dumps(digest) + "\n")

        # Email disabled - only send during nightly cycle via nightly_email_report_v2
        # Previously: self._send_email(digest, last_digest) was called here every snapshot

        return digest

    def _trend_arrow(self, current, previous):
        if previous is None:
            return ""
        try:
            if current > previous:
                return "↑"
            elif current < previous:
                return "↓"
            else:
                return "→"
        except:
            return ""

    def _send_email(self, digest, last_digest):
        # EMAIL ALERTS DISABLED - user requested no more emails
        print("   ℹ️ Email disabled - governance digest logged to file only")
        return
        
        from email.mime.multipart import MIMEMultipart
        
        subject = f"🛡️ Correlation Risk Digest - {time.strftime('%b %d, %Y %H:%M')}"

        # Build HTML email with actionable insights
        ll_rows = []
        for pair, rec in digest["components"]["lead_lag"].items():
            prev_conf = None
            if last_digest and pair in last_digest.get("components", {}).get("lead_lag", {}):
                prev_conf = last_digest["components"]["lead_lag"][pair]["confidence"]
            arrow = self._trend_arrow(rec["confidence"], prev_conf)
            
            conf_color = "#27ae60" if rec["confidence"] > 0.7 else "#f39c12" if rec["confidence"] > 0.5 else "#e74c3c"
            false_color = "#e74c3c" if rec["false_followers"] > 2 else "#27ae60"
            
            ll_rows.append(f"""
                <tr>
                    <td style="padding: 8px; border-bottom: 1px solid #ddd;">{pair}</td>
                    <td style="padding: 8px; border-bottom: 1px solid #ddd; color: {conf_color}; font-weight: bold;">
                        {rec['confidence']:.2f} {arrow}
                    </td>
                    <td style="padding: 8px; border-bottom: 1px solid #ddd;">{rec['peak_lag']} candles</td>
                    <td style="padding: 8px; border-bottom: 1px solid #ddd; color: {false_color};">{rec['false_followers']}</td>
                </tr>
            """)

        comm_rows = []
        exposures = digest["components"]["communities"]["exposures"]
        for i, comm in enumerate(digest["components"]["communities"]["details"]):
            total_exp = sum(exposures.get(sym, 0) for sym in comm)
            exp_color = "#e74c3c" if total_exp > 3000 else "#f39c12" if total_exp > 2000 else "#27ae60"
            
            comm_rows.append(f"""
                <tr>
                    <td style="padding: 8px; border-bottom: 1px solid #ddd;">Cluster {i+1}</td>
                    <td style="padding: 8px; border-bottom: 1px solid #ddd;">{', '.join(comm)}</td>
                    <td style="padding: 8px; border-bottom: 1px solid #ddd; color: {exp_color}; font-weight: bold;">
                        ${total_exp:,.0f}
                    </td>
                </tr>
            """)

        pca = digest["components"]["pca"]
        prev_var = None
        if last_digest:
            prev_var = last_digest.get("components", {}).get("pca", {}).get("variance")
        arrow_var = self._trend_arrow(pca["variance"], prev_var)
        
        pca_status = "⚠️ OVER-CONCENTRATED" if pca["dominant"] else "✅ Diversified"
        pca_color = "#e74c3c" if pca["dominant"] else "#27ae60"
        var_pct = pca["variance"] * 100

        html = f"""
        <html>
        <head>
            <style>
                body {{ font-family: Arial, sans-serif; line-height: 1.6; color: #333; }}
                .header {{ background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); 
                          color: white; padding: 20px; border-radius: 5px; margin-bottom: 20px; }}
                .section {{ margin-bottom: 25px; }}
                .section-title {{ color: #2c3e50; font-size: 18px; font-weight: bold; 
                                 border-bottom: 2px solid #667eea; padding-bottom: 5px; margin-bottom: 15px; }}
                table {{ width: 100%; border-collapse: collapse; background: white; }}
                th {{ background: #f8f9fa; padding: 10px; text-align: left; font-weight: bold; }}
                .insight {{ background: #fff3cd; border-left: 4px solid #ffc107; padding: 12px; margin: 10px 0; }}
                .footer {{ color: #7f8c8d; font-size: 12px; margin-top: 30px; padding-top: 15px; border-top: 1px solid #ddd; }}
            </style>
        </head>
        <body>
            <div class="header">
                <h2 style="margin: 0;">🛡️ Correlation Risk Digest</h2>
                <p style="margin: 5px 0 0 0; opacity: 0.9;">{time.strftime('%B %d, %Y at %H:%M UTC')}</p>
            </div>

            <div class="section">
                <div class="section-title">📊 Lead-Lag Relationships</div>
                <table>
                    <tr>
                        <th>Pair</th>
                        <th>Confidence</th>
                        <th>Lag</th>
                        <th>False Signals</th>
                    </tr>
                    {''.join(ll_rows) if ll_rows else '<tr><td colspan="4" style="padding: 12px; text-align: center; color: #7f8c8d;">No lead-lag relationships detected</td></tr>'}
                </table>
                {f'<div class="insight"><strong>💡 Insight:</strong> {len(ll_rows)} correlation pair(s) detected. Monitor false signals - high counts indicate unreliable relationships.</div>' if ll_rows else ''}
            </div>

            <div class="section">
                <div class="section-title">🔗 Correlation Clusters</div>
                <table>
                    <tr>
                        <th>Cluster</th>
                        <th>Assets</th>
                        <th>Total Exposure</th>
                    </tr>
                    {''.join(comm_rows) if comm_rows else '<tr><td colspan="3" style="padding: 12px; text-align: center; color: #7f8c8d;">No correlation clusters detected</td></tr>'}
                </table>
                <div class="insight"><strong>💡 Insight:</strong> Found {len(digest["components"]["communities"]["details"])} cluster(s). 
                Limit exposure per cluster to avoid correlated drawdowns.</div>
            </div>

            <div class="section">
                <div class="section-title">🎯 PCA Concentration Risk</div>
                <table>
                    <tr>
                        <th>Status</th>
                        <th>First Component Variance</th>
                    </tr>
                    <tr>
                        <td style="padding: 10px; color: {pca_color}; font-weight: bold;">{pca_status}</td>
                        <td style="padding: 10px; font-weight: bold;">{var_pct:.1f}% {arrow_var}</td>
                    </tr>
                </table>
                <div class="insight"><strong>💡 Insight:</strong> 
                    {f'⚠️ Portfolio is over-concentrated - first component explains {var_pct:.1f}% of variance (threshold: 50%).' if pca["dominant"] else f'✅ Portfolio is well-diversified - first component explains only {var_pct:.1f}% of variance.'}
                </div>
            </div>

            <div class="footer">
                <p><strong>v5.6 Exploitation Infrastructure</strong> - Automated correlation risk monitoring</p>
                <p>This digest identifies correlated positions to prevent concentrated risk exposure.</p>
            </div>
        </body>
        </html>
        """

        msg = MIMEMultipart('alternative')
        msg["Subject"] = subject
        msg["From"] = self.smtp_user
        msg["To"] = self.email_to
        
        msg.attach(MIMEText(html, 'html'))

        try:
            with smtplib.SMTP(self.smtp_host, self.smtp_port) as server:
                server.starttls()
                server.login(self.smtp_user, self.smtp_pass)
                server.sendmail(self.smtp_user, [self.email_to], msg.as_string())
            print(f"✅ Governance digest emailed to {self.email_to}")
        except Exception as e:
            print(f"⚠️ Email send failed: {e}")


# ---------------------------------------------------------------------
# Example nightly run
# ---------------------------------------------------------------------
if __name__ == "__main__":
    llv = LeadLagValidator()
    crm = CommunityRiskManager()
    pca = PCAOverlay()

    # Fake demo data
    llv.update("BTCUSDT", "ETHUSDT", {1: 0.72, 4: 0.65})
    positions = [{"symbol": "BTCUSDT", "side": "long", "size_usd": 200000},
                 {"symbol": "ETHUSDT", "side": "long", "size_usd": 150000}]
    returns_matrix = np.random.randn(100, 4)

    gd = GovernanceDigest(llv, crm, pca,
                          smtp_user="your_gmail_username@gmail.com",
                          smtp_pass="your_app_password",
                          email_to="operator@example.com")
    snapshot = gd.snapshot(positions, returns_matrix)
    print("Governance digest snapshot:", json.dumps(snapshot, indent=2))
