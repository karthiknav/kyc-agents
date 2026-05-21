import React from 'react';
import type { Role } from '../types.js';

interface NavbarProps {
    role: Role;
    onLogout: () => void;
    currentView: string;
    onViewChange: (view: string) => void;
    escalationCount: number;
    variant?: 'app' | 'admin';
}

const Navbar: React.FC<NavbarProps> = ({ role, onLogout, currentView, onViewChange, escalationCount, variant = 'app' }) => {
    const isAnalyst = role === 'analyst';
    const isAdmin = variant === 'admin';
    const avatarText = isAnalyst ? 'SJ' : 'MV';
    const avatarBg = isAnalyst
        ? 'linear-gradient(135deg, #6366F1, #8B5CF6)'
        : 'linear-gradient(135deg, #10B981, #06B6D4)';

    return (
        <div className="role-switcher">
            <div className="logo">
                <div className="nav-logo-icon">K</div>
                <span>KYC Agentic AI</span>
            </div>
            {!isAdmin && (
                <div className="role-tabs">
                    {isAnalyst ? (
                        <>
                            <button
                                className={`role-tab ${currentView === 'dashboard' ? 'active' : ''}`}
                                onClick={() => onViewChange('dashboard')}
                            >
                                📊 Dashboard
                            </button>
                            <button
                                className={`role-tab ${currentView === 'escalation' ? 'active' : ''}`}
                                onClick={() => onViewChange('escalation')}
                            >
                                ⚠️ Escalations
                                <span style={{
                                    background: 'var(--accent-red)',
                                    color: 'white',
                                    borderRadius: '10px',
                                    padding: '1px 6px',
                                    fontSize: '10px',
                                    marginLeft: '4px'
                                }}>
                                    {escalationCount}
                                </span>
                            </button>
                        </>
                    ) : ''}
                </div>
            )}
            <div className="nav-right">
                <div className="nav-badge">{isAdmin ? 'Admin' : 'Strands Agent Active'}</div>
                {!isAdmin && isAnalyst && (
                    <div className="nav-notif" onClick={() => onViewChange('escalation')}>
                        🔔<div className="notif-count">{escalationCount}</div>
                    </div>
                )}
                <div
                    className="nav-avatar"
                    style={{ background: avatarBg }}
                >
                    {avatarText}
                </div>
                <button className="logout-btn" onClick={onLogout}>Sign Out</button>
            </div>
        </div>
    );
};

export default Navbar;
