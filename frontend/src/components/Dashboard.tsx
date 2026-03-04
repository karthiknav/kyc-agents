import React, { useState, useEffect } from 'react';
import type { KycSubmission } from '../types.js';
import { API_BASE_URL } from '../config.js';

interface DashboardProps {
    onEscalate: () => void;
}

const Dashboard: React.FC<DashboardProps> = ({ onEscalate }) => {
    const [submissions, setSubmissions] = useState<KycSubmission[]>([]);
    const [selectedSubmission, setSelectedSubmission] = useState<KycSubmission | null>(null);
    const [loading, setLoading] = useState(true);
    const [analytics, setAnalytics] = useState({
        total_onboardings: 0,
        pending_review: 0,
        auto_approved: 0,
        avg_processing_time: 0,
        escalations: 0
    });

    useEffect(() => {
        const fetchData = async () => {
            try {
                // Fetch Submissions
                const subResponse = await fetch(`${API_BASE_URL}/submissions`);
                if (subResponse.ok) {
                    const data = await subResponse.json();
                    setSubmissions(data);
                    if (data.length > 0) {
                        setSelectedSubmission(data[0]);
                    }
                }

                // Fetch Analytics
                const analyticsResponse = await fetch(`${API_BASE_URL}/analytics/summary`);
                if (analyticsResponse.ok) {
                    const data = await analyticsResponse.json();
                    setAnalytics(data);
                }
            } catch (error) {
                console.error('Failed to fetch data:', error);
            } finally {
                setLoading(false);
            }
        };
        fetchData();
    }, []);

    const formatDate = (isoString: string) => {
        try {
            const date = new Date(isoString);
            return date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
        } catch (e) {
            return 'N/A';
        }
    };
    return (
        <div className="app-view active">
            <div className="analyst-content">
                <div className="stats-row">
                    <div className="stat-card"><div className="stat-label">Total Onboardings</div><div className="stat-value">{analytics.total_onboardings}</div><div className="stat-change up">↑ Real-time</div></div>
                    <div className="stat-card"><div className="stat-label">Pending Review</div><div className="stat-value" style={{ color: 'var(--accent-orange)' }}>{analytics.pending_review}</div><div className="stat-change">requires action</div></div>
                    <div className="stat-card"><div className="stat-label">Auto-Approved</div><div className="stat-value" style={{ color: 'var(--accent-green)' }}>{analytics.auto_approved}</div><div className="stat-change up">✓ optimized</div></div>
                    <div className="stat-card">
                        <div className="stat-label">Avg Processing</div>
                        <div className="stat-value">
                            {analytics.avg_processing_time}
                            <span style={{ fontSize: '16px', color: 'var(--text-muted)', fontWeight: '400' }}>s</span>
                        </div>
                        <div className="stat-change up">↓ optimized</div>
                    </div>
                    <div className="stat-card"><div className="stat-label">Escalations</div><div className="stat-value" style={{ color: 'var(--accent-red)' }}>{analytics.escalations}</div><div className="stat-change">attention needed</div></div>
                </div>
                <div className="dash-layout">
                    <div className="table-section">
                        <div className="table-header">
                            <h3>Onboarding Pipeline</h3>
                            <div className="table-filters">
                                <button className="filter-btn active">All</button>
                                <button className="filter-btn">Pending</button>
                                <button className="filter-btn">Escalated</button>
                                <button className="filter-btn">Approved</button>
                                <button className="filter-btn">Rejected</button>
                            </div>
                        </div>
                        <table className="kyc-table">
                            <thead>
                                <tr><th>Applicant</th><th>Type</th><th>Risk</th><th>Decision</th><th>Agent</th><th>Time</th></tr>
                            </thead>
                            <tbody>
                                {loading ? (
                                    <tr><td colSpan={6} style={{ textAlign: 'center', padding: '40px' }}>Loading submissions...</td></tr>
                                ) : submissions.length === 0 ? (
                                    <tr><td colSpan={6} style={{ textAlign: 'center', padding: '40px' }}>No submissions found</td></tr>
                                ) : submissions.map(sub => (
                                    <tr
                                        key={sub.caseId}
                                        className={selectedSubmission?.caseId === sub.caseId ? 'selected' : ''}
                                        onClick={() => setSelectedSubmission(sub)}
                                        style={{ cursor: 'pointer' }}
                                    >
                                        <td>
                                            <div className="applicant-cell">
                                                <div className="applicant-avatar" style={{ background: `linear-gradient(135deg, #6366F1, #8B5CF6)` }}>
                                                    {sub.identity.fullName.split(' ').map((n: string) => n[0]).join('')}
                                                </div>
                                                <div>
                                                    <div className="applicant-name">{sub.identity.fullName}</div>
                                                    <div className="applicant-id">{sub.caseId}</div>
                                                </div>
                                            </div>
                                        </td>
                                        <td style={{ fontSize: '12px', color: 'var(--text-secondary)' }}>Individual</td>
                                        <td><span className="risk-badge low">Low</span></td>
                                        <td><span className={`decision-badge ${sub.status}`}>{sub.status}</span></td>
                                        <td><span className="agent-indicator" style={{ color: 'var(--accent-cyan)' }}><span className="agent-dot" style={{ background: 'var(--accent-cyan)' }}></span> AI Processing</span></td>
                                        <td style={{ fontSize: '12px', color: 'var(--text-muted)' }}>{formatDate(sub.createdAt)}</td>
                                    </tr>
                                ))}
                            </tbody>
                        </table>
                    </div>
                    <div className="detail-panel">
                        <div className="detail-panel-header"><h3>Onboarding Detail</h3><span className="status-chip processing">⟳ In Progress</span></div>
                        <div className="detail-content">
                            {selectedSubmission ? (
                                <>
                                    <div className="applicant-summary">
                                        <div className="big-avatar" style={{ background: 'linear-gradient(135deg, #6366F1, #8B5CF6)' }}>
                                            {selectedSubmission.identity.fullName.split(' ').map((n: string) => n[0]).join('')}
                                        </div>
                                        <div className="info">
                                            <h4>{selectedSubmission.identity.fullName}</h4>
                                            <div className="sub">{selectedSubmission.caseId} · Individual</div>
                                        </div>
                                    </div>
                                    <div className="confidence-meter">
                                        <div className="cm-header"><span className="cm-label">Agent Confidence</span><span className="cm-value" style={{ color: 'var(--accent-green)' }}>82%</span></div>
                                        <div className="confidence-bar"><div className="fill" style={{ width: '82%', background: 'linear-gradient(90deg, var(--accent-blue), var(--accent-green))' }}></div></div>
                                    </div>
                                    <div className="agent-reasoning" style={{ marginBottom: '20px' }}>
                                        <div className="ar-header">🤖 Agent Findings</div>
                                        <div className="ar-text">
                                            Passport verified. MRZ match. Risk level: Low. Trajectory: <strong>Auto-Approve</strong>.
                                        </div>
                                    </div>
                                    <div className="section-title">Verification Documents</div>
                                    <div className="document-list">
                                        {['passport', 'address', 'income'].map(type => {
                                            const url = selectedSubmission.document_urls?.[type];
                                            const label = type.charAt(0).toUpperCase() + type.slice(1);
                                            return (
                                                <div key={type} className="doc-list-item">
                                                    <div className="doc-info">
                                                        <span className="doc-icon">📄</span>
                                                        <span className="doc-label">{label}</span>
                                                    </div>
                                                    <button
                                                        className="view-doc-btn"
                                                        onClick={() => url && window.open(url, '_blank')}
                                                        disabled={!url}
                                                        title={url ? 'View Document' : 'Document not available'}
                                                    >
                                                        👁 View
                                                    </button>
                                                </div>
                                            );
                                        })}
                                    </div>

                                    <div className="flow-section" style={{ background: 'var(--bg-secondary)', padding: '15px', borderRadius: '8px' }}>
                                        <div className="section-title" style={{ marginBottom: '10px' }}>Extracted Details</div>
                                        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '10px', fontSize: '12px' }}>
                                            <div><span style={{ color: 'var(--text-muted)' }}>Passport:</span> {selectedSubmission.identity.passportNumber}</div>
                                            <div><span style={{ color: 'var(--text-muted)' }}>Expiry:</span> {selectedSubmission.identity.passportExpiry}</div>
                                            <div style={{ gridColumn: 'span 2' }}><span style={{ color: 'var(--text-muted)' }}>Address:</span> {selectedSubmission.identity.address}</div>
                                        </div>
                                    </div>
                                    <div className="action-buttons" style={{ marginTop: '20px' }}>
                                        <button className="action-btn approve">✓ Approve</button>
                                        <button className="action-btn escalate-btn" onClick={onEscalate}>↑ Escalate</button>
                                        <button className="action-btn reject">✕ Reject</button>
                                    </div>
                                </>
                            ) : (
                                <div style={{ textAlign: 'center', padding: '40px', color: 'var(--text-muted)' }}>Select a submission to view details</div>
                            )}
                        </div>
                    </div>
                </div>
            </div>
        </div>
    );
};

export default Dashboard;
