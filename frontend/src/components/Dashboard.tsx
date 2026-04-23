import React, { useState, useEffect, useRef } from 'react';
import type { KycSubmission } from '../types.js';
import { API_BASE_URL } from '../config.js';

interface DashboardProps {
    onEscalate: () => void;
}

const Dashboard: React.FC<DashboardProps> = ({ onEscalate }) => {
    const [submissions, setSubmissions] = useState<KycSubmission[]>([]);
    const [selectedSubmission, setSelectedSubmission] = useState<KycSubmission | null>(null);
    const [openMenuId, setOpenMenuId] = useState<string | null>(null);
    const [loading, setLoading] = useState(true);
    const [filter, setFilter] = useState('ALL');
    const [toasts, setToasts] = useState<{ id: string; message: string; type: 'success' | 'error' | 'info' }[]>([]);
    const [analytics, setAnalytics] = useState({
        total_onboardings: 0,
        pending_review: 0,
        auto_approved: 0,
        avg_processing_time: 0,
        escalations: 0
    });

    // Override flow state
    const [overrideFormOpen, setOverrideFormOpen] = useState(false);
    const [overrideComments, setOverrideComments] = useState('');
    const [overrideSubmitting, setOverrideSubmitting] = useState(false);
    const pollingRef = useRef<ReturnType<typeof setInterval> | null>(null);

    useEffect(() => {
        const handleClickOutside = (event: MouseEvent) => {
            const target = event.target as HTMLElement;
            if (!target.closest('.row-actions')) {
                setOpenMenuId(null);
            }
        };
        if (openMenuId) {
            document.addEventListener('mousedown', handleClickOutside);
        }
        return () => {
            document.removeEventListener('mousedown', handleClickOutside);
        };
    }, [openMenuId]);

    useEffect(() => {
        const fetchData = async () => {
            try {
                const subResponse = await fetch(`${API_BASE_URL}/submissions`);
                if (subResponse.ok) {
                    const data = await subResponse.json();
                    setSubmissions(data);
                    if (data.length > 0) {
                        setSelectedSubmission(data[0]);
                    }
                }
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

    // Reset override form when selected submission changes
    useEffect(() => {
        setOverrideFormOpen(false);
        setOverrideComments('');
    }, [selectedSubmission?.caseId]);

    // Poll for override result when case is OVERRIDE_PENDING_AI_REVIEW
    useEffect(() => {
        if (pollingRef.current) {
            clearInterval(pollingRef.current);
            pollingRef.current = null;
        }
        if (selectedSubmission?.status !== 'OVERRIDE_PENDING_AI_REVIEW') return;

        const caseId = selectedSubmission.caseId || (selectedSubmission as any).CaseId;
        pollingRef.current = setInterval(async () => {
            try {
                const res = await fetch(`${API_BASE_URL}/submissions/${caseId}`);
                if (!res.ok) return;
                const updated = await res.json();
                const newStatus = (updated.status || '');
                if (newStatus === 'OVERRIDE_PENDING_AI_REVIEW') return;

                const normalizedId = updated.caseId || updated.CaseId;
                const merged = { ...updated, caseId: normalizedId };
                setSubmissions(prev => prev.map(s => {
                    const sId = s.caseId || (s as any).CaseId;
                    return sId === normalizedId ? merged : s;
                }));
                setSelectedSubmission(merged);

                if (newStatus === 'APPROVED') {
                    showToast('Override approved by AI review', 'success');
                } else if (newStatus === 'PENDING_HUMAN_REVIEW') {
                    showToast('AI rejected the override justification. See reasoning below.', 'error');
                }
            } catch (e) {
                console.error('Override polling error:', e);
            }
        }, 5000);

        return () => {
            if (pollingRef.current) clearInterval(pollingRef.current);
        };
    }, [selectedSubmission?.status, selectedSubmission?.caseId]);

    const showToast = (message: string, type: 'success' | 'error' | 'info' = 'info') => {
        const id = Math.random().toString(36).substring(2, 9);
        setToasts(prev => [...prev, { id, message, type }]);
        setTimeout(() => {
            setToasts(prev => prev.filter(t => t.id !== id));
        }, 5000);
    };

    const formatDate = (isoString: string) => {
        try {
            const date = new Date(isoString);
            return date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
        } catch (e) {
            return 'N/A';
        }
    };

    const filteredSubmissions = submissions.filter(sub => {
        const s = sub.status.toUpperCase();
        if (filter === 'ALL') return true;
        if (filter === 'PENDING') return ['INITIATED', 'PROCESSING', 'PENDING', 'PENDING_HUMAN_REVIEW', 'OVERRIDE_PENDING_AI_REVIEW'].includes(s);
        return s === filter;
    });

    const handleStatusUpdate = async (status: string) => {
        if (!selectedSubmission) return;
        const caseId = selectedSubmission.caseId || (selectedSubmission as any).CaseId;
        try {
            const response = await fetch(`${API_BASE_URL}/submissions/${caseId}/status`, {
                method: 'PATCH',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ status })
            });
            if (response.ok) {
                const updatedSubmissions = submissions.map((sub: any) => {
                    const subId = sub.caseId || (sub as any).CaseId;
                    if (subId === caseId) return { ...sub, status };
                    return sub;
                });
                setSubmissions(updatedSubmissions);
                setSelectedSubmission({ ...selectedSubmission, status });
                showToast(`Case ${status} successfully`, 'success');
            } else {
                const error = await response.json();
                showToast(`Failed to update status: ${error.detail || 'Unknown error'}`, 'error');
            }
        } catch (error) {
            console.error('Error updating status:', error);
            showToast('Failed to connect to the server', 'error');
        }
    };

    const handleOverrideSubmit = async () => {
        if (!selectedSubmission || !overrideComments.trim()) return;
        const caseId = selectedSubmission.caseId || (selectedSubmission as any).CaseId;
        setOverrideSubmitting(true);
        try {
            const response = await fetch(`${API_BASE_URL}/submissions/${caseId}/override`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ analystComments: overrideComments.trim() })
            });
            if (response.ok) {
                const updatedSubmissions = submissions.map((sub: any) => {
                    const subId = sub.caseId || (sub as any).CaseId;
                    return subId === caseId ? { ...sub, status: 'OVERRIDE_PENDING_AI_REVIEW' } : sub;
                });
                setSubmissions(updatedSubmissions);
                setSelectedSubmission({ ...selectedSubmission, status: 'OVERRIDE_PENDING_AI_REVIEW' });
                setOverrideFormOpen(false);
                setOverrideComments('');
                showToast('Override request submitted — AI is reviewing...', 'info');
            } else {
                const error = await response.json();
                showToast(`Override failed: ${error.detail || 'Unknown error'}`, 'error');
            }
        } catch (error) {
            console.error('Error submitting override:', error);
            showToast('Failed to submit override request', 'error');
        } finally {
            setOverrideSubmitting(false);
        }
    };

    const renderActionButtons = (sub: KycSubmission) => {
        const status = sub.status;
        const overrideReview = sub.stages?.overrideReview;

        if (status === 'OVERRIDE_PENDING_AI_REVIEW') {
            return (
                <div style={{ textAlign: 'center', padding: '24px 0', color: 'var(--accent-cyan)' }}>
                    <div style={{ fontSize: '28px', marginBottom: '8px', animation: 'spin 2s linear infinite' }}>⟳</div>
                    <div style={{ fontWeight: 600 }}>AI is reviewing your override request...</div>
                    <div style={{ fontSize: '11px', color: 'var(--text-muted)', marginTop: '4px' }}>This usually takes 30–60 seconds</div>
                </div>
            );
        }

        if (status === 'PENDING_HUMAN_REVIEW') {
            return (
                <div>
                    {overrideReview?.verdict === 'REJECTED' && (
                        <div style={{ background: 'rgba(239,68,68,0.08)', border: '1px solid rgba(239,68,68,0.3)', borderRadius: '8px', padding: '12px', marginBottom: '12px' }}>
                            <div style={{ display: 'flex', alignItems: 'center', gap: '6px', color: 'var(--accent-red)', fontWeight: 600, fontSize: '12px', marginBottom: '6px' }}>
                                <span>✕</span> AI Override Review — Rejected
                            </div>
                            <div style={{ fontSize: '12px', color: 'var(--text-secondary)', lineHeight: '1.5' }}>
                                {overrideReview.reasoning}
                            </div>
                            {overrideReview.riskFlagsEvaluated?.length > 0 && (
                                <div style={{ marginTop: '8px', display: 'flex', gap: '4px', flexWrap: 'wrap' }}>
                                    {overrideReview.riskFlagsEvaluated.map((flag, i) => (
                                        <span key={i} style={{ fontSize: '10px', background: 'rgba(239,68,68,0.15)', color: 'var(--accent-red)', padding: '2px 6px', borderRadius: '4px' }}>{flag}</span>
                                    ))}
                                </div>
                            )}
                        </div>
                    )}

                    {overrideFormOpen ? (
                        <div>
                            <textarea
                                value={overrideComments}
                                onChange={e => setOverrideComments(e.target.value)}
                                placeholder="Provide a specific justification for the override. Vague statements will be rejected — address each risk flag directly (e.g. confirmed false positive, DOB mismatch, distinct individual)."
                                style={{ width: '100%', minHeight: '90px', background: 'var(--bg-tertiary)', border: '1px solid var(--border)', borderRadius: '6px', color: 'var(--text-primary)', padding: '10px', fontSize: '12px', resize: 'vertical', boxSizing: 'border-box' }}
                            />
                            <div style={{ display: 'flex', gap: '8px', marginTop: '8px' }}>
                                <button
                                    className="action-btn approve"
                                    style={{ flex: 1 }}
                                    onClick={handleOverrideSubmit}
                                    disabled={overrideSubmitting || !overrideComments.trim()}
                                >
                                    {overrideSubmitting ? '⟳ Submitting...' : '↑ Submit for AI Review'}
                                </button>
                                <button
                                    className="action-btn reject"
                                    onClick={() => { setOverrideFormOpen(false); setOverrideComments(''); }}
                                    style={{ flex: '0 0 auto', padding: '0 16px' }}
                                >
                                    Cancel
                                </button>
                            </div>
                        </div>
                    ) : (
                        <div className="action-buttons">
                            <button
                                className="action-btn"
                                style={{ background: 'linear-gradient(135deg, #F59E0B, #D97706)', color: '#fff' }}
                                onClick={() => setOverrideFormOpen(true)}
                            >
                                🔍 {overrideReview?.verdict === 'REJECTED' ? 'Try Again' : 'Request Override'}
                            </button>
                            <button className="action-btn escalate-btn" onClick={() => handleStatusUpdate('ESCALATED')}>↑ Escalate</button>
                        </div>
                    )}
                </div>
            );
        }

        return (
            <div className="action-buttons">
                <button className="action-btn approve" onClick={() => handleStatusUpdate('APPROVED')}>✓ Approve</button>
                <button className="action-btn escalate-btn" onClick={() => handleStatusUpdate('ESCALATED')}>↑ Escalate</button>
                <button className="action-btn reject" onClick={() => handleStatusUpdate('REJECTED')}>✕ Reject</button>
            </div>
        );
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
                                <button className={`filter-btn ${filter === 'ALL' ? 'active' : ''}`} onClick={() => setFilter('ALL')}>All</button>
                                <button className={`filter-btn ${filter === 'PENDING' ? 'active' : ''}`} onClick={() => setFilter('PENDING')}>Pending</button>
                                <button className={`filter-btn ${filter === 'PENDING_HUMAN_REVIEW' ? 'active' : ''}`} onClick={() => setFilter('PENDING_HUMAN_REVIEW')}>Human Review</button>
                                <button className={`filter-btn ${filter === 'ESCALATED' ? 'active' : ''}`} onClick={() => setFilter('ESCALATED')}>Escalated</button>
                                <button className={`filter-btn ${filter === 'APPROVED' ? 'active' : ''}`} onClick={() => setFilter('APPROVED')}>Approved</button>
                                <button className={`filter-btn ${filter === 'REJECTED' ? 'active' : ''}`} onClick={() => setFilter('REJECTED')}>Rejected</button>
                            </div>
                        </div>
                        <table className="kyc-table">
                            <thead>
                                <tr><th>Applicant</th><th>Type</th><th>Risk</th><th>Decision</th><th>Agent</th><th>Time</th><th>Actions</th></tr>
                            </thead>
                            <tbody>
                                {loading ? (
                                    <tr><td colSpan={7} style={{ textAlign: 'center', padding: '40px' }}>Loading submissions...</td></tr>
                                ) : filteredSubmissions.length === 0 ? (
                                    <tr><td colSpan={7} style={{ textAlign: 'center', padding: '40px' }}>No submissions found for this filter</td></tr>
                                ) : filteredSubmissions.map(sub => (
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
                                                    <div className="applicant-id">{sub.caseId || (sub as any).CaseId}</div>
                                                </div>
                                            </div>
                                        </td>
                                        <td style={{ fontSize: '12px', color: 'var(--text-secondary)' }}>Individual</td>
                                        <td><span className="risk-badge low">Low</span></td>
                                        <td><span className={`decision-badge ${sub.status}`}>{sub.status}</span></td>
                                        <td><span className="agent-indicator" style={{ color: 'var(--accent-cyan)' }}><span className="agent-dot" style={{ background: 'var(--accent-cyan)' }}></span> AI Processing</span></td>
                                        <td style={{ fontSize: '12px', color: 'var(--text-muted)' }}>{formatDate(sub.createdAt)}</td>
                                        <td>
                                            <div className="row-actions">
                                                <button
                                                    className="menu-toggle"
                                                    onClick={(e) => {
                                                        e.stopPropagation();
                                                        const id = sub.caseId || (sub as any).CaseId;
                                                        setOpenMenuId(openMenuId === id ? null : id);
                                                    }}
                                                >
                                                    ⋮
                                                </button>
                                                {openMenuId === (sub.caseId || (sub as any).CaseId) && (
                                                    <div className="row-menu" onClick={(e) => e.stopPropagation()}>
                                                        <div className="menu-header">Documents</div>
                                                        {['passport', 'address', 'income'].map(type => {
                                                            const url = sub.document_urls?.[type];
                                                            const label = type.charAt(0).toUpperCase() + type.slice(1);
                                                            return (
                                                                <button
                                                                    key={type}
                                                                    className="menu-item"
                                                                    onClick={() => {
                                                                        if (url) window.open(url, '_blank');
                                                                        setOpenMenuId(null);
                                                                    }}
                                                                    disabled={!url}
                                                                >
                                                                    <span className="doc-icon">📄</span>
                                                                    {label}
                                                                </button>
                                                            );
                                                        })}
                                                    </div>
                                                )}
                                            </div>
                                        </td>
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
                                        <div className="ar-header" style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', width: '100%' }}>
                                            <span>🤖 Agent Findings</span>
                                            {selectedSubmission.stages?.orchestrator?.status && (
                                                <span className={`decision-badge ${selectedSubmission.stages.orchestrator.status}`}>
                                                    {selectedSubmission.stages.orchestrator.status}
                                                </span>
                                            )}
                                        </div>
                                        <div className="ar-text">
                                            {selectedSubmission.stages?.orchestrator?.recommendation_summary || 'No findings available'}
                                        </div>
                                        {Array.isArray(selectedSubmission.stages?.orchestrator?.reason) && (
                                            <ul style={{ fontSize: '12px', marginTop: '8px', color: 'var(--text-secondary)', paddingLeft: '20px' }}>
                                                {selectedSubmission.stages!.orchestrator!.reason.map((r: string, i: number) => (
                                                    <li key={i}>{r}</li>
                                                ))}
                                            </ul>
                                        )}
                                    </div>

                                    {selectedSubmission.stages?.documentProcessing && (
                                        <div className="flow-section" style={{ background: 'var(--bg-secondary)', padding: '15px', borderRadius: '8px', marginBottom: '20px' }}>
                                            <div className="section-title" style={{ marginBottom: '10px' }}>Document Verification</div>
                                            <div style={{ display: 'grid', gridTemplateColumns: '1fr', gap: '10px', fontSize: '12px' }}>
                                                <div style={{ marginBottom: '8px' }}>
                                                    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                                                        <span style={{ color: 'var(--text-muted)' }}>Status:</span>
                                                        <span className={`decision-badge ${selectedSubmission.stages.documentProcessing.result || 'PENDING'}`}>
                                                            {selectedSubmission.stages.documentProcessing.result || 'PENDING'}
                                                        </span>
                                                    </div>
                                                </div>
                                                {selectedSubmission.stages.documentProcessing.discrepancies && selectedSubmission.stages.documentProcessing.discrepancies.length > 0 && (
                                                    <div style={{ marginTop: '5px', borderTop: '1px solid var(--border)', paddingTop: '8px' }}>
                                                        <div style={{ color: 'var(--accent-orange)', fontSize: '11px', fontWeight: '600', marginBottom: '5px', display: 'flex', alignItems: 'center', gap: '4px' }}>
                                                            <span>⚠️</span> Discrepancies Found:
                                                        </div>
                                                        <ul style={{ fontSize: '11px', color: 'var(--text-secondary)', paddingLeft: '20px' }}>
                                                            {selectedSubmission.stages.documentProcessing.discrepancies.map((d: string, i: number) => (
                                                                <li key={i} style={{ marginBottom: '2px' }}>{d}</li>
                                                            ))}
                                                        </ul>
                                                    </div>
                                                )}
                                            </div>
                                        </div>
                                    )}

                                    {selectedSubmission.stages?.screening && (
                                        <div className="flow-section" style={{ background: 'var(--bg-secondary)', padding: '15px', borderRadius: '8px', marginBottom: '20px' }}>
                                            <div className="section-title" style={{ marginBottom: '10px' }}>Screening Details</div>
                                            <div style={{ display: 'grid', gridTemplateColumns: '1fr', gap: '10px', fontSize: '12px' }}>
                                                {selectedSubmission.stages.screening.riskListScreening && (
                                                    <div style={{ marginBottom: '8px' }}>
                                                        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                                                            <span style={{ color: 'var(--text-muted)' }}>Risk List:</span>
                                                            <span className={`decision-badge ${selectedSubmission.stages.screening.riskListScreening.result || 'PENDING'}`}>
                                                                {selectedSubmission.stages.screening.riskListScreening.result || 'PENDING'}
                                                            </span>
                                                        </div>
                                                        {selectedSubmission.stages.screening.riskListScreening.summary && (
                                                            <div style={{ fontSize: '11px', marginTop: '4px', color: 'var(--text-secondary)' }}>{selectedSubmission.stages.screening.riskListScreening.summary}</div>
                                                        )}
                                                        {selectedSubmission.stages.screening.riskListScreening.pepStatus && (
                                                            <div style={{ fontSize: '10px', marginTop: '2px', color: 'var(--accent-blue)' }}>Status: {selectedSubmission.stages.screening.riskListScreening.pepStatus}</div>
                                                        )}
                                                    </div>
                                                )}
                                                {selectedSubmission.stages.screening.adverseMedia && (
                                                    <div style={{ marginTop: '5px', borderTop: '1px solid var(--border)', paddingTop: '5px' }}>
                                                        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                                                            <span style={{ color: 'var(--text-muted)' }}>Adverse Media:</span>
                                                            <span className={`decision-badge ${selectedSubmission.stages.screening.adverseMedia.result || 'PENDING'}`}>
                                                                {selectedSubmission.stages.screening.adverseMedia.result || 'PENDING'}
                                                            </span>
                                                        </div>
                                                        {selectedSubmission.stages.screening.adverseMedia.summary && (
                                                            <div style={{ fontSize: '11px', marginTop: '4px', color: 'var(--text-secondary)' }}>{selectedSubmission.stages.screening.adverseMedia.summary}</div>
                                                        )}
                                                    </div>
                                                )}
                                            </div>
                                        </div>
                                    )}

                                    <div className="flow-section" style={{ background: 'var(--bg-secondary)', padding: '15px', borderRadius: '8px', marginBottom: '20px' }}>
                                        <div className="section-title" style={{ marginBottom: '10px' }}>Extracted Details</div>
                                        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '10px', fontSize: '12px' }}>
                                            <div><span style={{ color: 'var(--text-muted)' }}>Passport:</span> {selectedSubmission.identity.passportNumber}</div>
                                            <div><span style={{ color: 'var(--text-muted)' }}>Expiry:</span> {selectedSubmission.identity.passportExpiry}</div>
                                            <div style={{ gridColumn: 'span 2' }}><span style={{ color: 'var(--text-muted)' }}>Address:</span> {selectedSubmission.identity.address}</div>
                                        </div>
                                    </div>

                                    <div style={{ marginTop: '20px' }}>
                                        {renderActionButtons(selectedSubmission)}
                                    </div>
                                </>
                            ) : (
                                <div style={{ textAlign: 'center', padding: '40px', color: 'var(--text-muted)' }}>Select a submission to view details</div>
                            )}
                        </div>
                    </div>
                </div>
            </div>

            <div className="toast-container">
                {toasts.map(toast => (
                    <div key={toast.id} className={`toast ${toast.type}`}>
                        <span className="toast-icon">
                            {toast.type === 'success' && '✓'}
                            {toast.type === 'error' && '✕'}
                            {toast.type === 'info' && 'ℹ'}
                        </span>
                        <span className="toast-message">{toast.message}</span>
                    </div>
                ))}
            </div>
        </div>
    );
};

export default Dashboard;
