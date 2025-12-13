"""
Autonomous Optimization Proposals

Tracks and logs optimization opportunities detected by the autonomous operator.
Creates actionable proposals for system improvements without manual prompting.
"""
import json
import os
from datetime import datetime
from pathlib import Path


PROPOSALS_LOG = "logs/optimization_proposals.jsonl"


def propose_policy_increase(current_min, current_max, suggested_min, suggested_max, reason, severity="medium"):
    """
    Propose increasing trading policy limits.
    
    Args:
        current_min: Current minimum position size
        current_max: Current maximum position size
        suggested_min: Suggested minimum position size
        suggested_max: Suggested maximum position size
        reason: Detailed reason for the proposal
        severity: "low", "medium", or "high"
    """
    proposal = {
        "timestamp": datetime.utcnow().isoformat() + "Z",
        "type": "policy_limit_increase",
        "severity": severity,
        "current_limits": {
            "min_usd": current_min,
            "max_usd": current_max
        },
        "suggested_limits": {
            "min_usd": suggested_min,
            "max_usd": suggested_max
        },
        "reason": reason,
        "status": "pending_review",
        "auto_approved": False
    }
    
    _log_proposal(proposal)
    return proposal


def propose_margin_allocation_increase(current_pct, suggested_pct, reason, severity="medium"):
    """
    Propose increasing futures margin allocation.
    
    Args:
        current_pct: Current margin allocation percentage
        suggested_pct: Suggested margin allocation percentage
        reason: Detailed reason for the proposal
        severity: "low", "medium", or "high"
    """
    proposal = {
        "timestamp": datetime.utcnow().isoformat() + "Z",
        "type": "margin_allocation_increase",
        "severity": severity,
        "current_allocation_pct": current_pct,
        "suggested_allocation_pct": suggested_pct,
        "reason": reason,
        "status": "pending_review",
        "auto_approved": False
    }
    
    _log_proposal(proposal)
    return proposal


def _log_proposal(proposal):
    """Log proposal to JSONL file."""
    log_dir = Path("logs")
    log_dir.mkdir(exist_ok=True)
    
    with open(PROPOSALS_LOG, "a") as f:
        f.write(json.dumps(proposal) + "\n")


def get_pending_proposals(hours=24):
    """
    Get all pending optimization proposals in the last N hours.
    
    Args:
        hours: Number of hours to look back
    
    Returns:
        list: Pending proposals
    """
    if not os.path.exists(PROPOSALS_LOG):
        return []
    
    cutoff_time = datetime.utcnow().timestamp() - (hours * 3600)
    pending = []
    
    with open(PROPOSALS_LOG, "r") as f:
        for line in f:
            if not line.strip():
                continue
            proposal = json.loads(line)
            
            proposal_time = datetime.fromisoformat(proposal["timestamp"].replace("Z", "")).timestamp()
            if proposal_time < cutoff_time:
                continue
            
            if proposal.get("status") == "pending_review":
                pending.append(proposal)
    
    return pending


def get_proposal_summary():
    """
    Get summary of all optimization proposals.
    
    Returns:
        dict: Summary statistics
    """
    if not os.path.exists(PROPOSALS_LOG):
        return {
            "total_proposals": 0,
            "pending": 0,
            "approved": 0,
            "rejected": 0,
            "by_type": {},
            "by_severity": {}
        }
    
    all_proposals = []
    with open(PROPOSALS_LOG, "r") as f:
        for line in f:
            if not line.strip():
                continue
            all_proposals.append(json.loads(line))
    
    pending = sum(1 for p in all_proposals if p.get("status") == "pending_review")
    approved = sum(1 for p in all_proposals if p.get("status") == "approved")
    rejected = sum(1 for p in all_proposals if p.get("status") == "rejected")
    
    by_type = {}
    by_severity = {}
    
    for p in all_proposals:
        prop_type = p.get("type", "unknown")
        severity = p.get("severity", "unknown")
        
        by_type[prop_type] = by_type.get(prop_type, 0) + 1
        by_severity[severity] = by_severity.get(severity, 0) + 1
    
    return {
        "total_proposals": len(all_proposals),
        "pending": pending,
        "approved": approved,
        "rejected": rejected,
        "by_type": by_type,
        "by_severity": by_severity,
        "recent_pending": all_proposals[-5:] if all_proposals else []
    }


def mark_proposal_status(timestamp, status):
    """
    Mark a proposal as approved/rejected.
    
    Args:
        timestamp: Timestamp of the proposal to update
        status: "approved" or "rejected"
    """
    if not os.path.exists(PROPOSALS_LOG):
        return False
    
    proposals = []
    with open(PROPOSALS_LOG, "r") as f:
        for line in f:
            if not line.strip():
                continue
            proposal = json.loads(line)
            
            if proposal.get("timestamp") == timestamp:
                proposal["status"] = status
                proposal["reviewed_at"] = datetime.utcnow().isoformat() + "Z"
            
            proposals.append(proposal)
    
    # Rewrite file with updated status
    with open(PROPOSALS_LOG, "w") as f:
        for proposal in proposals:
            f.write(json.dumps(proposal) + "\n")
    
    return True
