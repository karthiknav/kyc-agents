export type Role = 'uploader' | 'analyst';

export interface VerificationStage {
    status: string;
    startedAt: string;
    updatedAt: string;
    detailsS3: { bucket: string; key: string };
    error: string | null;
    version: number;
    matchesFound?: string[];
}

export interface User {
    user_id: string;
    email: string;
    role: Role;
    status: string;
    caseId?: string;
    identity?: {
        fullName: string;
        dateOfBirth: string;
        nationality: string;
        address: string;
        passportNumber: string;
        passportExpiry: string;
    };
    kyc_logs?: Array<{ time: string; event: string; agent: string }>;
    document_urls?: Record<string, string>;
    stages?: {
        documentVerification: VerificationStage;
        personScreening: VerificationStage;
    };
    finalDecision?: string;
}

export interface KycSubmission {
    caseId: string;
    user_id: string;
    createdAt: string;
    createdBy: string;
    status: string;
    statusUpdatedAt: string;
    identity: {
        fullName: string;
        dateOfBirth: string;
        nationality: string;
        address: string;
        passportNumber: string;
        passportExpiry: string;
    };
    stages: {
        documentVerification: VerificationStage;
        personScreening: VerificationStage;
    };
    document_urls: Record<string, string>;
    finalDecision: string;
}
