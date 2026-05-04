import React, { useState } from 'react';

interface LoginProps {
    onLogin: (email: string, password: string) => Promise<boolean>;
}

const Login: React.FC<LoginProps> = ({ onLogin }) => {
    const [email, setEmail] = useState('');
    const [password, setPassword] = useState('');
    const [error, setError] = useState('');

    const handleSubmit = async (e: React.FormEvent) => {
        e.preventDefault();
        const success = await onLogin(email, password);
        if (!success) {
            setError('Invalid email or password');
        }
    };

    return (
        <div className="login-screen">
            <div className="login-left">
                <div className="login-brand">
                    <div className="logo-row">
                        <div className="logo-icon">K</div>
                        <div className="logo-text">KYC Agentic AI</div>
                    </div>
                    <div className="logo-sub">Powered by Cognizant AI Labs</div>
                </div>
                <div className="login-hero">
                    <h1>Intelligent KYC<br />powered by <span>Agentic AI</span></h1>
                    <p>Automate document verification, sanctions screening, PEP checks, and risk scoring with multi-agent orchestration. Reduce onboarding time by 70% while maintaining full DNB compliance.</p>
                </div>
                <div className="login-features">
                    <div className="login-feature">
                        <div className="feat-icon" style={{ background: 'var(--accent-blue-dim)' }}>🤖</div>
                        <div className="feat-text">
                            <h4>Multi-Agent Orchestration</h4>
                            <p>Strands agents handle verification, screening, and scoring</p>
                        </div>
                    </div>
                    <div className="login-feature">
                        <div className="feat-icon" style={{ background: 'var(--accent-green-dim)' }}>⚡</div>
                        <div className="feat-text">
                            <h4>4.2 min Avg Processing</h4>
                            <p>From upload to decision, fully automated</p>
                        </div>
                    </div>
                    <div className="login-feature">
                        <div className="feat-icon" style={{ background: 'var(--accent-purple-dim)' }}>🔒</div>
                        <div className="feat-text">
                            <h4>DNB Compliant</h4>
                            <p>Full audit trail and explainable reasoning</p>
                        </div>
                    </div>
                </div>
            </div>
            <div className="login-right">
                <div className="login-card">
                    <h2>Welcome back</h2>
                    <div className="login-sub">Sign in to access KYC platform</div>

                    <form onSubmit={handleSubmit}>
                        <div className="form-group">
                            <label>Email</label>
                            <input
                                type="email"
                                className="form-input"
                                placeholder="email@bank.nl"
                                value={email}
                                onChange={(e) => setEmail(e.target.value)}
                                required
                            />
                        </div>
                        <div className="form-group">
                            <label>Password</label>
                            <input
                                type="password"
                                className="form-input"
                                value={password}
                                onChange={(e) => setPassword(e.target.value)}
                                required
                            />
                        </div>

                        {error && <div style={{ color: 'var(--accent-red)', fontSize: '12px', marginBottom: '10px' }}>{error}</div>}

                        <div className="form-row">
                            <label className="remember">
                                <input type="checkbox" defaultChecked /> Remember me
                            </label>
                            <a href="#" className="forgot">Forgot password?</a>
                        </div>
                        <button type="submit" className="login-btn">Sign In</button>
                    </form>

                    <div className="login-divider">
                        <div className="line"></div>
                        <span>OR</span>
                        <div className="line"></div>
                    </div>
                    <button className="sso-btn">🔐 Sign in with Corporate SSO</button>
                    <div className="login-footer">
                        Protected by MFA · SOC 2 Compliant · DNB Regulated<br />
                        <span style={{ color: 'var(--accent-blue)', cursor: 'pointer' }}>Request access</span>
                    </div>
                </div>
            </div>
        </div>
    );
};

export default Login;
