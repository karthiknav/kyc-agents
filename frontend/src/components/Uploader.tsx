import React, { useState, useEffect, useRef } from 'react';
import { API_BASE_URL } from '../config.js';

type DocStatus = 'idle' | 'uploaded' | 'processing' | 'verified' | 'failed';

interface DocSection {
    id: string;
    name: string;
    requirement: string;
    status: DocStatus;
    fileName?: string;
    fileSize?: string;
    icon: string;
    iconClass: string;
}

interface UserDetails {
    fullName: string;
    address: string;
    passportNumber: string;
    passportExpiry: string;
    dateOfBirth: string;
    nationality: string;
}

interface UploaderProps {
    userId: string;
    initialStatus: string;
    initialSubmissionId: string | undefined;
}

const Uploader: React.FC<UploaderProps> = ({ userId, initialStatus, initialSubmissionId }) => {
    const [currentStep, setCurrentStep] = useState(1);
    const [docs, setDocs] = useState<DocSection[]>([
        { id: 'id', name: 'Government-Issued ID', requirement: "Passport, National ID, or Driver's License", status: 'idle', icon: '🪪', iconClass: 'id' },
        { id: 'address', name: 'Proof of Address', requirement: 'Utility bill, bank statement (< 3 months)', status: 'idle', icon: '🏠', iconClass: 'address' },
        { id: 'income', name: 'Proof of Income', requirement: 'Salary slips, tax return', status: 'idle', icon: '💰', iconClass: 'income' }
    ]);

    const [userDetails, setUserDetails] = useState<UserDetails>({
        fullName: '',
        address: '',
        passportNumber: '',
        passportExpiry: '',
        dateOfBirth: '1990-01-01',
        nationality: 'NL'
    });

    const [isSubmitting, setIsSubmitting] = useState(false);
    const [submissionError, setSubmissionError] = useState<string | null>(null);
    const [hasSubmitted, setHasSubmitted] = useState(false);
    const [progress, setProgress] = useState(0);
    const [dragActive, setDragActive] = useState<Record<string, boolean>>({});
    const fileInputRefs = useRef<Record<string, HTMLInputElement | null>>({});
    const uploadedFiles = useRef<Record<string, File>>({});
    const [submissionStages, setSubmissionStages] = useState<any>(null);
    const [caseStatus, setCaseStatus] = useState<string>(initialStatus);
    const [caseId, setCaseId] = useState<string | undefined>(initialSubmissionId);
    const pollingInterval = useRef<any>(null);
    const [toasts, setToasts] = useState<{ id: string; message: string; type: 'success' | 'error' | 'info' }[]>([]);

    const showToast = (message: string, type: 'success' | 'error' | 'info' = 'info') => {
        const id = Math.random().toString(36).substring(2, 9);
        setToasts(prev => [...prev, { id, message, type }]);
        setTimeout(() => {
            setToasts(prev => prev.filter(t => t.id !== id));
        }, 4000);
    };

    const selectedSubmissionStageStatus = (stage: any) => {
        return stage?.result || stage?.status || 'PENDING';
    };

    const isScreeningComplete = (screening: any, stage?: 'adverseMedia' | 'riskListScreening'): boolean => {
        if (!screening) return false;

        const isResultComplete = (res: any) => {
            if (!res || typeof res !== 'string') return false;
            const r = res.toUpperCase();
            return r !== 'PENDING' && r !== 'WAITING' && r !== 'INITIATED' && r !== 'PROCESSING' && r !== 'UNKNOWN';
        };

        if (stage) {
            const sub = screening[stage];
            return isResultComplete(sub?.result) || sub?.status === 'SUCCESS' || sub?.status === 'COMPLETED';
        }

        if (screening.adverseMedia && screening.riskListScreening) {
            return isScreeningComplete(screening, 'adverseMedia') && isScreeningComplete(screening, 'riskListScreening');
        }

        return screening.status === 'SUCCESS' || screening.status === 'COMPLETED' || isResultComplete(screening.result);
    };

    const fetchStatus = async () => {
        try {
            const response = await fetch(`${API_BASE_URL}/submission/${userId}`);
            if (response.ok) {
                const data = await response.json();
                setCaseStatus(data.status);
                setSubmissionStages(data.stages);
                if (data.caseId) setCaseId(data.caseId);

                if (data.status === 'APPROVED' || data.status === 'REJECTED') {
                    if (pollingInterval.current) {
                        clearInterval(pollingInterval.current);
                        pollingInterval.current = null;
                    }
                }
            }
        } catch (error) {
            console.error('Error fetching status:', error);
        }
    };

    useEffect(() => {
        if (currentStep === 3 && caseStatus !== 'APPROVED' && caseStatus !== 'REJECTED') {
            fetchStatus(); // Initial fetch
            pollingInterval.current = setInterval(fetchStatus, 5000);
        } else if (pollingInterval.current) {
            clearInterval(pollingInterval.current);
            pollingInterval.current = null;
        }

        return () => {
            if (pollingInterval.current) {
                clearInterval(pollingInterval.current);
            }
        };
    }, [currentStep, caseStatus]);

    const handleFile = (id: string, file: File) => {
        // Validation: Types — check extension OR MIME type (handles files with no extension, pasted images, phone photos)
        const allowedExtensions = ['jpg', 'jpeg', 'png', 'pdf', 'webp', 'heic', 'heif', 'bmp', 'tiff', 'tif'];
        const allowedMimeTypes = ['image/jpeg', 'image/png', 'image/webp', 'image/heic', 'image/heif', 'image/bmp', 'image/tiff', 'application/pdf'];
        const fileExtension = file.name.split('.').pop()?.toLowerCase();
        const isValidExtension = !!fileExtension && allowedExtensions.includes(fileExtension);
        const isValidMime = allowedMimeTypes.includes(file.type) || file.type.startsWith('image/');

        if (!isValidExtension && !isValidMime) {
            showToast(`Invalid file type${fileExtension ? ` (.${fileExtension})` : ''}. Please upload JPG, PNG, PDF, WEBP, or HEIC.`, 'error');
            return;
        }

        // Validation: Size (10MB)
        const MAX_SIZE_BYTES = 10 * 1024 * 1024;
        if (file.size > MAX_SIZE_BYTES) {
            showToast(`File too large: ${(file.size / (1024 * 1024)).toFixed(1)} MB. Max size is 10 MB.`, 'error');
            return;
        }

        const sizeInMB = (file.size / (1024 * 1024)).toFixed(1);
        uploadedFiles.current[id] = file;
        setDocs(prev => prev.map(doc => {
            if (doc.id === id) {
                return {
                    ...doc,
                    status: 'uploaded',
                    fileName: file.name,
                    fileSize: `${sizeInMB} MB`
                };
            }
            return doc;
        }));
    };

    const onDrag = (e: React.DragEvent, id: string, active: boolean) => {
        e.preventDefault();
        e.stopPropagation();
        setDragActive(prev => ({ ...prev, [id]: active }));
    };

    const onDrop = (e: React.DragEvent, id: string) => {
        e.preventDefault();
        e.stopPropagation();
        setDragActive(prev => ({ ...prev, [id]: false }));

        if (e.dataTransfer.files && e.dataTransfer.files[0]) {
            handleFile(id, e.dataTransfer.files[0]);
        }
    };

    const handleUploadClick = (id: string) => {
        fileInputRefs.current[id]?.click();
    };

    const handleFileInputChange = (e: React.ChangeEvent<HTMLInputElement>, id: string) => {
        if (e.target.files && e.target.files[0]) {
            handleFile(id, e.target.files[0]);
            e.target.value = ''; // reset so same file can be re-selected after Replace
        }
    };


    const handleSubmit = async () => {
        setIsSubmitting(true);
        setSubmissionError(null);
        setHasSubmitted(true);
        setCurrentStep(3); // Move to verification step

        const formData = new FormData();
        formData.append('userId', userId);
        formData.append('fullName', userDetails.fullName);
        formData.append('address', userDetails.address);
        formData.append('passportNumber', userDetails.passportNumber);
        formData.append('passportExpiry', userDetails.passportExpiry);
        formData.append('dateOfBirth', userDetails.dateOfBirth);
        formData.append('nationality', userDetails.nationality);

        formData.append('id_file', uploadedFiles.current['id'] as Blob);
        formData.append('address_file', uploadedFiles.current['address'] as Blob);
        if (uploadedFiles.current['income']) {
            formData.append('income_file', uploadedFiles.current['income'] as Blob);
        }

        // Simulate processing states visually while waiting for server
        setDocs(prev => prev.map(doc => ({ ...doc, status: 'processing' })));

        try {
            const response = await fetch(`${API_BASE_URL}/submit-kyc`, {
                method: 'POST',
                body: formData,
            });

            const result = await response.json().catch(() => ({}));

            if (!response.ok) {
                const message = (result?.detail ?? result?.message ?? 'Submission failed') as string;
                throw new Error(message);
            }

            console.log('Submission success:', result);
            setIsSubmitting(false);

        } catch (error) {
            console.error('Submission failed:', error);
            setSubmissionError(error instanceof Error ? error.message : 'Submission failed');
            setDocs(prev => prev.map(doc => ({ ...doc, status: 'failed' })));
            setIsSubmitting(false);
        }
    };

    const statusCounts = {
        verified: docs.filter(d => d.status === 'verified').length,
        total: docs.length,
        uploaded: docs.filter(d => d.status !== 'idle').length
    };

    const requiredDocs = ['id', 'address'];
    const allUploaded = requiredDocs.every(id => docs.find(d => d.id === id)?.status !== 'idle');
    const detailsFilled = userDetails.fullName && userDetails.address && userDetails.passportNumber && userDetails.passportExpiry;

    useEffect(() => {
        setProgress(Math.round((statusCounts.verified / statusCounts.total) * 100));
    }, [statusCounts.verified]);

    useEffect(() => {
        if (initialStatus !== 'not_started') {
            setCurrentStep(3);
            setHasSubmitted(true);
            setCaseStatus(initialStatus);
            // If it was already verified, we update the docs state
            if (initialStatus === 'APPROVED' || initialStatus === 'verified') {
                setDocs(prev => prev.map(doc => ({ ...doc, status: 'verified' })));
            } else if (initialStatus === 'PROCESSING' || initialStatus === 'pending') {
                setDocs(prev => prev.map(doc => ({ ...doc, status: 'processing' })));
            }
        }
    }, [initialStatus]);

    const steps = [
        { label: 'Personal Info', id: 1 },
        { label: 'Documents', id: 2 },
        { label: 'Verification', id: 3 },
    ];

    return (
        <div className="app-view active">
            <div className="uploader-content">
                <div className="uploader-header">
                    <h1>KYC Document Submission</h1>
                    <p>Follow the steps to complete your identity verification. Our AI agent will process your submission securely.</p>
                </div>

                {/* Main Progress Indicator */}
                <div className="steps">
                    {steps.map((step, idx) => (
                        <React.Fragment key={step.id}>
                            <div className={`step-item ${currentStep === step.id ? 'active' : ''} ${currentStep > step.id ? 'done' : ''}`}>
                                <div className="step-num">{currentStep > step.id ? '✓' : step.id}</div>
                                <div className="step-label">{step.label}</div>
                            </div>
                            {idx < steps.length - 1 && (
                                <div className={`step-line ${currentStep > step.id ? 'done' : ''}`}></div>
                            )}
                        </React.Fragment>
                    ))}
                </div>

                {/* Step 1: User Details */}
                {currentStep === 1 && (
                    <div className="user-details-form" style={{ padding: '32px', background: 'var(--bg-card)', borderRadius: 'var(--radius)', border: '1px solid var(--border)' }}>
                        <h3 style={{ marginBottom: '24px', fontSize: '18px', display: 'flex', alignItems: 'center', gap: '10px' }}>
                            <span style={{ color: 'var(--accent-blue)' }}>Step 1:</span> Personal Profile
                        </h3>
                        <div className="form-group">
                            <label>Full Name</label>
                            <input
                                type="text"
                                className="form-input"
                                placeholder="John Doe"
                                value={userDetails.fullName}
                                onChange={(e) => setUserDetails({ ...userDetails, fullName: e.target.value })}
                            />
                        </div>
                        <div className="form-group">
                            <label>Residential Address</label>
                            <input
                                type="text"
                                className="form-input"
                                placeholder="123 Main St, City, Country"
                                value={userDetails.address}
                                onChange={(e) => setUserDetails({ ...userDetails, address: e.target.value })}
                            />
                        </div>
                        <div className="form-row" style={{ gap: '16px', marginBottom: '16px' }}>
                            <div className="form-group" style={{ flex: 1, marginBottom: 0 }}>
                                <label>Date of Birth</label>
                                <input
                                    type="date"
                                    className="form-input"
                                    value={userDetails.dateOfBirth}
                                    onChange={(e) => setUserDetails({ ...userDetails, dateOfBirth: e.target.value })}
                                />
                            </div>
                            <div className="form-group" style={{ flex: 1, marginBottom: 0 }}>
                                <label>Nationality</label>
                                <input
                                    type="text"
                                    className="form-input"
                                    placeholder="NL"
                                    value={userDetails.nationality}
                                    onChange={(e) => setUserDetails({ ...userDetails, nationality: e.target.value })}
                                />
                            </div>
                        </div>
                        <div className="form-row" style={{ gap: '16px', marginBottom: 0 }}>
                            <div className="form-group" style={{ flex: 2, marginBottom: 0 }}>
                                <label>Passport / ID Number</label>
                                <input
                                    type="text"
                                    className="form-input"
                                    placeholder="A12345678"
                                    value={userDetails.passportNumber}
                                    onChange={(e) => setUserDetails({ ...userDetails, passportNumber: e.target.value })}
                                />
                            </div>
                            <div className="form-group" style={{ flex: 1, marginBottom: 0 }}>
                                <label>Expiry Date</label>
                                <input
                                    type="date"
                                    className="form-input"
                                    value={userDetails.passportExpiry}
                                    onChange={(e) => setUserDetails({ ...userDetails, passportExpiry: e.target.value })}
                                />
                            </div>
                        </div>
                        <div style={{ marginTop: '32px', display: 'flex', justifyContent: 'flex-end' }}>
                            <button
                                className="login-btn"
                                style={{ maxWidth: '200px', opacity: detailsFilled ? 1 : 0.5 }}
                                disabled={!detailsFilled}
                                onClick={() => setCurrentStep(2)}
                            >
                                Next: Documents →
                            </button>
                        </div>
                    </div>
                )}

                {/* Step 2: Document Uploads */}
                {currentStep === 2 && (
                    <div className="upload-section">
                        <div className="section-header" style={{ marginBottom: '20px', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                            <h3 style={{ fontSize: '18px' }}>
                                <span style={{ color: 'var(--accent-blue)' }}>Step 2:</span> Identity Documents
                            </h3>
                            <button className="sso-btn" style={{ width: 'auto', padding: '6px 12px' }} onClick={() => setCurrentStep(1)}>
                                ← Edit Info
                            </button>
                        </div>
                        <div className="upload-grid">
                            {docs.map(doc => (
                                <div key={doc.id} className="upload-card">
                                    <div className="upload-card-header">
                                        <div className="left">
                                            <div className={`doc-icon ${doc.iconClass}`}>{doc.icon}</div>
                                            <div>
                                                <div className="doc-name">
                                                    {doc.name}
                                                    {!requiredDocs.includes(doc.id) && (
                                                        <span style={{ marginLeft: '8px', fontSize: '11px', fontWeight: 500, padding: '2px 6px', borderRadius: '4px', background: 'var(--bg-secondary)', color: 'var(--text-muted)', verticalAlign: 'middle' }}>Optional</span>
                                                    )}
                                                </div>
                                                <div className="doc-req">{doc.requirement}</div>
                                            </div>
                                        </div>
                                        {doc.status === 'verified' && <span className="status-chip verified">✓ Verified</span>}
                                        {doc.status === 'processing' && <span className="status-chip processing">⟳ Processing</span>}
                                        {doc.status === 'failed' && <span className="status-chip failed">✕ Re-upload</span>}
                                        {doc.status === 'uploaded' && <span className="status-chip" style={{ background: 'var(--accent-blue-dim)', color: 'var(--accent-blue)' }}>Ready</span>}
                                        {doc.status === 'idle' && !requiredDocs.includes(doc.id) && <span className="status-chip" style={{ background: 'var(--bg-secondary)', color: 'var(--text-muted)' }}>○ Skip</span>}
                                        {doc.status === 'idle' && requiredDocs.includes(doc.id) && <span className="status-chip pending">○ Pending</span>}
                                    </div>

                                    {doc.status === 'idle' ? (
                                        <div
                                            className={`upload-zone ${dragActive[doc.id] ? 'dragging' : ''}`}
                                            onDragEnter={(e) => onDrag(e, doc.id, true)}
                                            onDragLeave={(e) => onDrag(e, doc.id, false)}
                                            onDragOver={(e) => onDrag(e, doc.id, true)}
                                            onDrop={(e) => onDrop(e, doc.id)}
                                            onClick={() => handleUploadClick(doc.id)}
                                        >
                                            <input
                                                type="file"
                                                ref={el => { fileInputRefs.current[doc.id] = el; }}
                                                style={{ display: 'none' }}
                                                onChange={(e) => handleFileInputChange(e, doc.id)}
                                                accept=".pdf,.jpg,.jpeg,.png,.webp,.heic,.heif,.bmp,.tiff,.tif,image/*"
                                            />
                                            <div style={{ flex: 1, textAlign: 'center' }}>
                                                <div className="icon">⬆️</div>
                                                <div className="text">Drag & drop or click</div>
                                                <div style={{ fontSize: '11px', color: 'var(--text-muted)', marginTop: '6px' }}>JPG, PNG, PDF, WEBP, HEIC · Max 10 MB</div>
                                            </div>
                                        </div>
                                    ) : (
                                        <>
                                            <div className="file-preview">
                                                <div className="file-icon">📄</div>
                                                <div className="file-info">
                                                    <div className="file-name">{doc.fileName}</div>
                                                    <div className="file-size">{doc.status === 'failed' ? 'Failed' : doc.fileSize}</div>
                                                </div>
                                                <div className="file-actions">
                                                    <button onClick={() => setDocs(prev => prev.map(d => d.id === doc.id ? { ...d, status: 'idle' } : d))}>
                                                        Replace
                                                    </button>
                                                </div>
                                            </div>
                                        </>
                                    )}
                                </div>
                            ))}
                        </div>
                        <div style={{ textAlign: 'center', marginTop: '32px' }}>
                            <button
                                className="login-btn"
                                style={{
                                    maxWidth: '300px',
                                    opacity: allUploaded ? 1 : 0.5,
                                    cursor: allUploaded ? 'pointer' : 'not-allowed'
                                }}
                                onClick={handleSubmit}
                                disabled={!allUploaded}
                            >
                                {allUploaded ? 'Submit for Verification' : `Upload Required Documents (${docs.filter(d => requiredDocs.includes(d.id) && d.status !== 'idle').length}/${requiredDocs.length})`}
                            </button>
                        </div>
                    </div>
                )}

                {/* Step 3: Verification */}
                {currentStep === 3 && (
                    <div className="overall-status" style={{ padding: '40px', background: 'var(--bg-card)', borderRadius: 'var(--radius)', border: '1px solid var(--border)' }}>
                        {caseStatus === 'APPROVED' ? (
                            <>
                                <div className="big-icon">✅</div>
                                <h3>Identity Verified Successfully</h3>
                                <p>Thank you, {userDetails.fullName}. Your KYC application has been approved.</p>
                                <div className="upload-grid" style={{ marginTop: '30px', textAlign: 'left' }}>
                                    <div className="upload-card" style={{ borderLeft: '4px solid var(--accent-green)' }}>
                                        <div className="upload-card-header" style={{ marginBottom: 0 }}>
                                            <div className="left">
                                                <div className="doc-icon verified">🪪</div>
                                                <div>
                                                    <div className="doc-name">Document Verification</div>
                                                    <div className="doc-req">Completed successfully</div>
                                                </div>
                                            </div>
                                            <span className="status-chip verified">✓ Success</span>
                                        </div>
                                    </div>
                                    <div className="upload-card" style={{ borderLeft: '4px solid var(--accent-green)' }}>
                                        <div className="upload-card-header" style={{ marginBottom: 0 }}>
                                            <div className="left">
                                                <div className="doc-icon verified">🔎</div>
                                                <div>
                                                    <div className="doc-name">Adverse Media Screening</div>
                                                    <div className="doc-req">No adverse findings found</div>
                                                </div>
                                            </div>
                                            <span className="status-chip verified">✓ Success</span>
                                        </div>
                                    </div>
                                    <div className="upload-card" style={{ borderLeft: '4px solid var(--accent-green)' }}>
                                        <div className="upload-card-header" style={{ marginBottom: 0 }}>
                                            <div className="left">
                                                <div className="doc-icon verified">🛡️</div>
                                                <div>
                                                    <div className="doc-name">Risk List Screening</div>
                                                    <div className="doc-req">No matches in global watchlists</div>
                                                </div>
                                            </div>
                                            <span className="status-chip verified">✓ Success</span>
                                        </div>
                                    </div>
                                </div>
                            </>
                        ) : caseStatus === 'REJECTED' ? (
                            <>
                                <div className="big-icon">❌</div>
                                <h3>Verification Rejected</h3>
                                <p>We're sorry, but your KYC application could not be approved at this time.</p>
                            </>
                        ) : (
                            <>
                                <div className="big-icon">{isSubmitting ? '🤖' : '⏳'}</div>
                                <h3>{isSubmitting ? 'AI Agents are Working' : 'Verification In Progress'}</h3>
                                <p>We are running automated checks on your submission. This usually takes less than a minute.</p>

                                <div className="upload-grid" style={{ marginTop: '30px', textAlign: 'left' }}>
                                    {/* Document Verification Stage */}
                                    <div className="upload-card" style={{ borderLeft: `4px solid ${selectedSubmissionStageStatus(submissionStages?.documentProcessing) === 'MATCH' ? 'var(--accent-green)' : submissionStages?.documentProcessing ? 'var(--accent-blue)' : 'var(--border)'}` }}>
                                        <div className="upload-card-header" style={{ marginBottom: 0 }}>
                                            <div className="left">
                                                <div className={`doc-icon ${selectedSubmissionStageStatus(submissionStages?.documentProcessing) === 'MATCH' ? 'verified' : submissionStages?.documentProcessing ? 'processing' : ''}`}>🪪</div>
                                                <div>
                                                    <div className="doc-name">Document Verification</div>
                                                    <div className="doc-req">Analyzing ID authenticity and OCR extraction</div>
                                                </div>
                                            </div>
                                            {selectedSubmissionStageStatus(submissionStages?.documentProcessing) === 'MATCH' ? (
                                                <span className="status-chip verified">✓ Completed</span>
                                            ) : selectedSubmissionStageStatus(submissionStages?.documentProcessing) === 'PARTIAL_MATCH' ? (
                                                <span className="status-chip" style={{ background: 'var(--accent-orange-dim)', color: 'var(--accent-orange)' }}>⚠️ Partial Match</span>
                                            ) : submissionStages?.documentProcessing ? (
                                                <span className="status-chip processing">⟳ In Progress</span>
                                            ) : (
                                                <span className="status-chip pending">○ Waiting</span>
                                            )}
                                        </div>
                                    </div>

                                    {/* Adverse Media Stage */}
                                    <div className="upload-card" style={{ borderLeft: `4px solid ${isScreeningComplete(submissionStages?.screening, 'adverseMedia') ? 'var(--accent-green)' : submissionStages?.documentProcessing ? 'var(--accent-blue)' : 'var(--border)'}` }}>
                                        <div className="upload-card-header" style={{ marginBottom: 0 }}>
                                            <div className="left">
                                                <div className={`doc-icon ${isScreeningComplete(submissionStages?.screening, 'adverseMedia') ? 'verified' : submissionStages?.documentProcessing ? 'processing' : ''}`}>🔎</div>
                                                <div>
                                                    <div className="doc-name">Adverse Media Screening</div>
                                                    <div className="doc-req">Checking global news and media for reputational risk</div>
                                                </div>
                                            </div>
                                            {isScreeningComplete(submissionStages?.screening, 'adverseMedia') ? (
                                                submissionStages?.screening?.result?.toUpperCase() === 'SUCCESS' ? (
                                                    <span className="status-chip verified">✓ Success</span>
                                                ) : (
                                                    <span className="status-chip verified">✓ Completed</span>
                                                )
                                            ) : submissionStages?.documentProcessing ? (
                                                <span className="status-chip processing">⟳ In Progress</span>
                                            ) : (
                                                <span className="status-chip pending">○ Waiting</span>
                                            )}
                                        </div>
                                    </div>

                                    {/* Risk List Screening Stage */}
                                    <div className="upload-card" style={{ borderLeft: `4px solid ${isScreeningComplete(submissionStages?.screening, 'riskListScreening') ? 'var(--accent-green)' : isScreeningComplete(submissionStages?.screening, 'adverseMedia') ? 'var(--accent-blue)' : 'var(--border)'}` }}>
                                        <div className="upload-card-header" style={{ marginBottom: 0 }}>
                                            <div className="left">
                                                <div className={`doc-icon ${isScreeningComplete(submissionStages?.screening, 'riskListScreening') ? 'verified' : isScreeningComplete(submissionStages?.screening, 'adverseMedia') ? 'processing' : ''}`}>🛡️</div>
                                                <div>
                                                    <div className="doc-name">Risk List Screening</div>
                                                    <div className="doc-req">Cross-referencing against global sanctions and PEP lists</div>
                                                </div>
                                            </div>
                                            {isScreeningComplete(submissionStages?.screening, 'riskListScreening') ? (
                                                submissionStages?.screening?.result?.toUpperCase() === 'SUCCESS' ? (
                                                    <span className="status-chip verified">✓ Success</span>
                                                ) : (
                                                    <span className="status-chip verified">✓ Completed</span>
                                                )
                                            ) : isScreeningComplete(submissionStages?.screening, 'adverseMedia') ? (
                                                <span className="status-chip processing">⟳ In Progress</span>
                                            ) : (
                                                <span className="status-chip pending">○ Waiting</span>
                                            )}
                                        </div>
                                    </div>
                                </div>

                                <div className="processing-bar" style={{ maxWidth: '100%', margin: '40px 0 20px' }}>
                                    <div className="fill" style={{
                                        width: isScreeningComplete(submissionStages?.screening) ? '100%' :
                                            isScreeningComplete(submissionStages?.screening, 'adverseMedia') ? '75%' :
                                                submissionStages?.documentProcessing ? '50%' : '25%',
                                        background: 'var(--accent-blue)',
                                        transition: 'width 1s ease-in-out'
                                    }}></div>
                                </div>

                                <div className="upload-grid" style={{ marginTop: '30px', textAlign: 'left' }}>
                                    {docs.map(doc => (
                                        doc.status === 'failed' && (
                                            <div key={doc.id} className="ai-result" style={{ borderLeftColor: 'var(--accent-red)' }}>
                                                <div className="ai-label" style={{ color: 'var(--accent-red)' }}>🤖 Needs Attention: {doc.name}</div>
                                                <div className="check-item"><span className="fail">✕</span> {submissionError ?? 'Submission failed. Please retry or check your documents.'}</div>
                                                <button
                                                    className="sso-btn"
                                                    style={{ marginTop: '10px', width: 'auto' }}
                                                    onClick={() => { setSubmissionError(null); setCurrentStep(2); setDocs(prev => prev.map(d => d.id === doc.id ? { ...d, status: 'idle' } : d)); }}
                                                >
                                                    Retry Upload
                                                </button>
                                            </div>
                                        )
                                    ))}
                                </div>
                            </>
                        )}
                        <div className="ref-id" style={{ marginTop: '30px' }}>CASE ID: {caseId || `PENDING`}</div>
                    </div>
                )}
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

export default Uploader;
