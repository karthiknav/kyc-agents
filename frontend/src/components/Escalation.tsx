import React, { useState, useEffect } from 'react';

const Escalation: React.FC = () => {
    const [sla, setSla] = useState(6138);

    useEffect(() => {
        const timer = setInterval(() => {
            setSla(prev => (prev > 0 ? prev - 1 : 0));
        }, 1000);
        return () => clearInterval(timer);
    }, []);

    const formatSla = (seconds: number) => {
        const h = Math.floor(seconds / 3600);
        const m = Math.floor((seconds % 3600) / 60);
        const s = seconds % 60;
        return `${String(h).padStart(2, '0')}:${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}`;
    };

    return (
        <div className="app-view active">
            <div className="escalation-content">
                <div className="esc-header">
                    <h2>⚠️ Escalation Queue</h2>
                    <div className="esc-count">🔥 3 cases requiring decision</div>
                </div>
                <div className="esc-layout">
                    <div className="esc-queue">
                        <div className="esc-card selected">
                            <div className="esc-card-top">
                                <div className="left">
                                    <div className="applicant-avatar" style={{ background: 'linear-gradient(135deg, #F59E0B, #EF4444)', width: '38px', height: '38px', fontSize: '13px' }}>KH</div>
                                    <div>
                                        <div className="esc-name">Khalid Hassan</div>
                                        <div className="esc-id">KYC-2026-NL-004819</div>
                                    </div>
                                </div>
                                <div style={{ textAlign: 'right' }}>
                                    <div className="esc-priority critical">Critical</div>
                                    <div className="esc-time" style={{ marginTop: '4px' }}>18 min ago</div>
                                </div>
                            </div>
                            <div className="esc-reason">
                                <div className="reason-icon">🏛️</div>
                                <div>
                                    <div className="reason-text">PEP Match — Political Exposure</div>
                                    <div className="reason-sub">Government advisory board connection</div>
                                </div>
                            </div>
                            <div className="esc-tags">
                                <span className="esc-tag pep">PEP</span>
                                <span className="esc-tag high-value">High Net Worth</span>
                            </div>
                        </div>
                    </div>
                    <div className="esc-detail">
                        <div className="esc-detail-header">
                            <h3>Escalation Review</h3>
                            <span className="esc-priority critical">Critical</span>
                        </div>
                        <div className="esc-detail-body">
                            <div className="sla-timer">
                                <div className="sla-icon">⏰</div>
                                <div className="sla-text">SLA Deadline</div>
                                <div className="sla-time">{formatSla(sla)}</div>
                            </div>
                            <div className="esc-summary-card">
                                <div className="esc-sum-top">
                                    <div className="esc-sum-avatar" style={{ background: 'linear-gradient(135deg, #F59E0B, #EF4444)' }}>KH</div>
                                    <div>
                                        <h4>Khalid Hassan</h4>
                                        <div className="esc-sum-sub">KYC-2026-NL-004819 · Individual · NL Resident</div>
                                    </div>
                                </div>
                                <div className="esc-meta-grid">
                                    <div className="esc-meta-item"><div className="meta-label">Risk Score</div><div className="meta-value" style={{ color: 'var(--accent-red)' }}>78 / 100 — High</div></div>
                                    <div className="esc-meta-item"><div className="meta-label">Agent Confidence</div><div className="meta-value" style={{ color: 'var(--accent-orange)' }}>64%</div></div>
                                    <div className="esc-meta-item"><div className="meta-label">Reason</div><div className="meta-value" style={{ color: 'var(--accent-orange)' }}>PEP Match</div></div>
                                    <div className="esc-meta-item"><div className="meta-label">Account Type</div><div className="meta-value">Wealth Management</div></div>
                                </div>
                            </div>
                            <div className="decision-form">
                                <h4>Analyst Decision</h4>
                                <div className="df-group">
                                    <label>Decision</label>
                                    <select className="df-select">
                                        <option value="">Select decision...</option>
                                        <option>Approve with Enhanced Due Diligence</option>
                                        <option>Approve (false positive)</option>
                                        <option>Reject — Unacceptable risk</option>
                                        <option>Request Additional Information</option>
                                        <option>Escalate to Senior Compliance</option>
                                    </select>
                                </div>
                                <div className="df-group">
                                    <label>Justification</label>
                                    <textarea className="df-textarea" placeholder="Provide rationale — this becomes part of the audit trail..."></textarea>
                                </div>
                                <div className="decision-actions">
                                    <button className="decision-btn approve-final">✓ Approve with EDD</button>
                                    <button className="decision-btn request-info">📋 Request Info</button>
                                    <button className="decision-btn reject-final">✕ Reject</button>
                                </div>
                            </div>
                        </div>
                    </div>
                </div>
            </div>
        </div>
    );
};

export default Escalation;
