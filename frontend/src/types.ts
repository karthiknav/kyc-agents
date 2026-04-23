export type Role = 'uploader' | 'analyst';

export interface S3Location {
    bucket: string;
    key: string;
}

export interface BaseStage {
    result: string;
    summary: string;
    updatedAt: string;
    reportS3?: S3Location;
}

export interface DocumentProcessingStage extends BaseStage {
    discrepancies?: string[];
    governmentVerificationSummary?: string;
}

export interface ScreeningSubStage extends BaseStage {
    rawResponseS3?: S3Location;
}

export interface AdverseMediaResult extends ScreeningSubStage {
    searchQueries?: string[];
}

export interface RiskListResult extends ScreeningSubStage {
    datasetsMatched?: string[];
    pepStatus?: string;
    sanctionsStatus?: string;
}

export interface ScreeningStage {
    adverseMedia?: AdverseMediaResult;
    riskListScreening?: RiskListResult;
    // Legacy support for older items
    status?: string;
    result?: string;
    summary?: string;
}

export interface OrchestratorStage {
    status: string;
    decision: string;
    reason: string[];
    recommendation_summary: string;
    decidedAt: string;
    // Legacy support
    updatedAt?: string;
}

export interface OverrideReviewStage {
    verdict: 'APPROVED' | 'REJECTED';
    reasoning: string;
    riskFlagsEvaluated: string[];
    analystComments: string;
    reviewedAt: string;
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
        documentProcessing?: DocumentProcessingStage;
        screening?: ScreeningStage;
        orchestrator?: OrchestratorStage;
        overrideReview?: OverrideReviewStage;
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
        documentProcessing?: DocumentProcessingStage;
        screening?: ScreeningStage;
        orchestrator?: OrchestratorStage;
        overrideReview?: OverrideReviewStage;
    };
    document_urls: Record<string, string>;
    finalDecision: string;
}